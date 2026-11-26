import asyncio, json, inspect, re, time, uuid, os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from pydantic import BaseModel, PrivateAttr
from typing import Optional, Any
from cycls._app.auth import User, validator
from cycls._app.db import Workspace, workspace
from cycls._agent.logs import log
from cycls._agent import activity, inbox, routines, state, webpush
from cycls._agent.harness.llm import warm_up
from cycls._agent.web import voice


BRAND_TTL = 300   # how long a container serves the brand it last read from the CMS
_HEAD = re.compile(r'__TITLE__|__DESC__|content="/og\.png"')   # what the page's head says, filled per request

class PassMetadata(BaseModel):
    name: str
    description: str = ""
    logo: str = ""       # agent icon — chat hero
    brand: str = ""      # brand wordmark — nav bar (falls back to Cycls logo)

class Config(BaseModel):
    public_path: str = "theme"
    name: Optional[str] = None
    pass_metadata: Optional[dict[str, PassMetadata]] = None
    title: Optional[str] = None
    prod: bool = False
    auth: bool = False
    cms: Optional[dict] = None        # {brand: url, explore: url, token: bearer} — plain GETs, contract JSON
    analytics: Optional[list] = None  # analytics plugins: [{provider, ...}] — one event pipe, fanned out client-side
    notifications: Optional[list] = None  # push plugins: [{provider, app_id}] — the FE owns the prompt UI
    routines: Optional[list] = None   # Web.routines: on, with these examples (docs/rfc-routines.md)
    suggestions: bool = False
    voice: bool = False                # the mic shows: set from `transcription` as the server starts
    transcription: Optional[Any] = None  # Web.voice: {model, base_url, api_key, headers}, or False; server-side
    pk: Optional[str] = None
    one_tap: bool = False             # Google One Tap on the signed-out page
    affiliate: Optional[str] = None   # affiliate/referral provider key (e.g. Rewardful)
    mobile_app: Optional[dict] = None # {ios, android} store links — the phone banner
    plans: Optional[dict] = None      # the plans window: {pay, currency, words} (Web.plans)
    max_upload: int = 512             # per-file upload cap in MB
    workspaces: Optional[str] = None  # multi-workspace mode: None off, else team-create policy ("member"|"admin")
    volume: str = "/workspace"
    seo: Optional[dict] = None        # {title, description} — page copy overriding the brand
    head: Optional[str] = None        # raw HTML appended to <head> (verification tags etc.)
    favicon: Optional[str] = None     # inline <svg>, data URI, or URL
    og: Optional[str] = None          # og:image URL when external; custom bytes ride _og_image
    accent: Optional[str] = None      # the agent's colour, the glow on the cards it draws: .brand()'s, else the CMS's
    explore: Optional[list] = None    # static explore menu (contract-shaped entries)
    explore_enabled: bool = False     # FE shows the agents dropdown
    examples: Optional[list] = None   # [{label, label_ar, urls}] — resolved at GET /examples
    examples_enabled: bool = False    # FE shows the example gallery on the empty screen
    colors: Optional[dict] = None     # {primary, secondary, primary_dark, secondary_dark}
    _og_image: Optional[bytes] = PrivateAttr(default=None)  # custom og card, served at /og.png
    _fonts: list = PrivateAttr(default_factory=list)        # .brand(fonts=)'s files, for the cards it draws

    def set_prod(self, prod: bool):
        self.prod = prod

    def public(self):
        """Config as sent to the browser — cms (bearer token), volume
        (internal mount path), the raw examples mapping (the FE reads the
        resolved cards from /examples) and the voice model and its key stay
        server-side."""
        data = self.model_dump(exclude={"cms", "volume", "examples", "transcription"})
        # the .fig editor, a static app on its own origin; unset → .fig shows the download card
        if url := os.environ.get("DESIGN_EDITOR_URL"):
            data["design_editor_url"] = url
        # The video editor runs on the video service (VIDEO_EDITOR_URL); whether an organisation has
        # Video at all is answered per workspace by POST /video/editor.
        if os.environ.get("VIDEO_EDITOR_URL") and os.environ.get("VIDEO_URL"):
            data["video_editor"] = True
        # Cycls Sheets, on the cycls-office service; whether an organisation has it is answered per
        # workspace by GET /office/sheets.
        from cycls._agent.office import client as _office
        if _office.configured() and _office.editor_url():
            data["sheets_editor"] = True
        # The microphone hears first on the cycls-transcribe service: the browser warms a listener as
        # it starts recording (POST /transcribe/warm), so a cold GPU starts while the person speaks.
        # (ElevenLabs, the other engine, has nothing to warm.)
        from cycls._agent.transcribe import engine as _transcribe_engine
        if _transcribe_engine() == "cycls":
            data["voice_warm"] = True
        return data

    @property
    def storage(self) -> str:
        if self.prod and self.name:
            bucket = json.loads(os.environ.get("CYCLS_VOLUMES") or "{}").get("/workspace")
            if bucket:
                return f"gs://{bucket}"
            raise RuntimeError(
                "No volume mounted at /workspace — agent state needs one. "
                "Declare volumes={'/workspace': cycls.Volume(...)} on the decorator.")
        return f"file://{self.volume}"

async def _aiter(stream):
    """Unify sync + async streams as a single async iterator."""
    if inspect.isasyncgen(stream):
        async for x in stream: yield x
    else:
        for x in stream: yield x

async def openai_encoder(stream):
    try:
        async for msg in _aiter(stream):
            if msg: yield f"data: {json.dumps({'choices': [{'delta': {'content': msg}}]})}\n\n"
    except Exception as e:
        note = f"\n\n[stream failed: {e}]"
        yield f"data: {json.dumps({'choices': [{'delta': {'content': note}}]})}\n\n"
    yield "data: [DONE]\n\n"

def sse(item):
    if not item: return None
    if not isinstance(item, dict): item = {"type": "text", "text": item}
    return f"data: {json.dumps(item)}\n\n"

RUN_BUDGET = 45 * 60   # a run cannot outlive this
RUN_DRAIN = 5          # how long a cancelled run gets to unwind
RUN_BEAT = 10          # heartbeat interval; state.RUN_STALE is the reader's patience
RUN_FILES = 5          # how long the run's end waits on recording what it changed (the rest finishes after)
QUEUE_MAX = 512        # events buffered for a reader; a view, not a log
_DONE, _LAGGED = object(), object()
_OWNER = f"{os.environ.get('K_REVISION', 'local')}/{uuid.uuid4().hex[:8]}"


class Run:
    """One agent run. Two tasks on purpose: `task` supervises and is never
    cancelled by us, so it always lives to stamp the record and release the slot;
    `inner` drives the loop and is the only thing stop, budget, disconnect and
    shutdown cancel."""

    def __init__(self, *, detach, workspace=None, chat_id=None, user=None, agent=None, origin=None):
        self.queue = asyncio.Queue(QUEUE_MAX)
        self.detach, self.attached, self.reason = detach, True, None
        self.failed = False   # the encoder handles the error itself
        self.error_id = None  # the reference the person was shown, and the key to the error log
        # Stop's `take_back`: the sha256 of the prompt the person has back in their composer, which
        # the run drops as it ends if it kept nothing after it; `taken_back` says whether it did.
        self.take_back, self.taken_back = None, False
        self.task = self.inner = None
        self.workspace, self.chat_id, self.user = workspace, chat_id, user
        self.id, self.started = uuid.uuid4().hex, time.monotonic()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.agent, self.stepped, self.before = agent, False, None
        self.origin, self.waiting = origin, None   # where the app is, for a push; the card it last asked with
        self.routine = None   # a routine's run: its end goes on the routine's record, not to its owner's bell

    def row(self, status):
        return {"run": self.id, "status": status, "owner": _OWNER,
                "started": self.started_at,
                "heartbeat": datetime.now(timezone.utc).isoformat(),
                "user": getattr(self.user, "id", None), "reason": self.reason,
                "ms": int((time.monotonic() - self.started) * 1000),
                **({"error_id": self.error_id} if self.error_id else {}),
                **({"taken_back": "1"} if self.taken_back else {})}

    def outcome(self):
        if self.inner.cancelled():
            return "stopped" if self.reason == "stopped" else "interrupted"
        return "failed" if (self.inner.exception() or self.failed) else "done"

    def done(self):
        return self.task is not None and self.task.done()

    def emit(self, chunk):
        """Never awaits: a producer that blocks on a queue nobody drains would
        hang the run. A reader that falls behind is dropped instead."""
        if not self.attached: return
        try:
            self.queue.put_nowait(chunk)
        except asyncio.QueueFull:
            self.attached = False
            self.push(_LAGGED)

    def push(self, item):
        """Force an item in, evicting if need be — the end marker must land or
        the reader waits forever."""
        while True:
            try: return self.queue.put_nowait(item)
            except asyncio.QueueFull:
                try: self.queue.get_nowait()
                except asyncio.QueueEmpty: return


async def _supervise(run, stream, runs, key, on_run):
    if run.workspace is not None:   # what was there before it, for what it creates: names only, read while the model thinks
        run.before = asyncio.ensure_future(asyncio.to_thread(activity.names, run.workspace.root))
    run.inner = asyncio.create_task(_drive(run, stream))
    try:
        while True:
            _, pending = await asyncio.wait({run.inner}, timeout=RUN_BEAT)
            if not pending:
                break
            if time.monotonic() - run.started > RUN_BUDGET:
                run.reason = run.reason or "budget"
            elif not await _beat(run):
                continue
            run.inner.cancel()
            await asyncio.wait({run.inner}, timeout=RUN_DRAIN)
            break
    finally:
        try: await asyncio.wait_for(stream.aclose(), RUN_DRAIN)
        except BaseException: pass
        status = run.outcome() if run.inner.done() else "interrupted"
        if status == "failed": run.reason = run.reason or "error"
        # Here, before the record says stopped and the slot frees: no other run can start
        # in between, so the turn dropped is the one taken back and nothing came after it.
        if status == "stopped" and run.take_back and run.workspace is not None:
            try:
                run.taken_back = await state.truncate_last_exchange(
                    run.workspace, run.chat_id, run.take_back, alone=True) is not None
            except Exception as e: log("warn", chat_id=run.chat_id, message=f"take back failed: {e}")
        if run.workspace is not None and state.is_team(run.chat_id):   # what the team said meanwhile, after the reply
            try: await state.flush_held(run.workspace, run.chat_id)
            except Exception as e: log("warn", chat_id=run.chat_id, message=f"held messages not saved: {e}")
        # Shielded: this is the only place that knows the run ended, and it runs
        # while the process may already be shutting down.
        await asyncio.shield(asyncio.ensure_future(_finish(run, status, on_run)))
        if run.stepped and run.workspace is not None:
            await asyncio.wait({asyncio.ensure_future(_files_changed(run))}, timeout=RUN_FILES)
        run.push(_DONE)
        if runs.get(key) is run: runs.pop(key, None)


async def _beat(run):
    """Heartbeat, and read the stop flag back first — a stop can land on another
    container, which has nowhere to put it but the record. Returns True to stop."""
    if run.workspace is None:
        return False
    try:
        row = await state.get_run(run.workspace, run.chat_id)
    except Exception:
        row = None
    if row and row.get("stop"):
        run.reason, run.take_back = "stopped", row.get("take_back")
        return True
    await _record(run, "running")
    return False


async def _record(run, status):
    if run.workspace is None: return
    try: await state.put_run(run.workspace, run.chat_id, run.row(status))
    except Exception as e: log("warn", chat_id=run.chat_id, message=f"run record failed: {e}")


async def _finish(run, status, on_run):
    """The status transition, and the only moment that knows a run ended. The
    hook is the deployment's — push, email, a webhook, nothing."""
    await _record(run, status)
    log("run", user=run.user, chat_id=run.chat_id, status=status, reason=run.reason,
        error_id=run.error_id, ms=int((time.monotonic() - run.started) * 1000))
    if run.routine and run.workspace is not None:   # refused for the limit is a run that could not run
        await routines.ended(run.workspace, run.routine["id"], run.chat_id, "failed" if run.waiting == "plan" else status)
    elif not run.attached and run.user is not None and run.workspace is not None and status != "stopped":   # they had left
        await inbox.away(run.workspace, run.user.id, run.chat_id, status, run.waiting, run.origin)
    if on_run is None: return
    try:
        row = {**run.row(status), "chat_id": run.chat_id}
        result = on_run(row)
        if inspect.isawaitable(result): await result
    except Exception as e:   # a deployment's webhook must never fail the run
        log("warn", chat_id=run.chat_id, message=f"on_run failed: {e}")


async def _drive(run, stream):
    async for chunk in stream:
        run.emit(chunk)


async def _files_changed(run):
    """A run that called tools may have changed any file, bash included: each is recorded as its change."""
    try:
        before = await run.before if run.before else None
    except Exception:
        before = None
    try: await activity.after_run(run.workspace, before, run.started_at, run.chat_id, run.agent)
    except Exception as e: log("warn", chat_id=run.chat_id, message=f"file changes not recorded: {type(e).__name__}: {e}")


async def _forward(run):
    """The response: drains the run's queue. Ending this does not end the run —
    unless the client never opted into detachment, which is today's behaviour."""
    try:
        while True:
            try:
                item = await asyncio.wait_for(run.queue.get(), 1.0)
            except asyncio.TimeoutError:
                if run.inner is not None and run.inner.done() and run.queue.empty(): return
                continue
            if item is _DONE or item is _LAGGED: return
            yield item
    finally:
        run.attached = False
        if not run.detach and run.inner is not None and not run.inner.done():
            run.reason = run.reason or "disconnected"
            run.inner.cancel()


def _claim(runs, key, task):
    """Take the chat's run slot, or report it busy. Check and insert stay
    adjacent — an await between them reopens the race. A done task is stale, so
    a missed release can't lock a chat forever."""
    for k, t in list(runs.items()):
        if t.done(): runs.pop(k, None)
    owner = runs.get(key)
    if owner is not None and not owner.done(): return False
    runs[key] = task
    return True


_PUSH_WORKER = """
self.addEventListener("push", (e) => {
  const n = e.data ? e.data.json() : {};
  e.waitUntil((async () => {
    const wins = await clients.matchAll({ type: "window", includeUncontrolled: true });
    wins.forEach((w) => w.postMessage({ type: "cycls:push" }));
    const seen = wins.some((w) => w.visibilityState === "visible");
    await self.registration.showNotification(n.title || "", { tag: n.tag, silent: seen, data: n });
    if (seen) (await self.registration.getNotifications({ tag: n.tag })).forEach((x) => x.close());
  })());
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const n = e.notification.data || {};
  e.waitUntil((async () => {
    const [w] = await clients.matchAll({ type: "window", includeUncontrolled: true });
    if (!w) return clients.openWindow(n.url || "/");
    await w.focus();
    w.postMessage({ type: "cycls:open", ws: n.ws, chat: n.chat });
  })());
});
"""


def _app_url(request):
    """Where the app is, as the person reached it: https behind the platform's proxy, http on this machine alone."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    return host and f"{'http' if host.split(':')[0] in ('localhost', '127.0.0.1') else 'https'}://{host}"


async def encoder(stream, *, chat_id=None, user=None, first=False, run=None):
    if chat_id: yield sse({"type": "chat_id", "chat_id": chat_id, **({"first": True} if first else {})})
    try:
        async for item in _aiter(stream):
            if run is not None and isinstance(item, dict) and item.get("type") == "step":
                run.stepped = True   # it called tools: the files it may have changed are recorded as it ends
            if run is not None and isinstance(item, dict) and item.get("type") == "ui" and item.get("action") in ("ask", "confirm", "connect"):
                run.waiting = item["action"]   # it ends on a card: a question, an OK, a connector
            if run is not None and isinstance(item, dict) and item.get("action") == "open_plan_modal":
                run.waiting = "plan"   # the deployment's limit refused it
            if msg := sse(item): yield msg
    except Exception as e:
        import traceback
        error_id = uuid.uuid4().hex[:8]
        log("error", user=user, chat_id=chat_id,
            error_id=error_id, message=str(e), stack=traceback.format_exc())
        if run is not None: run.failed, run.error_id = True, error_id   # the callout would read as `done`
        from cycls._agent.harness.main import _is_retryable   # the service, still busy after the loop's own retries
        busy = _is_retryable(e)
        yield sse({"type": "callout",
                   "callout": (f"The service is busy right now. Try again in a minute. Reference: `{error_id}`" if busy
                               else f"Something went wrong. Reference: `{error_id}`"),
                   "style": "error", "error_id": error_id, **({"code": "busy"} if busy else {})})
    yield "data: [DONE]\n\n"

class Messages(list):
    """A list that provides text-only messages by default, with .raw for full data."""
    def __init__(self, raw_messages):
        self._raw = raw_messages
        text_messages = []
        for m in raw_messages:
            text_content = "".join(
                p.get("text", "") for p in m.get("parts", []) if p.get("type") == "text"
            )
            text_messages.append({
                "role": m.get("role"),
                "content": m.get("content") or text_content
            })
        super().__init__(text_messages)

    @property
    def raw(self):
        return self._raw

def _clean_folder(raw):
    """The folder the person has open in Files (a workspace path), else ""."""
    if not isinstance(raw, str) or len(raw) > 300 or raw.startswith("/") or "\\" in raw or ".." in raw.split("/") or raw.startswith("."):
        return ""
    return raw.strip("/")


def _clean_app(raw):
    """The slug of the app open beside the chat (apps/<slug>/), else ""."""
    if not isinstance(raw, str) or not 0 < len(raw) <= 64 or set(raw) - _APP_SLUG:
        return ""
    return raw


_APP_SLUG = set("abcdefghijklmnopqrstuvwxyz0123456789-_")


def _clean_selection(raw):
    """A selection in an open design, video, workbook or Word document {path: a .fig, .video.html, .xlsx or .docx
    in the workspace, frame, nodes: [{name, type, text?}], page? (a workbook's sheet), time?}, capped; else None."""
    if not isinstance(raw, dict):
        return None
    path = raw.get("path")
    if (not isinstance(path, str) or not path.lower().endswith((".fig", ".video.html", ".xlsx", ".docx")) or len(path) > 300
            or path.startswith("/") or "\\" in path or ".." in path.split("/")):
        return None
    nodes = []
    for n in (raw.get("nodes") if isinstance(raw.get("nodes"), list) else [])[:20]:
        if isinstance(n, dict) and isinstance(n.get("name"), str) and isinstance(n.get("type"), str):
            node = {"name": n["name"][:120], "type": n["type"][:24]}
            if isinstance(n.get("text"), str) and n["text"]:
                node["text"] = n["text"][:80]
            nodes.append(node)
    if not nodes:
        return None
    frame, page = raw.get("frame"), raw.get("page")
    sel = {"path": path, "frame": frame[:120] if isinstance(frame, str) and frame else None, "nodes": nodes}
    if isinstance(page, str) and page.strip():
        sel["page"] = page.strip()[:80]
    t = raw.get("time")
    if path.lower().endswith(".video.html") and isinstance(t, (int, float)) and not isinstance(t, bool) and 0 <= t < 36000:
        sel["time"] = round(float(t), 1)
    return sel


def web(func, config, extra_routers=None, auth=None, iap=None, on_run=None):
    from fastapi import FastAPI, Request, HTTPException, Depends
    from fastapi import Response as FastAPIResponse
    from fastapi.responses import JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles

    import httpx

    if isinstance(config, dict):
        config = Config(**config)

    cms = config.cms or {}
    _cms_headers = {"Authorization": f"Bearer {cms['token']}"} if cms.get("token") else {}
    _static_brand = dict(config.pass_metadata or {})   # .brand() wins piece by piece; the CMS fills what's unset
    _own_og = bool(config.og or config._og_image)       # .brand(og=) wins over the CMS's card
    _own_accent = config.accent                          # and .brand(accent=) over its colour

    volume = Path(config.volume)
    onesignal = next((p for p in config.notifications or [] if isinstance(p, dict) and p.get("provider") == "onesignal"), None)
    if onesignal and os.environ.get("ONESIGNAL_API_KEY"):   # the server pushes too, not only the platform's campaigns
        inbox.push_with(onesignal["app_id"], os.environ["ONESIGNAL_API_KEY"], config.name)
    web_push = next((p for p in config.notifications or [] if isinstance(p, dict) and p.get("provider") == "webpush"), None)
    if web_push and os.environ.get("VAPID_PRIVATE_KEY"):   # our own Web Push: the browsers subscribe with its public half
        webpush.use(os.environ["VAPID_PRIVATE_KEY"])
        web_push["key"] = webpush.public()
    # (workspace path, chat id) -> endpoint task. One run per chat per container;
    # create-only turn writes catch the cross-container pair (docs/notes/runs.md).
    runs = {}

    class Context(BaseModel):
        messages: Any
        user: Optional[User] = None
        chat_id: Optional[str] = None
        prod: bool = False
        workspace_id: Optional[str] = None
        disabled_tools: list = []   # tools the person switched off in Settings (e.g. ["WebSearch"]); LLM.run() honours it
        approvals: list = []       # approval keys from the confirm card — this turn only
        declined: list = []        # keys the confirm card's "Not now" turned down, saved with this turn
        auto: bool = True          # the composer's switch; absent means Auto
        connectors: list = []      # connectors the person @-mentioned — the turn gets a "[Using: …]" line
        selection: Optional[dict] = None   # "Add selection" from an open design — the turn gets a "[Selected in …]" block
        folder: str = ""           # the folder open in Files: where a design named without one is saved
        app: str = ""              # the app open beside the chat — the turn gets an "[Open beside the chat: …]" line
        replay: bool = False       # `regenerate` / `retry`: the last saved turn runs again instead of a new one
        agent_name: str = ""       # the agent's name as the chat shows it: what it signs a Word comment with
        by: Optional[dict] = None  # in a team chat, who wrote this turn: {id, name}
        routine: Optional[dict] = None   # a routine's run: {id, name, at} — `tell` instead of `routine`
        routines: bool = False     # Web.routines is on: the agent may offer one
        tz: str = ""               # the person's time zone, as their browser says

        model_config = {"arbitrary_types_allowed": True}

        @property
        def last_message(self) -> str:
            if self.messages:
                return self.messages[-1].get("content", "")
            return ""

        @property
        def workspace(self) -> Workspace:
            return state.chats_of(workspace(self.user, volume, base=config.storage, ws=self.workspace_id), self.chat_id)

    async def _author(user, ws):
        """Who writes in a team chat, as the model reads it: the sign-in's name, else the one they last had here."""
        pid = state.actor_of(ws.subject)
        return {"id": pid, "name": user.name or (await activity.people(ws)).get(pid, {}).get("name") or "A teammate"}

    def _agent_name():
        """The agent's name as the chat shows it (the brand's English name, else the agent's own), read at each turn
        since the CMS can rename it — the one the comments panel shows beside the agent's badge."""
        brand = (config.pass_metadata or {}).get("en")
        return " ".join(str(getattr(brand, "name", "") or config.name or "").split())[:60]

    @asynccontextmanager
    async def _lifespan(app):
        warm_up()   # the first turn's client, connection and connectors, readied as the instance starts
        yield
        # SIGTERM: hypercorn drives this, and Cloud Run allows 10s. Cancel the
        # loops, then let the supervisors finish their unwind and checkpoints.
        for run in list(runs.values()):
            run.reason = run.reason or "shutdown"
            if run.inner is not None and not run.inner.done(): run.inner.cancel()
        if tasks := [r.task for r in runs.values() if r.task and not r.task.done()]:
            await asyncio.wait(tasks, timeout=8)

    app = FastAPI(lifespan=_lifespan)

    @app.middleware("http")
    async def _origin(request: Request, call_next):
        activity.ORIGIN.set(activity.origin_of(request.headers, request.client))   # where an audit row came from
        return await call_next(request)
    app.state.runs = runs   # routers read it off the request

    validate = validator(auth, config.prod, iap)
    auth = Depends(validate) if config.auth else Depends(lambda: None)
    required_auth = Depends(validate)

    from .routers import resolve_ws_id

    @app.post("/")
    @app.post("/chat")
    @app.post("/chat/completions")
    async def back(request: Request, user: Optional[User] = auth):
        return await _chat(request, user, await request.json())

    async def _chat(request, user, data, routine=None):
        """A chat message: the person's, or a routine's run sent as its owner's (`routine`, from /routines/run alone)."""
        messages = data.get("messages")
        given = request.query_params.get("id")
        chat_id = given or f"{state.TEAM if data.get('team') is True else ''}{uuid.uuid4()}"
        api = request.url.path == "/chat/completions"   # read off the request while it exists
        ws_id = await resolve_ws_id(user, request.headers.get("x-workspace"), config.workspaces,
                                    volume, config.storage)
        tz = data.get("tz") if isinstance(data.get("tz"), str) and len(data["tz"]) < 64 else ""
        if user is not None and routine is None:   # who they are, for a routine that runs while they are away
            await inbox.remember(user, volume, config.storage, tz)

        # The account's first agent use — a durable per-account marker, so the
        # activation tick fires once per user (a browser flag re-fires on
        # every new device; a per-workspace check re-fires per workspace).
        first = False
        if user is not None and not given and data.get("post") is not True and routine is None:
            try:
                first = await state.mark_first_use(user, volume, config.storage, config.workspaces)
            except Exception:
                first = False

        context = Context(messages=Messages(messages), user=user, chat_id=chat_id, prod=config.prod,
                          workspace_id=ws_id,
                          disabled_tools=[t for t in (data.get("disabled_tools") or []) if isinstance(t, str)][:20],
                          approvals=[t for t in (data.get("approvals") or []) if isinstance(t, str)][:20],
                          declined=[t for t in (data.get("declined") or []) if isinstance(t, str)][:20], auto=data.get("auto") is not False,
                          connectors=[t for t in (data.get("connectors") or []) if isinstance(t, str)][:10],
                          selection=_clean_selection(data.get("selection")), folder=_clean_folder(data.get("folder")),
                          app=_clean_app(data.get("app")),
                          agent_name=_agent_name(), routine=routine, routines=config.routines is not None, tz=tz)
        try: context.workspace
        except LookupError: raise HTTPException(404, "Chat not found")
        if state.is_team(chat_id) and user is not None:   # its id is the client's, which shows it before it is saved
            said = (messages or [{}])[-1]
            turn, to = said.get("id"), data.get("reply")
            context.by = {**await _author(user, context.workspace),
                          "turn": turn if isinstance(turn, str) and re.fullmatch(r"[\w-]{6,40}", turn) else None,
                          "mentions": activity.mentioned(state.user_text(said), await activity.people(context.workspace))}
            if isinstance(to, str) and re.fullmatch(r"[\w-]{6,40}(\.re)?", to) and (q := await state.quote(context.workspace, chat_id, to)):
                context.by["reply"] = q   # whose message it answers is told, as an @ tells them
                if q.get("by") and q["by"] != context.by["id"]: context.by["mentions"].append(q["by"])

        # Every run gets an entry, fresh id or not: `stop` finds it there, the cap
        # counts it, and shutdown drains it. A fresh id simply never collides.
        key = (context.workspace.path, chat_id)
        # Detachment is the client's call — one that won't poll keeps today's
        # behaviour, where its disconnect ends the run. Never on the API route,
        # whose caller is given no chat id to come back to.
        run = Run(detach=data.get("detach") is True and not api,
                  workspace=context.workspace if user is not None else None,
                  chat_id=chat_id, user=user, agent=config.name, origin=_app_url(request))
        run.routine = routine
        busy = JSONResponse(status_code=409, headers={"Retry-After": "2"},
                            content={"error": "run_in_progress", "chat_id": chat_id,
                                     "detail": "This chat is still working on your last message."})
        if data.get("post") is True and context.by:   # to the team alone, no run: held while one has the chat
            said, mine = (messages or [{}])[-1], _claim(runs, key, run)
            try:
                running = not mine or state.run_status(await state.get_run(run.workspace, chat_id)) == "running"
                await (state.hold if running else state.post)(run.workspace, chat_id, said, context.by)
            finally:
                if mine: runs.pop(key, None)
            await inbox.later(inbox.mentioned(run.workspace, chat_id, said, context.by, run.origin))
            return JSONResponse({"chat_id": chat_id, "posted": True})
        if not _claim(runs, key, run):
            return busy
        try:
            # The registry only sees this container; the record is the other half,
            # and a heartbeat that stopped reads as gone rather than running.
            if run.workspace is not None:
                status = state.run_status(await state.get_run(run.workspace, chat_id))
                if status == "running":
                    runs.pop(key, None)
                    return busy
                if state.is_team(chat_id):   # anything held from the last run goes before this one
                    await state.flush_held(run.workspace, chat_id)
                # A replay runs the saved turn again, not the request's copy of it, and drops only
                # what came after it, here, where this run holds the chat. `regenerate` names a turn
                # on screen, so it must match. `retry` names one that may never have arrived, and one
                # whose run finished is an earlier message, so it falls back to an ordinary send.
                regenerate, retry = data.get("regenerate"), data.get("retry")
                if isinstance(regenerate, str) or (isinstance(retry, str) and retry and status != "done"):
                    expect = regenerate if isinstance(regenerate, str) else retry
                    turn = await state.truncate_last_exchange(run.workspace, chat_id, expect or None, keep=True)
                    if turn is not None:
                        context.replay = True
                        context.connectors = turn.get("connectors") or context.connectors
                        try: await state.touch_meta(run.workspace, chat_id, turn.get("content"))   # to the top of the list
                        except Exception as e: log("warn", chat_id=chat_id, message=f"meta touch failed: {e}")
                    elif isinstance(regenerate, str):
                        runs.pop(key, None)
                        return JSONResponse(status_code=409, content={
                            "error": "chat_changed", "chat_id": chat_id,
                            "detail": "This chat changed since it was opened. Reload it to see the latest."})
                await _record(run, "running")   # visible before the first heartbeat
                if context.by and not context.replay:   # once, as it is taken: a replay says nothing new
                    await inbox.later(inbox.mentioned(run.workspace, chat_id, (messages or [{}])[-1], context.by, run.origin))
            stream = await func(context) if inspect.iscoroutinefunction(func) else func(context)
            stream = (openai_encoder(stream) if api
                      else encoder(stream, chat_id=chat_id, user=user, first=first, run=run))
        except BaseException:
            if runs.get(key) is run: runs.pop(key, None)   # no supervisor yet to do it
            raise
        activity.ORIGIN.set({**activity.ORIGIN.get(), "agent": config.name, "chat": chat_id})   # the run's own rows
        run.task = asyncio.create_task(_supervise(run, stream, runs, key, on_run))
        return StreamingResponse(_forward(run), media_type="text/event-stream")

    @app.post("/chats/{chat_id}/stop")
    async def stop_run(chat_id: str, request: Request, user: Optional[User] = auth):
        """The only thing that cancels a run. A dropped connection is not a stop.
        `{"take_back": <sha256 of the prompt>}`: the person has the prompt back in their
        composer, so the run drops it as it ends if it kept nothing after it — and this
        answers once it has, with `taken_back`."""
        ws_id = await resolve_ws_id(user, request.headers.get("x-workspace"), config.workspaces,
                                    volume, config.storage)
        try: ws = state.chats_of(workspace(user, volume, base=config.storage, ws=ws_id), chat_id)
        except LookupError: return JSONResponse(status_code=404, content={"error": "no_run"})
        try: take = (json.loads(await request.body() or b"{}") or {}).get("take_back")
        except (ValueError, AttributeError): take = None
        take = take if isinstance(take, str) and take else None
        run = runs.get((ws.path, chat_id))
        if run is not None and run.inner is not None and not run.inner.done():
            run.reason, run.take_back = "stopped", take
            run.inner.cancel()
            if take: await asyncio.wait({run.task}, timeout=RUN_DRAIN + 5)
            return JSONResponse(status_code=202, content={"stopping": True,
                                                          **({"taken_back": run.taken_back} if take else {})})
        # Not ours: the run is on another container, which can only be reached
        # through the record. Its supervisor reads this on its next beat.
        row = await state.get_run(ws, chat_id) if user is not None else None
        status = state.run_status(row)
        if row is not None and status != "running":   # finished: a no-op, not an error
            return JSONResponse(status_code=202, content={"stopping": False, "status": status})
        if status != "running":
            return JSONResponse(status_code=404, content={"error": "no_run"})
        await state.put_run(ws, chat_id, {**row, "stop": "1", **({"take_back": take} if take else {})})
        if not take:
            return JSONResponse(status_code=202, content={"stopping": True})
        for _ in range(int((RUN_BEAT + RUN_DRAIN + 5) / 0.5)):   # until its next beat ends it
            await asyncio.sleep(0.5)
            row = await state.get_run(ws, chat_id)
            if state.run_status(row) != "running":
                break
        return JSONResponse(status_code=202, content={"stopping": True,
                                                      "taken_back": bool(row and row.get("taken_back"))})

    # ---- Routines (docs/rfc-routines.md): the clock, a run, Run now ----

    async def _start(origin, ws, record, chat):
        """A routine's run, sent as a request of its own: Cloud Run gives CPU while one is open, and spreads them."""
        async with httpx.AsyncClient(timeout=30) as client:   # its answer is not waited for: the run goes on, detached
            async with client.stream("POST", f"{origin}/routines/run", params={"id": chat}, headers={"x-workspace": ws.ws or ""},
                                     json={"sig": routines.signed(ws, record, chat)}) as r:
                if r.status_code >= 300:
                    raise RuntimeError(f"the run was refused: {r.status_code}")

    @app.post("/routines/tick")
    async def routines_tick(request: Request):
        """The clock, every five minutes: each routine due, claimed and sent. Anyone may call it: a routine starts only
        once its time has come, and once."""
        if config.routines is None: raise HTTPException(404)
        origin = _app_url(request)
        return {"started": await routines.tick(volume, config.storage, datetime.now(timezone.utc),
                                               lambda ws, record, chat: _start(origin, ws, record, chat))}

    @app.post("/routines/run")
    async def routines_run(request: Request):
        """A routine's run: its owner's chat message, built from the routine's record. Only this deployment can sign one."""
        try: sig = routines.verify((await request.json()).get("sig") or "")
        except (ValueError, KeyError, TypeError): raise HTTPException(403, "Not a routine's run")
        if sig["c"] != request.query_params.get("id") or (sig["w"] or "") != (request.headers.get("x-workspace") or ""):
            raise HTTPException(403, "Not this run")
        owner, ws = await inbox.person(sig["s"], volume, config.storage), workspace(sig["s"], volume, base=config.storage, ws=sig["w"])
        record = await routines.get(ws, sig["r"])
        if owner is None or record is None: raise HTTPException(404, "Gone")
        if sig["c"] != record.get("chat") and not await state.get_meta(ws, sig["c"]):   # its own chat: named for the day, off the list
            at = datetime.now(timezone.utc)
            await state.put_meta(ws, sig["c"], {"id": sig["c"], "title": f"{record['name']} · {at.astimezone(ZoneInfo(record['when']['tz'])):%d/%m}",
                                                "titleSource": "routine", "routine": record["id"],
                                                "createdAt": at.isoformat(), "updatedAt": at.isoformat()})
        return await _chat(request, owner, {"messages": [routines.opening(record)], "detach": True, "connectors": record["connectors"]},
                           routine={"id": record["id"], "name": record["name"], "at": datetime.now(timezone.utc).isoformat()})

    @app.post("/routines/{rid}/now")
    async def routine_now(rid: str, request: Request, user: Any = required_auth):
        """Run now: the run, at once, in a new chat (or the one kept), which the person opens to watch."""
        ws_id = await resolve_ws_id(user, request.headers.get("x-workspace"), config.workspaces, volume, config.storage)
        ws = workspace(user, volume, base=config.storage, ws=ws_id)
        record, chat = await routines.now(ws, rid)
        if record is None: raise HTTPException(404, "No such routine")
        await _start(_app_url(request), ws, record, chat)
        return {"chat": chat}

    @app.get("/config")
    async def get_config():
        asyncio.create_task(_refresh())
        warm_up()   # a client is loading the app (the phone asks here, the web page below): a message is coming
        return config.public()

    # The mic: our transcription engines first when they are set (ElevenLabs and/or the cycls-transcribe
    # service: the first, then the other), then the Web.voice service behind them (unset, OpenAI's
    # gpt-4o-transcribe whenever OPENAI_API_KEY is there). Web.voice(False) is no mic at all.
    from cycls._agent import transcribe as service
    speech = voice.resolve(config.transcription)

    def engines():
        return config.transcription is not False and service.configured()
    config.voice = bool(speech) or engines()

    @app.post("/transcribe/warm")
    async def transcribe_warm(user: Optional[User] = auth):
        """The microphone started recording: a listener starts while the person speaks. A hint only."""
        if engines() and service.engine() == "cycls":
            asyncio.create_task(service.warm(subject=service.subject_of(user)))
        return {"ok": True}

    @app.post("/transcribe")
    async def transcribe(request: Request, user: Optional[User] = auth):
        ours = engines()
        if not speech and not ours:
            raise HTTPException(status_code=501, detail="Voice input isn't set up")
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="No audio file")
        audio_bytes = await file.read()
        if ours:
            if len(audio_bytes) > service.client.SHORT_BYTES:
                raise HTTPException(status_code=413, detail="The recording is too long for the microphone")
            # The engine reads the format off the name: Firefox records webm, Safari and Chrome m4a.
            ext = (file.filename or "").rsplit(".", 1)[-1].lower()
            name = f"voice.{ext}" if ext in voice.FORMATS else "voice.m4a"
            hint = form.get("language")
            language = hint if hint in ("ar", "en") else "auto"
            from cycls._agent.transcribe import usage
            subject = service.subject_of(user)
            try:
                reason = await usage.refusal(subject, volume, config.storage)
            except Exception:  # noqa: BLE001 - an unreadable count never blocks the mic
                reason = None
            if reason:
                raise HTTPException(status_code=429, detail=reason)
            try:
                # With another engine behind it, a listener that is slow to start is not waited for long.
                behind = bool(service.fallback() or speech)
                t0 = time.monotonic()
                heard = await service.hear_short(audio_bytes, filename=name, language=language,
                                                 subject=subject, timeout=45.0 if behind else 130.0)
                await usage.charge(subject, volume, config.storage, seconds=heard.get("duration") or 0,
                                   engine=heard.get("engine_used") or "cycls", via="mic",
                                   ms=round((time.monotonic() - t0) * 1000), user=user)
                return {"text": heard.get("text") or "", "language": heard.get("language"),
                        "engine": heard.get("engine_used") or "cycls"}
            except service.OverAllowance as e:
                raise HTTPException(status_code=429, detail=str(e))
            except service.Refused as e:
                raise HTTPException(status_code=422, detail=str(e))
            except (service.Unavailable, RuntimeError) as e:
                if not speech:
                    raise HTTPException(status_code=503, detail=f"Transcription is unavailable: {e}")
                log("warn", user=getattr(user, "id", None), message=f"transcribe fell back to Web.voice: {str(e)[:200]}")
        try:
            return {"text": await voice.transcribe(speech, audio_bytes, file.filename, file.content_type)}
        except Exception as e:   # the service's own words would name it: they stay in the log
            log("warn", user=user, chat_id=None, message=f"transcription failed: {type(e).__name__}: {e}"[:500])
            raise HTTPException(status_code=502, detail="Couldn't transcribe the recording")

    for install in (extra_routers or []):
        install(app, required_auth)

    # ---- Explore menu (static list, or proxied + cached CMS) ----

    _explore_cache = {"at": 0.0, "data": None}

    @app.get("/explore")
    async def explore(response: FastAPIResponse):
        response.headers["Cache-Control"] = "public, max-age=300"
        if config.explore is not None:
            return {"agents": config.explore}
        url = cms.get("explore")
        if not url:
            return {"agents": []}
        if _explore_cache["data"] is None or time.time() - _explore_cache["at"] > 300:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.get(url, headers=_cms_headers)
                r.raise_for_status()
                _explore_cache.update(at=time.time(), data=r.json())
            except Exception:
                _explore_cache["at"] = time.time()
        return _explore_cache["data"] or {"agents": []}

    # ---- SEO ----

    from fastapi.responses import HTMLResponse
    from html import escape
    _base_html = (Path(config.public_path) / "index.html").read_text(encoding="utf-8")

    _head = ""   # the <head> additions the CMS cannot change, so they are built once
    _gtm_id = next((p.get("id") for p in (config.analytics or [])
                    if isinstance(p, dict) and p.get("provider") == "gtm"), None)
    if _gtm_id and re.fullmatch(r"GTM-[A-Z0-9]{4,10}", str(_gtm_id)):   # shape re-checked: inlined into a script tag
        _head += (
            "<script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':new Date().getTime(),event:'gtm.js'});"
            "var f=d.getElementsByTagName(s)[0],j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';"
            "j.async=true;j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);})"
            f"(window,document,'script','dataLayer','{_gtm_id}');</script>")
    if config.favicon:
        href = config.favicon if config.favicon.startswith(("http", "data:")) else "/favicon.svg"
        _head += f'<link rel="icon" href="{escape(href)}" />'
    if config.colors:
        c = config.colors
        light = "".join(f"--color-{k}:{v};" for k, v in
                        (("accent", c.get("primary")), ("secondary", c.get("secondary"))) if v)
        dark = "".join(f"--color-{k}:{v};" for k, v in
                       (("accent", c.get("primary_dark") or c.get("primary")),
                        ("secondary", c.get("secondary_dark") or c.get("secondary"))) if v)
        _head += f"<style>:root{{{light}}}.dark{{{dark}}}</style>"
    if m := re.search(r"/id(\d+)", (config.mobile_app or {}).get("ios", "")):
        _head += f'<meta name="apple-itunes-app" content="app-id={m.group(1)}" />'   # Safari's own banner
    _android = (config.mobile_app or {}).get("android", "")
    if _play := re.search(r"[?&]id=([\w.]+)", _android):
        _head += '<link rel="manifest" href="/manifest.webmanifest" />'   # Chrome's install sheet for the Play app
    if config.head:
        _head += config.head

    V = {}   # everything baked from the brand; _build() replaces the whole set together

    def _build():
        brand, seo = (config.pass_metadata or {}).get("en"), config.seo or {}
        V["title"] = seo.get("title") or (brand.name if brand else None) \
            or (f"{config.name.capitalize()} | Cycls Pass" if config.name else "Cycls")
        V["desc"] = seo.get("description") or (brand.description if brand else "") \
            or config.title or "AI Agent"
        V["og_title"] = (brand.name if brand else None) or (config.name.capitalize() if config.name else "Cycls")
        V["og_desc"] = (brand.description if brand else "") or config.title or ""
        # "</" escaped so CMS-sourced text can't close either script tag
        jsonld = json.dumps({"@context": "https://schema.org", "@type": "WebApplication",
                             "name": V["title"], "description": V["desc"],
                             "image": config.og or "/og.png",
                             "inLanguage": list(config.pass_metadata or {"en": None})}).replace("</", "<\\/")
        cfg = json.dumps(config.public()).replace("</", "<\\/")
        html = _base_html.replace("</head>", f'<script type="application/ld+json">{jsonld}</script>{_head}</head>')
        V["html"] = html.replace("</body>", f'<script>window.__CONFIG__={cfg}</script></body>')

    def _page(request, title=None, card=None):
        """The page, its head naming `title` with `card` as its social card (the agent's own by default), the
        card's address whole: X, LinkedIn and WhatsApp don't read one relative to the page."""
        fill = {"__TITLE__": escape(title or V["title"]), "__DESC__": escape(V["desc"]),
                'content="/og.png"': f'content="{escape(card or config.og or f"{request.base_url}og.png")}"'}
        return HTMLResponse(_HEAD.sub(lambda m: fill[m[0]], V["html"]))

    def _brand(agent):
        merged = {}
        for loc, name, desc in (("en", agent.get("title"), agent.get("description", "")),
                                ("ar", agent.get("title_ar") or agent.get("title"), agent.get("description_ar", ""))):
            s = _static_brand.get(loc)
            merged[loc] = PassMetadata(name=(s.name if s else "") or name or config.name or "",
                                       description=(s.description if s else "") or desc,
                                       logo=(s.logo if s else "") or agent.get("icon_svg", ""),
                                       brand=s.brand if s else "")
        config.pass_metadata = {**_static_brand, **merged}
        if not _own_og:   # the agent's card is its page's on the website, drawn by the CMS
            config.og = agent.get("card") or None
        config.accent = _own_accent or agent.get("accent") or None
        _build()

    _brand_at = {"t": 0.0}   # 0 means never loaded, so the first request retries instead of waiting a TTL
    if cms.get("brand"):     # once at boot, so the very first page already carries the real name
        try:
            r = httpx.get(cms["brand"], headers=_cms_headers, timeout=5)
            if r.status_code == 200:
                _brand(r.json())
                _brand_at["t"] = time.time()
        except Exception:
            # A CMS that scales to zero costs more than the timeout to wake, and this read is
            # usually what wakes it. Leaving the clock at 0 means the next request re-reads at
            # once, by which point the CMS is warm — rather than serving a blank brand for a TTL.
            pass
    if not V:                # no CMS, or the boot read failed
        _build()

    async def _refresh():
        """Re-read the brand at most once per TTL, in the background: the request that finds the
        cache stale is served from the copy in hand, so nothing ever waits on the CMS."""
        if not cms.get("brand") or time.time() - _brand_at["t"] < BRAND_TTL:
            return
        _brand_at["t"] = time.time()
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(cms["brand"], headers=_cms_headers)
            if r.status_code == 200:
                _brand(r.json())
        except Exception:
            pass

    @app.get("/robots.txt")
    async def robots(request: Request):
        return FastAPIResponse(f"User-agent: *\nAllow: /\nSitemap: {request.base_url}sitemap.xml\n",
                               media_type="text/plain")

    @app.get("/llms.txt")
    async def llms(request: Request):
        return FastAPIResponse(f"# {V['title']}\n\n> {V['desc']}\n\n- [{V['title']}]({request.base_url})\n",
                               media_type="text/plain")

    @app.get("/sitemap.xml")
    async def sitemap(request: Request):
        return FastAPIResponse(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<url><loc>{request.base_url}</loc></url></urlset>',
            media_type="application/xml")

    if _play:
        @app.get("/manifest.webmanifest")
        async def manifest():
            icons = [{"src": f"/app-icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png"} for n in (192, 512)]
            return FastAPIResponse(json.dumps({
                "name": V["og_title"], "short_name": V["og_title"], "start_url": "/", "icons": icons,
                "prefer_related_applications": True,
                "related_applications": [{"platform": "play", "id": _play.group(1), "url": _android}],
            }), media_type="application/manifest+json")

    if config.favicon and not config.favicon.startswith(("http", "data:")):
        @app.get("/favicon.svg")
        async def favicon():
            return FastAPIResponse(config.favicon, media_type="image/svg+xml")

    # ---- Dynamic OG images ----

    from fastapi.responses import RedirectResponse, Response
    from . import og

    _faces = og.faces(config._fonts)   # .brand(fonts=)'s, put where the cards find them, once

    def _look():
        """The agent as its cards show it: its icon, names, colour, wordmark and fonts — .brand()'s, else the CMS's."""
        en, ar = ((config.pass_metadata or {}).get(k) for k in ("en", "ar"))
        return {"icon": en.logo if en else "", "en": V["og_title"], "ar": ar.name if ar and ar.name != V["og_title"] else "",
                "accent": config.accent, "logo": en.brand if en else "", **_faces}

    @app.get("/og.png")
    async def og_image():
        if config._og_image:
            return Response(config._og_image, media_type="image/png")
        return Response(await og.card(V["og_desc"] or V["og_title"], agent=_look()), media_type="image/png")

    _drawn = {}   # each link's card as last drawn, for ten minutes: every paste of a link is another fetch of it

    @app.get("/share/{user}/{token}/card.png")
    async def share_card(user: str, token: str, request: Request, ws: Optional[str] = None):
        """A public link's social card, drawn as it's asked for: what it made beside its title, else its title over
        the question. Any other link, the moment it stops being public, or one that can't be drawn, has the agent's own."""
        from .routers import public_share, share_words
        own = RedirectResponse(config.og or f"{request.base_url}og.png")
        found = await public_share(user, token, ws, config.workspaces, volume, config.storage)
        if not found:
            return own
        for k in [k for k, (at, _) in _drawn.items() if time.time() - at > 600]:
            del _drawn[k]
        key = (user, token, ws, found[2])   # renamed, it's drawn again
        if key not in _drawn:
            try:
                ask, picture = await share_words(*found[:2])
                _drawn[key] = (time.time(), await og.link(found[2], ask, picture, _look()))
            except Exception as e:
                log("warn", message=f"share card not drawn: {e}")
                return own
        return Response(_drawn[key][1], media_type="image/png", headers={"Cache-Control": "public, max-age=600"})

    # ---- SPA fallback routes (before static mounts) ----

    @app.get("/")
    @app.get("/sso-callback")
    async def index(request: Request):
        asyncio.create_task(_refresh())   # this page is served from what we have; the next one is fresh
        warm_up()
        return _page(request)

    @app.get("/shared/{user}/{token}")
    async def share_index(user: str, token: str, request: Request, ws: Optional[str] = None):
        asyncio.create_task(_refresh())
        # A public link's page is named after what it shares, with its own card; any other link (a team's, a revoked
        # one) is the agent's page and says nothing of it.
        from .routers import public_share
        found = await public_share(user, token, ws, config.workspaces, volume, config.storage)
        if not found:
            return _page(request)
        return _page(request, found[2], f"{request.base_url}share/{user}/{token}/card.png" + (f"?ws={ws}" if ws else ""))

    if onesignal:
        # A push service worker must come from the site's own origin; scoped
        # under /push/onesignal/ so it never intercepts the page itself.
        @app.get("/push/onesignal/OneSignalSDKWorker.js")
        async def onesignal_worker():
            return FastAPIResponse('importScripts("https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js");\n',
                                   media_type="application/javascript")

    if web_push and web_push.get("key"):
        # The worker shows a push, and opens its chat on a click; with no fetch handler it never touches the page. While
        # the app is in view it shows it silently and closes it at once (a browser must show every push): the bell sounds.
        @app.get("/push/sw.js")
        async def push_worker():
            return FastAPIResponse(_PUSH_WORKER, media_type="application/javascript")

    # ---- Static mounts (must be last) ----

    if Path("public").is_dir():
        app.mount("/public", StaticFiles(directory="public", html=True))
    app.mount("/", StaticFiles(directory=config.public_path))

    return app

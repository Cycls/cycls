import asyncio, json, inspect, re, time, uuid, os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, PrivateAttr
from typing import Optional, Any
from cycls._app.auth import User, validator
from cycls._app.db import Workspace, workspace
from cycls._agent.logs import log
from cycls._agent import state


BRAND_TTL = 300   # how long a container serves the brand it last read from the CMS

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
    suggestions: bool = False
    voice: bool = False
    pk: Optional[str] = None
    one_tap: bool = False             # Google One Tap on the signed-out page
    affiliate: Optional[str] = None   # affiliate/referral provider key (e.g. Rewardful)
    max_upload: int = 512             # per-file upload cap in MB
    workspaces: Optional[str] = None  # multi-workspace mode: None off, else team-create policy ("member"|"admin")
    volume: str = "/workspace"
    seo: Optional[dict] = None        # {title, description} — page copy overriding the brand
    head: Optional[str] = None        # raw HTML appended to <head> (verification tags etc.)
    favicon: Optional[str] = None     # inline <svg>, data URI, or URL
    og: Optional[str] = None          # og:image URL when external; custom bytes ride _og_image
    explore: Optional[list] = None    # static explore menu (contract-shaped entries)
    explore_enabled: bool = False     # FE shows the agents dropdown
    examples: Optional[list] = None   # [{label, label_ar, urls}] — resolved at GET /examples
    examples_enabled: bool = False    # FE shows the example gallery on the empty screen
    colors: Optional[dict] = None     # {primary, secondary, primary_dark, secondary_dark}
    _og_image: Optional[bytes] = PrivateAttr(default=None)  # custom og card, served at /og.png

    def set_prod(self, prod: bool):
        self.prod = prod

    def public(self):
        """Config as sent to the browser — cms (bearer token), volume
        (internal mount path) and the raw examples mapping (the FE reads the
        resolved cards from /examples) stay server-side."""
        return self.model_dump(exclude={"cms", "volume", "examples"})

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
QUEUE_MAX = 512        # events buffered for a reader; a view, not a log
_DONE, _LAGGED = object(), object()
_OWNER = f"{os.environ.get('K_REVISION', 'local')}/{uuid.uuid4().hex[:8]}"


class Run:
    """One agent run. Two tasks on purpose: `task` supervises and is never
    cancelled by us, so it always lives to stamp the record and release the slot;
    `inner` drives the loop and is the only thing stop, budget, disconnect and
    shutdown cancel."""

    def __init__(self, *, detach, workspace=None, chat_id=None, user=None):
        self.queue = asyncio.Queue(QUEUE_MAX)
        self.detach, self.attached, self.reason = detach, True, None
        self.task = self.inner = None
        self.workspace, self.chat_id, self.user = workspace, chat_id, user
        self.id, self.started = uuid.uuid4().hex, time.monotonic()

    def row(self, status):
        return {"run": self.id, "status": status, "owner": _OWNER,
                "heartbeat": datetime.now(timezone.utc).isoformat(),
                "user": getattr(self.user, "id", None), "reason": self.reason,
                "ms": int((time.monotonic() - self.started) * 1000)}

    def outcome(self):
        if self.inner.cancelled():
            return "stopped" if self.reason == "stopped" else "interrupted"
        return "failed" if self.inner.exception() else "done"

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
        # Shielded: this is the only place that knows the run ended, and it runs
        # while the process may already be shutting down.
        await asyncio.shield(asyncio.ensure_future(_finish(run, status, on_run)))
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
        run.reason = "stopped"
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
    log("run", user=run.user, chat_id=run.chat_id, status=status,
        reason=run.reason, ms=int((time.monotonic() - run.started) * 1000))
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


async def encoder(stream, *, chat_id=None, user=None, first=False):
    if chat_id: yield sse({"type": "chat_id", "chat_id": chat_id, **({"first": True} if first else {})})
    try:
        async for item in _aiter(stream):
            if msg := sse(item): yield msg
    except Exception as e:
        import traceback
        error_id = uuid.uuid4().hex[:8]
        log("error", user=user, chat_id=chat_id,
            error_id=error_id, message=str(e), stack=traceback.format_exc())
        yield sse({"type": "callout",
                   "callout": f"Something went wrong. Reference: `{error_id}`",
                   "style": "error"})
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

    volume = Path(config.volume)
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
        auto: bool = True          # the composer's switch; absent means Auto
        connectors: list = []      # connectors the person @-mentioned — the turn gets a "[Using: …]" line

        model_config = {"arbitrary_types_allowed": True}

        @property
        def last_message(self) -> str:
            if self.messages:
                return self.messages[-1].get("content", "")
            return ""

        @property
        def workspace(self) -> Workspace:
            return workspace(self.user, volume, base=config.storage, ws=self.workspace_id)

    @asynccontextmanager
    async def _lifespan(app):
        yield
        # SIGTERM: hypercorn drives this, and Cloud Run allows 10s. Cancel the
        # loops, then let the supervisors finish their unwind and checkpoints.
        for run in list(runs.values()):
            run.reason = run.reason or "shutdown"
            if run.inner is not None and not run.inner.done(): run.inner.cancel()
        if tasks := [r.task for r in runs.values() if r.task and not r.task.done()]:
            await asyncio.wait(tasks, timeout=8)

    app = FastAPI(lifespan=_lifespan)
    app.state.runs = runs   # routers read it off the request

    validate = validator(auth, config.prod, iap)
    auth = Depends(validate) if config.auth else Depends(lambda: None)
    required_auth = Depends(validate)

    from .routers import resolve_ws_id

    @app.post("/")
    @app.post("/chat")
    @app.post("/chat/completions")
    async def back(request: Request, user: Optional[User] = auth):
        data = await request.json()
        messages = data.get("messages")
        given = request.query_params.get("id")
        chat_id = given or str(uuid.uuid4())
        api = request.url.path == "/chat/completions"   # read off the request while it exists
        ws_id = await resolve_ws_id(user, request.headers.get("x-workspace"), config.workspaces,
                                    volume, config.storage)

        # The account's first agent use — a durable per-account marker, so the
        # activation tick fires once per user (a browser flag re-fires on
        # every new device; a per-workspace check re-fires per workspace).
        first = False
        if user is not None and not given:
            try:
                first = await state.mark_first_use(user, volume, config.storage, config.workspaces)
            except Exception:
                first = False

        context = Context(messages=Messages(messages), user=user, chat_id=chat_id, prod=config.prod,
                          workspace_id=ws_id,
                          disabled_tools=[t for t in (data.get("disabled_tools") or []) if isinstance(t, str)][:20],
                          approvals=[t for t in (data.get("approvals") or []) if isinstance(t, str)][:20], auto=data.get("auto") is not False,
                          connectors=[t for t in (data.get("connectors") or []) if isinstance(t, str)][:10])

        # Every run gets an entry, fresh id or not: `stop` finds it there, the cap
        # counts it, and shutdown drains it. A fresh id simply never collides.
        key = (context.workspace.path, chat_id)
        # Detachment is the client's call — one that won't poll keeps today's
        # behaviour, where its disconnect ends the run. Never on the API route,
        # whose caller is given no chat id to come back to.
        run = Run(detach=data.get("detach") is True and not api,
                  workspace=context.workspace if user is not None else None,
                  chat_id=chat_id, user=user)
        busy = JSONResponse(status_code=409, headers={"Retry-After": "2"},
                            content={"error": "run_in_progress", "chat_id": chat_id,
                                     "detail": "This chat is still working on your last message."})
        if not _claim(runs, key, run):
            return busy
        try:
            # The registry only sees this container; the record is the other half,
            # and a heartbeat that stopped reads as gone rather than running.
            if run.workspace is not None:
                if state.run_status(await state.get_run(run.workspace, chat_id)) == "running":
                    runs.pop(key, None)
                    return busy
                await _record(run, "running")   # visible before the first heartbeat
            stream = await func(context) if inspect.iscoroutinefunction(func) else func(context)
            stream = (openai_encoder(stream) if api
                      else encoder(stream, chat_id=chat_id, user=user, first=first))
        except BaseException:
            if runs.get(key) is run: runs.pop(key, None)   # no supervisor yet to do it
            raise
        run.task = asyncio.create_task(_supervise(run, stream, runs, key, on_run))
        return StreamingResponse(_forward(run), media_type="text/event-stream")

    @app.post("/chats/{chat_id}/stop")
    async def stop_run(chat_id: str, request: Request, user: Optional[User] = auth):
        """The only thing that cancels a run. A dropped connection is not a stop."""
        ws_id = await resolve_ws_id(user, request.headers.get("x-workspace"), config.workspaces,
                                    volume, config.storage)
        ws = workspace(user, volume, base=config.storage, ws=ws_id)
        run = runs.get((ws.path, chat_id))
        if run is not None and run.inner is not None and not run.inner.done():
            run.reason = "stopped"
            run.inner.cancel()
            return JSONResponse(status_code=202, content={"stopping": True})
        # Not ours: the run is on another container, which can only be reached
        # through the record. Its supervisor reads this on its next beat.
        row = await state.get_run(ws, chat_id) if user is not None else None
        if state.run_status(row) != "running":
            return JSONResponse(status_code=404, content={"error": "no_run"})
        await state.put_run(ws, chat_id, {**row, "stop": "1"})
        return JSONResponse(status_code=202, content={"stopping": True})

    @app.get("/config")
    async def get_config():
        asyncio.create_task(_refresh())
        return config.public()

    @app.post("/transcribe")
    async def transcribe(request: Request, user: Optional[User] = auth):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=501, detail="Transcription not configured")
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="No audio file")
        audio_bytes = await file.read()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("voice.m4a", audio_bytes, file.content_type or "audio/mp4")},
                data={"model": "gpt-4o-transcribe"},
                timeout=30,
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            return r.json()

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

    config.voice = bool(os.environ.get("OPENAI_API_KEY"))

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
        html = _base_html.replace("__TITLE__", escape(V["title"])).replace("__DESC__", escape(V["desc"]))
        if config.og:
            html = html.replace('content="/og.png"', f'content="{escape(config.og)}"')
        html = html.replace("</head>", f'<script type="application/ld+json">{jsonld}</script>{_head}</head>')
        V["html"] = html.replace("</body>", f'<script>window.__CONFIG__={cfg}</script></body>')

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

    if config.favicon and not config.favicon.startswith(("http", "data:")):
        @app.get("/favicon.svg")
        async def favicon():
            return FastAPIResponse(config.favicon, media_type="image/svg+xml")

    # ---- Dynamic OG images ----

    from fastapi.responses import Response

    @app.get("/og.png")
    async def og_image():
        if config._og_image:
            return Response(config._og_image, media_type="image/png")
        from .og import generate as og_generate
        return Response(await og_generate(V["og_title"], V["og_desc"]), media_type="image/png")

    # ---- SPA fallback routes (before static mounts) ----

    @app.get("/")
    @app.get("/sso-callback")
    async def index():
        asyncio.create_task(_refresh())   # this page is served from what we have; the next one is fresh
        return HTMLResponse(V["html"])

    @app.get("/shared/{user}/{token}")
    async def share_index(user: str, token: str):
        asyncio.create_task(_refresh())
        return HTMLResponse(V["html"])

    if any(isinstance(p, dict) and p.get("provider") == "onesignal" for p in (config.notifications or [])):
        # A push service worker must come from the site's own origin; scoped
        # under /push/onesignal/ so it never intercepts the page itself.
        @app.get("/push/onesignal/OneSignalSDKWorker.js")
        async def onesignal_worker():
            return FastAPIResponse('importScripts("https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js");\n',
                                   media_type="application/javascript")

    # ---- Static mounts (must be last) ----

    if Path("public").is_dir():
        app.mount("/public", StaticFiles(directory="public", html=True))
    app.mount("/", StaticFiles(directory=config.public_path))

    return app

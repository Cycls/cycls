"""Agent loop — streams provider turns with sandboxed tool execution.

Owns one decision: alternate model turns and tool execution until the model
stops. Yields dict events (and bare strings for text deltas) that the agent
body forwards as-is. `Turn` is loop-internal (the last event a provider
stream emits) — never reaches the body.
"""
import asyncio, json, random, re, time, uuid
from datetime import datetime, timezone
from pathlib import Path

from cycls._app.db import Conflict
from .. import connectors, spill, state
from ..state import Session
from . import events
from .events import Turn
from .compact import COMPACT_AT, COMPACT_BUFFER, CLEAR_AT_LEAST, CLEAR_COLD, COLD_AFTER, DROPPED, KEEP_RECENT
from ..logs import log
from .prompts import DEFAULT_SYSTEM, workspace_instructions, fence_instructions
from .providers import make_provider
from ..tools import build_tools, dispatch, _exec_read, vendor_skips, tool_prompts, is_terminal, interrupted_note, register_labels, detailed, excerpt, app_catalog, ToolContext
from ..tools import skills as skills_mod


# ---- Config ----

MAX_RETRIES = 10
BASE_DELAY_MS = 500
MAX_DELAY_MS = 32_000
# 500 included: model servers surface transient capacity failures (CUDA OOM
# on a saturated GPU) as plain 500s that clear within seconds.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504, 529}
_FAILED = ("Error:", "Build failed:")   # how a tool says it failed — it returns, it does not raise
MAX_CONTINUATIONS = 4         # auto-continue rounds after a max_tokens cut
MAX_PAUSES = 8                # pause_turn resends before giving up
CANCEL_DRAIN = 2              # seconds a cancelled tool batch gets to unwind
_CONTINUE = ("Your previous message was cut off at the output-token limit. "
             "Continue exactly from where you stopped. Do not repeat anything.")
# Providers report context overflow as an error, each with its own wording.
# One phrasing per provider, because each says it differently and a miss here is
# not a smaller context — it is the error reaching the user instead of a compact
# and retry. SGLang's wording was missing while it served production.
_OVERFLOW_RE = re.compile(
    r"prompt is too long|request_too_large|exceeds the context window"
    r"|maximum context length|input token count.*exceeds"
    r"|context[_ ]length[_ ]exceeded|too many tokens"
    r"|is longer than the model", re.I)
DEFAULT_WINDOW = 1_000_000    # context window when .context() is unset — set it for smaller models
DEFAULT_MAX_TOKENS = 8_192    # output cap when .max_tokens() is unset — safe on every model


def _cause(e):
    """A TaskGroup/ExceptionGroup wrapper says nothing — dig out the exception that actually failed."""
    while getattr(e, "exceptions", None): e = e.exceptions[0]
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


def _server_said(e):
    """An MCP server's own words, when it answered with a reason rather than failing to answer at all.
    A server writes these for the person to act on — Slack's names the switch and links the page that
    flips it — so they belong in the chat. A timeout or a TLS failure says nothing a user can use and
    stays in the log."""
    from mcp.shared.exceptions import MCPError
    while getattr(e, "exceptions", None): e = e.exceptions[0]
    said = str(e).strip() if isinstance(e, MCPError) else ""
    return said[:300] or None


def _seen_connectors(messages, prefixes, catalog):
    """Which connectors this chat already discovered — read back from the transcript, so discovery
    survives a new instance without storing anything. Either the lookup that loaded them is in the
    history, or a call to one of their tools is."""
    seen = set()
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                continue
            name = str(b.get("name") or "")
            if name == "find_tools":
                seen |= set(connectors.matches(str((b.get("input") or {}).get("query") or ""), catalog))
            else:
                seen |= {n for p, n in prefixes.items() if name.startswith(p)}
    return seen


def _user_warn(user, chat_id, public, detail):
    """Chat callout with a reference id; the detail lives only in the log."""
    ref = uuid.uuid4().hex[:8]
    log("warn", user=user, chat_id=chat_id, error_id=ref, message=detail)
    return events.callout(f"{public} Reference: {ref}", "warning")


def _cost(price, inp, out, cached, cache_create):
    """USD for one turn from `.price()` rates (per 1M tokens). No price → 0."""
    if not price: return 0.0
    pin, pout, prd, pwr = price
    return (inp * pin + out * pout + cached * prd + cache_create * pwr) / 1_000_000


async def _timed(coro):
    """Run a coroutine, return (result_or_exception, elapsed_ms)."""
    t0 = time.monotonic()
    try:
        return await coro, int((time.monotonic() - t0) * 1000)
    except asyncio.CancelledError:
        raise   # a cancelled tool is cancelled, not a tool that returned an error
    except BaseException as e:
        return e, int((time.monotonic() - t0) * 1000)


# ---- Ingest ----

# A gated builtin's name, as the tool list knows it — `never` drops the whole row, read included.
_SETTINGS_NAME = {"bash": "Bash", "edit": "Editor", "database": "DataBase", "build_app": "Apps"}


def _with_mention(content, line):
    """The @-pill in the transcript: one line the model reads and a replay keeps."""
    if isinstance(content, list):
        return [*content, {"type": "text", "text": line}]
    return f"{content}\n\n{line}" if content else line


def _shape(block, out, ok, handlers, mcp_names):
    """A tool's output as (what the model reads, what the chat is shown, whether
    the turn now waits on the person). Split out so the cancel path can derive
    the same content without yielding — you cannot yield while unwinding."""
    name = block["name"]
    if ok and isinstance(out, dict) and "_model" in out:
        # Two channels: `_model` lands in tool_result, `_ui` goes to the client.
        return out["_model"], ([{**out["_ui"], "id": block["id"]}] if out.get("_ui") else []), False
    if ok and isinstance(out, dict) and out.get("type") == "ui":
        # A UI tool drives the client; the model gets a short ack so tool_result
        # stays a valid string. `ack` overrides the wording and never ships.
        ack = out.pop("ack", None)
        waiting = out.get("action") in ("confirm", "connect")
        return (ack or f"Opened {out.get('name') or out.get('path') or 'the file'} for the user.",
                [out], waiting)
    if ok and handlers and name in handlers and name not in mcp_names and not detailed(name):
        # A custom handler's result is both the chat's and the model's; a
        # connector's is the model's alone — the chat sees the step.
        return (out if isinstance(out, str) else json.dumps(out, default=str)), [out], False
    return out, [], False


async def _unwind(session, blocks, tasks, reason, handlers, mcp_names, workspace):
    """Take the batch back. `asyncio.wait` does not cancel what it waits on, so a
    bare cancel leaves tools running and their effects unrecorded. Cancel, give
    them a moment, then write a result for every call — the real one where it
    finished, `Interrupted:` only where it did not — because a `tool_use` with no
    result is stripped on the next read, taking the assistant turn with it."""
    for t in tasks:
        if not t.done(): t.cancel()
    await asyncio.wait(tasks, timeout=CANCEL_DRAIN)
    results = []
    for block, t in zip(blocks, tasks):
        if t.cancelled() or not t.done():
            content, failed = interrupted_note(block["name"], reason), True
        else:
            out, _ = t.result()
            failed = isinstance(out, BaseException)
            if failed: out = f"Error: {_cause(out)}"
            content, _, _ = _shape(block, out, not failed, handlers, mcp_names)
        if isinstance(content, str) and block["name"] not in ("read", "skill"):
            content = spill.spill(content, workspace.root, session.chat_id,
                                  f"{block['name']}-{block['id'][-6:]}")
        results.append({"type": "tool_result", "tool_use_id": block["id"],
                        "content": content, "is_error": failed})
    session.messages.append({"role": "user", "content": results})
    await asyncio.shield(session.checkpoint())


async def _ingest(content, workspace, vision=True):
    """Resolve attachment refs in an incoming user message to inline blocks,
    framed with the filename so the model knows what the user attached.
    Reuses `_exec_read` as the single source of truth for path → content.
    With `vision=False`, media that resolves to base64 blocks (images, PDFs)
    stays out of history — the model gets a note naming the file instead."""
    if not isinstance(content, list): return content
    out = []
    for block in content:
        if block.get("type") in ("image", "file"):
            fname = block.get("image") or block.get("file")
            if fname:
                result = await _exec_read({"path": fname}, workspace)
                if isinstance(result, str) and result.startswith("Error:"):
                    out.append({"type": "text", "text":
                        f'[The user attached "{fname}" but it can\'t be read directly ({result[7:]}). '
                        "It's saved in the workspace — propose a way to extract its content.]"})
                    continue
                if (not vision and isinstance(result, list)
                        and any(b.get("type") in ("image", "document") for b in result)):
                    out.append({"type": "text", "text":
                        f'[The user attached "{fname}" but this model can\'t view it directly (no vision). '
                        "It's saved in the workspace — propose a way to extract its content.]"})
                    continue
                out.append({"type": "text", "text": f"[Attached: {fname}]"})
                if isinstance(result, list): out.extend(result); continue
                if isinstance(result, str): out.append({"type": "text", "text": result}); continue
        out.append(block)
    return out


# ---- Retry & recovery ----

def _is_retryable(e):
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    if status and status in _RETRYABLE_STATUSES: return True
    msg = str(e).lower()
    return any(s in msg for s in ("overloaded", "rate limit", "too many requests", "429", "529"))


def _retry_delay(attempt, error=None):
    retry_after = getattr(error, "headers", {}).get("retry-after") if error else None
    if retry_after:
        try: return int(retry_after)
        except (ValueError, TypeError): pass
    base = min(BASE_DELAY_MS * (2 ** (attempt - 1)), MAX_DELAY_MS)
    return (base + random.random() * 0.25 * base) / 1000


async def _stream_with_retry(provider, **kw):
    """`provider.stream` with exponential backoff on overload / rate-limit.
    A stream that fails after some deltas re-emits them on retry — accepted;
    stored history isn't touched until the turn completes."""
    attempt = 0
    while True:
        try:
            async for ev in provider.stream(**kw):
                yield ev
            return
        except Exception as e:
            attempt += 1
            if not (_is_retryable(e) and attempt <= MAX_RETRIES): raise
            delay = _retry_delay(attempt, e)
            yield events.step(f"Model endpoint busy, retrying in {delay:.1f}s... (attempt {attempt}/{MAX_RETRIES})")
            await asyncio.sleep(delay)


# ---- Loop ----

async def _run(*, context, system="", tools=None, allowed_tools=[],
               model="anthropic/claude-sonnet-4-20250514", max_tokens=None,
               bash_timeout=600, bash_network=True, client=None,
               base_url=None, api_key=None, headers=None, handlers=None, mcp_servers=None,
               thinking="adaptive", vision=True, web_search="brave",
               instructions="AGENT.md", skills=[], price=None, context_window=None,
               extra_body=None, approvals=(), mentions=(), auto=True, api_connectors=()):
    vendor, bare_model = model.split("/", 1)
    provider = make_provider(model, client=client, base_url=base_url, api_key=api_key,
                             headers=headers, vision=vision)
    if max_tokens is None: max_tokens = DEFAULT_MAX_TOKENS
    workspace = context.workspace
    user = getattr(context, "user", None)
    Path(workspace.root).mkdir(parents=True, exist_ok=True)

    session = await Session.open(context)
    # the person's own allow / ask / never for the builtins, read once — no subject means no per-user store
    modes = await state.settings_db(workspace).get("tools", {}) if getattr(workspace, "subject", None) else {}
    if off := {_SETTINGS_NAME[k] for k, v in modes.items() if v == "never" and k in _SETTINGS_NAME}:
        allowed_tools = [t for t in allowed_tools if t not in off]
    ctx = ToolContext(user, workspace, session.chat_id, frozenset(approvals), auto, modes)
    incoming = context.messages.raw[-1]
    content = await _ingest(incoming.get("content", ""), workspace.root, vision)
    if mentions:
        titles = {s._connector.name: connectors.copy_of(s._connector)[0] or s._connector.name
                  for s in mcp_servers or [] if s._connector}
        content = _with_mention(content, "[Using: " + ", ".join(titles.get(m, m) for m in mentions) + "]")
    await session.add_user(content, attachments=incoming.get("attachments"), internal=bool(approvals))
    messages = session.messages

    system_text = DEFAULT_SYSTEM + ("\n\n" + system if system else "")
    if instructions:
        try:
            agent_md = await asyncio.to_thread(workspace_instructions, workspace.root, instructions)
            if agent_md: system_text += "\n\n" + fence_instructions(agent_md)
        except Exception as e:
            yield _user_warn(user, session.chat_id,
                             f"Couldn't load {instructions} — your instructions weren't applied this turn.",
                             f"couldn't load {instructions}: {e}")
    skill_catalog = {}
    if skills is not None:
        try:
            skills_mod.configure(skills)
            skill_catalog = await asyncio.to_thread(skills_mod.discover, workspace.root)
            if skill_catalog: system_text += "\n\n" + skills_mod.catalog_text(skill_catalog)
        except Exception:
            skill_catalog = {}
    for _ in vendor_skips(allowed_tools, vendor, web_search):
        log("warn", user=user, chat_id=session.chat_id,
                 message=f"native web search unavailable on {vendor}/* — use .web_search('brave') or an anthropic model")
    tools_list = build_tools(allowed_tools, tools or [], vendor=vendor, web_search=web_search)
    if skill_catalog and not any(t.get("name") == "skill" for t in tools_list):
        tools_list.append(skills_mod.SKILL_TOOL)
    owners = {}   # tool name -> the OAuth2 it acts with, for the audit line
    mcp_names = set()   # a server's results are the model's, never the chat's
    handlers = dict(handlers or {})

    def _mount(server, schemas, fns, names):
        nonlocal system_text
        tools_list.extend(schemas)
        handlers.update(fns)
        mcp_names.update(fns)
        register_labels({}, names, dict.fromkeys(fns, server._connector.name) if server._connector else None, details=fns.keys())
        if server._connector:
            owners.update(dict.fromkeys(fns, server._connector))
        if server._guidance and schemas:
            system_text += "\n\n" + server._guidance

    client_side = [s for s in mcp_servers or [] if not s._server_side]
    # An org admin's switch and the person's own resolve the same way here: the tools never enter the turn.
    hidden = (await connectors.blocked(workspace) | await connectors.off(workspace)) if (any(s._connector for s in client_side) or api_connectors) else set()
    deferred, catalog, objs = {}, {}, {}   # a connector's schemas wait behind `find_tools`
    for server in client_side:
        if server._connector and server._connector.name in hidden:
            continue
        try:
            schemas, fns, names = await connectors.tools_for(server, workspace)
        except Exception as e:
            said, label = _server_said(e), server._name or server._url
            yield _user_warn(user, session.chat_id,
                             f"{label}'s tools are off this turn — {said}" if said
                             else f"Couldn't reach {label} — its tools are off this turn.",
                             f"mcp discovery failed for {server._url}: {_cause(e)}")
            continue
        if not (server._connector and schemas):
            _mount(server, schemas, fns, names)
            continue
        o = server._connector
        objs[o.name] = o
        deferred.setdefault(o.name, []).append((server, schemas, fns, names))
        catalog.setdefault(o.name, (*connectors.copy_of(o), []))[2].extend(
            f'{s["name"]} {s.get("description") or ""}' for s in schemas)
    mcp_servers = [s for s in mcp_servers or [] if s._server_side] or None

    def _discover(name):
        """Its tools enter the turn and stay for the rest of the chat — the cache breakpoint sits on the
        last tool, so this is paid once per connector per chat, never once per turn."""
        got = []
        for entry in deferred.pop(name, ()):
            _mount(*entry)
            got += list(entry[2])
        return got

    def _owner_of(tool):
        return next((n for n, es in deferred.items() for s, *_ in es if tool.startswith(f"{s.label}_")), None)

    async def _find_tools(inp, ctx):
        hits = connectors.matches(str(inp.get("query") or ""), catalog)
        loaded = [(n, _discover(n)) for n in hits if n in deferred]
        if loaded:
            return "Loaded:\n" + "\n".join(f"- {n}: {', '.join(sorted(t))}" for n, t in loaded)
        if hits:
            return f"Already loaded: {', '.join(hits)}. Call those tools directly."
        return ("Nothing matched. You can load: " + ", ".join(sorted(deferred))) if deferred else "No connectors left to load."

    if deferred:   # already discovered here, or just `@`-mentioned — either way, no round-trip
        prefixes = {f"{s.label}_": n for n, es in deferred.items() for s, *_ in es}
        for name in _seen_connectors(messages, prefixes, catalog) | set(mentions or []):
            _discover(name)
    if deferred:
        tools_list.append(connectors.FIND_TOOLS)
        handlers["find_tools"] = _find_tools
        register_labels({"find_tools": lambda i: str(i.get("query") or "")}, {"find_tools": "Finding tools"},
                        details=("find_tools",))   # the result is the model's; the step row carries it
        system_text += "\n\nConnectors this person has connected. Their tools are not loaded yet — call " \
                       "`find_tools` once with what you need, then call the tools it returns.\n" + \
                       "\n".join(connectors.index_line(objs[n], sum(len(e[2]) for e in es)) for n, es in sorted(deferred.items()))
    # CONN-4: a connector with a REST base and no MCP server contributes one tool — otherwise a
    # stored key is unreachable, since everything above only walks servers.
    for o in api_connectors or ():
        if not o.api or o.servers or o.name in hidden or not await o.bearer(workspace):
            continue
        schema, fn, label, writes = connectors.api_tool(o)
        tools_list.append(schema)
        handlers[schema["name"]] = connectors.gated(fn, schema["name"], label, o.name, writes)
        mcp_names.add(schema["name"])
        owners[schema["name"]] = o
        register_labels({}, {schema["name"]: label}, {schema["name"]: o.name}, details=(schema["name"],))

    if any(t.get("name") == "build_app" for t in tools_list):
        if cat := await asyncio.to_thread(app_catalog, workspace.root):
            system_text += "\n\n" + cat
        # CONN-6: an app calls these live from the page; nothing else tells the model they exist.
        if apis := [o for o in {**{s._connector.name: s._connector for s in client_side if s._connector},
                                **{o.name: o for o in api_connectors or ()}}.values()
                    if o.api and o.name not in hidden]:
            system_text += ("\n\nInside an app, `await cycls.connector(name).json(path, init)` calls these "
                            "live, with the credential attached server-side:\n"
                            + "\n".join(f"- {o.name}: {o.api}" for o in apis))

    for guidance in tool_prompts(tools_list):
        system_text += "\n\n" + guidance
    window = context_window or DEFAULT_WINDOW
    trigger, keep = min(window * COMPACT_AT, window - max_tokens - COMPACT_BUFFER), int(window * KEEP_RECENT)
    tokens_since_compact = 0
    continuations = 0
    pauses = 0
    overflowed = False

    def request():
        """Everything a call sends besides its messages. The summary sends it too, so its prefix is cached."""
        return dict(system=system_text, tools=tools_list, mcp_servers=mcp_servers, thinking=thinking, extra_body=extra_body)

    def compacted(tier, reason, tokens, ok=True):
        """The analytics record of one compaction: a log row, and a `ui` event the client tracks."""
        log("compaction", user=user, chat_id=session.chat_id, model=bare_model,
            tier=tier, reason=reason, tokens=tokens, ok=ok)
        return {"type": "ui", "action": "compacted", "tier": tier, "reason": reason, "tokens": tokens, "ok": ok}

    async def fold():
        """Past the trigger: the cheap tier, or the summary when it frees too little or the window overflowed."""
        if tokens_since_compact <= trigger or len(messages) - session.first_kept <= 2: return
        reason = "overflow" if tokens_since_compact >= window else "trigger"
        if reason == "trigger" and await session.clear(keep, window * CLEAR_AT_LEAST):
            yield compacted(1, reason, tokens_since_compact)
            return
        yield events.step("Summarizing earlier messages to keep this chat going...")
        try:
            provider.last_usage = None
            task = asyncio.ensure_future(session.compact(provider, keep, max_tokens, request()))
            while not task.done():   # pings keep proxies from cutting a long silent call; a cut leaves it running
                await asyncio.wait([task], timeout=15.0)
                if not task.done(): yield {"type": "ping"}
            task.result()
            yield compacted(2, reason, tokens_since_compact, DROPPED not in session.summary)
            # The summarizer call is a real billed turn — track it too.
            if u := getattr(provider, "last_usage", None):
                c = _cost(price, *u)
                log("usage", user=user, chat_id=session.chat_id, model=bare_model,
                    input=u[0], output=u[1], cached=u[2], cache_create=u[3],
                    cost=round(c, 6), ms=0, compact=True)
                if session.chat_id and c:
                    try: await state.add_cost(workspace, session.chat_id, c)
                    except Exception as e: log("warn", user=user, chat_id=session.chat_id, message=f"add_cost failed: {e}")
        except Exception as ce:
            # degrades the loop until the context hard-overflows — never silent
            yield compacted(2, reason, tokens_since_compact, False)
            yield _user_warn(user, session.chat_id,
                             "Long-chat compression failed — this chat may hit its length limit sooner.",
                             f"compaction failed: {ce}")

    # Back after a pause the provider cache is gone, so stubbing now costs no miss.
    last = next((m["usage"] for m in reversed(messages) if m.get("usage")), {})
    if (last.get("at") and (datetime.now(timezone.utc) - datetime.fromisoformat(last["at"])).total_seconds() > COLD_AFTER
            and await session.clear(keep, window * CLEAR_COLD)):
        yield compacted(1, "cold", last.get("input", 0) + last.get("cached", 0) + last.get("cache_create", 0))

    while True:
        try:
            async for ev in fold(): yield ev

            turn = None
            partial_text = ""
            turn_t0 = time.monotonic()
            try:
                async for ev in _stream_with_retry(provider, messages=state.normalize(session.context()),
                                                   max_tokens=max_tokens, **request()):
                    if isinstance(ev, Turn): turn = ev
                    else:
                        if isinstance(ev, str): partial_text += ev
                        yield ev
            except (GeneratorExit, asyncio.CancelledError):
                if partial_text:
                    messages.append({"role": "assistant", "content": [
                        {"type": "text", "text": partial_text + "\n\n[…]"}
                    ]})
                    try: await asyncio.shield(session.checkpoint())
                    except BaseException: pass
                raise

            turn_ms = int((time.monotonic() - turn_t0) * 1000)
            tokens_since_compact = turn.input + turn.cached + turn.cache_create
            turn_cost = _cost(price, turn.input, turn.output, turn.cached, turn.cache_create)
            now = datetime.now(timezone.utc).isoformat()
            messages.append({"role": "assistant", "content": turn.content, "usage": {
                "model": bare_model,
                "input": turn.input, "output": turn.output,
                "cached": turn.cached, "cache_create": turn.cache_create,
                "cost": f"{turn_cost:.6f}",
                "ms": turn_ms,
                "at": now,
            }})
            log("usage", user=user, chat_id=session.chat_id,
                model=bare_model,
                input=turn.input, output=turn.output,
                cached=turn.cached, cache_create=turn.cache_create,
                cost=round(turn_cost, 6), ms=turn_ms, stop=turn.stop_reason)
            if session.chat_id:
                try: await state.add_cost(workspace, session.chat_id, turn_cost)
                except Exception as e: log("warn", user=user, chat_id=session.chat_id, message=f"add_cost failed: {e}")

            # max_tokens with zero output means the input filled the window —
            # an overflow in disguise, not a truncation.
            overflow = (turn.stop_reason == "model_context_window_exceeded"
                        or (turn.stop_reason == "max_tokens" and turn.output == 0))
            if overflow and not overflowed and len(messages) - session.first_kept > 2:
                # One recovery per run: drop the partial turn, compact, replay it.
                overflowed = True
                messages.pop()
                tokens_since_compact = window
                continue

            if turn.stop_reason == "max_tokens":
                # Pair any dangling tool_use blocks with error tool_results so
                # stored history stays API-valid for the next user turn.
                ids = [b["id"] for b in turn.content if isinstance(b, dict) and b.get("type") == "tool_use"]
                if ids:
                    messages.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": i, "content": "Cut off by output limit.", "is_error": True}
                        for i in ids]})
                if continuations < MAX_CONTINUATIONS:
                    continuations += 1
                    if not ids:
                        messages.append({"role": "user", "internal": True, "content": _CONTINUE})
                    yield events.step("Continuing past the output limit...")
                    await session.checkpoint()
                    continue

            if turn.stop_reason == "pause_turn" and pauses < MAX_PAUSES:
                pauses += 1  # server tool paused — resend to resume, bounded
                await session.checkpoint()
                continue

            if turn.stop_reason not in ("tool_use", "end_turn"):
                yield events.callout(f"Stopped: {turn.stop_reason}", "warning")
            if turn.stop_reason != "tool_use":
                await session.checkpoint(); break

            # On disk before the tools run — and after the pops above, which
            # would strand `_saved` past the list.
            await session.checkpoint()
            blocks = [b for b in turn.content if isinstance(b, dict) and b.get("type") == "tool_use"]
            for b in blocks:   # reached for a tool it never loaded — load it and let the call through
                _discover(_owner_of(b.get("name") or ""))
            # One `seen` per batch; comprehensions run left to right, so the first call wins.
            seen = set()
            pairs = [dispatch(b, workspace, bash_timeout, handlers, network=bash_network, seen=seen, ctx=ctx)
                     for b in blocks]
            for step, _ in pairs: yield step
            # Heartbeat every 15s while tools run — keeps intermediate
            # proxies from severing the SSE stream during long silent tool
            # executions.
            tasks = [asyncio.create_task(_timed(c)) for _, c in pairs]
            try:
                while True:
                    _, pending = await asyncio.wait(tasks, timeout=15.0, return_when=asyncio.ALL_COMPLETED)
                    if not pending: break
                    yield {"type": "ping"}
                timed = [t.result() for t in tasks]
            except (GeneratorExit, asyncio.CancelledError):
                # Why it stopped is the run record's job (§3); the model only
                # needs to know this call did not run to completion.
                await _unwind(session, blocks, tasks, "interrupted",
                              handlers, mcp_names, workspace)
                raise

            results, terminal, waiting, cards = [], False, False, []
            for block, (out, ms) in zip(blocks, timed):
                # `ok` routes the result; `good` is the outcome, and a returned error is one
                ok = not isinstance(out, BaseException)
                good = ok and not (isinstance(out, str) and out.startswith(_FAILED))
                o = owners.get(block["name"])
                log("tool_call", user=user, chat_id=session.chat_id,
                    model=bare_model, tool=block["name"], tool_use_id=block["id"], ms=ms, ok=good,
                    connector=o.name if o else None, credential_scope=o.scope if o else None,
                    output_bytes=len(out) if isinstance(out, (str, bytes)) else None,
                    error=None if good else (_cause(out) if not ok else out[:200]))
                if not ok: out = f"Error: {_cause(out)}"
                content, evs, waits = _shape(block, out, ok, handlers, mcp_names)
                for ev in evs: yield ev
                if waits:
                    waiting = True   # the person has to answer before anything else can happen
                    cards += [e for e in evs if isinstance(e, dict) and e.get("type") == "ui"]
                if isinstance(content, str) and block["name"] not in ("read", "skill"):
                    content = spill.spill(content, workspace.root, session.chat_id, f"{block['name']}-{block['id'][-6:]}")
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": content})
                if block["name"] in mcp_names or detailed(block["name"]):   # the step shows the outcome, bounded; a card (a ui dict) is its own outcome
                    yield {"type": "step", "id": block["id"], "ok": good,
                           **({} if isinstance(out, dict) and out.get("type") == "ui" else {"result": excerpt(content)})}
                # Only a call that reached the user ends the turn — a malformed
                # `ask` gets another turn to fix itself.
                if ok and is_terminal(block["name"]) and not str(content).startswith("Error"):
                    terminal = True
            # A card is a `ui` event, which the transcript does not keep — so a
            # run that ends waiting looks finished after a reload, with nothing to
            # approve. Ride it on the message the batch already writes.
            messages.append({"role": "user", "content": results, **({"cards": cards} if cards else {})})
            await session.checkpoint()
            if waiting:
                terminal = True
            if terminal:
                break

        except Conflict:
            # A turn slot was taken: this run's index is stale because something
            # else wrote the chat. Never replay — a replay writes more turns at
            # the same stale index. `checkpoint` has already logged and banked
            # what landed; fail the run and let the next load re-read the truth.
            session.rollback()
            raise
        except Exception as e:
            # Most providers report context overflow as an error, not a
            # stop_reason — compact and replay the turn, once per run.
            if (_OVERFLOW_RE.search(str(e)) and not overflowed
                    and len(messages) - session.first_kept > 2):
                overflowed = True
                tokens_since_compact = window
                continue
            # Retries already happened inside _stream_with_retry; this is fatal.
            # Rollback, then re-raise so the encoder owns the user-facing
            # callout + structured log (with error_id) in one place.
            # `normalize` sanitizes any dangling tool_use on next send.
            session.rollback()
            raise

    async for ev in fold(): yield ev   # now, while the answer is read — not when the next message waits on it

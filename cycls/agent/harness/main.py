"""Agent loop — streams provider turns with sandboxed tool execution.

Owns one decision: alternate model turns and tool execution until the model
stops. Yields dict events (and bare strings for text deltas) that the agent
body forwards as-is. `Turn` is loop-internal (the last event a provider
stream emits) — never reaches the body.
"""
import asyncio, json, random, time
from datetime import datetime, timezone
from pathlib import Path

from .. import state
from ..state import Session
from . import events
from .events import Turn
from .compact import COMPACT_BUFFER, KEEP_RECENT, compact
from .prompts import DEFAULT_SYSTEM
from .providers import make_provider
from ..tools import build_tools, dispatch, _exec_read, vendor_skips


# ---- Config ----

MAX_RETRIES = 10
BASE_DELAY_MS = 500
MAX_DELAY_MS = 32_000
_RETRYABLE_STATUSES = {429, 502, 503, 504, 529}

# Pricing per million tokens: (input, output, cache_read, cache_write)
_PRICING = {
    "claude-sonnet": (3, 15, 0.30, 3.75),
    "claude-opus":   (15, 75, 1.50, 18.75),
    "claude-haiku":  (0.80, 4, 0.08, 1),
}


def _cost(model, in_, out, cached, cache_create):
    """USD for one turn (or aggregate). Unknown model → 0."""
    p = next((v for k, v in _PRICING.items() if k in model), None)
    if not p: return 0.0
    return (in_ * p[0] + out * p[1] + cached * p[2] + cache_create * p[3]) / 1_000_000


async def _timed(coro):
    """Run a coroutine, return (result_or_exception, elapsed_ms)."""
    t0 = time.monotonic()
    try:
        return await coro, int((time.monotonic() - t0) * 1000)
    except BaseException as e:
        return e, int((time.monotonic() - t0) * 1000)


# ---- Ingest ----

async def _ingest(content, workspace):
    """Resolve attachment refs in an incoming user message to inline blocks.
    Reuses `_exec_read` as the single source of truth for path → content."""
    if not isinstance(content, list): return content
    out = []
    for block in content:
        if block.get("type") in ("image", "file"):
            fname = block.get("image") or block.get("file")
            if fname:
                result = await _exec_read({"path": fname}, workspace)
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
            yield events.step(f"Rate limited, retrying in {delay:.1f}s... (attempt {attempt}/{MAX_RETRIES})")
            await asyncio.sleep(delay)


# ---- Loop ----

async def _run(*, context, system="", tools=None, allowed_tools=[],
               model="anthropic/claude-sonnet-4-20250514", max_tokens=None,
               bash_timeout=600, bash_network=True, client=None,
               base_url=None, api_key=None, handlers=None, mcp_servers=None,
               thinking="adaptive"):
    vendor, bare_model = model.split("/", 1)
    provider = make_provider(model, client=client, base_url=base_url, api_key=api_key)
    if max_tokens is None: max_tokens = provider.max_output
    workspace = context.workspace
    user_id = getattr(getattr(context, "user", None), "id", None)
    Path(workspace.root).mkdir(parents=True, exist_ok=True)

    session = await Session.open(context)
    incoming = context.messages.raw[-1]
    await session.add_user(await _ingest(incoming.get("content", ""), workspace.root),
                           attachments=incoming.get("attachments"))
    messages = session.messages

    system_text = DEFAULT_SYSTEM + ("\n\n" + system if system else "")
    for skipped in vendor_skips(allowed_tools, vendor):
        yield events.callout(f"`{skipped}` is Anthropic-only; skipped on `{vendor}/*` models.", "warning")
    tools_list = build_tools(allowed_tools, tools or [], vendor=vendor)
    window = provider.context_window
    tokens_since_compact = 0

    while True:
        try:
            if tokens_since_compact > window - COMPACT_BUFFER and len(messages) > KEEP_RECENT:
                yield events.step("Compacting context...")
                try:
                    await session.rewrite(await compact(provider, messages))
                    tokens_since_compact = 0
                except Exception as ce:
                    yield events.callout(f"Compaction failed: {ce}", "warning")

            turn = None
            partial_text = ""
            turn_t0 = time.monotonic()
            try:
                async for ev in _stream_with_retry(provider, messages=state.normalize(messages), system=system_text,
                                                   tools=tools_list, max_tokens=max_tokens,
                                                   mcp_servers=mcp_servers, thinking=thinking):
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
            turn_cost = _cost(bare_model, turn.input, turn.output, turn.cached, turn.cache_create)
            now = datetime.now(timezone.utc).isoformat()
            messages.append({"role": "assistant", "content": turn.content, "usage": {
                "model": bare_model,
                "input": turn.input, "output": turn.output,
                "cached": turn.cached, "cache_create": turn.cache_create,
                "cost": f"{turn_cost:.6f}",
                "ms": turn_ms,
                "at": now,
            }})
            # Structured Cloud Logging entry — queryable via `cycls logs --query
            # 'jsonPayload.level="usage"'`. Mirrors the QA error logging shape.
            print(json.dumps({
                "source": "agent", "level": "usage",
                "model": bare_model,
                "user_id": user_id, "chat_id": session.chat_id,
                "input": turn.input, "output": turn.output,
                "cached": turn.cached, "cache_create": turn.cache_create,
                "cost": round(turn_cost, 6),
                "ms": turn_ms,
                "at": now,
            }), flush=True)
            if session.chat_id:
                try: await state.add_cost(workspace, session.chat_id, turn_cost)
                except Exception as e: print(f"[WARN] add_cost failed: {e}")

            if turn.stop_reason == "max_tokens":
                # Pair any dangling tool_use blocks with error tool_results so
                # stored history stays API-valid for the next user turn.
                ids = [b["id"] for b in turn.content if isinstance(b, dict) and b.get("type") == "tool_use"]
                if ids:
                    messages.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": i, "content": "Cut off by output limit.", "is_error": True}
                        for i in ids]})
            if turn.stop_reason not in ("tool_use", "end_turn"):
                yield events.callout(f"Stopped: {turn.stop_reason}", "warning")
            if turn.stop_reason != "tool_use":
                await session.checkpoint(); break

            blocks = [b for b in turn.content if isinstance(b, dict) and b.get("type") == "tool_use"]
            pairs = [dispatch(b, workspace, bash_timeout, handlers, network=bash_network) for b in blocks]
            for step, _ in pairs: yield step
            # Heartbeat every 15s while tools run — keeps intermediate
            # proxies from severing the SSE stream during long silent tool
            # executions.
            tasks = [asyncio.create_task(_timed(c)) for _, c in pairs]
            while True:
                _, pending = await asyncio.wait(tasks, timeout=15.0, return_when=asyncio.ALL_COMPLETED)
                if not pending: break
                yield {"type": "ping"}
            timed = [t.result() for t in tasks]

            results = []
            for block, (out, ms) in zip(blocks, timed):
                ok = not isinstance(out, BaseException)
                # Structured tool-call log — shape only (tool, ms, ok, output
                # size), no raw args/output (those may contain user data; the
                # full content already lives in tool_use / tool_result blocks
                # on the chat).
                print(json.dumps({
                    "source": "agent", "level": "tool_call",
                    "model": bare_model,
                    "user_id": user_id, "chat_id": session.chat_id,
                    "tool": block["name"],
                    "ms": ms, "ok": ok,
                    "output_bytes": len(out) if isinstance(out, (str, bytes)) else None,
                    "at": datetime.now(timezone.utc).isoformat(),
                }), flush=True)
                if not ok: out = f"Error: {out}"
                # Custom-handler results flow through the stream for the body to see
                # (UI rendering) AND serialize into tool_result for the model (data).
                if handlers and block["name"] in handlers and ok:
                    yield out
                    content = out if isinstance(out, str) else json.dumps(out, default=str)
                else:
                    content = out
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": content})
            messages.append({"role": "user", "content": results})
            await session.checkpoint()

        except Exception:
            # Retries already happened inside _stream_with_retry; this is fatal.
            # Rollback, then re-raise so the encoder owns the user-facing
            # callout + structured log (with error_id) in one place.
            # `normalize` sanitizes any dangling tool_use on next send.
            session.rollback()
            raise

"""Agent loop — streams provider turns with sandboxed tool execution.

Owns one decision: alternate model turns and tool execution until the model
stops. Yields dict events (and bare strings for text deltas) that the agent
body forwards as-is. `Turn` is loop-internal (the last event a provider
stream emits) — never reaches the body.
"""
import asyncio, json, random, time
from pathlib import Path

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
               model="anthropic/claude-sonnet-4-20250514", max_tokens=64000,
               bash_timeout=600, bash_network=True, show_usage=False, client=None,
               base_url=None, api_key=None, handlers=None, mcp_servers=None,
               thinking="adaptive"):
    t0 = time.monotonic()
    vendor, bare_model = model.split("/", 1)
    provider = make_provider(model, client=client, base_url=base_url, api_key=api_key)
    workspace = context.workspace
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
    usage_total = [0, 0, 0, 0]  # in, out, cached, cache_create
    tokens_since_compact = 0

    while True:
        try:
            if tokens_since_compact > window - COMPACT_BUFFER and len(messages) > KEEP_RECENT:
                yield events.step("Compacting context...")
                try:
                    await session.rewrite(await compact(provider.complete, messages))
                    tokens_since_compact = 0
                except Exception as ce:
                    yield events.callout(f"Compaction failed: {ce}", "warning")

            turn = None
            partial_text = ""
            try:
                async for ev in _stream_with_retry(provider, messages=messages, system=system_text,
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

            usage_total[0] += turn.input
            usage_total[1] += turn.output
            usage_total[2] += turn.cached
            usage_total[3] += turn.cache_create
            tokens_since_compact = turn.input + turn.cached + turn.cache_create
            messages.append({"role": "assistant", "content": turn.content})

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
            outputs = await asyncio.gather(*(c for _, c in pairs), return_exceptions=True)

            results = []
            for block, out in zip(blocks, outputs):
                if isinstance(out, BaseException): out = f"Error: {out}"
                if isinstance(out, str) and "timed out" in out:
                    yield events.callout(out, "warning")
                # Custom-handler results flow through the stream for the body to see
                # (UI rendering) AND serialize into tool_result for the model (data).
                if handlers and block["name"] in handlers and not isinstance(out, BaseException):
                    yield out
                    content = out if isinstance(out, str) else json.dumps(out, default=str)
                else:
                    content = out
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": content})
            messages.append({"role": "user", "content": results})
            await session.checkpoint()

        except Exception as e:
            # Retries already happened inside _stream_with_retry; this is fatal.
            # _valid_prefix trims any dangling tool_use on next load.
            session.rollback()
            yield events.callout(str(e), "error"); break

    if show_usage and usage_total[0]:
        p = next((v for k, v in _PRICING.items() if k in bare_model), None)
        cost = (usage_total[0]*p[0] + usage_total[1]*p[1] + usage_total[2]*p[2] + usage_total[3]*p[3]) / 1_000_000 if p else None
        yield events.usage(usage_total[0], usage_total[1], usage_total[2], usage_total[3], cost, time.monotonic() - t0)

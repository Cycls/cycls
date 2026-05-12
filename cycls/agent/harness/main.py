"""Agent loop — streams provider tool-use turns with sandboxed execution.

The loop owns one decision: alternate model turns and tool execution until the
model stops. Everything else is a collaborator — `make_provider` (the wire),
`Session` (the message log + its persistence), `compact` (context budget),
`dispatch`/`build_tools` (the tools). It yields typed `Event`s (see
`harness.events`); `LLM.run` is what its caller consumes, and the agent body
`to_ui`s them through (or pattern-matches first to hook the loop).
"""
import asyncio, json, random, time
from pathlib import Path
from ..sessions import Session
from .compact import COMPACT_BUFFER, KEEP_RECENT, compact
from .prompts import DEFAULT_SYSTEM
from .providers import make_provider
from .events import (Turn, Usage, Retrying, Compacting, CompactionFailed,
                     OutputLimitHit, StoppedUnexpectedly, TimedOut, Failed, Raw)
from ..tools import build_tools, dispatch, _exec_read


# ---- Config ----

MAX_RETRIES = 10
BASE_DELAY_MS = 500
MAX_DELAY_MS = 32_000
_RETRYABLE_STATUSES = {429, 502, 503, 504, 529}

# Pricing per million tokens: (input, output, cache_read, cache_write)
_PRICING = {
    "claude-sonnet": (3, 15, 0.30, 3.75),
    "claude-opus": (15, 75, 1.50, 18.75),
    "claude-haiku": (0.80, 4, 0.08, 1),
}

# ---- Ingest ----

async def _ingest(content, workspace):
    """Resolve attachment refs in an incoming user message to inline content blocks.
    Reuses _exec_read as the single source of truth for path → content blocks."""
    if not isinstance(content, list):
        return content
    out = []
    for block in content:
        if block.get("type") in ("image", "file"):
            fname = block.get("image") or block.get("file")
            if fname:
                result = await _exec_read({"path": fname}, workspace)
                if isinstance(result, list):
                    out.extend(result); continue
                if isinstance(result, str):
                    out.append({"type": "text", "text": result}); continue
        out.append(block)
    return out

# ---- Retry & Recovery ----

def _is_retryable(e):
    """Check if error is retryable. Uses status code when available, falls back to string match."""
    status = getattr(e, 'status_code', None) or getattr(e, 'status', None)
    if status and status in _RETRYABLE_STATUSES: return True
    msg = str(e).lower()
    return any(s in msg for s in ("overloaded", "rate limit", "too many requests", "429", "529"))

def _retry_delay(attempt, error=None):
    """Exponential backoff with jitter + retry-after header support."""
    retry_after = getattr(error, 'headers', {}).get('retry-after') if error else None
    if retry_after:
        try: return int(retry_after)
        except (ValueError, TypeError): pass
    base = min(BASE_DELAY_MS * (2 ** (attempt - 1)), MAX_DELAY_MS)
    jitter = random.random() * 0.25 * base
    return (base + jitter) / 1000

def _recover(e, messages):
    last = messages[-1] if messages else {}
    content = last.get("content", [])
    if not isinstance(content, list): return False
    if last.get("role") == "assistant" and any(b.get("type") == "tool_use" for b in content):
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b["id"], "content": f"Error: {e}"}
            for b in content if b.get("type") == "tool_use"]})
        return True
    return False

async def _stream_with_retry(provider, *, messages, system, tools, max_tokens, mcp_servers):
    """`provider.stream` with exponential backoff on overload / rate-limit:
    yields the provider's events; on a retryable error yields a `Retrying` step
    and tries again (up to `MAX_RETRIES`), otherwise propagates. A stream that
    fails after some deltas re-emits them on retry — accepted; the model output
    is regenerated, stored history isn't touched until the turn completes."""
    attempt = 0
    while True:
        try:
            async for ev in provider.stream(messages=messages, system=system, tools=tools,
                                            max_tokens=max_tokens, mcp_servers=mcp_servers):
                yield ev
            return
        except Exception as e:
            attempt += 1
            if not (_is_retryable(e) and attempt <= MAX_RETRIES):
                raise
            delay = _retry_delay(attempt, e)
            yield Retrying(attempt, MAX_RETRIES, delay)
            await asyncio.sleep(delay)

# ---- Agent ----

async def _run(*, context, system="", tools=None, allowed_tools=[],
               model="anthropic/claude-sonnet-4-20250514", max_tokens=64000,
               bash_timeout=600, bash_network=True, show_usage=False, client=None,
               base_url=None, api_key=None, handlers=None, mcp_servers=None):
    t0 = time.monotonic()
    bare_model = model.split("/", 1)[1]
    provider = make_provider(model, client=client, base_url=base_url, api_key=api_key)
    workspace = context.workspace
    Path(workspace.root).mkdir(parents=True, exist_ok=True)

    session = await Session.open(context)
    incoming = context.messages.raw[-1]
    await session.add_user(await _ingest(incoming.get("content", ""), workspace.root),
                           attachments=incoming.get("attachments"))
    messages = session.messages

    system_text = DEFAULT_SYSTEM + ("\n\n" + system if system else "")
    tools_list = build_tools(allowed_tools, tools or [])
    window = provider.context_window
    usage = [0, 0, 0, 0]  # in, out, cached, cache_create
    tokens_since_compact = recovery = 0

    while True:
        try:
            if tokens_since_compact > window - COMPACT_BUFFER and len(messages) > KEEP_RECENT:
                yield Compacting()
                try:
                    await session.rewrite(await compact(provider.complete, messages))
                    tokens_since_compact = 0
                except Exception as ce:
                    yield CompactionFailed(str(ce))

            turn = None
            async for ev in _stream_with_retry(provider, messages=messages, system=system_text,
                                               tools=tools_list, max_tokens=max_tokens, mcp_servers=mcp_servers):
                if isinstance(ev, Turn): turn = ev
                else: yield ev

            usage[0] += turn.input; usage[1] += turn.output; usage[2] += turn.cached; usage[3] += turn.cache_create
            tokens_since_compact = turn.input + turn.cached + turn.cache_create
            messages.append({"role": "assistant", "content": turn.content})

            if turn.stop_reason == "max_tokens" and recovery < 3:
                recovery += 1
                ids = [b["id"] for b in turn.content if isinstance(b, dict) and b.get("type") == "tool_use"]
                msg = "Cut off by output limit. Resume — break remaining work into smaller pieces."
                messages.append({"role": "user", "content": (
                    [{"type": "tool_result", "tool_use_id": i, "content": msg, "is_error": True} for i in ids]
                    if ids else msg)})
                yield OutputLimitHit(recovery, 3)
                continue
            if turn.stop_reason not in ("tool_use", "end_turn"):
                yield StoppedUnexpectedly(turn.stop_reason)
            if turn.stop_reason != "tool_use":
                await session.checkpoint(); break

            blocks = [b for b in turn.content if isinstance(b, dict) and b.get("type") == "tool_use"]
            pairs = [dispatch(b, workspace, bash_timeout, handlers, network=bash_network) for b in blocks]
            for step, _ in pairs: yield Raw(step)
            outputs = await asyncio.gather(*(c for _, c in pairs), return_exceptions=True)

            results = []
            for block, out in zip(blocks, outputs):
                if isinstance(out, BaseException): out = f"Error: {out}"
                if isinstance(out, str) and "timed out" in out:
                    yield TimedOut(out)
                # Custom-handler results flow through the stream for the body to see
                # (UI rendering) AND serialize into tool_result for the model (data).
                if handlers and block["name"] in handlers and not isinstance(out, BaseException):
                    yield Raw(out)
                    content = out if isinstance(out, str) else json.dumps(out, default=str)
                else:
                    content = out
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": content})
            messages.append({"role": "user", "content": results})
            await session.checkpoint()

        except Exception as e:
            # Retries (overload / rate-limit) already happened inside
            # _stream_with_retry; what reaches here is fatal. If the model left a
            # dangling tool_use, inject error tool_results and let the loop carry
            # on; otherwise surface the error and stop.
            if not _recover(e, messages):
                session.rollback()
                yield Failed(str(e)); break
            await session.checkpoint(); continue

    if show_usage and usage[0]:
        p = next((v for k, v in _PRICING.items() if k in bare_model), None)
        cost = (usage[0]*p[0] + usage[1]*p[1] + usage[2]*p[2] + usage[3]*p[3]) / 1_000_000 if p else None
        yield Usage(usage[0], usage[1], usage[2], usage[3], cost, time.monotonic() - t0)

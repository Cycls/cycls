"""Agent loop — streams provider tool-use turns with sandboxed execution."""
import asyncio, json, random, time
from datetime import datetime, timezone
from pathlib import Path
from .. import chat
from .compact import COMPACT_BUFFER, KEEP_RECENT, compact
from .prompts import DEFAULT_SYSTEM
from .providers import make_provider
from .events import Turn, Usage, to_ui
from ..tools import build_tools, dispatch, _exec_read


def _ephemeralize(messages):
    """Strip stale cache_control markers; tag the last message ephemeral so
    prompt caching keeps the prior context warm and the new turn is fresh."""
    for msg in messages:
        c = msg.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    if messages:
        c = messages[-1].get("content")
        if isinstance(c, str):
            messages[-1]["content"] = [{"type": "text", "text": c, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        elif isinstance(c, list) and c:
            c[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return messages


async def _touch_meta(workspace, chat_id, content):
    """Stamp `updatedAt` for chat-list ordering; on the first turn also derive
    title from the user message and set createdAt. Sole writer of chat meta —
    the FE shouldn't PUT this back."""
    existing = (await chat.get_meta(workspace, chat_id)) or {}
    now = datetime.now(timezone.utc).isoformat()
    meta = {**existing, "id": chat_id, "updatedAt": now}
    if "createdAt" not in meta:
        meta["createdAt"] = now
    if not meta.get("title"):
        text = content if isinstance(content, str) else next(
            (b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"),
            "",
        )
        title = text.strip()[:80]
        if title:
            meta["title"] = title
    await chat.put_meta(workspace, chat_id, meta)

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
                    out.extend(result)
                    continue
                if isinstance(result, str):
                    out.append({"type": "text", "text": result})
                    continue
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

# ---- Agent ----

async def _run(*, context, system="", tools=None, allowed_tools=[],
               model="anthropic/claude-sonnet-4-20250514", max_tokens=64000,
               bash_timeout=600, bash_network=True, show_usage=False, client=None,
               base_url=None, api_key=None, handlers=None, mcp_servers=None):
    t0 = time.monotonic()
    bare_model = model.split("/", 1)[1]
    provider = make_provider(model, client=client, base_url=base_url, api_key=api_key)
    workspace = context.workspace
    ws = workspace.root
    Path(ws).mkdir(parents=True, exist_ok=True)
    persist = bool(context.chat_id and context.user)
    messages = _ephemeralize(await chat.load_messages(workspace, context.chat_id)) if persist else []
    saved = len(messages)
    incoming_msg = context.messages.raw[-1]
    incoming = incoming_msg.get("content", "")
    user_msg = {"role": "user", "content": await _ingest(incoming, ws)}
    # Persist FE attachment metadata as a sidecar — the model sees inlined
    # base64 in `content`, the FE renders thumbnails from `attachments[]`.
    if attachments := incoming_msg.get("attachments"):
        user_msg["attachments"] = attachments
    messages.append(user_msg)
    if persist:
        try: await _touch_meta(workspace, context.chat_id, incoming)
        except Exception as e: print(f"[WARN] meta touch failed: {e}")

    system_text = DEFAULT_SYSTEM + ("\n\n" + system if system else "")
    tools_list = build_tools(allowed_tools, tools or [])
    window = provider.context_window
    usage = [0, 0, 0, 0]  # in, out, cached, cache_create
    tokens_since_compact = 0
    retries = 0
    recovery = 0

    while True:
        try:
            if tokens_since_compact > window - COMPACT_BUFFER and len(messages) > KEEP_RECENT:
                yield {"type": "step", "step": "Compacting context..."}
                try:
                    messages[:] = await compact(provider.complete, messages)
                    tokens_since_compact = 0
                    if persist:
                        await chat.replace_messages(workspace, context.chat_id, messages); saved = len(messages)
                except Exception as ce:
                    yield {"type": "callout", "callout": f"Compaction failed: {ce}", "style": "warning"}

            turn = None
            async for ev in provider.stream(messages=messages, system=system_text, tools=tools_list,
                                            max_tokens=max_tokens, mcp_servers=mcp_servers):
                if isinstance(ev, Turn): turn = ev
                else: yield to_ui(ev)

            retries = 0
            usage[0] += turn.input; usage[1] += turn.output; usage[2] += turn.cached; usage[3] += turn.cache_create
            tokens_since_compact = turn.input + turn.cached + turn.cache_create
            messages.append({"role": "assistant", "content": turn.content})
            if turn.stop_reason == "max_tokens" and recovery < 3:
                recovery += 1
                ids = [b["id"] for b in (messages[-1].get("content") or [])
                       if isinstance(b, dict) and b.get("type") == "tool_use"]
                msg = "Cut off by output limit. Resume — break remaining work into smaller pieces."
                messages.append({"role": "user", "content": (
                    [{"type": "tool_result", "tool_use_id": i, "content": msg, "is_error": True} for i in ids]
                    if ids else msg
                )})
                yield {"type": "step", "step": f"Output limit hit, continuing... ({recovery}/3)"}
                continue
            if turn.stop_reason not in ("tool_use", "end_turn"):
                yield {"type": "callout", "callout": f"Stopped: {turn.stop_reason}", "style": "warning"}
            if turn.stop_reason != "tool_use":
                # Clean turn end — persist the assistant message atomically
                # before breaking so the disk reflects only consistent state.
                if persist:
                    await chat.append_messages(workspace, context.chat_id, messages[saved:], saved); saved = len(messages)
                break

            blocks = [b for b in turn.content if isinstance(b, dict) and b.get("type") == "tool_use"]
            pairs = [dispatch(b, workspace, bash_timeout, handlers, network=bash_network) for b in blocks]
            for step, _ in pairs: yield step
            outputs = await asyncio.gather(*(c for _, c in pairs), return_exceptions=True)

            results = []
            for block, out in zip(blocks, outputs):
                if isinstance(out, BaseException): out = f"Error: {out}"
                if isinstance(out, str) and "timed out" in out:
                    yield {"type": "callout", "callout": out, "style": "warning"}
                # Custom-handler results flow through the stream for the body to see
                # (UI rendering) AND serialize into tool_result for the model (data).
                if handlers and block["name"] in handlers and not isinstance(out, BaseException):
                    yield out
                    content = out if isinstance(out, str) else json.dumps(out, default=str)
                else:
                    content = out
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": content})
            messages.append({"role": "user", "content": results})
            if persist:
                await chat.append_messages(workspace, context.chat_id, messages[saved:], saved); saved = len(messages)

        except Exception as e:
            if _is_retryable(e) and retries < MAX_RETRIES:
                retries += 1
                delay = _retry_delay(retries, e)
                yield {"type": "step", "step": f"Rate limited, retrying in {delay:.1f}s... (attempt {retries}/{MAX_RETRIES})"}
                await asyncio.sleep(delay)
                # Roll in-memory back to last persisted — exception may have
                # left a dangling assistant tool_use in messages that the
                # retried request would otherwise resend mid-pair.
                del messages[saved:]
                continue
            if not _recover(e, messages):
                # Non-recoverable: don't leave orphans on disk. Rollback any
                # unpersisted partial state before breaking.
                del messages[saved:]
                yield {"type": "callout", "callout": str(e), "style": "error"}; break
            if persist:
                await chat.append_messages(workspace, context.chat_id, messages[saved:], saved); saved = len(messages)
            continue

    # All persists happen on clean turn boundaries above — no final cleanup
    # needed. The load-time repair in chat.load_messages handles any legacy
    # corruption from before this refactor.

    if show_usage and usage[0]:
        p = next((v for k, v in _PRICING.items() if k in bare_model), None)
        cost = (usage[0]*p[0] + usage[1]*p[1] + usage[2]*p[2] + usage[3]*p[3]) / 1_000_000 if p else None
        yield to_ui(Usage(usage[0], usage[1], usage[2], usage[3], cost, time.monotonic() - t0))



"""Agent loop — streams Claude tool-use turns with sandboxed execution."""
import asyncio, json, random, time
from cycls.app.state import ensure_workspace, history_path, load_history, save_history
from .compact import COMPACT_BUFFER, KEEP_RECENT, compact, context_window
from .prompts import DEFAULT_SYSTEM
from .tools import build_tools, dispatch

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

# ---- Helpers ----

def _prepare_prompt(context):
    content = context.messages.raw[-1].get("content", "")
    if not isinstance(content, list):
        return content
    texts = [p["text"] for p in content if p.get("type") == "text"]
    files = [p.get("image") or p.get("file") for p in content if p.get("type") in ("image", "file")]
    files = [f for f in files if f]
    return " ".join(texts) + (f"\n\nAttached files: {', '.join(files)}" if files else "")

# ---- Stream ----

async def _iter_stream(stream):
    search_idx, search_buf = None, ""
    async for ev in stream:
        if ev.type == "content_block_start":
            if ev.content_block.type == "server_tool_use" and ev.content_block.name == "web_search":
                search_idx, search_buf = ev.index, ""
        elif ev.type == "content_block_delta":
            d = ev.delta
            if d.type == "thinking_delta": yield {"type": "thinking", "thinking": d.thinking}
            elif d.type == "text_delta": yield d.text
            elif d.type == "input_json_delta" and ev.index == search_idx: search_buf += d.partial_json
        elif ev.type == "content_block_stop":
            if ev.index == search_idx:
                try: q = json.loads(search_buf).get("query", "")
                except Exception: q = ""
                yield {"type": "step", "step": q, "tool_name": "Web Search"}; search_idx = None

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

async def Agent(*, context, system="", tools=None, builtin_tools=[],
                model="claude-sonnet-4-20250514", max_tokens=16384, thinking=True,
                bash_timeout=600, show_usage=False, client=None):
    t0 = time.monotonic()
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic()
    ws = context.workspace
    ensure_workspace(ws)
    hp = history_path(context.user, context.session_id) if context.session_id and context.user else None
    messages = load_history(hp) if hp else []
    saved = len(messages)
    messages.append({"role": "user", "content": _prepare_prompt(context)})
    window = context_window(model)

    kwargs = {
        "model": model, "max_tokens": max_tokens,
        "tools": build_tools(builtin_tools, tools or []),
        "messages": messages,
        "system": [{"type": "text", "text": DEFAULT_SYSTEM + ("\n\n" + system if system else ""),
                     "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        **({"thinking": {"type": "adaptive"}} if thinking else {}),
    }
    usage = [0, 0, 0, 0]  # in, out, cached, cache_create
    retries = 0

    while True:
        try:
            # Pre-turn compaction: compact before API call if approaching context limit
            if usage[0] > window - COMPACT_BUFFER and len(messages) > KEEP_RECENT:
                yield {"type": "step", "step": "Compacting context..."}
                try:
                    messages[:] = await compact(client, model, messages)
                    usage[0] = 0  # reset so we don't compact every turn
                    if hp: save_history(hp, messages, mode="w"); saved = len(messages)
                except Exception as ce:
                    yield {"type": "callout", "callout": f"Compaction failed: {ce}", "style": "warning"}

            async with client.messages.stream(**kwargs) as stream:
                async for event in _iter_stream(stream): yield event
                response = await stream.get_final_message()

            retries = 0
            u = response.usage
            usage[0] += u.input_tokens; usage[1] += u.output_tokens
            usage[2] += u.cache_read_input_tokens or 0; usage[3] += u.cache_creation_input_tokens or 0
            messages.append({"role": "assistant",
                            "content": [b.model_dump(exclude_none=True) for b in response.content]})
            if response.stop_reason != "tool_use": break

            blocks = [b for b in response.content if b.type == "tool_use"]
            pairs = [dispatch(b, ws, bash_timeout) for b in blocks]
            for step, _ in pairs: yield step
            outputs = await asyncio.gather(*(c for _, c in pairs), return_exceptions=True)

            results = []
            for block, out in zip(blocks, outputs):
                if isinstance(out, BaseException): out = f"Error: {out}"
                if isinstance(out, str) and "timed out" in out:
                    yield {"type": "callout", "callout": out, "style": "warning"}
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            messages.append({"role": "user", "content": results})
            if hp: save_history(hp, messages[saved:]); saved = len(messages)

        except Exception as e:
            if _is_retryable(e) and retries < MAX_RETRIES:
                retries += 1
                delay = _retry_delay(retries, e)
                yield {"type": "step", "step": f"Rate limited, retrying in {delay:.1f}s... (attempt {retries}/{MAX_RETRIES})"}
                await asyncio.sleep(delay); continue
            if not _recover(e, messages):
                yield {"type": "callout", "callout": str(e), "style": "error"}; break
            if hp: save_history(hp, messages[saved:]); saved = len(messages)
            continue

    # Finalize: save any unsaved messages
    if hp and saved < len(messages):
        save_history(hp, messages[saved:])
    if show_usage and usage[0]:
        p = next((v for k, v in _PRICING.items() if k in model), None)
        elapsed = time.monotonic() - t0
        m, s = divmod(int(elapsed), 60)
        t = f"{m}m {s}s" if m else f"{s}s"
        parts = [f"in: {usage[0]:,}", f"out: {usage[1]:,}", f"cached: {usage[2]:,}", f"cache-create: {usage[3]:,}"]
        if p:
            cost = (usage[0] * p[0] + usage[1] * p[1] + usage[2] * p[2] + usage[3] * p[3]) / 1_000_000
            parts.append(f"cost: ${cost:.4f}")
        parts.append(f"time: {t}")
        yield "\n\n*" + " · ".join(parts) + "*"

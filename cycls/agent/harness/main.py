"""Agent loop — streams Claude tool-use turns with sandboxed execution."""
import asyncio, json, random, time
from ..state import ensure_workspace, history_path, load_history, save_history
from .compact import COMPACT_BUFFER, KEEP_RECENT, compact, context_window
from .prompts import DEFAULT_SYSTEM
from .tools import build_tools, dispatch, _exec_read

# ---- Client routing ----

def _make_client(model, base_url=None, api_key=None):
    """Pick the provider client from a `provider/model` string. Anthropic
    routes native; everything else (openai, groq, humain, vllm, local) routes
    through the OpenAI Chat Completions adapter — the lingua franca of every
    non-Anthropic provider."""
    if "/" not in model:
        raise ValueError(
            f"model must be `provider/model` (e.g. `anthropic/claude-sonnet-4-6`, "
            f"`openai/gpt-5.4`, `groq/llama-3.3-70b`); got {model!r}"
        )
    provider = model.split("/", 1)[0]
    if provider == "anthropic":
        import anthropic
        return anthropic.AsyncAnthropic(**({"api_key": api_key} if api_key else {}))
    from .openai import AsyncOpenAI
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


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

async def _run(*, context, system="", tools=None, allowed_tools=[],
               model="anthropic/claude-sonnet-4-20250514", max_tokens=16384,
               bash_timeout=600, bash_network=False, show_usage=False, client=None,
               base_url=None, api_key=None, handlers=None):
    t0 = time.monotonic()
    if client is None:
        client = _make_client(model, base_url=base_url, api_key=api_key)
    model = model.split("/", 1)[1]
    ws = context.workspace().root
    ensure_workspace(ws)
    hp = history_path(context.user, context.session_id) if context.session_id and context.user else None
    messages = load_history(hp) if hp else []
    # Heal trailing orphan tool_use left by a prior interrupted turn — else Anthropic 400s.
    if messages and messages[-1].get("role") == "assistant" and isinstance(messages[-1].get("content"), list):
        ids = [b["id"] for b in messages[-1]["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
        if ids:
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": i, "content": "[Interrupted]", "is_error": True} for i in ids
            ]})
    saved = len(messages)
    incoming = context.messages.raw[-1].get("content", "")
    messages.append({"role": "user", "content": await _ingest(incoming, ws)})
    window = context_window(model)

    kwargs = {
        "model": model, "max_tokens": max_tokens,
        "tools": build_tools(allowed_tools, tools or []),
        "messages": messages,
        "system": [{"type": "text", "text": DEFAULT_SYSTEM + ("\n\n" + system if system else ""),
                     "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        "thinking": {"type": "adaptive"},
    }
    usage = [0, 0, 0, 0]  # in, out, cached, cache_create
    tokens_since_compact = 0
    retries = 0

    while True:
        try:
            if tokens_since_compact > window - COMPACT_BUFFER and len(messages) > KEEP_RECENT:
                yield {"type": "step", "step": "Compacting context..."}
                try:
                    messages[:] = await compact(client, model, messages)
                    tokens_since_compact = 0
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
            tokens_since_compact = u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
            messages.append({"role": "assistant",
                            "content": [b.model_dump(exclude_none=True) for b in response.content]})
            if response.stop_reason != "tool_use": break

            blocks = [b for b in response.content if b.type == "tool_use"]
            pairs = [dispatch(b, ws, bash_timeout, handlers, network=bash_network) for b in blocks]
            for step, _ in pairs: yield step
            outputs = await asyncio.gather(*(c for _, c in pairs), return_exceptions=True)

            results = []
            for block, out in zip(blocks, outputs):
                if isinstance(out, BaseException): out = f"Error: {out}"
                if isinstance(out, str) and "timed out" in out:
                    yield {"type": "callout", "callout": out, "style": "warning"}
                # Custom-handler results flow through the stream for the body to see
                # (UI rendering) AND serialize into tool_result for the model (data).
                if handlers and block.name in handlers and not isinstance(out, BaseException):
                    yield out
                    content = out if isinstance(out, str) else json.dumps(out, default=str)
                else:
                    content = out
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
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



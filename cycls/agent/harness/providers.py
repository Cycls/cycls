"""LLM providers — wrap vendor clients behind one streaming interface.

Each provider exposes:
    .model              bare model name
    .context_window     token budget
    .stream(messages, system, tools, max_tokens, mcp_servers, thinking)
                        async-yields loop events (dicts / bare strings) then
                        exactly one Turn (loop-internal sentinel).
    .complete(messages, system, max_tokens) -> str
                        non-streaming one-shot (used by compaction).

The loop's message/tool shape is Anthropic's; OpenAI-side translates on the way
in. `make_provider("vendor/model", ...)` picks the right provider and reuses an
SDK client per vendor.
"""
import json

from . import events
from .events import Turn
from ..tools import tool_step


_CONTEXT_WINDOWS = {
    "claude-sonnet-4-6": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet": 200_000,
    "claude-opus": 200_000,
    "claude-haiku": 200_000,
}


def context_window(model):
    """Token budget for a bare model name. Exact match first, then longest
    family prefix that occurs in the name; 200k if unknown."""
    if model in _CONTEXT_WINDOWS: return _CONTEXT_WINDOWS[model]
    return next((v for k, v in _CONTEXT_WINDOWS.items() if k in model), 200_000)


# ---- Anthropic ----

def _strip_sidecars(messages):
    """Anthropic rejects unknown top-level keys per message — drop FE-only fields."""
    return [{k: v for k, v in m.items() if k in ("role", "content")} for m in messages]


class AnthropicProvider:
    def __init__(self, client, model):
        self._client = client
        self.model = model

    @property
    def context_window(self):
        return context_window(self.model)

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None, thinking="adaptive"):
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "tools": tools,
            "messages": _strip_sidecars(messages),
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        }
        if isinstance(thinking, int):
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking}
        elif thinking == "adaptive" and "haiku" not in self.model:
            kwargs["thinking"] = {"type": "adaptive"}
        if mcp_servers:
            kwargs["extra_body"] = {"mcp_servers": [s._spec() for s in mcp_servers]}
            kwargs["extra_headers"] = {"anthropic-beta": "mcp-client-2025-04-04"}

        tool_idx, search_idx, search_buf = {}, None, ""
        async with self._client.messages.stream(**kwargs) as stream:
            async for ev in stream:
                if ev.type == "content_block_start":
                    cb = ev.content_block
                    if cb.type == "server_tool_use" and cb.name == "web_search":
                        search_idx, search_buf = ev.index, ""
                    elif cb.type == "mcp_tool_use":
                        server = getattr(cb, "server_name", None) or "mcp"
                        yield events.step("", tool=f"{server} · {cb.name}")
                    elif cb.type == "tool_use":
                        tool_idx[ev.index] = cb.id
                        yield events.step("", tool=tool_step(cb.name, {})["tool_name"], id=cb.id)
                elif ev.type == "content_block_delta":
                    d = ev.delta
                    if d.type == "thinking_delta":
                        yield events.thinking(d.thinking)
                    elif d.type == "text_delta":
                        yield events.text(d.text)
                    elif d.type == "input_json_delta":
                        if ev.index == search_idx:
                            search_buf += d.partial_json
                        elif ev.index in tool_idx:
                            yield events.tool_args(tool_idx[ev.index], d.partial_json)
                elif ev.type == "content_block_stop" and ev.index == search_idx:
                    try: q = json.loads(search_buf).get("query", "")
                    except Exception: q = ""
                    yield events.step(q, tool="Web Search")
                    search_idx = None
            resp = await stream.get_final_message()
        u = resp.usage
        yield Turn(
            content=[b.model_dump(exclude_none=True) for b in resp.content],
            stop_reason=resp.stop_reason,
            input=u.input_tokens, output=u.output_tokens,
            cached=u.cache_read_input_tokens or 0,
            cache_create=u.cache_creation_input_tokens or 0,
        )

    async def complete(self, *, messages, system, max_tokens):
        r = await self._client.messages.create(
            model=self.model, max_tokens=max_tokens,
            system=[{"type": "text", "text": system}], messages=messages)
        return r.content[0].text


# ---- OpenAI-compatible (Chat Completions: OpenAI, Groq, vLLM, ...) ----

def _tool_result_text(content):
    """Anthropic tool_result content → OpenAI tool-message text (text-only).
    Returns (text, dropped_kinds) so the caller can warn about elided blocks."""
    if isinstance(content, str): return content, set()
    if not isinstance(content, list): return json.dumps(content), set()
    parts, dropped = [], set()
    for x in content:
        if not isinstance(x, dict): continue
        t = x.get("type")
        if t == "text": parts.append(x.get("text", ""))
        elif t in ("image", "document"):
            dropped.add(t)
            parts.append(f"[{t} content not viewable on this provider]")
    return "".join(parts), dropped


def _to_oai(messages, system):
    """Anthropic messages → OpenAI messages, prepending system. Returns
    (messages, dropped_kinds_in_tool_results)."""
    out, dropped = [], set()
    for m in messages:
        role, content = m["role"], m.get("content", "")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
        elif role == "user":
            parts, tools = [], []
            for b in content:
                t = b.get("type")
                if t == "text":
                    parts.append({"type": "text", "text": b["text"]})
                elif t == "image":
                    src = b.get("source", {})
                    if src.get("type") == "base64":
                        parts.append({"type": "image_url", "image_url": {
                            "url": f"data:{src['media_type']};base64,{src['data']}"}})
                elif t == "tool_result":
                    text, d = _tool_result_text(b.get("content"))
                    dropped |= d
                    tools.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": text})
            out.extend(tools)
            if parts:
                out.append({"role": "user", "content": parts})
        elif role == "assistant":
            text, calls = "", []
            for b in content:
                t = b.get("type")
                if t == "text":
                    text += b.get("text", "")
                elif t == "tool_use":
                    calls.append({"id": b["id"], "type": "function", "function": {
                        "name": b["name"], "arguments": json.dumps(b.get("input", {}))}})
            msg = {"role": "assistant", "content": text or None}
            if calls: msg["tool_calls"] = calls
            out.append(msg)
    s = system if isinstance(system, str) else (
        "\n\n".join(s.get("text", "") for s in system if isinstance(s, dict))
        if isinstance(system, list) else "")
    if s: out.insert(0, {"role": "system", "content": s})
    return out, dropped


def _to_oai_tools(tools):
    """Anthropic tools → OpenAI functions. Drops Anthropic server tools."""
    return [
        {"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
        for t in (tools or []) if not t.get("type", "").startswith("web_search")
    ]


class OpenAIProvider:
    def __init__(self, client, model):
        self._client = client
        self.model = model

    @property
    def context_window(self):
        return context_window(self.model)

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None, thinking=None):
        oa_messages, dropped = _to_oai(messages, system)
        for kind in sorted(dropped):
            yield events.callout(f"`{kind}` content in tool results isn't viewable on this provider — the model sees a text stub.", "warning")
        if mcp_servers:
            yield events.callout("MCP servers are Anthropic-only — ignored on this provider.", "warning")

        kwargs = {
            "model": self.model, "messages": oa_messages,
            "max_completion_tokens": max_tokens,
            "stream": True, "stream_options": {"include_usage": True},
        }
        if (oa_tools := _to_oai_tools(tools)): kwargs["tools"] = oa_tools

        text_buf, calls, stop, usage = [], {}, "end_turn", None
        async for chunk in await self._client.chat.completions.create(**kwargs):
            if chunk.usage: usage = chunk.usage
            if not chunk.choices: continue
            d = chunk.choices[0].delta
            if d.content:
                text_buf.append(d.content)
                yield events.text(d.content)
            if (r := getattr(d, "reasoning", None) or getattr(d, "reasoning_content", None)):
                yield events.thinking(r)
            for tc in (d.tool_calls or []):
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": "", "started": False})
                if tc.id: slot["id"] = tc.id
                arg_chunk = ""
                if tc.function:
                    slot["name"] += tc.function.name or ""
                    arg_chunk = tc.function.arguments or ""
                    slot["args"] += arg_chunk
                if not slot["started"] and slot["id"] and slot["name"]:
                    slot["started"] = True
                    yield events.step("", tool=tool_step(slot["name"], {})["tool_name"], id=slot["id"])
                    if slot["args"]:
                        yield events.tool_args(slot["id"], slot["args"])
                elif slot["started"] and arg_chunk:
                    yield events.tool_args(slot["id"], arg_chunk)
            if chunk.choices[0].finish_reason:
                stop = "tool_use" if chunk.choices[0].finish_reason == "tool_calls" else "end_turn"

        content = [{"type": "text", "text": "".join(text_buf)}] if text_buf else []
        for _, tc in sorted(calls.items()):
            try: inp = json.loads(tc["args"]) if tc["args"] else {}
            except json.JSONDecodeError: inp = {}
            content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": inp})
        yield Turn(content=content, stop_reason=stop,
                   input=(usage.prompt_tokens if usage else 0),
                   output=(usage.completion_tokens if usage else 0))

    async def complete(self, *, messages, system, max_tokens):
        oa_messages, _ = _to_oai(messages, system)
        r = await self._client.chat.completions.create(
            model=self.model, max_completion_tokens=max_tokens, messages=oa_messages)
        return r.choices[0].message.content or ""


# ---- Client routing ----

_clients: dict = {}  # vendor → reused SDK client. Construction is ~1s (httpx + TLS).


def _client_for(vendor, *, base_url, api_key):
    if vendor in _clients: return _clients[vendor]
    if vendor == "anthropic":
        import anthropic
        c = anthropic.AsyncAnthropic(**({"api_key": api_key} if api_key else {}))
    else:
        import openai
        c = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
    _clients[vendor] = c
    return c


def make_provider(model, *, client=None, base_url=None, api_key=None):
    """Build the provider for a `vendor/model` string. `anthropic/*` goes native;
    everything else (openai, groq, vllm, local) goes through Chat Completions.
    Pass `client` to inject a pre-built SDK client (test seam)."""
    if "/" not in model:
        raise ValueError(
            f"model must be `vendor/model` (e.g. `anthropic/claude-sonnet-4-6`, "
            f"`openai/gpt-5.4`); got {model!r}"
        )
    vendor, name = model.split("/", 1)
    sdk = client or _client_for(vendor, base_url=base_url, api_key=api_key)
    if vendor == "anthropic": return AnthropicProvider(sdk, name)
    return OpenAIProvider(sdk, name)

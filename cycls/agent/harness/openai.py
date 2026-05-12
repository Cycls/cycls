"""OpenAI Chat Completions provider.

Same interface as `providers.Provider` (`.model`, `.context_window`, `.stream`,
`.complete`) — talks Chat Completions instead of the Anthropic Messages API, so
the loop runs unchanged against OpenAI, Groq, vLLM, Together, HUMAIN, and any
other Chat Completions-compatible endpoint. The loop's message/tool shape is the
Anthropic shape; the translators below convert it on the way in.
"""
import json

from .events import TextDelta, Thinking, Turn
from .providers import context_window


def _to_messages(messages):
    """Anthropic messages → OpenAI messages. tool_result blocks become
    role=tool messages; assistant tool_use blocks become assistant.tool_calls."""
    out = []
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
                    c = b.get("content")
                    if isinstance(c, list):
                        c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
                    if not isinstance(c, str):
                        c = json.dumps(c)
                    tools.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": c})
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
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
    return out


def _to_system(system):
    """Anthropic system (string, or list of cache-controlled blocks) → string."""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(s.get("text", "") for s in system if isinstance(s, dict))
    return ""


def _to_tools(tools):
    """Anthropic tools → OpenAI functions. Drops Anthropic server tools
    (web_search etc.) — no Chat Completions equivalent."""
    return [
        {"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""),
            "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
        for t in (tools or []) if not t.get("type", "").startswith("web_search")
    ]


def _prepend_system(messages, system):
    out = _to_messages(messages)
    if (s := _to_system(system)):
        out.insert(0, {"role": "system", "content": s})
    return out


class OpenAIProvider:
    def __init__(self, client, model):
        self._client = client
        self.model = model

    @property
    def context_window(self):
        return context_window(self.model)

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None):
        kwargs = {
            "model": self.model,
            "messages": _prepend_system(messages, system),
            "max_completion_tokens": max_tokens,
            "stream": True, "stream_options": {"include_usage": True},
        }
        if (oa_tools := _to_tools(tools)):
            kwargs["tools"] = oa_tools
        # `thinking` / `cache_control` / `mcp_servers` have no Chat Completions
        # equivalent — silently dropped.

        text, calls, stop, usage = [], {}, "end_turn", None
        async for chunk in await self._client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            ch = chunk.choices[0]
            d = ch.delta
            if d.content:
                text.append(d.content)
                yield TextDelta(d.content)
            # `reasoning` is the modern field; `reasoning_content` the legacy
            # DeepSeek/old-vLLM name. Both surface as thinking bubbles.
            if (r := getattr(d, "reasoning", None) or getattr(d, "reasoning_content", None)):
                yield Thinking(r)
            for tc in (d.tool_calls or []):
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    slot["name"] += tc.function.name or ""
                    slot["args"] += tc.function.arguments or ""
            if ch.finish_reason:
                stop = "tool_use" if ch.finish_reason == "tool_calls" else "end_turn"

        content = [{"type": "text", "text": "".join(text)}] if text else []
        for _, tc in sorted(calls.items()):
            try:
                inp = json.loads(tc["args"]) if tc["args"] else {}
            except json.JSONDecodeError:
                inp = {}
            content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": inp})
        yield Turn(content=content, stop_reason=stop,
                   input=(usage.prompt_tokens if usage else 0),
                   output=(usage.completion_tokens if usage else 0))

    async def complete(self, *, messages, system, max_tokens):
        r = await self._client.chat.completions.create(
            model=self.model, max_completion_tokens=max_tokens,
            messages=_prepend_system(messages, system))
        return r.choices[0].message.content or ""

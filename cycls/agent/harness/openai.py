"""OpenAI Chat Completions provider.

Same interface as `providers.Provider` (`.model`, `.context_window`, `.stream`,
`.complete`) — talks Chat Completions instead of the Anthropic Messages API, so
the loop runs unchanged against OpenAI, Groq, vLLM, Together, HUMAIN, and any
other Chat Completions-compatible endpoint. The loop's message/tool shape is the
Anthropic shape; the translators below convert it on the way in.
"""
import json

from .events import TextDelta, Thinking, ToolStart, ToolArgs, Turn, Callout
from .providers import context_window
from ..tools import tool_step


def _tool_result_content(content):
    """Render a tool_result's content blocks into the text-only form OpenAI
    tool messages accept. Returns (text, dropped_kinds). Image/document blocks
    can't be carried in OpenAI tool messages — surface them as text stubs so the
    model knows something was elided, and report the kinds so the caller can
    warn the user."""
    if isinstance(content, str):
        return content, set()
    if not isinstance(content, list):
        return json.dumps(content), set()
    parts, dropped = [], set()
    for x in content:
        if not isinstance(x, dict):
            continue
        t = x.get("type")
        if t == "text":
            parts.append(x.get("text", ""))
        elif t in ("image", "document"):
            dropped.add(t)
            parts.append(f"[{t} content not viewable on this provider]")
    return "".join(parts), dropped


def _to_messages(messages):
    """Anthropic messages → OpenAI messages. Returns (messages, dropped_kinds).
    tool_result blocks become role=tool messages; assistant tool_use blocks
    become assistant.tool_calls. Image/document blocks inside tool_results get a
    text stub (OpenAI tool messages are text-only) and the kinds are returned
    so the caller can warn — no simulation, no follow-up-user trick."""
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
                    text, d = _tool_result_content(b.get("content"))
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
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
    return out, dropped


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
    out, dropped = _to_messages(messages)
    if (s := _to_system(system)):
        out.insert(0, {"role": "system", "content": s})
    return out, dropped


class OpenAIProvider:
    def __init__(self, client, model):
        self._client = client
        self.model = model

    @property
    def context_window(self):
        return context_window(self.model)

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None, thinking=None):
        oa_messages, dropped = _prepend_system(messages, system)
        for kind in sorted(dropped):
            yield Callout(f"`{kind}` content in tool results isn't viewable on this provider — the model sees a text stub.", "warning")
        if mcp_servers:
            yield Callout("MCP servers are Anthropic-only — ignored on this provider.", "warning")
        kwargs = {
            "model": self.model,
            "messages": oa_messages,
            "max_completion_tokens": max_tokens,
            "stream": True, "stream_options": {"include_usage": True},
        }
        if (oa_tools := _to_tools(tools)):
            kwargs["tools"] = oa_tools
        # `thinking` / `cache_control` have no Chat Completions equivalent —
        # silently dropped (the `thinking` kwarg is accepted just so the loop's
        # signature is provider-agnostic).

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
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": "", "started": False})
                if tc.id:
                    slot["id"] = tc.id
                arg_chunk = ""
                if tc.function:
                    slot["name"] += tc.function.name or ""
                    arg_chunk = tc.function.arguments or ""
                    slot["args"] += arg_chunk
                if not slot["started"] and slot["id"] and slot["name"]:
                    slot["started"] = True
                    yield ToolStart(slot["id"], tool_step(slot["name"], {})["tool_name"])
                    if slot["args"]:
                        yield ToolArgs(slot["id"], slot["args"])
                elif slot["started"] and arg_chunk:
                    yield ToolArgs(slot["id"], arg_chunk)
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
        oa_messages, _ = _prepend_system(messages, system)  # internal: no UI to warn into
        r = await self._client.chat.completions.create(
            model=self.model, max_completion_tokens=max_tokens, messages=oa_messages)
        return r.choices[0].message.content or ""

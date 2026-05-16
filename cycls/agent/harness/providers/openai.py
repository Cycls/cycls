"""OpenAI Chat Completions provider — also serves Groq, vLLM, Together, any
endpoint speaking Chat Completions.

Translates cycls Message shape (Anthropic JSON) ↔ OpenAI Chat Completions:
  - assistant tool_use blocks ↔ assistant.tool_calls
  - user tool_result blocks ↔ role="tool" messages (text-only)
  - image/document in tool_results → text stubs (with a warning)
"""
import json

from .. import events
from ..events import Turn
from ...tools import tool_step


_WINDOWS = {
    "gpt-5":  400_000,
    "gpt-4o": 128_000,
    "gpt-4":  128_000,
    "o1":     200_000,
    "o3":     200_000,
}


class OpenAIProvider:
    def __init__(self, client, model):
        self._client = client
        self.model = model

    @property
    def context_window(self):
        """Exact match first, then longest family prefix in the name; 128k default
        (covers most modern Chat-Completions-compatible models)."""
        if self.model in _WINDOWS: return _WINDOWS[self.model]
        return next((v for k, v in _WINDOWS.items() if k in self.model), 128_000)

    @staticmethod
    def _tool_result_text(content):
        """tool_result content → text-only string (OpenAI tool messages are
        text-only). Returns (text, dropped_kinds) so callers can warn."""
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

    def _to_messages(self, messages, system):
        """cycls Messages → OpenAI Chat Completions messages, prepending system.
        Returns (api_messages, dropped_kinds_in_tool_results)."""
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
                        text, d = self._tool_result_text(b.get("content"))
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

    def _to_tools(self, tools):
        """cycls tools → OpenAI functions. Drops Anthropic server tools."""
        return [
            {"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
            for t in (tools or []) if not t.get("type", "").startswith("web_search")
        ]

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None, thinking=None):
        api_messages, dropped = self._to_messages(messages, system)
        for kind in sorted(dropped):
            yield events.callout(f"`{kind}` content in tool results isn't viewable on this provider — the model sees a text stub.", "warning")
        if mcp_servers:
            yield events.callout("MCP servers are Anthropic-only — ignored on this provider.", "warning")

        kwargs = {
            "model": self.model, "messages": api_messages,
            "max_completion_tokens": max_tokens,
            "stream": True, "stream_options": {"include_usage": True},
        }
        if (api_tools := self._to_tools(tools)): kwargs["tools"] = api_tools

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
        api_messages, _ = self._to_messages(messages, system)
        r = await self._client.chat.completions.create(
            model=self.model, max_completion_tokens=max_tokens, messages=api_messages)
        return r.choices[0].message.content or ""

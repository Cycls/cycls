"""Anthropic Messages provider.

Translation is near-identity: cycls Message shape *is* the Anthropic JSON
shape, so messages pass through (only storage-only sidecars stripped).
Output Turn carries content blocks in the same shape — sessions.py can
persist them directly without conversion.
"""
import json

from .. import events
from ..events import Turn
from . import context_window
from ...tools import tool_step


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

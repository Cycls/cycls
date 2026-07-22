"""Anthropic Messages provider.

cycls Message shape IS Anthropic's JSON shape, so translation is near-identity:
strip storage-only sidecars on the way out; output Turn content blocks pass
through to sessions.py for direct persistence.
"""
import json

from .. import events
from ..events import Turn
from ...tools import tool_step


# Cache breakpoint applied to system prompt, last tool, and last user-message
# tail block. Three of Anthropic's four available breakpoints; each marks the
# END of a cacheable prefix. ttl 1h matches the persistence we want for chat
# sessions (5min is the free default — wire a knob if turns straddle 5min).
_CACHE = {"type": "ephemeral", "ttl": "1h"}


class AnthropicProvider:
    def __init__(self, client, model):
        self._client = client
        self.model = model

    def _to_messages(self, messages):
        """Drop FE-only sidecars; attach `cache_control` to the last user
        message's tail block so the entire conversation prefix is cacheable."""
        out = [{k: v for k, v in m.items() if k in ("role", "content")} for m in messages]
        for i in range(len(out) - 1, -1, -1):
            if out[i]["role"] != "user": continue
            c = out[i]["content"]
            if isinstance(c, str):
                out[i]["content"] = [{"type": "text", "text": c, "cache_control": _CACHE}]
            elif isinstance(c, list) and c:
                out[i]["content"] = [*c[:-1], {**c[-1], "cache_control": _CACHE}]
            break
        return out

    def _to_tools(self, tools):
        """Attach `cache_control` to the last tool so the entire tool-definition
        block is cacheable."""
        if not tools: return []
        return [*tools[:-1], {**tools[-1], "cache_control": _CACHE}]

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None, thinking="adaptive"):
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "tools": self._to_tools(tools),
            "messages": self._to_messages(messages),
            "system": [{"type": "text", "text": system, "cache_control": _CACHE}],
        }
        if isinstance(thinking, int):
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking}
        elif thinking in ("low", "medium", "high") and "haiku" not in self.model:
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["extra_body"] = {"output_config": {"effort": thinking}}
        elif thinking == "adaptive" and "haiku" not in self.model:
            kwargs["thinking"] = {"type": "adaptive"}
        if mcp_servers:
            kwargs.setdefault("extra_body", {})["mcp_servers"] = [s._spec() for s in mcp_servers]
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
        self.last_usage = (r.usage.input_tokens, r.usage.output_tokens)
        return r.content[0].text

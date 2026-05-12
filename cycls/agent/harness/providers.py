"""LLM provider — wraps a model client behind one streaming interface.

`Provider.stream(...)` yields typed loop events as content arrives, then a
final `Turn` carrying the assistant's content blocks (storage shape), the stop
reason, and token usage. `Provider.complete(...)` is the non-streaming one-shot
(used by compaction). Today there is one wire shape — the Anthropic Messages
API — and the non-Anthropic OpenAI adapter (`cycls.agent.harness.openai`)
mimics it, so a single `Provider` class drives both. A later split gives
OpenAI/Google/etc. their own providers that emit these same events directly.
"""
import json

from .events import TextDelta, Thinking, Step, Heartbeat, Turn

_HEARTBEAT_EVERY = 10  # input_json_delta events between heartbeats — keeps SSE/UDP flows warm

_CONTEXT_WINDOWS = {
    "claude-sonnet-4-6": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet": 200_000,   # earlier 4.x
    "claude-opus": 200_000,
    "claude-haiku": 200_000,
}


def context_window(model):
    """Token budget for a bare model name. Exact match first, then longest
    family prefix that occurs in the name; 200k if unknown."""
    if model in _CONTEXT_WINDOWS:
        return _CONTEXT_WINDOWS[model]
    return next((v for k, v in _CONTEXT_WINDOWS.items() if k in model), 200_000)


def _for_api(messages):
    """Anthropic rejects unknown top-level keys per message — strip storage-only
    sidecars (e.g. the FE `attachments` block) before send."""
    return [{k: v for k, v in m.items() if k in ("role", "content")} for m in messages]


class Provider:
    """Wraps a client with the Anthropic Messages API shape (or the OpenAI
    adapter that mimics it)."""

    def __init__(self, client, model):
        self._client = client
        self.model = model

    @property
    def context_window(self):
        return context_window(self.model)

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None):
        """Yield content events as they arrive, then exactly one `Turn`."""
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "tools": tools,
            "messages": _for_api(messages),
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            "thinking": {"type": "adaptive"},
        }
        if mcp_servers:
            kwargs["extra_body"] = {"mcp_servers": [s._spec() for s in mcp_servers]}
            kwargs["extra_headers"] = {"anthropic-beta": "mcp-client-2025-04-04"}

        search_idx, search_buf, deltas = None, "", 0
        async with self._client.messages.stream(**kwargs) as stream:
            async for ev in stream:
                if ev.type == "content_block_start":
                    cb = ev.content_block
                    if cb.type == "server_tool_use" and cb.name == "web_search":
                        search_idx, search_buf = ev.index, ""
                    elif cb.type == "mcp_tool_use":
                        # Anthropic ran this server-side; just surface it as a step.
                        server = getattr(cb, "server_name", None) or "mcp"
                        yield Step("", tool=f"{server} · {cb.name}")
                elif ev.type == "content_block_delta":
                    d = ev.delta
                    if d.type == "thinking_delta":
                        yield Thinking(d.thinking)
                    elif d.type == "text_delta":
                        yield TextDelta(d.text)
                    elif d.type == "input_json_delta":
                        if ev.index == search_idx:
                            search_buf += d.partial_json
                        deltas += 1
                        if deltas % _HEARTBEAT_EVERY == 0:
                            yield Heartbeat()
                elif ev.type == "content_block_stop" and ev.index == search_idx:
                    try:
                        q = json.loads(search_buf).get("query", "")
                    except Exception:
                        q = ""
                    yield Step(q, tool="Web Search")
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
        """Non-streaming one-shot — returns the response text. Used by compaction."""
        r = await self._client.messages.create(
            model=self.model, max_tokens=max_tokens,
            system=[{"type": "text", "text": system}], messages=messages)
        return r.content[0].text

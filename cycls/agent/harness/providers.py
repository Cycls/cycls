"""LLM providers — each wraps a vendor client behind one streaming interface.

A provider exposes:

    .model                              the bare model name
    .context_window                     token budget for that model
    .stream(messages, system, tools, max_tokens, mcp_servers=None)
                                        async-iterates loop events as content
                                        arrives, then yields exactly one `Turn`
                                        (assistant content blocks in storage
                                        shape + stop_reason + token usage)
    .complete(messages, system, max_tokens) -> str
                                        non-streaming one-shot (used by compaction)

`make_provider("vendor/model", ...)` picks the right one. The loop's message and
tool shape is the Anthropic Messages shape; non-Anthropic providers translate it
(see `cycls.agent.harness.openai`). `AnthropicProvider` lives here; `prewarm()`
pays its client warmup at process start.
"""
import json

from .events import TextDelta, Thinking, Step, ToolStart, ToolArgs, Turn
from ..tools import tool_step

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


class AnthropicProvider:
    def __init__(self, client, model):
        self._client = client
        self.model = model

    @property
    def context_window(self):
        return context_window(self.model)

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None):
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

        tool_idx, search_idx, search_buf = {}, None, ""  # content-block index → tool_use id; the web_search block
        async with self._client.messages.stream(**kwargs) as stream:
            async for ev in stream:
                if ev.type == "content_block_start":
                    cb = ev.content_block
                    if cb.type == "server_tool_use" and cb.name == "web_search":
                        search_idx, search_buf = ev.index, ""
                    elif cb.type == "mcp_tool_use":
                        # Anthropic ran this server-side; surface it as a step.
                        server = getattr(cb, "server_name", None) or "mcp"
                        yield Step("", tool=f"{server} · {cb.name}")
                    elif cb.type == "tool_use":
                        # The model has committed to a tool call — tell the UI now,
                        # before the (maybe huge) arguments stream in.
                        tool_idx[ev.index] = cb.id
                        yield ToolStart(cb.id, tool_step(cb.name, {})["tool_name"])
                elif ev.type == "content_block_delta":
                    d = ev.delta
                    if d.type == "thinking_delta":
                        yield Thinking(d.thinking)
                    elif d.type == "text_delta":
                        yield TextDelta(d.text)
                    elif d.type == "input_json_delta":
                        if ev.index == search_idx:
                            search_buf += d.partial_json
                        elif ev.index in tool_idx:
                            yield ToolArgs(tool_idx[ev.index], d.partial_json)
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
        r = await self._client.messages.create(
            model=self.model, max_tokens=max_tokens,
            system=[{"type": "text", "text": system}], messages=messages)
        return r.content[0].text


# ---- Client routing ----

_clients: dict = {}  # vendor → reused SDK client. Construction is ~1s (httpx +
                     # TLS warmup); reuse is safe across requests.


def _client_for(vendor, *, base_url, api_key):
    if vendor in _clients:
        return _clients[vendor]
    if vendor == "anthropic":
        import anthropic
        c = anthropic.AsyncAnthropic(**({"api_key": api_key} if api_key else {}))
    else:
        import openai
        c = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
    _clients[vendor] = c
    return c


def prewarm():
    """Pay the Anthropic client's httpx + TLS warmup now (process start)."""
    _client_for("anthropic", base_url=None, api_key=None)


def make_provider(model, *, client=None, base_url=None, api_key=None):
    """Build the provider for a `vendor/model` string. `anthropic/*` goes
    native; everything else (openai, groq, humain, vllm, local) goes through the
    OpenAI Chat Completions provider — the lingua franca of every non-Anthropic
    vendor. Pass `client` to use a pre-built SDK client."""
    if "/" not in model:
        raise ValueError(
            f"model must be `vendor/model` (e.g. `anthropic/claude-sonnet-4-6`, "
            f"`openai/gpt-5.4`, `groq/llama-3.3-70b`); got {model!r}"
        )
    vendor, name = model.split("/", 1)
    sdk = client or _client_for(vendor, base_url=base_url, api_key=api_key)
    if vendor == "anthropic":
        return AnthropicProvider(sdk, name)
    from .openai import OpenAIProvider
    return OpenAIProvider(sdk, name)

"""LLM providers — each wraps a vendor SDK behind one streaming interface.

The cycls Message/Content shape is the Anthropic shape (the richest superset
across vendors). Each provider translates from this neutral shape to its own
wire format. Adding a new provider = one file conforming to `Provider`.

Public API:
    make_provider("vendor/model", ...) → Provider
    Provider                # the protocol
    Message, Block, Text, Thinking, Image, ToolUse, ToolResult    # cycls shape
"""
from typing import AsyncIterator, Literal, Protocol, TypedDict, Union


# ---- cycls Message shape (structurally identical to Anthropic's JSON) ----

class Text(TypedDict):
    type: Literal["text"]
    text: str

class Thinking(TypedDict, total=False):
    type: Literal["thinking"]
    thinking: str
    signature: str

class Image(TypedDict):
    type: Literal["image"]
    source: dict   # {"type": "base64", "media_type": "...", "data": "..."}

class ToolUse(TypedDict):
    type: Literal["tool_use"]
    id: str
    name: str
    input: dict

class ToolResult(TypedDict, total=False):
    type: Literal["tool_result"]
    tool_use_id: str
    content: Union[str, list]
    is_error: bool

Block = Union[Text, Thinking, Image, ToolUse, ToolResult]

class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: Union[str, list[Block]]


# ---- Provider protocol ----

class Provider(Protocol):
    model: str

    def stream(self, *, messages: list[Message], system: str, tools: list[dict],
               max_tokens: int, mcp_servers=None, thinking=None) -> AsyncIterator:
        """Yield loop events (dicts / bare strings); then exactly one Turn."""
        ...

    async def complete(self, *, messages: list[Message], system: str, max_tokens: int) -> str:
        """Non-streaming one-shot (used by compaction)."""
        ...


# ---- Client routing ----

_clients: dict = {}  # vendor → reused SDK client. Construction is ~1s (httpx + TLS).


def _client_for(vendor: str, *, base_url, api_key):
    if vendor in _clients: return _clients[vendor]
    if vendor == "anthropic":
        import anthropic
        c = anthropic.AsyncAnthropic(**({"api_key": api_key} if api_key else {}))
    else:
        import openai
        c = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
    _clients[vendor] = c
    return c


def make_provider(model: str, *, client=None, base_url=None, api_key=None,
                  vision=True) -> Provider:
    """Build the provider for a `vendor/model` string. `anthropic/*` goes native;
    everything else (openai, groq, vllm, local) goes through Chat Completions.
    Pass `client` to inject a pre-built SDK client (test seam). `vision=False`
    marks a text-only model: image blocks degrade to text stubs instead of
    being sent (and rejected) on the wire — no-op on the native Anthropic path."""
    if "/" not in model:
        raise ValueError(
            f"model must be `vendor/model` (e.g. `anthropic/claude-sonnet-4-6`, "
            f"`openai/gpt-5.4`); got {model!r}"
        )
    vendor, name = model.split("/", 1)
    sdk = client or _client_for(vendor, base_url=base_url, api_key=api_key)
    if vendor == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(sdk, name)
    from .openai import OpenAIProvider
    return OpenAIProvider(sdk, name, vendor, vision=vision)


# Re-export concrete providers for type-checking / direct construction by callers
# that bypass make_provider (tests, custom loops). Lazy imports above avoid cycle.
def __getattr__(name):
    if name == "AnthropicProvider":
        from .anthropic import AnthropicProvider; return AnthropicProvider
    if name == "OpenAIProvider":
        from .openai import OpenAIProvider; return OpenAIProvider
    raise AttributeError(name)

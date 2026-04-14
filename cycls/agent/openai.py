"""OpenAI Chat Completions adapter.

Translates Anthropic-shaped calls to OpenAI Chat Completions and back, so the
Agent loop can run unchanged against OpenAI, Groq, vLLM, HUMAIN, and any other
Chat Completions-compatible endpoint.

Shape: exposes the same `.messages.stream(**kwargs)` surface that
`anthropic.AsyncAnthropic` exposes. Yields the same event objects that
`_iter_stream` consumes, and `get_final_message()` returns an object the
loop can destructure like an Anthropic response.
"""
import json
from types import SimpleNamespace


# ---- Translation: Anthropic-shaped → OpenAI-shaped ----

def _translate_messages(messages):
    """Anthropic messages → OpenAI messages. Tool results become role=tool
    messages; assistant tool_use blocks become assistant.tool_calls."""
    out = []
    for m in messages:
        role = m["role"]
        content = m.get("content", "")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if role == "user":
            parts, tool_results = [], []
            for b in content:
                t = b.get("type")
                if t == "text":
                    parts.append({"type": "text", "text": b["text"]})
                elif t == "image":
                    src = b.get("source", {})
                    if src.get("type") == "base64":
                        parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"},
                        })
                elif t == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
                    if not isinstance(c, str):
                        c = json.dumps(c)
                    tool_results.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": c})
            out.extend(tool_results)
            if parts:
                out.append({"role": "user", "content": parts})

        elif role == "assistant":
            text, tool_calls = "", []
            for b in content:
                t = b.get("type")
                if t == "text":
                    text += b.get("text", "")
                elif t == "tool_use":
                    tool_calls.append({
                        "id": b["id"],
                        "type": "function",
                        "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))},
                    })
            msg = {"role": "assistant", "content": text or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
    return out


def _translate_system(system):
    """Anthropic system (list of blocks with cache_control) → OpenAI system string."""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(s.get("text", "") for s in system if isinstance(s, dict))
    return ""


def _translate_tools(tools):
    """Anthropic tools → OpenAI functions. Drops Anthropic server tools
    (web_search etc) — those have no OpenAI equivalent."""
    out = []
    for t in (tools or []):
        if t.get("type", "").startswith("web_search"):
            continue
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


# ---- Response-shape objects the loop destructures ----

class _TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text
    def model_dump(self, exclude_none=True):
        return {"type": "text", "text": self.text}


class _ToolUseBlock:
    def __init__(self, id, name, input):
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input
    def model_dump(self, exclude_none=True):
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


# ---- Stream wrapper ----

class _Stream:
    """Context manager + async iterator. Matches anthropic.MessageStream's
    surface: `async with`, `async for event`, `await get_final_message()`."""

    def __init__(self, client, kwargs):
        self._client = client
        self._kwargs = kwargs
        self._final = None

    async def __aenter__(self):
        self._stream = await self._client.chat.completions.create(
            stream=True, stream_options={"include_usage": True}, **self._kwargs,
        )
        return self

    async def __aexit__(self, *exc):
        pass

    async def __aiter__(self):
        text_buf = []
        tool_calls = {}  # index → {id, name, arguments}
        stop_reason = "end_turn"
        usage = None

        async for chunk in self._stream:
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            if delta.content:
                text_buf.append(delta.content)
                yield SimpleNamespace(
                    type="content_block_delta",
                    index=0,
                    delta=SimpleNamespace(type="text_delta", text=delta.content),
                )

            # Reasoning deltas — GPT-5, o-series, and any OpenAI-compat reasoning
            # model (vLLM, DeepSeek, etc.). `reasoning` is the modern field;
            # `reasoning_content` is the legacy DeepSeek/old-vLLM name. Both map
            # to Cycls' thinking_delta channel so _iter_stream yields them as
            # regular thinking events and the UI shows thinking bubbles.
            reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
            if reasoning:
                yield SimpleNamespace(
                    type="content_block_delta",
                    index=0,
                    delta=SimpleNamespace(type="thinking_delta", thinking=reasoning),
                )

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments

            if choice.finish_reason:
                stop_reason = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"

        content = []
        if text_buf:
            content.append(_TextBlock("".join(text_buf)))
        for _, tc in sorted(tool_calls.items()):
            try:
                inp = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                inp = {}
            content.append(_ToolUseBlock(id=tc["id"], name=tc["name"], input=inp))

        self._final = SimpleNamespace(
            content=content,
            stop_reason=stop_reason,
            usage=SimpleNamespace(
                input_tokens=(usage.prompt_tokens if usage else 0),
                output_tokens=(usage.completion_tokens if usage else 0),
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    async def get_final_message(self):
        return self._final


class _Messages:
    def __init__(self, client):
        self._client = client

    def stream(self, **kwargs):
        oa_kwargs = {
            "model": kwargs["model"].split("/", 1)[-1] if "/" in kwargs["model"] else kwargs["model"],
            "messages": _translate_messages(kwargs["messages"]),
            "max_completion_tokens": kwargs.get("max_tokens", 4096),
        }
        system = _translate_system(kwargs.get("system", ""))
        if system:
            oa_kwargs["messages"].insert(0, {"role": "system", "content": system})
        tools = _translate_tools(kwargs.get("tools"))
        if tools:
            oa_kwargs["tools"] = tools
        # Anthropic `thinking` has no Chat Completions equivalent — silently dropped.
        # Anthropic `cache_control` lives on system/tool wrappers — already stripped by the translators.
        return _Stream(self._client, oa_kwargs)


class AsyncOpenAI:
    """Drop-in replacement for `anthropic.AsyncAnthropic`. Same surface, OpenAI
    Chat Completions underneath. Works against any Chat Completions-compatible
    endpoint: OpenAI, Groq, vLLM, Together, HUMAIN, local, etc."""

    def __init__(self, base_url=None, api_key=None):
        import openai
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.messages = _Messages(self._client)

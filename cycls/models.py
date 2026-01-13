"""Model abstraction for @cycls.agent() - multi-provider support."""

import os
import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional
import httpx

@dataclass
class ToolCall:
    """Represents a tool call from the model."""
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    """A message in the conversation."""
    role: str  # "user", "assistant", "system", "tool"
    content: str
    tool_calls: list[ToolCall] = None
    tool_call_id: str = None  # For tool results


def parse_model_string(model: str) -> tuple[str, str]:
    """Parse 'provider/model-name' into (provider, model)."""
    if '/' in model:
        provider, model_name = model.split('/', 1)
        return provider.lower(), model_name
    # Default to anthropic
    return "anthropic", model


class ModelClient:
    """Base class for model clients."""

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = None,
    ) -> AsyncIterator[dict]:
        """Stream a response from the model. Yields chunks with type: text/tool_call/done."""
        raise NotImplementedError


class AnthropicClient(ModelClient):
    """Client for Anthropic Claude models."""

    def __init__(self, model: str, api_key: str = None):
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = "https://api.anthropic.com/v1"

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = None,
    ) -> AsyncIterator[dict]:
        if not self.api_key:
            yield {"type": "error", "error": "ANTHROPIC_API_KEY not set. Set the environment variable or pass api_key."}
            return

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Convert tools to Anthropic format
        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func["description"],
                    "input_schema": func["parameters"],
                })

        # Convert messages to Anthropic format
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "system":
                continue  # Handle system separately
            if msg["role"] == "tool":
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id"),
                        "content": msg["content"],
                    }]
                })
            elif msg.get("tool_calls"):
                # Assistant message with tool calls
                content = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"]),
                    })
                anthropic_messages.append({"role": "assistant", "content": content})
            else:
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        payload = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": anthropic_messages,
            "stream": True,
        }

        if anthropic_tools:
            payload["tools"] = anthropic_tools

        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/messages",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    yield {"type": "error", "error": error.decode()}
                    return

                current_tool_id = None
                current_tool_name = None
                current_tool_input = ""

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        event = json.loads(data)
                    except:
                        continue

                    event_type = event.get("type")

                    if event_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            current_tool_id = block.get("id")
                            current_tool_name = block.get("name")
                            current_tool_input = ""

                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield {"type": "text", "text": delta.get("text", "")}
                        elif delta.get("type") == "input_json_delta":
                            current_tool_input += delta.get("partial_json", "")

                    elif event_type == "content_block_stop":
                        if current_tool_id and current_tool_name:
                            try:
                                args = json.loads(current_tool_input) if current_tool_input else {}
                            except:
                                args = {}
                            yield {
                                "type": "tool_call",
                                "id": current_tool_id,
                                "name": current_tool_name,
                                "arguments": args,
                            }
                            current_tool_id = None
                            current_tool_name = None
                            current_tool_input = ""

                    elif event_type == "message_stop":
                        yield {"type": "done"}


class OpenAIClient(ModelClient):
    """Client for OpenAI models."""

    def __init__(self, model: str, api_key: str = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = "https://api.openai.com/v1"

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = None,
    ) -> AsyncIterator[dict]:
        if not self.api_key:
            yield {"type": "error", "error": "OPENAI_API_KEY not set. Set the environment variable or pass api_key."}
            return

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Prepend system message if provided
        openai_messages = []
        if system:
            openai_messages.append({"role": "system", "content": system})

        for msg in messages:
            if msg["role"] == "system":
                continue
            openai_messages.append(msg)

        payload = {
            "model": self.model,
            "messages": openai_messages,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    yield {"type": "error", "error": error.decode()}
                    return

                tool_calls = {}  # id -> {name, arguments}

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        event = json.loads(data)
                    except:
                        continue

                    choices = event.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})

                    # Text content
                    if "content" in delta and delta["content"]:
                        yield {"type": "text", "text": delta["content"]}

                    # Tool calls
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls:
                                tool_calls[idx] = {
                                    "id": tc.get("id", ""),
                                    "name": "",
                                    "arguments": "",
                                }
                            if "id" in tc and tc["id"]:
                                tool_calls[idx]["id"] = tc["id"]
                            if "function" in tc:
                                if "name" in tc["function"]:
                                    tool_calls[idx]["name"] = tc["function"]["name"]
                                if "arguments" in tc["function"]:
                                    tool_calls[idx]["arguments"] += tc["function"]["arguments"]

                    # Check for finish
                    if choices[0].get("finish_reason"):
                        # Emit any accumulated tool calls
                        for tc in tool_calls.values():
                            if tc["name"]:
                                try:
                                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                                except:
                                    args = {}
                                yield {
                                    "type": "tool_call",
                                    "id": tc["id"],
                                    "name": tc["name"],
                                    "arguments": args,
                                }
                        yield {"type": "done"}


def get_client(model: str) -> ModelClient:
    """Get a model client for the given model string."""
    provider, model_name = parse_model_string(model)

    if provider == "anthropic":
        return AnthropicClient(model_name)
    elif provider == "openai":
        return OpenAIClient(model_name)
    else:
        raise ValueError(f"Unknown provider: {provider}. Supported: anthropic, openai")

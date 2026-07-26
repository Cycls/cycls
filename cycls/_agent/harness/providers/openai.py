"""OpenAI Chat Completions provider — also serves Groq, vLLM, Together, any
endpoint speaking Chat Completions.

Translates cycls Message shape (Anthropic JSON) ↔ OpenAI Chat Completions:
  - assistant tool_use blocks ↔ assistant.tool_calls
  - user tool_result blocks ↔ role="tool" messages (text-only)
  - images in tool_results → hoisted into the following user message on
    vision models (tool messages are text-only by spec); text stubs (with a
    warning) on vision=False. Documents in tool_results → stubs always.
  - user-content images → image_url data URLs; stubs on vision=False models
  - user-content documents → text stubs (no Chat Completions wire form)
"""
import json
import sys

from .. import events
from ..events import Turn
from ...tools import tool_step


def _thinking_kwargs(vendor, thinking):
    """Translate the unified .thinking() spec (None | "adaptive" | "low" |
    "medium" | "high") into the vendor's reasoning dialect. Unknown vendors get
    {} and the server default applies — control them via the model's own docs.
    Verified against vendor docs July 2026."""
    effort = thinking if thinking in ("low", "medium", "high") else None
    on = bool(thinking)   # None → off; "adaptive"/levels → on
    if vendor in ("zai", "zhipu", "zhipuai", "glm"):
        # binary toggle only, non-standard field
        return {"extra_body": {"thinking": {"type": "enabled" if on else "disabled"}}}
    if vendor == "deepseek":
        # V4: same toggle shape as GLM, plus a reasoning_effort level
        kw = {"extra_body": {"thinking": {"type": "enabled" if on else "disabled"}}}
        if effort: kw["reasoning_effort"] = effort
        return kw
    if vendor in ("qwen", "dashscope", "alibaba"):
        # Qwen3.x: enable_thinking bool + thinking_budget (tokens) in extra_body
        extra = {"enable_thinking": on}
        if effort:
            extra["thinking_budget"] = {"low": 4_096, "medium": 16_384, "high": 32_768}[effort]
        return {"extra_body": extra}
    if vendor in ("kimi", "moonshot", "moonshotai"):
        # K3 tiers are low/high/max (server default max); can't be disabled
        return {"reasoning_effort": {"low": "low", "medium": "high", "high": "max"}[effort]} if effort else {}
    if vendor == "openrouter":
        # aggregator normalizes to a `reasoning` object
        return {"extra_body": {"reasoning": {"effort": effort}}} if effort else {}
    if vendor in ("openai", "azure", "google", "gemini", "xai", "grok",
                  "mistral", "mistralai", "groq", "perplexity"):
        # the de-facto standard: top-level reasoning_effort low/medium/high
        # (gpt-5*/o*, Azure OpenAI, Gemini-compat, Grok 4.5, Mistral Small 4+,
        # Groq-hosted, Perplexity)
        return {"reasoning_effort": effort} if effort else {}
    return {}


class OpenAIProvider:
    def __init__(self, client, model, vendor="openai", vision=True):
        self._client = client
        self.model = model
        self.vendor = vendor
        self.vision = vision

    @staticmethod
    def _tool_result_text(content, vision=False):
        """tool_result content → (text, dropped_kinds, images). OpenAI tool
        messages are text-only by spec; on vision models the image blocks are
        returned so the caller can hoist them into the user message that
        follows the tool responses — the model then actually sees them."""
        if isinstance(content, str): return content, set(), []
        if not isinstance(content, list): return json.dumps(content), set(), []
        parts, dropped, images = [], set(), []
        for x in content:
            if not isinstance(x, dict): continue
            t = x.get("type")
            if t == "text": parts.append(x.get("text", ""))
            elif t == "image" and vision and x.get("source", {}).get("type") == "base64":
                images.append(x["source"])
                parts.append("[image attached — it follows in the next user message]")
            elif t == "document":
                dropped.add(t)
                parts.append("[PDF can't be sent inline on this provider — call `read` "
                             "again with the pages parameter (e.g. pages='1-5') to view "
                             "it as page images]" if vision else
                             "[document content not viewable on this provider — extract "
                             "its text with bash instead]")
            elif t == "image":
                dropped.add(t)
                parts.append("[image content not viewable on this provider]")
        return "".join(parts), dropped, images

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
                        # Strict endpoints (GLM) reject empty text parts.
                        if b.get("text"): parts.append({"type": "text", "text": b["text"]})
                    elif t == "image" and self.vision:
                        src = b.get("source", {})
                        if src.get("type") == "base64":
                            parts.append({"type": "image_url", "image_url": {
                                "url": f"data:{src['media_type']};base64,{src['data']}"}})
                    elif t == "document":
                        # No Chat Completions wire form — stub with a way forward:
                        # the ingest frames uploads with [Attached: <name>], so the
                        # model knows which workspace file to open.
                        dropped.add(t)
                        parts.append({"type": "text", "text":
                            "[this document can't be sent inline on this provider — it's "
                            "saved in the workspace; use `read` with pages='1-5' to view "
                            "it as page images, or extract its text with bash]" if self.vision else
                            "[this document can't be viewed by this model — it's saved in "
                            "the workspace; extract its text with bash]"})
                    elif t == "image":
                        # Text-only model (vision=False) — stub instead of a 400.
                        dropped.add(t)
                        parts.append({"type": "text",
                                      "text": "[image content not viewable on this provider]"})
                    elif t == "tool_result":
                        text, d, imgs = self._tool_result_text(b.get("content"), vision=self.vision)
                        dropped |= d
                        tools.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": text})
                        # hoisted images ride in the user message after the tool responses
                        parts.extend({"type": "image_url", "image_url": {
                            "url": f"data:{src['media_type']};base64,{src['data']}"}}
                            for src in imgs)
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
                if text or calls: out.append(msg)  # thinking-only turns have no wire form here
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

    async def stream(self, *, messages, system, tools, max_tokens, mcp_servers=None,
                     thinking=None, extra_body=None):
        api_messages, dropped = self._to_messages(messages, system)
        # Capability limits are logged, never shown in chat — the model gets an
        # actionable stub in-context and works around it with tools.
        for kind in sorted(dropped):
            print(f"[provider] {kind} content stubbed for {self.vendor}/{self.model}",
                  file=sys.stderr, flush=True)
        if mcp_servers:
            print(f"[provider] MCP servers are Anthropic-only — ignored on {self.vendor}/{self.model}",
                  file=sys.stderr, flush=True)

        kwargs = {
            "model": self.model, "messages": api_messages,
            "stream": True, "stream_options": {"include_usage": True},
        }
        # OpenAI's reasoning models require `max_completion_tokens`; everyone
        # else speaks the standard `max_tokens`.
        kwargs["max_completion_tokens" if self.vendor == "openai" else "max_tokens"] = max_tokens
        if (api_tools := self._to_tools(tools)): kwargs["tools"] = api_tools
        kwargs.update(_thinking_kwargs(self.vendor, thinking))
        if extra_body:
            # merged last — deployer keys win, even over top-level params
            kwargs["extra_body"] = {**kwargs.get("extra_body", {}), **extra_body}

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
                stop = {"tool_calls": "tool_use", "length": "max_tokens"}.get(
                    chunk.choices[0].finish_reason, "end_turn")

        content = [{"type": "text", "text": "".join(text_buf)}] if text_buf else []
        for _, tc in sorted(calls.items()):
            try: inp = json.loads(tc["args"]) if tc["args"] else {}
            except json.JSONDecodeError: inp = {}
            content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": inp})
        # Server-side caching is automatic on these providers; report the cached
        # split so cost prices it at the cache-read rate. prompt_tokens INCLUDES
        # cached tokens (unlike Anthropic's input_tokens, which excludes them).
        # Kimi/Moonshot reports `cached_tokens` at the top level of usage.
        cached = (getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
                  or getattr(usage, "cached_tokens", 0) or 0) if usage else 0
        yield Turn(content=content, stop_reason=stop,
                   input=(usage.prompt_tokens - cached if usage else 0),
                   output=(usage.completion_tokens if usage else 0),
                   cached=cached)

    async def complete(self, *, messages, system, max_tokens):
        api_messages, _ = self._to_messages(messages, system)
        cap = {"max_completion_tokens" if self.vendor == "openai" else "max_tokens": max_tokens}
        r = await self._client.chat.completions.create(
            model=self.model, messages=api_messages, **cap)
        if r.usage: self.last_usage = (r.usage.prompt_tokens, r.usage.completion_tokens)
        return r.choices[0].message.content or ""

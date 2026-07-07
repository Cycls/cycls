"""Harness tests — _resolve_path escape hardening, build_tools scoping,
LLM builder plumbing."""
import asyncio
import pytest

import cycls
from cycls.agent.tools import _resolve_path, build_tools, vendor_skips


# ---- _resolve_path escape hardening ----

def test_tools_resolve_path_rejects_cycls(tmp_path):
    (tmp_path / ".db").mkdir()
    with pytest.raises(ValueError, match=".db/"):
        _resolve_path("/workspace/.db/usage.json", tmp_path)
    with pytest.raises(ValueError, match=".db/"):
        _resolve_path(".db", tmp_path)


def test_tools_resolve_path_rejects_agent_database(tmp_path):
    """The agent's KV store (.database/) must not be touchable via editor —
    the agent uses the `database` tool, not raw read/edit on SST files."""
    (tmp_path / ".database").mkdir()
    with pytest.raises(ValueError, match=".database/"):
        _resolve_path("/workspace/.database/manifest", tmp_path)
    with pytest.raises(ValueError, match=".database/"):
        _resolve_path(".database", tmp_path)


def test_resolve_path_rejects_dotdot_escape(tmp_path):
    """Relative `..` must not escape the workspace root."""
    with pytest.raises(ValueError, match="escapes workspace"):
        _resolve_path("../etc/passwd", tmp_path)


def test_resolve_path_rejects_workspace_prefix_escape(tmp_path):
    """`/workspace/../etc/passwd` must not resolve outside the workspace
    just because it carries the /workspace/ prefix."""
    with pytest.raises(ValueError, match="escapes workspace"):
        _resolve_path("/workspace/../etc/passwd", tmp_path)


def test_resolve_path_normalizes_absolute_to_workspace(tmp_path):
    """Absolute paths without /workspace/ prefix are normalized to
    workspace-relative (documented behavior — not an escape)."""
    out = _resolve_path("/etc/passwd", tmp_path)
    assert out == (tmp_path / "etc/passwd").resolve()


def test_resolve_path_allows_workspace_prefix(tmp_path):
    """Paths under /workspace/... resolve to workspace-relative files."""
    out = _resolve_path("/workspace/notes.md", tmp_path)
    assert out == (tmp_path / "notes.md").resolve()


# ---- build_tools scoping ----

def test_build_tools_empty_allowlist_returns_empty():
    assert build_tools([], None) == []


def test_build_tools_scopes_to_allowlist():
    """Only tools named in allowed_tools are exposed to the LLM."""
    tools = build_tools(["Bash"], None)
    names = {t.get("name") for t in tools}
    assert "bash" in names
    assert "read" not in names
    assert "edit" not in names
    assert "web_search" not in names


def test_build_tools_editor_bundle_has_read_and_edit():
    tools = build_tools(["Editor"], None)
    names = {t.get("name") for t in tools}
    assert names == {"read", "edit"}


def test_build_tools_database_exposes_kv_tool():
    tools = build_tools(["DataBase"], None)
    names = {t.get("name") for t in tools}
    assert names == {"database"}


def test_build_tools_unknown_name_ignored():
    """Unknown tool names silently drop — don't crash the agent boot."""
    tools = build_tools(["Bash", "NotARealTool"], None)
    names = {t.get("name") for t in tools}
    assert names == {"bash"}


def test_build_tools_custom_passthrough():
    """User-supplied custom tools are normalized and included."""
    custom = [{"name": "render_image", "description": "x",
               "inputSchema": {"type": "object"}}]
    tools = build_tools([], custom)
    assert len(tools) == 1
    assert tools[0]["type"] == "custom"
    assert tools[0]["name"] == "render_image"


def test_build_tools_web_search_defaults_to_portable_brave(monkeypatch):
    """Default web search is our portable Brave pair — search + fetch — and it's
    present on every vendor (that's the whole point of switching off native)."""
    monkeypatch.setenv("BRAVE_API_KEY", "x")
    for vendor in ("openai", "anthropic", None):
        names = {t.get("name") for t in build_tools(["WebSearch"], None, vendor=vendor)}
        assert names == {"web_search", "web_fetch"}


def test_build_tools_missing_brave_key_falls_back_to_native(monkeypatch):
    """No BRAVE_API_KEY → use the provider's native search where it has one;
    other vendors keep the portable pair (which reports the missing key)."""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    anth = build_tools(["WebSearch"], None, vendor="anthropic")
    assert anth == [{"type": "web_search_20250305", "name": "web_search"}]
    names = {t.get("name") for t in build_tools(["WebSearch"], None, vendor="openai")}
    assert names == {"web_search", "web_fetch"}


def test_build_tools_native_web_search_only_on_anthropic():
    """`native` uses the provider server tool on Anthropic, skips elsewhere."""
    anth = build_tools(["WebSearch"], None, vendor="anthropic", web_search="native")
    assert anth == [{"type": "web_search_20250305", "name": "web_search"}]
    assert build_tools(["WebSearch"], None, vendor="openai", web_search="native") == []


def test_vendor_skips_flags_native_search_off_anthropic():
    assert vendor_skips(["WebSearch", "Bash"], "openai", "native") == ["WebSearch"]
    assert vendor_skips(["WebSearch", "Bash"], "anthropic", "native") == []
    assert vendor_skips(["WebSearch"], "openai", "brave") == []
    assert vendor_skips(["WebSearch"], "openai") == []  # default is brave


# ---- pricing / context ----

def test_cost_from_price_rates():
    from cycls.agent.harness.main import _cost
    price = (3, 15, 0.30, 6)
    assert _cost(price, 1_000_000, 0, 0, 0) == 3.0
    assert _cost(price, 0, 1_000_000, 0, 0) == 15.0
    assert _cost(price, 0, 0, 1_000_000, 1_000_000) == 6.30
    assert _cost(None, 1_000_000, 1_000_000, 0, 0) == 0.0  # no .price() set


def test_llm_price_and_context_reach_the_loop():
    seen = {}
    async def fake_loop(**kw):
        seen.update(kw)
        yield "ok"
    llm = (cycls.LLM().model("openai/gpt-x")
           .price(input=3, output=15, cache_read=0.30, cache_write=6)
           .context(1_000_000).loop(fake_loop))
    async def drain():
        return [ev async for ev in llm.run(context=None)]
    asyncio.run(drain())
    assert seen["price"] == (3, 15, 0.30, 6)
    assert seen["context_window"] == 1_000_000


def test_llm_price_and_context_default_unset():
    assert cycls.LLM()._price is None
    assert cycls.LLM()._context is None


# ---- web search / fetch executors ----

class _FakeResp:
    def __init__(self, data=None, text="", headers=None):
        self._data, self.text, self.headers = data, text, headers or {}
    def raise_for_status(self): pass
    def json(self): return self._data


class _FakeClient:
    """Stands in for httpx.AsyncClient — returns a preset response from .get."""
    resp = None
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, *a, **k): return type(self).resp


def test_web_search_requires_api_key(monkeypatch):
    from cycls.agent.tools import _exec_web_search
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert "BRAVE_API_KEY" in asyncio.run(_exec_web_search({"query": "hi"}))


def test_web_search_formats_passages(monkeypatch):
    import httpx
    from cycls.agent.tools import _exec_web_search
    monkeypatch.setenv("BRAVE_API_KEY", "x")
    _FakeClient.resp = _FakeResp(data={"web": {"results": [
        {"title": "T1", "url": "http://a", "description": "D1", "extra_snippets": ["s1", "s2"]},
        {"title": "T2", "url": "http://b", "description": "D2"}]}})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    out = asyncio.run(_exec_web_search({"query": "hi"}))
    assert "T1" in out and "http://a" in out and "s1" in out and "s2" in out and "T2" in out


def test_web_fetch_strips_html_to_text(monkeypatch):
    import httpx
    from cycls.agent.tools import _exec_web_fetch
    _FakeClient.resp = _FakeResp(
        text="<html><head><style>x{}</style></head><body><p>Hello</p><script>bad()</script>World</body></html>",
        headers={"content-type": "text/html"})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    out = asyncio.run(_exec_web_fetch({"url": "http://a"}))
    assert "Hello" in out and "World" in out
    assert "bad()" not in out and "x{}" not in out


def test_web_fetch_rejects_non_url():
    from cycls.agent.tools import _exec_web_fetch
    assert "http(s) URL" in asyncio.run(_exec_web_fetch({"url": "not-a-url"}))


def test_openai_to_messages_degrades_image_in_tool_result():
    """OpenAI tool messages are text-only — image/document blocks inside a
    tool_result get a text stub + the kinds are reported so the loop can warn."""
    from cycls.agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "text", "text": "page 1: "},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}},
            ]},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "gpt-x")._to_messages(raw, "")
    assert dropped == {"image"}
    tool_msg = out[0]
    assert tool_msg["role"] == "tool"
    assert "page 1: " in tool_msg["content"]
    assert "[image content not viewable on this provider]" in tool_msg["content"]


def test_openai_to_messages_degrades_document_in_tool_result():
    from cycls.agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "..."}},
            ]},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "gpt-x")._to_messages(raw, "")
    assert dropped == {"document"}
    assert "[document content not viewable on this provider]" in out[0]["content"]


def test_openai_to_messages_no_drops_when_text_only():
    from cycls.agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "plain text"},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "gpt-x")._to_messages(raw, "")
    assert dropped == set()
    assert out[0]["content"] == "plain text"


class _CaptureClient:
    """Fake OpenAI SDK client — records create() kwargs, yields no chunks."""
    def __init__(self):
        self.kwargs = None
        self.chat = self
        self.completions = self

    async def create(self, **kw):
        self.kwargs = kw
        async def gen():
            return
            yield
        return gen()


def _stream_kwargs(vendor, thinking=None):
    from cycls.agent.harness.providers.openai import OpenAIProvider
    client = _CaptureClient()
    p = OpenAIProvider(client, "some-model", vendor)
    async def drain():
        return [e async for e in p.stream(messages=[{"role": "user", "content": "hi"}],
                                          system="", tools=[], max_tokens=100, thinking=thinking)]
    asyncio.run(drain())
    return client.kwargs


def test_openai_vendor_uses_max_completion_tokens():
    kw = _stream_kwargs("openai")
    assert kw["max_completion_tokens"] == 100 and "max_tokens" not in kw


def test_compat_vendors_use_standard_max_tokens():
    kw = _stream_kwargs("zai")
    assert kw["max_tokens"] == 100 and "max_completion_tokens" not in kw


def test_unified_reasoning_levels():
    """`.thinking("low"|"medium"|"high")` maps to reasoning_effort on
    OpenAI/Gemini-compat; other vendors and non-level specs don't send it."""
    assert _stream_kwargs("openai", thinking="low")["reasoning_effort"] == "low"
    assert _stream_kwargs("google", thinking="high")["reasoning_effort"] == "high"
    assert "reasoning_effort" not in _stream_kwargs("openai", thinking="adaptive")
    assert "reasoning_effort" not in _stream_kwargs("groq", thinking="medium")


def test_glm_thinking_passthrough():
    assert _stream_kwargs("zai", thinking="adaptive")["extra_body"] == {"thinking": {"type": "enabled"}}
    assert _stream_kwargs("zai", thinking=None)["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in _stream_kwargs("groq", thinking="adaptive")


def test_openai_usage_splits_cached_tokens():
    """prompt_tokens includes cached tokens on OpenAI-compat providers — the
    Turn must carry the split so cost prices them at the cache-read rate."""
    from unittest.mock import AsyncMock, MagicMock
    from cycls.agent.harness.providers.openai import OpenAIProvider
    from cycls.agent.harness.events import Turn

    chunk = MagicMock()
    chunk.usage.prompt_tokens = 100
    chunk.usage.completion_tokens = 10
    chunk.usage.prompt_tokens_details.cached_tokens = 60
    chunk.choices = []

    client = _CaptureClient()
    async def gen():
        yield chunk
    client.create = AsyncMock(return_value=gen())

    async def drain():
        return [e async for e in OpenAIProvider(client, "gpt-5.5").stream(
            messages=[{"role": "user", "content": "hi"}], system="", tools=[], max_tokens=100)]
    turn = next(e for e in asyncio.run(drain()) if isinstance(e, Turn))
    assert (turn.input, turn.cached, turn.output) == (40, 60, 10)


def test_openai_to_messages_drops_empty_text_parts():
    """Strict endpoints (GLM) reject empty text — parts and thinking-only
    assistant turns must not reach the wire."""
    from cycls.agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [{"type": "text", "text": ""}, {"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "hmm"}]},
    ]
    out, _ = OpenAIProvider(None, "glm-5.2", "zai")._to_messages(raw, "")
    assert out == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_build_tools_no_provider_specific_markers():
    """`build_tools` is provider-neutral — no `cache_control` (Anthropic-only)
    leaks in; the AnthropicProvider attaches it at request time."""
    tools = build_tools(["Bash", "Editor"], None)
    for t in tools:
        assert "cache_control" not in t


def test_anthropic_provider_caches_last_tool_and_last_user_message():
    """AnthropicProvider attaches cache_control to the last tool and the last
    user message's tail block — the three breakpoints (system + tools + last
    user) make the entire static prefix cacheable per turn."""
    from cycls.agent.harness.providers.anthropic import AnthropicProvider
    p = AnthropicProvider(None, "claude-sonnet-4-20250514")

    tools = [{"name": "a", "description": "", "input_schema": {}},
             {"name": "b", "description": "", "input_schema": {}}]
    out_tools = p._to_tools(tools)
    assert "cache_control" not in out_tools[0]
    assert out_tools[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
        {"role": "user", "content": [{"type": "text", "text": "second"}]},
    ]
    out_msgs = p._to_messages(msgs)
    # Last user message's tail block carries cache_control; earlier user does not.
    assert out_msgs[-1]["content"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in str(out_msgs[0])


# ---- LLM builder plumbing ----

def test_llm_sandbox_network_default_on():
    """Default on for the LLM bash tool; opt out via sandbox(network=False)."""
    assert cycls.LLM()._bash_network is True
    assert cycls.LLM().sandbox(network=False)._bash_network is False


def test_llm_sandbox_network_kwarg_only():
    """`network` is keyword-only — prevents accidental positional misuse."""
    with pytest.raises(TypeError):
        cycls.LLM().sandbox(True)


def test_llm_instructions_default_and_opt_out():
    """AGENT.md auto-load is on by default; .instructions(None) disables,
    any other string swaps the filename. Originals stay untouched."""
    base = cycls.LLM()
    assert base._instructions == "AGENT.md"
    assert base.instructions(None)._instructions is None
    assert base.instructions("NOTES.md")._instructions == "NOTES.md"
    assert base._instructions == "AGENT.md"


def test_llm_skills_accumulates_and_disables():
    base = cycls.LLM()
    assert base._skills == []
    assert base.skills("a")._skills == ["a"]
    assert base.skills("a").skills("b")._skills == ["a", "b"]
    assert base.skills("a", "b")._skills == ["a", "b"]
    assert base.skills(None)._skills is None
    assert base._skills == []  # original untouched


# ---- cycls.MCP ----

def test_mcp_builder_immutable_and_fluent():
    base = cycls.MCP("https://example.com/mcp")
    named = base.name("github").token("ghp_x").allow("create_issue", "list_issues")
    assert (base._name, base._token, base._allow) == (None, None, None)  # original untouched
    assert named._url == "https://example.com/mcp"
    assert named._name == "github"
    assert named._token == "ghp_x"
    assert named._allow == ["create_issue", "list_issues"]


def test_mcp_spec_shape():
    assert cycls.MCP("https://x/mcp")._spec() == {"type": "url", "url": "https://x/mcp", "name": "mcp"}
    assert cycls.MCP("https://x/mcp").name("gh").token("t").allow("a")._spec() == {
        "type": "url", "url": "https://x/mcp", "name": "gh",
        "authorization_token": "t", "tool_configuration": {"allowed_tools": ["a"]},
    }


def test_llm_mcp_accumulates():
    a, b = cycls.MCP("https://a/mcp"), cycls.MCP("https://b/mcp")
    assert cycls.LLM().mcp(a).mcp(b)._mcp == [a, b]
    assert cycls.LLM().mcp(a, b)._mcp == [a, b]
    assert cycls.LLM()._mcp == []  # original untouched


# ---- LLM.loop ----

def test_llm_loop_default_is_none():
    assert cycls.LLM()._loop is None


def test_llm_loop_runs_custom_loop():
    """A custom loop replaces the built-in; .run yields whatever it yields,
    threaded the same kwargs the default loop gets."""
    async def my_loop(*, context, model, **kw):
        yield cycls.events.text(model)
        yield cycls.events.callout("done", "success")

    llm = cycls.LLM().model("anthropic/claude-x").loop(my_loop)

    async def go():
        return [cycls.to_ui(ev) async for ev in llm.run(context=object())]

    assert asyncio.run(go()) == ["anthropic/claude-x", {"type": "callout", "callout": "done", "style": "success"}]


def test_harness_kit_exposes_building_blocks():
    from cycls.agent.harness import default_loop, make_provider, Session, build_tools, dispatch, compact, events, to_ui
    assert callable(default_loop) and callable(make_provider) and callable(build_tools)

"""Harness tests — _resolve_path escape hardening, build_tools scoping,
LLM builder plumbing."""
import asyncio, json
import pytest

import cycls
from cycls._agent.tools import _resolve_path, build_tools, vendor_skips


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


def test_build_tools_suggest_exposes_tool():
    tools = build_tools(["Suggest"], None)
    names = {t.get("name") for t in tools}
    assert names == {"suggest"}


def test_suggest_dispatch_emits_ui_event_with_ack():
    """`suggest` is a client-driving tool like `canvas`: the dispatch step
    labels it, the executor returns a ui event, and `ack` (what the model
    reads back) rides along for the loop to strip."""
    import asyncio
    from types import SimpleNamespace
    from cycls._agent.tools import dispatch

    step, aw = dispatch({"id": "t1", "name": "suggest",
                         "input": {"text": "Turn this into a document"}},
                        SimpleNamespace(root="/tmp"), timeout=5)
    assert step == {"type": "step", "id": "t1", "tool_name": "Suggest",
                    "step": "Turn this into a document"}
    out = asyncio.run(_await(aw))
    assert out == {"type": "ui", "action": "suggest",
                   "text": "Turn this into a document",
                   "ack": "Suggestion offered to the user."}
    # Empty text is a model error, not a client event.
    _, aw = dispatch({"id": "t2", "name": "suggest", "input": {"text": "  "}},
                     SimpleNamespace(root="/tmp"), timeout=5)
    assert asyncio.run(_await(aw)).startswith("Error")


async def _await(x):
    return await x


def test_suggest_guidance_rides_with_the_tool():
    """Opting into the tool is the only switch — the prompt block appends
    when 'Suggest' is allowed and steers toward finished artifacts."""
    from cycls._agent.harness.prompts import SUGGEST_GUIDANCE
    assert "suggest" in SUGGEST_GUIDANCE
    assert "artifact" in SUGGEST_GUIDANCE


def test_build_tools_ask_exposes_tool():
    tools = build_tools(["Ask"], None)
    names = {t.get("name") for t in tools}
    assert names == {"ask"}


def test_ask_dispatch_emits_ui_event_with_options():
    """`ask` is fire-and-forget like `suggest`: the ui event drives the card
    and the ack tells the model to end its turn rather than guess an answer."""
    import asyncio
    from types import SimpleNamespace
    from cycls._agent.tools import dispatch

    step, aw = dispatch({"id": "t1", "name": "ask", "input": {
        "question": "Which format?",
        "options": [{"label": "PDF", "description": "Print-ready"}, {"label": "Markdown"}],
    }}, SimpleNamespace(root="/tmp"), timeout=5)
    assert step == {"type": "step", "id": "t1", "tool_name": "Ask", "step": "Which format?"}
    out = asyncio.run(_await(aw))
    assert out["type"] == "ui" and out["action"] == "ask"
    assert out["question"] == "Which format?"
    assert out["options"] == [{"label": "PDF", "description": "Print-ready"},
                              {"label": "Markdown"}]
    assert out["multi_select"] is False   # single-answer unless asked for
    assert "End your turn" in out["ack"]


def test_ask_multi_select_needs_more_than_one_option():
    """`multi_select` rides through for a real choice, but a card with one (or
    zero) options can't be a multi-select — it would render checkboxes over a
    single row and a Submit that adds nothing to just typing."""
    import asyncio
    from types import SimpleNamespace
    from cycls._agent.tools import dispatch

    _, aw = dispatch({"id": "t1", "name": "ask", "input": {
        "question": "Which formats?", "multi_select": True,
        "options": [{"label": "PDF"}, {"label": "Markdown"}, {"label": "HTML"}],
    }}, SimpleNamespace(root="/tmp"), timeout=5)
    assert asyncio.run(_await(aw))["multi_select"] is True

    _, aw = dispatch({"id": "t2", "name": "ask", "input": {
        "question": "Ship it?", "multi_select": True, "options": [{"label": "Yes"}],
    }}, SimpleNamespace(root="/tmp"), timeout=5)
    assert asyncio.run(_await(aw))["multi_select"] is False

    _, aw = dispatch({"id": "t3", "name": "ask", "input": {
        "question": "Open question?", "multi_select": True,
    }}, SimpleNamespace(root="/tmp"), timeout=5)
    assert asyncio.run(_await(aw))["multi_select"] is False


def test_ask_normalizes_ragged_options():
    """The model improvises: bare strings, blank labels, more than four, and
    a missing options key all have to land on the same clean shape."""
    import asyncio
    from types import SimpleNamespace
    from cycls._agent.tools import dispatch

    _, aw = dispatch({"id": "t1", "name": "ask", "input": {
        "question": "Pick", "options": ["A", {"label": "  "}, None, {"label": "B"},
                                         {"label": "C"}, {"label": "D"}, {"label": "E"}],
    }}, SimpleNamespace(root="/tmp"), timeout=5)
    out = asyncio.run(_await(aw))
    # First four survive the cap, then blanks/non-dicts drop out.
    assert out["options"] == [{"label": "A"}, {"label": "B"}]

    _, aw = dispatch({"id": "t2", "name": "ask", "input": {"question": "Open?"}},
                     SimpleNamespace(root="/tmp"), timeout=5)
    assert asyncio.run(_await(aw))["options"] == []

    # No question is a model error, not a client event.
    _, aw = dispatch({"id": "t3", "name": "ask", "input": {"question": "  "}},
                     SimpleNamespace(root="/tmp"), timeout=5)
    assert asyncio.run(_await(aw)).startswith("Error")


def test_ask_guidance_rides_with_the_tool():
    from cycls._agent.harness.prompts import ASK_GUIDANCE
    assert "ask" in ASK_GUIDANCE
    assert "last action" in ASK_GUIDANCE


def test_ask_schema_is_plural():
    """The model batches: one call carries every question, so it never has to
    choose between clobbering its first card and burning another round-trip."""
    (ask,) = build_tools(["Ask"], None)
    props = ask["input_schema"]["properties"]
    assert set(ask["input_schema"]["required"]) == {"questions"}
    assert props["questions"]["type"] == "array"
    assert props["questions"]["maxItems"] == 3
    item = props["questions"]["items"]
    assert set(item["required"]) == {"question"}
    # multi_select is per question, not per card — "which formats" and "which
    # section" can sit side by side with different answer arities.
    assert set(item["properties"]) == {"question", "header", "options", "multi_select"}


def test_ask_carries_several_questions_with_headers():
    import asyncio
    from types import SimpleNamespace
    from cycls._agent.tools import dispatch

    step, aw = dispatch({"id": "t1", "name": "ask", "input": {"questions": [
        {"question": "Which format?", "header": "Format",
         "options": [{"label": "PDF"}, {"label": "Markdown"}]},
        {"question": "Which sections?", "header": "Sections", "multi_select": True,
         "options": [{"label": "Intro"}, {"label": "Methods"}]},
    ]}}, SimpleNamespace(root="/tmp"), timeout=5)
    assert step["tool_name"] == "Ask" and step["step"] == "Which format? (+1)"
    out = asyncio.run(_await(aw))
    assert [q["question"] for q in out["questions"]] == ["Which format?", "Which sections?"]
    assert [q["header"] for q in out["questions"]] == ["Format", "Sections"]
    assert [q["multi_select"] for q in out["questions"]] == [False, True]
    assert "2 questions" in out["ack"] and "End your turn" in out["ack"]
    # The old singular keys still ride along, for clients that ship separately.
    assert out["question"] == "Which format?"
    assert out["options"] == [{"label": "PDF"}, {"label": "Markdown"}]


def test_ask_caps_questions_and_says_so():
    """Silently dropping questions would leave the model believing it asked
    them, so the overflow is named in the ack."""
    import asyncio
    from types import SimpleNamespace
    from cycls._agent.tools import dispatch

    _, aw = dispatch({"id": "t1", "name": "ask", "input": {"questions": [
        {"question": f"Q{i}"} for i in range(5)]}}, SimpleNamespace(root="/tmp"), timeout=5)
    out = asyncio.run(_await(aw))
    assert len(out["questions"]) == 3
    assert "Only the first 3" in out["ack"] and "2 dropped" in out["ack"]


def test_ask_second_call_in_a_batch_is_refused():
    """`ask` is `once`: a model that emits two cards in one turn would have the
    second silently replace the first in the UI, so the loop refuses it and
    says how to batch instead."""
    import asyncio
    from types import SimpleNamespace
    from cycls._agent.tools import dispatch

    ws, seen = SimpleNamespace(root="/tmp"), set()
    first = {"id": "t1", "name": "ask", "input": {"questions": [{"question": "A?"}]}}
    second = {"id": "t2", "name": "ask", "input": {"questions": [{"question": "B?"}]}}

    _, aw1 = dispatch(first, ws, timeout=5, seen=seen)
    step2, aw2 = dispatch(second, ws, timeout=5, seen=seen)
    assert asyncio.run(_await(aw1))["type"] == "ui"
    out2 = asyncio.run(_await(aw2))
    assert out2.startswith("Error") and "single call" in out2
    assert step2["id"] == "t2" and step2["ok"] is False


def test_dispatch_without_seen_never_refuses():
    """`seen` is opt-in, so every non-loop caller (and every existing test)
    dispatches every block."""
    import asyncio
    from types import SimpleNamespace
    from cycls._agent.tools import dispatch

    ws = SimpleNamespace(root="/tmp")
    block = {"id": "t1", "name": "ask", "input": {"questions": [{"question": "A?"}]}}
    for _ in range(2):
        _, aw = dispatch(block, ws, timeout=5)
        assert asyncio.run(_await(aw))["type"] == "ui"


def test_descriptor_flags_and_prompts():
    """The three facts the loop acts on live on the tool, so its contract stops
    being a sentence the model is asked to honor."""
    from cycls._agent.tools import _TOOLS, is_terminal, tool_prompts

    assert _TOOLS["ask"].once and _TOOLS["ask"].terminal
    assert _TOOLS["suggest"].once and not _TOOLS["suggest"].terminal
    assert is_terminal("ask") and not is_terminal("bash")
    assert not is_terminal("some_custom_tool")
    assert tool_prompts(build_tools(["Bash"], None)) == []
    assert len(tool_prompts(build_tools(["Ask", "Suggest"], None))) == 2


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
    from cycls._agent.harness.main import _cost
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


def test_llm_vision_default_on_and_reaches_the_loop():
    assert cycls.LLM()._vision is True
    seen = {}
    async def fake_loop(**kw):
        seen.update(kw)
        yield "ok"
    llm = cycls.LLM().model("zai/glm-5.2").vision(False).loop(fake_loop)
    async def drain():
        return [ev async for ev in llm.run(context=None)]
    asyncio.run(drain())
    assert seen["vision"] is False


# ---- web search / fetch executors ----

class _FakeResp:
    def __init__(self, data=None, text="", headers=None, status=200):
        self._data, self.text, self.headers = data, text, headers or {}
        self.is_redirect, self.encoding = 300 <= status < 400, "utf-8"
    def raise_for_status(self): pass
    def json(self): return self._data
    async def aiter_bytes(self):
        yield self.text.encode()


class _FakeClient:
    """Stands in for httpx.AsyncClient — returns a preset response from .get/.stream."""
    resp = None
    last_kwargs = None
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, *a, **k):
        type(self).last_kwargs = k
        return type(self).resp

    def stream(self, *a, **k):
        resp = type(self).resp
        class _S:
            async def __aenter__(self): return resp
            async def __aexit__(self, *a): return False
        return _S()


def test_web_search_requires_api_key(monkeypatch):
    from cycls._agent.tools import _exec_web_search
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert "BRAVE_API_KEY" in asyncio.run(_exec_web_search({"query": "hi"}))


def test_web_search_formats_passages(monkeypatch):
    import httpx
    from cycls._agent.tools import _exec_web_search
    monkeypatch.setenv("BRAVE_API_KEY", "x")
    _FakeClient.resp = _FakeResp(data={"web": {"results": [
        {"title": "T1", "url": "http://a", "description": "D1", "extra_snippets": ["s1", "s2"]},
        {"title": "T2", "url": "http://b", "description": "D2"}]}})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    out = asyncio.run(_exec_web_search({"query": "hi"}))
    # Two channels off one row set: JSON for the model, the same rows as a
    # `sources` event for the client — so the citations the user sees are
    # exactly what the search returned.
    model = json.loads(out["_model"])
    assert model["query"] == "hi"
    assert [r["url"] for r in model["results"]] == ["http://a", "http://b"]
    assert model["results"][0]["title"] == "T1"
    assert "s1" in model["results"][0]["snippet"] and "s2" in model["results"][0]["snippet"]
    assert out["_ui"] == {"type": "sources", "sources": model["results"]}


def test_web_search_drops_rows_without_a_url(monkeypatch):
    """A citation chip is a link; a row with no URL can't become one. If none
    of them can, that's 'no results', not an empty chip row."""
    import httpx
    from cycls._agent.tools import _exec_web_search
    monkeypatch.setenv("BRAVE_API_KEY", "x")
    _FakeClient.resp = _FakeResp(data={"web": {"results": [
        {"title": "T1", "url": "", "description": "D1"},
        {"title": "T2", "url": "http://b", "description": "D2"}]}})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    out = asyncio.run(_exec_web_search({"query": "hi"}))
    assert [r["url"] for r in out["_ui"]["sources"]] == ["http://b"]

    _FakeClient.resp = _FakeResp(data={"web": {"results": [{"title": "T", "url": ""}]}})
    assert "No results" in asyncio.run(_exec_web_search({"query": "hi"}))


def test_web_search_locale_params(monkeypatch):
    """Env vars are deployment defaults; per-query model input overrides them."""
    import httpx
    from cycls._agent.tools import _exec_web_search
    monkeypatch.setenv("BRAVE_API_KEY", "x")
    monkeypatch.delenv("BRAVE_COUNTRY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_LANG", raising=False)
    _FakeClient.resp = _FakeResp(data={"web": {"results": [
        {"title": "T", "url": "http://a", "description": "D"}]}})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    asyncio.run(_exec_web_search({"query": "q"}))
    assert _FakeClient.last_kwargs["params"] == {"q": "q", "count": 5}

    monkeypatch.setenv("BRAVE_COUNTRY", "sa")
    asyncio.run(_exec_web_search({"query": "q"}))
    assert _FakeClient.last_kwargs["params"]["country"] == "sa"

    asyncio.run(_exec_web_search({"query": "q", "country": "US", "search_lang": "AR"}))
    assert _FakeClient.last_kwargs["params"]["country"] == "us"
    assert _FakeClient.last_kwargs["params"]["search_lang"] == "ar"


def test_client_cache_keyed_by_full_config(monkeypatch):
    """Same vendor with different base_url/api_key/headers must not share a client."""
    from cycls._agent.harness import providers
    monkeypatch.setattr(providers, "_clients", {})
    a = providers._client_for("openai", base_url="https://a/v1", api_key="k1")
    b = providers._client_for("openai", base_url="https://b/v1", api_key="k2")
    c = providers._client_for("openai", base_url="https://a/v1", api_key="k1")
    h = providers._client_for("openai", base_url="https://a/v1", api_key="k1",
                              headers={"Modal-Key": "x"})
    assert a is not b and a is c and h is not a
    assert str(a.base_url).startswith("https://a/") and str(b.base_url).startswith("https://b/")
    assert h.default_headers["Modal-Key"] == "x"


def test_thinking_unmapped_vendor_warns_once(monkeypatch, capsys):
    from cycls._agent.harness.providers import openai as prov
    monkeypatch.setattr(prov, "_unmapped_thinking_warned", set())
    assert prov._thinking_kwargs("modal", "medium") == {}
    assert "no dialect for vendor 'modal'" in capsys.readouterr().err
    assert prov._thinking_kwargs("modal", "medium") == {}       # deduped
    assert prov._thinking_kwargs("modal", "adaptive") == {}     # default: quiet
    assert prov._thinking_kwargs("modal", None) == {}
    assert capsys.readouterr().err == ""
    assert prov._thinking_kwargs("kimi", "medium") == {"reasoning_effort": "high"}
    assert capsys.readouterr().err == ""


def test_llm_headers_reach_provider_client(monkeypatch):
    from cycls._agent.harness import providers
    from cycls._agent.harness.llm import LLM
    monkeypatch.setattr(providers, "_clients", {})
    llm = LLM().model("modal/kimi-k3").api_key("unused").headers({"Modal-Key": "x", "Modal-Secret": "y"})
    assert llm._headers == {"Modal-Key": "x", "Modal-Secret": "y"}
    p = providers.make_provider("modal/kimi-k3", api_key="unused", headers=llm._headers)
    assert p._client.default_headers["Modal-Secret"] == "y"
    p2 = providers.make_provider("modal/kimi-k3", api_key="unused", headers={"Modal-Key": "z"})
    assert p2._client is not p._client


def test_openai_stream_clamps_cached_above_prompt():
    """cached_tokens above prompt_tokens (SGLang) must not yield negative input."""
    import types
    from cycls._agent.harness.providers.openai import OpenAIProvider
    from cycls._agent.harness.events import Turn

    def chunk(text=None, finish=None, usage=None):
        delta = types.SimpleNamespace(content=text, tool_calls=None)
        choices = [types.SimpleNamespace(delta=delta, finish_reason=finish)] if text or finish else []
        return types.SimpleNamespace(usage=usage, choices=choices)

    usage = types.SimpleNamespace(
        prompt_tokens=127, completion_tokens=43,
        prompt_tokens_details=types.SimpleNamespace(cached_tokens=128))

    async def _gen():
        yield chunk(text="hi")
        yield chunk(finish="stop")
        yield chunk(usage=usage)

    async def _create(**kw): return _gen()
    client = types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=_create)))

    async def run():
        p = OpenAIProvider(client, "kimi-k3", "kimi")
        return [ev async for ev in p.stream(
            messages=[{"role": "user", "content": "q"}], system="", tools=[], max_tokens=100)]

    turn = next(e for e in asyncio.run(run()) if isinstance(e, Turn))
    assert turn.input == 0 and turn.cached == 127 and turn.output == 43
    assert turn.input + turn.cached + turn.cache_create == 127


def test_web_fetch_strips_html_to_text(monkeypatch):
    import httpx
    from cycls._agent import tools
    _FakeClient.resp = _FakeResp(
        text="<html><head><style>x{}</style></head><body><p>Hello</p><script>bad()</script>World</body></html>",
        headers={"content-type": "text/html"})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(tools, "_is_public_host", lambda h: True)
    out = asyncio.run(tools._exec_web_fetch({"url": "http://a"}))
    assert "Hello" in out and "World" in out
    assert "bad()" not in out and "x{}" not in out


def test_web_fetch_rejects_non_url():
    from cycls._agent.tools import _exec_web_fetch
    assert "http(s) URL" in asyncio.run(_exec_web_fetch({"url": "not-a-url"}))


def test_web_fetch_blocks_private_addresses():
    """SSRF guard: the fetch runs in the server process — loopback, RFC1918
    and link-local (cloud metadata) targets are refused before any request."""
    from cycls._agent.tools import _exec_web_fetch
    for url in ("http://localhost:8000/x", "http://127.0.0.1/", "http://[::1]/",
                "http://169.254.169.254/computeMetadata/v1/", "http://192.168.1.1/admin"):
        assert "private" in asyncio.run(_exec_web_fetch({"url": url})), url


def test_web_fetch_checks_redirect_hops(monkeypatch):
    """A public URL redirecting to an internal host is refused at the hop."""
    import httpx
    from cycls._agent import tools
    monkeypatch.setattr(tools, "_is_public_host", lambda h: h != "localhost")
    _FakeClient.resp = _FakeResp(headers={"location": "http://localhost/admin"}, status=302)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    assert "private" in asyncio.run(tools._exec_web_fetch({"url": "http://public.example/r"}))


def test_custom_tool_step_defaults_to_first_string_input(monkeypatch):
    """Unlabelled custom tools show their first string input, like Bash(command)."""
    from cycls._agent import tools
    monkeypatch.setattr(tools, "_custom_labels", {})
    s = tools.tool_step("legal_search", {"limit": 5, "sql": "SELECT id FROM laws"})
    assert s == {"tool_name": "legal_search", "step": "SELECT id FROM laws"}
    assert tools.tool_step("t", {"a": "x" * 300})["step"].endswith("...")
    assert tools.tool_step("t", {"n": 3}) == {"tool_name": "t", "step": ""}


def test_registered_label_renders_the_step(monkeypatch):
    from cycls._agent import tools
    monkeypatch.setattr(tools, "_custom_labels", {})
    tools.register_labels({"legal_search": lambda inp: f"بحث: {inp['sql']}"})
    assert tools.tool_step("legal_search", {"sql": "SELECT 1"})["step"] == "بحث: SELECT 1"
    # a broken label falls back to the default, never breaks the stream
    tools.register_labels({"legal_search": lambda inp: inp["missing"]})
    assert tools.tool_step("legal_search", {"sql": "SELECT 1"})["step"] == "SELECT 1"


def test_llm_on_label_registers_via_run(monkeypatch):
    from cycls._agent import tools
    monkeypatch.setattr(tools, "_custom_labels", {})

    async def fake_loop(**kw):
        yield "ok"

    async def handler(inp):
        return "r"

    llm = (cycls.LLM().model("openai/gpt-x").loop(fake_loop)
           .on("legal_search", handler, label=lambda inp: "labelled"))

    async def drain():
        return [ev async for ev in llm.run(context=None)]
    asyncio.run(drain())
    assert tools.tool_step("legal_search", {})["step"] == "labelled"


def test_web_fetch_caps_body_size(monkeypatch):
    """An endless body stops at _FETCH_MAX_BYTES instead of filling memory."""
    import httpx
    from cycls._agent import tools

    class _Endless(_FakeResp):
        async def aiter_bytes(self):
            while True: yield b"a" * 100

    monkeypatch.setattr(tools, "_is_public_host", lambda h: True)
    monkeypatch.setattr(tools, "_FETCH_MAX_BYTES", 1_000)
    _FakeClient.resp = _Endless(headers={"content-type": "text/plain"})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    out = asyncio.run(tools._exec_web_fetch({"url": "http://a"}))
    assert len(out) <= 1_100


def test_thinking_kwargs_vendor_dialects():
    """One unified knob → each vendor's reasoning dialect; unknown vendors no-op."""
    from cycls._agent.harness.providers.openai import _thinking_kwargs as tk
    # standard reasoning_effort pass-through family
    for v in ("openai", "gemini", "xai", "grok", "mistral", "groq"):
        assert tk(v, "medium") == {"reasoning_effort": "medium"}, v
        assert tk(v, "adaptive") == {}, v  # server default
    # kimi: low/high/max value set
    assert tk("kimi", "medium") == {"reasoning_effort": "high"}
    assert tk("kimi", "high") == {"reasoning_effort": "max"}
    assert tk("kimi", "adaptive") == {}
    # glm: binary toggle
    assert tk("glm", "adaptive") == {"extra_body": {"thinking": {"type": "enabled"}}}
    assert tk("glm", None) == {"extra_body": {"thinking": {"type": "disabled"}}}
    # deepseek: toggle + effort
    assert tk("deepseek", "low") == {
        "extra_body": {"thinking": {"type": "enabled"}}, "reasoning_effort": "low"}
    assert tk("deepseek", None) == {"extra_body": {"thinking": {"type": "disabled"}}}
    # qwen: enable_thinking + budget
    assert tk("qwen", "high") == {
        "extra_body": {"enable_thinking": True, "thinking_budget": 32_768}}
    assert tk("qwen", None) == {"extra_body": {"enable_thinking": False}}
    # openrouter: normalized reasoning object
    assert tk("openrouter", "low") == {"extra_body": {"reasoning": {"effort": "low"}}}
    # azure/perplexity ride the standard family
    assert tk("azure", "low") == {"reasoning_effort": "low"}
    assert tk("perplexity", "high") == {"reasoning_effort": "high"}
    # unknown vendor: silent server default
    assert tk("somevendor", "high") == {}


def test_extra_body_passthrough_and_override():
    """.extra_body() extras reach the request and win over the built-in
    vendor mapping on collision (unknown vendors get pure passthrough)."""
    kw = _stream_kwargs("together", extra_body={"enable_thinking": True, "thinking_budget": 8192})
    assert kw["extra_body"] == {"enable_thinking": True, "thinking_budget": 8192}
    # collision: qwen mapping says budget 4096 for low; deployer override wins
    kw = _stream_kwargs("qwen", thinking="low", extra_body={"thinking_budget": 999})
    assert kw["extra_body"]["thinking_budget"] == 999
    assert kw["extra_body"]["enable_thinking"] is True  # non-colliding mapped key kept


def test_openai_to_messages_hoists_image_in_tool_result_on_vision():
    """OpenAI tool messages are text-only — on a vision model the image block
    is hoisted into the user message following the tool responses (no warn)."""
    from cycls._agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "text", "text": "page 1: "},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}},
            ]},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "gpt-x")._to_messages(raw, "")
    assert dropped == set()
    tool_msg, user_msg = out[0], out[1]
    assert tool_msg["role"] == "tool"
    assert "page 1: " in tool_msg["content"]
    assert "[image attached" in tool_msg["content"]
    assert user_msg["role"] == "user"
    assert user_msg["content"][0]["type"] == "image_url"
    assert user_msg["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_to_messages_degrades_image_in_tool_result_no_vision():
    """vision=False keeps the old contract: stub + dropped kind so the loop warns."""
    from cycls._agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "text", "text": "page 1: "},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}},
            ]},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "gpt-x", vision=False)._to_messages(raw, "")
    assert dropped == {"image"}
    tool_msg = out[0]
    assert tool_msg["role"] == "tool"
    assert "page 1: " in tool_msg["content"]
    assert "[image content not viewable on this provider]" in tool_msg["content"]


def test_openai_to_messages_degrades_document_in_tool_result():
    from cycls._agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "..."}},
            ]},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "gpt-x")._to_messages(raw, "")
    assert dropped == {"document"}   # still reported, for the server-side log
    # actionable stub: routes a vision model to read-with-pages, not a dead end
    assert "pages=" in out[0]["content"]


def test_openai_to_messages_user_image_sent_when_vision():
    """Default (vision=True): user-content images go out as image_url data URLs."""
    from cycls._agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "gpt-x")._to_messages(raw, "")
    assert dropped == set()
    parts = out[0]["content"]
    assert parts[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}


def test_openai_to_messages_user_image_stubbed_without_vision():
    """vision=False backstop: an image block that reaches a text-only model
    degrades to a text stub instead of a rejected request (z.ai code 1210)."""
    from cycls._agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "glm-5.2", "zai", vision=False)._to_messages(raw, "")
    assert dropped == {"image"}
    parts = out[0]["content"]
    assert parts[1] == {"type": "text", "text": "[image content not viewable on this provider]"}


def test_openai_to_messages_user_document_stubbed():
    """Documents have no Chat Completions wire form — stubbed on any model,
    not silently dropped."""
    from cycls._agent.harness.providers.openai import OpenAIProvider
    raw = [
        {"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "abc"}},
        ]},
    ]
    out, dropped = OpenAIProvider(None, "gpt-x")._to_messages(raw, "")
    assert dropped == {"document"}   # still reported, for the server-side log
    stub = out[0]["content"][0]
    assert stub["type"] == "text"
    # actionable stub: points at the saved workspace file, not a dead end
    assert "saved in the workspace" in stub["text"]


def test_openai_to_messages_no_drops_when_text_only():
    from cycls._agent.harness.providers.openai import OpenAIProvider
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


def _stream_kwargs(vendor, thinking=None, extra_body=None):
    from cycls._agent.harness.providers.openai import OpenAIProvider
    client = _CaptureClient()
    p = OpenAIProvider(client, "some-model", vendor)
    async def drain():
        return [e async for e in p.stream(messages=[{"role": "user", "content": "hi"}],
                                          system="", tools=[], max_tokens=100, thinking=thinking,
                                          extra_body=extra_body)]
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
    # groq now maps (it forwards reasoning_effort); use a truly unmapped vendor
    assert "reasoning_effort" not in _stream_kwargs("together", thinking="medium")


def test_glm_thinking_passthrough():
    assert _stream_kwargs("zai", thinking="adaptive")["extra_body"] == {"thinking": {"type": "enabled"}}
    assert _stream_kwargs("zai", thinking=None)["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in _stream_kwargs("groq", thinking="adaptive")


def test_openai_usage_splits_cached_tokens():
    """prompt_tokens includes cached tokens on OpenAI-compat providers — the
    Turn must carry the split so cost prices them at the cache-read rate."""
    from unittest.mock import AsyncMock, MagicMock
    from cycls._agent.harness.providers.openai import OpenAIProvider
    from cycls._agent.harness.events import Turn

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


def test_openai_usage_cached_tokens_top_level_fallback():
    """Kimi/Moonshot reports `cached_tokens` at the top level of usage, not
    under prompt_tokens_details — the split must still be carried."""
    from unittest.mock import AsyncMock, MagicMock
    from cycls._agent.harness.providers.openai import OpenAIProvider
    from cycls._agent.harness.events import Turn

    chunk = MagicMock()
    chunk.usage.prompt_tokens = 100
    chunk.usage.completion_tokens = 10
    chunk.usage.prompt_tokens_details = None
    chunk.usage.cached_tokens = 60
    chunk.choices = []

    client = _CaptureClient()
    async def gen():
        yield chunk
    client.create = AsyncMock(return_value=gen())

    async def drain():
        return [e async for e in OpenAIProvider(client, "kimi-k3", "kimi").stream(
            messages=[{"role": "user", "content": "hi"}], system="", tools=[], max_tokens=100)]
    turn = next(e for e in asyncio.run(drain()) if isinstance(e, Turn))
    assert (turn.input, turn.cached, turn.output) == (40, 60, 10)


def test_openai_to_messages_drops_empty_text_parts():
    """Strict endpoints (GLM) reject empty text — parts and thinking-only
    assistant turns must not reach the wire."""
    from cycls._agent.harness.providers.openai import OpenAIProvider
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
    from cycls._agent.harness.providers.anthropic import AnthropicProvider
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
    from cycls._agent.harness import default_loop, make_provider, Session, build_tools, dispatch, compact, events, to_ui
    assert callable(default_loop) and callable(make_provider) and callable(build_tools)

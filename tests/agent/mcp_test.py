"""cycls.MCP client-side: discovery is prefixed, filtered and cached; results
are shaped for the model; the step line reads `server · tool`."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from cycls._agent import mcp as m


def _tool(name, **kw): return SimpleNamespace(**{"name": name, "description": "d", "title": None, "input_schema": {"type": "object"}, "annotations": None, **kw})


@pytest.fixture(autouse=True)
def fresh_cache():
    m._discovered.clear()


def test_discover_prefixes_filters_and_caches():
    listed = AsyncMock(return_value=[_tool("orders"), _tool("refund")])
    with patch.object(m, "_list", listed):
        srv = m.MCP("https://x/mcp").name("salla").allow("orders")
        schemas, handlers, names = asyncio.run(srv.discover())
        asyncio.run(srv.discover())
    assert [s["name"] for s in schemas] == ["salla_orders"]
    assert set(handlers) == {"salla_orders"} and names == {"salla_orders": "salla · orders"}
    assert listed.await_count == 1


def test_handler_calls_the_raw_name_with_the_bearer():
    called = AsyncMock(return_value="ok")
    with patch.object(m, "_list", AsyncMock(return_value=[_tool("orders")])), patch.object(m, "_call", called):
        _, handlers, _ = asyncio.run(m.MCP("https://x/mcp").name("salla").token("t").discover())
        assert asyncio.run(handlers["salla_orders"]({"since": "2026-08"}, None)) == "ok"
    called.assert_awaited_once_with("https://x/mcp", {"Authorization": "Bearer t"}, "orders", {"since": "2026-08"})


def test_shape_text_error_and_non_text():
    from mcp.types import CallToolResult, TextContent, ImageContent
    text = lambda t: TextContent(type="text", text=t)
    assert m._shape(CallToolResult(content=[text("a"), text("b")])) == "a\nb"
    assert m._shape(CallToolResult(content=[text("boom")], is_error=True)) == "Error: boom"
    assert "1 non-text" in m._shape(CallToolResult(content=[ImageContent(type="image", data="AA==", mime_type="image/png")]))
    assert m._shape(CallToolResult(content=[])) == "(no output)"


def test_step_line_uses_the_registered_display_name():
    from cycls._agent.tools import register_labels, tool_step
    register_labels({}, {"salla_orders": "salla · orders"})
    assert tool_step("salla_orders", {"since": "2026-08"}) == {"tool_name": "salla · orders", "step": ""}   # raw args stay out of the chat
    assert tool_step("salla_orders", {"since": "2026-08", "context": "Orders for August"})["step"] == "Orders for August"


def test_live_public_server_discovers_tools(request):
    if not request.config.getoption("--live", default=False):
        pytest.skip("--live")
    schemas, _, _ = asyncio.run(m.MCP("https://mcp.deepwiki.com/mcp").name("deepwiki").discover())
    assert any(s["name"].startswith("deepwiki_") for s in schemas)


def test_writes_trusts_the_annotation_and_falls_back_to_the_name():
    from cycls._agent import connectors as c
    ro = SimpleNamespace(read_only_hint=True, destructive_hint=None)
    assert c.writes(_tool("delete_file", annotations=ro)) is False          # the server knows best
    assert c.writes(_tool("search_files")) is False
    assert c.writes(_tool("create_file")) is True
    drive = SimpleNamespace(label="drive", _writes=None)
    assert c.mode(drive, _tool("create_file"), {}) == "ask"    # writes ask by default
    assert c.mode(drive, _tool("search_files"), {}) == "allow"
    assert c.mode(drive, _tool("search_files"), {"drive_search_files": "never"}) == "never"


def test_a_connector_knows_its_servers_however_the_chain_is_ordered():
    from cycls._agent import connectors as c
    o = c.OAuth2("g", authorize="a", token="t", client_id="i", secret="s")
    base = m.MCP("https://x/mcp").connector(o)
    a, b = base.name("a"), base.name("b").allow("t1")
    assert [s.label for s in o.servers] == ["a", "b"]           # the dead intermediates are gone


def test_prompts_are_cached_and_a_server_without_them_reads_as_none():
    m._prompts.clear()
    with patch.object(m, "_list_prompts", AsyncMock(return_value=[_tool("weekly")])) as lp:
        assert [p.name for p in asyncio.run(m.MCP("https://x/mcp").prompts())] == ["weekly"]
        asyncio.run(m.MCP("https://x/mcp").prompts())
        assert lp.await_count == 1
    with patch.object(m, "_list_prompts", AsyncMock(side_effect=RuntimeError("no prompts"))):
        assert asyncio.run(m.MCP("https://y/mcp").prompts()) == []


def test_prompts_are_cached_and_a_server_without_them_reads_as_none():
    m._prompts.clear()
    with patch.object(m, "_list_prompts", AsyncMock(return_value=[_tool("weekly")])) as lp:
        assert [p.name for p in asyncio.run(m.MCP("https://x/mcp").prompts())] == ["weekly"]
        asyncio.run(m.MCP("https://x/mcp").prompts())
        assert lp.await_count == 1
    with patch.object(m, "_list_prompts", AsyncMock(side_effect=RuntimeError("no prompts"))):
        assert asyncio.run(m.MCP("https://y/mcp").prompts()) == []


def test_discovery_can_carry_the_callers_token_and_caches_per_token():
    m._discovered.clear()
    with patch.object(m, "_list", AsyncMock(return_value=[_tool("t")])) as ls:
        s = m.MCP("https://x/mcp")
        asyncio.run(s.tools("k1")); asyncio.run(s.tools("k1")); asyncio.run(s.tools("k2"))
        assert ls.await_count == 2
        assert ls.await_args_list[0].args[1] == {"Authorization": "Bearer k1"}


def test_guidance_and_the_write_classifier_ride_the_copy():
    fn = lambda tool, args: False
    s = m.MCP("https://x/mcp").guidance("Use call execute-sql directly.").writes(fn)
    assert (s._guidance, s._writes) == ("Use call execute-sql directly.", fn)

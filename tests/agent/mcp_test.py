"""cycls.MCP client-side: discovery is prefixed, filtered and cached; results
are shaped for the model; the step line reads `server · tool`."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from cycls._agent import mcp as m


def _tool(name): return SimpleNamespace(name=name, description="d", input_schema={"type": "object"})


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
    assert tool_step("salla_orders", {"since": "2026-08"}) == {"tool_name": "salla · orders", "step": "2026-08"}


def test_live_public_server_discovers_tools(request):
    if not request.config.getoption("--live", default=False):
        pytest.skip("--live")
    schemas, _, _ = asyncio.run(m.MCP("https://mcp.deepwiki.com/mcp").name("deepwiki").discover())
    assert any(s["name"].startswith("deepwiki_") for s in schemas)

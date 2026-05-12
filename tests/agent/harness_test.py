"""Harness tests — _resolve_path escape hardening, build_tools scoping,
LLM builder plumbing."""
import pytest

import cycls
from cycls.agent.tools import _resolve_path, build_tools


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


def test_build_tools_cache_control_on_last():
    """Last tool gets ephemeral cache_control for prompt-cache efficiency."""
    tools = build_tools(["Bash", "Editor"], None)
    assert tools[-1].get("cache_control") == {"type": "ephemeral", "ttl": "1h"}
    for t in tools[:-1]:
        assert "cache_control" not in t


# ---- LLM builder plumbing ----

def test_llm_sandbox_network_default_on():
    """Default on for the LLM bash tool; opt out via sandbox(network=False)."""
    assert cycls.LLM()._bash_network is True
    assert cycls.LLM().sandbox(network=False)._bash_network is False


def test_llm_sandbox_network_kwarg_only():
    """`network` is keyword-only — prevents accidental positional misuse."""
    with pytest.raises(TypeError):
        cycls.LLM().sandbox(True)


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

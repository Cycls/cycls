"""Tests for .cycls/ reserved-path guards (RFC 002 Impl I Step 3)
and bash sandbox / tool-scoping hardening."""
import asyncio
import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cycls
from cycls.agent.state.main import resolve_path
from cycls.agent.harness.tools import _resolve_path, _exec_bash, build_tools


def test_state_resolve_path_rejects_cycls(tmp_path):
    (tmp_path / ".cycls").mkdir()
    with pytest.raises(ValueError, match="Reserved path"):
        resolve_path(tmp_path, ".cycls")
    with pytest.raises(ValueError, match="Reserved path"):
        resolve_path(tmp_path, ".cycls/usage.json")


def test_state_resolve_path_rejects_cycls_nested(tmp_path):
    (tmp_path / ".cycls" / "sub").mkdir(parents=True)
    with pytest.raises(ValueError, match="Reserved path"):
        resolve_path(tmp_path, ".cycls/sub/file.json")


def test_state_resolve_path_allows_normal(tmp_path):
    out = resolve_path(tmp_path, "notes.md")
    assert out == (tmp_path / "notes.md").resolve()


def test_tools_resolve_path_rejects_cycls(tmp_path):
    (tmp_path / ".cycls").mkdir()
    with pytest.raises(ValueError, match=".cycls/"):
        _resolve_path("/workspace/.cycls/usage.json", tmp_path)
    with pytest.raises(ValueError, match=".cycls/"):
        _resolve_path(".cycls", tmp_path)


def test_dict_still_works_inside_workspace(tmp_path):
    """Guards block raw filesystem access; cycls.Dict keeps working."""
    with cycls.Workspace(tmp_path):
        d = cycls.Dict("usage")
        d["2026-04"] = {"count": 1}
    assert (tmp_path / ".cycls" / "usage.json").exists()


def test_bash_sandbox_ro_binds_cycls(tmp_path):
    """_exec_bash argv must include --ro-bind-try for .cycls so user shell
    can read its state but any write is blocked by the read-only mount."""
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["argv"] = args
        return mock_proc

    with patch("asyncio.create_subprocess_exec", fake_exec):
        asyncio.run(_exec_bash("echo", str(tmp_path)))

    argv = captured["argv"]
    assert "--ro-bind-try" in argv
    i = argv.index("--ro-bind-try")
    assert argv[i + 1] == str(tmp_path / ".cycls")
    assert argv[i + 2] == "/workspace/.cycls"


def _capture_bash_exec(tmp_path, **kwargs):
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
    captured = {}

    async def fake_exec(*args, **kw):
        captured["argv"] = args
        captured["kwargs"] = kw
        return mock_proc

    with patch("asyncio.create_subprocess_exec", fake_exec):
        asyncio.run(_exec_bash("echo", str(tmp_path), **kwargs))
    return captured


def _capture_bash_argv(tmp_path, **kwargs):
    return _capture_bash_exec(tmp_path, **kwargs)["argv"]


def test_bash_sandbox_network_off_by_default(tmp_path):
    """Network is OFF by default via --unshare-net — sandboxed bash can't
    egress even if it reads a secret. Opt in via LLM.sandbox(network=True).
    We use --unshare-net (not --unshare-all) because --unshare-pid's procfs
    mount fails in nested container environments."""
    argv = _capture_bash_argv(tmp_path)
    assert "--unshare-net" in argv


def test_bash_sandbox_network_opt_in(tmp_path):
    """network=True drops --unshare-net so bash can egress (curl, pip, git)."""
    argv = _capture_bash_argv(tmp_path, network=True)
    assert "--unshare-net" not in argv


def test_bash_sandbox_clearenv(tmp_path):
    """--clearenv strips parent env so secrets like ANTHROPIC_API_KEY don't
    cross the sandbox boundary."""
    argv = _capture_bash_argv(tmp_path)
    assert "--clearenv" in argv


def test_bash_sandbox_forwards_only_safe_env(tmp_path):
    """Only PATH / HOME / TERM / LANG may be forwarded via --setenv.
    Anything else risks leaking a secret the caller forgot to strip."""
    argv = _capture_bash_argv(tmp_path)
    safe = {"PATH", "HOME", "TERM", "LANG"}
    forwarded = {argv[i + 1] for i, a in enumerate(argv) if a == "--setenv"}
    assert forwarded <= safe, f"unexpected env forwarded: {forwarded - safe}"


def test_bash_sandbox_die_with_parent(tmp_path):
    """--die-with-parent prevents orphaned sandbox processes."""
    argv = _capture_bash_argv(tmp_path)
    assert "--die-with-parent" in argv


def test_bash_sandbox_bwrap_env_is_sanitized(tmp_path, monkeypatch):
    """REGRESSION: bwrap itself is visible as PID 1 inside the sandbox, so
    its own environ must be sanitized via subprocess env=. --clearenv only
    affects the bash child — without env= on subprocess_exec, bwrap leaks
    the parent Python's secrets via /proc/1/environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-LEAK")
    monkeypatch.setenv("CYCLS_API_KEY", "ak-LEAK")
    monkeypatch.setenv("GITHUB_TOKEN", "ghu_LEAK")
    captured = _capture_bash_exec(tmp_path)
    env = captured["kwargs"].get("env")
    assert env is not None, "bwrap must be launched with explicit env= to block leak"
    assert set(env.keys()) <= {"PATH", "LANG"}, f"unexpected bwrap env keys: {env.keys()}"
    blob = "\n".join(f"{k}={v}" for k, v in env.items())
    assert "LEAK" not in blob
    assert "sk-ant" not in blob
    assert "ak-" not in blob
    assert "ghu_" not in blob


def _bwrap_live_ok():
    """Probe whether bwrap can actually run with our mount config.
    Deployed containers have /workspace; dev hosts usually don't,
    and --ro-bind / / blocks creating it."""
    if shutil.which("bwrap") is None:
        return False
    try:
        out = asyncio.run(_exec_bash("echo ok", "/tmp"))
        return "ok" in out and "Read-only file system" not in out
    except Exception:
        return False


_BWRAP_LIVE = _bwrap_live_ok()


@pytest.mark.skipif(not _BWRAP_LIVE, reason="bwrap cannot run in this env (needs /workspace mount point)")
def test_bash_sandbox_bwrap_pid_environ_is_clean_live(tmp_path, monkeypatch):
    """Live: bwrap's own environ (visible in the sandbox's /proc) must not
    leak the parent Python's secrets. We don't --unshare-pid (breaks in
    nested containers), so the full /proc is visible — but each process's
    environ is what matters, and bwrap's must be sanitized.
    Note: without --unshare-pid, bash CAN read the parent Python's environ
    via /proc/<ppid>/environ. This is the pre-existing state documented in
    docs/sandbox-security.md — eliminating it requires PID namespace isolation that
    isn't available in our nested-container runtime."""
    monkeypatch.setenv("CYCLS_SANDBOX_LEAK_SENTINEL_XYZ", "should-not-leak")
    out = asyncio.run(_exec_bash(
        r"pgrep -a bwrap | awk '{print $1}' | xargs -I{} sh -c 'tr \"\\0\" \"\\n\" < /proc/{}/environ' 2>/dev/null",
        str(tmp_path),
    ))
    assert "should-not-leak" not in out, (
        "bwrap's own environ leaked parent-process secret — env= sanitization "
        "on subprocess_exec is broken"
    )


# ---- _resolve_path escape hardening ----

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


# ---- LLM builder plumbing ----

def test_llm_sandbox_network_opt_in():
    """Default off; opt-in flips the flag that dispatch threads to _exec_bash."""
    assert cycls.LLM()._bash_network is False
    assert cycls.LLM().sandbox(network=True)._bash_network is True


def test_llm_sandbox_network_kwarg_only():
    """`network` is keyword-only — prevents accidental positional misuse."""
    with pytest.raises(TypeError):
        cycls.LLM().sandbox(True)


def test_build_tools_cache_control_on_last():
    """Last tool gets ephemeral cache_control for prompt-cache efficiency."""
    tools = build_tools(["Bash", "Editor"], None)
    assert tools[-1].get("cache_control") == {"type": "ephemeral", "ttl": "1h"}
    for t in tools[:-1]:
        assert "cache_control" not in t

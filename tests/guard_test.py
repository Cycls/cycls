"""Tests for .cycls/ reserved-path guards (RFC 002 Impl I Step 3)."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cycls
from cycls.agent.state.main import resolve_path
from cycls.agent.harness.tools import _resolve_path, _exec_bash


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

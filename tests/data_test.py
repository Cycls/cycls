"""Tests for cycls.Dict + cycls.Workspace (RFC 002 Fold 1)."""
import json
import pytest

import cycls


def test_dict_persists_across_with_blocks(tmp_path):
    with cycls.Workspace(tmp_path):
        d = cycls.Dict("sessions")
        d["abc"] = {"title": "Budget", "updatedAt": "2026-04-16"}

    with cycls.Workspace(tmp_path):
        d = cycls.Dict("sessions")
        assert d["abc"] == {"title": "Budget", "updatedAt": "2026-04-16"}


def test_dict_outside_scope_raises():
    with pytest.raises(RuntimeError, match="outside a workspace scope"):
        cycls.Dict("usage")


def test_dict_update_and_delete(tmp_path):
    with cycls.Workspace(tmp_path):
        d = cycls.Dict("x")
        d["a"] = 1
        d.update(b=2, c=3)
        assert d["a"] == 1 and d["b"] == 2 and d["c"] == 3
        del d["b"]
        assert "b" not in d

    raw = json.loads((tmp_path / ".cycls" / "x.json").read_text())
    assert raw == {"a": 1, "c": 3}


def test_getitem_returns_deep_copy(tmp_path):
    """Mutating the returned value must not secretly mutate stored state."""
    with cycls.Workspace(tmp_path):
        d = cycls.Dict("usage")
        d["2026-04"] = {"count": 0}

        entry = d["2026-04"]
        entry["count"] = 999  # mutate the copy — must NOT persist

        assert d["2026-04"]["count"] == 0


def test_atomic_write_leaves_no_tmp_on_success(tmp_path):
    with cycls.Workspace(tmp_path):
        d = cycls.Dict("x")
        d["a"] = 1

    data_dir = tmp_path / ".cycls"
    assert (data_dir / "x.json").exists()
    assert not (data_dir / "x.json.tmp").exists()


def test_user_id_produces_nested_path(tmp_path):
    with cycls.Workspace(tmp_path, user_id="u_42"):
        d = cycls.Dict("sessions")
        d["s1"] = {"title": "hi"}

    assert (tmp_path / ".cycls" / "u_42" / "sessions.json").exists()


def test_nested_with_restores_outer_scope(tmp_path):
    outer = tmp_path / "outer"
    inner = tmp_path / "inner"

    with cycls.Workspace(outer):
        cycls.Dict("x")["tag"] = "outer"
        with cycls.Workspace(inner):
            cycls.Dict("x")["tag"] = "inner"
        # after inner exits, outer is the active scope again
        cycls.Dict("x")["tag2"] = "outer2"

    outer_data = json.loads((outer / ".cycls" / "x.json").read_text())
    inner_data = json.loads((inner / ".cycls" / "x.json").read_text())
    assert outer_data == {"tag": "outer", "tag2": "outer2"}
    assert inner_data == {"tag": "inner"}


def test_scope_cleared_after_with(tmp_path):
    with cycls.Workspace(tmp_path):
        cycls.Dict("x")
    with pytest.raises(RuntimeError):
        cycls.Dict("x")

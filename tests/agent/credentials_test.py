"""The credential store: encrypted at rest, user before workspace, both slots
sandbox-masked and path-guarded like .db."""
import asyncio
import pytest
from cycls._agent import credentials
from cycls._app.db import workspace


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("CYCLS_SECRET_KEY", "k1")


def _ws(tmp_path, subject="org:u1", ws="t-team"):
    return workspace(subject, tmp_path, base=f"file://{tmp_path}", ws=ws)


def _get(ws, name): return asyncio.run(credentials.get(ws, name))
def _put(ws, name, v, **k): asyncio.run(credentials.put(ws, name, v, **k))


def test_round_trip_is_encrypted_on_disk(tmp_path):
    ws = _ws(tmp_path)
    _put(ws, "salla", {"token": "tok-123"})
    assert _get(ws, "salla") == {"token": "tok-123"}
    on_disk = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    assert b"tok-123" not in on_disk


def test_user_beats_workspace_beats_nothing(tmp_path):
    ws = _ws(tmp_path)
    assert _get(ws, "salla") is None
    _put(ws, "salla", "shared", shared=True)
    assert _get(ws, "salla") == "shared"
    _put(ws, "salla", "mine")
    assert _get(ws, "salla") == "mine"
    asyncio.run(credentials.delete(ws, "salla"))
    assert _get(ws, "salla") == "shared"


def test_isolation(tmp_path):
    """A user's record follows them across workspaces and is invisible to other
    users; a workspace's record belongs to that workspace alone."""
    u1_team, u1_home = _ws(tmp_path, "org:u1", "t-team"), _ws(tmp_path, "org:u1", "u-u1")
    u2_team, u1_other = _ws(tmp_path, "org:u2", "t-team"), _ws(tmp_path, "org:u1", "t-other")
    _put(u1_team, "gmail", "u1")
    assert _get(u1_home, "gmail") == "u1"
    assert _get(u2_team, "gmail") is None
    _put(u1_team, "salla", "team", shared=True)
    assert _get(u2_team, "salla") == "team"
    assert _get(u1_other, "salla") is None


def test_rotated_key_reads_as_absent(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    _put(ws, "salla", "v")
    monkeypatch.setenv("CYCLS_SECRET_KEY", "k2")
    assert _get(ws, "salla") is None


def test_missing_key_refuses_to_store(tmp_path, monkeypatch):
    monkeypatch.delenv("CYCLS_SECRET_KEY")
    with pytest.raises(RuntimeError, match="CYCLS_SECRET_KEY"):
        _put(_ws(tmp_path), "salla", "v")


def test_both_slots_are_path_guarded(tmp_path):
    from cycls._agent.tools import _resolve_path
    from cycls._agent.web.routers import resolve_path
    for name in (".secrets", ".connectors"):
        with pytest.raises(ValueError, match="managed by cycls"):
            _resolve_path(f"{name}/x", str(tmp_path))
        with pytest.raises(ValueError, match="managed by cycls"):
            resolve_path(str(tmp_path), f"{name}/x")


def test_context_secret_reads_the_store(tmp_path):
    from cycls._agent.tools import ToolContext
    ws = _ws(tmp_path)
    _put(ws, "salla", "tok")
    assert asyncio.run(ToolContext(None, ws, None).secret("salla")) == "tok"

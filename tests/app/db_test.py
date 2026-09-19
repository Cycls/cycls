"""Tests for cycls.DB — async JSON KV over object storage at any URL.

Each test opens a real DB at a tmp path (file:// backend), exercising the
substrate that everything else depends on.
"""
import asyncio
from pathlib import Path

import pytest

from cycls._app import db
from cycls._app.db import DB


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def workspace(tmp_path):
    return db.workspace("tenant", tmp_path, base=f"file://{tmp_path}")


# ---------------------------------------------------------------------------
# URL composition
# ---------------------------------------------------------------------------

def test_workspace_personal_data_path(tmp_path):
    ws = db.workspace("user", tmp_path, base=f"file://{tmp_path}")
    assert ws.path == "user/.db"


def test_workspace_org_data_path(tmp_path):
    ws = db.workspace("org:member_1", tmp_path, base=f"file://{tmp_path}")
    assert ws.path == "org/.db/member_1"


def test_workspace_url_with_bucket(tmp_path):
    ws = db.workspace("user", tmp_path, base="gs://cycls-ws-myagent")
    assert ws.path == "user/.db"
    assert ws.base == "gs://cycls-ws-myagent"


def test_workspace_url_with_bucket_org(tmp_path):
    ws = db.workspace("org:member_1", tmp_path, base="gs://cycls-ws-myagent")
    assert ws.path == "org/.db/member_1"
    assert ws.base == "gs://cycls-ws-myagent"


def test_workspace_volume_property(tmp_path):
    assert db.workspace("org:member_1", tmp_path).volume == tmp_path
    assert db.workspace("user", tmp_path).volume == tmp_path


# ---------------------------------------------------------------------------
# Multi-workspace mode (ws=) — docs/workspaces.md
# ---------------------------------------------------------------------------

def test_workspace_ws_org_personal(tmp_path):
    ws = db.workspace("org:member_1", tmp_path, base=f"file://{tmp_path}", ws="u-member_1")
    assert ws.root == tmp_path / "org" / "ws" / "u-member_1"
    assert ws.path == "org/ws/u-member_1/.db/member_1"
    assert ws.ws == "u-member_1"
    assert ws.volume == tmp_path


def test_workspace_ws_solo_user_is_the_root(tmp_path):
    """A solo account's personal workspace collapses to the account root —
    the legacy layout; solo data never migrates for the workspaces flag."""
    ws = db.workspace("user", tmp_path, ws="u-user")
    assert ws.root == tmp_path / "user"
    assert ws.path == "user/.db"
    assert ws.volume == tmp_path


def test_workspace_ws_team_id(tmp_path):
    ws = db.workspace("org:member_1", tmp_path, ws="t-abc123")
    assert ws.root == tmp_path / "org" / "ws" / "t-abc123"
    assert ws.path == "org/ws/t-abc123/.db/member_1"


def test_workspace_ws_invalid_id_raises(tmp_path):
    for bad in ("..", "u-", "t-", "shared", "u-a/b", "u-a.b", "x-abc", "u-../evil", ""):
        with pytest.raises(ValueError):
            db.workspace("org:member_1", tmp_path, ws=bad)


def test_workspace_subject_traversal_raises(tmp_path):
    for bad in ("..", ".", "../evil", "a/b", "org:..", "org:a/b", "..\\evil"):
        with pytest.raises(ValueError):
            db.workspace(bad, tmp_path)


# ---------------------------------------------------------------------------
# Basic ops
# ---------------------------------------------------------------------------

def test_put_get_round_trip(workspace):
    async def t():
        db = DB(workspace)
        await db.put("test/k", {"a": 1})
        assert await db.get("test/k") == {"a": 1}
    _run(t())


def test_get_missing_returns_none(workspace):
    async def t():
        db = DB(workspace)
        assert await db.get("nope") is None
    _run(t())


def test_get_missing_returns_default(workspace):
    async def t():
        db = DB(workspace)
        assert await db.get("nope", default={"x": 0}) == {"x": 0}
    _run(t())


def test_delete(workspace):
    async def t():
        db = DB(workspace)
        await db.put("k", 1)
        await db.delete("k")
        assert await db.get("k") is None
    _run(t())


def test_json_roundtrip_preserves_types(workspace):
    async def t():
        db = DB(workspace)
        for v in [{"a": 1}, [1, 2, 3], "string", 42, True, False, None]:
            await db.put("k", v)
            assert await db.get("k") == v
    _run(t())


def test_overwrite(workspace):
    async def t():
        db = DB(workspace)
        await db.put("k", "first")
        await db.put("k", "second")
        assert await db.get("k") == "second"
    _run(t())


# ---------------------------------------------------------------------------
# Iteration
# ---------------------------------------------------------------------------

def test_items_returns_all(workspace):
    async def t():
        db = DB(workspace)
        await db.put("a", 1)
        await db.put("b", 2)
        await db.put("c", 3)
        items = sorted([(k, v) async for k, v in db.items()])
        assert items == [("a", 1), ("b", 2), ("c", 3)]
    _run(t())


def test_items_returns_full_keys(workspace):
    """Keys come back as stored — no automatic prefix stripping."""
    async def t():
        db = DB(workspace)
        await db.put("sessions/abc", "value")
        keys = [k async for k, _ in db.items(prefix="sessions/")]
        assert keys == ["sessions/abc"]
    _run(t())


def test_items_filtered_by_prefix(workspace):
    async def t():
        db = DB(workspace)
        await db.put("foo/1", 1)
        await db.put("foo/2", 2)
        await db.put("bar/1", 3)
        items = sorted([(k, v) async for k, v in db.items(prefix="foo/")])
        assert items == [("foo/1", 1), ("foo/2", 2)]
    _run(t())


def test_items_empty(workspace):
    async def t():
        db = DB(workspace)
        items = [i async for i in db.items()]
        assert items == []
    _run(t())


def test_prefix_isolation(workspace):
    """Prefixes are caller convention; same suffix under two prefixes never collides."""
    async def t():
        db = DB(workspace)
        await db.put("sessions/k", "session-value")
        await db.put("usage/k", "usage-value")
        assert await db.get("sessions/k") == "session-value"
        assert await db.get("usage/k") == "usage-value"
        s = sorted([k async for k, _ in db.items(prefix="sessions/")])
        u = sorted([k async for k, _ in db.items(prefix="usage/")])
        assert s == ["sessions/k"] and u == ["usage/k"]
    _run(t())


# ---------------------------------------------------------------------------
# create=True — a write that refuses to clobber (docs/notes/runs.md)
# ---------------------------------------------------------------------------

def test_create_refuses_to_overwrite_and_leaves_the_value(workspace):
    async def t():
        d = DB(workspace)
        await d.put("chat/c/000000", {"turn": "first"}, create=True)
        with pytest.raises(db.Conflict) as e:
            await d.put("chat/c/000000", {"turn": "second"}, create=True)
        assert e.value.key == "chat/c/000000"
        assert await d.get("chat/c/000000") == {"turn": "first"}
    _run(t())


def test_put_still_overwrites_by_default(workspace):
    """replace_messages, put_meta and the KV tool all rewrite in place."""
    async def t():
        d = DB(workspace)
        await d.put("k", "one")
        await d.put("k", "two")
        assert await d.get("k") == "two"
    _run(t())


def test_concurrent_creates_leave_exactly_one_winner(workspace):
    """The duplicate-POST case: whoever loses gets Conflict, not a torn file."""
    async def t():
        d = DB(workspace)
        results = await asyncio.gather(
            *[d.put("chat/c/000000", {"writer": i}, create=True) for i in range(8)],
            return_exceptions=True)
        assert sum(r is None for r in results) == 1, results
        assert all(isinstance(r, db.Conflict) for r in results if r is not None)
        assert (await d.get("chat/c/000000"))["writer"] in range(8)
    _run(t())


def test_keys_lists_a_file_it_cannot_decode(workspace):
    """`scan` reads bodies and drops what it cannot parse; `keys` must not, or a
    torn file survives the wipe in replace_messages and sits above the rewrite."""
    async def t():
        d = DB(workspace)
        await d.put("chat/c/000000", {"ok": True})
        torn = Path(workspace.base[7:]) / workspace.path / "chat" / "c" / "000001.json"
        torn.write_bytes(b"{not json")
        assert await d.keys(glob="chat/c/[0-9]*") == ["chat/c/000000", "chat/c/000001"]
        scanned = sorted([k async for k, _ in d.scan(glob="chat/c/[0-9]*")])
        assert scanned == ["chat/c/000000"], "scan is body-parsing, as documented"
    _run(t())



def test_gcs_create_sends_the_precondition_and_maps_412(monkeypatch):
    """The prod backend. ifGenerationMatch=0 must ride the URL — passing it as
    httpx `params=` would replace uploadType=multipart and corrupt the upload."""
    store = db._GCSStore("gs://bucket/prefix")
    seen = {}

    class _Resp:
        def __init__(self, code): self.status_code = code
        def raise_for_status(self):
            if self.status_code >= 400: raise AssertionError("should not reach raise_for_status")

    async def fake_req(method, url, **kw):
        seen["url"] = url
        return _Resp(seen.pop("code", 200))

    monkeypatch.setattr(store, "_req", fake_req)
    _run(store.write("chat/c/000000", b"{}"))
    assert "ifGenerationMatch" not in seen["url"]

    _run(store.write("chat/c/000000", b"{}", create=True))
    assert seen["url"].endswith("?uploadType=multipart&ifGenerationMatch=0")

    seen["code"] = 412
    with pytest.raises(db.Conflict):
        _run(store.write("chat/c/000000", b"{}", create=True))

"""Tests for cycls.DB — async JSON KV over SlateDB at any URL.

Each test opens a real SlateDB at a tmp path. Slow-ish but exercises the
substrate that everything else depends on.
"""
import asyncio
import pytest

from cycls.app.db import DB
from cycls.app.tenancy import workspace_at


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def workspace(tmp_path):
    return workspace_at("tenant", tmp_path, base=f"file://{tmp_path}")


# ---------------------------------------------------------------------------
# URL composition
# ---------------------------------------------------------------------------

def test_workspace_personal_data_path(tmp_path):
    ws = workspace_at("user", tmp_path, base=f"file://{tmp_path}")
    assert DB(ws)._url == f"file://{tmp_path}/user/.db"


def test_workspace_org_data_path(tmp_path):
    ws = workspace_at("org/member_1", tmp_path, base=f"file://{tmp_path}")
    assert DB(ws)._url == f"file://{tmp_path}/org/.db/member_1"


def test_workspace_url_with_bucket(tmp_path):
    ws = workspace_at("user", tmp_path, base="gs://cycls-ws-myagent")
    assert DB(ws)._url == "gs://cycls-ws-myagent/user/.db"


def test_workspace_url_with_bucket_org(tmp_path):
    ws = workspace_at("org/member_1", tmp_path, base="gs://cycls-ws-myagent")
    assert DB(ws)._url == "gs://cycls-ws-myagent/org/.db/member_1"


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
# Transactions
# ---------------------------------------------------------------------------

def test_transaction_commits_on_clean_exit(workspace):
    async def t():
        db = DB(workspace)
        async with db.transaction() as txn:
            await txn.put("a", 1)
            await txn.put("b", 2)
        assert await db.get("a") == 1
        assert await db.get("b") == 2
    _run(t())


def test_transaction_rolls_back_on_exception(workspace):
    async def t():
        db = DB(workspace)
        await db.put("a", "original")
        with pytest.raises(RuntimeError, match="boom"):
            async with db.transaction() as txn:
                await txn.put("a", "modified")
                raise RuntimeError("boom")
        assert await db.get("a") == "original"
    _run(t())


def test_transaction_atomic_prefix_delete_then_rewrite(workspace):
    async def t():
        db = DB(workspace)
        await db.put("log/0", "old0")
        await db.put("log/1", "old1")
        await db.put("log/2", "old2")
        async with db.transaction() as txn:
            async for k, _ in txn.items(prefix="log/"):
                await txn.delete(k)
            await txn.put("log/0", "new0")
        items = sorted([(k, v) async for k, v in db.items(prefix="log/")])
        assert items == [("log/0", "new0")]
    _run(t())

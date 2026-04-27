"""Tests for cycls.KV — async K/V primitive backed by SlateDB.

Each test opens a real SlateDB at a tmp path. Slow-ish but exercises the
substrate that everything else depends on.
"""
import asyncio
import pytest

from cycls.app.db import KV, Workspace, request_scope


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def workspace(tmp_path):
    ws_root = tmp_path / "tenant"
    ws_root.mkdir()
    return Workspace(ws_root)


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

def test_workspace_personal_data_path(tmp_path):
    ws = Workspace(tmp_path / "user")
    assert ws.data == tmp_path / "user" / ".cycls"


def test_workspace_org_data_path(tmp_path):
    """Org members nest under .cycls/{user_id} so a shared mount stays isolated."""
    ws = Workspace(tmp_path / "org", user_id="member_1")
    assert ws.data == tmp_path / "org" / ".cycls" / "member_1"


def test_workspace_url_file_fallback(tmp_path):
    """No bucket → file:// to data path."""
    ws = Workspace(tmp_path / "user")
    url = ws.url()
    assert url.startswith("file://")
    assert url.endswith("/.cycls")


def test_workspace_url_with_bucket(tmp_path):
    """bucket=... → object-store URL with tenant-relative path appended."""
    ws = Workspace(tmp_path / "user", bucket="gs://cycls-ws-myagent")
    assert ws.url() == "gs://cycls-ws-myagent/user/.cycls"


def test_workspace_url_with_bucket_org(tmp_path):
    ws = Workspace(tmp_path / "org", user_id="member_1", bucket="gs://cycls-ws-myagent")
    assert ws.url() == "gs://cycls-ws-myagent/org/.cycls/member_1"


# ---------------------------------------------------------------------------
# KV — basic operations
# ---------------------------------------------------------------------------

def test_kv_put_get_round_trip(workspace):
    async def t():
        kv = KV("test", workspace)
        await kv.put("k", {"a": 1})
        assert await kv.get("k") == {"a": 1}
    _run(t())


def test_kv_get_missing_returns_none(workspace):
    async def t():
        kv = KV("test", workspace)
        assert await kv.get("nope") is None
    _run(t())


def test_kv_get_missing_returns_default(workspace):
    async def t():
        kv = KV("test", workspace)
        assert await kv.get("nope", default={"x": 0}) == {"x": 0}
    _run(t())


def test_kv_delete(workspace):
    async def t():
        kv = KV("test", workspace)
        await kv.put("k", 1)
        await kv.delete("k")
        assert await kv.get("k") is None
    _run(t())


def test_kv_json_roundtrip_preserves_types(workspace):
    """JSON values round-trip cleanly — dicts, lists, strings, ints, bools, None."""
    async def t():
        kv = KV("test", workspace)
        for v in [{"a": 1}, [1, 2, 3], "string", 42, True, False, None]:
            await kv.put("k", v)
            assert await kv.get("k") == v
    _run(t())


def test_kv_overwrite(workspace):
    async def t():
        kv = KV("test", workspace)
        await kv.put("k", "first")
        await kv.put("k", "second")
        assert await kv.get("k") == "second"
    _run(t())


# ---------------------------------------------------------------------------
# KV — iteration
# ---------------------------------------------------------------------------

def test_kv_items_returns_all_in_namespace(workspace):
    async def t():
        kv = KV("test", workspace)
        await kv.put("a", 1)
        await kv.put("b", 2)
        await kv.put("c", 3)
        items = sorted([(k, v) async for k, v in kv.items()])
        assert items == [("a", 1), ("b", 2), ("c", 3)]
    _run(t())


def test_kv_items_strips_namespace_from_keys(workspace):
    """Returned keys should be exactly what the caller put — no leaked namespace prefix."""
    async def t():
        kv = KV("sessions", workspace)
        await kv.put("abc", "value")
        keys = [k async for k, _ in kv.items()]
        assert keys == ["abc"]
    _run(t())


def test_kv_items_filtered_by_prefix(workspace):
    async def t():
        kv = KV("test", workspace)
        await kv.put("foo/1", 1)
        await kv.put("foo/2", 2)
        await kv.put("bar/1", 3)
        items = sorted([(k, v) async for k, v in kv.items(prefix="foo/")])
        assert items == [("foo/1", 1), ("foo/2", 2)]
    _run(t())


def test_kv_items_empty(workspace):
    async def t():
        kv = KV("test", workspace)
        items = [i async for i in kv.items()]
        assert items == []
    _run(t())


# ---------------------------------------------------------------------------
# KV — namespace isolation
# ---------------------------------------------------------------------------

def test_multiple_kvs_share_db_but_isolated_by_namespace(workspace):
    """Two KVs on the same workspace can use the same key without collision —
    they're prefix-views into one SlateDB instance."""
    async def t():
        sessions = KV("sessions", workspace)
        usage = KV("usage", workspace)
        await sessions.put("k", "session-value")
        await usage.put("k", "usage-value")
        assert await sessions.get("k") == "session-value"
        assert await usage.get("k") == "usage-value"
        # Listings don't leak across namespaces
        s_keys = sorted([k async for k, _ in sessions.items()])
        u_keys = sorted([k async for k, _ in usage.items()])
        assert s_keys == ["k"] and u_keys == ["k"]
    _run(t())


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def test_transaction_commits_on_clean_exit(workspace):
    async def t():
        kv = KV("test", workspace)
        async with kv.transaction() as txn:
            await txn.put("a", 1)
            await txn.put("b", 2)
        assert await kv.get("a") == 1
        assert await kv.get("b") == 2
    _run(t())


def test_transaction_rolls_back_on_exception(workspace):
    """If the body raises, the transaction reverts — original value preserved."""
    async def t():
        kv = KV("test", workspace)
        await kv.put("a", "original")
        with pytest.raises(RuntimeError, match="boom"):
            async with kv.transaction() as txn:
                await txn.put("a", "modified")
                raise RuntimeError("boom")
        assert await kv.get("a") == "original"
    _run(t())


def test_transaction_atomic_prefix_delete_then_rewrite(workspace):
    """The compaction pattern: wipe all matching keys then write new ones, atomically."""
    async def t():
        kv = KV("test", workspace)
        await kv.put("log/0", "old0")
        await kv.put("log/1", "old1")
        await kv.put("log/2", "old2")
        async with kv.transaction() as txn:
            async for k, _ in txn.items(prefix="log/"):
                await txn.delete(k)
            await txn.put("log/0", "new0")
        items = sorted([(k, v) async for k, v in kv.items(prefix="log/")])
        assert items == [("log/0", "new0")]
    _run(t())


# ---------------------------------------------------------------------------
# request_scope — ops in the same scope share one Db open
# ---------------------------------------------------------------------------

def test_request_scope_caches_db_across_ops(workspace):
    """All KV ops inside `request_scope` should reuse the same Db instance."""
    async def t():
        kv = KV("test", workspace)
        async with request_scope():
            await kv.put("a", 1)
            await kv.put("b", 2)
            await kv.put("c", 3)
            items = sorted([(k, v) async for k, v in kv.items()])
            assert items == [("a", 1), ("b", 2), ("c", 3)]
    _run(t())


def test_request_scope_isolation(workspace):
    """Two scopes are independent: the second sees what the first persisted."""
    async def t():
        kv = KV("test", workspace)
        async with request_scope():
            await kv.put("x", "first")
        async with request_scope():
            assert await kv.get("x") == "first"
    _run(t())

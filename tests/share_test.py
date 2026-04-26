"""Tests for cycls.agent.share — frozen public shares with KV ownership.

Owner-deletable, anyone-readable. Snapshots live at a workspace-global path
so they survive even if the owner's account is deleted; ownership is tracked
in a per-user `KV("share", ws)` index.
"""
import asyncio
import pytest

from cycls.app.db import Workspace
from cycls.agent import share


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env(tmp_path):
    """Volume + a single tenant workspace."""
    volume = tmp_path / "volume"
    volume.mkdir()
    ws_root = volume / "tenant_a"
    ws_root.mkdir()
    return volume, Workspace(ws_root)


# ---------------------------------------------------------------------------
# Create / list / read
# ---------------------------------------------------------------------------

def test_create_share_basic(env):
    volume, ws = env
    async def t():
        msgs = [{"role": "user", "content": "hi"}]
        sid, snap = await share.create_share(ws, volume, messages=msgs, title="Test")
        assert len(sid) == 12  # uuid4().hex[:12]
        assert snap["title"] == "Test"
        assert snap["messages"] == msgs
        # snapshot.json on disk at the global path
        snap_file = volume / ".cycls" / "shared" / sid / "snapshot.json"
        assert snap_file.is_file()
        # Owner has it in their KV index
        assert await share.is_owner(ws, sid)
    _run(t())


def test_create_share_copies_attachments_and_rewrites_url(env):
    volume, ws = env
    (ws.root / "doc.pdf").write_bytes(b"pdf-bytes")
    async def t():
        msgs = [{
            "role": "user",
            "content": "with attachment",
            "attachments": [{"path": "doc.pdf", "name": "doc.pdf"}],
        }]
        sid, _ = await share.create_share(ws, volume, messages=msgs)
        copied = volume / ".cycls" / "shared" / sid / "assets" / "doc.pdf"
        assert copied.is_file()
        assert copied.read_bytes() == b"pdf-bytes"
        # The message's attachment now has a public URL
        assert msgs[0]["attachments"][0]["url"] == f"/shared-assets/{sid}/doc.pdf"
    _run(t())


def test_list_shares_returns_only_owner_shares(tmp_path):
    """Tenant A's shares aren't visible in tenant B's list."""
    volume = tmp_path / "volume"
    volume.mkdir()
    (volume / "tenant_a").mkdir()
    (volume / "tenant_b").mkdir()
    ws_a = Workspace(volume / "tenant_a")
    ws_b = Workspace(volume / "tenant_b")
    async def t():
        sid_a, _ = await share.create_share(ws_a, volume, messages=[{"role": "user", "content": "a"}])
        sid_b, _ = await share.create_share(ws_b, volume, messages=[{"role": "user", "content": "b"}])
        a_items = [i async for i in share.list_shares(ws_a)]
        b_items = [i async for i in share.list_shares(ws_b)]
        assert [sid for sid, _ in a_items] == [sid_a]
        assert [sid for sid, _ in b_items] == [sid_b]
    _run(t())


# ---------------------------------------------------------------------------
# Public read (no auth, no workspace)
# ---------------------------------------------------------------------------

def test_read_snapshot_public(env):
    volume, ws = env
    async def t():
        sid, _ = await share.create_share(ws, volume, messages=[{"role": "user", "content": "hi"}], title="T")
        snap = share.read_snapshot(volume, sid)
        assert snap is not None
        assert snap["title"] == "T"
    _run(t())


def test_read_snapshot_missing_returns_none(env):
    volume, _ = env
    assert share.read_snapshot(volume, "nonexistent00") is None


def test_read_snapshot_blocks_invalid_id(env):
    """Path traversal attempts return None, not a stack trace."""
    volume, _ = env
    assert share.read_snapshot(volume, "../etc") is None
    assert share.read_snapshot(volume, "..") is None
    assert share.read_snapshot(volume, ".hidden") is None
    assert share.read_snapshot(volume, "sub/dir") is None


# ---------------------------------------------------------------------------
# Asset serving
# ---------------------------------------------------------------------------

def test_asset_path_returns_when_exists(env):
    volume, ws = env
    (ws.root / "img.png").write_bytes(b"fake-png")
    async def t():
        sid, _ = await share.create_share(
            ws, volume,
            messages=[{
                "role": "user", "content": "x",
                "attachments": [{"path": "img.png", "name": "img.png"}],
            }],
        )
        p = share.asset_path(volume, sid, "img.png")
        assert p is not None
        assert p.read_bytes() == b"fake-png"
    _run(t())


def test_asset_path_missing_returns_none(env):
    volume, _ = env
    assert share.asset_path(volume, "any_share", "missing.png") is None


def test_asset_path_blocks_traversal(env):
    """Filename guards block escape attempts."""
    volume, _ = env
    assert share.asset_path(volume, "any", "../etc/passwd") is None
    assert share.asset_path(volume, "any", ".hidden") is None
    assert share.asset_path(volume, "any", "sub/file") is None


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_is_owner_true_for_creator(env):
    volume, ws = env
    async def t():
        sid, _ = await share.create_share(ws, volume, messages=[{"role": "user", "content": "x"}])
        assert await share.is_owner(ws, sid)
    _run(t())


def test_is_owner_false_for_other_tenant_but_publicly_readable(tmp_path):
    """Tenant A creates a share. Tenant B isn't the owner, but can still read it
    publicly — that's the whole point of frozen shares."""
    volume = tmp_path / "volume"
    volume.mkdir()
    (volume / "tenant_a").mkdir()
    (volume / "tenant_b").mkdir()
    ws_a = Workspace(volume / "tenant_a")
    ws_b = Workspace(volume / "tenant_b")
    async def t():
        sid, _ = await share.create_share(ws_a, volume, messages=[{"role": "user", "content": "x"}])
        # B doesn't own A's share
        assert not await share.is_owner(ws_b, sid)
        # But can read it
        assert share.read_snapshot(volume, sid) is not None
    _run(t())


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_share_removes_kv_and_dir(env):
    volume, ws = env
    async def t():
        sid, _ = await share.create_share(ws, volume, messages=[{"role": "user", "content": "x"}])
        sdir = volume / ".cycls" / "shared" / sid
        assert sdir.is_dir()
        assert await share.is_owner(ws, sid)

        await share.delete_share(ws, volume, sid)

        assert not sdir.exists()
        assert not await share.is_owner(ws, sid)
        assert share.read_snapshot(volume, sid) is None
    _run(t())


def test_delete_share_idempotent(env):
    """Deleting a non-existent share doesn't crash."""
    volume, ws = env
    async def t():
        # Never created — delete is a no-op
        await share.delete_share(ws, volume, "nothere00xxxx")
    _run(t())


def test_share_outlives_owner_workspace_deletion(env, tmp_path):
    """The frozen snapshot lives at a global path, not inside the owner's
    workspace — so deleting their workspace dir leaves the share resolvable."""
    volume, ws = env
    import shutil
    async def t():
        sid, _ = await share.create_share(ws, volume, messages=[{"role": "user", "content": "x"}], title="P")
        # Nuke the owner's workspace dir entirely
        shutil.rmtree(ws.root)
        # Public read still works — snapshot lives elsewhere
        snap = share.read_snapshot(volume, sid)
        assert snap is not None
        assert snap["title"] == "P"
    _run(t())

"""Frozen public shares of a chat — owner-deletable, anyone-readable.

A share is a frozen snapshot. Ownership lives in the owner's per-user
`KV("share", workspace)` index; the snapshot itself lives at a workspace-
global path so it survives even if the owner's account is deleted.

    KV("share", owner_ws)
        {share_id} → metadata (title, sharedAt, ...) — owner-only

    {volume}/.cycls/shared/{share_id}/
        snapshot.json   — messages + metadata, public-readable
        assets/         — copied attachments (blobs stay on the filesystem)

Public read goes straight to the global path — no per-user lookup, no
authorization check. The path *is* the resolver.
"""
import json
import shutil
from datetime import datetime, timezone
from uuid import uuid4

from cycls.app.db import KV


def _shared_root(volume):
    return volume / ".cycls" / "shared"


def _share_dir(share_id, volume):
    if "/" in share_id or ".." in share_id or share_id.startswith("."):
        raise ValueError(f"Invalid share id: {share_id}")
    return _shared_root(volume) / share_id


def _kv(workspace):
    return KV("share", workspace)


# ---- Owner operations (auth'd) ----

async def list_shares(workspace):
    """Yield (share_id, metadata) for shares owned by this workspace."""
    async for sid, meta in _kv(workspace).items():
        yield sid, meta


async def is_owner(workspace, share_id):
    return (await _kv(workspace).get(share_id)) is not None


async def create_share(workspace, volume, *, messages, title="", author=None):
    """Freeze a chat: copy attachments to the global snapshot dir, write
    snapshot.json, register in the owner's KV. Returns (share_id, snapshot).
    The *messages* list is mutated in place to set asset URLs."""
    share_id = uuid4().hex[:12]
    sdir = _share_dir(share_id, volume)
    (sdir / "assets").mkdir(parents=True, exist_ok=True)

    for msg in messages:
        for att in msg.get("attachments") or []:
            att_path = att.get("path")
            if not att_path:
                continue
            src = workspace.root / att_path
            if src.is_file():
                shutil.copy2(src, sdir / "assets" / src.name)
                att["url"] = f"/shared-assets/{share_id}/{src.name}"

    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "id": share_id,
        "title": title,
        "author": author,
        "sharedAt": now,
        "messages": messages,
    }
    (sdir / "snapshot.json").write_text(json.dumps(snapshot))

    await _kv(workspace).put(share_id, {
        "id": share_id,
        "title": title,
        "sharedAt": now,
    })

    return share_id, snapshot


async def delete_share(workspace, volume, share_id):
    """Remove from owner's KV and rmtree the snapshot dir. Caller must verify
    ownership via is_owner first."""
    sdir = _share_dir(share_id, volume)
    if sdir.is_dir():
        shutil.rmtree(sdir)
    await _kv(workspace).delete(share_id)


# ---- Public read (no auth) ----

def read_snapshot(volume, share_id):
    """Public — read the frozen snapshot. Returns None if missing."""
    try:
        sdir = _share_dir(share_id, volume)
    except ValueError:
        return None
    snap = sdir / "snapshot.json"
    if not snap.is_file():
        return None
    return json.loads(snap.read_text())


def asset_path(volume, share_id, filename):
    """Public — return Path to a shared asset, or None if missing/invalid."""
    if "/" in filename or ".." in filename or filename.startswith("."):
        return None
    try:
        sdir = _share_dir(share_id, volume)
    except ValueError:
        return None
    p = sdir / "assets" / filename
    return p if p.is_file() else None

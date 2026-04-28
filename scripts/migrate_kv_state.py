"""One-shot migration: legacy on-disk state → KV.

Run after deploying the KV-shaped state code on a volume that has pre-migration
data. Reads the legacy file layouts and writes to the new KV-backed storage.

Migrates:
    .sessions/{chat_id}.history.jsonl       → KV("chat", ws): log/{chat_id}/{turn:06d}
    .sessions/{chat_id}.json                → KV("chat", ws): meta/{chat_id}
    .sessions/public/{share_id}/share.json  → {volume}/.cycls/shared/{share_id}/snapshot.json
    .sessions/public/{share_id}/{file}      → {volume}/.cycls/shared/{share_id}/assets/{file}
                                            + KV("share", ws): {share_id}

Org tenants are detected by the absence of `.history.jsonl` files directly in
`.sessions/` — each member is a subdir.

Idempotent. Legacy files are left in place — verify, then `rm -rf .sessions/`
per tenant and the old `{volume}/shared/` pointer dir.

Usage:
    uv run --with slatedb python scripts/migrate_kv_state.py [--volume /workspace] [--dry-run]
"""
import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cycls.app.db import DB
from cycls.app.workspace import workspace_at
from cycls.agent import chat


async def _migrate_chat_logs(ws, member_dir, dry_run):
    for jsonl_file in member_dir.glob("*.history.jsonl"):
        chat_id = jsonl_file.name.removesuffix(".history.jsonl")
        messages = []
        try:
            with open(jsonl_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"  [warn] {jsonl_file}: skip malformed line — {e}")
        except UnicodeDecodeError:
            print(f"  [warn] {jsonl_file}: encoding error, skipping")
            continue

        meta = None
        meta_file = member_dir / f"{chat_id}.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text())
            except json.JSONDecodeError:
                pass

        verb = "would" if dry_run else "did"
        extra = " + meta" if meta else ""
        print(f"  chat {chat_id}: {verb} migrate {len(messages)} message(s){extra}")
        if dry_run:
            continue
        if messages:
            await chat.append_messages(ws, chat_id, messages, start_idx=0)
        if meta:
            await chat.put_meta(ws, chat_id, meta)


async def _migrate_shares(ws, member_dir, volume, dry_run):
    public = member_dir / "public"
    if not public.is_dir():
        return
    new_root = volume / ".cycls" / "shared"
    share_kv = DB(ws).kv("share")
    for old in public.iterdir():
        if not old.is_dir():
            continue
        share_id = old.name
        snap_old = old / "share.json"
        if not snap_old.is_file():
            continue
        try:
            snap = json.loads(snap_old.read_text())
        except json.JSONDecodeError:
            print(f"  [warn] {snap_old}: invalid JSON, skipping")
            continue

        new_dir = new_root / share_id
        verb = "would" if dry_run else "did"
        print(f"  share {share_id}: {verb} migrate to {new_dir}")
        if dry_run:
            continue

        new_dir.mkdir(parents=True, exist_ok=True)
        (new_dir / "assets").mkdir(exist_ok=True)
        (new_dir / "snapshot.json").write_text(json.dumps(snap))
        for f in old.iterdir():
            if f.name == "share.json" or not f.is_file():
                continue
            shutil.copy2(f, new_dir / "assets" / f.name)
        await share_kv.put(share_id, {
            "id": share_id,
            "title": snap.get("title", ""),
            "sharedAt": snap.get("sharedAt", ""),
        })


async def _migrate_tenant(tenant_root, volume, dry_run):
    sessions = tenant_root / ".sessions"
    if not sessions.is_dir():
        return
    print(f"tenant {tenant_root.name}:")

    # Personal: .history.jsonl directly in .sessions/
    if any(sessions.glob("*.history.jsonl")):
        ws = workspace_at(tenant_root.name, tenant_root.parent)
        await _migrate_chat_logs(ws, sessions, dry_run)
        await _migrate_shares(ws, sessions, volume, dry_run)
        return

    # Org: each member is a subdir of .sessions/
    found_member = False
    for member_dir in sessions.iterdir():
        if not member_dir.is_dir() or member_dir.name == "public":
            continue
        found_member = True
        print(f" member {member_dir.name}:")
        ws = workspace_at(f"{tenant_root.name}/{member_dir.name}", tenant_root.parent)
        await _migrate_chat_logs(ws, member_dir, dry_run)
        await _migrate_shares(ws, member_dir, volume, dry_run)

    # Personal with shares but no chats
    if not found_member and (sessions / "public").is_dir():
        ws = workspace_at(tenant_root.name, tenant_root.parent)
        await _migrate_shares(ws, sessions, volume, dry_run)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--volume", default="/workspace", help="Volume root (default: /workspace)")
    ap.add_argument("--dry-run", action="store_true", help="Show what would happen without writing")
    args = ap.parse_args()

    volume = Path(args.volume)
    if not volume.is_dir():
        print(f"volume not found: {volume}", file=sys.stderr)
        sys.exit(1)

    for tenant_root in sorted(volume.iterdir()):
        if not tenant_root.is_dir():
            continue
        # Skip the legacy global pointer dir and the new global shared root
        if tenant_root.name in ("shared", ".cycls"):
            continue
        await _migrate_tenant(tenant_root, volume, dry_run=args.dry_run)

    if args.dry_run:
        print("\n(dry run — no changes written)")
    else:
        print("\nmigration complete. legacy files untouched — verify, then `rm -rf .sessions/` per tenant + the old /workspace/shared/ dir.")


if __name__ == "__main__":
    asyncio.run(main())

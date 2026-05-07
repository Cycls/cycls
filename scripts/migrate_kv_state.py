"""One-shot migration: legacy on-disk chat state → SlateDB KV.

Run after deploying the SlateDB-shaped state code on a volume that has
pre-migration data. Reads the legacy file layouts and writes to SlateDB.

Migrates:
    .sessions/{chat_id}.history.jsonl   →  chat/log/{chat_id}/{turn:06d}
    .sessions/{chat_id}.json            →  chat/meta/{chat_id}

Org tenants are detected by the absence of `.history.jsonl` files
directly in `.sessions/` — each member is a subdir.

Legacy share assets at `.sessions/public/{share_id}/...` are NOT migrated.
The share product changed shape with RFC003 (opaque tokens + path-pointer
instead of content snapshots); legacy shares are left untouched on disk
for archival but won't be reachable through the new resolver.

Idempotent. Legacy files are left in place — verify, then
`rm -rf .sessions/` per tenant once you've validated.

Usage (dry-run first):
    uv run python scripts/migrate_kv_state.py --volume /workspace --base gs://cycls-ws-myagent --dry-run
    uv run python scripts/migrate_kv_state.py --volume /workspace --base gs://cycls-ws-myagent
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cycls.app.workspace import workspace_at, shutdown_pool
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


async def _migrate_tenant(tenant_root, base, dry_run):
    sessions = tenant_root / ".sessions"
    if not sessions.is_dir():
        return
    print(f"tenant {tenant_root.name}:")
    volume = tenant_root.parent

    # Personal: .history.jsonl files directly in .sessions/
    if any(sessions.glob("*.history.jsonl")):
        ws = workspace_at(tenant_root.name, volume, base=base)
        await _migrate_chat_logs(ws, sessions, dry_run)
        return

    # Org: each member is a subdir of .sessions/
    # Subject uses ':' separator (URL-path-safe; FastAPI rejects '/').
    for member_dir in sessions.iterdir():
        if not member_dir.is_dir() or member_dir.name == "public":
            continue
        print(f" member {member_dir.name}:")
        ws = workspace_at(f"{tenant_root.name}:{member_dir.name}", volume, base=base)
        await _migrate_chat_logs(ws, member_dir, dry_run)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--volume", default="/workspace",
                    help="Volume root (default: /workspace)")
    ap.add_argument("--base", required=True,
                    help="SlateDB base URL — gs://cycls-ws-<agent> for prod, "
                         "file:///{volume} for dry-run on a local copy")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would happen without writing")
    args = ap.parse_args()

    volume = Path(args.volume)
    if not volume.is_dir():
        print(f"volume not found: {volume}", file=sys.stderr)
        sys.exit(1)

    for tenant_root in sorted(volume.iterdir()):
        if not tenant_root.is_dir():
            continue
        # Skip the legacy global pointer dir and the new global shared root
        if tenant_root.name in ("shared", ".cycls", ".db"):
            continue
        await _migrate_tenant(tenant_root, args.base, dry_run=args.dry_run)

    # Flush all SlateDB handles before exit — writes are non-durable by
    # default; without this, in-memory state is lost when the script exits.
    await shutdown_pool()

    if args.dry_run:
        print("\n(dry run — no changes written)")
    else:
        print("\nmigration complete. legacy files untouched — verify, then "
              "`rm -rf .sessions/` per tenant.")


if __name__ == "__main__":
    asyncio.run(main())

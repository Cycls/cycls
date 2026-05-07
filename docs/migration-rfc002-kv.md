# RFC-002 cutover: JSONL-on-FUSE → SlateDB

One-shot migration of legacy `.sessions/{chat}.history.jsonl` + `{chat}.json`
to the SlateDB-backed `chat/log/` and `chat/meta/` keyspaces. Per-tenant.
Idempotent. Use this once per agent deployment that has pre-RFC002 data.

Legacy share assets at `.sessions/public/{share_id}/` are **not migrated**
— share product changed shape with RFC003 (opaque token + path-pointer);
legacy shares are abandoned in place for archival only.

---

## 1. Pre-flight

```bash
# Per agent: confirm tenants with legacy data
gsutil ls gs://cycls-ws-<agent>/  # list tenant dirs
gsutil du -sh gs://cycls-ws-<agent>/<tenant>/.sessions/  # size

# Confirm new code is deployed (but routing change is implicit — the
# new code already reads SlateDB on next request)
cycls ls
```

## 2. Dry-run on a snapshot

```bash
# Copy one tenant's legacy data to a local sandbox
mkdir -p /tmp/cutover/{tenant}
gsutil -m cp -r gs://cycls-ws-<agent>/<tenant>/.sessions /tmp/cutover/{tenant}/

# Dry-run against local file:// base
uv run python scripts/migrate_kv_state.py \
    --volume /tmp/cutover \
    --base file:///tmp/cutover \
    --dry-run

# Real migration locally — verify it writes
uv run python scripts/migrate_kv_state.py \
    --volume /tmp/cutover \
    --base file:///tmp/cutover

# Spot-check by loading messages back via Python
uv run python -c "
import asyncio
from cycls.app.workspace import workspace_at, shutdown_pool
from cycls.agent import chat
async def go():
    ws = workspace_at('{tenant}', '/tmp/cutover', base='file:///tmp/cutover')
    async for chat_id, meta in chat.list_chats(ws):
        msgs = await chat.load_messages(ws, chat_id)
        print(f'{chat_id}: {len(msgs)} messages, title={meta.get(\"title\")!r}')
    await shutdown_pool()
asyncio.run(go())
"
```

If counts and titles match the legacy `.sessions/` files, you're good.

## 3. Real migration (prod)

Recommended: **maintenance window** (~15–30 min for typical agents).
Zero-downtime via dual-read is possible but adds code we don't have today.

```bash
# Pause traffic at the cycls control plane (or via Cloud Run min-instances=0
# + max-instances=0 toggle, depending on your setup)

# Run migration with the prod base URL
uv run python scripts/migrate_kv_state.py \
    --volume /workspace \
    --base gs://cycls-ws-<agent>

# Verify — same spot-check as step 2 but against the gs:// base
uv run python -c "
import asyncio
from cycls.app.workspace import workspace_at, shutdown_pool
from cycls.agent import chat
async def go():
    ws = workspace_at('<tenant>', '/workspace', base='gs://cycls-ws-<agent>')
    async for chat_id, meta in chat.list_chats(ws):
        print(chat_id, meta.get('title'))
    await shutdown_pool()
asyncio.run(go())
"

# Resume traffic
```

The new code reads SlateDB on next request — no explicit "flip" needed.

## 4. Rollback

If post-cutover verification fails:

- Legacy `.sessions/` files are untouched. Revert cycls to the previous
  version (reads JSONL again) and traffic resumes against legacy data.
- New SlateDB writes since cutover would be lost; if cutover was clean
  and rollback happens within minutes, this is acceptable.
- For longer windows after cutover, rollback gets messy — fix forward
  instead.

## 5. Cleanup (after 7 days clean)

```bash
# Per tenant, after confirming the new shape is stable
gsutil -m rm -r gs://cycls-ws-<agent>/<tenant>/.sessions/
gsutil rm -r gs://cycls-ws-<agent>/shared/  # if it exists
```

## Notes

- Migration writes via SlateDB's default `_NON_DURABLE` setting — the
  script's `shutdown_pool()` call ensures all writes are flushed before
  exit. Don't ctrl-C mid-migration; partial writes can be lost.
- Re-running migration is safe (idempotent via deterministic turn-index
  keys), but only re-applies what's currently in `.sessions/`. Once the
  new code has appended SlateDB-only writes, do not re-run — it would
  overwrite recent messages with stale legacy state.
- One process per migration. Do not run concurrent migrations against
  the same tenant — SlateDB's writer fence will reject the loser.

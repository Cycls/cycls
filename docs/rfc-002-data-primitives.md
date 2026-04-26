# RFC 002: cycls.KV

**Companion**: [forward-compatibility audits](rfc-002-forward-compat.md)

---

## Status

| Phase | State | Where |
|---|---|---|
| `Workspace` + `KV` primitives | **Shipped** | `cycls/app/db/main.py` |
| Chat metadata + log unified on KV | **Shipped** | `cycls/agent/chat.py` — one `KV("chat")` with `meta/{id}` and `log/{id}/{turn}` prefixes |
| Auto-derived chat titles | **Shipped** | `cycls/agent/harness/main.py:_maybe_set_title` |
| Substrate auto-detection (FUSE → direct GCS) | **Shipped** | `Workspace.url()` |
| Shares (pointer indirection) | **Deferred** | `cycls/agent/web/routers.py:share_router` still file-based |

---

## The primitive

```python
import cycls

# Developer code
usage = cycls.KV("usage", context.workspace)
n = await usage.get("2026-04", {"count": 0})
await usage.put("2026-04", {"count": n["count"] + 1})

# Iterate everything in this KV
async for key, value in usage.items():
    ...

# Filter by sub-prefix
async for key, value in usage.items(prefix="2026-"):
    ...
```

`cycls.KV("name", workspace)` is an async key-value store. Five methods:
`get`, `put`, `delete`, `items`, `__init__`. Keys are arbitrary strings,
values JSON-serialize automatically. Backed by SlateDB.

**One primitive, both audiences.** The framework uses the same `KV` class for
sessions metadata, the auto-title flow, and any future state. The pitch is
literal: cycls is four primitives — Function, App, Agent, KV — and we use the
same KV you do.

```
cycls.Image   → what the container IS
cycls.Web     → how users REACH it
cycls.LLM     → what the model DOES
cycls.KV      → what the data REMEMBERS
```

---

## Workspace + substrate

```python
class Workspace:
    def __init__(self, root, user_id=None):
        self.root = Path(root)
        # Personal: .cycls/ under root.
        # Org: .cycls/{user_id}/ — members isolated in a shared mount.
        self.data = self.root / ".cycls" / user_id if user_id else self.root / ".cycls"

    def url(self) -> str: ...   # SlateDB URL prefix
```

`Workspace.url()` picks the SlateDB substrate, in this order:

1. **`CYCLS_STATE_URL` env var** — explicit override (e.g. `gs://other-bucket`).
2. **gcsfuse mount auto-detected from `/proc/mounts`** — same bucket your deploy already attached for FUSE, talked to directly via SlateDB so writes get native conditional-write semantics for writer fencing. Zero config.
3. **`file://{workspace.data}`** — local dev / no FUSE mount.

Cross-cloud portable: same shape works against S3 + Mountpoint or Azure Blob + BlobFuse2. The driver name changes; the architecture doesn't.

One SlateDB instance per tenant; KVs share the underlying handle, namespaced by `{name}/` key prefix. Pool keyed by `workspace.url()` — at heavy multi-tenant scale the pool needs LRU eviction, deferred until measured.

---

## What it kills

| Wrinkle | Before | After |
|---|---|---|
| Per-Dict file-per-name | `.cycls/{name}.json` per Dict | One SlateDB per tenant, KVs are prefix views |
| ContextVar magic | `with context.workspace():` required | Explicit `workspace` arg, no `with` block |
| Sync/async mismatch | Dict was sync, harness async | KV is async-native, composes with FastAPI |
| N+1 chat listing | `iterdir()` + read each `.json` | One `scan_prefix` returns all chats |
| Empty chat titles | FE-PUTs metadata, often skipped | Server auto-derives from first user message |
| Counter races (theoretical) | Read-modify-write JSON file | Same pattern on KV; merge ops available if/when needed |
| FUSE-only state | All state through `gcsfuse` | Direct `gs://` for state, FUSE only for user files |

---

## Examples

### Billing counter

```python
usage = cycls.KV("usage", context.workspace)
month = datetime.now(timezone.utc).strftime("%Y-%m")
entry = await usage.get(month, {"count": 0})
if user.plan == "free" and entry["count"] >= LIMIT:
    return "quota reached"
entry["count"] += 1
await usage.put(month, entry)
```

`history()` style — review past months for invoicing/dashboards:
```python
async for month, entry in usage.items():
    print(month, entry["count"])
```

### Chats (framework code, lives in `cycls/agent/web/routers.py`)

```python
chats = KV("chats", _ws(user))
items = [v async for _, v in chats.items()]   # N+1 → one scan
items.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
return items
```

### Auto-title (in the harness)

```python
chats = KV("chats", workspace)
existing = await chats.get(chat_id, {})
if not existing.get("title"):
    title = first_user_message[:80]
    await chats.put(chat_id, {**existing, "title": title, ...})
```

---

## What's still file-based (and why)

| Concern | Why it stays |
|---|---|
| User files (`/workspace/{user_id}/...`) | The agent's bwrap surface needs POSIX. FUSE/object-storage-as-filesystem is the right shape. |
| Shares (pointer + dir + assets) | Cross-tenant public read is its own concern; deferred to a follow-up. Attachments (blobs) belong on the filesystem regardless. |

---

## Forward-compat

See [rfc-002-forward-compat.md](rfc-002-forward-compat.md). The core conclusion still holds: nothing in the substrate locks future features out — share variants, billing tiers, audit logs, all build on KV without redesign.

---

## Symmetry

```
cycls.Image   → what the container IS
cycls.Web     → how users REACH it
cycls.LLM     → what the model DOES
cycls.KV      → what the data REMEMBERS
```

Same primitive both audiences. SlateDB underneath, Pythonic on top. Build features on it.

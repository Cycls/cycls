# RFC 002: cycls.Dict — The Memory Primitive

**Status**: Draft
**Depends on**: RFC 001 (shipped)
**First fold**: `cycls.Dict` (~50 lines, file-backed) — everything else falls out of it

---

## Summary

`cycls.Dict` is a named key-value store with queries. It's the fourth primitive alongside `Image` (container), `Web` (interface), and `LLM` (intelligence). Dict is memory — what the data remembers.

Internally, Cycls uses Dict to replace every filesystem-as-database hack in `state/main.py`: session index, share index, usage counters. Externally, developers use the same primitive for their own structured data — user preferences, agent memory, cached results, feature flags.

v1 is file-backed (`_index.json` on gcsfuse). When filesystem limits are hit, the backend migrates to Firestore. Same API surface, different substrate. The developer never changes their code.

---

## Why

`state/main.py` today has **15+ filesystem-as-database callsites** that all share the same anti-pattern: `json.loads(path.read_text())` for reads, `path.write_text(json.dumps(data))` for writes, `iterdir()` for listing. Each is a GCS API call via gcsfuse.

### The wrinkles Dict eliminates

| Wrinkle | Current code | After Dict |
|---|---|---|
| **Two files per session** | `{id}.history.jsonl` + `{id}.json` | Single `{id}.jsonl`, metadata lives in Dict |
| **N+1 session listing** | `iterdir()` + read each `.json` (50 sessions = 50 GCS reads) | `dict.list("sessions")` — one read |
| **FE sends full history** | Server loads from disk anyway, ignores FE's array except last message | Server owns state, FE sends `?chat=id` + new message only |
| **FE PUTs metadata** | `PUT /sessions/{id}` with title/updatedAt from the FE | Server derives title, writes Dict on each turn |
| **Share pointer files** | Global `/workspace/shared/{id}.json` → user's `public/{id}/share.json` (two reads) | `dict.set("shares", id, snapshot)` — self-contained |
| **Share N+1 listing** | `iterdir()` on public dir + read each `share.json` | `dict.list("shares")` — one read |
| **Share attachment duplication** | `shutil.copy2(src, share_dir)` — every share copies attachments | Reference by URL, no copy (separate fix) |
| **Session ID in JS state** | Lost on refresh | `?chat=` in URL, server generates ID |
| **Session deletion race** | Delete `.json` + delete `.history.jsonl` separately | Delete from Dict + delete single `.jsonl` |
| **No usage counters** | Nothing — can't enforce billing limits | `dict.increment("usage.2026-04.tokens", n)` |
| **No pagination** | All list endpoints return everything | `dict.list(limit=20, offset=cursor)` |
| **Clerk-coupled User** | `org_id`, `org_slug`, `org_role` as fields on User class | `User(id, claims)` — generic |
| **Hardcoded `/workspace`** | `Path(f"/workspace/{self.org_id}")` in five places | Volume resolver, configurable |
| **`/workspace/local` fallback** | No-auth agents share one flat dir, zero isolation | Default resolver: `/workspace/{user.id}` or `/workspace/local` — explicit |
| **`/workspace/shared` hardcoded globally** | Three separate references to `Path("/workspace/shared")` | Dict-backed global share index |

---

## The Primitive

```python
db = cycls.Dict("sessions")

await db.set(session_id, {"title": "Budget planning", "updatedAt": "..."})
await db.get(session_id)
await db.delete(session_id)
await db.list(sort_by="updatedAt", limit=20)
await db.increment(session_id, "messageCount", 1)
```

Named, lifecycle-independent, create-on-first-use. Same pattern as Image/Web/LLM — declare once, use anywhere.

### Four consumers, one implementation

```
cycls.Dict("name")
    ├── sessions    → Cycls internal: session metadata index
    ├── shares      → Cycls internal: share snapshot index
    ├── usage       → Cycls internal: per-user billing counters
    └── developer   → User-facing: whatever structured data they need
```

Cycls eats its own cooking. The same Dict developers use for their data is the same Dict that backs the session list, the share index, and the usage counters. One primitive, two audiences.

---

## Server-Owned Sessions

### Current flow (FE-driven)

```
FE sends POST /chat:
  body: { messages: [full history...], session_id: "abc" | null }
                     ↑ wasteful                   ↑ JS state, lost on refresh

Server loads history from disk anyway (ignores FE messages except last one)
FE calls PUT /sessions/{id} to save metadata (title, updatedAt)
```

### Proposed flow (server-driven, URL-based)

```
URL: https://my-agent.cycls.ai/?chat=abc123

FE sends POST /chat:
  body: { session_id: "abc123", content: "user's new message" }
                                         ↑ only the new input

Server:
  - if no session_id: generate UUID, create session in Dict
  - load history from {session_id}.jsonl
  - append user message, run loop, append response
  - update Dict: title (from first message), updatedAt, messageCount
  - first SSE event: { type: "session_id", session_id: "abc123" }

FE:
  - pushState(?chat=abc123) into URL bar
  - refresh → reads ?chat= → fetches session → conversation restored
  - "New Chat" → navigates to / (no ?chat)
```

What the FE stops doing: sending full history, tracking session ID in JS, PUTting metadata.

What the server starts doing: generating IDs, owning all state, deriving titles, maintaining Dict.

---

## Single Session File

### Current (two files)

```
.sessions/
├── abc.history.jsonl     ← messages
├── abc.json              ← metadata (written by FE)
```

### Proposed (one file, Claude Code-style)

```
sessions/
├── abc.jsonl
```

Optional `_meta` header line:

```jsonl
{"_meta": true, "title": "Budget planning", "createdAt": "...", "updatedAt": "..."}
{"role": "user", "content": "Help me plan my budget"}
{"role": "assistant", "content": [{"type": "text", "text": "..."}]}
```

- **List sessions**: reads Dict (not the file)
- **Open session**: reads the `.jsonl`, skips `_meta` lines
- **Title**: server-derived from first user message, stored in Dict and `_meta` header

The `_meta` line is a backup for index rebuilds. Dict is the authoritative index.

---

## Share Simplification

### Current (two-level indirection + attachment duplication)

```
/workspace/shared/{share_id}.json         ← global pointer
/workspace/{user}/.sessions/public/{id}/
    ├── share.json                        ← full snapshot
    └── attachment.png                    ← COPIED from workspace
```

### Proposed (self-contained + global Dict index)

```
/workspace/{user}/shared/{share_id}.json  ← self-contained snapshot

Global: Dict("shares").set(share_id, {user, title, sharedAt})
```

- Resolve a share: Dict lookup → get user + share_id → read one file
- List shares: `Dict("shares").list()`
- Attachments: URL reference to workspace file, no copy (file deletion = broken link, acceptable trade — or snapshot-on-share for critical files)

---

## Usage Tracking

Usage counters live in Dict, not in a separate system. Billing LOGIC (plan limits, tier enforcement, overage, Stripe) is a separate `cycls.billing` module that reads/writes Dict.

```python
usage = cycls.Dict("usage")

# After each agent loop turn:
month = datetime.utcnow().strftime("%Y-%m")
await usage.increment(f"{user.id}.{month}", "input_tokens", response.usage.input_tokens)
await usage.increment(f"{user.id}.{month}", "output_tokens", response.usage.output_tokens)
await usage.increment(f"{user.id}.{month}", "api_calls", 1)

# Billing check before each call:
counters = await usage.get(f"{user.id}.{month}")
if counters and counters.get("input_tokens", 0) > plan_limit:
    yield {"type": "callout", "callout": "Usage limit reached", "style": "error"}
    return
```

Dict gives billing a place to store counters. Billing gives Dict a reason to exist beyond sessions. They compose without coupling.

---

## Workspace Decoupling

### Generic User

```python
class User(BaseModel):
    id: str              # from JWT "sub" — universal
    claims: dict = {}    # raw JWT payload — provider-specific
```

Clerk-specific fields (`org_id`, `org_slug`, `org_role`, `org_permissions`, `plan`, `features`) move into `claims`. Developers read `user.claims["o"]["id"]` (Clerk) or `user.claims["org_id"]` (Auth0).

### Configurable workspace resolver

```python
volume = cycls.Volume("workspace")
# Default: /workspace/{user.id}

volume = cycls.Volume("workspace",
    resolve=lambda user: Path(f"/workspace/{user.claims['o']['id']}"))
# Clerk org isolation
```

Five hardcoded `/workspace` references in state/web/auth replaced by one configurable resolver.

---

## Directory Layout

```
/workspace/{user_identity}/
├── sessions/
│   ├── {session_id}.jsonl        ← single file: _meta header + messages
│   └── ...
├── shared/
│   └── {share_id}.json           ← self-contained share snapshot
└── files/
    └── (agent workspace: bash output, uploads, artifacts)
```

Dict-backed indexes (not on disk as files):
- `Dict("sessions")` — per-user session metadata
- `Dict("shares")` — global share index
- `Dict("usage")` — per-user/per-month billing counters

Flat session layout. Month partitioning deferred until someone hits 2000+ sessions per folder.

---

## Substrate

### v1: file-backed (`_index.json`)

```python
class Dict:
    def __init__(self, name):
        self._path = workspace / f"_{name}.json"
        self._data = json.loads(self._path.read_text()) if self._path.exists() else {}

    async def get(self, key): ...
    async def set(self, key, value): ...
    async def delete(self, key): ...
    async def list(self, sort_by=None, limit=None): ...
    async def increment(self, key, field, n): ...
```

~50 lines. File-backed. Reads/writes the whole file (fine for <10K entries). Dev mode: regular local file. Prod mode: same file on gcsfuse.

### v2: Firestore

When file-backed Dict hits limits (cross-user queries for billing, atomic increments under concurrency, >1MB index files):

```python
class Dict:
    def __init__(self, name):
        self._collection = firestore.collection(f"{account_id}/{name}")

    async def get(self, key):
        return (await self._collection.document(key).get()).to_dict()
    ...
```

Same API. Different substrate. Developer code unchanged. The migration is a backend swap inside the Dict class, gated by a feature flag or config.

---

## Shipping order (origami folds)

Each fold stands alone. Each makes the next one cheaper.

**Fold 1: `cycls.Dict` class** (~50 lines)
- File-backed, async get/set/delete/list/increment
- Importable as `cycls.Dict`
- Works locally and on gcsfuse

**Fold 2: Session index on Dict**
- `list_sessions` reads Dict instead of `iterdir()` + N reads
- `put_session` / `delete_session` update Dict
- N+1 dies. One import, few lines changed in state.py.

**Fold 3: Single session file + server-owned sessions**
- Kill separate `.json` metadata files
- Server generates session_id, derives title, owns all state
- FE sends `?chat=id` + new message only (FE change)

**Fold 4: Share index on Dict**
- Kill pointer files, self-contained share snapshots
- Global `Dict("shares")` for cross-user share lookup

**Fold 5: Usage counters on Dict**
- `dict.increment()` after each loop turn
- Billing limit checks before each API call
- Revenue-gating enabled

**Fold 6: Workspace decoupling**
- Generic `User(id, claims)`
- Configurable Volume resolver
- Strip Clerk fields

**Fold 7 (future): Firestore backend**
- When file-backed Dict hits scale limits
- Same API, swap substrate
- `cycls.Dict` becomes `cycls.Volume`'s sibling in the data primitive family

---

## What this does NOT solve

Two wrinkles that need separate treatment:

1. **Share attachment duplication** — currently `shutil.copy2` copies files into the share directory. Dict doesn't change this. Fix: reference attachments by URL instead of copying. Separate decision, orthogonal to Dict.

2. **File browser on large workspaces** — `os.scandir` on gcsfuse for the `/files` endpoint is slow for big directories. Not a Dict concern — the filesystem IS the right abstraction for files. Fix: pagination + caching on the `/files` endpoint. Separate work.

---

## Open questions

1. **Title derivation** — first user message (simple, free) vs LLM-generated summary (better UX, costs a call). Start with first message?
2. **Dict scope** — per-user only, or also global? Sessions are per-user, shares are global, usage is per-user-per-month. The Dict API needs to handle both scopes cleanly.
3. **Concurrency** — file-backed Dict does full-file read/write. Two concurrent requests writing to the same Dict race (last writer wins on gcsfuse). Acceptable for chat cadence (~1 write/30s per user). If agents do rapid parallel tool calls, batch Dict updates to end-of-turn.
4. **Dict size limit** — file-backed Dict loads the entire JSON into memory. At 10K entries (~1MB) this is fine. At 100K entries (~10MB) it's not. That's the Firestore trigger.
5. **Dev experience** — `cycls run` should auto-initialize Dict files. No emulator needed for v1 (it's just a JSON file). Firestore emulator only needed for v2.

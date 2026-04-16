# RFC 002: cycls.Dict

**Status**: Draft
**Depends on**: RFC 001 (shipped)

---

## The primitive

```python
@cycls.agent(image=image, web=web)
async def my_agent(context):
    with context.workspace():
        sessions = cycls.Dict("sessions")
        sessions[sid] = {"title": "Budget planning", "updatedAt": "..."}
        data = sessions[sid]
        for k, v in sessions.items(): ...
        del sessions[sid]
```

`cycls.Dict("name")` is a persistent dict. One argument. The scope comes from the surrounding `with` block — the dict lives in the active workspace. No context object passed, no path argument, no scope kwarg.

JSON-serialized (language-agnostic, inspectable, survives version bumps). Auto-loads on first access, auto-saves on every write.

All cycls-owned files live under `.cycls/` in the workspace — the root stays the user's surface. Every workspace owns its `.cycls/`; sessions never cross workspaces (a chat started in personal can't resume in org because its file context is gone).

**Personal workspace:**
```
/workspace/{user_id}/
├── .cycls/
│   ├── sessions.json          # cycls.Dict("sessions")
│   └── sessions/
│       └── {sid}.jsonl
└── (user files)
```

**Org workspace** (same rule — `.cycls/` at root, nested by member because the mount is shared):
```
/workspace/{org_id}/
├── .cycls/
│   └── {user_id}/             # each member's private data
│       ├── sessions.json
│       └── sessions/
│           └── {sid}.jsonl
└── (shared org files)
```

---

## Scoping

Workspace is a context manager. Everything inside the `with` block is scoped to it. Outside the block, `cycls.Dict(...)` has no scope and raises.

```python
# Per-user (developer code)
with context.workspace():
    sessions = cycls.Dict("sessions")

# Tests / scripts / migrations — explicit path
with cycls.Workspace("/tmp/test"):
    d = cycls.Dict("x")
```

Two modes, both honest. Developer handlers use `context.workspace()` — the framework constructs it from auth. Scripts and tests construct a Workspace directly with an explicit path. No hidden `cycls.system` namespace, no singleton bootstrapping. Framework code that needs the global snapshot dir reads `Path("/workspace/.cycls/shared/...")` directly — no Workspace primitive required for pure path operations.

Mechanism: `contextvars.ContextVar`. Workspace `__enter__` sets the current scope, `__exit__` restores. Dict reads the current scope in `__init__`.

---

## What it kills

| Wrinkle | Before | After |
|---|---|---|
| Two files per session | `{id}.history.jsonl` + `{id}.json` | Single `{id}.jsonl`, metadata in Dict |
| N+1 session listing | `iterdir()` + read each `.json` | One Dict file, one read |
| N+1 share listing | `iterdir()` + read each `share.json` | One Dict file, one read |
| FE sends full history *(needs FE)* | Server ignores, loads from disk | `?chat=id` + new message only |
| FE PUTs metadata *(needs FE)* | `PUT /sessions/{id}` from FE | Server derives title, writes Dict |
| Share pointer files | Global pointer → user dir → `share.json` | `dict[id] = metadata`, snapshot in one self-contained dir |
| Share location scattered | Snapshots live inside each user's `.sessions/public/` | `/workspace/.cycls/shared/{id}/` — one place, one dir per share |
| Session ID in JS state *(needs FE)* | Lost on refresh | `?chat=` in URL |
| Session deletion race | Delete `.json` + `.jsonl` separately | Dict entry + one file |
| No usage counters | Can't bill | `dict[k] = {..., "tokens": old + n}` |
| Hardcoded `/workspace` | Five references | `Image.volume(path)` |

---

## Decisions

**Scoping mechanism**: `with workspace(): ...`. ContextVar under the hood. Explicit at the block boundary, flat inside. No auto-enter magic, no per-call argument, no singleton. Missing `with` raises `RuntimeError` — not a silent fallback.

**Volume path**: declared on `cycls.Image` — same primitive that describes the container. Default `/workspace`. `Image.volume()` sets the mount path the framework uses when constructing `context.workspace()` for each request. Framework code that touches raw paths (global snapshot dir, migration walks) reads the same value from the Image at boot.

```python
image = cycls.Image().copy(".env").volume("/workspace")
```

When `cycls.Volume` becomes a real primitive, `.volume()` accepts it in place of a string — no API break.

**Title derivation**: first user message, truncated to 80 chars. LLM-generated summaries are a later upgrade.

**Concurrency**: last-writer-wins on gcsfuse. Metadata and session writes run at chat cadence (~1 write per 30s per user) — fine. Usage counters and other per-turn writes are more frequent; mitigated by end-of-turn batching, with Firestore (Fold 9) as the durable fix when volume demands it. Atomic writes (temp file + rename) prevent mid-write corruption across the board.

---

## Implementation

```python
import contextvars, copy, json
from pathlib import Path

_current_workspace = contextvars.ContextVar("cycls_workspace")


class Workspace:
    def __init__(self, root, user_id=None):
        self.root = Path(root)
        # Personal: .cycls/ directly under root. Org: .cycls/{user_id}/ so members stay isolated.
        self.data = self.root / ".cycls" / user_id if user_id else self.root / ".cycls"

    def __enter__(self):
        self._token = _current_workspace.set(self)
        self.data.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *a):
        _current_workspace.reset(self._token)


class Dict(dict):
    def __init__(self, name):
        try: ws = _current_workspace.get()
        except LookupError:
            raise RuntimeError(f"cycls.Dict({name!r}) used outside a workspace scope — wrap in `with context.workspace():`")
        self._path = ws.data / f"{name}.json"
        if self._path.exists():
            super().update(json.loads(self._path.read_text()))

    def _save(self):
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dict(self)))
        tmp.rename(self._path)

    # Returns a deep copy — in-place mutation of the returned value can't silently skip _save()
    def __getitem__(self, k):    return copy.deepcopy(super().__getitem__(k))
    def get(self, k, d=None):    return copy.deepcopy(super().get(k, d))
    def __setitem__(self, k, v): super().__setitem__(k, v); self._save()
    def __delitem__(self, k):    super().__delitem__(k);    self._save()
    def update(self, *a, **kw):  super().update(*a, **kw);  self._save()
```

~28 lines. Workspace: context manager over a Path. Dict: persistent dict that reads the active workspace. Atomic write via temp-file-and-rename. `__getitem__` and `get` return deep copies — forces read-modify-write pattern so in-place mutation of nested values can't silently skip `_save()`. Matches Modal's Dict semantics.

When file-backed hits limits (>1MB, concurrent writes, cross-user aggregation), swap to Firestore — same brackets, different persistence layer.

### Wiring `context.workspace()`

Framework captures the volume from `Image.volume()` at decoration, stores it on the Agent/App instance, passes it into every `Context` built per request. `Context.workspace()` is a method that returns a fresh Workspace:

```python
class Context:
    def workspace(self) -> Workspace:
        user, volume = self.user, self._volume
        if user.org_id:
            return Workspace(root=volume / user.org_id, user_id=user.id)
        return Workspace(root=volume / user.id)
```

`with context.workspace():` enters it; the ContextVar does the rest. Breaking change from today's `context.workspace` (Path attr) to `context.workspace()` (method returning Workspace).

---

## Shares

Shares are **frozen snapshots** by design — users expect "the chat I shared" to look the same forever, even if the original files change, get renamed, or get deleted. Copying attachments at share time is the correct semantic, kept as-is from today.

**Two pieces, decoupled:**
- **Per-workspace shares Dict** — lists the current workspace's own shares. Same per-workspace rule as sessions.
- **Global snapshot dir** — self-contained share directories, globally addressable by ID for public resolve.

No global shares.json (would hotspot every create/delete across the platform through one file).

**Layout:**
```
/workspace/
├── .cycls/
│   └── shared/
│       └── {share-id}/                   # self-contained snapshot + assets
│           ├── snapshot.json             # messages + metadata (incl. author)
│           └── assets/
│               ├── image1.png
│               └── doc.pdf
│
├── {user_id}/                            # personal workspace
│   └── .cycls/
│       └── shares.json                   # this user's shares (local Dict)
│
└── {org_id}/
    └── .cycls/
        └── {user_id}/
            └── shares.json               # member's shares, in this org
```

**Flow** (developer or framework — same shape):
```python
# Create — inside the user's active workspace
with context.workspace() as ws:
    shares = cycls.Dict("shares")
    share_id = uuid4().hex[:12]

    # Snapshot dir lives globally, not in ws.data
    share_dir = Path("/workspace/.cycls/shared") / share_id
    (share_dir / "assets").mkdir(parents=True)

    for msg in messages:
        for att in msg.get("attachments", []):
            src = ws.root / att["path"]
            if src.is_file():
                shutil.copy2(src, share_dir / "assets" / src.name)
                att["url"] = f"/shared-assets/{share_id}/{src.name}"

    (share_dir / "snapshot.json").write_text(json.dumps({
        "id": share_id, "title": title, "messages": messages,
        "author": user.id, "sharedAt": now,
    }))
    shares[share_id] = {"id": share_id, "title": title, "sharedAt": now}


# Resolve (public, no auth needed — snapshot dir IS the index)
snapshot = json.loads(Path(f"/workspace/.cycls/shared/{share_id}/snapshot.json").read_text())


# Delete — verify ownership first
snap = json.loads(Path(f"/workspace/.cycls/shared/{share_id}/snapshot.json").read_text())
if snap["author"] == user.id:
    shutil.rmtree(f"/workspace/.cycls/shared/{share_id}")
    with context.workspace():
        del cycls.Dict("shares")[share_id]
```

**What changes from today** (layout only — behavior preserved):
- **Kill the pointer indirection.** Old: `/workspace/shared/{id}.json` → points to → user's `.sessions/public/{id}/share.json`. New: snapshot dir at a known path IS the resolver.
- **Kill the scatter.** Old: snapshots buried inside each user's workspace. New: one central root at `/workspace/.cycls/shared/`.
- **Kill N+1 listing.** Per-workspace `shares.json` Dict — one read for "my shares."
- **No global shares index.** Each workspace owns its own — resolving a share by ID doesn't consult any index, deleting doesn't contend on a global file.
- **Keep the attachment copy.** Shares are snapshots; copies preserve them against later deletion/rename/edit. 2x storage for attachments-in-shared-chats is negligible.
- **Shares outlive user data.** Deleting a user's workspace leaves snapshots in `/workspace/.cycls/shared/` untouched — public URLs keep resolving.

---

## Forward-compatibility

Two audits live in [rfc-002-forward-compat.md](rfc-002-forward-compat.md): **share variants (RFC 003 scope)** and **usage & billing compatibility**. Both conclude that RFC 002's primitives don't lock the future out — every missing piece is additive.

---

## Migration

Backend scripts, not lazy-per-request. The SDK ships speaking only the new format — no dual-read code, no ongoing migration drag. Two scripts, reversible in two stages.

### Script 1 — migrate (additive, reversible)

Copies old layout into new. Does not delete anything. After this runs, both layouts coexist; new SDK reads `.cycls/`, old SDK reads `.sessions/`.

```
For each /workspace/{user_or_org_id}/:
  - Build .cycls/ (personal) or .cycls/{user_id}/ (org members)
  - Copy .history.jsonl → .cycls/sessions/{sid}.jsonl       # copy, not move
  - Write .cycls/sessions.json built from legacy .json metadata
  - Write .cycls/_migrated marker

For /workspace/shared/:
  - Build /workspace/.cycls/shares.json (the Dict index)
  - For each legacy share:
    - Create /workspace/.cycls/shared/{id}/
    - Copy share.json → /workspace/.cycls/shared/{id}/snapshot.json
    - Copy any attachments from .sessions/public/{id}/ → .cycls/shared/{id}/assets/

DO NOT TOUCH:
  - .sessions/*.json / .sessions/*.history.jsonl  (legacy)
  - .sessions/public/                              (legacy)
  - /workspace/shared/                             (legacy pointers)
```

Before Script 1: `gsutil cp -r gs://prod-workspace gs://prod-workspace-backup-YYYY-MM-DD` for the worst-case restore.

### Deploy the new SDK

New SDK reads only from `.cycls/`. Ignores `.sessions/` and `/workspace/shared/` entirely.

**Rollback path** during soak window:
1. Revert SDK deploy → old SDK reads old layout → data intact, users unaffected
2. (Optional) Delete `.cycls/` to clean up unused new-layout files

Writes made under the new SDK during soak (new sessions, usage counters) are lost if you roll back. Keep the soak short (hours to a day) so the tradeoff stays small.

### Script 2 — finalize (destructive, non-reversible)

Runs only after soak, once confidence is earned:

```
For each workspace with .cycls/_migrated:
  - Delete .sessions/
  - Delete .sessions/public/

For /workspace/:
  - Delete shared/
```

After Script 2, rollback requires restoring the bucket snapshot. This is the real point of no return — run deliberately.

### No SDK-level migration

The SDK ships speaking only the new format — no dual-read, no lazy migration, no fallback. Production is covered by the scripts above. Dev workspaces from pre-0.X installs are scratch dirs; `rm -rf` them. If a real "upgrade my local workspace" need emerges, ship a `cycls migrate <path>` CLI command then — additive, not burden on Workspace.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Shares nuke is irreversible | **High** | Announce before deploy; "this share was reset" landing page |
| Concurrent writes on `_sessions.json` | **High** | Atomic write (temp + rename); end-of-turn batching |
| Script 1 fails mid-run | **Low** | Additive only — legacy untouched, just rerun |
| New-SDK writes lost on rollback | **Low** | Short soak window; announce migration in release notes |
| FE/BE coordination (server-owned IDs, `?chat=`) | **Medium** | Ship together, feature-flag if needed |
| Missing `with` at call site | **Low** | Clear error, not silent fallback; `@cycls.agent` docs make pattern obvious |
| Dict + Workspace implementation | **Low** | ~25 lines, tested in isolation |

---

## Folds

Each stands alone. Each makes the next cheaper. Ordered by risk — **low first, irreversible last.**

1. **`cycls.Dict` + `Workspace`** *(low)* — ~25 lines, ships next to existing code. No callers yet.
2. **Plumb `Image.volume()`** *(low)* — mount path threaded from Image → Agent/App instance → `context.workspace()`. Kills the hardcoded `/workspace` references. User class stays as-is.
3. **Usage counters** *(low)* — new writes only, no migration. Exercises Dict on low-stakes data. Unlocks billing limits on Cycls Pass.
4. **Session index on Dict** *(medium)* — `list_sessions` becomes one read. Lazy migration per user. Backend-only.
5. **Single session file** *(medium)* — merge `{id}.json` + `{id}.history.jsonl` with `_meta` header. Backend-only.
6. **Server-owned sessions** *(medium)* — server generates session_id and title. FE stops PUTting metadata. Coordinated with FE.
7. **`?chat=` URL** *(medium)* — session_id in URL, FE stops sending full history. FE-driven.
8. **Share index + nuke** *(high)* — kill pointers, self-contained snapshots. Wipes existing public shares.
9. **Firestore backend** *(future)* — when file-backed hits scale limits, swap substrate. Same `cycls.Dict("name")` call; different persistence.

---

## Symmetry

```
cycls.Image   → what the container IS
cycls.Web     → how users REACH it
cycls.LLM     → what the model DOES
cycls.Dict    → what the data REMEMBERS
```

Framework and developer write `cycls.Dict("name")` identically. The only difference is which `with workspace():` block encloses the call. One grammar for both audiences — the Cycls way.

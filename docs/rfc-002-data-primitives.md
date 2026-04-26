# RFC 002: cycls.Dict

**Depends on**: RFC 001 (shipped)
**Companion**: [forward-compatibility audits](rfc-002-forward-compat.md)

---

## Status

| Phase | State | Where |
|---|---|---|
| Impl I — primitives | **Shipped** | `cycls/app/store.py:8–46`, `cycls/agent/web/main.py:126–132`, commit `e162a20` |
| Impl II — workspace plumbing | **Pending** | 5-step refactor below |
| Shares (RFC vision) | **Unshipped** | Code still uses pre-RFC pointer-and-scatter layout; design below; ships as Fold 8 |
| Folds 4–9 | **Planned** | Folds ladder below |

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

## Implementation I — primitives (shipped)

Canonical: `cycls/app/store.py`. The implementation is ~28 lines: Workspace as a context manager over a Path, Dict as a persistent dict reading the active workspace via ContextVar, atomic write via temp+rename. `__getitem__` and `get` return deep copies — forces read-modify-write so in-place mutation of nested values can't silently skip `_save()`. Matches Modal's Dict semantics.

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

    def __getitem__(self, k):    return copy.deepcopy(super().__getitem__(k))
    def get(self, k, d=None):    return copy.deepcopy(super().get(k, d))
    def __setitem__(self, k, v): super().__setitem__(k, v); self._save()
    def __delitem__(self, k):    super().__delitem__(k);    self._save()
    def update(self, *a, **kw):  super().update(*a, **kw);  self._save()
```

When file-backed hits limits (>1MB, concurrent writes, cross-user aggregation), swap to Firestore — same brackets, different persistence layer.

### Wiring `context.workspace()`

Framework captures the volume from `Image.volume()` at decoration, stores it on the Agent/App instance, passes it into every `Context` built per request. `Context.workspace()` is a method that returns a fresh Workspace (`cycls/agent/web/main.py:126`).

---

## Implementation II — workspace plumbing (pending)

**Goal:** finish the wrinkle Impl I left half-closed. After this, `Image.volume()` works end-to-end, `User` carries identity only, and every request-scoped primitive (Dict, sessions, bash cwd, editor paths) resolves from the same `with context.workspace():` block.

**Key principle:** `with context.workspace():` means *"I want persistence."* Stateless agents (no tools, no history) don't need it. Agents with tools or history fail loudly at first use with a clear error.

| # | Step | LOC |
|---|---|---|
| 1 | Harness reads `_current_workspace` *lazily* at point of use | ~15 |
| 2 | State routers derive paths from Workspace, not User | ~30 |
| 3 | Drop `User.workspace` and `User.sessions` properties | −10 |
| 4 | Lazy `mkdir` — `Workspace.__enter__` stops creating `.cycls/` eagerly | ~2 |
| 5 | Update `super.py` + tutorial: `llm.run` inside the `with` block | ~5 |

Net change: roughly zero lines, substantially cleaner boundaries.

### Step 1 — Harness lazy ContextVar reads

Today the harness reaches into `context.user.workspace` (host path for bash cwd) and `context.user.sessions` (history file path) — Clerk-shaped hardcodes on `User`.

After this step, the harness reads the active workspace from the ContextVar set by the caller's `with context.workspace():` block — **but only at the moment each tool fires or each history write happens**, never at `llm.run` entry.

```python
# Bash tool — reads workspace only when actually invoked
async def _exec_bash(...):
    try:
        cwd = _current_workspace.get().root
    except LookupError:
        raise RuntimeError("Bash tool requires a workspace scope. Wrap llm.run in `with context.workspace():`")
    # ...

# Session history save — fails gracefully if stateless
def _persist_history(...):
    try:
        ws = _current_workspace.get()
    except LookupError:
        return   # stateless agent, no persistence — silent no-op
    path = ws.data / "sessions" / f"{sid}.jsonl"
    # ...
```

**Files:** `cycls/agent/harness/tools.py` (bash + editor), `cycls/agent/harness/main.py` (history writer).

**Tests:** stateless `llm.run` works and persists nothing; tool-using `llm.run` without `with` raises `RuntimeError` at first tool call; tool-using `llm.run` inside `with` routes correctly to personal and org workspaces.

### Step 2 — State routers off User

HTTP routes (`/sessions/*`, `/files/*`, `/share/*`) don't run inside a developer handler so they can't inherit the ContextVar. Build the Workspace directly from `user` + `Config.volume` in each router via a helper:

```python
def _user_workspace(user, volume: Path) -> Workspace:
    if user.org_id:
        return Workspace(volume / user.org_id, user_id=user.id)
    return Workspace(volume / user.id)
```

Used by `Context.workspace()` and every route handler — one source of truth.

**File:** `cycls/agent/state/main.py`.

### Step 3 — Drop `User.workspace` / `User.sessions`

`cycls/app/auth.py:25–31` — remove the properties. User becomes pure identity (`id`, `org_id`, `org_slug`, `plan`, claims). Anything still reaching for `user.workspace` fails at runtime — that's the point, flush out stragglers.

**Grep gate:**
```
grep -rn "user\.workspace\|user\.sessions\|\.user\.workspace\|context\.user\.workspace" cycls/ tests/ examples/ docs/
```
Expect zero hits after Steps 1 and 2 land.

### Step 4 — Lazy `mkdir` in Workspace

`Workspace.__enter__` currently eagerly creates `.cycls/`. Stateless agents that enter a workspace conditionally pay an unnecessary fs op every request. Move the `mkdir` into `_save`:

```python
class Workspace:
    def __enter__(self):
        self._token = _current_workspace.set(self)
        return self

class Dict(dict):
    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dict(self)))
        tmp.rename(self._path)
```

Session history writer does the same (`path.parent.mkdir(...)` before write). After this, a `with` block that doesn't mutate produces zero filesystem writes.

### Step 5 — Examples + tutorial

`examples/agent/super.py` — indent `async for msg in llm.run(...)` inside the existing `with context.workspace():`. One line.

`docs/tutorial.md` — show two canonical shapes side by side:

```python
# Stateless — no `with` needed.
@cycls.agent(image=image, web=web)
async def simple(context):
    async for msg in llm.run(context=context):
        yield msg

# Persistent / tool-using — wrap to opt in.
@cycls.agent(image=image, web=web)
async def persistent(context):
    with context.workspace():
        async for msg in llm.run(context=context):
            yield msg
```

One sentence: *"`with context.workspace():` means 'I want persistence.' If you save Dicts, use Bash/Editor tools, or want session history, wrap your handler body. Stateless agents skip it."*

### Shipping order

1. **PR 1** — Steps 1+2+3 in one change. Audited together; grep verifies zero stragglers before merge.
2. **PR 2** — Step 4: lazy mkdir.
3. **PR 3** — Step 5: tutorial + super.py.

**Total engineering:** half a day to a full day, most of it on the router audit in Step 2.

---

## Shares (unshipped vision — Fold 8)

Shares are **frozen snapshots** by design — users expect "the chat I shared" to look the same forever, even if the original files change, get renamed, or get deleted. Copying attachments at share time is the correct semantic, kept as-is from today.

> Status: code currently uses the pre-RFC layout (`/workspace/shared/{id}.json` pointers → user `.sessions/public/{id}/share.json`). The migration to the layout below ships as **Fold 8** with a brief soak window — see Risks.

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

## Folds

Each stands alone. Each makes the next cheaper. Ordered by risk — **low first, irreversible last.**

| # | Fold | Status |
|---|---|---|
| 1 | `cycls.Dict` + `Workspace` | **Shipped** (Impl I) |
| 2 | Plumb `Image.volume()` | **Shipped** (Impl I); finalized by Impl II Steps 1–3 |
| 3 | Usage counters | **Shipped** (month-keyed usage Dict, commit `e162a20`) |
| 4 | Session index on Dict — `list_sessions` becomes one read; lazy migration per user | Planned |
| 5 | Single session file — merge `{id}.json` + `{id}.history.jsonl` with `_meta` header | Planned |
| 6 | Server-owned sessions — server generates session_id and title; FE stops PUTting metadata | Planned (FE coord) |
| 7 | `?chat=` URL — session_id in URL, FE stops sending full history | Planned (FE-driven) |
| 8 | Share index + nuke — kill pointers, self-contained snapshots; wipes existing public shares | Planned |
| 9 | Firestore backend — when file-backed hits scale limits, swap substrate; same `cycls.Dict("name")` call | Future |

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Shares nuke is irreversible (Fold 8) | **High** | Announce before deploy; "this share was reset" landing page |
| Concurrent writes on `_sessions.json` | **High** | Atomic write (temp + rename); end-of-turn batching; Firestore at Fold 9 |
| FE/BE coordination (server-owned IDs, `?chat=`) | **Medium** | Ship together, feature-flag if needed |
| Tool-using agent without `with` block (post Impl II) | **Medium** | Lazy reads raise `RuntimeError` at first tool invocation with a clear fix message |
| Missed `user.workspace` / `user.sessions` callsite (Impl II) | **Medium** | Single grep gate; properties removed so runtime catches what grep misses |
| Pre-Impl-II developer agents | **Low** | One-line indent: move `llm.run` inside `with`. Tutorial shows both shapes. |
| ContextVar across spawned subprocess | **Low** | Bash tool reads cwd just before spawn; ContextVar resolved on the calling task |

---

## Symmetry

```
cycls.Image   → what the container IS
cycls.Web     → how users REACH it
cycls.LLM     → what the model DOES
cycls.Dict    → what the data REMEMBERS
```

Framework and developer write `cycls.Dict("name")` identically. The only difference is which `with workspace():` block encloses the call. One grammar for both audiences — the Cycls way.

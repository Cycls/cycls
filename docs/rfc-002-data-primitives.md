# RFC 002: cycls.Dict

**Status**: Draft
**Depends on**: RFC 001 (shipped)

---

## The primitive

```python
sessions = cycls.Dict("sessions")

# Python dict — brackets, operators, iteration
sessions[session_id] = {"title": "Budget planning", "updatedAt": "..."}
data = sessions[session_id]
del sessions[session_id]
"abc123" in sessions
len(sessions)
for key in sessions: ...
sessions.update({k1: v1, k2: v2})
sessions.pop(key)
sessions.keys(), sessions.values(), sessions.items()
sessions.clear()

# Two additions Python dicts can't express
sessions.list(sort_by="updatedAt", limit=20)
sessions.increment(session_id, "messageCount", 1)
```

Dict subclass. Named. Persistent. ~50 lines. Same gene as Image (dict subclass, ~25 lines). JSON-serialized (not cloudpickle — language-agnostic, inspectable, survives version bumps).

Scoping via context — same pattern as `llm.run(context=context)`:

```python
sessions = cycls.Dict("sessions", context)   # per-user → context.workspace/_sessions.json
shares = cycls.Dict("shares")                # global → $CYCLS_DATA_DIR/_shares.json
```

With context: per-user, file in the user's workspace. Without: global. Auto-loads on first access, auto-saves on every write. Developer never sees a path.

---

## What it kills

| Wrinkle | Before | After |
|---|---|---|
| Two files per session | `{id}.history.jsonl` + `{id}.json` | Single `{id}.jsonl`, metadata in Dict |
| N+1 session listing | `iterdir()` + read each `.json` | `dict.list()` — one read |
| N+1 share listing | `iterdir()` + read each `share.json` | `dict.list()` — one read |
| FE sends full history | Server ignores it, loads from disk | `?chat=id` + new message only |
| FE PUTs metadata | `PUT /sessions/{id}` from FE | Server derives title, writes Dict |
| Share pointer files | Global pointer → user dir → `share.json` | `dict.set(id, snapshot)` |
| Share attachment copies | `shutil.copy2` duplicates files | URL reference, no copy |
| Session ID in JS state | Lost on refresh | `?chat=` in URL |
| Session deletion race | Delete `.json` + `.history.jsonl` separately | Dict entry + one file |
| No usage counters | Can't bill | `dict.increment("tokens", n)` |
| No pagination | All endpoints return everything | `dict.list(limit=, offset=)` |
| Clerk-coupled User | `org_id`, `org_slug` as fields | `User(id, claims)` |
| Hardcoded `/workspace` | Five references | Volume resolver |
| `/workspace/local` fallback | No-auth agents share one dir | Explicit default |

---

## Decisions

**Title derivation**: first user message, truncated to 80 chars. Free, instant, good enough. LLM-generated summaries are a future upgrade, not v1.

**Scoping**: pass `context` for per-user, omit for global. Same pattern as `llm.run(context=context)`. Per-user files live in the user's workspace. Global files live at `$CYCLS_DATA_DIR`.

**Concurrency**: last-writer-wins on gcsfuse. Fine for chat cadence (~1 write per 30s per user). Batch writes to end-of-turn for rapid tool calls.

---

## Implementation

```python
class Dict(dict):
    def __init__(self, name, context=None):
        if context and hasattr(context, 'workspace'):
            root = context.workspace
        else:
            root = Path(os.environ.get("CYCLS_DATA_DIR", "/workspace"))
        self._path = root / f"_{name}.json"
        if self._path.exists():
            super().update(json.loads(self._path.read_text()))

    def _save(self):
        self._path.write_text(json.dumps(dict(self)))

    # Every mutation goes through here → guaranteed persistence
    def __setitem__(self, k, v):     super().__setitem__(k, v);   self._save()
    def __delitem__(self, k):        super().__delitem__(k);      self._save()
    def update(self, *a, **kw):      super().update(*a, **kw);    self._save()
    def pop(self, *a, **kw):         v = super().pop(*a, **kw);   self._save(); return v
    def popitem(self):               kv = super().popitem();      self._save(); return kv
    def clear(self):                 super().clear();             self._save()
    def setdefault(self, k, d=None): v = super().setdefault(k, d); self._save(); return v

    def list(self, sort_by=None, limit=None):
        """Return (key, value) pairs, optionally sorted/limited."""
        items = list(self.items())
        if sort_by:
            items.sort(key=lambda kv: kv[1].get(sort_by) if isinstance(kv[1], dict) else kv[1],
                       reverse=True)
        return items[:limit] if limit else items

    def increment(self, key, field, n=1):
        entry = dict(self.get(key, {}))
        entry[field] = entry.get(field, 0) + n
        self[key] = entry
```

Dict subclass. ~40 lines. Sync. Every mutation persists — no inherited dict method silently skips the save. `list()` returns `(key, value)` pairs, not just values — keys stay meaningful.

When file-backed hits limits (>1MB, concurrent writes, cross-user aggregation), swap to Firestore. Same brackets, same `list`/`increment` — different persistence layer.

---

## Shares

Same Dict-as-index pattern as sessions. Dict holds metadata, files hold content.

```python
shares = cycls.Dict("shares")  # global, no context — shares are public

# Create
share_id = uuid4().hex[:12]
snapshot = {"id": share_id, "title": title, "messages": messages,
            "author": author, "sharedAt": now}
Path(f"/workspace/_shared/{share_id}.json").write_text(json.dumps(snapshot))
shares[share_id] = {"id": share_id, "user": user.id, "title": title, "sharedAt": now}

# List (for the sharing user)
user_shares = [v for v in shares.list(sort_by="sharedAt") if v["user"] == user.id]

# Resolve (public, no auth)
meta = shares[share_id]
snapshot = json.loads(Path(f"/workspace/_shared/{share_id}.json").read_text())

# Delete
del shares[share_id]
Path(f"/workspace/_shared/{share_id}.json").unlink()
```

**What changes from today:**
- Kill the pointer indirection (`/workspace/shared/{id}.json` → user's `public/{id}/share.json`). One global dir, one global index.
- Kill attachment duplication (`shutil.copy2`). Reference originals by URL. Broken if user deletes the file — acceptable.
- Kill N+1 listing. `shares.list()` reads the index.
- Snapshots live at `/workspace/_shared/`, not inside any user's workspace. Shares survive independent of user data.

---

## Folds

Each stands alone. Each makes the next cheaper.

1. **`cycls.Dict` class** — dict subclass, sync, ~40 lines
2. **Session index on Dict** — `list_sessions` becomes `dict.list()`. N+1 dies. Backend-only.
3. **Single session file** — merge `{id}.json` + `{id}.history.jsonl` into one `{id}.jsonl` with `_meta` header. Backend-only; existing FE keeps working.
4. **Server-owned sessions** — server generates session_id and derives title. FE can stop PUTting metadata. Coordinated with FE.
5. **`?chat=` URL** — FE moves session_id into the URL, stops sending full history. FE-driven.
6. **Share index on Dict** — kill pointer files, self-contained snapshots.
7. **Usage counters on Dict** — `dict.increment()` per turn, billing limits enabled.
8. **Workspace decoupling** — `User(id, claims)`, configurable resolver.
9. **Firestore backend** — when file-backed hits scale limits, swap substrate.

---

## Symmetry

```
cycls.Image   → what the container IS
cycls.Web     → how users REACH it
cycls.LLM     → what the model DOES
cycls.Dict    → what the data REMEMBERS
```

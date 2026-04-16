# RFC 002: cycls.Dict

**Status**: Draft
**Depends on**: RFC 001 (shipped)

---

## The primitive

```python
db = cycls.Dict("sessions")

await db.set(key, value)
await db.get(key)
await db.delete(key)
await db.list(sort_by="updatedAt", limit=20)
await db.increment(key, "field", n)
```

~50 lines. File-backed v1 (`_index.json` on gcsfuse). Firestore v2 (same API, swap substrate).

Per-user Dicts are scoped by workspace path. Global Dicts (shares) live at the workspace root.

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

**Per-user vs global scope**: Dict constructor takes an optional `scope` — `"user"` (default, scoped to workspace path) or `"global"` (workspace root). Sessions and usage are per-user. Shares are global.

**Concurrency**: last-writer-wins on gcsfuse. Fine for chat cadence (~1 write per 30s per user). Dict updates batch to end-of-turn for rapid tool calls.

---

## Folds

Each stands alone. Each makes the next cheaper.

1. **`cycls.Dict` class** — file-backed, async, ~50 lines
2. **Session index on Dict** — `list_sessions` becomes `dict.list()`. N+1 dies.
3. **Single session file + server-owned sessions** — kill `.json` metadata files, `?chat=` URL, FE sends only new message
4. **Share index on Dict** — kill pointer files, self-contained snapshots
5. **Usage counters on Dict** — `dict.increment()` per turn, billing limits enabled
6. **Workspace decoupling** — `User(id, claims)`, configurable Volume resolver
7. **Firestore backend** — when file-backed hits scale limits, swap substrate

---

## Symmetry

```
cycls.Image   → what the container IS
cycls.Web     → how users REACH it
cycls.LLM     → what the model DOES
cycls.Dict    → what the data REMEMBERS
```

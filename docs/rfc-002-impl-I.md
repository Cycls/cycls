# RFC 002: Implementation I — Stop the Revenue Bleed

**Goal:** ship the minimum slice of [RFC 002](rfc-002-data-primitives.md) that lets the agent refuse service to free-plan orgs (b2b) and quota-limit free-plan users (b2c). Everything shipped here is final RFC 002 API — no rework when later folds land.

---

## Scope

Folds 1 + 2 from RFC 002, plus a developer-side guard pattern (no SDK code).

| Step | What ships | Lines |
|---|---|---|
| 1 | `cycls.Dict` + `cycls.Workspace` (Fold 1) | ~25 |
| 2 | `Image.volume()` plumbing + `Context.workspace()` method (Fold 2) | ~10 |
| 3 | `.cycls/` sandbox + editor guard (read-only) | ~6 |
| 4 | Guard pattern in agent body (developer code) | ~8 |

**Out of scope** (deferred to later folds): session index, single session file, FE coordination (`?chat=`, server-owned sessions), share index + nuke, Firestore, audit log, per-org aggregate usage.

---

## Step 1 — `cycls.Dict` + `cycls.Workspace`

**New file**: `cycls/data.py` (or similar) containing both classes exactly as specified in RFC 002 Implementation section.

**Export** from `cycls/__init__.py`:
```python
from cycls.data import Dict, Workspace
```

**Tests** (`tests/data_test.py`):
- Dict persists across `with` blocks (write, reopen, read)
- Dict raises `RuntimeError` when used outside a workspace scope
- Atomic write via temp+rename (crash mid-write leaves no corrupted file)
- Workspace `user_id` kwarg produces `.cycls/{user_id}/` nesting
- ContextVar isolation: nested `with` blocks restore the outer scope on exit

**No callers yet.** Ships alongside existing code. Zero production risk.

---

## Step 2 — Plumb `Image.volume()` + `Context.workspace()`

Wire the primitive into the framework so `with context.workspace():` works in handlers.

**Files to touch:**

1. **`cycls/function/image.py`** — add `.volume(path)` method on `Image`:
   ```python
   def volume(self, path):
       return self._with(volume=path)
   ```

2. **`cycls/agent/main.py`** (and `cycls/function/main.py` / `cycls/app/main.py` as needed) — read `image.get("volume", "/workspace")` in `__init__`, store as `self._volume = Path(...)`. Pass into `Context` at request construction.

3. **Context class** (wherever it lives — `cycls/agent/web/main.py` likely) — add method:
   ```python
   def workspace(self) -> Workspace:
       user, volume = self.user, self._volume
       if user.org_id:
           return Workspace(root=volume / user.org_id, user_id=user.id)
       return Workspace(root=volume / user.id)
   ```

**Breaking change:** `context.workspace` (today a `Path` property) becomes `context.workspace()` (a method returning `Workspace`). Audit:
- `examples/agent/super.py` — likely unaffected (doesn't use context.workspace directly)
- `examples/agent/claude-agent.py` — uses `user_workspace = f"/workspace/{user_id}"` directly, not affected
- Tutorial docs mentioning `context.workspace` — update to show the method form
- Tests that assert `context.workspace` is a Path — update

**Tests**: request fires → handler gets Context → `context.workspace()` returns correct Workspace for personal + org cases.

---

## Step 3 — Guard `.cycls/` from user tools

Billing gates are meaningless if the user can run `echo '{}' > .cycls/usage.json` in the Bash tool. Close the exploit at two layers: the sandbox bind and the path resolver.

**1. bwrap read-only bind** in `cycls/agent/harness/tools.py`. After the main `--bind cwd /workspace`, add:
```python
"--ro-bind", str(cwd / ".cycls"), "/workspace/.cycls",
```
User's bash can read `.cycls/` (useful for "show me my usage" prompts, session recall) but any write or delete fails.

**2. Reserved-path check** in `cycls/agent/state/main.py`. Extend `resolve_path` to refuse paths inside `.cycls/`:
```python
def ensure_not_reserved(workspace: Path, resolved: Path) -> None:
    reserved = (workspace / ".cycls").resolve()
    if resolved == reserved or resolved.is_relative_to(reserved):
        raise ValueError("Reserved path: .cycls/ is managed by cycls")
```

Called inside `resolve_path` — covers the Editor tool and every `/files/{path}` HTTP endpoint (PUT, PATCH, DELETE, mkdir). Agent developers can still reference `.cycls/` through `cycls.Dict` (the legit way); raw filesystem access is denied.

**Tests**:
- Bash sandbox can read `.cycls/usage.json` but can't write or delete it
- Editor tool rejects paths inside `.cycls/` with a clear error
- `PUT /files/.cycls/usage.json` returns 403
- `cycls.Dict("usage")` inside a handler still works

~6 lines of new code, two files touched. Ships in the same PR as Step 2 (both touch adjacent code).

---

## Step 4 — Guard pattern in agent body

No SDK changes. Copy-paste into the user's agent file. Publish as a recipe in the tutorial.

```python
from datetime import datetime, timezone

FREE_MONTHLY_LIMIT = 10   # product call: messages, or tokens, or requests

@cycls.agent(image=image, web=web)
async def my_agent(context):
    user = context.user

    # b2b: free orgs blocked (no compute, no tracking)
    if user.plan == "o:free_org":
        yield {"type": "callout",
               "callout": "This workspace needs a paid plan.",
               "style": "error"}
        return

    # Track usage for every non-blocked user; gate free users on monthly quota.
    # Keys are months — history accumulates, no data loss across month boundaries.
    with context.workspace():
        usage = cycls.Dict("usage")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        entry = usage.get(month, {"count": 0})

        if user.plan == "u:free_user" and entry["count"] >= FREE_MONTHLY_LIMIT:
            yield {"type": "callout",
                   "callout": f"Free tier limit reached ({FREE_MONTHLY_LIMIT}/mo). Upgrade for unlimited.",
                   "style": "warning"}
            return

        entry["count"] += 1
        usage[month] = entry

    async for msg in llm.run(context=context):
        yield msg
```

Sharing this pattern in the tutorial makes it the canonical "how to gate free plans" recipe.

---

## Shipping order

1. PR 1: `cycls.Dict` + `cycls.Workspace` with tests. Zero-risk, no callers.
2. PR 2: `Image.volume()` + `Context.workspace()` wiring **+ `.cycls/` sandbox guard + reserved-path check**. Breaking change for the `context.workspace` attr users; audit and update examples/tutorial in the same PR.
3. Deploy new SDK version.
4. Update Cycls's own agent file with the guard pattern. Deploy.
5. Publish the recipe in the tutorial.

**Total engineering:** one to two days, most of it on Step 2's audit.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Dropped increments under concurrent writes | Low for "refuse at N" semantics | Accept; Fold 9 (Firestore) fixes it when accurate billing matters |
| `context.workspace()` breaking change misses a call site | Medium | grep for `context.workspace` in examples, tests, docs before PR 2 merges |
| gcsfuse `rename()` atomicity | Low | Standard temp+rename pattern; verify in a scratch deploy |
| User bypasses quota via Bash/Editor writing to `.cycls/` | **High** without Step 3 | Step 3 ro-binds `.cycls/` in bwrap and blocks writes in `resolve_path` |
| Developers forget the `with` block | Low | `RuntimeError` at Dict construction makes the mistake loud |

---

## Forward-compat guarantees

Everything shipped here is **final RFC 002 API**:

- `cycls.Dict("name")` call shape — never changes
- `with context.workspace():` — never changes
- `Image.volume(path)` — when `cycls.Volume` becomes a real primitive, `.volume()` accepts it without API break
- The guard pattern works identically when Firestore lands in Fold 9 — only the persistence layer swaps

No deprecation, no rework. Implementation I is a proper subset of the RFC.

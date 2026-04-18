# RFC 002: Implementation II — Close out workspace plumbing

**Goal:** finish the wrinkle Impl I left half-closed. After this, `Image.volume()` works end-to-end, `User` carries identity only, and every request-scoped primitive (Dict, sessions, bash cwd, editor paths) resolves from the same `with context.workspace():` block.

Everything shipped here is final RFC 002 API. No developer migration — the only developer-facing change is moving `llm.run(...)` inside the `with` block.

---

## Scope

| Step | What changes | Lines |
|---|---|---|
| 1 | Harness reads `_current_workspace` *lazily* at point of use | ~15 |
| 2 | State routers derive paths from Workspace, not User | ~30 |
| 3 | Drop `User.workspace` and `User.sessions` properties | -10 |
| 4 | Lazy `mkdir` — `Workspace.__enter__` stops creating `.cycls/` eagerly | ~2 |
| 5 | Update `super.py` + tutorial: `llm.run` inside the `with` block | ~5 |

Net change: roughly zero lines of code, substantially cleaner boundaries.

**Key principle:** `with context.workspace():` means *"I want persistence."* Stateless agents (no tools, no history) don't need it. Agents with tools or history fail loudly at first use with a clear error.

---

## Step 1 — Harness refactor (lazy ContextVar reads)

The harness receives `context`, runs the LLM loop, dispatches tools. Today it reaches into `context.user.workspace` (host path for bash cwd) and `context.user.sessions` (history file path). Both are Clerk-shaped hardcodes on `User`.

After this step, the harness reads the active workspace from the ContextVar set by the caller's `with context.workspace():` block — **but only at the moment each tool fires or each history write happens**, never at `llm.run` entry.

**Lazy pattern:**

```python
# Bash tool — reads workspace only when actually invoked
async def _exec_bash(...):
    try:
        cwd = _current_workspace.get().root
    except LookupError:
        raise RuntimeError(
            "Bash tool requires a workspace scope. "
            "Wrap llm.run in `with context.workspace():`"
        )
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

**Why lazy matters:**
- **Stateless agents** (no tools, no history) never read the ContextVar → never need `with`.
- **Agents with tools** fail loudly at the first tool call if `with` is missing — clear error, clear fix.
- **Persistent agents** wrap normally → everything works.

**Files to touch:**

- `cycls/agent/harness/tools.py` — `_exec_bash` and Editor dispatcher read `_current_workspace.get().root` at invocation time, not as a parameter from `user.workspace`.
- `cycls/agent/harness/main.py` — session history writer tries `_current_workspace.get()`; on `LookupError`, skips persistence.

**Tests:**
- Stateless agent (`llm.run` with no tools, no with block) works, yields responses, persists nothing.
- `llm.run` with bash tool but no `with` block → `RuntimeError` at first bash invocation with a clear fix message.
- `llm.run` inside `with cycls.Workspace(tmp):` → bash cwd is `tmp`, history lands at `tmp/.cycls/sessions/{sid}.jsonl`.
- Personal and org workspace both route correctly.

---

## Step 2 — State routers refactor

HTTP routes (`/sessions/*`, `/files/*`, `/share/*`) currently derive paths from `user.workspace` and `user.sessions`. They don't run inside a developer handler, so they can't inherit the ContextVar. Build the Workspace directly from user + Config.volume in each router.

**Files to touch:**

- `cycls/agent/state/main.py` — all three router factories take a `volume: Path` param (already available at mount time from `Config.volume`). Replace `user.workspace` with `Workspace(volume/user.org_id, user_id=user.id).root` (or the personal branch), same for `user.sessions`.

Cleaner: extract a helper:
```python
def _user_workspace(user, volume: Path) -> Workspace:
    if user.org_id:
        return Workspace(volume / user.org_id, user_id=user.id)
    return Workspace(volume / user.id)
```
Used by `Context.workspace()` and by every route handler — one source of truth.

**Tests:**
- Existing state router tests keep passing (same paths, different plumbing)
- `PUT /files/foo.txt` lands at `{volume}/{user_id}/foo.txt`, not hardcoded `/workspace/{user_id}/foo.txt`
- With `Image.volume("/data")`, state files appear under `/data/...`

---

## Step 3 — Drop `User.workspace` and `User.sessions`

`cycls/app/auth.py` lines 25–31. Remove the properties entirely. User is now pure identity: `id`, `org_id`, `org_slug`, `plan`, claims.

Anything still reaching for `user.workspace` or `user.sessions` fails at import/runtime. That's the point — flush out stragglers.

**Grep to run before merging:**
```
grep -rn "user\.workspace\|user\.sessions\|\.user\.workspace\|context\.user\.workspace" cycls/ tests/ examples/ docs/
```
Expect zero hits after Steps 1 and 2 land.

---

## Step 4 — Lazy `mkdir` in Workspace

Currently `Workspace.__enter__` eagerly creates `.cycls/`. Stateless agents that enter a workspace (e.g., to call `cycls.Dict` conditionally) but never write pay an unnecessary fs op on every request.

**Move the `mkdir` into `_save`:**

```python
# cycls/app/store.py

class Workspace:
    def __enter__(self):
        self._token = _current_workspace.set(self)
        # no mkdir here — lazy on first write
        return self

class Dict(dict):
    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)   # lazy
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dict(self)))
        tmp.rename(self._path)
```

Session history writer does the same (`path.parent.mkdir(...)` before write).

After this, a `with` block that doesn't mutate anything produces zero filesystem writes — exactly what a stateless agent should cost.

---

## Step 5 — Update examples and tutorial

**`examples/agent/super.py`** — indent `async for msg in llm.run(context=context):` one level deeper so it sits inside the existing `with context.workspace():` block. That's the whole change.

```python
with context.workspace():
    usage = cycls.Dict("usage")
    # ... quota gate ...
    entry["count"] += 1
    usage[month] = entry

    async for msg in llm.run(context=context):   # ← now inside the with
        yield msg
```

**`docs/tutorial.md`** — show two canonical shapes side by side:

```python
# Stateless agent — no persistence, no tools. No `with` needed.
@cycls.agent(image=image, web=web)
async def simple(context):
    async for msg in llm.run(context=context):
        yield msg

# Persistent / tool-using agent — wrap to opt in.
@cycls.agent(image=image, web=web)
async def persistent(context):
    with context.workspace():
        async for msg in llm.run(context=context):
            yield msg
```

One sentence explaining: *"`with context.workspace():` means 'I want persistence.' If you save Dicts, use Bash/Editor tools, or want session history, wrap your handler body. Stateless agents skip it."*

---

## Shipping order

1. **PR 1** — Steps 1 + 2 + 3 in one change. Small enough to audit together, big enough to not leave the codebase in a mixed state. grep verifies zero stragglers before merge.
2. **PR 2** — Step 4: tutorial + super.py update. Separate so the SDK change can ship before docs if needed.
3. Deploy the new SDK version.

**Total engineering:** half a day to a full day, most of it on the router audit in Step 2.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Agent with tools but no `with` block | Medium | Lazy reads raise `RuntimeError` at first tool invocation with a clear fix message |
| Stateless agent silently loses history | Low | By design — `with` is opt-in. Tutorial shows both shapes side by side. |
| Missed `user.workspace` / `user.sessions` callsite | Medium | Single grep command in Step 3's gate; properties removed so runtime catches what grep misses |
| ContextVar doesn't propagate into a spawned subprocess | Low | Bash tool already reads cwd as a param at spawn time; we read `_current_workspace.get().root` just before the call |
| Breaking change for developers running pre-II agents | Low | Move `llm.run` inside `with` — one-line indent. Tutorial update covers it. |

---

## Forward-compat guarantees

- **`with context.workspace():`** — still the one scoping primitive. After Impl II, it scopes *everything* request-bound, not just Dict.
- **`cycls.Dict("name")`** — unchanged.
- **`Image.volume(path)`** — now actually works for all paths, not just Dict. No API change.
- **`User` class** — shrinks but doesn't gain anything. Anyone reading claims off `user.plan`, `user.org_id` keeps working.

No deprecation, no rework. Impl II is Impl I's other half — they ship together to form the complete Fold 1 + Fold 2 experience.

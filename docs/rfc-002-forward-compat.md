# RFC 002: Forward-Compatibility Audits

**Companion to**: [RFC 002 — cycls.Dict](rfc-002-data-primitives.md)

This doc keeps RFC 002's core reading tight. It captures two forward-compat analyses that confirm the primitives don't paint us into a corner: **share variants (RFC 003)** and **usage & billing**.

---

## Share variants (RFC 003 scope)

RFC 002 handles one share type: **public chat with frozen snapshot + asset copy**. Other share variants are real features but out of scope — they need a `cycls.Share` primitive with axes for scope, copy mode, and payload shape. Explicit deferrals so nothing's forgotten:

| Variant | Why deferred |
|---|---|
| **Org-private chat shares** | Needs org-aware auth scoping; no-copy optimization (org already has files) |
| **Public file/asset shares** | Different payload shape (file, not chat); needs a URL structure for raw files |
| **Org-private file links** | Auth-scoped single-file references, not frozen copies |
| **Public forkables** (clone a whole chat + workspace dir) | Needs a fork op that copies messages + workspace subtree into the forker's workspace; bigger than sharing |

Shape hint for RFC 003: `cycls.Share(kind="chat"|"file"|"fork", scope="public"|"org", copy="frozen"|"reference")`. One primitive, three axes, each existing variant is a concrete configuration.

### Does RFC 002 make RFC 003 easier or harder?

Audited each deferred feature against the primitives committed in RFC 002:

| RFC 003 feature | What it'll need | RFC 002 makes it... |
|---|---|---|
| Org-private chat | Skip copy, snapshot lives in org workspace, auth-scoped route | **Easier** — per-workspace Dict is already per-user; snapshot at `/workspace/{org_id}/.cycls/shared/{id}/` is a sibling of public |
| Public file/asset share | New Dict (`file_shares`) + route serving a single file | **Easier** — `cycls.Dict("file_shares")` is one line; route is a path read |
| Org-private file links | Same as above + auth-check | **Easier** — reuse auth middleware; same Dict shape |
| Public forkables | Read public snapshot, write to forker's sessions Dict, copy workspace subtree into forker's `ws.root` | **Easier** — snapshot dir globally addressable; sessions Dict is a one-liner; `ws.root` vs `ws.data` split already separates user files from framework state |

**What RFC 002 specifically sets up that pays off:**

- `cycls.Dict("anything")` — every future "list my X" is one line
- Global `/workspace/.cycls/shared/{id}/` pattern — generalizes to `.cycls/files/{id}/`, `.cycls/forks/{id}/` with the same route-handler shape
- Per-workspace Dict rule — any per-user primitive scales without a global-index hotspot
- `ws.root` vs `ws.data` split — fork copying user files never collides with framework state
- ContextVar scoping — new primitives pick up the active workspace automatically
- No global indexes committed — every share type gets its own per-workspace Dict, no contention

**What we deliberately avoided** that would have made RFC 003 harder:

- A single global shares.json (bottleneck)
- Dict coupled to share semantics (would block other share kinds)
- `.cycls/` nested under `.sessions/` (would trap non-chat primitives)
- Dict taking a context object (would tangle every future primitive with User/Auth)

**One mild concern:** `.cycls/shared/` assumes one concept of "shared." When forks and file shares arrive, we'll want siblings (`.cycls/shared_chats/`, `.cycls/forks/`, `.cycls/files/`). Cheap rename, not a blocker.

**Verdict:** RFC 002's minimalism is the feature — nothing committed there needs undoing for RFC 003.

---

## Usage & billing compatibility

Cycls Pass and future billing tiers need per-user/org counters, quota enforcement, and eventually audit-grade accounting. Audit of how far RFC 002 gets us:

| Billing concern | RFC 002 makes it... |
|---|---|
| Per-user counters (tokens, calls, tool invocations) | **Easier** — `cycls.Dict("usage")` per workspace is literally Fold 3 |
| Plan tiers (free / pass / pro) | **Neutral** — static config on `user.plan`, not data-layer |
| Per-user budgets / overrides | **Easier** — `cycls.Dict("budgets")`, same shape as usage |
| Quota check-before-act | **Easier** — one Dict read, O(1); cache per request |
| Monthly resets | **Easier** — Dict value carries `{"month": "2026-04", "tokens": N}`; flip on month change |
| Multi-provider cost split | **Easier** — nested JSON values in Dict |
| Org-level aggregation | **Neutral** — per-user Dicts don't aggregate; add a sibling `/workspace/{org_id}/.cycls/usage.json` updated in parallel |
| High-frequency writes (tool-heavy turns) | **Harder than ideal** — gcsfuse last-writer-wins can drop increments; end-of-turn batching mitigates; real fix is Firestore (Fold 9) |
| Atomic reservations (hard limits) | **Not sufficient** — file-backed can't give atomic compare-and-swap; needs Firestore |
| Audit trail (disputes, invoices) | **Not covered** — Dict overwrites; needs a sibling `events.jsonl` or a future `cycls.Log` primitive |
| Platform-wide reporting | **Neutral** — iterdir workspaces; admin op, acceptable |

**What RFC 002 gives for free:** per-user counter storage, per-workspace scoping that naturally splits personal and org-member usage, O(1) quota checks, and Fold 3 already planned.

**What needs to be added later (all additive, none block on RFC 002):**
- **Per-org aggregate Dict** — so org-wide quotas don't require iteration. Sibling `.cycls/usage.json` at org workspace root, double-written on each charge.
- **Event log alongside Dict** — append-only JSONL for audit. Future `cycls.Log("charges")` primitive, same gene as Dict, different semantics.
- **Firestore backend** (Fold 9) — for real money, file-backed atomicity isn't enough. Same `cycls.Dict(...)` call shape, transactional substrate.

**Sequence:**
1. Fold 3 — usage counters, soft limits. Unblocks Cycls Pass monetization.
2. Add `cycls.Log` primitive when audit trail becomes a product requirement.
3. Fold 9 — Firestore when concurrency losses become real (money at stake, high-frequency tool calls).

**Verdict:** RFC 002 is a good-enough foundation for usage tracking and soft-limit enforcement now, and the right substrate to swap under when billing becomes money-critical. Doesn't close the billing loop alone, doesn't block it either.

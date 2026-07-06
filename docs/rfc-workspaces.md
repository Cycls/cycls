# RFC — Multi-workspace orgs (personal + team folders)

Status: **accepted — Phases 1–2 implemented** (ws dimension in `workspace()`, personal workspaces behind `Web().workspaces(...)`, `X-Workspace` header, `.org/` registry + ACL, team workspaces with the `/workspaces` + members API, org-admin lifecycle-only on personal; Phase 3 — FE switcher, share `ws` field, migration tooling — remains)

Give each org multiple folders, each one a full workspace (own file tree, chats, AGENT.md, skills). Every user gets a personal workspace; team workspaces are shared with role-based access managed by their creator. Org admins manage workspace lifecycle, not content.

## Where the current code stands

Everything hangs off `workspace()` in `cycls/app/db.py:22-30`. It derives, from the authenticated `User`:

- **Filesystem root** `volume/{org}` — the bash-sandbox bind target, and the root for the files router, canvas, uploads, AGENT.md, and skills. Keyed on **org only**: all users in an org share one tree with no isolation between them.
- **KV prefix** `{org}/.db/{user}` — chats and shares are per-user within the org; the agent `database` tool uses `{org}/.database/{user}`.

Three facts this design leans on:

1. **Sandbox isolation is "whatever root you bind."** The bash tool binds only `workspace.root` at `/workspace` inside bwrap (`cycls/agent/tools/__init__.py`), and the over-mount shadows all siblings (see `docs/sandbox-security.md` attack probes). Per-workspace isolation falls out automatically once the root path includes a workspace segment.
2. **Clerk already delivers the org data.** `User` carries `org_id`, `org_role`, `org_permissions` (`cycls/app/auth.py`, from Clerk's `o` claim) — parsed today, enforced nowhere.
3. **Share tokens are the access-control precedent**: `public` / `org:{id}` audiences checked per request against a stored row (`cycls/agent/state.py::resolve`). The workspace ACL generalizes that pattern.

## Model

A **workspace** = one folder with its own filesystem root, chat namespace, AGENT.md, and skills.

- **Personal** — auto-provisioned per user, id `u-{user_id}`. No ACL rows; only the owner can enter. **Org admins get lifecycle rights only** (see below), never content access.
- **Team** — id `t-{nanoid}`. Created by any org member by default; `Web().workspaces(create="admin")` restricts creation to org admins. Members carry roles:
  - `owner` — the creator; full control incl. delete
  - `admin` — manage members
  - `editor` — read/write files, run agent sessions
  - (`viewer` reserved for later — read-only files, no bash; if added, gate `AGENT.md` and `skills/` writes behind `editor`)

  The Clerk org admin (`org_role == "admin"`) has implicit `admin` on all **team** workspaces.

**Lifecycle-only admin access to personal workspaces**: an org admin can list personal workspaces (name, owner, size, last activity), delete one (offboarding), and export/archive it as a blob — but `GET /files`, `/chats`, and the chat stream return 404 for them like any non-owner. Privacy by default; a per-org visibility override can come later if a compliance customer needs it.

The client sends the active workspace as an `X-Workspace` header on every request. No header → personal workspace, which keeps the b2c/no-org case and existing API clients working unchanged.

## Storage layout

```
volume/{org}/
├── .org/                          # framework-managed, OUTSIDE every workspace root
│   ├── workspaces/{ws_id}         # {id, name, type, created_by, created_at}
│   └── members/{ws_id}/{user_id}  # {role, added_by, added_at}   ← O(1) access check
└── ws/{ws_id}/                    # workspace root = the sandbox bind target
    ├── ... user files, AGENT.md, skills/
    ├── .db/{user}/chat/...        # chats scoped per (workspace, user)
    └── .database/{user}/...       # agent KV — stays per-user (decision)
```

- **ACL lives under `{org}/.org/`, outside every workspace root.** Never bind-mounted into any sandbox, unreachable by `_resolve_path` (which can't escape `ws.root`), touched only by trusted Python — same posture as share tokens. Member rows are flat `str:str` so they ride GCS custom metadata for fast scans.
- **Member rows keyed `{ws_id}/{user_id}`** → hot-path check is one GET. A short in-process TTL cache (~30s) is fine; it bounds revocation latency.
- **Chats move inside the workspace.** Attachments resolve against `ws.root` at ingest (`harness/main.py::_ingest`), so a chat is only coherent in the workspace it was created in. Sidebar becomes workspace-scoped.
- **The `database` KV stays per-user within a workspace** (`{org}/ws/{ws_id}/.database/{user}`). A team-shared scope can be a v2 option on the tool.
- **`u-`/`t-` prefixes** plus the existing id regex (`^[A-Za-z0-9_-]+$`, same as chat ids) prevent traversal and prevent a team workspace colliding with someone's personal one. The `ws/` subtree keeps workspace roots clear of `.org/`.
- Don't extend the `org:user` subject-string format — `partition(":")` is too fragile. `Workspace` gains an explicit `ws` field; share rows store `ws` (rows without it resolve to the legacy/default workspace).

## Enforcement

One FastAPI dependency replaces the current `_build_ws` (`cycls/agent/web/routers.py`) as the single chokepoint:

```
resolve_workspace(user, ws_id) →
  personal (u-{user.id})            → allow, ensure dir
  personal (u-{someone else})       → 404      # org admin included — content is off-limits
  team: member row exists           → allow with row.role
  team: user.org_role == "admin"    → allow as admin
  else                              → 404      # not 403 — don't leak existence
```

Lifecycle endpoints (`GET /workspaces` listing, `DELETE /workspaces/{id}`, archive/export) sit outside this check and grant org admins their lifecycle powers over personal workspaces explicitly.

New routers: `/workspaces` CRUD + `/workspaces/{id}/members` CRUD. Creation policy comes from the builder (`workspaces(create="member" | "admin")`, default `"member"`).

**No Clerk backend API needed to validate invited members**: an ACL row alone grants nothing — access requires the row *and* an authenticated JWT whose `org_id` matches. A bogus user id in the ACL is inert because that user can never mint a token in the org.

`workspace()` grows the `ws` dimension: `root = volume/{org}/ws/{ws_id}`, `path = {org}/ws/{ws_id}/.db/{user}`. All call sites go through it, and every consumer (files router, bash bind, read/edit/canvas, AGENT.md, skills discovery, agent KV) keys off `ws.root`/`ws.path`, so they follow automatically.

## Security analysis

Holds by construction:

- **Cross-workspace bash access** — the bwrap bind of `volume/{org}/ws/{ws_id}` at `/workspace` shadows all siblings, the same mechanism isolating orgs today. Add attack-probe tests mirroring `tests/app/sandbox_test.py`: from a team workspace, `ls /workspace` shows nothing else; `/proc` cross-reads stay blocked by the user-namespace boundary.
- **Cross-workspace API access** — everything funnels through `resolve_workspace`; `_resolve_path`/`resolve_path` already can't escape the root.
- **ACL tampering from inside the agent** — `.org/` is outside every root and every sandbox.

Documented caveats:

1. **The GCS metadata-token bypass now crosses a boundary users care about.** `docs/sandbox-security.md` documents that a deliberately adversarial user (static binary, `unset LD_PRELOAD`) can steal the Cloud Run SA token from a `network=True` bash; that token is bucket-wide and reads every workspace in the deployment — including colleagues' personal workspaces. Mitigations unchanged (the shim covers ~all LLM-generated code; `network=False` closes it fully; per-tenant deploys are the architectural fix). Consider a per-workspace `network` policy so sensitive workspaces can opt out of egress.
2. **AGENT.md and skills become a teammate-injection surface.** Both are read from `ws.root`, so any team-workspace editor can plant instructions/skills that execute in teammates' agent sessions. Within a team's trust boundary (same as a shared repo), but document it; the future `viewer` role must not be able to write them.

## Migration and rollout

Gated behind `cycls.Web().workspaces(...)`, default off — existing deployments untouched. When enabled:

- **Fresh deployments** get the clean layout immediately.
- **Existing deployments** run a one-time migration: legacy org-root files move to a builtin team workspace (`t-shared`, all org members as editors); legacy chats under `{org}/.db/{user}` map there too — that's where their attachments live. Prod FS is gcsfuse (renames = copy+delete), so migrate via trusted server-side GCS rewrites, not through the mount.

Phases:

1. Thread `ws` through `workspace()`; personal workspaces; `X-Workspace` header; sandbox probe tests. Small, shippable on its own.
2. Registry + ACL + members API + org-admin enforcement (lifecycle-only on personal) + creation policy option.
3. FE switcher (mirror the org-switcher remount pattern, key by `org+ws`), workspace-settings UI, share/fork extension, migration tool.

## Decisions log

| Decision | Outcome |
|---|---|
| Org admin access to personal workspaces | **Lifecycle only** — list/delete/archive, never content |
| Who can create team workspaces | Builder option `workspaces(create=...)`, **default any member** |
| Agent `database` KV scope in team workspaces | **Per-user** (`.database/{user}`); team-shared is a possible v2 |

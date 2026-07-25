# Workspaces — personal and team folders for orgs

Multi-workspace mode gives every user a private personal workspace and lets
org members share team workspaces with role-based access. Each workspace is a
full, isolated context: its own file tree, chats, `AGENT.md`, skills, and
agent KV. Opt in on the Web builder — it requires auth:

```python
web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .workspaces()            # or .workspaces(create="admin")
)
```

`create` sets who may create team workspaces: `"member"` (default, anyone in
the org) or `"admin"` (org admins only).

## The model

| Workspace | Id | Who can enter | Managed by |
| --- | --- | --- | --- |
| Personal | `u-{user_id}` | only the owner — org admins get lifecycle (list/delete), never content | the owner |
| Team | `t-{id}` | members via the ACL; org admins implicitly | the creator (`owner`) + `admin` members |
| General (builtin) | `t-shared` | every org member (editor) by default — org admins may exclude individuals; member rows hold only `excluded` markers | org admins (name/icon editable by them only) |

Every org gets **General** automatically on its first request — an empty
registry row; any legacy data reaches it only via the operator CLI. An org
admin deleting General is permanent. Solo (org-less) users get Personal only.

Team member roles: `owner` (the creator; can delete), `admin` (manages
members and rename), `editor` (works in the workspace). The owner row is
immutable; members can remove themselves.

## Selecting a workspace

The client sends the active workspace id in the `X-Workspace` header on every
request; no header means the user's personal workspace, so existing API
clients keep working unchanged. The chat UI ships a switcher in the header
(beside the panel toggle) with inline create and member management; the
selection persists per org. Unknown or unauthorized ids return 404 — not
403 — so workspace ids don't leak existence.

Inside the agent, `context.workspace` resolves to the active workspace; the
Bash sandbox binds only that workspace's directory at `/workspace`, and
`AGENT.md`, skills, uploads, and the canvas all follow it. Chats and the
`database` tool KV stay **per-user within** a workspace — teammates share
files, not each other's chats.

## HTTP API

Mounted only when workspaces are enabled; all routes require auth.

```
GET    /workspaces                          # personal + your teams (+ ?all=1: org-admin lifecycle view)
POST   /workspaces                          # create team (body: {"name": ..., "icon"?: "🚀"}); 409 on reserved names (Personal, General's)
PATCH  /workspaces/<id>                     # rename / set icon — one emoji, validated (owner/admin; icon: "" clears)
DELETE /workspaces/<id>                     # owner or org admin; personal: self or org admin
GET    /workspaces/<id>/members             # on General: the exclusion rows (membership is the org minus these)
PUT    /workspaces/<id>/members/<user_id>   # body: {"role": "editor"|"admin"}; on General: clears an exclusion (re-add)
DELETE /workspaces/<id>/members/<user_id>   # managers, or yourself (leave); on General: org admins only — writes an exclusion
```

Adding a member takes their Clerk user id; the row alone grants nothing —
access also requires an authenticated token for the same org, so a stray id
is inert. The chat UI offers org members by name (from Clerk, client-side).

## Enabling on an existing deployment

The SDK moves no data. On an org's first request it provisions General's
registry row — nothing else. Legacy content under the org root stays where
it is (invisible in workspace mode) until the operator migrates it into
General via the CLI, dry-run first. Solo accounts need no migration at
all: their personal workspace IS the account root, so their data is
readable in place the moment the flag flips. Deleting General writes a
tombstone row, which keeps the deletion permanent across provisioning.

## Security

- The bash tool's bubblewrap sandbox binds only the active workspace's
  directory at `/workspace` — sibling workspaces are not mounted and stay
  invisible. Registry and ACL rows live under the org-level `.org/` tree,
  outside every workspace root, out of reach of both the sandbox and the
  path-validated file tools.
- `AGENT.md` and `skills/` are per-workspace, so in a team any editor's
  instructions run in teammates' sessions — the same trust boundary as a
  shared repo, but worth knowing.
- A deliberately adversarial user with `network=True` bash can steal the
  deployment's service-account token, which reads the whole bucket across
  workspaces. See [sandbox-security.md](notes/sandbox-security.md) for the threat
  boundary; `network=False` closes it fully.

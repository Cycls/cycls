# Trash — a delete is a move

**Why.** Two parties delete things in a workspace: the user, and the agent
(`rm` from bash, an `edit create` over an existing file). Both were
unrecoverable. Now nothing the product calls "delete" is.

## Shape

- One trash per workspace at a hidden `.trash/`. Bytes move (a rename) to
  `.trash/<id>/data/<original path>`; `meta.json` beside them records path,
  kind (`file` / `dir` / `app`), who (`user` / `agent`), why (`delete` /
  `overwrite`), when. No DB index — the layout has to be writable from the
  sandbox `rm` shim, which is stdlib-only.
- **Chats** are DB rows, so their delete is a `deletedAt` tombstone on the
  chat's index row: listings skip it, restore clears it, purge wipes the
  subtree. `GET /trash` merges files and tombstoned chats into one list.
- **Restore** moves back; if the path was taken since, it lands as
  `name (restored).ext`.
- **Roles**: anyone who can edit trashes and restores. **Delete-forever,
  empty-trash, and deleting an app** are owner/admin only (personal
  workspaces: the owner) — one permission model, server-enforced.
- The model never sees `.trash/`: hidden from listings and zips, rejected by
  both path guards (`_resolve_path` in tools, `resolve_path` in routers),
  and tmpfs-masked inside the bash sandbox.

## Expiry — 30 days, lazy

Entries expire `TTL_DAYS` after *their own* deletion. The sweep runs at two
user-triggered moments — any trash listing (the Files tab loads the footer
count, which is a listing) and any new deletion — so an active workspace's
trash can't grow unbounded, and an idle workspace costs nothing. No cron, no
scheduler, no per-agent job. If an abandoned-workspace guarantee is ever
wanted, an operator CLI is the add, not a v1 need.

## The agent's `rm`

`cycls/_agent/tools/shims/rm` (and `rmdir`) sits first on the sandbox
`PATH`. Targets inside the workspace move to the trash tagged `by: agent`;
anything outside (`/tmp` scratch) falls through to the real `rm`; missing
files behave like `rm`; the trash itself is refused. The model still thinks
it deleted. Inside the sandbox the trash is masked at `/workspace/.trash` and
bound at `/workspace-trash` (envs `CYCLS_WORKSPACE`, `CYCLS_TRASH`) — the
shim writes through the second mount.

An `edit create` over an existing file snapshots the old content into the
trash (`reason: overwrite`) before writing — light version history for free.

**Limits, honestly**: `find -delete`, `shred`, `/bin/rm` by full path, or
`>` truncation bypass the shim. The prompt already steers the model away from
bash for file content; these are rare and documented, not covered.

## UI

- **Undo instead of confirm** for ordinary deletes: an Undo toast (10s) and
  **⌘Z / Ctrl+Z** while it shows (never inside a text field — that stays
  native text undo). Confirm dialogs survive only for apps and delete-forever.
- **Trash** is a footer row at the bottom of the Files tab ("Trash · 3"),
  opening one list of files, apps and chats — what it was, where, when, and
  *who deleted it* (agent or person). Chats also get "Recently deleted" at
  the bottom of the Chats tab, the same view filtered.
- Apps: a ⋯ menu on the card — Open in new tab, Rename, Change icon (emoji),
  Upload image (saved as `apps/<slug>/icon.<ext>`, ≤ 2 MB) — all edit
  `apps/<slug>/app.json`; the slug stays immutable — and an admin-only Delete
  (confirm → trash).

## API

`DELETE /files/{path}` → `{trash_id, kind}` · `DELETE /chats/{id}` →
`{trash_id: "chat:<id>"}` · `GET /trash` · `POST /trash/{id}/restore` →
`{path}` · `DELETE /trash/{id}` (admin) · `DELETE /trash` (admin).

## Events

`file_deleted{kind, by, permanent:false}`, `chat_deleted`,
`trash_restored{kind, method}`, `trash_purged{kind | all}` — see
analytics.md.

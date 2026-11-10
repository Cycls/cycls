# File metadata: who made and changed each file, and an audit log for org admins

**Status**: proposed (2026-11-10), branch `rfc/file-metadata`.

Every file says who created it and who last edited it, with a short history, the way Drive does. When an agent made a
change, the file says for whom and in which chat. Organizations also get an audit log of what changed in their team
workspaces, for org admins, in Settings.

## Decisions

| | Decided |
| --- | --- |
| What a file shows | Created and last edited (who, when), and its last 20 changes |
| An agent's change | Belongs to the person who asked: "Sara, via Super in “Café plan”", the chat a link back |
| Opened by | Not recorded |
| Faces | The person's own picture, small and round; their initial on their color without one. A star (the Cycls star) on the face when an agent made the change |
| The list | Size, date, then the last editor's face. A click on the face opens the details |
| When we don't know | The date alone, never a guessed name |
| The agent | Sees who last edited a file it reads in a team workspace |
| Audit log | Organizations only, org admins only, team workspaces and the org's own changes; loads as it scrolls; exports as CSV |
| Safety | No agent, bash command, file tool or file route can read or change a record or the log |

## What a change is

```json
{"by": "u_sara", "at": "2026-11-10T09:03:00Z", "action": "edited",
 "agent": "super", "chat": {"id": "c1", "title": "Café plan"}, "from": "drafts/plan.docx"}
```

`action` is `created`, `edited`, `uploaded`, `renamed`, `moved`, `restored`, or for the log also `deleted`. `by` is the
person (the one who asked, when an agent made it). `agent` is the agent's name; the client shows it in the person's
language. `from` is a rename's or a move's old path.

## Where it comes from

1. **The person, through the app**: upload, a save from an editor (text, Design, Sheets, Docs, video), rename and
   move, a new folder, delete, restore. Each route knows who is signed in and records the change.
2. **The agent**: its file tools and its bash commands write straight to the workspace, and bash is how most Word,
   Excel and PowerPoint files are made. So a run that made any tool call ends with one walk of the workspace: every
   file changed since the run began, and not already recorded by someone else meanwhile, is that run's change, for
   its person, agent and chat. One mechanism covers every tool, bash included.
3. **Anything else** (a change from outside cycls): the record keeps the size and time the file had when it was
   recorded. When they no longer match, the file shows its date without a name.

## Where it is kept

- **A file's record**: the workspace's own `.files` store, keyed by the file's path. The summary (last edited,
  created, the file's size and time) rides as the object's metadata, so a folder's listing reads every record in it
  with one LIST; the history is read only when the details open. A rename or move takes the record along (a
  folder's, every record under it); a delete keeps it with the trash entry and a restore brings it back.
- **People**: the org's store, `people/{id}`: name and picture. The app sends the signed-in person's on load, and
  the sign-in token fills it when it carries them. Records keep only the id, so a new photo shows on every file.
- **The audit log**: the org's store, `audit/{inverted time}-{rand}`, so keys sort newest first and a page is one
  LIST from a cursor (the store gains `page(prefix, after, limit)`).

## Kept from the agent

`.files` and the org store (`.org`) join the managed slots (`paths.MANAGED`): the sandbox mounts an empty tmpfs over
each, the file tools refuse them, and the file routes refuse them. Only the server's own code writes a record or a
log entry; the log has no route that changes or deletes it.

## The audit log

What the products people compare us with keep (2026-11-11): Claude Enterprise about 35 events (sign-ins, invites,
members, projects, chats by id, files uploaded, exports; never chat titles or content; 180 days); Notion several
hundred (pages viewed, edited, exported, shared to the web, members, integrations, MCP, AI settings; 365 days);
Google Drive (viewed, edited, downloaded, shared; 180 days). We keep what an admin acts on, and nothing private.

- **Who**: organizations only; org admins only (`org_role == "admin"`). A personal account has none.
- **Where**: the org's team workspaces and the org itself. Personal workspaces stay out: org admins manage their
  lifecycle, never their content.
- **What**:
  - files: created, edited, uploaded, renamed, moved, deleted, restored, deleted forever, the trash emptied,
    downloaded (a file, a folder as a zip, a design exported, in its format); views are not kept
  - links: shared (public apart from the organization), unshared
  - apps: published (one row an app, not its files)
  - connectors: connected and disconnected (personal or shared with the workspace), what a tool may do changed,
    allowed or blocked for the organization, and every write the agent made through one (the tool and how it was
    let: approved, Auto or Always allow; never its arguments)
  - the org: a workspace created, renamed, deleted; a member added, their role changed, removed; the log exported
- **Each row**: when, who (face and name), what, the target, the workspace, the agent when one did it, and where
  it came from: the address and the client (web, iOS, Android, or a program on the API). Never a chat's title or
  anything inside a chat or a file.
- **Kept**: 180 days. Older rows are cleared once a day, from the first row written that day.
- **Reading it**: Settings, an "Audit log" tab for org admins. 50 rows a page, more as it scrolls.
- **Export**: `GET /audit.csv`, the whole log as CSV, paged through on the server; the export is itself a row.
- **Later**: sign-ins, invites and org membership from the sign-in provider's webhooks.

**A run's walk** leaves out what builds leave (`node_modules`, `__pycache__`, virtual environments), counts an
app as one row, and records 100 files one by one; past that, one row says how many more changed.

**A chat is its owner's**: a file's history shows the chat an agent's change came from to the person who asked
only; a teammate sees "via Super".

## Routes

- `GET /files` entries gain `created` and `edited` (each a change, with `by` as `{id, name, image, you}`).
- `GET /files-info/{path}`: `{created, edited, activity}`.
- `PUT /people/me`: `{name, image}` for the signed-in person.
- `GET /audit?after=<cursor>` → `{events, next}`; `GET /audit.csv`.

## The agent

Reading a file in a team workspace starts with one line: `Last edited by Sara Alharbi on 10 Nov 2026, via Super in
“Café plan”.` Team chat will need this; a personal workspace's files are all its owner's, so it is left out there.

## Phases

1. The records, the routes, the walk after a run, the faces, the agent's line, the managed slots.
2. The audit log and its tab, the CSV.
3. Mobile: the same fields.
4. Later: notifications from the same changes; a file's versions linked from its history.

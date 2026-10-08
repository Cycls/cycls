# Cycls and the design editor — how a design is handed between them

A short reference for the seam between the Cycls app and the design editor embedded in
its canvas: who holds what, what they say to each other, and the rules that keep one
file from being written two ways. The reasons behind each rule are in
[design.md](design.md) ("Editing — the in-canvas editor", "One design, in the
workspace", "Together"); this is the map. Current as of 9 October 2026.

(This file was the hand-off plan of 16–17 September 2026 — "commit, give the editor a
home, deploy" — with the first patch files pasted into it. All of that is done; the
plan is in the file's git history.)

## The pieces

| Piece | Where | What it does |
|---|---|---|
| The design | `designs/<name>.fig` in the workspace | The one document. The agent writes it through the design service; a person edits it in the editor; both save to this file. |
| The Cycls side | `client/src/components/design-editor-view.tsx` (this repo) | Fetches the `.fig`, posts it into the editor, writes the editor's saves back, relays the agent's live edits, shows who else is here. |
| The editor | `cycls-design/editor/` — a patched OpenPencil, built by `editor/build.sh` (`editor/Dockerfile`) and served by the design service on its own origin (`DESIGN_EDITOR_URL`, opened with `?embed=cycls`) | Edits one design. Everything that would touch a disk or open a second document is routed to Cycls instead. |
| The bridge | `cycls-design/editor/patches/cycls-bridge.ts` + `host.ts` | The editor's half of the conversation below. Its header comment is the protocol's source of truth. |
| The relay | `cycls-design/live/` (`cycls-design-live`) | Carries a shared document between the editors of people who have one design open. It never reads the design. |

The editor holds no sign-in and never talks to the workspace: the Cycls page around it
does, and the two speak only by `postMessage`.

## The hops

| From → to | By |
|---|---|
| Agent's `Design` tool → design service | HTTP, `DESIGN_URL` + `DESIGN_SECRET` (`cycls/_agent/design/client.py`) |
| An agent edit → the open editor | the tool's `_ui` event `design_command` on the chat stream → `chat.tsx` → `CustomEvent("cycls:design-command")` → `DesignEditorView` → `command` |
| `DesignEditorView` ↔ editor iframe | `postMessage`: `{target: "cycls-editor", …}` in, `{source: "cycls-editor", …}` out |
| `DesignEditorView` ↔ workspace | `GET /files/<path>` (the bytes, with `X-Version`), `PUT /files/<path>?base=<version>` (a save; 412 when the file changed since) |
| Editor ↔ editor (several people) | a WebSocket each to the relay, opened with a pass from `GET /design/live?path=` |
| Server → a room | `POST /room/<id>/notify` on the relay (`cycls/_agent/design/live.py`): an agent's edit, or "open the file again" |

## What they say (protocol 2)

Cycls → editor:

| Message | Meaning |
|---|---|
| `load {protocol: 2, doc, name, fig, brand?, page?, live?}` | Open this document (a second `load` replaces it). `doc` tags its saves; `page` is the page to open on; `live` opens it together with whoever else has it open. |
| `written {id, ok}` | The workspace has save `id` — or couldn't write it. |
| `save` · `flush {id}` | Save now · save anything unsaved, then answer `flushed {id, ok}`. |
| `command {script, intent?, page?}` | An agent's edit, to make on the document in view. |
| `page {name}` · `theme {theme}` · `locale {lang}` · `brand {brand}` | The page to show; dark or light; Arabic or English; the workspace's brand kit. |
| `fit` | The editor's box changed size: fit the design again, unless the person has zoomed or panned since the last fit. |
| `follow {client}` | Keep this person's view in step with that one's (`null`: stop). |
| `liveTicket {id, ticket}` · `liveBase {version}` · `liveReset` | A fresh pass for the room; "this document holds that version of the file"; "this person took the file over what the room holds — everyone opens it again". |

Editor → Cycls:

| Message | Meaning |
|---|---|
| `ready {protocol: 2, features}` | The editor is up. `features` lists what it does beyond the base protocol — `selection`, `lang`, `fit`, `pages`, `live` — so Cycls offers only what this build supports. |
| `loaded {doc, name, live?}` | The document is open (`live: "seed" \| "join"`: it gave the room the file's document, or took the room's). |
| `saved {doc, id, name, fig}` | Bytes to write to the workspace; answered with `written`. |
| `flushed {id, ok}` · `applied {doc}` · `commandError {doc, message}` · `error {doc?, message}` | Answers and failures. |
| `newDesign {size?}` · `saveCopy {doc, name, fig}` · `export {doc, files}` · `exportAs {doc, format}` | What the editor's own menus ask Cycls to do in the workspace. |
| `selection {doc, frame, nodes}` · `pages {doc, page, pages}` | What is selected; the design's pages and the one in view. |
| `presence {doc, peers, saver, connected}` | Who else has the design open, and whether this editor is the one saving for them. |
| `liveTicket {id}` · `liveAgent {doc, version}` · `liveReload {doc, version}` · `liveBase {doc, version}` | Asks and news from the room. |

An older Cycls app sends `load` without `protocol`: its saves count as done once
posted, and it gets none of the workspace messages.

## The rules that keep one file one file

- **One editor, one design.** The editor's own tabs, Open, Save-as and export-to-disk
  are stubbed to Cycls (`patches/stubs/`); a copy or an export lands in the workspace.
- **A save names what it started from.** `PUT …?base=<version>`; the server refuses a
  save over a file that changed since (412, with the version it is now). Alone, that
  opens the conflict dialog. Together, a refusal over a version the room has heard of
  is retried quietly; over one it hasn't, the dialog opens.
- **An agent's edit is made on the server first.** It is applied to the saved file and
  written before the editor hears of it; the editor then *replays* it. A replay that
  fails posts `commandError`, and Cycls opens the saved file again — a stale document
  never auto-saves over the agent's change.
- **Together, one editor saves.** The person present longest is the saver; the others
  ask it to. Each save is announced to the room before it is written, so nobody takes
  it for someone else's change. A file written anew (a version restored, slides changed
  in the deck viewer, a document re-rendered) is told to the room as "open it again".
- **A background tab waits.** Showing a page and fitting it need animation frames; a
  design opened or joined in a hidden tab waits to be seen instead of failing.
- **A fit is to what can be seen.** After the editor's own fit, a page that ends under
  the editor's toolbar — a tall page in a docked pane — is fitted again to what the
  bars leave of the canvas (`fitPage`).

## Where to look

| For | Read |
|---|---|
| The Cycls side | `client/src/components/design-editor-view.tsx`, `design-presence.tsx`, `version-history.tsx`, `deck-view.tsx`; tests in `client/tests/design-editor-view.test.tsx` |
| The server | `cycls/_agent/web/routers.py` (`/files`, `/versions`, `/deck`, `/design/*`), `cycls/_agent/design/` (`store.py` versions and bases, `live.py` rooms and passes, `refresh.py` exports beside a design, `deck.py` slide changes) |
| The editor's patches | `cycls-design/editor/patches/` — `cycls-bridge.ts`, `host.ts`, `collab/`, `stubs/`, `edits.json` (exact edits to upstream files), `upstream.sha256` (the upstream files they rely on, pinned) |
| The relay | `cycls-design/live/server.ts`, `live/ticket.ts`, `deploy_live.py` |
| Why OpenPencil needs each patch | `cycls-design/docs/quirks.md` |
| Tests of the seam | `cycls-design/editor/tests/` (Playwright: a real editor in a stand-in Cycls page; `test_workspace.py` alone, `test_live.py` together), `cycls-design/tests/live.test.ts` (the relay) |

## Building and shipping it

The editor is built inside a Linux container (`docker build -f editor/Dockerfile
--output type=local,dest=editor-dist editor`, from the service repo); the service
deploy copies `editor-dist/` into its image, so the editor ships with the service.
The build pins OpenPencil to one commit and fails if an upstream file the patches
replace or edit has changed. The Cycls side ships in this package: `cd client && npm
run build` writes the web client into `cycls/_agent/web/themes/default`.

`docs/notes/design-editor-patch/` is a snapshot of the patch files from 5 October 2026,
kept from before they had a repo of their own. It is not what is built.

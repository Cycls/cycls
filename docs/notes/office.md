# Cycls Sheets and Cycls Docs (the office editors)

Spreadsheets and documents people edit in the canvas and the agent edits with them, shaped like Cycls Design and
Cycls Video: a branded editor framed from its own service, files that stay real `.xlsx` / `.docx` in the workspace,
versions, live agent edits. The engine is the open-source part of [Univer](https://github.com/dream-num/univer)
(Apache-2.0), patched and rebranded in the **cycls-office** repo, which also holds the Excel/Word exchange (we write
back only what changed), the headless engine the agent edits through, and the service.

The full plan (phases P0 → S1–S6 → D1–D6) is kept outside the repo; this note says what is built. Sheets only so
far; Docs has its config switch and nothing else.

## The service (cycls-office)

One Node process:
- `/sheets/` — the Cycls Sheets editor (public, framed by Cycls, strict content policy).
- `/health` — release, engine stamp, workers.
- `/v1/…` behind `OFFICE_SECRET`:
  - `xlsx/read` — the file's bytes → the workbook the editor opens, plus notices of what is kept but not editable.
    Charts come with it as descriptions (kind, series and the cells they draw from, colours, axes, legend, place):
    the editor draws them with ECharts, redraws one when its cells change, and a moved, resized or deleted chart
    is saved (the chart part itself is never rewritten). Pivot tables come with their place, fields and source:
    the editor outlines each with a tag and keeps its cells from edits (formatting allowed, as in Excel); a save
    after its source changed sets `refreshOnLoad`, so Excel recomputes it on open.
  - `xlsx/patch` — the original file + the editor's workbook (gzip JSON, `{snapshot, ops}`) → the patched file.
    Only changed rows and parts are rewritten; `ops` (rows/columns inserted or removed) move the references the
    file keeps as written (conditional formats, validation, filters, pictures, charts, tables, pivots, names).
  - `sheets/read` and `sheets/apply` — the agent's tool (below).

## In the SDK

- `cycls/_agent/office/client.py`: `configured()`, `editor_url()`, `offered(workspace, "sheets"|"docs")`, and the
  service calls (`read_xlsx`, `patch_xlsx`, `sheets_read`, `sheets_apply`). Never follows a redirect.
- `web/office_routes.py`:
  - `GET /office/sheets?path=` → `{editor: true, url, name}` or `{editor: false, reason}`, per workspace.
  - `GET /office/sheets/open?path=` → the workbook (gzip JSON, cached by file version in `.cache/sheets/`),
    `X-Version`, `X-Modified`.
  - `GET /office/sheets/version?path=` → `{version, modified}`, the version open and save use.
  - `PUT /office/sheets/save?path=&base=&force=` → patch-back through the service, `write_fig(by="user")` keeps the
    replaced version; a stale `base` answers 412 with the file's version.
- `Config.public()` sends `sheets_editor: true` when the service is configured (the URL and org list stay
  server-side).
- `client/src/components/sheets-editor-view.tsx`: `SheetsOrPreview` asks the route once per file (without Sheets
  the SheetJS preview stays). The editor puts its items into the canvas's file header (last modified, status,
  Open ⌄ with Excel/PDF) and shows the conflict bar (Load the latest / Keep mine). Each time the canvas fetches
  the file again (a turn ended, a refresh), once the agent is done the view checks the file's version: a file
  changed some other way (the agent's other tools, another tab or person) is taken in, or, with changes not yet
  saved, the conflict bar asks.

## The agent's `sheets` tool (`cycls/_agent/office/sheets.py`)

Offered like Video: the agent lists `"Sheets"` in its tools, `build_tools` adds it when `OFFICE_URL` is set, and
`harness/main.py` drops it per run for an organisation not on `SHEETS_ORGS`. While it is on, the prompt says .xlsx
changes go through `sheets`, not openpyxl (pandas stays fine for analysis).

- Required: `action` (`read` / `edit` / `create`) and `path`; each op requires `op` and `target`.
- `read` → the sheets outlined (used range, right-to-left, frozen panes, merges) and a sheet or range as a grid of
  formulas → values, about 8k characters at most; notices of what the file keeps but Sheets doesn't edit.
- `edit` → `ops` run in order on the service in the same engine the editor runs: `set_values`, `set_formulas`,
  `format`, `clear`, `merge`/`unmerge`, `insert_rows`/`delete_rows`/`insert_cols`/`delete_cols`,
  `add_sheet`/`rename_sheet`/`delete_sheet`, `freeze`, `column_width`, `sort`, `set_direction`, `note` (`text`; empty
  removes it), `define_name` (`name`, Arabic names allowed). Under the file's
  lock: read → apply → `write_fig(by="agent")`; a save in the editor meanwhile makes it apply once more to the newer
  file. The reply reads the changed ranges back and lists formula errors.
- `create` → a blank workbook (first sheet named by `target`, `rtl` for Arabic) and then `ops`; opens in the canvas.
  Without `rtl`, an Arabic sheet name or Arabic values make it right to left (DeepSeek dropped the flag on super-dev).
- Every call logs `sheets_call` with its argument names and op names.

The `_ui` event `sheets_command {path, mutations, version, intent}` carries the engine's mutations. An open editor
replays them; it is read-only under a banner while the turn runs (the tab is marked live, as Design does); one that
does not replay, or one too large to send (`reload`), reopens the saved file. Before a message is sent, every open
Sheets editor saves what is unsaved, so the agent reads what the person sees.

## Configuration

| env | meaning |
|---|---|
| `OFFICE_URL` | the service, e.g. `https://cycls-office.cycls.ai` |
| `OFFICE_SECRET` | the key the SDK sends (`Authorization: Bearer`) |
| `OFFICE_EDITOR_URL` | where the browser loads the editors; defaults to `OFFICE_URL` |
| `SHEETS_ORGS` / `DOCS_ORGS` | who gets each: org ids, a person's id, a team workspace id; empty = nobody, `*` = everyone |

## Editor protocol 1 (postMessage)

Cycls → editor `{target: "cycls-sheets", type, …}`, posted to the editor's exact origin; editor → Cycls
`{source: "cycls-sheets", type, …}`, heard only from that origin and frame.

| Cycls → editor | editor → Cycls |
|---|---|
| `load {doc, name, snapshot, activeSheet, readonly}` | `ready {protocol, features}` |
| `theme {theme}` · `locale {lang}` · `readonly {readonly}` | `loaded {doc}` · `error {doc, message}` |
| `written {doc, id, ok}` (a save landed, or didn't) | `dirty {doc, dirty}` |
| `flush {id}` · `save` | `saved {doc, id, snapshot, ops}` · `flushed {id, ok}` |
| `command {doc, id, mutations}` (the agent's edit, already in the file) | `applied {doc, id, ok, error?}` |

Autosave: about 1.2 s after the last change, at most 8 s after the first; one save in flight. A replayed mutation is
never saved or undone and never marks the workbook dirty.

## Not built yet

Comments and co-editing (S5); Docs (D1–D6). Built 2026-10-24 (not deployed yet): charts drawn and kept, pivot
tables guarded, the file's own fonts (Aptos, Calibri) used for cells without a format and text laid out again
once a font has loaded, the reload after a file changed some other way. Saved since 2026-10-24: notes, defined
names, tables (with their Excel style shown), pictures (shown, moved, resized, deleted, added), cells inserted or
deleted with a shift; right-to-left sheets drawn mirrored (S4). Deployed 2026-10-24: the cycls-office service and
super-dev (SDK feat/office).

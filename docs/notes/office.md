# Cycls Sheets and Cycls Docs (the office editors)

Spreadsheets and documents people edit in the canvas and the agent edits with them, shaped like Cycls Design and
Cycls Video: a branded editor framed from its own service, files that stay real `.xlsx` / `.docx` in the workspace,
versions, live agent edits. The engine is the open-source part of [Univer](https://github.com/dream-num/univer)
(Apache-2.0), patched and rebranded in the **cycls-office** repo, which also holds the Excel/Word exchange (we write
back only what changed), the headless engine the agent edits through, and the service.

The full plan (phases P0 → S1–S6 → D1–D6) is kept outside the repo; this note says what is built: Sheets (editor
and agent tool), and Docs (agent tool, and the editor for left-to-right documents).

## The service (cycls-office)

One Node process:
- `/sheets/` — the Cycls Sheets editor (public, framed by Cycls, strict content policy).
- `/docs/` — the Cycls Docs editor (the same).
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
  - `docx/read` — the file's bytes → the document the editor opens (`{document, notices, readonly, stats}`;
    `readonly` when it has tracked changes). `docx/patch` — the original + the editor's document (gzip JSON) →
    the patched file, only changed paragraphs rewritten, or `{unchanged: true}`.
  - `docs/read` and `docs/apply` — the agent's Word tool (below).

## In the SDK

- `cycls/_agent/office/client.py`: `configured()`, `editor_url()`, `offered(workspace, "sheets"|"docs")`, and the
  service calls (`read_xlsx`, `patch_xlsx`, `read_docx`, `patch_docx`, `sheets_read`, `sheets_apply`, `docs_read`,
  `docs_apply`). Never follows a redirect.
- `web/office_routes.py`, the same four routes for each editor (`<p>` is `sheets` for .xlsx/.xlsm, `docs` for .docx):
  - `GET /office/<p>?path=` → `{editor: true, url, name}` or `{editor: false, reason}`, per workspace
    (`SHEETS_ORGS` / `DOCS_ORGS`). Arabic (right-to-left) Word documents open in the editor too (D3, below).
  - `GET /office/<p>/open?path=` → what the editor opens (gzip JSON, cached by file version in `.cache/<p>/`),
    `X-Version`, `X-Modified`.
  - `GET /office/<p>/version?path=` → `{version, modified}`, the version open and save use.
  - `PUT /office/<p>/save?path=&base=&force=` → patch-back through the service, `write_fig(by="user")` keeps the
    replaced version; a stale `base` answers 412 with the file's version. Every save logs `office_save` (product,
    path, outcome written/unchanged/stale/refused/unavailable, the patch summary, versions) with the editor's
    `X-Edit-Trail`: what the editor did since its last save, a line per command, edit or selection (names, offsets,
    lengths, never the text; the first 20 lines of a burst and the last 39) — a save that changed more than the
    person meant can be traced from `cycls logs`.
- `Config.public()` sends `sheets_editor: true` when the service is configured (the URL and org list stay
  server-side).
- `client/src/components/sheets-editor-view.tsx`: `SheetsOrPreview` asks the route once per file (without Sheets
  the SheetJS preview stays). The editor puts its items into the canvas's file header (last modified, status,
  Open ⌄ with Excel/PDF) and shows the conflict bar (Load the latest / Keep mine). Each time the canvas fetches
  the file again (a turn ended, a refresh), once the agent is done the view checks the file's version: a file
  changed some other way (the agent's other tools, another tab or person) is taken in, or, with changes not yet
  saved, the conflict bar asks.
- The same view is Cycls Docs with `product="docs"` (`DocsOrPreview`, used by the canvas for a .docx; without Docs
  the docx-preview stays): its own channel (`cycls-docs`), wording, glyph and Word download. A document with
  tracked changes opens view only. Not yet: comments in the editor, the selection offered to the composer, and
  the agent's edits replayed live — an open document takes them in when the canvas fetches the file again.

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

## The agent's `docs` tool (`cycls/_agent/office/docs.py`)

Offered like `sheets`: the agent lists `"Docs"`, `build_tools` adds it when `OFFICE_URL` is set, `harness/main.py`
drops it for an organisation not on `DOCS_ORGS`. While it is on, the prompt says .docx changes go through `docs`,
not python-docx. The work is the service's (`packages/docx/src/agent` in cycls-office, `/v1/docs/read|apply`).

- Required: `action` (`read` / `edit` / `create`), `path`, `ops` and `content` — the last two even when an action
  takes none (`[]`, `""`): DeepSeek sent 14 creates in a row without `content` while it was optional.
- `read` → each paragraph on a line: `¶7·k3f [Heading 2] {center} {rtl} 1) text with **bold**, *italic*,
  [links](url)`. The number is its place among the body's paragraphs (tables apart); the three letters are a check
  of its id and text, so an edit made from an old read is refused ("read the document again"). Tables are grids
  (`T1`, rows `r1:` with ` | ` between cells); pictures, footnote marks, page and line breaks show where they are;
  headers, footers and footnotes are listed; about 12k characters, then `from` goes on.
- `edit` → `ops`, all or none (the first that cannot be made stops the call and nothing is written): `replace`
  (a paragraph's text; refused when it holds a picture or a note — `find_replace` keeps them), `find_replace`
  (asks which when the words are in several places, unless `all`), `insert_after` / `insert_before` (markdown
  lines: `## Heading`, `- item`, `1. item`, plain; plain text after a heading is body text), `delete` (never the
  paragraph that ends a section or the document), `style` (a named style written as that style — not its look on
  every word —, `align`, `rtl`; with `find` or for whole paragraphs bold / italic / underline / strike / color /
  highlight / size / font), `list` (bullet / numbered / none; a new list takes the document's own look),
  `link` (`""` removes), `cell`, `insert_row` / `delete_row`, `insert_column` / `delete_column`. Arabic text is
  written right to left. Under the file's lock: read → apply → `write_fig(by="agent")`, once more on a save
  meanwhile. The reply lists what was done and shows the changed paragraphs and tables as the next read will
  (new paragraphs carry a Word paragraph id, so their references hold).
- `create` → a new document from `content` in markdown (headings, one paragraph per line, lists nested by two
  spaces, `| tables |`, `> quotes`, links, `[page break]`; Arabic makes it right to left, `rtl` forces it); opens
  in the canvas. The reply is its read.
- The `_ui` event after an edit is `docs_command {path, version, touched, intent?}`: an open Docs editor opens the
  new file at once, read-only under the orange banner until the turn ends, the view kept where it was; the
  paragraphs the edit changed (`touched`, paragraph ids in the written file, at most 50, from the service's
  `/v1/docs/apply`) are marked in orange and the first is scrolled into view. The marks are drawn over the page,
  never written into the file; they go ~6 s after the turn ends, or as soon as the person changes something. An
  open preview fetches the file again (`cycls:canvas-refresh`). A command naming the version already open does
  nothing; two quick edits open only the latest. A right-to-left paragraph is marked across the page's text area
  (in a table cell too: the row), since a right-to-left line's own box is not reliable.
- Every call logs `docs_call` with its argument names and op names (`op_keys`: each op's field names as sent).
- An op's words are `words` in the tool (replace, insert_*, cell, comment, reply), `text` to the service: the SDK
  renames it (a model's `text` is taken too) and says `words` in the service's errors. Some OpenRouter hosts'
  tool-call parsers drop a key named `text` (probed 2026-10-26: Alibaba, Morph, OpenInference, Relace, Makora,
  Ionstream, PrimeIntellect, Wafer — a reply failed 6 times on prod); with `words` they keep it. super-dev also
  skips those hosts (they drop `done` and ramble even so).

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
| | `selection {doc, sheet, ranges}` · `print {doc}` (Ctrl/Cmd+P) |
| Docs: `load {…, marks?, keepView?, me?}` · `reveal {doc, start, end}` | Docs: `selection {doc, nodes: [{name, type, text?}]}` |
| `comments {doc, threads, me, agent?}` · `commentDone {doc, rid, ok, thread?, error?}` | `comment {doc, rid, op, id?, reply?, text?, sheet?, sheet_name?, cell?}` |

Autosave: about 1.2 s after the last change, at most 8 s after the first; one save in flight. A replayed mutation is
never saved or undone and never marks the workbook dirty. Ctrl/Cmd+S saves at once. The agent's replayed changes
are outlined in Cycls orange until a few seconds after its turn.

## Comments

What people write on a workbook's cells is kept like a design's comments: in the workspace's `.comments` record
(`design/comments.py`), not in the file, so a comment is no save. A thread is pinned to `{sheet, sheet_name, cell}`
(the sheet's id, its name for people, a cell like B5); `cell: null` once its row or column was removed (the thread
stays in the list). The routes are the design ones, `/comments/<path>`; a rename, the trash and a restore carry a
workbook's comments as they do a design's. Anyone's edit moves a thread with its cell (`move`); the words stay
their author's.

- In the editor, the engine's own comment UI (a violet corner mark — a note's is yellow — the thread card, replies,
  resolve) runs on a data source that asks the app (`comment` → the store → `commentDone` with the thread); the app
  polls the record (the design comment store) and gives the editor the list (`comments`), which it applies. Rows
  inserted or removed, and cells moved, report the threads' new cells.
- The agent: `sheets {action: "comments"}` lists every thread; with `number`, `reply` and `resolve` it answers and
  closes or reopens one as itself. `read` ends with the open ones. An edit that inserts or removes rows or columns
  moves the threads with their cells (`comments.shift`).

## Cycls Docs: selection, comments, tracked changes

- **Add selection.** The editor names what is selected the way the agent's read names it (`@cycls-office/docx`
  agent/selection.ts): words in a paragraph `¶12·h10 (words) "15%"`, whole paragraphs `(paragraph)`, a table
  cell `T1 r2c3 (cell)`, a long stretch `¶3·abc to ¶40·xyz (paragraphs)`; it sends `selection {doc, nodes}` and
  the canvas offers it to the composer (the chip shows the words). The turn gets
  `[Selected in reports/q3.docx: ¶12·h10 (words) "15%"]`; the references work for an edit straight away (the chat
  saves an open document before a message goes). A paragraph typed in the editor keeps an id of the editor's own
  until the file is read again: its reference fails once, and the agent is told to read again.
- **Comments are kept in the Word file** (not in `.comments`, unlike a workbook's). The editor's read
  (`/v1/docx/read`) gives the file's comments as the engine's threads (the `DOC_UNIVER_THREAD_COMMENT_PLUGIN`
  resource, the commented words as COMMENT decorations); the editor runs the engine's comment UI on them (marked
  words, the panel, replies, resolve, edit and delete for one's own). Authors are people by name: the person at the
  editor (`me` in `load`, from the comments host) is `person:<name>`, and the file's comments under that name are
  theirs. A new comment or reply gets the next free Word comment id in the editor; a save (the service's
  `saveDocx`: patch-back, then `write/comments.ts`) compares the editor's threads with the file's and writes only
  what differs under those ids, so the file read back names them the same and the next save does nothing. Guards:
  the editor sends its threads only once a comment changed; a save removes only threads the editor was given
  (those whose words are in the body). The agent's `docs` comment ops write to the same place, so each sees the
  other's.
- **Tracked changes open in review.** The editor's read marks them as Word's review does (insertions underlined,
  deletions struck through, a colour per person) and lists them (`changes`: ids, author, date, inserted/deleted,
  place; formatting, paragraph-mark and row changes as one `other` item, so taking every listed change leaves
  none). The document stays read-only; the canvas shows a review bar (the count, a list with each change's words
  and author — picking one sends `reveal {doc, start, end}` and the editor selects it — ✓/✕ each, Accept all /
  Reject all). `POST /office/docs/changes {base, action: accept | reject, ids?}` takes some or all for the person
  (the service's `accept_changes` / `reject_changes` with `ids`), written like a save with the old version kept;
  the file opens again, editable once none are left. Reads of `.docx` are cached in `.cache/docs-review` since
  this (older reads have no review in them).
- **Pictures, headers and footers made in the editor are saved** (cycls-office `packages/docx/src/write/`
  blocks.ts, fields.ts, sections.ts). A picture inserted (Insert › picture: PNG, JPEG, GIF or BMP up to 5 MB,
  inline) becomes a media part and an inline drawing; a picture the file had keeps the file's own drawing when it
  is moved, copied (the copy gets its own drawing id) or resized (only its size changes). Pictures are told apart by
  their bytes and size, not their ids (the editor keeps its ids, the file read again gives new ones), so the next
  save does nothing. A header or footer made by double-clicking the top or bottom of a page becomes its own part
  (`word/headerN.xml`) named by its section; an empty one (a click and nothing typed) is not written. The engine's
  id for a header it made is paired with the file's header in the same place, so later saves edit that part.
  "Different first page" is the section's `w:titlePg`, "Different odd and even pages" the settings'
  `w:evenAndOddHeaders`, the header and footer distances the section's `w:pgMar`. Page number, page count and date
  fields are written as Word fields; the reader gives PAGE and NUMPAGES in headers and footers to the editor as live
  fields, so each page shows its own number. The Header & Footer toolbar's groups sit on one row (they were drawn
  for a two-row ribbon and came out cut off). Still not saved, with a notice: text wrapping set on a picture
  (it stays inline), shapes, tables inside a new header. A section break added or removed refuses the save, as
  before.
- **Paragraph borders** (Word's `w:pBdr`) are read and written. The editor's horizontal line (Insert › line) is a
  bottom border on the paragraph it is put under; a file's own borders (a line under a heading, a box) now show in
  the editor. Thickness and distance go into Word's units (eighths of a point, whole points) and the editor's values
  are compared in those units, so the next save does nothing. Solid, dotted and dashed are drawn as such; Word's
  other lines (double, wavy…) are drawn solid and kept as Word wrote them unless that side is changed. A side
  taken away is removed, or written as none when the paragraph's style has a border there.

## Arabic and right-to-left editing

A right-to-left sheet is drawn mirrored (S4). While a cell is edited: arrows move the caret the way they point in
Arabic text (a letter at a time — the engine laid an Arabic word out as one glyph, so the caret jumped words and
Backspace deleted a whole word; each letter is a glyph of its own now, the word still painted joined); typing
straight into a cell, an arrow moves to the cell it points at; pointing at cells in a formula follows the screen;
a validation list, a link card, a note or a comment opens on the mirrored side. Typed text keeps no colour of the
editor's own (cells stay "automatic" in Excel).

A right-to-left Word document (D3, engine patch 0012 + the docx reader) is laid out as Word lays it out: a w:bidi
paragraph starts on the right, its indents (and a list level's hanging) are measured from the right, the list
marker stands beside its text on the right, a justified paragraph's last line ends on the right, a w:bidiVisual
table is mirrored (first column on the right), and Arabic punctuation takes its own place in the line. Word's jc
"left"/"right" in a w:bidi paragraph name its sides by reading order; the model holds the side on screen (the
editor's align buttons), swapped on the way in and back on the way out. In the editor the arrow keys go the way
they point in a right-to-left paragraph (Left goes on through the text, Right goes back; Shift extends).

## Not built yet

Live co-editing (left out on purpose, 2026-10-24); in Docs, right-to-left mouse work (clicking into and selecting
mixed Arabic and English lines), right-to-left headers and footers, Arabic-Indic page numbers (D5), section breaks
saved. The Docs editor, its Arabic layout, the `docs` agent tool, comments and tracked changes
are deployed (2026-10-25/26); pictures, headers and footers saved from the editor: built 2026-10-26. Built
2026-10-24: charts drawn
and kept, pivot tables guarded, the file's own fonts (Aptos, Calibri) used for cells without a format and text laid
out again once a font has loaded, the reload after a file changed some other way, print, comments, the agent's
changes outlined, Arabic caret and deletion by letter and the other right-to-left editing fixes. Saved since 2026-10-24: notes, defined
names, tables (with their Excel style shown), pictures (shown, moved, resized, deleted, added), cells inserted or
deleted with a shift; right-to-left sheets drawn mirrored (S4). Deployed 2026-10-24: the cycls-office service and
super-dev (SDK feat/office).

# Cycls Sheets and Cycls Docs (the office editors)

Spreadsheets and documents people edit in the canvas and the agent edits with them, shaped like Cycls Design and
Cycls Video: a branded editor framed from its own service, files that stay real `.xlsx` / `.docx` in the workspace,
versions, live agent edits. The engine is the open-source part of [Univer](https://github.com/dream-num/univer)
(Apache-2.0), patched and rebranded in the **cycls-office** repo, which also holds the Excel/Word exchange (we write
back only what changed), the headless engine the agent edits through, and the service.

The full plan (phases P0 → S1–S6 → D1–D6) is kept outside the repo; this note says what is built.

## What is built (Phase 0)

- **Service** (cycls-office): one Node process — `/sheets/` the Cycls Sheets editor (public, framed by Cycls, strict
  content policy), `/v1/…` the API behind `OFFICE_SECRET`, `/health` (release, engine stamp, workers).
- **SDK**:
  - `cycls/_agent/office/client.py`: `configured()`, `editor_url()`, `offered(workspace, "sheets"|"docs")`,
    `health()`, `smoke()`. Never follows a redirect.
  - `web/office_routes.py`: `GET /office/sheets?path=` → `{editor: true, url, name}` or `{editor: false, reason}`,
    per workspace.
  - `Config.public()` sends `sheets_editor: true` when the service is configured (the URL and org list stay
    server-side).
  - `client/src/components/sheets-editor-view.tsx`: `SheetsOrPreview` asks the route once per file; the editor is
    framed with `?embed=cycls&theme=&lang=` and only its exact origin and frame are heard. Without Sheets the
    SheetJS preview stays.

Opening the file's contents, saving (patch-back, `write_fig` versions, the 412 conflict dialog) and the agent's
`sheets` tool arrive with the Excel reader (S1–S3).

## Configuration

| env | meaning |
|---|---|
| `OFFICE_URL` | the service, e.g. `https://cycls-office.cycls.ai` |
| `OFFICE_SECRET` | the key the SDK sends (`Authorization: Bearer`) |
| `OFFICE_EDITOR_URL` | where the browser loads the editors; defaults to `OFFICE_URL` |
| `SHEETS_ORGS` / `DOCS_ORGS` | who gets each: org ids, a person's id, a team workspace id; empty = nobody, `*` = everyone |

## Editor protocol 1 (postMessage)

Cycls → editor `{target: "cycls-sheets", type, …}`, posted to the editor's exact origin; editor → Cycls
`{source: "cycls-sheets", type, …}`, heard only from that origin and frame. Phase 0: `ready {protocol, features}`,
`theme {theme}`, `locale {lang}`.

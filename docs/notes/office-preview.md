# Office files on the canvas

Word, PowerPoint and Excel files can't render in a browser directly. The canvas
renders each **in the form that fits it** rather than flattening everything to a
PDF:

| File | Renders as | How |
|------|------------|-----|
| **Spreadsheets** `csv tsv xls xlsx xlsm ods` | interactive grid (sheet tabs) | SheetJS, in a Web Worker, client-side |
| **Word** `docx` | formatted document (pages, fonts, tables, images, RTL) | docx-preview, client-side from raw bytes |
| **Presentations** `ppt pptx odp fodp` | slide viewer (main slide + thumbnail rail) | office-render `/v1/render` → per-slide PNGs |
| **Everything else** `doc odt rtf fodt fods epub` | read-only PDF | office-render `/v1/convert` → PDF viewer |

The routing is decided **client-side by extension** (`canvas-utils.ts`:
`isSpreadsheet` / `isDocx` / `isPresentation` / `isOffice`), so web and mobile
agree and the server stays a plain file host. Every one of these reads as
renderable, so a click opens the canvas instead of a download card; any failure
(service down, unconvertible, parse error) degrades to the download card, never a
dead error.

## The four paths

```
canvas click                     agent web server              office-render
────────────                     ────────────────              ─────────────
GET /files/book.xlsx        ──▶  raw bytes ──────────────────▶ (client parses w/ SheetJS)
GET /files/report.docx      ──▶  raw bytes ──────────────────▶ (client renders w/ docx-preview)
GET /files/deck.pptx?as=slides ─▶ cache? ─▶ POST /v1/render ─▶ soffice → PNGs
                                     └─ JSON of per-slide data-URIs ◀──────┘
GET /files/memo.rtf?as=pdf  ──▶  cache? ─▶ POST /v1/convert ─▶ soffice → PDF
```

- **Spreadsheets / .docx** need no server round-trip beyond the file itself: the
  browser fetches the raw bytes (an authed blob URL) and the renderer parses them
  in place — SheetJS in a worker (`spreadsheet-view.tsx`, `lib/xlsx-worker.ts`),
  docx-preview dynamically imported so it never weighs on the main bundle
  (`docx-view.tsx`). Both are *value/format previews*, not editors.
- **Presentations** hit `?as=slides` → `office.to_slides` posts the file to the
  service's `/v1/render` (multipart `file` + `dpi` + `pages`), which returns
  per-slide PNGs. The route assembles a JSON manifest of `data:image/png;base64`
  URIs; `slides-view.tsx` shows the current slide big with a thumbnail rail and
  arrow-key / click navigation. The slide images are pre-rendered by LibreOffice,
  so RTL decks come through already shaped.
- **The PDF fallback** is the original path (`?as=pdf` → `office.to_pdf` →
  `/v1/convert`), unchanged, for the office files none of the native renderers
  cover.

## Why a shared service, not bundled LibreOffice

LibreOffice is ~1 GB and used by a minority of turns. Baking it into every agent
image taxes 100% of invocations for a <5% capability and puts soffice cold-start
on the user's path. So the presentation-render and PDF-convert steps live in
**one** deployed service (`office-render`, `https://office-render.cycls.ai`) that
every agent calls over HTTP — the same service that backs the agent's
`render_file` / `convert_file` tools. This SDK ships only the *client*
(`_agent/web/office.py`); the service is its own repo. Spreadsheets and .docx
skip the service entirely — they render from the raw bytes in the browser.

## Configuration

The service-backed paths (presentations, PDF fallback) are on when the agent's
environment carries both:

| Env var                | Meaning                                         |
|------------------------|-------------------------------------------------|
| `OFFICE_RENDER_URL`    | service base URL, e.g. `https://office-render.cycls.ai` |
| `OFFICE_RENDER_SECRET` | shared service secret (Bearer token)            |

Unset either and `office.configured()` is false: `to_pdf` / `to_slides` raise
`Unavailable`, the route answers 415, and those files show the download card —
**no regression.** Spreadsheets and .docx still render (client-side), since they
never call the service. The workspace's `subject` rides along as `X-User-Id` for
attribution/quota (an id, not a credential).

## Caching

The service-rendered outputs are cached in a hidden `.cache/office/` dir under
the workspace root, so a re-open never repays the soffice spawn:

- **Hidden** — the catalog walk skips dot-prefixed entries, so it never appears
  in the file list.
- **Keyed by source path + mtime + size** — an edited document is a fresh cache
  entry (`<hash>-<mtime>-<size>.pdf` for PDFs, `.slides.json` for decks); prior
  renders of the same file are swept on the miss.
- **Best-effort** — on a read-only workspace (e.g. a share mount) the render is
  served from a temp file instead, uncached, so the preview still works.

Spreadsheets and .docx aren't cached server-side — the browser already has the
bytes and parses them locally.

## Which extensions, and why the split

`CONVERTIBLE` and `PRESENTATION` (in `office.py`) are mirrored in `canvas-utils.ts`:

- **Grid** `csv tsv · xls xlsx xlsm ods` — an interactive table beats a static
  PDF for reading and copying data. Trade-off: SheetJS shows **values only** (no
  charts, cell formatting, or formulas) and caps the preview at 300 rows × 50
  columns. Flat-XML `fods` stays on PDF — SheetJS can't read it.
- **Native doc** `docx` only — docx-preview handles OOXML Word; `doc` (old
  binary), `odt`, `rtf`, `fodt` keep the PDF path.
- **Slides** `ppt pptx odp fodp` — the render service opens all of them.
- **PDF fallback** `doc odt rtf fodt fods epub` — the remainder.
- Apple iWork (`pages` / `key` / `numbers`) is absent — LibreOffice can't open it
  reliably, so it keeps its download card.

## Shared Office files

Shared files preview the same way over the token-scoped `/share/.../file/`
transport — `?as=slides` for presentations, `?as=pdf` for the fallback, raw bytes
for spreadsheets and .docx — all read-only.

## Follow-ups

- **Cold start** — the first `?as=slides` / `?as=pdf` on an idle `office-render`
  pays LibreOffice spawn (~1-2s); caching hides it after the first open. A warm LO
  (unoserver) is the service-side upgrade if that ever bites.
- **Big decks** — the slide manifest inlines every slide as a base64 data-URI in
  one response (capped at `_SLIDE_MAX_PAGES`). If very large decks bite, move to a
  lazy per-slide endpoint (`?as=slide&page=N`).

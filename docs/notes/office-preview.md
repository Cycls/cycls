# Office preview on the canvas

Word, PowerPoint and Excel files can't render in a browser. The canvas now
shows them by converting to **PDF on demand** and serving that through the PDF
viewer it already has — so `.docx` / `.pptx` / `.xlsx` (and the ODF and older
binary formats) open in place instead of falling to a download card.

## The shape of it

```
canvas click                     agent web server                office-render
────────────                     ────────────────                ─────────────
GET /files/deck.pptx?as=pdf ──▶  office.convertible? ──▶ cache hit ─▶ serve .pdf
                                        │ miss
                                        └─▶ POST /v1/convert (to=pdf) ──▶ soffice
                                            cache the PDF ◀── PDF bytes ──┘
   ◀────────────── application/pdf (inline) ──────────────────────────────
```

- **Client** (`canvas-utils.ts`, `canvas.tsx`). `isOffice(name)` marks the
  convert-to-PDF class and joins `isRenderable`, so a click opens the canvas.
  `useFileContent` fetches the office doc as `openFile(path + "?as=pdf")` — a
  blob URL of the *rendered PDF* — and `CanvasDoc` runs it through the same
  branch as a native PDF (search / zoom / print, mobile open-in-tab). A failed
  conversion degrades to the download card, never a dead error.
- **Server** (`_agent/web/routers.py`). `?as=pdf` on an Office file returns the
  PDF inline (no `Content-Disposition`, so it renders rather than downloads).
  The office extensions are one `office` kind in `_KINDS`, single-sourced from
  the converter's `CONVERTIBLE` set so labelling and conversion can't drift.
- **Converter client** (`_agent/web/office.py`). A thin client of the shared
  `office-render` service's `/v1/convert` contract (multipart `file` + `to=pdf`,
  service-secret auth). Raises `Unavailable` on any miss so the route can answer
  415 and the client can fall back.

## Why a shared service, not bundled LibreOffice

LibreOffice is ~1 GB and used by a minority of turns. Baking it into every agent
image taxes 100% of invocations for a <5% capability and puts soffice cold-start
on the user's path. So conversion lives in **one** deployed service
(`office-render`, `https://office-render.cycls.ai`) that every agent calls over
HTTP — the same service that backs the agent's `render_file` / `convert_file`
tools. This SDK ships only the *client*; the service is its own repo.

## Configuration

The feature is on when the agent's environment carries both:

| Env var                | Meaning                                         |
|------------------------|-------------------------------------------------|
| `OFFICE_RENDER_URL`    | service base URL, e.g. `https://office-render.cycls.ai` |
| `OFFICE_RENDER_SECRET` | shared service secret (Bearer token)            |

Unset either and `office.configured()` is false: `to_pdf` raises `Unavailable`,
the route answers 415, and Office files show the download card — **exactly the
pre-feature behaviour, no regression.** The workspace's `subject` rides along as
`X-User-Id` for the service's attribution/quota (an id, not a credential).

## Caching

Converting on every open would repay the soffice spawn each time, so the render
is cached in a hidden `.cache/office/` dir under the workspace root:

- **Hidden** — the catalog walk skips dot-prefixed entries, so it never appears
  in the file list.
- **Keyed by source path + mtime + size** — an edited document is a fresh cache
  entry, not a stale hit; prior renders of the same file are swept on the miss.
- **Best-effort** — on a read-only workspace (e.g. a share mount) the PDF is
  served from a temp file instead, uncached, so the preview still works.

## Which extensions

`CONVERTIBLE` (in `office.py`, mirrored in `canvas-utils.ts`):
`doc docx odt rtf fodt · ppt pptx odp fodp · xls xlsx xlsm ods fods · epub`.
Binary spreadsheets moved off the in-browser SheetJS grid onto this PDF path
for layout fidelity (print ranges, charts, merged cells); `csv` / `tsv` stay on
the interactive grid. Apple iWork (`pages` / `key` / `numbers`) is absent —
LibreOffice can't open it reliably, so it keeps its download card.

## Editable Office (Collabora) — on by default when configured

The PDF above is read-only. Editing Word/Excel/PowerPoint on the canvas is **on
by default** and lights up wherever the platform has wired the shared
**Collabora Online** editor — `COLLABORA_URL` + `WOPI_SECRET` in the agent's env
(the office-render pattern: one platform-run service, agents point at it).
Without them Office files keep the PDF preview, so it's always safe.

To force the read-only preview even where the editor is available — a compliance
or intentionally read-only agent — opt out:

```python
web = cycls.Web().auth(cycls.Clerk()).office_edit(False)
```

How it works: the file route mints a per-file, HMAC-signed WOPI token
(`_agent/web/wopi.py`), hands the browser the Collabora editor URL, and Collabora
loads/saves the real workspace file through the agent's own WOPI host endpoints
(`/wopi/files/{id}` — CheckFileInfo / GetFile / PutFile). The heavy editor is one
shared container (see the `collabora-service` deploy bundle), never baked into an
agent image; the SDK only carries the thin WOPI proxy + the canvas editor iframe.

The canvas picks the path per file: `office_edit` on → the Collabora editor;
else the read-only PDF preview; a failed editor falls back to the download card.

## Follow-ups

- **Shared Office files** preview as PDF over the token-scoped `/share/.../file/`
  transport (`?as=pdf`, read-only — shares aren't editable, so no Collabora
  there). The Collabora *editor* remains owner-only.
- **Cold start** — the first call to an idle `office-render` pays LibreOffice
  spawn (~1-2s); caching hides it after the first open. A warm LO (unoserver)
  is the service-side upgrade if that ever bites.
- **WOPI at fleet scale** — handled: edit locks live in the workspace DB (shared
  across instances), and `office_edit` only turns on when a real shared
  `WOPI_SECRET` is set — it refuses to enable on the per-process random fallback,
  so tokens verify across a multi-instance agent.

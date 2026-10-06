# Agent-native design for Cycls agents

**Status: implemented.** A Cycls agent can **create social-media posts and slide
decks** and show them on the canvas — with **no design engine in the agent image**.
The heavy part ([OpenPencil](https://github.com/open-pencil/open-pencil), a
headless vector engine on Skia/CanvasKit) runs **once, in a shared service**; the
SDK ships only a thin client (`cycls/_agent/design`) and the built-in `Design`
tool. Same split as office-render and the browser tool: the heavy dependency lives
in one service, not in every image.

The agent and the human meet at one shared file — `designs/<name>.fig`. The agent
**generates** it (and can **edit** it live), and the human **hand-edits** the same
file in an OpenPencil editor embedded in the canvas — see
[Editing](#editing--the-in-canvas-editor) below.

Enable it by putting `"Design"` in an agent's `allowed_tools` and pointing
`DESIGN_URL` (+ optional `DESIGN_SECRET`) at a deployed `cycls-design` service; set
`DESIGN_EDITOR_URL` too for the in-canvas editor. Validated end-to-end: the client
renders a spec through the service to a 2160² PNG + editable `.fig`; a real Kimi-K3
agent turn chose the tool, wrote a spec, and the post opened on the canvas; a
model-authored 3-slide deck exported to a real `.pptx`; and — with the editor
configured — the human edited that same design in the embedded editor while the
agent's live `edit` changed it under their cursor.

## Why this shape

- **Generate programmatically, NOT from HTML.** OpenPencil's HTML `import` is a
  structural converter, not a browser — in testing it dropped gradients and didn't
  lay out CSS (a 1080² post came back near-blank). The **Figma plugin API** path
  (explicit geometry + fills + fonts) renders faithfully headless. So the service
  compiles a declarative spec to plugin-API calls; it does not import HTML.
- **The engine is heavy and Bun-native.** OpenPencil's CLI uses Bun globals and
  pulls `canvaskit-wasm` (~8 MB); baking that into every agent image would tax
  100% of turns for a <5% capability (the office-render argument). → a **service**.
- **The SDK ships the client; the service is deployed once.** → the office-render
  precedent, reused verbatim.

## Non-goals

- Not bundling a design engine into agent images.
- Not multiplayer co-editing. The agent and human share the `.fig` *file*, not a
  live session: the agent renders/edits it headlessly and over the live `edit`
  bridge, the human hand-edits it in the embedded editor, and both persist to the
  same workspace file. True co-editing (OpenPencil's Yjs CRDT) is a later option.

## Architecture

```
   agent container (tiny)                   shared cycls-design service
   ─────────────────────                    ───────────────────────────
   Design tool + client (httpx)             Bun + OpenPencil (headless,
        │                                    CanvasKit-WASM, no display)
        │  POST /render {spec}  ───────────▶  compile spec → Figma plugin API
        │  POST /eval   {script}             → export png/jpg/webp/svg/pptx
        ▼                                     → return image + editable .fig
   save designs/<name>.<fmt> + .fig ◀────────  (stateless: files live in the
   open_canvas → user sees it                  agent's workspace)
```

## The spec

`render` takes a declarative design; coordinates are pixels from the top-left:

```jsonc
{
  "size": [1080, 1080],
  "fill": { "gradient": ["#4f46e5", "#db2777"], "angle": 135 },  // solid "#hex" or a gradient
  "nodes": [
    { "type": "ellipse", "x": 600, "y": -160, "w": 640, "h": 640,
      "fill": "#ffffff", "opacity": 0.08 },                       // soft flair, bleeds off the edge
    { "type": "text", "text": "NEW RELEASE", "x": 90, "y": 150,
      "font": "Inter Bold", "size": 26, "color": "#ffffff",
      "letterSpacing": 6, "opacity": 0.85 },                      // tracked eyebrow
    { "type": "text", "text": "Design that ships itself.",
      "x": 90, "y": 205, "w": 900,                                // wrap width → auto height
      "font": "Inter Bold", "size": 96, "color": "#ffffff", "lineHeight": 100 },
    { "type": "rect", "x": 90, "y": 780, "w": 340, "h": 100,
      "radius": 50, "fill": "#ffffff",
      "shadow": { "blur": 44, "y": 18, "opacity": 0.28 } },        // pill (radius=h/2) + drop shadow
    { "type": "text", "text": "Try it free", "x": 90, "y": 810, "w": 340,
      "font": "Inter Bold", "size": 36, "color": "#4f46e5", "align": "center" }
  ]
}
```

A **paint** — any `fill`, or a text `color` — is a solid `"#4f46e5"` or a linear
gradient `{ "gradient": ["#a", "#b", …], "angle": deg }` (even stops, or placed
`[["#a",0],["#b",0.6]]`; `angle` 0 = →, 45 = ↘, 90 = ↓ default, 135 = ↙). A colour
may carry alpha as `#rrggbbaa`, so a gradient can fade to transparent — the scrim
that darkens a photo behind text without a hard edge. **Node types**: `text`, `rect`
(`radius`, `stroke`/`strokeWeight`), `ellipse` (a circle when `w == h`), `line` (a
thin divider, `h` defaults to 2), and `image` (below). A shape given `color` but no
`fill` takes it as the fill, as text reads either. Every node also takes `opacity`
(0–1) and `shadow` (`true` or `{ blur, x, y, spread, color, opacity }`), so a
design has depth and overlays, not just flat rectangles. Text opacity is applied
as fill alpha (setting a text node's own opacity collapses its auto-width box).

**Fonts: any Google Font.** A text `font` is a family plus a style —
`"Playfair Display Bold"`, `"Montserrat Extra Bold Italic"` — or `{family, style}`,
with optional `weight` (100–900) and `italic`. The renderer (OpenPencil core) takes
Inter and Noto Naskh Arabic from its bundle and everything else from Google Fonts /
Fontsource at export; the editor in a browser loads the same families from
Fontsource. The service's `fonts.ts` makes that dependable before every render:

- **Parsing.** Style words are peeled off the *end*, so `"Noto Sans"` stays one
  family and `"Black Ops One"` keeps its "Black". (The old builder split at the first
  space — `"Playfair Display Bold"` became family "Playfair" — which is why every
  multi-word family rendered blank and fonts were wrongly believed to be Inter-only.)
- **Figma style names, with spaces.** OpenPencil's `fontName` setter maps only
  `"Semi Bold"` / `"Extra Bold"` / `"Extra Light"`; `"SemiBold"` silently became 400.
  Every resolved style is the spaced form, in the service and the builder.
- **Open twins.** Arial / Helvetica → Arimo, Times → Tinos, Courier → Cousine,
  Georgia → Gelasio, Calibri → Carlito, … (noted to the model).
- **Arabic.** Arabic text keeps an Arabic-capable face (Cairo, Tajawal, Almarai, IBM
  Plex Sans Arabic, Amiri, Noto Kufi Arabic, …); anything else becomes Noto Naskh
  Arabic, since a Latin face would render the Arabic blank in the editor.
- **RTL alignment.** The renderer reads LEFT/RIGHT as start/end in the paragraph's own
  direction, so an Arabic line set `align: "right"` landed on the left. The builder
  swaps the two for a paragraph whose first strong letter is Arabic/Hebrew, so `align`
  means the visual side. (Edit scripts set `textAlignHorizontal` raw — the tool
  description tells the model it follows the text's direction there.)
- **Availability.** Each face is checked with the renderer's own `WebFontResolver`
  (cached per process). A weight the family lacks falls back to its Regular with a
  note; an unknown family is a 422 naming it — never blank text. `/apply` checks the
  fonts an edit leaves on the page the same way.

The service returns `notes` for what it changed; the SDK appends them to the ack.

**The editor draws with the export's fonts.** In a browser the editor fetches a web font
as Fontsource *subset* files registered under one family name, and an Arabic web font
(Cairo, Tajawal…) drew blank there while the export was right (default Arabic — the
bundled Noto Naskh — was fine). The bridge replaces the font manager's remote loader with
one that asks the service's `GET /font` first: one complete file per face, fetched with
the renderer's own resolver — so the editor and the PNG shape text from the same file. It
also drops cached text pictures whenever the font set changes, so text drawn before a
late font arrived re-shapes.

`size` is `[W, H]` or a **preset** the SDK
resolves before the request: `square` 1080², `post-portrait` 1080×1350, `story` /
`reel` 1080×1920, `slide` / `wide` 1920×1080, `x-post` 1600×900, `a4-poster`
1240×1754 (150dpi, so the default @2x render is print-ready 300dpi). An unknown
preset is an error back to the model, never a guessed size. `size` also takes `"1080x1920"`, `{w, h}`, or `width`/`height` on the frame; left out, it is written as the renderer's 1080² default so SDK and service agree.

**Layout guards.** Two silent pile-ups seen on a live prod turn: coordinates quoted as strings (`"y": "1300"`) reach the builder's text clamp as strings, whose bounds check then concatenates and pulls *every* text box to the bottom edge; and a story laid out in a frame left at 1080² gets everything below 1080 clamped to the bottom. So numeric fields (`x y w h size radius lineHeight letterSpacing opacity strokeWeight rotation`) are coerced from `"1500"` / `"96px"` and anything else is an error, and a text or image node that *starts* outside its frame is an error naming the frame size — the clamp is for a box that overruns an edge, not a layout built for another size. (The model had blamed the tool and rebuilt the post in Pillow, losing the editable `.fig`.) The tool description
carries the same vocabulary plus design guidance (hierarchy, tight palette,
margins, depth) so the model produces something intentional, not a wireframe.

**Brand.** When the workspace has a brand kit (`brand/brand.yaml`, the brand-kit
skill's file), `_exec_design` fills what the spec **left out**: a frame `fill` →
the brand primary, a shape `fill` → the accent. It never overrides a value the
model set, and reads only the two colours (flat `primary_color`/`accent_color`,
or the older nested `colors: primary/accent`) with a pattern — the SDK carries no
YAML dependency. Brand fonts (`font_heading`, `font_body`, or nested `fonts:`) fill a text node with no `font` — the heading face at display sizes (≥ 48px), the body face below; a fonts-only kit applies no colours. With a kit present, the ack says what it filled, or flags a design that uses
neither brand colour. Independently of brand, text with no `color` gets white or
near-black by WCAG luminance against its frame's fill, so a forgotten colour is
never black-on-navy.

**Images.** `{ "type": "image", "src": "attachments/photo.jpg", x, y, w?, h?,
"fit"?: "cover" | "contain", radius?, opacity?, shadow?, stroke? }` places a PNG /
JPEG / WebP / GIF that is already in the workspace. Or the model names a photo to
find — `"stock": "coffee beans on wood"` (and `pick` for another result) in place of
`src`, on a node, a deck slide's `image`, a team `photo` or a `replace_image` op:
`design/stock.py` searches Pexels (`PEXELS_API_KEY`), saves the photo to
`attachments/stock/<query>-<id>.jpg`, remembers the query in
`attachments/stock/.index.json` so it's found once, puts the path in as `src` and
credits the photographer in the ack — everything after sees an ordinary workspace
file. Without the key, `stock` is an error asking for a saved photo. `_exec_design` resolves `src`
with `_resolve_path` (no traversal, no reserved dirs; URLs and SVG are errors
naming the fix), reads the pixel size from the file header, and ships the bytes
as base64 inside the spec — the service stays stateless and the `.fig` archives
them, so the editor shows the photo too. `cover` (default) fills the box and
crops; `contain` is done by **geometry** — the box shrinks to the image's aspect
and centres — because the renderer's own FIT scales non-uniformly (upstream bug;
its STRETCH also falls through to FILL, and the `.fig` codec has no CROP). Give
`w`, `h` or both; a missing side follows the aspect. The renderer honours a JPEG's
EXIF rotation, so a quarter-turn (orientation 5–8) swaps the header's width and
height — without that every portrait phone photo would be mis-sized. No imaging
library in the SDK, so no resize: an image over 5 MB, or 8 MB across a design, is
an error asking for a smaller copy. A round avatar is a square image with
`radius = w/2`; a full-bleed photo is an image at 0,0 the frame's size, first in
`nodes`, with a gradient scrim and explicitly light text over it (the automatic
text colour only knows the frame's fill).

**Self-QA.** Every render comes back to the model as an image beside the ack,
with a short rubric — headline dominant, ~8–10% margins, legible text, nothing
overlapping or cut off, exact copy, on-brand — and the instruction to fix anything
off with `edit` (the same design, checked and saved by the service) before
presenting. The image is the service's `preview`: a @1x JPEG of the frame (~50–150
KB) exported beside the render, since a photo-heavy @2x PNG runs several MB and a
PPTX is no image at all. A deck attaches **every** slide's preview (up to 12, each
labelled "Slide N:", within 3 MB), with a rubric that adds consistency across
slides. Against a service without previews it falls back to the render itself when
it is a raster within `read`'s 3 MB. The tool does this rather than a prompt rule: a
"read your render" instruction competing with the tool's own ack gets narrated,
not acted on.

**Decks** are a list of frames — one per slide, all one size:

```jsonc
{ "frames": [ { "size": "slide", "fill": …, "nodes": […],
                "id"?: "cover", "title"?: "Cover", "notes"?: "…", "transition"?: "fade|slide|none" }, … ] }
```

- `format: "pptx"` — one PowerPoint file, a slide per frame. Each slide's speaker
  `notes` and `transition` are written in (OpenPencil's exporter writes neither; the
  service post-processes the file). Text, rects, ellipses and lines stay native and
  editable; **charts and tables are PowerPoint's own** — the builder keeps each one's
  data on its frame, and the export swaps the drawn shapes for a native chart (its
  own chart part and embedded workbook: the data edits in PowerPoint) or a native
  table in the same box (cycls-design `src/native.ts`); right-to-left text keeps its
  side (the exporter's logical alignment is swapped back to PowerPoint's absolute
  one, and the paragraph marked rtl). Gradients, icons, SVG, photos and blurs are
  pictures — one element each, never the whole slide: bleeding plain rects are trimmed
  to the slide, and the slides export unclipped so other bleed hangs off the slide
  and PowerPoint crops it in the show.
- `format: "pdf"` — one page per slide, each the slide's own render (Arabic and web
  fonts exactly as in the PNG), with the slide's words laid over it invisibly — every
  line as the renderer laid it out, in its own embedded font — so they search,
  select and copy; pages are PowerPoint's size (13.333 in wide).
- `format: "png" | "jpg" | "webp"` — a **carousel**: every slide saved as its own
  image, `designs/<name>-slide-1.png`, `-slide-2.png`, …
- Mixed frame sizes are refused (PowerPoint takes the first slide's size and
  letterboxes the rest).

A slide's `id` names its frame; its title, notes and transition ride on the frame
as plugin data in the `.fig`, so they survive edits, reorders and re-exports, and
`inspect` lists them. A multi-frame render also writes `designs/<name>.deck.json` —
`{type: "cycls.deck", version, fig, size, slides, exports, settings?}` — the deck
document the canvas opens to view and present it.

**Decks of layouts** are the normal way to make a presentation. The model fills slots;
the service (`cycls-design/src/layouts.js`) lays them out:

```jsonc
{ "deck": { "theme": "editorial", "footer": { "text": "Brewly · Seed 2026" },
    "slides": [ { "layout": "title", "title": "…", "subtitle": "…", "notes": "…" },
                { "layout": "stats", "title": "…", "items": [ { "value": "3×", "label": "…" } ] },
                { "layout": "custom", "nodes": [ … ] } ] } }
```

Fifteen layouts — title, section, agenda, bullets, two-column, image-left / -right,
image (full-bleed), quote, stats, timeline, table, chart, team, closing — plus `custom`
(hand-built nodes). A slide sent without `layout` gets the one its slots name. Every
content slide shares the title place (titles shrink to fit two lines), margins,
footer and page numbers; hero slides (title, section, closing) take the theme's hero
background and the deck logo. Eight themes (`src/themes.js`) or an override object on
a base; with a brand kit and no theme, the SDK builds a brand theme (`_brand_theme`:
the primary as the hero, the accent where it reads on white, the brand fonts,
`brand/logo.*`). Layouts are drawn left-to-right and mirrored whole for a right-to-left
slide: a slide whose words are two-thirds Arabic is right-to-left, two-thirds Latin
left-to-right, and a bilingual slide (an Arabic headline over English bullets) or one of
only numbers follows the deck's `dir` — the model's, else what most of the deck's words
are. The service returns that `dir` and the deck document keeps it in its settings, so a
slide added or rebuilt later turns the same way as the rest. The SDK
(`_prepare_deck`) resolves image slots — a slide's `image`, a team member's `photo`,
the deck and footer logos — from workspace paths to bytes, and keeps the deck's
settings (images back to paths) in the deck document so a later slide matches. Each
frame keeps its layout `source` (image bytes out), which `inspect` shows. A test
renders a compact deck in every theme and fails on any layout-check finding.

**Slide actions** change a deck's structure on the saved `.fig`, through the
service's `/apply` like an `edit`: `add_slide {slide, at?}`, `update_slide {number,
slide}` (or just `notes` / `title` / `transition`), `move_slide {number, to}`,
`duplicate_slide`, `delete_slide` — slides numbered from 1. A new slide is laid out
with the deck's settings; after any change the slides are re-placed and their page
numbers follow (`relayoutDeck`). Only the touched slides are previewed back to the
model. The result both replays in an open editor (`design_command`) and opens the deck
viewer (`open_canvas`) — a tool's `_ui` may be a list. Changes to one design are
serialized (`design/deck.py` `lock`): the model calls tools in parallel, and two slide
actions in one turn each read the same `.fig` — the later write dropped the other's
change until they queued. The deck viewer's own drag-to-reorder, duplicate and delete
go through `POST /deck/<deck>` and the same code.

## Pages

A design's **pages** are its variants — a post, a story and a banner of one campaign; a
light and a dark version — in one `.fig`. They are OpenPencil's own pages (the editor's
Pages panel), and Cycls works on **one page at a time**, named by its name:

- **Making them.** `render {spec: {pages: [{name, size, fill, nodes}, …]}}` makes one
  design of several pages (`_prepare_pages`: each prepared as a design of its own — its
  own size, a carousel's frames one size); an `edit` adds, copies, renames or removes
  one with the `page_add {name, spec}` / `page_duplicate` / `page_rename` /
  `page_delete` ops; or the person adds one in the editor. A deck of layouts is not a
  page — it is a design of its own, with its deck document.
- **The agent.** `inspect {name, page?}` and `edit {name, page?, ops}` are about one
  page (the first when none is named); a design of several lists them in every
  outline. A render of several pages comes back with every page to look at, each
  labelled, and a layout check whose findings name their page. "Add selection" says
  which page the person is on (`[Selected in designs/x.fig page "Story" › …]`).
- **The files.** One `designs/<name>.fig`. The first page's image is the design's own
  `<name>.<fmt>`; the others are `<name>-page-2.<fmt>`, `-page-3`, … by their place
  (`refresh.page_file`), like a carousel's `-slide-N`. A render of pages writes them
  all; `refresh` keeps them in step: once a design has any page image in a format, each
  page has one (a page added gets its own, one removed loses it — a page with no frame
  has none), and a page's `.pdf` / `.pptx` is re-exported where it exists. A design
  whose pages were all made by hand has none until one is asked for (an export, or an
  agent's page op).
- **The routes.** `?as=slides|pptx|pdf|images|png` take `&page=<name>` — the first page
  without it — cached per page beside the design's other renders (a save drops them
  all); the slides manifest carries `pages: [{name, frames}]` and `page`. A named
  page's download is `<name>-<page>.<ext>`. `POST /design/export {path, format, page?}`
  writes the page's own file (`<name>-page-<n>.<fmt>`). A page that is gone is a 404.
- **The canvas.** The editor says which pages a design has and the one in view (`pages`,
  below); a design opens on the page it was left on (this browser's `localStorage`).
  **Preview** is of the page in view, with the pages as tabs when there are several —
  a tab shows that page and takes the editor to it, so Edit comes back on the same
  page; a page of several frames is its slides, an empty one says so. ⋮ › Download PNG /
  PDF, Export in the editor's menus and a shared design's downloads are all of the page
  in view; a shared design shows its pages the same way.
- **An agent's edit, live.** The `design_command` event carries `page` — the page the
  edit is made on — and the editor shows that page before replaying it. An edit that
  changes the pages themselves is not replayed: the event says `reload`, and the editor
  re-opens the saved file on the page the edit ended on.

## Documents

A **document** is what is read on paper-sized pages and handed over as a PDF: a report,
a proposal, a white paper, a guide, a brochure, a CV. It differs from everything else
the tool makes in one way: nothing is placed. The agent writes **content, in order**, and
the pages make themselves.

- **Making one.** `render {spec: {document: {title, sections: [{title, blocks: […]}],
  …}}}`. A block is `{<kind>: …}` — `lead`, `p` (or a bare string; `**bold**`,
  `*italic*`, `[links](…)`), `h2`, `h3`, `bullets`, `numbered`, `callout`, `quote`,
  `stats`, `chart`, `table`, `image`, `columns`, `cards`, `pairs`, `note`, `nodes` (a
  hand-built area), `break`. `size` is the paper (`a4` by default, `letter`, `a5`,
  `landscape`), `cover.style` is `full`, `band`, `minimal`, `split` (the title on a dark
  panel beside a full-height photo) or `type` (the whole page in the accent), `openers`
  is `plain` or `band` (each section opens on a band of the dark colour), `pages` are hand-built
  full pages, `back` a closing page. The service (cycls-design `document.js` + `flow.js`)
  designs and paginates it: text runs from page to page, a heading never ends a page, a
  figure that doesn't fit waits for the next page while the text after it moves up, a
  long table goes on under its header, and the contents page, running header and page
  numbers are added. Arabic content is laid out right-to-left.
- **The look.** Open, by the user's choice: a theme named in the spec (or one with its
  accent or fonts overridden) stands; with none, the workspace **brand kit** is the
  theme and `brand/logo.*` the logo (`_prepare_document`, as a deck); with no kit, the
  tool description tells the agent to pick a theme that fits the subject.
- **`_prepare_document`.** Reads every image from the workspace wherever it sits — the
  cover's, the logo, an `image` block's (also inside `columns`), a `nodes` area's and a
  hand-built page's — into slots that carry the image's own size (`w`, `h`: the page
  sizes a figure from its shape). `"stock": "<query>"` works as everywhere else.
- **The files.** `designs/<name>.pdf` (the deliverable), `designs/<name>.fig` (its
  pages, editable) and `designs/<name>.deck.json` — a deck document with `kind:
  "document"`, the paper `size`, and `document`: the source as the agent wrote it (paths,
  not image bytes).
- **Changing one.** A small fix on one page — a word, a colour — is an ordinary `edit`
  (ops with `frame`: the page, from 0). Anything that changes the length is made on the
  document itself — **`update_section {name, number, section}`** (just the keys that
  change: `{blocks}` rewrites it, `{title}` renames it), **`add_section {name, section,
  at?}`**, **`move_section {name, number, to}`**, **`delete_section {name, number}`**,
  **`update_document {name, document}`** (its title, theme, cover… — `null` removes a
  key): the SDK changes the kept source (`_exec_document`) and renders it again in place,
  so the model sends the part that changes, not the whole document; `inspect` lists the
  sections by number. Nothing is saved unless the render succeeds. Or the whole
  `render` again with **`replace: true`**: the same name, the earlier `.fig` kept as a
  version (History restores it), and what is open follows — the event list is a
  `design_command` with `reload` (an open editor re-opens the file, the viewer fetches
  its pages) and `open_canvas`. Without `replace`, the same name makes `<name>-2`, as
  any render does. A page edited by hand does not re-flow the pages after it; the
  tool's reply says so.
- **Arguments as text.** Some models hand a large nested argument over as a JSON string;
  `spec`, `ops` and `slide` given that way are read as the object (seen on prod with a
  document's spec — it used to cost a refused call).
- **Hand edits are not laid out over.** A document's pages are made from its source, so
  a re-render (`replace`, or any section action) would drop what was changed on them
  since — by hand in the editor, or by an `edit`. The deck document keeps `rendered`, the
  version of the `.fig` as it was rendered, and a copy of that `.fig` is kept in
  `.cache/design/<hash>.rendered.fig`. Before a re-render the tool compares: same version
  → render. Different → the two saves are outlined with every text whole (`/inspect
  {full}`) and compared (`_edits_since_render`, `_page_changes`): a text's new wording
  (shown from where it parts from the old), the nodes moved or restyled, the ones added or
  removed, page by page. The tool then **does not render** and says so; the model folds
  the wording into what it sends, tells the user what can't be kept, and repeats with
  `discard_edits: true` — the edited pages are kept as a version either way. A save that
  changed nothing (the editor writing the file again) is not an edit; a document with no
  kept copy still holds, without the details; one rendered before `rendered` existed
  renders as before.
- **No cover.** `"cover": false` for a one-page CV, a letter, an invoice, a brief: a
  title block heads page 1 (`kind`, `title`, `subtitle`, `meta`), sections run on under
  compact headings, a single page has no page number, and a few lines too many for the
  page are set a little tighter to fit (cycls-design `document.js` / `flow.js`).
  `"max_pages": N` makes it fit N pages by setting its type smaller, down to 85% — or
  says how much too long it is; an `h2` / `h3` takes `aside` at the end of its line (a
  role's dates); a key a block doesn't read comes back as a note. These exist because a
  real agent's first one-page CV took five renders: it wrote dates in a key nothing read,
  then cut content four times to get back to one page.
- **Richer content.** A `p` takes `aside` (a note in the margin); `[^key]` cites the
  document's `footnotes: {key: text}` (numbered, set at the section's end); `numbering:
  true` numbers figures and tables; links are links in the PDF. A chart or a table can
  read a workspace spreadsheet instead of carrying its data — `"chart": {kind, "from":
  "data/sales.csv", x?, y?: [columns]}`, `"table": {"from": "data/sales.csv", columns?,
  limit?}` (`_sheet` / `_block_data`: `.csv`, `.tsv`, and `.xlsx` when the agent's image
  has openpyxl; the kept source names the file, so a re-render reads it again).
- **From an existing PDF.** `extract {path, name?}` takes a PDF apart to be redesigned
  (`_pdf_parts`, poppler's `pdftotext` and `pdfimages`): its text page by page (capped —
  the Read tool shows the rest) and its pictures — photographs and figures of 200 px or
  more, each once — saved into `designs/<name>-assets/`. The model then writes it as a
  document that uses them. What real PDFs taught it (a two-column paper, a tax form, an
  Arabic declaration made in Word, a scan):
  - **Reading order.** The words are read in reading order. "As laid out" set a
    two-column page's columns side by side on every line and spent most of a page's
    allowance on the gap. A **table**, though, only stays in rows as laid out — so a
    page's tables are found in that reading (`_laid_out_tables`: runs of lines three or
    more cells apart, two of them figures) and added under the page, cells joined by ` | `.
  - **Drawn figures.** A chart or diagram drawn in the PDF is not a picture in it (the
    paper had none to take). `extract {path, page: N}` draws that page for the model to
    look at; with `area: [left, top, width, height]` (parts of the page, 0 to 1) the
    figure is cut out at 200 to the inch, saved as `<name>-assets/figure-<n>.png` and
    shown back to be checked (`_pdf_page`, `pdftoppm`).
  - **Text that can't be trusted.** Arabic saved as the glyphs it was drawn with
    (presentation forms) is put back into letters, the reader's direction marks are
    dropped, and the reply says the wording must be taken from the pages themselves —
    letters come out doubled and lines out of order in such files.
  - **A scan** is said to be one, and its page images are not offered as pictures to
    reuse; its pages are read with `extract {path, page: N}`.
- **QA.** Every page comes back to the model, with the layout check — text sized for
  paper, not a slide — and the service's notes in words: a block taller than a page, a
  page a section left nearly empty. Up to twelve pages come as a preview each. Past
  twelve the tool asks the service for contact sheets (`design.render(…, sheets=True)`):
  the first four pages to read, and every other page small, twelve to a JPEG, each over
  its number — so a 33-page report is seen whole (it was shown its first twelve pages and
  nothing after), for less than twelve previews cost, and renders a quarter faster.
- **Arabic.** A document in Arabic is laid out from the right by the service. Three
  things it does that the agent need not: a phone number, an IBAN's digits or a
  reference like `2026-0412` inside Arabic text is kept reading left to right (the
  direction rules alone drew `0000 000 5 966+`); the items of a contact line stay in the
  order they were given; and a bullet or a table cell that opens with a Latin word
  (`Figma و…`) still reads from the right. The PDF's text copies whole — two letters
  drawn as one glyph are both there — and without the direction marks.
- **The canvas.** The deck document opens the **page viewer** — the deck viewer, told
  `kind: "document"` by the slides manifest: "Pages", **PDF first** in Download, and no
  moving, duplicating or deleting a page (its number and the contents would be wrong).
  Edit opens the pages in the design editor, as for a deck.
- **The PDF.** Real text in its own embedded fonts, A4 (or the paper asked for), a few
  KB a text page, an outline of the sections, a contents page whose rows are links.
  `?as=pdf` on the deck document writes it from the `.fig`, so it is what was last saved.

## Two smaller things

- **A renamed design takes its files with it.** `PATCH /files/<x>.fig` moved the `.fig`
  alone and left its image, its slides' and pages' images, its PDF and its deck document
  under the old name. `refresh.follow` now moves them too (never over a file already
  there) and rewrites the deck document's `fig` / `exports`.
- **A stale token is asked again.** In a tab left in the background the browser
  throttles Clerk's token refresh, and the first request on coming back was a bare
  "HTTP 401". `fetchAuthed` (client `use-auth-headers.ts`, used by `useApi` and the chat
  send) asks once more with a token fetched afresh (`getToken({skipCache: true})`).

## Two channels + the canvas

`_exec_design` (in `_agent/tools`) saves the render to `designs/<name>.<fmt>` and
the editable source to `designs/<name>.fig`, then returns the two-channel result
the loop already understands: the model reads a short ack (plus the render itself,
for self-QA), and the client gets an
`open_canvas` event for the render (the same event the Canvas tool and browser
screenshots use). PNGs render inline; a `.pptx` deck shows in the slide viewer when
office-render is configured, else a download card.

**Decks open in the deck viewer.** A multi-frame render opens its
`designs/<name>.deck.json` (`DeckView`, `client/src/components/deck-view.tsx`): a
filmstrip beside the current slide and its speaker notes, or a grid of every slide;
**Present**; **Download** — the whole deck as PowerPoint or PDF, or every slide as a
PNG in one zip (`<name>-slide-<n>.png`; listed first for a carousel, which is posted
as images), exported on demand; and **Edit**, which swaps in the design editor on the
deck's `.fig`. Its content is
the slide manifest from `GET /files/<deck>?as=slides` — the server resolves the
deck document to its `.fig` (inside the workspace), asks the service's `/slides`
for every slide as a JPEG plus its name / title / notes / transition, and caches the
manifest in `.cache/design/` keyed by the `.fig`'s path + mtime + size, so an edit is
a fresh render. `?as=pptx` / `?as=pdf` / `?as=images` (the zip) / `?as=png` (the first
frame) export the same way; a file share of the deck document serves them all, so a
shared deck presents. An agent `edit` of the deck while the viewer (not the editor)
is open refetches the manifest.

**A design where there is no editor** — a shared page, an examples card, a deployment
without `DESIGN_EDITOR_URL` — shows as what it looks like. The canvas fetches the
`.fig`'s slide manifest (`?as=slides`) instead of its bytes (`useFileContent`'s
`designAsPictures`): one frame is a picture with **Download image** (`?as=png`), several
are the read-only deck viewer. With the design service down it is the download card. `.fig` files are
kind `design` and `.deck.json` kind `deck` in the Files panel, so neither downloads
on click.

**Present mode** (`present-mode.tsx`) is a portal on `document.body` that asks for
real fullscreen: one slide at a time, each entering with its own transition (fade /
slide / none), click or ←/→/Space/PageUp/PageDown/Home/End to move, **N** notes,
**G** grid, **P** a presenter window (current + next slide, notes, a timer — a React
root rendered into the popup from the presenting page, so its buttons drive the deck).
It takes every key in the capture phase, so chat's global Escape — which closes the
whole canvas — never sees the Escape that ends a presentation. (The same rule for
everything else that opens over the canvas — menus, popovers, the version history,
the save-a-copy and conflict dialogs: `hooks/use-escape.ts`. An open layer registers
with `useEscape` and the newest takes the key; chat's own Escape, `useEscapeFallback`,
acts only when no layer and no field did.) ←, ↑, PageUp and Backspace all step back —
from the end screen, to the last slide. Office presentations
(`SlidesView`) present the same way.

**Live polls.** A `poll` slide (`{layout: "poll", question, options}`, 2–6 options)
draws the question, each option over an empty track and a join card — what every
export shows. The service keeps the poll on the frame (plugin data `cycls.poll`: the
question and options, where each track and the join card are — mirrored on an Arabic
slide, whose bars fill from the right — and the colours), `/slides` returns it, and
the manifest carries `polls[i]`. When the deck's owner presents it:

- the slide opens its poll (`POST /polls {deck, slide, question, options}` — a fresh
  session), `poll-overlay.tsx` polls `GET /polls/results` every 1.5 s and fills the
  slide's own tracks (an SVG over the slide in its coordinates, `object-contain` like
  the image, so they line up), with each option's share and count and the total; the
  presenter window lists the counts; **R** restarts it; leaving the slide closes it;
- the join card shows a QR of the deck's **public share link** with `?vote=1` — an
  existing public share of the deck, or, the first time, a button that makes one (no
  link is made without that click);
- a phone on that link gets `AudienceView` (`audience-view.tsx`, anonymous): it
  follows whatever poll is open (`GET /share/<user>/<token>/poll`, every 2 s), votes
  once (`POST …/poll/vote {session, option, voter}` — a random voter id the phone
  keeps), then shows the room's results.

The server runs on several instances, so nothing is pushed or held in memory: each
vote is its own record in the owner's store (`polls/<deck key>/<session>/v/<voter>`),
written create-only — a second vote from the same voter is a 409 — and the tally is
one listing of a session's votes, cached for a second. Votes are throttled per address
(`POLL_VOTES_PER_MINUTE`, per instance); the share's audience check applies, and a
link that isn't a deck has no poll. A shared deck presents its poll slides as drawn
— only the owner runs polls.

## Editing — the in-canvas editor

Generation is half of it. When `DESIGN_EDITOR_URL` is set, a `.fig` on the canvas
opens the **OpenPencil editor embedded in an iframe** (`DesignEditorView`), so the
human edits the exact design the agent rendered. The editor is a static app on its
**own origin** (a patched OpenPencil build, loaded with `?embed=cycls`); the SDK
ships only the small React embed component and threads the `design_editor_url`
config value to it. Two directions meet at the shared `designs/<name>.fig`:

- **Human edits** — the canvas fetches the `.fig` bytes, posts them into the editor
  (`load`), and writes the editor's saved bytes back to the workspace
  (`PUT /files`) after each change. Runs entirely in the browser (CanvasKit/WASM) —
  no service call. The agent picks up the human's edits on its next turn. One editor
  edits **one design** — see "One design, in the workspace" below.
- **Agent edits** — the `edit` action first runs the script on the saved
  `designs/<name>.fig` through the service's `POST /apply` (the same OpenPencil
  plugin API, headless). A script that throws — a node it looks up isn't there —
  is the model's error, verbatim, and nothing changes; a success is written back
  to the `.fig` and its image re-exported (`design/refresh`), whether or not an
  editor is open. Only then does the `design_command` UI event go out: the FE
  relays the script over `postMessage` to the open editor, which *replays* it on
  the live canvas the human is watching (the Super cursor). If that replay fails
  in the browser, the bridge posts `commandError` and the host re-opens the editor
  on the saved file (a fresh fetch — the canvas's copy may predate the edit), so
  a stale document can never auto-save over the agent's change. This replaced a
  fire-and-forget path where a throwing script failed silently in the browser
  (surfacing only as a misleading "Couldn't save" pill), a closed editor dropped
  the edit entirely, and the model said "done" either way. Use `edit` to tweak a
  design ("bigger headline", "make the button green"); use `render` / `script` to
  *create* one.

```
Tool `edit` ──▶ {_ui:{action:"design_command", path, script}}
   │             (two-channel; no render-service call)
   ▼
chat.tsx ──▶ CustomEvent("cycls:design-command") ──▶ DesignEditorView
                                                        │  postMessage
                                                        ▼  (target/source:"cycls-editor")
                              editor iframe (own origin, ?embed=cycls)
                                 load .fig in  ·  apply script live  ·  save .fig back
                                                        │  PUT /files
                                                        ▼
                                         designs/<name>.fig (workspace)
                                                        │  design/refresh (debounced)
                                                        ▼  POST /export {fig, format, width}
                                         designs/<name>.png|…|pptx|pdf (+ -slide-N) re-exported
```

**The image follows the `.fig`.** A render saves `designs/<name>.<fmt>` beside the
`.fig`, but every edit after that — the human's or the agent's `edit`, including a
self-QA fix — lands only in the `.fig`. Left alone, the image goes stale: a
download, a `read`, or a bash `cp` into an email or a deck gets the pre-edit
design. So the `PUT /files` route hands every save to `design/refresh.schedule`,
which, for a `designs/*.fig` (only there — a user's own `logo.fig` + `logo.png`
elsewhere is never touched), re-exports each image **already beside it** through
the service's `POST /export` once the saves go quiet (2 s debounce; the editor
saves in bursts while someone drags, and a newer save cancels an export in
flight). A raster sends its old pixel width, and the service sets the scale to
width ÷ frame width, so a @1x render stays @1x. A deck's `.pptx` / `.pdf` re-exports
whole (notes and transitions come from the `.fig`); a carousel's `-slide-N` images
re-export together, and a slide deleted since loses its image. A design with nothing
beside it — a copy made in the editor, a version opened as a copy — gets `<name>.png`:
a new `.fig` (`?dedupe=1`) and an agent `edit` schedule with `ensure=True`, which
survives the save the editor makes right after opening it; a deck or a carousel keeps
only its own files. Best effort: a failure logs and
leaves the old image — it never fails the save. Eager rather than on-read,
because the sandbox reads the file straight off the volume where no hook can
intercept it. The `edit` ack tells the model the image catches up a few seconds
after the save.

### One design, in the workspace

The editor is a Cycls surface, not a standalone app: it edits the one design the
Cycls tab opened, and everything it makes lands in the workspace.

- **One document per editor.** The bridge binds the document it loads (`host.ts`),
  and every save, export, copy and agent command acts on that one — never on "the
  active tab". The standalone editor's tab bar and Home screen are gone; a second
  `load` replaces the document. Before this, the editor's own "+", File › New or
  Open, or closing its only tab made the next auto-save write *that* document over
  the workspace file.
- **Its pages.** `load` may name the `page` to open on; the editor reports `pages
  {doc, page, pages}` whenever its pages or the one in view change, and shows one on
  `page {name}` (feature `"pages"`). It gives every page a name of its own — Cycls and
  the agent name pages — and a page shown for the first time is fitted to the editor.
- **Saves are confirmed.** Protocol 2: each `load` carries a `doc` tag; the editor's
  `saved {doc, id}` is written to the tab's path and answered with `written {id, ok}`,
  after which the document counts as saved (no dirty dot, no "Leave site?"). A save
  tagged with an older load, or from a file being deleted, is refused. Ctrl+S /
  File › Save save at once; otherwise 1.2 s after an edit stops. An editor from
  before protocol 2 still works: its saves count as done once posted.
- **New design** — the canvas `+` (with size presets: square, portrait, story,
  slide, X post, A4 poster), the Files panel's menu, or File › New design in the
  editor (`newDesign {size}` → the current frame's size). `POST /design/new` renders
  one blank frame through the service and writes `designs/<name>.fig` + `.png`, like
  a render — the refresh keeps the image current and the agent edits it by name.
  It opens in its own Cycls tab. (Ctrl/⌘+N rarely reaches the page: browsers keep it.)
- **Exports and copies go to the workspace.** The editor's exports (File › Export
  selection, the Export panel, Ctrl+Shift+E — PNG, JPG, WebP, SVG, PDF) come to
  Cycls as `export {files}`, one file each, written beside the design as
  `<design>-<export name>` with `PUT /files?dedupe=1`: never over an existing file,
  and never on a name the refresh keeps for the design's own images
  (`refresh.managed`). "Save a copy…" asks for a name and writes a new `.fig` beside
  it, then opens it. No downloads or file pickers from inside the editor.
- **Edit | Preview.** A design open in the canvas has one switch in its header
  (`EditPreviewSwitch`, `deck-view.tsx`): **Edit** is the editor; **Preview** is what the
  design looks like without the editor around it — its picture, or for several frames
  the slides (filmstrip, grid, notes, Present, downloads). Preview saves what's unsaved
  first, then reads the slide manifest (`?as=slides`); the editor stays mounted
  underneath, hidden and inert, so Edit is back at once with nothing reloaded, and an
  agent edit made meanwhile shows in the preview. A deck opened as its `.deck.json` has
  the same switch (it opens on Preview; Edit swaps the editor in).
- **A PDF is made by Cycls.** The editor's own PDF is SVG → jsPDF with no fonts
  embedded, so Arabic and web fonts come out wrong; the design service's is each page's
  own render with a text layer. So File › Export selection › **PDF** (and **Export PDF**
  in the docked pane's menu) sends `exportAs {doc, format}`: the host flushes the
  editor and calls `POST /design/export {path, format: "pdf" | "png"}`, which exports
  the saved file through the service and writes it beside the design — under
  `designs/` as `<name>.pdf`, the design's own image (replaced; the refresh keeps it in
  step from then on), elsewhere under a free name — and a toast offers to open it. The
  canvas ⋮ menu of a design downloads it as **PNG**, **PDF** or the `.fig`
  (`?as=png|pdf`, after a flush), and the no-editor view has both downloads too.
- **Brand kit.** With each `load`, Cycls sends `GET /brand` — the named colours of
  `brand/brand.yaml` (primary, secondary, accent, background, text, neutral; only
  those it names) and its heading/body fonts. The editor adds them as a **Brand**
  variable collection and loads the fonts, so a person editing by hand uses the same
  brand as the agent. Created when missing, and set only when the brand changed since
  the last sync (recorded on the first frame: a `.fig` keeps neither a variable's
  description nor a page's plugin data), so a colour changed by hand stands.
- **Full screen.** The button beside a design's ⋮ puts the editor's own box full
  screen: the same iframe, so nothing reloads and saves go on. The design is fitted to
  the bigger box: when the editor's box changes size by more than 15% (full screen, the
  canvas expanded over the chat) the host posts `fit`, and the editor fits the design
  again unless the person has zoomed or panned since the last fit (an editor that
  lists the `fit` feature; before it the design stayed small in a corner). **Esc leaves
  it**, as on any full-screen page, and an Exit button stays at the top middle the whole
  time — named for the first moments, then a small icon. (It was built with a keyboard
  lock that kept Esc for the editor — hold it to leave — and a button that hid after
  2.5 s behind a thin hover strip: in practice there was no way out.) Toasts show inside it (`data-toasts`), and a
  new design, a copy or an export's Open leaves full screen first, since each opens
  another canvas tab.
- **Switching, closing, renaming, deleting.** A design tab switched away from or
  closed stays mounted, hidden, until its editor has flushed (`flush` → `flushed`, or
  5 s); closing the last tab, hiding the canvas and Close all flush first (up to
  1.5 s), since the canvas goes with them. A renamed or moved file flushes,
  then its tabs follow it; a deleted one stops writing first (a late save would bring
  it back), then its tabs close. Light/dark follows Cycls live (`theme`).
- **No save overwrites what it didn't see** (`cycls/_agent/design/store.py`). A
  design's version is the first 16 hex of the sha256 of its bytes; `GET /files`
  serves a `.fig` with it (`X-Version`, from the bytes served), and every load reads
  it (`host.fetchVersioned`). A save names it (`PUT ?base=`) and gets the new one
  back; a save over a newer file is refused — 412 with the version now, nothing
  written. Every `.fig` write goes through `write_fig` — the editor's saves, the
  agent's `edit` and slide actions (which compare too: a save made while the service
  worked means the edit is applied again, to that save, once), a restore — under a
  short per-file lock, never `deck.lock` (held across the service call, minutes).
  - **An agent edit** is saved on the server first, so a save the editor posted before
    replaying it is expected to be refused: `design_command` carries the edit's
    version, the edits replay one at a time (the next after `applied`), and on
    `applied` the base moves to the edit's version and the refused work is flushed
    again. None is sent before the editor says `loaded` — one that arrived while it
    was loading used to get `commandError: no document is open`, and a second load:
    an edit made before the editor's `ready` is in the file it is about to read;
    of those that arrive while it loads, the one whose version the load read (and
    every one before it) is in the document already, and the rest replay.
  - **Anything else** — another tab, another person, a script — after 3 s (the
    agent's event travels apart from the save's answer) asks: **Load the latest**,
    **Keep mine** (`?force=1`: written over, the other kept as a version), or **Save
    mine as a copy**. Nothing is written while the dialog is open.
  - Known limit: each instance's gcsfuse metadata cache is a window between
    instances no file-level check closes; session affinity keeps a person on one.
- **Version history** (`cycls/_agent/versions.py`). What a write replaces is kept:
  `.versions/<path>/<id>` and one `index.json` (`{id, at, by, reason, intent?, size}`).
  Autosaves keep one per five minutes per file (an editing session's start, then its
  progress); an agent edit, a restore and a keep-mine always keep one; 50 per file,
  30 days. ⋮ › **Version history** lists them by what replaced each ("Before an agent
  edit: move slide 4"); **Restore** saves an open editor first, restores (keeping
  what it replaces — a restore is undone by restoring) and reopens it; **Open as
  copy** makes it a new design. Routes: `GET /versions/<path>` (`?id=` one's bytes),
  `POST /versions/<path>?restore=<id>`. `.versions` is managed by cycls: refused by
  the files routes and the agent's tools, masked in the bash sandbox; a rename
  carries a file's history (copied, where the mount can't rename a directory — gcsfuse;
  a history that can't follow is logged and never fails the rename), a purged trash
  entry ends it. A bash `cp` over a `.fig`
  bypasses it.
- **Add selection.** The editor reports what's selected (`selection {doc, frame,
  nodes:[{name, type, text?}]}`, by name — ids change on save), and the composer
  offers **Add selection** while that design is the visible canvas tab. The chip goes
  with the message (its editor saving first, so the agent reads what the person
  sees): the request's `selection` becomes one "[Selected in designs/x.fig › slide:
  headline (TEXT) "…", …]" block the model reads, stored on the message, which the
  chat shows as a chip instead. Nothing is sent without the button.
- **Arabic.** With Cycls in Arabic the editor's menus and panels are in Arabic
  (`?lang=ar`, then `locale` on every load and on a change; the translation is
  `editor/patches/locales/ar`). The layout stays left to right — the canvas, rulers
  and panels where a designer expects them — and each Arabic label reads right to
  left inside it (`unicode-bidi: plaintext`).
- **What's gone.** The AI chat and its provider keys (Cycls has its own agent), the
  settings dialog, the probe of a local MCP server on every load, collaboration and
  Share, the S3 storage workspace and sync, the library manager, crash-recovery copies
  in the browser, vectorize, the Display-P3 and File-API banners, the service worker,
  the theme and language menus (Cycls sets both), the profiler and dev tools — at the
  source, desktop and the narrow (mobile) layout alike. Kept: the Code tab,
  Variables, Split view.

The embedded editor is a **patched** OpenPencil build: replacements for its app
shell (`main.ts`, `App.vue`, `WorkspaceView.vue`, `pwa.ts`, `aliases.ts`), the
bridge (`cycls-bridge.ts` + `host.ts`), stubs aliased over upstream modules (save,
export, tabs, menus, AI), and exact edits (`edits.json`) — each must match, and the
upstream files they rely on are pinned by hash, so a new OpenPencil version fails
the build until it is reviewed. The patches and build recipe live in
[`design-editor-patch/`](design-editor-patch/) and the handoff note beside it.

## Implementation notes

- **The `.fig` codec renumbers node ids on save.** The builder logs an in-memory
  `__FRAME__<id>` only as a "script ran" sentinel — the service resolves the real
  export id from the *saved* fig via `openpencil find --type frame … --json`, then
  exports `--node <id>` for raster/vector (a `pptx` export is whole-document, so it
  needs no id). Relying on the logged id exported the wrong node.
- **Whole-document pptx = only the design.** The builder drops the scratch base
  doc's pages so a deck's `.pptx` contains exactly the design frames (N frames → N
  slides), not the loadable-base scratch page.
- **OpenPencil 0.14.0 packaging fix.** Every `@open-pencil/*` package's `exports`
  map declares a `bun` condition pointing at unpublished `./src/**/*.ts`; the
  service strips those on install so Bun falls back to the shipped `dist` builds.
- **Nodes join their frame before they're positioned.** OpenPencil's `appendChild`
  keeps a node's page position, so a node placed first and appended after landed
  outside any frame not at the origin — every deck slide after the first rendered
  blank until the builder switched the order (golden `deck.2`).
- **Pixel spacing, radial glows.** `letterSpacing` / `lineHeight` are pixel numbers
  (a Figma-style `{value, unit}` object saved as NaN); a `figma-compat` prelude runs
  ahead of every script — service `eval` and the editor bridge alike — so an agent's
  Figma-style edit works too. Radial gradients take `center` + `radius`.
- The service keeps a registry of every OpenPencil quirk, its guard and the test that
  pins it: `cycls-design/docs/quirks.md`. Goldens (Linux renders) cover each one.
- **Stacks and the layout check.** The service measures text while the builder runs
  (one `job.ts` process per render), so a `stack` node lays its children out from
  their real sizes — the model no longer guesses y for wrapped text. A stack of text,
  shapes and photos is an auto-layout frame named after its `id` (the builder still
  places each child itself, and the layout lands them on the same pixels): it moves
  as one in the editor, a line typed longer pushes the rest down, `move`/`duplicate`
  take the stack's id, and a child moved on its own leaves it. A stack holding a
  frame — a list, icon, chart, table, QR or another stack — is laid out as separate
  nodes, because after a load OpenPencil keeps a frame child where it was saved while
  the text around it reflows (quirks #27); and every save drops the loaded file's copy
  of the auto-layout fields, which the .fig writer would otherwise write back over an
  edit (#28 — the service before a save, the editor bridge on `save`). Every render
  returns `lint` (overlapping text, off/crowded edges, too-small text, low contrast on
  what's behind it); `_exec_design` turns it into the ack's "Layout check" line, next
  to the QA image. Nodes carry names from the spec's `id`.
- **Edits by name.** `inspect` returns a design's outline (frames, named nodes with
  box/text/font/colour); `edit` takes `ops` — set_text, style, move, resize, delete,
  duplicate, replace_image, add, and background (the slide's own fill: a slide isn't a
  node `style` can name) — which the service compiles with the builder's own
  code and applies to the saved .fig. The reply's compiled script is what the live
  editor replays (`design_command`), so both copies change identically; the edited
  design comes back to the model with a layout check. A raw `script` still works as
  the escape hatch.
- **More primitives, bigger photos.** icon (Iconify), svg (a file or markup), qr,
  line (from/to, arrowheads), list, chart (column/bar/stacked/line/area/pie/donut),
  table, rich-text `runs`, blur / backdropBlur, image `shape`/`focus`/`crop`. The
  service's job prepares them (fits photos to their box, fetches icons, draws QR/SVG
  as paths), so photos up to 15 MB each / 20 MB per render go through.

## Configuration

| Env                 | Meaning                                                     |
|---------------------|-------------------------------------------------------------|
| `DESIGN_URL`        | render-service base URL, e.g. `https://cycls-design.cycls.ai`. Gates the whole `Design` tool. |
| `DESIGN_SECRET`     | shared render-service secret (Bearer). A local dev instance may run open; the deployed service requires it (its `deploy.py` refuses to deploy without one, since the render API runs caller-written scripts). |
| `DESIGN_EDITOR_URL` | the embedded editor's own origin (a static OpenPencil build). Injected into `/config` as `design_editor_url`. Unset → `.fig` files show the download card and there is no open editor for `edit` to drive; generation (`render` / `script`) is unaffected. |

Unset `DESIGN_URL` and `design.configured()` is false: the `Design` tool is never
offered and the feature is simply absent — **no regression**, exactly the
office-render / browser behaviour. (The tool is gated on the render service, so an
agent can call `edit` whenever `DESIGN_URL` is set; without `DESIGN_EDITOR_URL`
there is simply no open editor for the command to reach.)

## The service

Lives in its own repo (`cycls-design`), deployed once — the SDK ships only the
client. It's a Bun HTTP server wrapping the OpenPencil headless CLI:

- `GET  /health`
- `POST /render { spec, format?, scale?, preview?, every? }` — the primary, safe path (declarative)
- `POST /eval   { script, format?, scale? }` — a raw Figma-API escape hatch
- `POST /apply  { fig, ops | script, preview? }` — an edit, checked and applied headless
- `POST /inspect { fig }` — the outline: frames (with title / notes / transition) and named nodes
- `POST /export { fig, format?, scale?, width?, every? }` — re-export an edited `.fig`
- `POST /slides { fig, scale?, format? }` — every slide's image, size and metadata (the deck viewer)

A render returns `{ ok, frameId, frames, format, image_base64, fig_base64, slides,
lint, notes? }` plus `preview_base64` / `previews_base64` (a @1x JPEG of the first /
every frame) when asked and `images_base64` (every frame) with `every`. It's
stateless (state is the caller's workspace), so it scales horizontally.

It guards itself (`cycls-design/src/guard.ts`): 30 MB per request; 100 frames, 1500
nodes, 5000 characters per text; caller-written scripts (`script`, `edit`) parsed and
screened to the `figma` API; a per-user rate limit (429 + retry-after, which the
client turns into a sentence); and the engine's child process gets no secrets and 90 s
per step.

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
JPEG / WebP / GIF that is already in the workspace. `_exec_design` resolves `src`
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
off (with `edit` when the editor is wired, else a fresh render) before presenting.
The image is the service's `preview`: a @1x JPEG of the first frame (~50–150 KB)
exported beside the render, since a photo-heavy @2x PNG runs several MB and a deck
has no image of its own — so a deck is QA'd on its first slide. Against a service
without previews it falls back to the render itself when it is a raster within
`read`'s 3 MB. The tool does this rather than a prompt rule: a "read your render"
instruction competing with the tool's own ack gets narrated, not acted on.

**Decks** are a list of frames — one per slide — exported as PowerPoint:

```jsonc
{ "frames": [ { "size": [1920,1080], "fill": …, "nodes": […] }, … ] }   // format: "pptx"
```

Each top-level frame becomes a slide. The `.fig` holds the whole deck, editable.

## Two channels + the canvas

`_exec_design` (in `_agent/tools`) saves the render to `designs/<name>.<fmt>` and
the editable source to `designs/<name>.fig`, then returns the two-channel result
the loop already understands: the model reads a short ack (plus the render itself,
for self-QA), and the client gets an
`open_canvas` event for the render (the same event the Canvas tool and browser
screenshots use). PNGs render inline; a `.pptx` deck shows in the slide viewer when
office-render is configured, else a download card.

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
  no service call. The agent picks up the human's edits on its next turn.
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
                                         designs/<name>.png|jpg|webp|svg|pptx re-exported
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
width ÷ frame width, so a @1x render stays @1x. Best effort: a failure logs and
leaves the old image — it never fails the save. Eager rather than on-read,
because the sandbox reads the file straight off the volume where no hook can
intercept it. The `edit` ack tells the model the image catches up a few seconds
after the save.

The embedded editor is a **patched** OpenPencil fork (three source patches +
forcing synchronous `.fig` compression so the in-page save doesn't hang on the
export web-worker). The patches and build recipe live in
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

## Configuration

| Env                 | Meaning                                                     |
|---------------------|-------------------------------------------------------------|
| `DESIGN_URL`        | render-service base URL, e.g. `https://cycls-design.cycls.ai`. Gates the whole `Design` tool. |
| `DESIGN_SECRET`     | shared render-service secret (Bearer). Optional — a local dev instance may run open; a deployed service sets one and rejects calls without it. |
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
- `POST /render { spec, format?, scale? }` — the primary, safe path (declarative)
- `POST /eval   { script, format?, scale? }` — a raw Figma-API escape hatch

Both return `{ ok, frameId, frames, format, image_base64, fig_base64 }`. It's
stateless (state is the caller's workspace), so it scales horizontally.

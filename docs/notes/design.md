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
gradient `{ "gradient": ["#a", "#b", …], "angle": deg }` (even stops; `angle`
0 = →, 45 = ↘, 90 = ↓ default, 135 = ↙). **Node types**: `text`, `rect`
(`radius`, `stroke`/`strokeWeight`), `ellipse` (a circle when `w == h`), and
`line` (a thin divider, `h` defaults to 2). Every node also takes `opacity`
(0–1) and `shadow` (`true` or `{ blur, x, y, spread, color, opacity }`), so a
design has depth and overlays, not just flat rectangles. Text opacity is applied
as fill alpha (setting a text node's own opacity collapses its auto-width box).

Fonts available headless: **Inter**, **Arial**. Common sizes: 1080×1080 (square
post), 1080×1920 (story), 1920×1080 (slide). The tool description carries the
same vocabulary plus design guidance (hierarchy, tight palette, margins, depth)
so the model produces something intentional, not a wireframe.

**Decks** are a list of frames — one per slide — exported as PowerPoint:

```jsonc
{ "frames": [ { "size": [1920,1080], "fill": …, "nodes": […] }, … ] }   // format: "pptx"
```

Each top-level frame becomes a slide. The `.fig` holds the whole deck, editable.

## Two channels + the canvas

`_exec_design` (in `_agent/tools`) saves the render to `designs/<name>.<fmt>` and
the editable source to `designs/<name>.fig`, then returns the two-channel result
the loop already understands: the model reads a short ack, and the client gets an
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
- **Agent edits live** — the `edit` action returns *instantly* (no render-service
  call) with a `design_command` UI event. The FE relays the Figma-plugin-API
  `script` over `postMessage` to the open editor, which applies it to the live
  canvas the human is watching; the same auto-save persists it. Use `edit` to tweak
  an open design ("bigger headline", "make the button green"); use `render` /
  `script` to *create* one.

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
```

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

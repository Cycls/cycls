# Agent-native design for Cycls agents

**Status: implemented.** A Cycls agent can **create social-media posts and slide
decks** and show them on the canvas — with **no design engine in the agent image**.
The heavy part ([OpenPencil](https://github.com/open-pencil/open-pencil), a
headless vector engine on Skia/CanvasKit) runs **once, in a shared service**; the
SDK ships only a thin client (`cycls/_agent/design`) and the built-in `Design`
tool. Same split as office-render and the browser tool: the heavy dependency lives
in one service, not in every image.

Enable it by putting `"Design"` in an agent's `allowed_tools` and pointing
`DESIGN_URL` (+ optional `DESIGN_SECRET`) at a deployed `cycls-design` service.
Validated end-to-end: the client renders a spec through the service to a 2160²
PNG + editable `.fig`; a real Kimi-K3 agent turn chose the tool, wrote a spec, and
the post opened on the canvas; and a model-authored 3-slide deck exported to a real
`.pptx`.

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
- Not a human drag-and-drop editor (Path A: the agent designs, the human
  art-directs in chat). A canvas mini-app editor over the same `.fig` is a possible
  later addition (Path B).

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
  "size": [1080, 1080],          // frame size
  "fill": "#0f172a",             // hex background (omit for none)
  "nodes": [
    { "type": "text", "text": "Agents that design.",
      "x": 96, "y": 360, "w": 888,          // give multi-word text a wrap width
      "font": "Inter Bold", "size": 96, "color": "#ffffff", "lineHeight": 100 },
    { "type": "rect", "x": 96, "y": 760, "w": 320, "h": 96,
      "radius": 14, "fill": "#3b82f6" }
  ]
}
```

Fonts available headless: **Inter**, **Arial**. Common sizes: 1080×1080 (square
post), 1080×1920 (story), 1920×1080 (slide).

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

| Env            | Meaning                                                          |
|----------------|------------------------------------------------------------------|
| `DESIGN_URL`   | service base URL, e.g. `https://cycls-design.cycls.ai`           |
| `DESIGN_SECRET`| shared service secret (Bearer). Optional — a local dev instance may run open; a deployed service sets one and rejects calls without it. |

Unset `DESIGN_URL` and `design.configured()` is false: the `Design` tool is never
offered and the feature is simply absent — **no regression**, exactly the
office-render / browser behaviour.

## The service

Lives in its own repo (`cycls-design`), deployed once — the SDK ships only the
client. It's a Bun HTTP server wrapping the OpenPencil headless CLI:

- `GET  /health`
- `POST /render { spec, format?, scale? }` — the primary, safe path (declarative)
- `POST /eval   { script, format?, scale? }` — a raw Figma-API escape hatch

Both return `{ ok, frameId, frames, format, image_base64, fig_base64 }`. It's
stateless (state is the caller's workspace), so it scales horizontally.

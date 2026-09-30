# cycls-render

Headless Blender as a Cycls function: send a scene config, get back a studio
render (PNG), a small JPEG preview and the object as a `.glb`.

```
agent tool ──cycls.remote("cycls-render")(config)──▶ render(config)  [cpu=8, 8Gi, 1 render per instance]
     ▲                                                     │ blender -b -P scenes.py (Cycles, CPU + OIDN)
     └──────────── {png, preview, glb, config, timings} ◀──┘
```

The box is **stateless**: no volume, no secrets. The caller decides where the
bytes live (the example agent writes them into the user's workspace and opens
the PNG on the canvas). That's also what makes a future "agent writes its own
bpy" option safe to add: there's nothing on this box to steal.

## Files

| File | What |
|---|---|
| `scenes.py` | The bpy scene builder, plus `normalize()`, which validates a config. It has no module-level `bpy` import, so it also runs outside Blender. |
| `render_fn.py` | The `@cycls.function` that installs the official Blender LTS tarball in the image, runs `scenes.py` in a subprocess, and returns the bytes. |
| `try.py` | The dev loop: `python try.py local <shot>` (Docker) or `python try.py remote <shot>` / `remote bench`. |
| `worker.py` | The warm Blender worker for Studio ops: jobs in on stdin as job directories, answers on a dedicated fd, recycled after 100 jobs and after any `script`/`import`. |
| `studio_bpy.py` | Studio's Blender side: the scene document to bpy and back, and the ops (`evaluate`, `apply`, `snapshot`, `render`, `export`, `script`, `import`, `selftest`). |
| `studio_try.py` | Studio's dev loop: `PYTHONPATH=<sdk> python studio_try.py dev apply …` runs the current code on a cloud executor, `remote` the deployment. |
| `spikes/` | Phase-0 spikes and `FINDINGS.md` (WebGL in the sandboxed frame, the warm worker, fidelity). |

## Studio ops

`render(op=…, scene=…, blobs=…, params=…)` serves the SDK's Studio (a Blender-style app in the
workspace plus the `studio` tool); with no `op` it is the product-shot renderer below, unchanged.
The ops, the sandbox (unshare + bwrap, uid 65534, `-Y`) and the protocol are documented in the SDK
at `docs/notes/studio.md`. The document schema is the SDK's `cycls/_agent/studio/scene.py`,
captured by value at deploy, so deploy with the SDK checkout on `PYTHONPATH`.

## Config

Every field is optional:

```json
{
  "object": "torus",
  "text": "CYCLS",
  "material": "gold",
  "backdrop": "#1b1b1f",
  "lighting": "studio-3point",
  "camera": "front-3/4",
  "resolution": [1280, 720],
  "samples": 32,
  "glb": true
}
```

| Field | Values |
|---|---|
| `object` | `sphere`, `ico-sphere`, `cube`, `rounded-cube`, `torus`, `cylinder`, `cone`, `monkey`, `text` |
| `text` | The word to extrude when `object` is `text`. Latin script only (Blender doesn't shape Arabic), at most 24 characters. |
| `material` | A preset: `gold`, `brushed-gold`, `chrome`, `brushed-steel`, `copper`, `plastic`, `matte`, `ceramic`, `glass`, `rubber`, `neon`. Or `{preset, color, metallic, roughness, coat, transmission, ior, emission}`; `color` is hex or `[r,g,b]` in sRGB. |
| `backdrop` | Hex color of the studio sweep. Defaults to light grey, or near-black for the dark rigs (`dramatic`, `rim`). |
| `lighting` | `studio-3point`, `softbox`, `dramatic`, `rim` |
| `camera` | An angle: `front`, `front-3/4`, `side`, `top`, `low`, `hero` (85mm with depth of field). Or `{angle, focal_mm}`. |
| `resolution` | `[w, h]`. Each side 64–2048, at most 1920×1080 pixels in total. |
| `samples` | 1–256 (default 32). The OpenImageDenoise denoiser is always on. |

The plan's original example also passes validation: `preset: "product-shot"`,
`engine: "CYCLES"`, and a material dict with `base_color`. A bad config comes
back as `{"ok": false, "error": "<which field, why>"}` before Blender starts.

## Deploy

```bash
PYTHONPATH=../.. cycls deploy render_fn.py   # from services/render, Python 3.12 → https://cycls-render.cycls.ai
python try.py remote torus-gold
```

Calling it needs `CYCLS_API_KEY`: `cycls.remote` derives a per-deployment
token from it. `max_instances` is capped at 4 in `render_fn.py`.

## Benchmark

Deployed, `cpu=8` (8 render threads), measured 2026-09-28 with a gold torus on the
studio-3point rig and the OIDN denoiser on. Command: `python try.py remote bench`.

| Resolution | Samples | Blender render | Whole call | Wall (from Egypt) |
|---|---|---|---|---|
| 1280×720 | 32 | 30s | 36s | 39s |
| 1280×720 | 64 | 52s | 58s | 62s |
| 1280×720 | 128 | 76s | 82s | 84s |
| 1920×1080 | 32 | 51s | 59s | 63s |
| 1920×1080 | 64 | 114s | 116s | 118s |
| 1920×1080 | 128 | 183s | 184s | 186s |

- Render time grows about linearly with samples and pixels.
- Each call adds about 6s on top: Blender boot, scene build, preview and glTF export.
- At 720p, 32 denoised samples look the same as 128 (compared side by side), so **the
  default is 1280×720 at 32 samples, about 40s per call**. The caps are 1920×1080 pixels
  and 256 samples.
- Cold start on the ~1.5 GB image was a few seconds; the gap between wall time and
  whole-call time stayed at 2–4s.
- A local Docker build pulls the 383 MB tarball. On a slow link that took over 30
  minutes, so do look-dev with `python try.py dev …`. That runs the current `scenes.py`
  on a cloud executor with the same spec, four shots in parallel.

## Look-dev notes

- **Color:** the view transform is **Khronos PBR Neutral**. AgX pushed saturated golds
  toward olive.
- **Neon:** emission above ~2 tone-maps to white.
- **Dark rigs** (`dramatic`, `rim`): keep the back lights high (50°+) and small. Low
  back lights flood the floor beside the object.
- **Glass and chrome** mirror what surrounds them. On the light default backdrop they
  read washed out, so give them a dark or colored `backdrop`.

## Not yet

- **More presets** for the product-shot path (Studio's `script` and `import` cover the rest).
- **Animation.** Frame sequences need a real job model, and Cloud Run throttles CPU
  once the response is sent, so they can't run as background work.

# Studio

A Blender-shaped 3D environment that lives in the workspace as a mini-app, with real Blender as
its engine. The agent builds a scene in chat; the person opens it, moves things, edits meshes and
presses Render; both are working on one file. Chat comes first — someone who has never opened a
3D tool gets a product shot from a sentence — and the app is there for whoever wants their hands on it.

It is not a streamed Blender desktop. There are no GPUs to stream from, a desktop needs a VM per
person, and a sandboxed frame can't host one. The split instead: the browser draws (three.js, on the
person's own GPU) and does what's cheap and interactive; Blender, in the cloud, does what only
Blender does right — modifiers, booleans, bevels, scripts, import/export and the Cycles render.

## The pieces

```
Studio app  apps/studio/index.html — Preact + three.js, one inlined file, its own CSP (connect-src 'none')
  │ cycls.read/write     data/scene.json, data/meshes/m-*.json          (the file bridge, unchanged)
  │ cycls.engine(op, …)  → host → POST /apps/studio/engine               (viewer's JWT)
  │ cycls.onCommand(fn)  ← host ← "cycls:app-command" ← chat ← the tool's _ui app_command
  │ cycls.me.set("view") → the .apps shelf → the tool reads the selection
  ▼
Agent server (SDK)  cycls/_agent/studio/
  scene.py    the document: schema, normalize, ops, diff/patch/merge3, layout checks — stdlib only
  tool.py     the `studio` tool (actions below) · route.py  the app's engine route
  store.py    scene.json under a lock, rev, history, mesh files · engine.py  the cycls.remote client
  install.py  puts the app in the workspace and keeps it current · app/index.html  the built bundle
  ▼ cycls.remote(CYCLS_STUDIO_ENGINE)(op=…, scene=…, blobs=…, params=…)
cycls-render  (its own folder, like cycls-design) — a warm Blender worker behind unshare + bwrap
```

The app's source is `studio/` at the repo root (`npm run build` writes the bundle into
`cycls/_agent/studio/app/index.html`, refusing past 1.2 MB). The engine lives outside the repo,
in `cycls-render`; at deploy it captures `scene.py`'s source from the installed SDK by value, so
the schema has one source and the engine can't drift from it.

## The document

`apps/studio/data/scene.json`, format `cycls.studio.scene` v2. Blender's conventions, so an agent
that knows bpy reads it on sight: Z up, metres, angles in degrees (Euler XYZ — three.js's `'ZYX'`),
colours sRGB hex (linear only at the edges), bpy field names (`energy`, `lens`, `levels`,
`segments`). `objects`, `meshes` and `materials` are maps keyed by stable id; `world` and `render`
are single entries; `rev` counts saves and `by` says whose (`agent` or `app:<session>`).
A mesh or text object has material **slots**, `materials: [id|null, …]`, and a face's
`material_index` (in its mesh file) picks one — Blender's model; a face past the last slot uses the
last. Version 1 had one `material`; a v1 document reads as v2 (it becomes slot 0) in `scene.py`'s
`migrate` and in the app's `bridge.readScene`, so an older scene or an open older tab merge cleanly.
Ops still take `material` as slot 0; `material {assign, slot}` sets another.

The file on disk is always normalized — every key present, defaults filled — and the app's
`make.*` builds entries in exactly that shape from `schema.json` (generated from `scene.py`; a
test fails if it drifts). That is what lets a save that changed nothing compare equal.

A mesh is either a **primitive** (Blender's operator parameters: `cube {size}`, `torus
{major_radius, minor_radius, …}`, …, plus `cyclorama` for photo sweeps) or **explicit**:
`{data: "meshes/m-<12 hex>.json", verts, faces, bbox}`. The sidecar is `cycls.mesh` v1 — base64
`co` (f32), `loop_start` and `loops` (u32, so n-gons survive), `smooth` (u8 per face), optional
`uv` (per corner), `material_index` (u16 per face) and `loose_edges`. It is named by its content —
everything it holds, UVs included — and never rewritten, which makes it its own cache key and makes
undo a pointer swap. The bridge carries text only, hence base64. Primitives get Blender's own UVs
(the Add operators' `calc_uvs`; hand-made grids for the torus and the cyclorama).

**Images.** `textures` is a map too: `{name, data: "textures/t-<12 hex>.json", width, height,
alpha}`. The file is a `cycls.texture` — `{media_type (PNG or JPEG), width, height, data: base64}`,
named by the image's sha256, at most 2048 px a side. A material names images by id in
`base_color_texture` (its transparency drives alpha when it has any), `roughness_texture` and
`normal_texture` (+ `normal_strength`), placed on the UVs as Blender's Mapping node places them:
`uv' = texture_offset + rotate(texture_rotation) · (texture_scale · uv)`. An image no material uses is
dropped at the end of an edit; a preset keeps a material's images.

Next to it: `data/history/<rev>.json` (the last 20 scenes an agent edit replaced — `revert` reads
them), `data/renders.json` (every render, newest last), `data/errors.json` (what the app caught;
the host's console can't see into the frame).

## One file, three writers

The agent (the tool, under a per-file asyncio lock), the app (over the bridge) and, now and then,
`edit`/`bash` all write `scene.json`. No real-time multiplayer — one person and their agent.

- **Agent writes** load, apply ops, normalize, bump `rev`, keep the replaced scene in history,
  then push `{type: "patch", base, rev, label, set, delete}` to the open app as an `app_command`.
- **The app** keeps `base` (the last scene it knows the disk had). A patch whose `base` matches is
  applied to `base` and three-way merged into the local document entry by entry: changed only
  there → take theirs; only here → keep ours; both → keep ours and say so in a toast. A patch it
  can't place (it missed one) and the turn's end (`turn_end`, broadcast to every open app) re-read
  the disk and merge the same way. An agent change is one undo step, "Agent: …".
- **An app save** re-reads the disk first and merges anything *newer* than its base — strictly
  newer: a stale read must never revert the agent. It writes `rev = max(disk, ours) + 1`.
- **Mesh files are written before the scene that names them**, and before any engine call (the
  route reads them from disk), so neither ever points at a file that isn't there yet.
- Files are swept, not deleted on the spot: a save deletes mesh files that neither the scene nor
  its history uses once they're a day old — an open app may be holding younger ones in its undo.

`studio/tests/app.test.js` is the merge contract: local edits plus an agent patch lose nothing on
screen or on disk; a conflict keeps the person's version and warns; a missed patch and a stale disk
both come out right.

## The engine

`render(config=None, *, op=None, scene=None, blobs=None, params=None)` in cycls-render. With no
`op` it is the original product-shot renderer, byte for byte. With one:

| op | who | what |
|---|---|---|
| `evaluate` | app, agent | display meshes after modifiers (per-loop positions/normals, triangles) |
| `apply` | app, agent | `modifier_apply {index}`, `convert`, `join {others}`, `remesh`, `decimate`, `boolean`, and on a selection: `bevel`, `inset`, `subdivide`, `triangulate`, `merge_by_distance`, `recalc_normals`, `uv {method: cube\|cylinder\|sphere\|reset}`, `assign {slot}` (faces → a material slot), `connect {verts}` (an edge between two vertices, splitting the faces between them); a join answers with the merged slots |
| `snapshot` | app, agent | ~640×360, few samples, ~5 s — for checking work |
| `render` | app, agent | the Cycles render, PBR Neutral, denoised |
| `export` | app, agent | glb, blend, fbx, obj, stl |
| `script` | agent | bpy against the scene; what comes back is read, not trusted |
| `import` | agent | glb, gltf, obj, fbx, stl, ply, blend — packed images come along as textures |
| `texture` | agent | an uploaded image Blender can read → PNG/JPEG ≤ 2048 px (a fresh sandboxed worker, like import) |

Images go up only with the ops that draw or read materials back (snapshot, render, export, script),
as the bytes of `textures/t-<hash>.png|jpg`; `build` wires Image → Mapping → UV into the Principled
inputs (roughness and normal images Non-Color), and `to_doc` reads such wiring back instead of
flattening it — a glb's packed images pass through as their own bytes, never through the view
transform.

A selection is `"all"`, `{faces: [i]}`, `{edges: [[a, b]]}` or `{verts: [i]}` — indices into the
object's explicit mesh. `bevel`, `inset` and `subdivide` answer with a `selection` too — what
Blender leaves selected (the bevel's faces, the inset's inner faces, the subdivided edges), as
indices into the mesh they return.

**The warm worker.** The deployed shim unpickles the function once per process, so a Blender
process started in one call is still there for the next (`sys._cycls_blender`). Jobs go in on
stdin as job directories; answers come back on a dedicated fd, as JSON and raw files — never a
pickle built from Blender's output, because the agent server unpickles the reply while holding
secrets. Boot ~1 s; a warm `evaluate` is ~7 ms in Blender and ~0.5 s end to end. The worker is
replaced after 100 jobs, when its code changes, and after every `script`/`import`.

**The sandbox.** The runtime is gVisor, where bwrap can't make a network namespace, so Blender
runs under `unshare --net` wrapped around bwrap: its own pid/ipc/uts namespaces, uid 65534, a
read-only root, `/app` masked, `--new-session`, and `-Y` so a `.blend` can't auto-run its own
scripts. A `script` or `import` gets a fresh
worker that can see only its own job directory and is killed after. With no sandbox available the
engine refuses those two ops rather than run them bare.

**Limits.** 100 MB of meshes and images per scene (the engine takes 110 MB in, 160 MB out — an
import's meshes come back base64), 100 MB per imported file, per-op timeouts, `max_instances=4` (a cost ceiling, shared by
everyone). Busy (429/503) reaches the person as "the Studio engine is busy". A call's timeout grows
with what it uploads (~4 s a megabyte), for an agent on a slow uplink. Files of 256 KB or more go up
gzip'd when that saves 10% (`engine.pack`; the engine unpacks, capped at its 110 MB) and big
outputs come back the same way (`gzip=True`): lossless — a .blend saved uncompressed is ~27%
of itself, mesh files well under half; images and a compressed .blend go as they are. The
engine deploys first: an older one refuses `.gz` names.

**Big scenes.** Up to 10,000 objects — a kitbashed venue is thousands of objects sharing a few
hundred meshes. What scales with them: the model's summary lists the selection and the top level
(80 rows) and counts the rest; the floating-object check skips scenes of over 300 parts; the
outliner draws only the rows in view; mesh files arriving in a burst reach the viewport in one
sync; past 300 meshes, objects sharing geometry and materials draw as one InstancedMesh (the
browser's cost is per draw call — the venue went from 4,456 calls a frame to 636), with what's
selected, edited, hidden or see-through drawn on its own and clicks still hitting each object;
materials are one per material, not per object; identical modified objects are shaped by Blender
once (40 a call, carrying only their meshes) and share the result; undo keeps 16 steps past 1,000 objects; and flat, wide objects (a site's terrain) count as
ground — not framed or lit for. An import hides volume-only objects (haze, fog), which as a
surface would box everything in.

## The app's route

`POST /apps/studio/engine`, mounted only when Studio is configured. It answers 404 unless the slug
is `studio` **and** `app.json` carries the installer's stamp — a hand-written app at that path gets
nothing. It allows the app ops only (never `script` or `import`), normalizes the scene it's sent,
and resolves mesh files only from the app's own `data/meshes/`. Budgets per subject: 60 calls a
minute, 30 renders an hour, one render at a time. It saves what the engine made — `renders/*.png`
plus the log, mesh files, `exports/*` — before answering, so a tab closed mid-render loses nothing.
One op never reaches the engine: `open {path}` answers `{open: path}` for a render the log lists or
a file under `exports/`, and the host bridge opens it on the canvas (the Renders list, the preview's
Open).

## The app

Preact and three.js core with its add-ons (OrbitControls, TransformControls, RectAreaLight),
hand-written CSS in Blender's dark theme, no WASM, no workers. Everything is inlined into one file
under a CSP meta of its own (`default-src 'none'`, `connect-src 'none'`): geometry is decoded from
base64 into typed arrays, never fetched.

It draws **on demand** — a frame when something changes, with a timer behind `requestAnimationFrame`
because a cross-origin frame that isn't focused gets almost none. It opens through the render
camera when there is one, and otherwise frames the subjects (not the sweep or a ground plane).
Camera view is Blender's: the whole render frame fits the viewport whatever its shape, the outside
is dimmed, and the view follows the camera when the agent moves it. Only an actual orbit leaves
it — a plain click starts an orbit too, and must not put the camera's own lines at the eye, where
they'd win every pick.

**Material Preview looks like the render.** Lamps map Blender watts to three's units (radiance,
as Cycles does). The world is Blender's own: `studio/src/worlds.js` holds 64×32 RGBE copies of the
eight `studiolights/world` HDRIs (regenerate with `scripts/worlds.py` inside the engine image),
sampled with Blender's equirectangular mapping in Z-up space, turned by the world's rotation, times
its strength — or the flat world colour. Reflections and ambient come from a probe baked at the
subjects' centre: the world, past the backdrop, which the lamps light — so chrome on a dark sweep
reads dark, as in Cycles, not lit by a stand-in room. It re-bakes only when the world, the lamps,
the set or the subjects' centre change. Against a Cycles render of the same scene the regions
land within ~10% of each other. The world shows behind the scene too
(a colour world is a dome as well — three's own solid-colour background is a unit box at the origin,
which a probe baked anywhere else sees from outside). Images load once per file: flipped as they
decode (Blender's v = 0 is the bottom row; an ImageBitmap ignores `flipY`), roughness repacked as
luminance (three reads green), each material placing its own view of the pixels with Blender's
mapping as `texture.matrix`. A textured primitive is drawn from Blender's evaluated mesh, so its UVs
are Blender's; the Material panel uploads an image (≤ 2048 px, PNG if transparent else JPEG, written
before the scene names it). Checked against Cycles with a UV checker on five primitives and a
normal-mapped card — they match.

**Shadows.** three can't shadow the area lamps the studio rigs use, so every lamp gets a proxy that
only casts (intensity 0: a spot aimed at the subjects, or a fitted directional for a sun), with
`shadow.intensity` = that lamp's share of the light reaching the subjects — the world's share and the
set's bounce (its albedo × the lamps) counted in, so a white sweep fills shadows and a black one
doesn't. The floor/sweep catches them on a `ShadowMaterial` copy that only darkens (the lamps' light
on it is untouched); subjects cast, and don't self-shadow. Variance shadow maps blurred by the
penumbra the lamp's size throws (big softboxes cast very soft shadows), plus one straight-down
contact shadow for the dark patch right under things. Maps re-render only when the scene changes;
off on touch devices, a View-menu toggle. Against Cycles on the four rigs, the regions under and
around the subjects land mostly within ±15% (worst ≈25%: VSM blurs evenly, where a real penumbra
hardens toward contact). They cost ~4 ms a frame on an Intel UHD 630.

**Render feedback.** The Render button's bar is an estimate from this workspace's own log
(`renders.json`: resolution, samples, Blender's seconds) — `seconds ≈ a + b·(pixels·samples)`,
least squares over the recent ones (a prior before there are any) plus the round trip, in
`studio/src/eta.js`; it lands within ~5% here. The Scene panel lists the renders; each opens full
size on the canvas.

**Object mode.** Click, Shift-click, A; the gizmo and G/R/S; Shift+A add, Shift+D duplicate, X
delete, H hide; numpad views, frame, camera to view; Solid or Material shading; F12 render and a
Snapshot button. Outliner (tree, visibility, rename) and properties: object, the data of each type,
material (Principled plus presets), modifiers (engine-evaluated, debounced, cached; Apply), world
and render. The Object menu runs Blender's convert, join (Ctrl+J), triangulate, merge, normals,
remesh and decimate.

**Edit mode (Tab).** A primitive or text is first made an explicit mesh by Blender (`convert`,
one undo step). Then vertex/edge/face select (1/2/3), click and Shift-click with occluded elements
skipped, A / Alt+A / Ctrl+I, and the gizmo moves the selection live. Local edits — delete (X),
extrude (E: the gizmo then points along the faces' normal), fill (F), merge at centre (M) — live
in `studio/src/mesh.js`, the sidecar codec's twin in JS. Bevel (Ctrl+B), inset (I), subdivide,
triangulate, merge by distance and recalculate normals go to Blender on the saved mesh and come
back as a new one, with what Blender left selected — so inset (I) then extrude (E) works as it does
in Blender. The Material panel lists the slots; in Edit mode **Assign** puts the selected faces in
the picked one (a local op, like extrude). Every edit is a new mesh file and one undo step; the viewport shows the cage
(surface, wire, vertices, selected faces) instead of the modifier result while editing.

**Edit-mode tools**, local like extrude, with an SVG overlay on the viewport for their previews:

- **Loop cut (Ctrl+R).** Hovering an edge draws the ring of quads it runs through (`edgeRing`:
  it stops at an n-gon or a boundary and knows when it closes). The wheel adds cuts, and a
  click cuts. Until the next edit, the Loop cut panel's Cuts and Slide re-run the cut on the
  mesh from before it, like Blender's last-op panel.
- **Knife (K).** Clicks on the surface, then Enter or Space; Esc stops. The path is projected
  onto the mesh's edges (perspective-correct crossings, occluded ones skipped), the crossed
  edges are split, and each face is split between consecutive crossings. Cutting all the way
  through, as a bisect, isn't there.
- **Connect (J).** Two selected vertices on one face split it here; otherwise Blender's
  `connect_vert_pair` does it.
- **Proportional editing (O).** Smooth, sphere, linear, sharp or constant falloff over a
  radius, measured in world space. The wheel resizes it mid-drag, and a circle shows it.
- **Snapping (Shift+Tab, or the Snap button in the header).** Holding Ctrl flips it during a
  drag. A move snaps by 0.1 m steps of the move itself, not the grid, so an off-grid vertex
  stays off it (TransformControls' own translation snap rounds the position). Rotation snaps
  by 15°, scale by 0.1. There's no vertex or surface snapping yet.

`studio/dev/checks/tools.js` drives each tool with real input and then round-trips the result
through Blender (recalculate normals on all of it has to bring back the same mesh).

**Keeping the agent in the picture.** The app publishes `{selection, mode, edit?}` to its
per-person shelf (`cycls.me.set("view")`). The tool resolves the id `"selected"` against it, and
in Edit mode `inspect` says what's selected and `apply` takes `selection: "selected"` — but only
if the mesh the app is editing is the one on disk (the app hasn't saved yet → refused, not
guessed). `cycls.ask(text)` pre-fills the composer; it never sends.

Without the host's `cycls.engine` — a shared view, the phone client, `vite dev` — the app still
opens and edits, and says rendering needs the chat.

## The tool

`studio`, gated on `CYCLS_STUDIO_ENGINE` plus `CYCLS_API_KEY`. Every action first makes sure the
app is installed and current.

| action | does |
|---|---|
| `open` | shows the app on the canvas, and tells the model what's already in the scene |
| `inspect` | the scene as a table, the person's selection, layout warnings |
| `edit {ops, intent, snapshot?}` | atomic ops (add, set, delete, duplicate, material, texture, modifier, world, render, look_at, frame, preset) — all or none, one rev, one patch |
| `snapshot` · `render` | preview to the model; a render also lands in `renders/` and opens |
| `apply` · `script` · `import` · `export` | engine ops, results merged under the lock and pushed |
| `revert {rev}` | a scene from history |

Wherever an image goes — a material's `*_texture`, `add {image}` (an upright plane at the image's
aspect: logos, posters, labels), a `texture` op — `{path}` of a workspace file works too: the tool
stores PNG/JPEG up to 2048 px as they are and sends anything else through the engine's `texture` op
first, all under the scene's lock.

Every edit answer carries a layout check (floating, sunk, off the floor, out of frame) because
models don't see those in numbers. Limits the model is told plainly: materials are Principled
surfaces with optional images; other node networks from a script come back flattened; the answer
says so and says retrying won't help.

## Installing

`ensure_installed(ws)` runs before every action, under a lock per workspace. It writes the
`app.json` stamp first (`studio: {version: <bundle hash>}`), then the bundle — the old one to the
trash as an upgrade — and the README, and seeds `data/scene.json` only when there is none. It
never touches anything else in `data/`. An `apps/studio` without the stamp is the person's own app:
the installer refuses, and `build_app` refuses to overwrite a stamped one.

## Configuration and deploy

```bash
# the engine (Python 3.12, the SDK checkout on PYTHONPATH so scene.py is captured)
cd cycls-render && PYTHONPATH=<sdk> cycls deploy render_fn.py
# the app bundle, then the web client (both are committed build output)
cd studio && npm run build
cd client && npm run build
```

An agent opts in with `.allowed_tools([..., "Studio"])` and the env `CYCLS_STUDIO_ENGINE=cycls-render`
plus `CYCLS_API_KEY`. `CYCLS_STUDIO_RENDERER` optionally sends `render` to a separate deployment so
long renders don't queue in front of interactive ops. `cycls.remote` needs matching Python and
cloudpickle on both sides.

**Importing a .blend.** The file's first scene comes in as it shows it: what its view layer
excludes or its collections hide stays hidden (often the prototypes of instances), and an
instancer Blender doesn't draw itself — a particle emitter, a duplicator — comes in hidden
(`show_instancer_for_render/viewport`). The file's world replaces the Studio's default one (a
plain colour as it is; a sky or an HDRI as the nearest preset, noted), and its active camera is
named for the model. Node-driven material inputs keep their plain values (noted); particle and
geometry-nodes instances don't come across yet.

## Known limitations

- One editor at a time; two editing the same entry keep the local copy.
- No UV editing beyond projections, animation, geometry nodes, sculpting, knife bisect, or
  vertex/surface snapping.
- Engine capacity is shared: four instances, one job each.
- The phone client has no `cycls.engine`; the app degrades to viewing and local edits.

## Testing

- `tests/agent/studio_scene_test.py` — the document: normalize, ops, merge, layout, schema drift.
- `tests/agent/studio_test.py` — the tool, installer, route and mount, with the engine faked.
- `studio/tests/` (vitest) — `doc` (entries, merge3, set vs subjects), `mesh` (codec and edits),
  `app` (the controller against a fake bridge: merging, saving, Edit mode, Apply, Blender's
  selection carried on).
- The viewport itself needs WebGL, so it's checked in a browser: the real host, or headless Chrome
  driving the built bundle through the real shim, bridge and route (gizmo drag and autosave, the
  Render button, Edit mode, and screenshots of Material Preview against a Cycles render).
- `client/tests/app-bridge.test.ts`, `app-shim.test.ts` — `engine`, `onCommand`, `ask`.
- The engine's own: `studio_try.py dev|remote selftest evaluate …` round-trips every object type
  and modifier through Blender and back.

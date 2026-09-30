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

`apps/studio/data/scene.json`, format `cycls.studio.scene` v3. Blender's conventions, so an agent
that knows bpy reads it on sight: Z up, metres, angles in degrees (Euler XYZ — three.js's `'ZYX'`),
colours sRGB hex (linear only at the edges), bpy field names (`energy`, `lens`, `levels`,
`segments`). `objects`, `meshes` and `materials` are maps keyed by stable id; `world` and `render`
are single entries; `rev` counts saves and `by` says whose (`agent` or `app:<session>`).
A mesh or text object has material **slots**, `materials: [id|null, …]`, and a face's
`material_index` (in its mesh file) picks one — Blender's model; a face past the last slot uses the
last. Version 1 had one `material`; a v1 document reads as v2 (it becomes slot 0) in `scene.py`'s
`migrate` and in the app's `bridge.readScene`, so an older scene or an open older tab merge cleanly.
Ops still take `material` as slot 0; `material {assign, slot}` sets another.

**Animation** (v3). `animation` is the timeline, `{fps, frame_start, frame_end}`, and an object's
`keys` are its motion: `{location|rotation|scale: [[frame, [x, y, z], interpolation], …]}`, one key
a frame, the interpolation (`bezier`, `linear`, `constant`) for the segment that key starts. They
are Blender's F-curves exactly as the engine builds them — auto-clamped handles with
auto-smoothing off (a new curve smooths by default, which no twin could match), constant
extrapolation — so `scene.py sample` and its JS twin `studio/src/anim.js` land on Blender's own
numbers: both are held to samples Blender took of the same keys through the real `build`
(`studio/tests/fixtures/anim_golden.json`, within 1e-4 — Blender works in float32). An animated
channel's stored value is where its keys put the first frame (normalize pins it), which is what
framing, layout checks and a still render see. Ops that would set an animated channel outright are
refused with a pointer to `keyframe`; `duplicate` and `on_floor` carry the keys along. A v2
document reads as v3 with a still timeline.

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
| `snapshot` | app, agent | ~640×360, few samples, ~5 s — for checking work; `frame` poses an animation there |
| `render` | app, agent | the Cycles render, PBR Neutral, denoised |
| `video` | route | frames `[a, b]` (≤ 120) as an H.264 segment, and the first frame as a poster when asked — see Video |
| `encode` | route | `segments/s-000.mp4 …` joined into `video.mp4` through the sequencer (tainted: the segments are workspace files) |
| `export` | app, agent | glb, blend, fbx, obj, stl |
| `script` | agent | bpy against the scene; what comes back is read, not trusted |
| `import` | agent | glb, gltf, obj, fbx, stl, ply, blend — packed images come along as textures, motion as keys |
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

**Keys in Blender.** `build` makes each object's keys an action — Blender 5's actions are layered,
so the curves live in a slot's channelbag (`bpy_extras.anim_utils`) — with each key's interpolation
and AUTO_CLAMPED handles, `auto_smoothing = "NONE"`, then sets the scene's fps and range and
`frame_set(frame_start)`. `to_doc` reads them back: the Studio's own curves key for key; anything
else — quaternions, another Euler order, a parent offset (`matrix_parent_inverse`) — re-keyed as XYZ
Euler at its keys through the object's local matrix, whole turns kept (compatible Eulers); a glTF
import's actions parked on the NLA are taken from their strip. What the document can't say (an
easing, hand-set handles, keys between frames, curve modifiers, drivers) is noted, not refused, and
more than 1,000 keys on a channel are thinned evenly. A glb or fbx carries motion but no timeline,
so its keys set the range. Exports write the scene's motion as one animation (glTF `SCENE` mode; FBX
without per-action stacks): per-action exports import as one active action and the rest parked, so
only one object would move. `.blend`, glb and fbx all round-trip the turntable and a keyed pedestal
(FBX shifts keys by a frame on its own round trip).

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
engine deploys first: an older one refuses `.gz` names. Mesh and image files go by name first (`refs`,
`cache` = a per-workspace key from the API key and the workspace path): the engine keeps what
it's been sent, per workspace and outside the jobs tree (a sandboxed worker never sees it),
answers `missing`, and only those follow; least recently used go past 1.2 GB. The calls are
`sticky` (Cloud Run's affinity cookie), so they tend to reach the instance that has them —
the venue's snapshot went from 39 s to 16 s, 13.6 of it Blender's.

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

## Video

A five-second 720p video is minutes of Cycles (15.3 s a frame at 1280×720 and 16 samples on the
8-core engine): more than one engine call may take, and Cloud Run throttles a server's CPU once it has
answered, so nothing can render in the background on the agent server. **The app drives it**, in
`cycls/_agent/studio/video.py`:

- `video_start` snapshots the scene (the app's own, unsaved edits included) into a job —
  `apps/studio/data/jobs/<id>.json`, the scene in `jobs/<id>/scene.json`. One running job a
  workspace; at most 240 frames, 1280×720 (a bigger render keeps its shape) and 64 samples
  (16 unless asked).
- `video_chunk` claims the next frames under a per-job lock and renders them into
  `jobs/<id>/s-NNN.mp4` — one request, a few minutes. A chunk is sized from the job's measured
  seconds a frame to take ~240 s of Blender (the first is short, ~90 s, to measure; before that
  the workspace's stills give the rate); a claim older than 15 minutes is taken again (a tab
  closed mid-chunk — whose request still finishes on the server). Engine slots: one chunk at a
  time on the shared engine (interactive ops keep the rest of it), four when
  `CYCLS_STUDIO_RENDERER` names a deployment of its own; a chunk waits up to 600 s for one. A
  chunk that fails is taken again; the third failure ends the job. 600 frames an hour a person.
  An answer with `wait` (nothing to take yet, the engine busy, the hour's frames spent) says when
  to come back.
- `video_finish` joins the segments (`encode`) into `renders/<name>.mp4`, logs it with the
  renders (`video: true`, frames, fps), drops the segments and answers `open` — the host opens the
  video on the canvas.
- `video_cancel`, and `video_jobs` (running first) so a reload, another tab or the agent's
  `render {animation: true}` (an `app_command {type: "video"}`) picks a job up where it stands.

On the engine a chunk renders PNG frames with persistent data (the scene syncs once, not once a
frame), then the sequencer encodes them in the Standard view — they're already tone-mapped — as
near-lossless H.264 (an intermediate; the join encodes once more at CRF "high"). A decoded frame
sits within ~1 of 255 of its PNG. The segments are joined, not the frames: 240 frames of 720p PNG
would be ~300 MB to carry back and forth. Store sweeps keep the mesh files a running job's scene
names. Measured: 48 frames at 480×270 and 4 samples, 0.65 s a frame, 45 s end to end; 96 at
640×360 and 8 samples, two chunks of ~73 s, joined. A snapshot during a chunk: the first ~12 s
(Cloud Run starts another instance, which is sent the scene's files), then 3.7–3.9 s as without
one (3.5–4.3 s).

## The app's route

`POST /apps/studio/engine`, mounted only when Studio is configured. It answers 404 unless the slug
is `studio` **and** `app.json` carries the installer's stamp — a hand-written app at that path gets
nothing. It allows the app ops only (never `script` or `import`), normalizes the scene it's sent,
and resolves mesh files only from the app's own `data/meshes/`. Budgets per subject: 60 calls a
minute, 30 renders an hour, one render at a time. It saves what the engine made — `renders/*.png`
plus the log, mesh files, `exports/*` — before answering, so a tab closed mid-render loses nothing.
One op never reaches the engine: `open {path}` answers `{open: path}` for a render the log lists or
a file under `exports/`, and the host bridge opens it on the canvas (the Renders list, the preview's
Open). The `video_*` ops are the video jobs above.

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

**Time.** The timeline is one row under everything, Blender's: first/previous key/play/next
key/last, the frame, a scrub bar with the selection's keys as diamonds, start, end and fps, auto-key
(●), ◆ Key, the interpolation of the key under the playhead, and Render video. Keys are Blender's:
I keys the selection's location, rotation and scale where they are, Alt+I removes this frame's
keys, Space plays (Esc stops where it began), ←/→ step a frame (Shift: to the ends), ↑/↓ jump key
to key. The Object panel shows the pose at this frame; each channel's ◆ keys or unkeys it here
(green when the channel moves, yellow when it has a key here). Moving a channel that has keys keys
it at this frame — the next frame would put it back otherwise; a still channel just moves, unless
auto-key is on. A turn keeps counting past 180° (the gizmo's Euler is made compatible with the
key's). The viewport draws the document posed at the current frame; playback runs off the clock
(a cross-origin frame gets few animation frames unfocused), and each tick moves only the keyed
objects' transforms (`vp.pose`) — no rebuild, no probe or lamp-rig bake, the shadow maps redraw,
the camera view rides an animated camera — and at rest a full sync catches up. What an animation
moves is never drawn batched. A video rendering shows its frames, the server's estimate counting
down, and Cancel; when it's done its poster shows with Open.

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
| `edit {ops, intent, snapshot?}` | atomic ops (add, set, delete, duplicate, material, texture, modifier, world, render, look_at, frame, preset, keyframe, unkey, animation, turntable) — all or none, one rev, one patch |
| `snapshot {frame?}` · `render` | preview to the model; a render also lands in `renders/` and opens |
| `render {animation: true}` | starts a video job, opens the Studio and tells it to render; the model says how long and doesn't wait (`inspect` reports progress) |
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
named for the model. A node-driven Base Color, Roughness or Metallic comes in as its average: the
engine bakes the network as emission onto a 16×16 plane in a scene of its own (so a file of
thousands of objects isn't prepared for each bake) and averages it — up to 80 inputs a job.
Instances Blender draws — particle scatter, collection instances, geometry-nodes instances of
objects — become objects sharing their source's mesh (the viewport instances them again), one
instancer's set whole or not at all: up to 2,000 come in; a million-pebble scatter is left out,
named, rather than carried as a misleading sliver. Instanced geometry that isn't an object isn't
carried. The tool counts material notes for the model rather than listing dozens.

## Known limitations

- One editor at a time; two editing the same entry keep the local copy.
- No UV editing beyond projections, geometry nodes, sculpting, knife bisect, or
  vertex/surface snapping. Animation is transforms only (no armatures, shape keys or animated
  materials); a video is at most 240 frames at 720p, and renders only while a Studio is open.
- Engine capacity is shared: four instances, one job each.
- The phone client has no `cycls.engine`; the app degrades to viewing and local edits.

## Testing

- `tests/agent/studio_scene_test.py` — the document: normalize, ops, merge, layout, schema drift,
  keys, and the evaluator against Blender's samples.
- `tests/agent/studio_test.py` — the tool, installer, route and mount, video jobs (chunk sizing,
  stale claims, failures, cancel, budgets, busy), with the engine faked.
- `studio/tests/` (vitest) — `doc` (entries, merge3, set vs subjects), `mesh` (codec and edits),
  `anim` (the evaluator against scene.py and against Blender), `app` (the controller against a fake
  bridge: merging, saving, Edit mode, Apply, Blender's selection carried on, keying, the video loop).
- The viewport itself needs WebGL, so it's checked in a browser: the real host, or headless Chrome
  driving the built bundle through the real shim, bridge and route (gizmo drag and autosave, the
  Render button, Edit mode, and screenshots of Material Preview against a Cycles render).
- `client/tests/app-bridge.test.ts`, `app-shim.test.ts` — `engine`, `onCommand`, `ask`.
- The engine's own: `studio_try.py dev|remote selftest evaluate …` round-trips every object type
  and modifier through Blender and back; `anim` round-trips keys and regenerates
  `anim_golden.json`, `anim-io` round-trips motion through blend/glb/fbx, `video` renders and joins
  two segments (with a decode check).

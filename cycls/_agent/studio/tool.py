"""The `studio` tool: the agent's hands on the Studio scene.

Pure-document actions (inspect, edit, revert, open) run here in milliseconds;
the rest (snapshot, render, apply, script, import, export) go to the Blender
engine. Every change is saved through store.edit's lock and pushed to an open
Studio app as an `app_command` patch, so what the user sees is what was saved.
"""
import asyncio
import base64
import json
import pathlib
import re


from . import APP_DIR, SLUG, engine, install, store, video
from . import scene as S

APP_ENTRY = f"{APP_DIR}/index.html"
MAX_IMPORT = 100_000_000          # a model or image file from the workspace
IMPORT_EXTS = ("glb", "gltf", "obj", "fbx", "stl", "ply", "blend")
EXPORT_EXTS = {"glb": "glb", "blend": "blend", "fbx": "fbx", "obj": "obj", "stl": "stl"}

STUDIO_TOOL = {
    "type": "custom",
    "name": "studio",
    "description": (
        "Build and render 3D scenes in the Studio — a Blender-style app the user can also edit by hand, "
        "rendered by real Blender (Cycles). The scene is a document: Z is up, units are metres, angles "
        "are degrees, colours are hex.\n\n"
        "Actions:\n"
        "- inspect: the scene as a table, with what the user has selected in the Studio.\n"
        "- edit {ops, intent, snapshot?}: change the scene with a list of ops, applied atomically "
        "(all or none). Batch a whole scene into ONE edit. `snapshot: true` also returns a quick preview.\n"
        "- snapshot: a fast low-quality Cycles preview (~5 s) of the current scene, for checking your work.\n"
        "- render {name, resolution?, samples?}: the final image (~25-60 s), saved to renders/ and opened. "
        "With `animation: true`: the animation as an mp4 — the Studio app renders it a chunk at a time "
        "(~15 s a frame at 1280x720 and 16 samples, so minutes), then renders/<name>.mp4 opens. At most 240 "
        "frames, 1280x720, 64 samples; one video at a time.\n"
        "- snapshot {frame?}: as above; `frame` looks at an animation's pose there.\n"
        "- apply {id, operation, params?}: a destructive mesh operation by real Blender: modifier_apply "
        "{index}, convert, bevel {selection, width, segments}, subdivide {selection, cuts}, inset "
        "{selection, thickness}, triangulate, merge_by_distance, recalc_normals, remesh {voxel_size}, "
        "decimate {ratio}, boolean {object, operation}, join {others}, uv {method: cube|cylinder|sphere|reset, "
        "scale?} (re-project UVs; primitives already have Blender's). selection: \"all\", {faces:[i]}, "
        "{edges:[[a,b]]}, {verts:[i]} — or \"selected\": what the user has selected in Edit mode (inspect "
        "says when there is something).\n"
        "- script {code}: run Blender Python (bpy) against the scene when no op can express it — e.g. a "
        "procedural arrangement. Objects it adds come back into the scene; anything the document can't "
        "represent is baked to a mesh (you're told).\n"
        "- import {path}: add a model file from the workspace (glb, gltf, obj, fbx, stl, ply, blend).\n"
        "- export {format, name}: glb, blend, fbx, obj or stl, into exports/.\n"
        "- revert {rev}: restore the scene as it was at an earlier rev.\n"
        "- open: show the Studio app on the canvas.\n\n"
        "Edit ops (each an object with \"op\"):\n"
        "- add {id?, name?, primitive (plane|grid|circle|cube|uv_sphere|ico_sphere|cylinder|cone|torus|monkey), "
        "params?, material?, location?, rotation?, scale?, parent?, on_floor?, look_at?} — or {image, height?}: "
        "an upright plane at the image's aspect showing it (logos, posters, labels) — or type "
        "\"light\" {light:{kind: point|sun|spot|area, energy (W), color, size...}}, \"camera\" "
        "{camera:{lens (mm), dof_fstop}}, \"text\" {text:{body, size, extrude, bevel_depth}}, \"empty\". "
        "material: a preset (gold, brushed-gold, chrome, brushed-steel, copper, plastic, matte, ceramic, "
        "glass, rubber, neon), an existing material id, or {name, base_color, metallic, roughness, ...}.\n"
        "- set {id, ...fields to change, params?: primitive parameters, on_floor?}\n"
        "- delete {id} · duplicate {id, offset?}\n"
        "- material {id?, name?, preset?, base_color?, metallic?, roughness?, coat?, transmission?, ior?, "
        "emission?, alpha?, base_color_texture?, roughness_texture?, normal_texture?, normal_strength?, "
        "texture_scale? [u,v], texture_offset? [u,v], texture_rotation?, assign?: object id(s)}. A *_texture is a "
        "texture id or {path} of an image in the workspace (png, jpg, webp…) — e.g. what the user attached; "
        "texture_scale tiles it (wood, fabric). A preset keeps the images.\n"
        "- texture {path, id?, name?}: add an image as a texture id to use in the same edit (unused ones are dropped). "
        "Anywhere an image goes, {path} works too.\n"
        "- modifier {object, action: add|set|remove|move, type (subsurf|bevel|mirror|array|solidify|boolean|"
        "remesh|decimate|weld|triangulate|wireframe), params?, index?, to?}\n"
        "- look_at {id, target: object id or [x,y,z]} · frame {camera?, targets?, angle?, margin?}\n"
        "- world {kind: hdri|color, hdri, strength, color, rotation} · render {resolution, samples, camera, transparent}\n"
        "- preset {studio: {lighting: studio-3point|softbox|dramatic|rim, backdrop: hex, camera: "
        "front|front-3/4|side|top|low|hero}} — a photo-studio sweep, light rig, framed camera and world.\n"
        "- turntable {target?, turns?, direction? (ccw|cw), seconds?, fps?}: spin the subjects (or target) on the "
        "spot, a seamless loop, under a new empty (5 s unless the timeline is set).\n"
        "- keyframe {id, frame, location?, rotation?, scale?, interpolation? (bezier|linear|constant)}: key "
        "channels at a frame — the values given, or where the object is then (none given: all three). Key the "
        "start pose, then the changes at later frames. A channel with keys changes only by keyframe, not set.\n"
        "- unkey {id, frame?, channel?} · animation {fps?, frame_start?, frame_end?, seconds?}: the timeline.\n"
        "Use id \"selected\" for whatever the user has selected in the Studio.\n\n"
        "Limits: materials are Principled surfaces with optional image maps (base colour — its transparency "
        "too — roughness, normal) on the object's UVs. Other node networks come back flattened to their plain "
        "values and procedural geometry baked to meshes; the result says so, and more scripts won't change that."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["inspect", "edit", "snapshot", "render", "apply", "script",
                                                  "import", "export", "revert", "open"]},
            "ops": {"type": "array", "items": {"type": "object"},
                    "description": "edit: the ops, applied in order, all or none"},
            "intent": {"type": "string", "description": "edit: a few words on what this change does"},
            "snapshot": {"type": "boolean", "description": "edit: also return a quick preview"},
            "name": {"type": "string", "description": "render/export: file name"},
            "resolution": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
            "samples": {"type": "integer", "minimum": 1, "maximum": 256},
            "animation": {"type": "boolean", "description": "render: the animation as an mp4 video"},
            "frame": {"type": "integer", "description": "snapshot: the frame to look at (animations)"},
            "id": {"type": "string", "description": "apply: the object"},
            "operation": {"type": "string", "description": "apply: which operation"},
            "params": {"type": "object", "description": "apply: the operation's parameters"},
            "code": {"type": "string", "description": "script: Blender Python; bpy, bmesh, Vector, Matrix, math, np are imported"},
            "path": {"type": "string", "description": "import: a model file in the workspace"},
            "format": {"type": "string", "enum": list(EXPORT_EXTS)},
            "rev": {"type": "integer", "description": "revert: the rev to restore"},
        },
        "required": ["action"],
    },
}

STUDIO_GUIDANCE = """## Studio (3D)
Build scenes with the `studio` tool; the user watches them appear in the Studio app and can move things by hand.
- Open the Studio once per conversation (`open`) when you start building, so the user can watch.
- Make a whole scene in ONE `edit`: start from a `preset` (studio lighting + backdrop + framed camera) after adding the objects, since the preset frames what exists.
- Z is up, metres, degrees. Stand things on the ground with `on_floor: true`; aim cameras and lights with `look_at`, and re-frame with `frame` — don't compute Euler angles by hand.
- "this"/"that"/"it" usually means what the user selected: use id "selected". `inspect` shows the selection.
- Check your work with `snapshot` (5 s) before a final `render` (25-60 s). Look at the preview: framing, overlaps, floating objects, materials.
- An image the user gives you (a logo, a label, a photo): `add {image: {path}}` for a flat sign or label in front of a surface, or a material's `base_color_texture: {path}` to wrap it round an object. Tile patterns with `texture_scale`.
- Motion: `turntable` for a product spin; `keyframe` for moves (key the start, then later frames). `snapshot {frame}` checks a pose; `render {animation: true}` makes the video — say roughly how long it will take, and don't wait for it.
- Use `script` only for what ops can't express; never edit apps/studio/data/ files directly.
- After a render, describe what you made in a sentence and offer one concrete variation."""


# ─────────────────────────────── helpers ──────────────────────────────────────

def _slug(s, default):
    return re.sub(r"[^a-z0-9-]+", "-", str(s or "").lower()).strip("-")[:48] or default


def _free(root, folder, name, ext):
    d = pathlib.Path(root) / folder
    d.mkdir(parents=True, exist_ok=True)
    base, n = name, 1
    while (d / f"{name}.{ext}").exists():
        n += 1
        name = f"{base}-{n}"
    return f"{folder}/{name}.{ext}"


def _image(jpg, text):
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpg).decode()}},
            {"type": "text", "text": text}]


def _command(command):
    return {"type": "ui", "action": "app_command", "path": APP_ENTRY, "command": command}


def _patch_event(before, after, label):
    d = S.diff(before, after)
    return _command({"type": "patch", "base": before["rev"], "rev": after["rev"], "by": "agent",
                     "label": (label or "")[:80], "set": d["set"], "delete": d["delete"]})


async def _view(ws):
    """What the person chatting has open in their Studio: {selection, mode, edit?} (the app keeps it current)."""
    from ..state import actor_of, app_shelf, apps_db
    try:
        view = await apps_db(ws).get(app_shelf(SLUG, "view", user=actor_of(ws.subject)))
    except Exception:
        return {}
    return view if isinstance(view, dict) else {}


def _picked(view):
    sel = view.get("selection")
    return [s for s in sel if isinstance(s, str)] if isinstance(sel, list) else []


async def _selection(ws):
    return _picked(await _view(ws))


_ELEMENTS = {"vert": ("verts", "vertices"), "edge": ("edges", "edges"), "face": ("faces", "faces")}


def _edit_view(view, doc):
    """The viewer's Edit-mode selection, if it's about the mesh the scene has now:
    (object id, mode, items or None when too many to pass on, count)."""
    e = view.get("edit") if view.get("mode") == "edit" else None
    if not isinstance(e, dict) or e.get("mode") not in _ELEMENTS:
        return None
    o = doc["objects"].get(e.get("object"))
    if not o or o.get("mesh") != e.get("mesh"):
        return None                          # not saved by the app yet, or changed since
    items = e.get("items")
    return e["object"], e["mode"], items if isinstance(items, list) else None, int(e.get("count") or 0)


def _edit_note(view, doc):
    ev = _edit_view(view, doc)
    if not ev:
        return ""
    oid, mode, items, count = ev
    if not count:
        return f"\nThe user is in Edit mode on {oid}, nothing selected."
    tail = (' — `apply` with params.selection "selected" works on them' if items is not None
            else ' (too many to pass on: use "all" or explicit indices)')
    return f"\nThe user is in Edit mode on {oid}: {count} {_ELEMENTS[mode][1]} selected{tail}."


async def _save(ws, before, after, label):
    saved = await store.save(ws, after, before)
    return saved, _patch_event(before, saved, label)


def _write_outputs(ws, files):
    """Mesh and image files a script or import made, into data/ (content-named)."""
    for rel, data in files.items():
        m = re.match(r"^meshes_out/(m-[0-9a-f]{12})\.json$", rel)
        if m:
            store.write_mesh(ws, m.group(1), data)
        t = re.match(r"^textures_out/t-[0-9a-f]{12}\.(png|jpg)$", rel)
        if t:
            store.write_texture(ws, data, "image/png" if t.group(1) == "png" else "image/jpeg")


IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "tga", "exr", "hdr")


def _png_alpha(data):
    """Could this PNG be transparent? RGBA / grey+alpha colour types, or a tRNS chunk."""
    if data[25:26] in (b"\x04", b"\x06"):
        return True
    idat = data.find(b"IDAT")
    return b"tRNS" in data[:idat if idat > 0 else 4096]


async def _image_texture(ws, rel):
    """A workspace image as a stored texture: PNG/JPEG up to 2048 px go in as they are,
    anything else (bigger, webp, tiff…) through Blender first."""
    from ..tools import _resolve_path
    try:
        path = _resolve_path(rel, ws.root)
    except ValueError as e:
        raise S.SceneError(f"{rel}: {e}") from None
    ext = path.suffix.lower().lstrip(".")
    if ext not in IMAGE_EXTS:
        raise S.SceneError(f"{rel}: images are {', '.join(IMAGE_EXTS)}")
    if not path.is_file():
        raise S.SceneError(f"{rel} does not exist")
    if path.stat().st_size > MAX_IMPORT:
        raise S.SceneError(f"{rel} is over {MAX_IMPORT // 1_000_000} MB")
    data = await asyncio.to_thread(path.read_bytes)
    media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext)
    size = None
    if media:
        try:
            size = store.image_size(data)
        except S.SceneError:
            media = None
    if media and max(size) <= 2048 and len(data) <= store.MAX_TEXTURE_BYTES:
        w, h = size
        alpha = media == "image/png" and _png_alpha(data)
    else:
        r = await engine.call("texture", {}, blobs={f"texture_in.{ext}": data}, params={"ext": ext})
        res = r["result"]
        data, media = r["files"][res["file"]], "image/png" if res["file"].endswith(".png") else "image/jpeg"
        w, h, alpha = res["width"], res["height"], res["alpha"]
    stored = await asyncio.to_thread(store.write_texture, ws, data, media)
    name = re.sub(r"^[0-9a-f]{8}-", "", path.stem)[:64] or "image"      # a chat upload's hash prefix
    return {"name": name, "data": stored, "width": w, "height": h, "alpha": bool(alpha)}


async def _resolve_images(ws, ops, doc):
    """`{path}` wherever an image goes → a `texture` op ahead of it and the new id in its place."""
    if not isinstance(ops, list):
        return ops
    out, made, taken = [], {}, set(doc["textures"])

    async def texture_id(ref, name=None):
        rel = ref["path"]
        if rel not in made:
            spec = await _image_texture(ws, rel)
            tid = S._new_id({"textures": dict.fromkeys(taken)}, "textures", name or spec["name"])
            taken.add(tid)
            made[rel] = tid
            out.append({"op": "texture", "id": tid, **spec})
        return made[rel]

    for op in ops:
        if not isinstance(op, dict):
            out.append(op)
            continue
        op = dict(op)
        if op.get("op") == "texture" and isinstance(op.get("path"), str):
            spec = await _image_texture(ws, op.pop("path"))
            tid = op.get("id") or S._new_id({"textures": dict.fromkeys(taken)}, "textures", op.get("name") or spec["name"])
            taken.add(tid)
            out.append({**spec, **{k: v for k, v in op.items() if k in ("name",)}, "op": "texture", "id": tid})
            continue
        for holder in (op, op.get("material") if isinstance(op.get("material"), dict) else None):
            if holder is None:
                continue
            for f in (*S.TEXTURE_FIELDS, "image"):
                if isinstance(holder.get(f), dict) and isinstance(holder[f].get("path"), str):
                    holder[f] = await texture_id(holder[f])
        if isinstance(op.get("material"), dict):
            op["material"] = dict(op["material"])
        out.append(op)
    return out


def _layout(doc):
    issues = S.layout_check(doc)
    return (" Layout check: " + "; ".join(issues[:6]) + ". Fix these before rendering.") if issues else ""


def _notes(notes):
    """What didn't come across, for the model: the material inputs counted (an import can have
    dozens), the rest listed first."""
    if not notes:
        return ""
    baked = [n for n in notes if n.endswith("used its baked average")]
    plain = [n for n in notes if "kept its plain value" in n]
    rest = [n for n in notes if n not in baked and n not in plain]
    lines = rest[:8]
    if baked:
        lines.append(f"{len(baked)} node-driven material inputs became their baked average colour/value")
    if plain:
        lines.append(f"{len(plain)} node-driven material inputs kept their plain values (e.g. {plain[0]})")
    return "\nNOT carried into the scene exactly (a limit of the document — don't retry it): " + "; ".join(lines)


# ─────────────────────────────── actions ──────────────────────────────────────

async def _edit(ws, inp):
    ops = inp.get("ops")
    sel = await _selection(ws)
    async with store.lock(ws):
        before = await store.load(ws)
        ops = await _resolve_images(ws, ops, before)
        after, touched = S.apply_ops(before, ops, selection=sel)
        if not touched or S.diff(before, after) == {"set": {}, "delete": []}:
            return "No change — the scene already looked like that."
        saved, event = await _save(ws, before, after, inp.get("intent") or f"{len(ops)} op(s)")
    shown = ", ".join(touched[:12]) + ("…" if len(touched) > 12 else "")
    ack = f"Saved rev {saved['rev']}: changed {shown}." + _layout(saved)
    if inp.get("snapshot"):
        r = await engine.call("snapshot", saved, blobs=store.blobs(ws, saved, "snapshot"), params={"samples": 12}, ws=ws)
        jpg = r["files"]["preview.jpg"]
        snap = _command({"type": "snapshot", "rev": saved["rev"],
                         "preview": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()})
        return {"_model": _image(jpg, ack + " Snapshot attached — check framing, overlaps, floating objects "
                                       "and materials before you render."),
                "_ui": [event, snap]}
    return {"_model": ack, "_ui": event}


async def _snapshot(ws, inp):
    doc = await store.load(ws)
    params = {"samples": inp.get("samples") or 12}
    if isinstance(inp.get("frame"), int):
        params["frame"] = inp["frame"]
    r = await engine.call("snapshot", doc, blobs=store.blobs(ws, doc, "snapshot"), params=params, ws=ws)
    jpg = r["files"]["preview.jpg"]
    ui = _command({"type": "snapshot", "rev": doc["rev"],
                   "preview": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()})
    return {"_model": _image(jpg, f"Snapshot of rev {doc['rev']} ({r['result']['resolution'][0]}x"
                                  f"{r['result']['resolution'][1]}, preview quality) — check framing, overlaps, "
                                  "floating objects and materials." + _layout(doc)),
            "_ui": ui}


async def _video(ws, inp):
    doc = await store.load(ws)
    job = await video.start(ws, doc, {k: inp[k] for k in ("resolution", "samples", "name") if inp.get(k)}, by="agent")
    (a, b), (w, h) = job["frames"], job["resolution"]
    ack = (f"Started video {job['id']}: frames {a}–{b} ({job['total']} frames at {job['fps']} fps, {w}x{h}, "
           f"{job['samples']} samples), about {max(1, round(job['seconds_left'] / 60))} min. The Studio (open on "
           "the canvas now) renders it a chunk at a time while it's open; when it's done, "
           f"renders/{job['name']}.mp4 opens there. `inspect` says how far it is. Tell the user it's rendering and "
           "roughly how long — don't wait for it.")
    return {"_model": ack, "_ui": [_studio_canvas(), _command({"type": "video", "job": job["id"]})]}


async def _render(ws, inp):
    if inp.get("animation"):
        return await _video(ws, inp)
    doc = await store.load(ws)
    params = {k: inp[k] for k in ("resolution", "samples") if inp.get(k)}
    r = await engine.call("render", doc, blobs=store.blobs(ws, doc, "render"), params=params, ws=ws)
    res = r["result"]
    png, jpg = r["files"]["render.png"], r["files"]["preview.jpg"]
    rel = _free(ws.root, "renders", _slug(inp.get("name"), "studio"), "png")
    await asyncio.to_thread((pathlib.Path(ws.root) / rel).write_bytes, png)
    await asyncio.to_thread(store.log_render, ws, {"path": rel, "rev": doc["rev"], "resolution": res["resolution"],
                                                   "samples": res["samples"], "seconds": res["render_seconds"],
                                                   "by": "agent"})
    w, h = res["resolution"]
    ack = (f"Rendered {rel} ({w}x{h}, {res['samples']} samples, {res['render_seconds']:.0f}s in Blender) "
           "and opened it on the canvas. The render is attached: check it before you describe it.")
    return {"_model": _image(jpg, ack),
            "_ui": [{"type": "ui", "action": "open_canvas", "path": rel, "name": rel.rsplit("/", 1)[-1]},
                    _command({"type": "render_done", "path": rel, "rev": doc["rev"],
                              "preview": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()})]}


async def _apply(ws, inp):
    oid, op = inp.get("id"), inp.get("operation")
    if not oid or not op:
        return "Error: apply needs `id` (the object) and `operation`."
    view = await _view(ws)
    sel = _picked(view)
    params = dict(inp.get("params") or {})
    async with store.lock(ws):
        before = await store.load(ws)
        if oid == "selected":
            if len(sel) != 1:
                return "Error: select exactly one object in the Studio (or name it by id)."
            oid = sel[0]
        if oid not in before["objects"]:
            return f"Error: no object {oid!r}."
        if params.get("selection") == "selected":
            ev = _edit_view(view, before)
            if not ev or ev[0] != oid or not ev[3]:
                return (f"Error: nothing is selected in Edit mode on {oid} (or the Studio hasn't saved it yet) — "
                        'pass explicit indices or "all".')
            if ev[2] is None:
                return 'Error: too many elements selected to pass on — use "all" or explicit indices.'
            params["selection"] = {_ELEMENTS[ev[1]][0]: ev[2]}
        r = await engine.call("apply", before, blobs=store.blobs(ws, before, "apply"),
                              params={"id": oid, "op": op, **params}, ws=ws)
        res = r["result"]
        rel = store.write_mesh(ws, res["mesh_id"], r["files"]["mesh.json"])
        after = json.loads(json.dumps(before))
        o = after["objects"][oid]
        keep = {k: o[k] for k in ("name", "parent", "location", "rotation", "scale", "visible", "renderable",
                                  "materials", "shading", "modifiers") if k in o}
        after["objects"][oid] = {**keep, "type": "mesh", "mesh": res["mesh_id"]}
        after["meshes"][res["mesh_id"]] = {"data": rel, "verts": res["verts"], "faces": res["faces"],
                                           "bbox": res["bbox"]}
        if res.get("modifiers") is not None:
            after["objects"][oid]["modifiers"] = res["modifiers"]
        if res.get("materials") is not None:                  # a join merges the others' slots
            after["objects"][oid]["materials"] = res["materials"]
        if op == "convert" or o["type"] == "text":
            after["objects"][oid].setdefault("modifiers", [])
        if res.get("removed"):
            after, _ = S.apply_ops(S.prune_meshes(after), [{"op": "delete", "id": rid} for rid in res["removed"]
                                                           if rid in after["objects"]])
        after = S.normalize(S.prune_meshes(after))
        saved, event = await _save(ws, before, after, f"{op} {oid}")
    return {"_model": f"Applied {op} to {oid}: now {res['verts']} vertices, {res['faces']} faces (rev {saved['rev']})."
                      + (f" Merged in and removed: {', '.join(res['removed'])}." if res.get("removed") else ""),
            "_ui": event}


async def _script(ws, inp):
    code = inp.get("code")
    if not isinstance(code, str) or not code.strip():
        return "Error: script needs `code` (Blender Python)."
    async with store.lock(ws):
        before = await store.load(ws)
        r = await engine.call("script", before, blobs=store.blobs(ws, before, "script"), params={"code": code}, ws=ws)
        res = r["result"]
        _write_outputs(ws, r["files"])
        after = S.prune_meshes(S.normalize(res["scene"]))
        if S.diff(before, after) == {"set": {}, "delete": []}:
            return "The script ran but changed nothing in the scene." + _notes(res.get("notes")) + (
                f"\nOutput:\n{res['stdout'][-1500:]}" if res.get("stdout") else "")
        saved, event = await _save(ws, before, after, "script")
    d = S.diff(before, saved)
    ack = (f"Script applied (rev {saved['rev']}): {len(d['set'])} entries changed, {len(d['delete'])} removed."
           + _notes(res.get("notes")) + _layout(saved)
           + (f"\nOutput:\n{res['stdout'][-1500:]}" if res.get("stdout") else ""))
    return {"_model": ack, "_ui": event}


async def _import(ws, inp):
    from ..tools import _resolve_path
    try:
        path = _resolve_path(inp.get("path", ""), ws.root)
    except ValueError as e:
        return f"Error: {e}"
    ext = path.suffix.lower().lstrip(".")
    if ext not in IMPORT_EXTS:
        return f"Error: import takes {', '.join(IMPORT_EXTS)} files."
    if not path.is_file():
        return f"Error: {inp.get('path')} does not exist."
    if path.stat().st_size > MAX_IMPORT:
        return f"Error: that file is over {MAX_IMPORT // 1_000_000} MB."
    data = await asyncio.to_thread(path.read_bytes)
    r = await engine.call("import", {}, blobs={f"import.{ext}": data}, params={"ext": ext})
    res = r["result"]
    _write_outputs(ws, r["files"])
    async with store.lock(ws):
        before = await store.load(ws)
        frag = res["scene"]
        frag["render"] = {**frag["render"], "camera": None}
        after, added = S.merge_fragment(before, frag)
        said = []
        # The file's world, when this scene's is still the Studio's default; its camera, named.
        if res.get("world") and before["world"] == S.new_scene()["world"]:
            after = S.normalize({**after, "world": {**after["world"], **res["world"]}})
            said.append("took the file's world")
        # Its timeline, for its keys — when nothing here moves yet.
        if res.get("animation") and S.animated(after) and not S.animated(before):
            after = S.normalize({**after, "animation": res["animation"]})
            a = after["animation"]
            said.append(f"its animation came along (frames {a['frame_start']}–{a['frame_end']} at {a['fps']} fps)")
        cam = dict(zip(frag["objects"], added)).get(res.get("camera"))
        if cam:
            said.append(f"the file's camera is {cam!r} — `render {{camera: \"{cam}\"}}` looks through it")
        saved, event = await _save(ws, before, after, f"import {path.name}")
    return {"_model": f"Imported {inp.get('path')}: added {len(added)} object(s) — {', '.join(added[:15])} "
                      f"(rev {saved['rev']})." + (" " + "; ".join(said) + "." if said else "") + _notes(res.get("notes")),
            "_ui": event}


async def _export(ws, inp):
    fmt = str(inp.get("format") or "glb").lower()
    if fmt not in EXPORT_EXTS:
        return f"Error: format is one of {', '.join(EXPORT_EXTS)}."
    doc = await store.load(ws)
    r = await engine.call("export", doc, blobs=store.blobs(ws, doc, "export"), params={"format": fmt}, ws=ws)
    data = r["files"][r["result"]["file"]]
    rel = _free(ws.root, "exports", _slug(inp.get("name"), "scene"), EXPORT_EXTS[fmt])
    await asyncio.to_thread((pathlib.Path(ws.root) / rel).write_bytes, data)
    ack = f"Exported the scene to {rel} ({len(data) // 1024} KB)."
    if fmt == "glb":
        return {"_model": ack + " Opened it on the canvas.",
                "_ui": {"type": "ui", "action": "open_canvas", "path": rel, "name": rel.rsplit("/", 1)[-1]}}
    return ack


async def _revert(ws, inp):
    rev = inp.get("rev")
    if not isinstance(rev, int):
        return "Error: revert needs `rev` (see data/history/)."
    async with store.lock(ws):
        before = await store.load(ws)
        old = await asyncio.to_thread(store.history, ws, rev)
        saved, event = await _save(ws, before, old, f"revert to rev {rev}")
    return {"_model": f"Restored the scene as it was at rev {rev} (now rev {saved['rev']}).", "_ui": event}


async def _videos_note(ws):
    jobs = await video.jobs(ws)
    if not jobs:
        return ""
    j = jobs[0]
    if j["status"] == "running":
        return (f"\nVideo {j['id']} is rendering: {j['done']}/{j['total']} frames, about "
                f"{max(1, round(j['seconds_left'] / 60))} min left (it renders while the Studio is open).")
    if j["status"] == "done":
        return f"\nThe last video is {j['path']}."
    if j["status"] == "failed":
        return f"\nThe last video failed: {j.get('error', 'unknown error')}"
    return ""


async def _inspect(ws, inp):
    doc = await store.load(ws)
    view = await _view(ws)
    return S.summary(doc, _picked(view)) + _edit_note(view, doc) + await _videos_note(ws)


def _studio_canvas():
    return {"type": "ui", "action": "open_canvas", "path": APP_ENTRY, "name": "Studio", "icon": install.ICON}


async def _open(ws, inp):
    # What's already there, so the model doesn't greet a finished scene as an empty one.
    return {**_studio_canvas(), "ack": "Opened the Studio on the canvas; your edits appear there as you go. It holds:\n"
                                       + await _inspect(ws, inp)}


_ACTIONS = {"edit": _edit, "snapshot": _snapshot, "render": _render, "apply": _apply, "script": _script,
            "import": _import, "export": _export, "revert": _revert, "inspect": _inspect}


async def run(inp, ws):
    action = str(inp.get("action") or "").lower()
    if action not in (*_ACTIONS, "open"):
        return f"Error: action is one of {', '.join([*_ACTIONS, 'open'])}."
    try:
        installed = await install.ensure_installed(ws)
        if action == "open":
            return await _open(ws, inp)
        out = await _ACTIONS[action](ws, inp)
    except install.InstallError as e:
        return f"Error: {e}"
    except S.SceneError as e:
        return f"Error: {e}"
    except (engine.EngineError, video.VideoError) as e:
        return f"Error: {e}"
    if installed == "installed" and isinstance(out, str):
        out += " (The Studio app was just added to the Apps tab.)"
    return out


def step(inp):
    a = str(inp.get("action") or "")
    detail = inp.get("intent") or inp.get("name") or inp.get("operation") or inp.get("path") or inp.get("format") or ""
    if a == "edit" and not inp.get("intent") and isinstance(inp.get("ops"), list):
        detail = f"{len(inp['ops'])} op(s)"
    return {"tool_name": "Studio", "step": f"{a} {detail}".strip()}

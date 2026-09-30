"""Studio, Blender side. Runs inside the warm worker (worker.py), next to
studio_scene.py — the SDK's scene.py, written there by the parent — so both
sides validate one schema.

  build(doc, jobdir)       scene document → bpy (objects tagged obj["cycls_id"])
  to_doc(prev, jobdir)     bpy → scene document (for script / import), baking
                           what the document can't express and noting it
  OPS[op](job, jobdir)     evaluate · apply · snapshot · render · export ·
                           script · import · selftest

Nothing here returns a pickle: results are out.json plus files in the job dir.
"""
import base64
import contextlib
import glob
import hashlib
import io
import json
import math
import os
import shutil
import time

import bmesh
import bpy
import numpy as np
from bpy_extras import anim_utils
from mathutils import Euler, Matrix, Quaternion, Vector

import studio_scene as S

ROOT_TMP = "/tmp"
_HDRI_CACHE = {}
_KEEP_IMAGES = set()


# ─────────────────────────────── reset ────────────────────────────────────────

def reset():
    """Empty the file between jobs (~1 ms; read_factory_settings is ~180 ms)."""
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.curves, bpy.data.worlds, bpy.data.metaballs,
                 bpy.data.node_groups, bpy.data.textures, bpy.data.actions):
        if len(coll):
            bpy.data.batch_remove(list(coll))
    stray = [im for im in bpy.data.images if im.name not in _KEEP_IMAGES]
    if stray:
        bpy.data.batch_remove(stray)
    scene = bpy.context.scene
    for c in list(scene.collection.children):
        scene.collection.children.unlink(c)


# ─────────────────────────────── mesh codec ───────────────────────────────────

def _b64(arr):
    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode()


def _unb64(s, dtype):
    return np.frombuffer(base64.b64decode(s), dtype=dtype)


def read_sidecar(data):
    """cycls.mesh JSON → bpy mesh."""
    if data.get("format") != "cycls.mesh" or data.get("version") != 1:
        raise ValueError("not a cycls.mesh v1 sidecar")
    co = _unb64(data["co"], np.float32)
    loop_start = _unb64(data["loop_start"], np.uint32).astype(np.int32)
    loops = _unb64(data["loops"], np.uint32).astype(np.int32)
    nv = len(co) // 3
    if len(loops) and int(loops.max()) >= nv:
        raise ValueError("sidecar loops index past the vertex count")
    me = bpy.data.meshes.new("mesh")
    me.vertices.add(nv)
    me.vertices.foreach_set("co", co)
    me.loops.add(len(loops))
    me.loops.foreach_set("vertex_index", loops)
    me.polygons.add(len(loop_start))
    me.polygons.foreach_set("loop_start", loop_start)
    edges = data.get("loose_edges")
    if edges:
        e = _unb64(edges, np.uint32).astype(np.int32)
        me.edges.add(len(e) // 2)
        me.edges.foreach_set("vertices", e)
    me.update(calc_edges=True)
    if data.get("uv") and len(loops):
        uv = me.uv_layers.new(name="UVMap")
        uv.data.foreach_set("uv", _unb64(data["uv"], np.float32))
    if data.get("smooth") and len(loop_start):
        me.polygons.foreach_set("use_smooth", _unb64(data["smooth"], np.uint8).astype(bool))
    if data.get("material_index") and len(loop_start):
        me.polygons.foreach_set("material_index", _unb64(data["material_index"], np.uint16).astype(np.int32))
    me.validate(clean_customdata=False)
    return me


def write_sidecar(me):
    """bpy mesh → (cycls.mesh JSON dict, id). The id hashes the geometry, so
    an unchanged mesh keeps its id and a changed one gets a new file."""
    nv, nf, nl = len(me.vertices), len(me.polygons), len(me.loops)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    ls = np.empty(nf, np.uint32)
    me.polygons.foreach_get("loop_start", ls)
    lp = np.empty(nl, np.uint32)
    me.loops.foreach_get("vertex_index", lp)
    sm = np.empty(nf, bool)
    me.polygons.foreach_get("use_smooth", sm)
    out = {"format": "cycls.mesh", "version": 1, "counts": {"verts": nv, "faces": nf, "loops": nl},
           "co": _b64(co), "loop_start": _b64(ls), "loops": _b64(lp), "smooth": _b64(sm.astype(np.uint8))}
    # Loose edges (no face uses them) — a face's edges are implied by its loops.
    ev = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ev)
    face_edges = set()
    for p in me.polygons:
        vs = p.vertices
        for i in range(len(vs)):
            a, b = vs[i], vs[(i + 1) % len(vs)]
            face_edges.add((a, b) if a < b else (b, a))
    loose = [v for i in range(0, len(ev), 2)
             for v in ((ev[i], ev[i + 1]) if (min(ev[i], ev[i + 1]), max(ev[i], ev[i + 1])) not in face_edges else ())]
    if loose:
        out["loose_edges"] = _b64(np.array(loose, np.uint32))
    uv = b""
    if me.uv_layers.active and nl:
        uvs = np.empty(nl * 2, np.float32)
        me.uv_layers.active.data.foreach_get("uv", uvs)
        out["uv"] = _b64(uvs)
        uv = uvs.tobytes()
    mi = b""
    if nf:
        mis = np.empty(nf, np.int32)
        me.polygons.foreach_get("material_index", mis)
        if mis.any():
            out["material_index"] = _b64(mis.astype(np.uint16))
            mi = mis.astype(np.uint16).tobytes()
    c = co.reshape(-1, 3) if nv else np.zeros((1, 3), np.float32)
    out["bbox"] = [c.min(0).round(6).tolist(), c.max(0).round(6).tolist()]
    # Everything written is in the name: a UV-only or material-only change is a new file.
    digest = hashlib.sha256(co.tobytes() + ls.tobytes() + lp.tobytes() + sm.astype(np.uint8).tobytes()
                            + b"uv" + uv + b"mi" + mi).hexdigest()[:12]
    return out, f"m-{digest}"


# ─────────────────────────────── primitives ───────────────────────────────────

def _torus(bm, R, r, maj, mino, uv_layer):
    """Blender's own add_torus topology (scripts/startup/bl_operators/add_mesh_torus.py),
    with its UV grid: u runs round the ring, v round the tube."""
    verts = []
    for i in range(maj):
        rot = Matrix.Rotation(2 * math.pi * i / maj, 3, "Z")
        for j in range(mino):
            a = 2 * math.pi * j / mino
            verts.append(bm.verts.new(rot @ Vector((R + math.cos(a) * r, 0.0, math.sin(a) * r))))
    n = len(verts)
    for i in range(maj):
        for j in range(mino):
            i1 = i * mino + j
            i2 = i * mino + (j + 1) % mino
            i3 = (i1 + mino) % n
            i4 = (i2 + mino) % n
            f = bm.faces.new((verts[i1], verts[i3], verts[i4], verts[i2]))
            u0, u1, v0, v1 = i / maj, (i + 1) / maj, j / mino, (j + 1) / mino
            for loop, uv in zip(f.loops, ((u0, v0), (u1, v0), (u1, v1), (u0, v1))):
                loop[uv_layer].uv = uv


def _cyclorama(bm, m, uv_layer):
    """A photo sweep: floor, a quarter-round cove, the wall. UVs run across (u) and
    along the sweep by arc length (v)."""
    prof = [(-m["depth"], 0.0), (0.0, 0.0)]
    r = m["radius"]
    for i in range(1, m["segments"] + 1):
        t = math.radians(90 * i / m["segments"])
        prof.append((r * math.sin(t), r - r * math.cos(t)))
    prof.append((r, m["height"]))
    x0, x1 = -m["width"] / 2, m["width"] / 2
    rows = [(bm.verts.new((x0, y, z)), bm.verts.new((x1, y, z))) for y, z in prof]
    run = [0.0]
    for (ya, za), (yb, zb) in zip(prof, prof[1:]):
        run.append(run[-1] + math.hypot(yb - ya, zb - za))
    for k, ((a0, a1), (b0, b1)) in enumerate(zip(rows, rows[1:])):
        f = bm.faces.new((a0, a1, b1, b0))
        v0, v1 = run[k] / run[-1], run[k + 1] / run[-1]
        for loop, uv in zip(f.loops, ((0, v0), (1, v0), (1, v1), (0, v1))):
            loop[uv_layer].uv = uv


def primitive_mesh(m):
    """A primitive as Blender's Add menu makes it — UVs included (the operators' calc_uvs)."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")          # calc_uvs writes into an existing layer
    p = m["primitive"]
    if p == "plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=m["size"] / 2, calc_uvs=True)
    elif p == "grid":
        bmesh.ops.create_grid(bm, x_segments=m["x_segments"], y_segments=m["y_segments"], size=m["size"] / 2,
                              calc_uvs=True)
    elif p == "circle":
        bmesh.ops.create_circle(bm, cap_ends=m["fill"] != "none", cap_tris=m["fill"] == "trifan",
                                segments=m["vertices"], radius=m["radius"], calc_uvs=True)
    elif p == "cube":
        bmesh.ops.create_cube(bm, size=m["size"], calc_uvs=True)
    elif p == "uv_sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=m["segments"], v_segments=m["ring_count"], radius=m["radius"],
                                  calc_uvs=True)
    elif p == "ico_sphere":
        bmesh.ops.create_icosphere(bm, subdivisions=m["subdivisions"], radius=m["radius"], calc_uvs=True)
    elif p in ("cylinder", "cone"):
        r1, r2 = (m["radius"], m["radius"]) if p == "cylinder" else (m["radius1"], m["radius2"])
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=m["vertices"],
                              radius1=r1, radius2=r2, depth=m["depth"], calc_uvs=True)
    elif p == "torus":
        _torus(bm, m["major_radius"], m["minor_radius"], m["major_segments"], m["minor_segments"], uv)
    elif p == "monkey":
        bmesh.ops.create_monkey(bm, matrix=Matrix.Scale(m["size"] / 2, 4), calc_uvs=True)
    elif p == "cyclorama":
        _cyclorama(bm, m, uv)
    else:
        raise ValueError(p)
    me = bpy.data.meshes.new(p)
    bm.to_mesh(me)
    bm.free()
    return me


def _checksum(me):
    """Did a job change this mesh? Positions, UVs and material slots all count."""
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    h = hashlib.sha256(co.tobytes())
    if me.uv_layers.active and len(me.loops):
        uv = np.empty(len(me.loops) * 2, np.float32)
        me.uv_layers.active.data.foreach_get("uv", uv)
        h.update(uv.tobytes())
    if len(me.polygons):
        mi = np.empty(len(me.polygons), np.int32)
        me.polygons.foreach_get("material_index", mi)
        h.update(mi.tobytes())
    return h.hexdigest()[:16] + f":{len(me.polygons)}"


# ─────────────────────────────── build ────────────────────────────────────────

def _texture_images(doc, jobdir):
    """The scene's images, loaded from the job's textures/ (only the ops that draw get them;
    a missing file just leaves that map off). Colour maps stay sRGB; roughness and normal
    maps get their own Non-Color copy."""
    out = {}
    for tid, t in doc.get("textures", {}).items():
        stem = os.path.basename(t["data"])[:-5]           # t-<hash>
        path = next((os.path.join(jobdir, "textures", stem + ext) for ext in (".png", ".jpg")
                     if os.path.exists(os.path.join(jobdir, "textures", stem + ext))), None)
        if path:
            out[tid] = path
    return out


def _image(path, tid, name, data):
    img = bpy.data.images.load(path, check_existing=False)
    img.name = name
    img["cycls_id"] = tid
    if data:
        img.colorspace_settings.name = "Non-Color"
    img.alpha_mode = "STRAIGHT"
    return img


def _texture_nodes(mat, bsdf, m, images, textures):
    """Image → Mapping (Blender's point order: scale, rotate, translate) → UV, into the
    Principled inputs the material names."""
    nt = mat.node_tree
    used = [f for f in S.TEXTURE_FIELDS if m.get(f) and m[f] in images]
    if not used:
        return
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.vector_type = "POINT"
    mapping.inputs["Location"].default_value = (*m["texture_offset"], 0.0)
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(m["texture_rotation"]))
    mapping.inputs["Scale"].default_value = (*m["texture_scale"], 1.0)
    nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])
    for f in used:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = _image(images[m[f]], m[f], textures[m[f]]["name"], data=f != "base_color_texture")
        nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        if f == "base_color_texture":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            if textures[m[f]]["alpha"]:
                nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        elif f == "roughness_texture":
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Roughness"])
        else:
            nm = nt.nodes.new("ShaderNodeNormalMap")
            nm.inputs["Strength"].default_value = m["normal_strength"]
            nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
            nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])


def _principled(name, m, images=None, textures=None):
    mat = bpy.data.materials.new(name)
    with contextlib.suppress(Exception):
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None) or nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    rgba = (*S.hex_to_linear(m["base_color"]), 1.0)

    def put(names, value):
        for n in names:
            if n in bsdf.inputs:
                bsdf.inputs[n].default_value = value
                return
    put(("Base Color",), rgba)
    put(("Metallic",), m["metallic"])
    put(("Roughness",), m["roughness"])
    put(("IOR",), m["ior"])
    put(("Alpha",), m["alpha"])
    put(("Coat Weight", "Coat"), m["coat"])
    put(("Transmission Weight", "Transmission"), m["transmission"])
    if m["emission"]:
        put(("Emission Color", "Emission"), rgba)
        put(("Emission Strength",), m["emission"])
    mat.diffuse_color = rgba
    if images:
        _texture_nodes(mat, bsdf, m, images, textures)
    return mat


def _shade(me, shading, explicit):
    if shading == "flat":
        me.shade_flat()
    elif shading == "smooth":
        me.shade_smooth()
    elif not explicit:                         # auto on a primitive: smooth, sharp past 30°
        me.shade_smooth()
        with contextlib.suppress(Exception):
            me.set_sharp_from_angle(angle=math.radians(30))


def _modifier(ob, mod, objs):
    t = mod["type"]
    kind = {"subsurf": "SUBSURF", "bevel": "BEVEL", "mirror": "MIRROR", "array": "ARRAY",
            "solidify": "SOLIDIFY", "boolean": "BOOLEAN", "remesh": "REMESH", "decimate": "DECIMATE",
            "weld": "WELD", "triangulate": "TRIANGULATE", "wireframe": "WIREFRAME"}[t]
    md = ob.modifiers.new(t, kind)
    md.show_viewport = md.show_render = mod["show"]
    if t == "subsurf":
        md.levels, md.render_levels = mod["levels"], mod["render_levels"]
    elif t == "bevel":
        md.width, md.segments = mod["width"], mod["segments"]
        md.limit_method = mod["limit_method"].upper()
        md.angle_limit = math.radians(mod["angle_limit"])
    elif t == "mirror":
        md.use_axis[0], md.use_axis[1], md.use_axis[2] = mod["axis"]
        md.use_clip = mod["use_clip"]
        if mod["mirror_object"]:
            md.mirror_object = objs[mod["mirror_object"]]
    elif t == "array":
        md.count = mod["count"]
        md.relative_offset_displace = mod["relative_offset"]
    elif t == "solidify":
        md.thickness, md.offset = mod["thickness"], mod["offset"]
    elif t == "boolean":
        md.operation = mod["operation"].upper()
        md.object = objs[mod["object"]]
        with contextlib.suppress(Exception):
            md.solver = mod["solver"].upper()
    elif t == "remesh":
        md.mode = "VOXEL"
        md.voxel_size = mod["voxel_size"]
    elif t == "decimate":
        md.ratio = mod["ratio"]
    elif t == "weld":
        md.merge_threshold = mod["merge_threshold"]
    elif t == "wireframe":
        md.thickness = mod["thickness"]
    return md


def _light(o):
    lt = o["light"]
    data = bpy.data.lights.new(o["name"], lt["kind"].upper())
    data.energy = lt["energy"]
    data.color = S.hex_to_linear(lt["color"])
    if lt["kind"] in ("point", "spot"):
        data.shadow_soft_size = lt["radius"]
    if lt["kind"] == "spot":
        data.spot_size = math.radians(lt["spot_size"])
        data.spot_blend = lt["spot_blend"]
    if lt["kind"] == "sun":
        data.angle = math.radians(lt["angle"])
    if lt["kind"] == "area":
        data.shape = lt["shape"].upper()
        data.size = lt["size"]
        data.size_y = lt["size_y"]
    return data


def _camera(o):
    c = o["camera"]
    data = bpy.data.cameras.new(o["name"])
    data.type = c["projection"].upper()
    data.lens, data.sensor_width, data.sensor_fit = c["lens"], c["sensor_width"], "AUTO"
    data.ortho_scale = c["ortho_scale"]
    data.clip_start, data.clip_end = c["clip_start"], c["clip_end"]
    data.dof.use_dof = c["dof_fstop"] > 0
    if c["dof_fstop"] > 0:
        data.dof.aperture_fstop = c["dof_fstop"]
    return data


def _text(o):
    t = o["text"]
    data = bpy.data.curves.new(o["name"], "FONT")
    data.body = t["body"]
    data.size, data.extrude = t["size"], t["extrude"]
    data.bevel_depth, data.bevel_resolution = t["bevel_depth"], t["bevel_resolution"]
    data.align_x = t["align"].upper()
    data.align_y = "CENTER"
    return data


def _world(w):
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    with contextlib.suppress(Exception):
        world.use_nodes = True
    nt = world.node_tree
    bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None) or nt.nodes.new("ShaderNodeBackground")
    out = next((n for n in nt.nodes if n.type == "OUTPUT_WORLD"), None) or nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bg.inputs["Strength"].default_value = w["strength"]
    if w["kind"] == "hdri":
        path = os.path.join(bpy.utils.system_resource("DATAFILES", path="studiolights/world"), f"{w['hdri']}.exr")
        if os.path.exists(path):
            img = _HDRI_CACHE.get(path)
            if img is None or img.name not in bpy.data.images:
                img = bpy.data.images.load(path, check_existing=True)
                _HDRI_CACHE[path] = img
                _KEEP_IMAGES.add(img.name)
            env = nt.nodes.new("ShaderNodeTexEnvironment")
            env.image = img
            if w["rotation"]:
                coord = nt.nodes.new("ShaderNodeTexCoord")
                mapping = nt.nodes.new("ShaderNodeMapping")
                mapping.inputs["Rotation"].default_value[2] = math.radians(w["rotation"])
                nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
                nt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
            nt.links.new(env.outputs["Color"], bg.inputs["Color"])
            return
    bg.inputs["Color"].default_value = (*S.hex_to_linear(w["color"]), 1.0)


def build(doc, jobdir):
    """Scene document → bpy. Returns {id: object}."""
    reset()
    doc = S.normalize(doc)
    scene = bpy.context.scene
    mats = {}
    images = _texture_images(doc, jobdir)
    for mid, m in doc["materials"].items():
        mats[mid] = _principled(m["name"], m, images, doc["textures"])
        mats[mid]["cycls_id"] = mid
    meshes = {}
    for mid, m in doc["meshes"].items():
        if "primitive" in m:
            me = primitive_mesh(m)
            me["cycls_primitive"] = mid
        else:
            with open(os.path.join(jobdir, "meshes", os.path.basename(m["data"]))) as f:
                me = read_sidecar(json.load(f))
            me["cycls_explicit"] = mid
        me["cycls_sum"] = _checksum(me)
        meshes[mid] = me
    objs = {}
    for oid, o in doc["objects"].items():
        t = o["type"]
        data = (meshes[o["mesh"]] if t == "mesh" else _light(o) if t == "light" else
                _camera(o) if t == "camera" else _text(o) if t == "text" else None)
        ob = bpy.data.objects.new(o["name"], data)
        ob["cycls_id"] = oid
        scene.collection.objects.link(ob)
        objs[oid] = ob
    for oid, o in doc["objects"].items():
        ob = objs[oid]
        if o["parent"]:
            ob.parent = objs[o["parent"]]
            ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.rotation_mode = "XYZ"
        ob.location, ob.rotation_euler, ob.scale = o["location"], [math.radians(a) for a in o["rotation"]], o["scale"]
        ob.hide_viewport = not o["visible"]
        ob.hide_render = not (o["visible"] and o["renderable"])
        if o["type"] in ("mesh", "text"):
            if o["type"] == "mesh":
                _shade(ob.data, o["shading"], "data" in doc["meshes"][o["mesh"]])
            for i, mid in enumerate(o["materials"]):          # slots; a face's material_index picks one
                if len(ob.material_slots) <= i:
                    ob.data.materials.append(None)
                ob.material_slots[i].link = "OBJECT"
                ob.material_slots[i].material = mats[mid] if mid else None
            for mod in o["modifiers"]:
                _modifier(ob, mod, objs)
        if o["type"] == "camera" and o["dof_focus"]:
            ob.data.dof.focus_object = objs[o["dof_focus"]]
    _world(doc["world"])
    if doc["render"]["camera"]:
        scene.camera = objs[doc["render"]["camera"]]
    if _animate(doc, objs):
        scene.frame_set(doc["animation"]["frame_start"])
    else:
        bpy.context.view_layer.update()
    return objs


_PATH = {"location": "location", "rotation": "rotation_euler", "scale": "scale"}
_INTERP = {"bezier": "BEZIER", "linear": "LINEAR", "constant": "CONSTANT"}


def _animate(doc, objs):
    """The timeline, and keys as F-curves the way the document's evaluator reads them
    (scene.py `sample`): the key's interpolation for the segment it starts, AUTO_CLAMPED
    handles with auto-smoothing off (new curves smooth by default), constant extrapolation.
    Blender 5's actions are layered: curves live in a slot's channelbag. Any keys at all?"""
    a, scene = doc["animation"], bpy.context.scene
    scene.render.fps, scene.render.fps_base = a["fps"], 1.0
    scene.frame_start, scene.frame_end = a["frame_start"], a["frame_end"]
    scene.frame_current = a["frame_start"]
    keyed = False
    for oid, o in doc["objects"].items():
        if not o.get("keys"):
            continue
        ob = objs[oid]
        act = bpy.data.actions.new(f"{o['name']}Action")
        slot = act.slots.new(id_type="OBJECT", name=ob.name)
        ad = ob.animation_data_create()
        ad.action = act
        ad.action_slot = slot
        bag = anim_utils.action_ensure_channelbag_for_slot(act, slot)
        for ch, ks in o["keys"].items():
            for c in range(3):
                fc = bag.fcurves.new(_PATH[ch], index=c)
                fc.auto_smoothing = "NONE"
                fc.keyframe_points.add(len(ks))
                for kp, (f, v, interp) in zip(fc.keyframe_points, ks):
                    kp.co = (f, math.radians(v[c]) if ch == "rotation" else v[c])
                    kp.interpolation = _INTERP[interp]
                    kp.handle_left_type = kp.handle_right_type = "AUTO_CLAMPED"
                fc.update()                      # sorted, handles computed
        keyed = True
    return keyed


def _render_settings(doc, resolution, samples, png):
    scene = bpy.context.scene
    r = scene.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y = resolution
    r.resolution_percentage = 100
    r.film_transparent = doc["render"]["transparent"]
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA" if doc["render"]["transparent"] else "RGB"
    r.image_settings.compression = 40
    r.filepath = png
    cy = scene.cycles
    cy.device = "CPU"
    cy.samples = samples
    cy.use_adaptive_sampling = True
    for attr, val in (("use_denoising", doc["render"]["denoise"]), ("denoiser", "OPENIMAGEDENOISE"),
                      ("max_bounces", 10), ("glossy_bounces", 6), ("transmission_bounces", 10),
                      ("caustics_reflective", False), ("caustics_refractive", False),
                      ("sample_clamp_indirect", 8.0)):
        with contextlib.suppress(Exception):
            setattr(cy, attr, val)
    for transform, look in (("Khronos PBR Neutral", "None"), ("AgX", "AgX - Medium High Contrast")):
        try:
            scene.view_settings.view_transform = transform
            scene.view_settings.look = look
            break
        except Exception:
            pass


def _preview(png, jpg, longest=768):
    img = bpy.data.images.load(png)
    w, h = img.size
    k = longest / max(w, h)
    if k < 1:
        img.scale(max(1, int(w * k)), max(1, int(h * k)))
    img.file_format = "JPEG"
    img.filepath_raw = jpg
    img.save()
    bpy.data.images.remove(img)


# ─────────────────────────────── bpy → document ───────────────────────────────

_KIND = {"POINT": "point", "SUN": "sun", "SPOT": "spot", "AREA": "area"}
_MODS_BACK = {"SUBSURF": "subsurf", "BEVEL": "bevel", "MIRROR": "mirror", "ARRAY": "array",
              "SOLIDIFY": "solidify", "BOOLEAN": "boolean", "REMESH": "remesh", "DECIMATE": "decimate",
              "WELD": "weld", "TRIANGULATE": "triangulate", "WIREFRAME": "wireframe"}


def _hex_of(linear):
    return S._lin_to_hex([max(0.0, min(1.0, c)) for c in linear[:3]])


_MAX_TEXTURE = 2048


def _image_bytes(img):
    """An image's file bytes as PNG or JPEG, at most 2048 px on a side, never through the
    view transform. Packed (a glb's) or on-disk files pass through as they are."""
    w, h = img.size
    ext = {"PNG": "png", "JPEG": "jpg"}.get(img.file_format)
    if ext and max(w, h) <= _MAX_TEXTURE:
        if img.packed_file:
            return bytes(img.packed_file.data), ext
        path = bpy.path.abspath(img.filepath)
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read(), ext
    copy_ = img.copy()
    if max(w, h) > _MAX_TEXTURE:
        k = _MAX_TEXTURE / max(w, h)
        copy_.scale(max(1, round(w * k)), max(1, round(h * k)))
    alpha = _has_alpha(copy_)
    ext = "png" if alpha else "jpg"
    path = os.path.join(ROOT_TMP, f"texture-{os.getpid()}.{ext}")
    copy_.filepath_raw = path
    copy_.file_format = "PNG" if alpha else "JPEG"
    copy_.save(quality=90) if not alpha else copy_.save()
    bpy.data.images.remove(copy_)
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data, ext


def _has_alpha(img):
    if img.channels < 4 or img.alpha_mode == "NONE":
        return False
    px = np.empty(len(img.pixels), np.float32)
    img.pixels.foreach_get(px)
    return bool(len(px) and px[3::4].min() < 0.999)


def _image_back(node, field, textures_out, doc, notes, mat):
    """A texture entry for the image a Principled input reads, written to textures_out/."""
    img = node.image
    if img is None:
        return None
    try:
        data, ext = _image_bytes(img)
    except Exception as e:                              # unreadable (missing file, odd format)
        notes.append(f"material {mat.name!r}: image {img.name!r} couldn't be read ({e}) — left off")
        return None
    digest = hashlib.sha256(data).hexdigest()[:12]
    with open(os.path.join(textures_out, f"t-{digest}.{ext}"), "wb") as f:
        f.write(data)
    tid = img.get("cycls_id") or _free_id(img.name, doc["textures"])
    if tid not in doc["textures"]:
        w, h = img.size
        if max(w, h) > _MAX_TEXTURE:
            k = _MAX_TEXTURE / max(w, h)
            w, h = max(1, round(w * k)), max(1, round(h * k))
        doc["textures"][tid] = {"name": img.name[:64], "data": f"textures/t-{digest}.json", "width": w,
                                "height": h, "alpha": field == "base_color_texture" and _has_alpha(img)}
    return tid


def _free_id(base, taken):
    base = "".join(c if c.isalnum() or c in "_.-" else "_" for c in base.lower()).strip("_.-")[:48] or "texture"
    cand, n = base, 2
    while cand in taken:
        cand, n = f"{base}_{n}", n + 1
    return cand


def _linked_image(sock):
    """The Image Texture node feeding a socket — directly, or through a Normal Map node."""
    if not sock.is_linked:
        return None, None
    node = sock.links[0].from_node
    if node.type == "NORMAL_MAP" and node.inputs["Color"].is_linked:
        return node.inputs["Color"].links[0].from_node if node.inputs["Color"].links[0].from_node.type == "TEX_IMAGE" \
            else None, node
    return (node if node.type == "TEX_IMAGE" else None), None


def _mapping_back(tex, out, notes, mat):
    """Texture placement from a Mapping node between the UVs and the image."""
    v = tex.inputs["Vector"]
    if not v.is_linked:
        return
    node = v.links[0].from_node
    if node.type == "MAPPING" and node.vector_type == "POINT":
        loc, rot, scl = (node.inputs[k].default_value for k in ("Location", "Rotation", "Scale"))
        out["texture_offset"] = [round(loc[0], 6), round(loc[1], 6)]
        out["texture_rotation"] = round(math.degrees(rot[2]), 4)
        out["texture_scale"] = [round(scl[0], 6), round(scl[1], 6)]
    elif node.type not in ("TEX_COORD", "UVMAP"):
        notes.append(f"material {mat.name!r}: image coordinates come from {node.type.lower()} — kept plain UVs")


INSTANCE_SET_MAX = 2000        # one instancer's repeats that come in as objects
BAKE_MAX = 80                  # node-driven inputs averaged per job (a few tenths of a second each)
_bakes = {"n": 0}


def _mean_of(mat, sock):
    """What a node-driven input averages to: its network baked as emission onto a small plane
    (generated coordinates span it, so a procedural texture shows its range; UVs span an image)
    and the pixels averaged. Linear RGB, or None if Blender can't bake it."""
    if _bakes["n"] >= BAKE_MAX or not sock.is_linked:
        return None
    _bakes["n"] += 1
    tree = mat.node_tree
    outs = [n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"]
    out_node = next((n for n in outs if n.is_active_output), outs[0] if outs else None)
    if out_node is None:
        _bakes["error"] = "no material output"
        return None
    was = out_node.inputs["Surface"].links[0].from_socket if out_node.inputs["Surface"].is_linked else None
    emit, holder = tree.nodes.new("ShaderNodeEmission"), tree.nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.new("_bake", 16, 16, float_buffer=True)
    holder.image = img
    me = bpy.data.meshes.new("_bake")
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")                      # calc_uvs fills it; the bake needs one
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=1, calc_uvs=True)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new("_bake", me)
    # A scene of its own: Cycles prepares every object in the scene it bakes in, and the file's
    # own may be thousands.
    sc = bpy.data.scenes.new("_bake")
    sc.render.engine = "CYCLES"
    sc.cycles.device, sc.cycles.samples = "CPU", 1
    sc.collection.objects.link(ob)
    vl = sc.view_layers[0]
    try:
        tree.links.new(sock.links[0].from_socket, emit.inputs["Color"])
        tree.links.new(emit.outputs["Emission"], out_node.inputs["Surface"])
        tree.nodes.active = holder
        with bpy.context.temp_override(scene=sc, view_layer=vl, object=ob, active_object=ob,
                                       selected_objects=[ob], selected_editable_objects=[ob]):
            ob.select_set(True, view_layer=vl)
            vl.objects.active = ob
            bpy.ops.object.bake(type="EMIT", width=16, height=16, margin=0, use_clear=True)
        px = np.empty(16 * 16 * 4, np.float32)
        img.pixels.foreach_get(px)
        return [float(v) for v in px.reshape(-1, 4)[:, :3].mean(axis=0)]
    except Exception as e:
        _bakes["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return None
    finally:
        tree.nodes.remove(emit)
        tree.nodes.remove(holder)
        if was is not None:
            tree.links.new(was, out_node.inputs["Surface"])
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
        bpy.data.images.remove(img)
        bpy.data.scenes.remove(sc)


def _material_back(mat, notes, doc=None, textures_out=None):
    out = {"name": mat.name[:64], "base_color": _hex_of(mat.diffuse_color), "metallic": 0.0,
           "roughness": 0.5}
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.node_tree else None
    if bsdf is None:
        notes.append(f"material {mat.name!r}: not a Principled BSDF — kept its viewport colour")
        return out

    kept = set()                                        # inputs an image map now carries
    if doc is not None:
        mapped = False
        for field, sock_name in (("base_color_texture", "Base Color"), ("roughness_texture", "Roughness"),
                                 ("normal_texture", "Normal")):
            if sock_name not in bsdf.inputs:
                continue
            tex, nmap = _linked_image(bsdf.inputs[sock_name])
            if tex is None:
                continue
            tid = _image_back(tex, field, textures_out, doc, notes, mat)
            if tid is None:
                continue
            out[field] = tid
            kept.add(sock_name)
            if nmap is not None:
                out["normal_strength"] = round(float(nmap.inputs["Strength"].default_value), 5)
            if not mapped:
                _mapping_back(tex, out, notes, mat)
                mapped = True
        if "Base Color" in kept and bsdf.inputs["Alpha"].is_linked:
            kept.add("Alpha")

    def get(names, default):
        for n in names:
            if n in bsdf.inputs:
                if bsdf.inputs[n].is_linked and n not in kept:
                    mean = _mean_of(mat, bsdf.inputs[n]) if n in ("Base Color", "Roughness", "Metallic") else None
                    if mean is not None:
                        notes.append(f"material {mat.name!r}: {n} is driven by nodes — used its baked average")
                        return mean + [1.0] if n == "Base Color" else mean[0]
                    notes.append(f"material {mat.name!r}: {n} is driven by nodes — kept its plain value"
                                 + (f" (bake: {_bakes['error']})" if _bakes.get("error") else ""))
                return bsdf.inputs[n].default_value
        return default
    out["base_color"] = "#ffffff" if "Base Color" in kept else _hex_of(list(get(("Base Color",), (0.8, 0.8, 0.8, 1))))
    for key, names, lo, hi in (("metallic", ("Metallic",), 0, 1), ("roughness", ("Roughness",), 0, 1),
                               ("ior", ("IOR",), 1, 3), ("alpha", ("Alpha",), 0, 1),
                               ("coat", ("Coat Weight", "Coat"), 0, 1),
                               ("transmission", ("Transmission Weight", "Transmission"), 0, 1),
                               ("emission", ("Emission Strength",), 0, 100)):
        out[key] = round(min(hi, max(lo, float(get(names, 0.0)))), 5)
    return out


def _local_trs(ob):
    local = (ob.parent.matrix_world.inverted() @ ob.matrix_world) if ob.parent else ob.matrix_world.copy()
    loc, rot, scl = local.decompose()
    e = rot.to_euler("XYZ")
    return ([round(v, 6) for v in loc], [round(math.degrees(a), 5) for a in e], [round(v, 6) for v in scl])


def _volume_only(mat):
    """A volume — haze, fog, smoke — with no surface. The document has no volumes, and as a
    surface it would be a solid box round everything inside it."""
    tree = getattr(mat, "node_tree", None) if mat else None
    for n in tree.nodes if tree else []:
        if n.type == "OUTPUT_MATERIAL" and n.is_active_output:
            return not n.inputs["Surface"].is_linked and n.inputs["Volume"].is_linked
    return False


def to_doc(prev, jobdir, notes):
    """bpy → scene document. Keeps ids tagged by build(); gives new objects ids
    from their names. Meshes a job changed become explicit sidecars written to
    jobdir/meshes_out/, primitives it left alone stay primitives."""
    prev = S.normalize(prev)
    _bakes["n"] = 0
    doc = {"objects": {}, "meshes": {}, "materials": {}, "textures": {}, "world": prev["world"],
           "render": dict(prev["render"]), "animation": dict(prev["animation"])}
    os.makedirs(os.path.join(jobdir, "meshes_out"), exist_ok=True)
    textures_out = os.path.join(jobdir, "textures_out")
    os.makedirs(textures_out, exist_ok=True)
    used = set()

    def new_id(base, section):
        base = "".join(c if c.isalnum() or c in "_.-" else "_" for c in base.lower()).strip("_.-")[:48] or section
        cand, n = base, 2
        while cand in used or cand in doc[section]:
            cand, n = f"{base}_{n}", n + 1
        return cand

    mat_ids = {}
    ob_ids = {}
    sidecars = {}                  # mesh datablock → its entry: objects sharing a mesh share one file
    for ob in bpy.context.scene.objects:
        oid = ob.get("cycls_id")
        if not oid or oid in used:
            oid = new_id(ob.name, "objects")
        used.add(oid)
        ob_ids[ob.name] = oid
    dg = bpy.context.evaluated_depsgraph_get()
    for ob in list(bpy.context.scene.objects):
        oid = ob_ids[ob.name]
        loc, rot, scl = _local_trs(ob)
        o = {"name": ob.name[:64], "parent": ob_ids.get(ob.parent.name) if ob.parent else None,
             "location": loc, "rotation": rot, "scale": scl, "visible": not ob.hide_viewport,
             "renderable": not ob.hide_render}
        if len(getattr(ob, "particle_systems", ())) or ob.instance_type != "NONE":
            # a particle emitter, a duplicator: Blender draws the instances, not it, unless told to
            o["renderable"] = o["renderable"] and ob.show_instancer_for_render
            o["visible"] = o["visible"] and ob.show_instancer_for_viewport
        kind = ob.type
        if kind == "LIGHT" and ob.data.type in _KIND:
            d = ob.data
            lt = {"kind": _KIND[d.type], "energy": round(d.energy, 4), "color": _hex_of(d.color)}
            if d.type in ("POINT", "SPOT"):
                lt["radius"] = round(d.shadow_soft_size, 5)
            if d.type == "SPOT":
                lt["spot_size"], lt["spot_blend"] = round(math.degrees(d.spot_size), 4), round(d.spot_blend, 4)
            if d.type == "SUN":
                lt["angle"] = round(math.degrees(d.angle), 4)
            if d.type == "AREA":
                lt["shape"] = d.shape.lower()
                lt["size"], lt["size_y"] = round(d.size, 5), round(d.size_y, 5)
            o.update(type="light", light=lt)
        elif kind == "CAMERA":
            d = ob.data
            o.update(type="camera", camera={
                "projection": "ortho" if d.type == "ORTHO" else "persp", "lens": round(d.lens, 4),
                "sensor_width": round(d.sensor_width, 4), "ortho_scale": round(d.ortho_scale, 4),
                "clip_start": round(max(d.clip_start, 1e-4), 5), "clip_end": round(d.clip_end, 3),
                "dof_fstop": round(d.dof.aperture_fstop, 4) if d.dof.use_dof else 0.0})
            if d.dof.use_dof and d.dof.focus_object:
                o["dof_focus"] = ob_ids.get(d.dof.focus_object.name)
        elif kind == "EMPTY":
            o["type"] = "empty"
        elif kind == "FONT" and len(ob.data.body) <= 200 and ob.data.body:
            d = ob.data
            o.update(type="text", text={"body": d.body, "size": round(d.size, 5), "extrude": round(d.extrude, 5),
                                        "bevel_depth": round(d.bevel_depth, 5),
                                        "bevel_resolution": d.bevel_resolution,
                                        "align": d.align_x.lower() if d.align_x in ("LEFT", "CENTER", "RIGHT") else "center"})
        elif kind in ("MESH", "CURVE", "SURFACE", "META", "FONT"):
            o["type"] = "mesh"
            mods, bake = [], kind != "MESH"
            if kind == "MESH":
                for md in ob.modifiers:
                    t = _MODS_BACK.get(md.type)
                    if t is None or (t == "boolean" and (not md.object or md.object.name not in ob_ids)):
                        bake = True
                        break
                    mods.append(_mod_back(t, md, ob_ids))
            if bake:
                me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=False,
                                                     depsgraph=dg)
                notes.append(f"{oid}: {kind.lower()} with unsupported modifiers/data — baked to a mesh")
                mods = []
            else:
                me = ob.data
            prim = me.get("cycls_primitive") if not bake else None
            if prim and prim in prev["meshes"] and me.get("cycls_sum") == _checksum(me):
                doc["meshes"][prim] = prev["meshes"][prim]
                o["mesh"] = prim
            elif not bake and me.as_pointer() in sidecars:
                o["mesh"], doc["meshes"][o["mesh"]] = sidecars[me.as_pointer()]
            else:
                sidecar, mid = write_sidecar(me)
                with open(os.path.join(jobdir, "meshes_out", f"{mid}.json"), "w") as f:
                    json.dump(sidecar, f)
                doc["meshes"][mid] = {"data": f"meshes/{mid}.json", "verts": sidecar["counts"]["verts"],
                                      "faces": sidecar["counts"]["faces"], "bbox": sidecar["bbox"]}
                o["mesh"] = mid
                if not bake:
                    sidecars[me.as_pointer()] = (mid, doc["meshes"][mid])
            o["modifiers"] = mods
            o["shading"] = "auto"
        else:
            o["type"] = "empty"
            notes.append(f"{oid}: {kind.lower()} objects aren't supported — kept as an empty")
        if o["type"] in ("mesh", "text"):
            slots = []
            for slot in ob.material_slots[:S.MAX_SLOTS]:
                mat = slot.material
                if mat is not None and mat.name not in mat_ids:
                    mid = mat.get("cycls_id") or new_id(mat.name, "materials")
                    mat_ids[mat.name] = mid
                    doc["materials"][mid] = _material_back(mat, notes, doc, textures_out)
                slots.append(mat_ids[mat.name] if mat is not None else None)
            o["materials"] = slots
            mats = [sl.material for sl in ob.material_slots if sl.material]
            if mats and all(_volume_only(m) for m in mats):
                o["visible"] = o["renderable"] = False
                notes.append(f"{oid}: a volume (haze, fog, smoke) — the Studio has no volumes, so it's hidden")
            if len(ob.material_slots) > S.MAX_SLOTS:
                notes.append(f"{oid}: {len(ob.material_slots)} material slots — the first {S.MAX_SLOTS} are kept")
        keys = _keys_back(ob, oid, notes)
        if keys:
            o["keys"] = keys
        doc["objects"][oid] = o
    sc = bpy.context.scene
    cam = sc.camera
    doc["render"]["camera"] = ob_ids.get(cam.name) if cam and cam.name in ob_ids else None
    start = max(0, min(S.MAX_FRAME, sc.frame_start))
    doc["animation"] = {"fps": max(1, min(120, round(sc.render.fps / (sc.render.fps_base or 1.0)))),
                        "frame_start": start, "frame_end": max(start, min(S.MAX_FRAME, sc.frame_end))}
    return S.normalize(doc)


_CHANNEL = {"location": "location", "rotation_euler": "rotation", "rotation_quaternion": "rotation",
            "rotation_axis_angle": "rotation", "scale": "scale"}
_INTERP_BACK = {v: k for k, v in _INTERP.items()}


def _basis_at(ob, by_path, f):
    """The object's own transform at frame f: its curves where it has them, its
    properties where it doesn't."""
    def vals(path, n):
        cur = getattr(ob, path)
        return [by_path[path][i].evaluate(f) if i in by_path.get(path, {}) else cur[i] for i in range(n)]
    mode = ob.rotation_mode
    if mode == "QUATERNION":
        rot = Quaternion(vals("rotation_quaternion", 4)).normalized()
    elif mode == "AXIS_ANGLE":
        w, x, y, z = vals("rotation_axis_angle", 4)
        rot = Quaternion((x, y, z), w)
    else:
        rot = Euler(vals("rotation_euler", 3), mode).to_quaternion()
    return Matrix.LocRotScale(Vector(vals("location", 3)), rot, Vector(vals("scale", 3)))


def _keys_back(ob, oid, notes):
    """An object's F-curves as the document's keys. The Studio's own (XYZ Euler, no parent
    offset) come back key for key; any other kind is re-keyed at its keys through the
    object's local matrix. What the document's curves can't say — easings, hand-set
    handles, keys between frames, curve modifiers — is noted, not refused."""
    ad = ob.animation_data
    act, slot, shift = (ad.action, ad.action_slot, 0.0) if ad else (None, None, 0.0)
    odd = set()
    if ad is not None and act is None:
        # A glTF import makes an action per object but parks all but one on the NLA.
        strip = next((st for tr in ad.nla_tracks for st in tr.strips if st.action), None)
        if strip is not None:
            act, slot = strip.action, getattr(strip, "action_slot", None)
            shift = strip.frame_start - strip.action_frame_start
            if abs(strip.scale - 1) > 1e-6 or abs(strip.repeat - 1) > 1e-6:
                odd.add("a scaled or repeated NLA strip (taken once, unscaled)")
    if act is not None and slot is None and len(act.slots) == 1:
        slot = act.slots[0]
    bag = None
    if act is not None and slot is not None:
        with contextlib.suppress(Exception):
            bag = anim_utils.action_get_channelbag_for_slot(act, slot)
    if ad and len(ad.drivers):
        notes.append(f"{oid}: drivers aren't carried")
    if bag is None:
        return None
    by_path, chans, other = {}, {}, set()
    for fc in bag.fcurves:
        ch = _CHANNEL.get(fc.data_path)
        if ch is None:
            other.add(fc.data_path.rsplit(".", 1)[-1])
            continue
        if not len(fc.keyframe_points):
            continue
        by_path.setdefault(fc.data_path, {})[fc.array_index] = fc
        chans.setdefault(ch, []).append(fc)
        if fc.auto_smoothing != "NONE" and any(kp.interpolation == "BEZIER" for kp in fc.keyframe_points):
            odd.add("smoothed handles")
        if len(fc.modifiers):
            odd.add("curve modifiers (cycles, noise…)")
        if fc.extrapolation != "CONSTANT":
            odd.add("extrapolation past its keys")
        for kp in fc.keyframe_points:
            if kp.interpolation not in _INTERP_BACK:
                odd.add(f"{kp.interpolation.lower()} easing")
            elif kp.interpolation == "BEZIER" and not (kp.handle_left_type == kp.handle_right_type == "AUTO_CLAMPED"):
                odd.add("hand-set handles")
            if abs(kp.co.x + shift - round(kp.co.x + shift)) > 1e-3:
                odd.add("keys between frames")
    if other:
        notes.append(f"{oid}: animated {', '.join(sorted(other)[:4])} isn't carried — only location, rotation, scale")
    if not chans:
        return None
    mpi = ob.matrix_parent_inverse if ob.parent else None
    offset = mpi is not None and any(abs(mpi[i][j] - (i == j)) > 1e-6 for i in range(4) for j in range(4))
    direct = not offset and ob.rotation_mode == "XYZ" and set(by_path) <= {"location", "rotation_euler", "scale"}
    frame = lambda x: min(S.MAX_FRAME, max(0, round(x + shift)))          # noqa: E731
    frames_of = {ch: sorted({frame(kp.co.x) for fc in fcs for kp in fc.keyframe_points}) for ch, fcs in chans.items()}

    def interp_at(fcs, f):
        for fc in fcs:
            for kp in fc.keyframe_points:
                if frame(kp.co.x) == f:
                    return _INTERP_BACK.get(kp.interpolation, "bezier")
        return "bezier"

    keys = {}
    if direct:
        for ch, fcs in chans.items():
            comps = {fc.array_index: fc for fc in fcs}
            cur = getattr(ob, _PATH[ch])
            keys[ch] = []
            for f in frames_of[ch]:
                v = [comps[c].evaluate(f - shift) if c in comps else cur[c] for c in range(3)]
                if ch == "rotation":
                    v = [math.degrees(x) for x in v]
                keys[ch].append([f, [round(x, 6) for x in v], interp_at(fcs, f)])
    else:
        why = ("under a parent offset" if offset else "as quaternions" if ob.rotation_mode == "QUATERNION"
               else "as an axis and angle" if ob.rotation_mode == "AXIS_ANGLE" else f"in {ob.rotation_mode} order")
        notes.append(f"{oid}: its motion was re-keyed as XYZ Euler at its keys (Blender stored it {why})")
        prev_e = None
        for f in sorted({f for fs in frames_of.values() for f in fs}):
            m = _basis_at(ob, by_path, f - shift)
            loc, q, scl = ((mpi @ m) if offset else m).decompose()
            e = q.to_euler("XYZ", prev_e) if prev_e is not None else q.to_euler("XYZ")
            prev_e = e
            v = {"location": list(loc), "rotation": [math.degrees(a) for a in e], "scale": list(scl)}
            for ch, fcs in chans.items():
                if f in frames_of[ch]:
                    keys.setdefault(ch, []).append([f, [round(x, 6) for x in v[ch]], interp_at(fcs, f)])
    for ch, ks in keys.items():
        if len(ks) > S.MAX_KEYS:                       # a key every frame for minutes: thinned evenly
            step = (len(ks) - 1) / (S.MAX_KEYS - 1)
            keys[ch] = [ks[round(i * step)] for i in range(S.MAX_KEYS)]
            odd.add(f"{len(ks)} keys on {ch} (thinned to {S.MAX_KEYS})")
    if odd:
        notes.append(f"{oid}: its keys ease the Studio's way now (auto-clamped Bézier) — the file had "
                     + ", ".join(sorted(odd)))
    return keys


def _mod_back(t, md, ob_ids):
    m = {"type": t, "show": bool(md.show_render)}
    if t == "subsurf":
        m.update(levels=min(6, md.levels), render_levels=min(6, md.render_levels))
    elif t == "bevel":
        m.update(width=md.width, segments=md.segments,
                 limit_method="angle" if md.limit_method == "ANGLE" else "none",
                 angle_limit=round(math.degrees(md.angle_limit), 4))
    elif t == "mirror":
        m.update(axis=[bool(a) for a in md.use_axis], use_clip=md.use_clip,
                 mirror_object=ob_ids.get(md.mirror_object.name) if md.mirror_object else None)
    elif t == "array":
        m.update(count=md.count, relative_offset=list(md.relative_offset_displace))
    elif t == "solidify":
        m.update(thickness=md.thickness, offset=md.offset)
    elif t == "boolean":
        m.update(operation=md.operation.lower(), object=ob_ids[md.object.name],
                 solver="fast" if getattr(md, "solver", "EXACT") == "FAST" else "exact")
    elif t == "remesh":
        m.update(voxel_size=md.voxel_size)
    elif t == "decimate":
        m.update(ratio=md.ratio)
    elif t == "weld":
        m.update(merge_threshold=md.merge_threshold)
    elif t == "wireframe":
        m.update(thickness=md.thickness)
    # Blender stores float32; round so an untouched value reads back as written.
    return {k: (round(v, 6) if isinstance(v, float) else [round(x, 6) for x in v]
                if isinstance(v, list) and v and isinstance(v[0], float) else v) for k, v in m.items()}


# ─────────────────────────────── ops ──────────────────────────────────────────

def _save(jobdir, name, data):
    path = os.path.join(jobdir, name)
    with open(path, "wb") as f:
        f.write(data)
    return name


def op_evaluate(job, jobdir):
    """Display meshes for the viewport: each object after its modifiers, as
    per-corner (loop) positions + normals and a triangle index — raw buffers."""
    objs = build(job["scene"], jobdir)
    ids = (job.get("params") or {}).get("ids") or [k for k, o in objs.items() if o.type in ("MESH", "FONT")]
    dg = bpy.context.evaluated_depsgraph_get()
    out, total = {}, 0
    for oid in ids:
        ob = objs.get(oid)
        if ob is None or ob.type not in ("MESH", "FONT"):
            continue
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        nl, nt = len(me.loops), len(me.loop_triangles)
        total += nt
        if total > 1_500_000:
            ev.to_mesh_clear()
            raise ValueError("evaluated scene is over 1.5M triangles — lower subdivision levels")
        vi = np.empty(nl, np.int32)
        me.loops.foreach_get("vertex_index", vi)
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        pos = co.reshape(-1, 3)[vi].astype(np.float32)
        nrm = np.empty(nl * 3, np.float32)
        try:
            me.corner_normals.foreach_get("vector", nrm)
        except AttributeError:
            me.loops.foreach_get("normal", nrm)
        tri = np.empty(nt * 3, np.uint32)
        me.loop_triangles.foreach_get("loops", tri)
        out[oid] = {"positions": _save(jobdir, f"{oid}.pos.bin", pos.tobytes()),
                    "normals": _save(jobdir, f"{oid}.nrm.bin", nrm.tobytes()),
                    "index": _save(jobdir, f"{oid}.idx.bin", tri.tobytes()),
                    "loops": nl, "tris": nt}
        if me.uv_layers.active and nl:
            uv = np.empty(nl * 2, np.float32)
            me.uv_layers.active.data.foreach_get("uv", uv)
            out[oid]["uv"] = _save(jobdir, f"{oid}.uv.bin", uv.tobytes())
        if nt and len(ob.material_slots) > 1:
            mi = np.empty(nt, np.int32)
            me.loop_triangles.foreach_get("material_index", mi)
            out[oid]["material_index"] = _save(jobdir, f"{oid}.mat.bin", mi.astype(np.uint16).tobytes())
        ev.to_mesh_clear()
    return {"meshes": out, "tris": total}


def _render_to(job, jobdir, resolution, samples):
    doc = S.normalize(job["scene"])
    objs = build(doc, jobdir)
    cam = doc["render"]["camera"]
    if not cam:
        raise ValueError("the scene has no render camera — add one (render.camera)")
    bpy.context.scene.camera = objs[cam]
    frame = (job.get("params") or {}).get("frame")
    if isinstance(frame, int) and 0 <= frame <= S.MAX_FRAME:      # an animation's pose there
        bpy.context.scene.frame_set(frame)
    png = os.path.join(jobdir, "render.png")
    _render_settings(doc, resolution, samples, png)
    t = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    secs = time.perf_counter() - t
    _preview(png, os.path.join(jobdir, "preview.jpg"))
    return round(secs, 2)


def op_snapshot(job, jobdir):
    p = job.get("params") or {}
    w, h = S.normalize(job["scene"])["render"]["resolution"]
    k = 640 / max(w, h)
    res = [max(16, int(w * k)), max(16, int(h * k))] if k < 1 else [w, h]
    secs = _render_to(job, jobdir, res, int(p.get("samples", 12)))
    return {"preview": "preview.jpg", "render_seconds": secs, "resolution": res}


def op_render(job, jobdir):
    doc = S.normalize(job["scene"])
    p = job.get("params") or {}
    res = p.get("resolution") or doc["render"]["resolution"]
    samples = int(p.get("samples") or doc["render"]["samples"])
    if res[0] * res[1] > S.MAX_PIXELS or not 1 <= samples <= S.MAX_SAMPLES:
        raise ValueError("resolution/samples over the caps (1920x1080 pixels, 256 samples)")
    secs = _render_to(job, jobdir, res, samples)
    return {"png": "render.png", "preview": "preview.jpg", "render_seconds": secs,
            "resolution": list(res), "samples": samples}


VIDEO_MAX_PIXELS = 1280 * 720
VIDEO_MAX_SAMPLES = 64
CHUNK_MAX = 120                # frames in one video call


def _encoder(name, w, h, fps, crf):
    """A scene that only encodes: sequencer strips → H.264 in an mp4, colours as they are —
    the Standard view, since what goes in is already display-ready."""
    sc = bpy.data.scenes.new(name)
    r = sc.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    r.fps, r.fps_base = fps, 1.0
    r.image_settings.media_type = "VIDEO"
    r.image_settings.file_format = "FFMPEG"
    f = r.ffmpeg
    f.format, f.codec, f.constant_rate_factor, f.ffmpeg_preset = "MPEG4", "H264", crf, "GOOD"
    f.gopsize = max(1, fps)                       # a keyframe a second: seeking stays quick
    f.audio_codec = "NONE"
    r.use_sequencer, r.use_compositing = True, False
    sc.view_settings.view_transform, sc.view_settings.look = "Standard", "None"
    sc.view_settings.exposure, sc.view_settings.gamma = 0.0, 1.0
    return sc, sc.sequence_editor_create()


def _encode(sc, out):
    """Render the encoder scene's strips to `out` (an .mp4)."""
    base = out[:-4] + "_"
    sc.render.filepath = base
    try:
        with bpy.context.temp_override(scene=sc):
            bpy.ops.render.render(animation=True)
    finally:
        bpy.data.scenes.remove(sc)
    made = sorted(glob.glob(base + "*.mp4"))
    if not made:
        raise RuntimeError("the encoder wrote nothing")
    os.replace(made[-1], out)
    return out


def _decode_check(mp4, png, w, h):
    """Dev check: the first frame of `mp4`, decoded, against the PNG it was encoded from —
    the mean absolute difference per channel, 0-255."""
    sc, se = _encoder("check", w, h, 24, "HIGH")
    se.strips.new_movie("m", mp4, channel=1, frame_start=1)
    sc.frame_start = sc.frame_end = 1
    sc.render.image_settings.media_type = "IMAGE"
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    out = os.path.join(os.path.dirname(os.path.dirname(png)), "decoded.png")
    sc.render.filepath = out
    try:
        with bpy.context.temp_override(scene=sc):
            bpy.ops.render.render(write_still=True)
    finally:
        bpy.data.scenes.remove(sc)
    px = []
    for path in (png, out):
        img = bpy.data.images.load(path)
        a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
        img.pixels.foreach_get(a)
        px.append(a.reshape(-1, 4)[:, :3] * 255)
        bpy.data.images.remove(img)
    os.unlink(out)
    return [round(float(x), 3) for x in np.abs(px[0] - px[1]).mean(0)]


def op_video(job, jobdir):
    """Frames [a, b] of the animation as an H.264 segment: Cycles renders them to PNG
    (persistent data: the scene syncs once, not once a frame), then the sequencer encodes
    the PNGs untouched. `poster` keeps the first frame as a JPEG."""
    doc = S.normalize(job["scene"])
    p = job.get("params") or {}
    fr = p.get("frames")
    if not (isinstance(fr, list) and len(fr) == 2 and all(isinstance(x, int) for x in fr)
            and 0 <= fr[0] <= fr[1] <= S.MAX_FRAME and fr[1] - fr[0] < CHUNK_MAX):
        raise ValueError(f"frames: [first, last], at most {CHUNK_MAX} of them")
    a, b = fr
    res = p.get("resolution") or doc["render"]["resolution"]
    w, h = int(res[0]) // 2 * 2, int(res[1]) // 2 * 2          # H.264 wants even sides
    samples = int(p.get("samples") or doc["render"]["samples"])
    if w < 16 or h < 16 or w * h > VIDEO_MAX_PIXELS or not 1 <= samples <= VIDEO_MAX_SAMPLES:
        raise ValueError(f"video: at most 1280x720 pixels and {VIDEO_MAX_SAMPLES} samples")
    objs = build(doc, jobdir)
    cam = doc["render"]["camera"]
    if not cam:
        raise ValueError("the scene has no render camera — add one (render.camera)")
    scene = bpy.context.scene
    scene.camera = objs[cam]
    frames = os.path.join(jobdir, "frames")
    os.makedirs(frames)
    _render_settings(doc, [w, h], samples, os.path.join(frames, "f-######"))
    r = scene.render
    r.film_transparent = False                     # an mp4 has no alpha
    r.image_settings.color_mode = "RGB"
    r.image_settings.compression = 15
    r.use_persistent_data = True
    scene.frame_start, scene.frame_end = a, b
    t = time.perf_counter()
    try:
        bpy.ops.render.render(animation=True)
    finally:
        r.use_persistent_data = False
    secs = time.perf_counter() - t
    pngs = [os.path.join(frames, f"f-{f:06d}.png") for f in range(a, b + 1)]
    if not all(os.path.exists(x) for x in pngs):
        raise RuntimeError("Blender didn't write every frame")
    out = {"segment": "segment.mp4", "frames": [a, b], "render_seconds": round(secs, 2),
           "seconds_per_frame": round(secs / (b - a + 1), 3), "resolution": [w, h], "samples": samples}
    if p.get("poster"):
        _preview(pngs[0], os.path.join(jobdir, "poster.jpg"), longest=1280)
        out["poster"] = "poster.jpg"
    t = time.perf_counter()
    sc, se = _encoder("encode", w, h, doc["animation"]["fps"], "PERC_LOSSLESS")   # an intermediate: joined later
    strip = se.strips.new_image("frames", pngs[0], channel=1, frame_start=1)
    for x in pngs[1:]:
        strip.elements.append(os.path.basename(x))
    sc.frame_start, sc.frame_end = 1, len(pngs)
    _encode(sc, os.path.join(jobdir, "segment.mp4"))
    out["encode_seconds"] = round(time.perf_counter() - t, 2)
    if p.get("check"):
        out["decode_diff"] = _decode_check(os.path.join(jobdir, "segment.mp4"), pngs[0], w, h)
    shutil.rmtree(frames)
    return out


def op_encode(job, jobdir):
    """segments/s-000.mp4 … joined into video.mp4, in order. Tainted: the segments come
    from the workspace, and this decodes them."""
    p = job.get("params") or {}
    n, fps, res = p.get("segments"), p.get("fps"), p.get("resolution")
    if not (isinstance(n, int) and 1 <= n <= 1000 and isinstance(fps, int) and 1 <= fps <= 120
            and isinstance(res, list) and len(res) == 2):
        raise ValueError("encode: {segments, fps, resolution}")
    w, h = int(res[0]) // 2 * 2, int(res[1]) // 2 * 2
    if w < 16 or h < 16 or w * h > VIDEO_MAX_PIXELS:
        raise ValueError("resolution: at most 1280x720")
    paths = [os.path.join(jobdir, "segments", f"s-{i:03d}.mp4") for i in range(n)]
    if not all(os.path.exists(x) for x in paths):
        raise ValueError("segments: s-000.mp4 … one per chunk, in order")
    reset()
    t = time.perf_counter()
    sc, se = _encoder("join", w, h, fps, "HIGH")
    at = 1
    for x in paths:
        at += se.strips.new_movie(os.path.basename(x), x, channel=1, frame_start=at).frame_final_duration
    sc.frame_start, sc.frame_end = 1, at - 1
    _encode(sc, os.path.join(jobdir, "video.mp4"))
    return {"video": "video.mp4", "frames": at - 1, "encode_seconds": round(time.perf_counter() - t, 2)}


def _select_only(ob):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def _bm_selection(bm, sel):
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    if sel in (None, "all"):
        return {"verts": list(bm.verts), "edges": list(bm.edges), "faces": list(bm.faces)}
    if "faces" in sel:
        faces = [bm.faces[i] for i in sel["faces"]]
        return {"faces": faces, "edges": list({e for f in faces for e in f.edges}),
                "verts": list({v for f in faces for v in f.verts})}
    if "edges" in sel:
        edges = []
        for a, b in sel["edges"]:
            e = bm.edges.get((bm.verts[a], bm.verts[b]))
            if e is None:
                raise ValueError(f"no edge between vertices {a} and {b}")
            edges.append(e)
        es = set(edges)                          # a face is selected when all its edges are, as in Blender
        return {"edges": edges, "verts": list({v for e in edges for v in e.verts}),
                "faces": [f for f in bm.faces if all(e in es for e in f.edges)]}
    verts = [bm.verts[i] for i in sel.get("verts", [])]
    vs = set(verts)                              # … and an edge or a face when all its vertices are
    return {"verts": verts, "edges": [e for e in bm.edges if all(v in vs for v in e.verts)],
            "faces": [f for f in bm.faces if all(v in vs for v in f.verts)]}


def _uv_project(bm, faces, method, p):
    """UVs by projection, in the object's own space: cube (each face by its dominant axis),
    cylinder or sphere (round Z), or reset (each face the whole 0–1 square)."""
    layer = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
    if method not in ("cube", "cylinder", "sphere", "reset"):
        raise ValueError("uv method: cube, cylinder, sphere or reset")
    pts = [v.co for f in faces for v in f.verts] or [Vector()]
    lo = Vector([min(c[i] for c in pts) for i in range(3)])
    hi = Vector([max(c[i] for c in pts) for i in range(3)])
    center, size = (lo + hi) / 2, max(max(hi - lo), 1e-9)
    scale = float(p.get("scale", 1.0))
    for f in faces:
        if method == "reset":
            n = len(f.loops)
            for i, loop in enumerate(f.loops):
                a = 2 * math.pi * i / n + math.pi / 4 * (n == 4)
                loop[layer].uv = (0.5 + 0.5 * math.cos(a) * (2 ** 0.5 if n == 4 else 1),
                                  0.5 + 0.5 * math.sin(a) * (2 ** 0.5 if n == 4 else 1))
            continue
        ax = max(range(3), key=lambda i: abs(f.normal[i]))
        seam_u = None
        for loop in f.loops:
            d = loop.vert.co - center
            if method == "cube":
                u, v = [d[i] for i in range(3) if i != ax]
                uv = (u / size + 0.5, v / size + 0.5)
            else:
                ang = math.atan2(d.y, d.x) / (2 * math.pi) + 0.5
                if seam_u is not None and abs(ang - seam_u) > 0.5:   # keep a face on one side of the seam
                    ang += 1 if ang < seam_u else -1
                seam_u = ang if seam_u is None else seam_u
                if method == "cylinder":
                    uv = (ang, (loop.vert.co.z - lo.z) / max(hi.z - lo.z, 1e-9))
                else:
                    r = max(d.length, 1e-9)
                    uv = (ang, math.asin(max(-1, min(1, d.z / r))) / math.pi + 0.5)
            loop[layer].uv = (uv[0] * scale, uv[1] * scale)


def op_texture(job, jobdir):
    """An uploaded image as a texture file: PNG if it has transparency, else JPEG, at most
    2048 px on a side."""
    p = job.get("params") or {}
    ext = str(p.get("ext", "")).lower().lstrip(".")
    path = os.path.join(jobdir, "texture_in." + ext)
    if not os.path.exists(path):
        raise ValueError("no image in the job")
    img = bpy.data.images.load(path, check_existing=False)
    if img.size[0] == 0 or img.size[1] == 0:
        raise ValueError("that file isn't an image Blender can read")
    data, ext_out = _image_bytes(img)
    alpha = _has_alpha(img)
    w, h = img.size
    if max(w, h) > _MAX_TEXTURE:
        k = _MAX_TEXTURE / max(w, h)
        w, h = max(1, round(w * k)), max(1, round(h * k))
    return {"file": _save(jobdir, f"texture.{ext_out}", data), "width": w, "height": h, "alpha": alpha}


def op_apply(job, jobdir):
    """A destructive mesh op on one object; answers with its new mesh sidecar."""
    p = job.get("params") or {}
    oid, name = p.get("id"), p.get("op")
    objs = build(job["scene"], jobdir)
    ob = objs.get(oid)
    if ob is None:
        raise ValueError(f"no object {oid!r}")
    _select_only(ob)
    removed, mods_left, picked, slots_after = [], None, None, None
    if ob.type == "FONT":
        bpy.ops.object.convert(target="MESH")
        ob = bpy.context.view_layer.objects.active
    if ob.type != "MESH":
        raise ValueError(f"{oid!r} is a {ob.type.lower()}, not a mesh")
    doc_mods = S.normalize(job["scene"])["objects"][oid].get("modifiers", [])
    if name == "modifier_apply":
        idx = int(p.get("index", 0))
        if not 0 <= idx < len(ob.modifiers):
            raise ValueError(f"{oid!r} has no modifier {idx}")
        # Blender applies from the top of the stack only; earlier ones stay.
        for _ in range(idx):
            bpy.ops.object.modifier_move_to_index(modifier=ob.modifiers[idx].name, index=0)
        bpy.ops.object.modifier_apply(modifier=ob.modifiers[0].name)
        mods_left = doc_mods[:idx] + doc_mods[idx + 1:]
    elif name in ("remesh", "decimate", "boolean"):
        spec = {"type": name, **{k: v for k, v in p.items() if k not in ("id", "op", "selection")}}
        md = _modifier(ob, S.normalize({"objects": {"x": {"type": "mesh", "mesh": "m", "modifiers": [spec]},
                                                    **({spec["object"]: {"type": "empty"}} if name == "boolean" and spec.get("object") else {})},
                                        "meshes": {"m": {"primitive": "cube"}}})["objects"]["x"]["modifiers"][0], objs)
        bpy.ops.object.modifier_move_to_index(modifier=md.name, index=0)
        bpy.ops.object.modifier_apply(modifier=md.name)
    elif name == "convert":
        pass                                     # building it already made it a plain mesh
    elif name == "join":
        others = [objs[i] for i in p.get("others", []) if i in objs and objs[i].type == "MESH"]
        if not others:
            raise ValueError("join needs `others`: mesh objects to merge into this one")
        for o in [ob, *others]:            # join carries mesh-linked materials: move each object's there
            for slot in o.material_slots:
                mat, slot.link = slot.material, "DATA"
                slot.material = mat
        for o in others:
            o.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.join()
        removed = [i for i in p["others"] if i in objs]
        slots_after = [sl.material.get("cycls_id") if sl.material else None for sl in ob.material_slots]
    else:
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        sel = _bm_selection(bm, p.get("selection"))
        # `picked`: what Blender leaves selected, so Edit mode can carry on from it (inset, then extrude).
        if name == "bevel":
            geom = sel["edges"] or sel["verts"]
            picked = bmesh.ops.bevel(bm, geom=list(geom) + list(sel["verts"] if sel["edges"] else []),
                                     offset=float(p.get("width", 0.05)), segments=int(p.get("segments", 2)),
                                     affect="EDGES" if sel["edges"] else "VERTICES", profile=0.5)["faces"]
        elif name == "subdivide":
            r = bmesh.ops.subdivide_edges(bm, edges=sel["edges"], cuts=int(p.get("cuts", 1)), use_grid_fill=True)
            picked = [e for e in r["geom"] if isinstance(e, bmesh.types.BMEdge)]
        elif name == "inset":
            bmesh.ops.inset_region(bm, faces=sel["faces"], thickness=float(p.get("thickness", 0.05)),
                                   depth=float(p.get("depth", 0.0)))
            picked = sel["faces"]                # the region's own faces are now the inner ones
        elif name == "connect":                  # J across faces: an edge path between two vertices
            ids = p.get("verts") or []
            if len(ids) != 2:
                raise ValueError("connect needs `verts`: two vertex indices")
            bm.verts.ensure_lookup_table()
            r = bmesh.ops.connect_vert_pair(bm, verts=[bm.verts[i] for i in ids])
            if not r.get("edges"):
                raise ValueError("Blender found no path across faces between those two vertices")
            picked = list(r["edges"])
        elif name == "bisect":                   # a plane through the mesh: a cut all the way through
            co, no = p.get("plane_co"), p.get("plane_no")
            vec = lambda v: isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v)  # noqa: E731
            if not (vec(co) and vec(no)) or Vector(no).length < 1e-12:
                bm.free()
                raise ValueError("bisect needs `plane_co` and `plane_no` (in the object's space)")
            geom = list({*sel["verts"], *sel["edges"], *sel["faces"]})
            r = bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-5, plane_co=Vector(co), plane_no=Vector(no).normalized(),
                                       clear_inner=bool(p.get("clear_inner")), clear_outer=bool(p.get("clear_outer")))
            picked = [e for e in r["geom_cut"] if isinstance(e, bmesh.types.BMEdge) and e.is_valid]
            if not picked:
                bm.free()
                raise ValueError("the cut misses the mesh — draw the line across it" if p.get("selection") in (None, "all")
                                 else "the cut misses what's selected — select all (A) or draw the line across the selection")
            if p.get("fill"):                    # cap what a cleared side left open
                with contextlib.suppress(Exception):
                    made = bmesh.ops.edgeloop_fill(bm, edges=picked)["faces"]
                    if made:
                        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        elif name == "assign":                   # the selected faces (all, if none) use material slot `slot`
            slot = int(p.get("slot", 0))
            if not 0 <= slot < S.MAX_SLOTS:
                raise ValueError(f"slot: 0–{S.MAX_SLOTS - 1}")
            for f in sel["faces"] or list(bm.faces):
                f.material_index = slot
        elif name == "uv":
            _uv_project(bm, sel["faces"] or list(bm.faces), str(p.get("method", "cube")), p)
        elif name == "triangulate":
            bmesh.ops.triangulate(bm, faces=sel["faces"] or list(bm.faces))
        elif name == "merge_by_distance":
            bmesh.ops.remove_doubles(bm, verts=sel["verts"], dist=float(p.get("distance", 1e-4)))
        elif name == "recalc_normals":
            bmesh.ops.recalc_face_normals(bm, faces=sel["faces"] or list(bm.faces))
        else:
            bm.free()
            raise ValueError(f"unknown apply op {name!r}")
        if picked is not None:                   # bmesh's order is the mesh's once written
            bm.verts.index_update()
            bm.edges.index_update()
            bm.faces.index_update()
            picked = ({"faces": sorted(f.index for f in picked if f.is_valid)}
                      if picked and isinstance(picked[0], bmesh.types.BMFace) else
                      {"edges": sorted([min(e.verts[0].index, e.verts[1].index), max(e.verts[0].index, e.verts[1].index)]
                                       for e in picked if e.is_valid)})
        bm.to_mesh(ob.data)
        bm.free()
    ob.data.update()
    sidecar, mid = write_sidecar(ob.data)
    _save(jobdir, "mesh.json", json.dumps(sidecar).encode())
    return {"mesh_id": mid, "mesh": "mesh.json", "verts": sidecar["counts"]["verts"],
            "faces": sidecar["counts"]["faces"], "bbox": sidecar["bbox"],
            "modifiers": mods_left, "removed": removed, **({"selection": picked} if picked else {}),
            **({"materials": slots_after} if slots_after is not None else {})}


_EXPORT = {"blend": ".blend", "glb": ".glb", "fbx": ".fbx", "obj": ".obj", "stl": ".stl"}


def op_export(job, jobdir):
    fmt = (job.get("params") or {}).get("format", "glb")
    if fmt not in _EXPORT:
        raise ValueError(f"format: one of {', '.join(_EXPORT)}")
    build(job["scene"], jobdir)
    path = os.path.join(jobdir, "export" + _EXPORT[fmt])
    if fmt == "blend":
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=True)
    elif fmt == "glb":
        # The scene's motion as one animation: per-action ones import as one active and the
        # rest parked on the NLA, so only one object would move.
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True,
                                  export_cameras=True, export_lights=True, export_animation_mode="SCENE")
    elif fmt == "fbx":
        bpy.ops.export_scene.fbx(filepath=path, use_mesh_modifiers=True, bake_anim_use_all_actions=False,
                                 bake_anim_use_nla_strips=False)
    elif fmt == "obj":
        bpy.ops.wm.obj_export(filepath=path, apply_modifiers=True, export_materials=False)
    elif fmt == "stl":
        bpy.ops.wm.stl_export(filepath=path, apply_modifiers=True)
    return {"file": os.path.basename(path), "format": fmt}


def op_script(job, jobdir):
    """The agent's escape hatch: run bpy against the built scene, read the
    result back into a document. Tainted — the parent recycles this worker."""
    code = (job.get("params") or {}).get("code", "")
    if not isinstance(code, str) or not code.strip() or len(code) > 100_000:
        raise ValueError("code: 1–100,000 characters of Python")
    build(job["scene"], jobdir)
    buf = io.StringIO()
    ns = {"bpy": bpy, "bmesh": bmesh, "math": math, "Vector": Vector, "Matrix": Matrix, "np": np,
          "__name__": "studio_script"}
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        exec(compile(code, "script.py", "exec"), ns)
    bpy.context.view_layer.update()
    notes = []
    doc = to_doc(job["scene"], jobdir, notes)
    return {"scene": doc, "notes": notes, "stdout": buf.getvalue()[-4000:]}


def op_import(job, jobdir):
    """A model file → a scene fragment (objects/meshes/materials). Tainted."""
    p = job.get("params") or {}
    ext = str(p.get("ext", "")).lower().lstrip(".")
    path = os.path.join(jobdir, "import." + ext)
    if not os.path.exists(path):
        raise ValueError("no import file in the job")
    reset()
    notes, extra = [], {}
    if ext in ("glb", "gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == "obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == "fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == "stl":
        bpy.ops.wm.stl_import(filepath=path)
    elif ext == "ply":
        bpy.ops.wm.ply_import(filepath=path)
    elif ext == "blend":
        extra = _import_blend(path, notes)
    else:
        raise ValueError("ext: glb, gltf, obj, fbx, stl, ply or blend")
    _realize_instances(notes)
    for ob in bpy.context.scene.objects:
        if "cycls_id" in ob:
            del ob["cycls_id"]
    empty = S.normalize({})
    doc = to_doc(empty, jobdir, notes)
    frames = [k[0] for o in doc["objects"].values() for ks in (o.get("keys") or {}).values() for k in ks]
    if frames and ext != "blend":          # a glb or fbx carries motion, not a timeline: its keys are it
        doc["animation"] = {**doc["animation"], "frame_start": min(frames), "frame_end": max(max(frames), min(frames) + 1)}
        doc = S.normalize(doc)
    if frames:
        a = doc["animation"]
        extra["animation"] = a
        notes.append(f"{len(S.animated(doc))} animated object(s), frames {a['frame_start']}–{a['frame_end']} at {a['fps']} fps")
    cam = extra.get("camera")
    extra["camera"] = next((k for k, o in doc["objects"].items() if o["type"] == "camera" and o["name"] == cam), None)
    return {"scene": doc, "notes": notes, **extra}


def _realize_instances(notes):
    """Instances Blender draws that the document has no word for — particle scatter, collection
    instances, geometry-nodes instances of objects — as objects of their own, sharing their
    source's mesh (the Studio draws repeats instanced). Instanced geometry that isn't an object
    is counted, not carried. The scene's object cap bounds how many come in."""
    here = bpy.context.scene
    # A heavy scatter is often hidden in the viewport and shown in renders; the depsgraph here is
    # the viewport's, so show what renders (and all of it) before asking for instances — the
    # emitter and the prototypes too (hidden objects aren't evaluated), then hide them again.
    hidden = [ob for ob in here.objects if ob.hide_viewport]
    for ob in hidden:
        ob.hide_viewport = False
    for ob in here.objects:
        for md in ob.modifiers:
            if md.type in ("PARTICLE_SYSTEM", "NODES") and md.show_render:
                md.show_viewport = True
        for ps in getattr(ob, "particle_systems", ()):
            ps.settings.display_percentage = 100
            if ps.settings.render_type in ("OBJECT", "COLLECTION"):
                ps.settings.display_method = "RENDER"      # dots or none draw no instances
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    groups, other, seen = {}, 0, 0             # instancer name → [count, [(source, matrix)] up to the cap]
    for inst in dg.object_instances:
        seen += 1
        if not inst.is_instance:
            continue
        src, host = inst.object.original, inst.parent.original if inst.parent else None
        if src.type != "MESH" or src is host or src.data is None:
            other += 1
            continue
        g = groups.setdefault(host.name if host else "", [0, []])
        g[0] += 1
        if g[0] <= INSTANCE_SET_MAX:                   # past it, only counted
            g[1].append((src, inst.matrix_world.copy()))
    for ob in hidden:
        ob.hide_viewport = True
    # A set of repeats comes in whole or not at all: a sliver of a million-pebble scatter would
    # misdraw it (and crowd the scene out); rows of seats, furniture, crowds come in.
    room = max(0, S.MAX_OBJECTS - len(here.objects) - 10)
    todo = []
    for host, (count, items) in sorted(groups.items(), key=lambda kv: kv[1][0]):
        if count > INSTANCE_SET_MAX or count > room - len(todo):
            notes.append(f"{host or 'an instancer'}: {count:,} instances — too many to carry as objects, left out")
            continue
        todo += items
    for i, (src, mw) in enumerate(todo):
        ob = bpy.data.objects.new(f"{src.name}.{i}", src.data)
        ob.matrix_world = mw
        for j, slot in enumerate(src.material_slots):
            if slot.link == "OBJECT":
                ob.material_slots[j].link = "OBJECT"
                ob.material_slots[j].material = slot.material
        here.collection.objects.link(ob)
    if todo:
        notes.append(f"{len(todo)} instances (particles, collection or geometry-nodes instances) became "
                     "objects sharing their meshes")
    if other:
        notes.append(f"{other} instanced pieces of geometry-nodes geometry aren't objects — not carried")
    if not groups and not other and any(len(getattr(o, "particle_systems", ())) for o in here.objects):
        notes.append(f"particle systems gave no instances ({seen} evaluated objects)")


def _import_blend(path, notes):
    """A .blend as its first scene shows it: what its view layer excludes, or its collections
    hide, stays hidden (it was often the source of instances, parked out of sight); its world
    and active camera come back for the caller to use."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        if src.scenes:
            dst.scenes = [src.scenes[0]]
        else:
            dst.objects = list(src.objects)
    here = bpy.context.scene
    sc = dst.scenes[0] if src.scenes and dst.scenes and dst.scenes[0] else None
    if sc is None:                                   # no scene (an asset library): its objects, as they are
        for ob in dst.objects:
            if ob is not None:
                here.collection.objects.link(ob)
        return {}
    shown_r, shown_v = set(), set()

    def walk(lc, hr, hv):
        c = lc.collection
        hr, hv = hr or lc.exclude or c.hide_render, hv or lc.exclude or c.hide_viewport or lc.hide_viewport
        for ob in c.objects:
            if not hr:
                shown_r.add(ob.name)
            if not hv:
                shown_v.add(ob.name)
        for ch in lc.children:
            walk(ch, hr, hv)

    walk(sc.view_layers[0].layer_collection, False, False)
    here.render.fps, here.render.fps_base = sc.render.fps, sc.render.fps_base      # its timeline, for its keys
    here.frame_start, here.frame_end = sc.frame_start, sc.frame_end
    for ob in list(sc.objects):
        if ob.name not in shown_r:
            ob.hide_render = True
        if ob.name not in shown_v:
            ob.hide_viewport = True
        if ob.name not in here.collection.objects:
            here.collection.objects.link(ob)
    return {"world": _world_of(sc.world, notes), "camera": sc.camera.name if sc.camera else None}


def _world_of(w, notes):
    """A file's world as the document's: a plain colour carries over; a sky or an HDRI
    becomes the nearest Studio world (they're presets)."""
    tree = getattr(w, "node_tree", None) if w else None
    bg = None
    for n in tree.nodes if tree else []:
        if n.type == "OUTPUT_WORLD" and n.is_active_output and n.inputs["Surface"].is_linked:
            bg = n.inputs["Surface"].links[0].from_node
    if bg is None or bg.type != "BACKGROUND":
        return {"kind": "color", "color": _hex_of(w.color), "strength": 1.0} if w else None
    strength = max(0.0, min(100.0, float(bg.inputs["Strength"].default_value)))
    col = bg.inputs["Color"]
    if not col.is_linked:
        return {"kind": "color", "color": _hex_of(col.default_value), "strength": round(strength, 4)}
    kind = col.links[0].from_node.type
    if kind == "TEX_SKY":
        low = math.degrees(getattr(col.links[0].from_node, "sun_elevation", 0.8)) < 12
        preset = "sunset" if low else "courtyard"
        notes.append(f"the file's sky became the {preset} world (Studio worlds are presets)")
        return {"kind": "hdri", "hdri": preset, "strength": 1.0}
    notes.append("the file's " + ("HDRI" if kind == "TEX_ENVIRONMENT" else "world") +
                 " became the courtyard world (Studio worlds are presets)")
    return {"kind": "hdri", "hdri": "courtyard", "strength": round(min(max(strength, 0.2), 3.0), 4)
            if kind == "TEX_ENVIRONMENT" else 1.0}


def op_selftest(job, jobdir):
    """document → bpy → document on a fixture covering every object kind and
    primitive; reports mismatches instead of raising."""
    doc = S.normalize(job["scene"])
    build(doc, jobdir)
    notes = []
    back = to_doc(doc, jobdir, notes)
    problems = []
    for oid, o in doc["objects"].items():
        b = back["objects"].get(oid)
        if b is None:
            problems.append(f"{oid}: missing after round trip")
            continue
        for k in ("location", "scale"):
            if max(abs(x - y) for x, y in zip(o[k], b[k])) > 1e-4:
                problems.append(f"{oid}.{k}: {o[k]} → {b[k]}")
        rm, rb = S.euler_matrix(o["rotation"]), S.euler_matrix(b["rotation"])
        if max(abs(rm[i][j] - rb[i][j]) for i in range(3) for j in range(3)) > 1e-4:
            problems.append(f"{oid}.rotation: {o['rotation']} → {b['rotation']}")
        ka, kb = o.get("keys") or {}, b.get("keys") or {}
        if set(ka) != set(kb) or any(
                len(ka[c]) != len(kb[c]) or any(x[0] != y[0] or x[2] != y[2] or
                                                max(abs(p_ - q_) for p_, q_ in zip(x[1], y[1])) > 1e-3
                                                for x, y in zip(ka[c], kb[c])) for c in ka):
            problems.append(f"{oid}.keys: {ka} → {kb}")
        for k in ("type", "parent", "mesh", "materials", "light", "camera", "text", "modifiers"):
            if k in o and o.get(k) != b.get(k):
                a_, b_ = o.get(k), b.get(k)
                if isinstance(a_, dict) and isinstance(b_, dict):
                    diffs = {kk: (a_[kk], b_.get(kk)) for kk in a_
                             if not (isinstance(a_[kk], float) and abs(a_[kk] - (b_.get(kk) or 0)) < 1e-3)
                             and a_[kk] != b_.get(kk)}
                    if diffs:
                        problems.append(f"{oid}.{k}: {diffs}")
                else:
                    problems.append(f"{oid}.{k}: {a_!r} → {b_!r}")
    for mid, m in doc["materials"].items():
        b = back["materials"].get(mid)
        if b is None:
            problems.append(f"material {mid}: missing")
            continue
        for k, v in m.items():
            if k in ("preset",):
                continue
            if isinstance(v, float) and abs(v - b[k]) > 2e-3 or isinstance(v, str) and v != b[k]:
                problems.append(f"material {mid}.{k}: {v!r} → {b[k]!r}")
    # primitive sizes against the document's own bounds
    sizes = {}
    for mid, m in doc["meshes"].items():
        if "primitive" in m:
            me = primitive_mesh(m)
            c = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", c)
            c = c.reshape(-1, 3)
            sizes[mid] = {"blender": [c.min(0).round(4).tolist(), c.max(0).round(4).tolist()],
                          "counts": [len(me.vertices), len(me.edges), len(me.polygons)]}
            bpy.data.meshes.remove(me)
    if doc["animation"] != back["animation"]:
        problems.append(f"animation: {doc['animation']} → {back['animation']}")
    out = {"problems": problems, "notes": notes, "primitive_bounds": sizes}
    anim = (job.get("params") or {}).get("anim")
    if anim:
        out["anim"] = _golden(anim, jobdir)
    return out


def _golden(cases, jobdir):
    """Blender's own samples of key sets, for the document's evaluators to be held to
    (studio/tests/fixtures/anim_golden.json): each set keys an empty's location, and another's
    rotation in degrees (the radians path), through the real build. {name: {keys, frames}} →
    {name: {keys, location: [[f, xyz]], rotation: [[f, xyz]]}}, plus how far the depsgraph's
    evaluated objects sit from the curves at whole frames (it should be nothing)."""
    doc = {"objects": {f"{ch[:3]}_{name}": {"type": "empty", "name": f"{ch[:3]}_{name}", "keys": {ch: c["keys"]}}
                       for name, c in cases.items() for ch in ("location", "rotation")}}
    objs = build(S.normalize(doc), jobdir)
    curves = {}
    for oid, ob in objs.items():
        bag = anim_utils.action_get_channelbag_for_slot(ob.animation_data.action, ob.animation_data.action_slot)
        curves[oid] = {fc.array_index: fc for fc in bag.fcurves}
    out = {}
    for name, c in cases.items():
        out[name] = {"keys": c["keys"]}
        for ch, conv in (("location", float), ("rotation", math.degrees)):
            fcs = curves[f"{ch[:3]}_{name}"]
            out[name][ch] = [[f, [conv(fcs[i].evaluate(f)) for i in range(3)]] for f in c["frames"]]
    drift = 0.0
    scene = bpy.context.scene
    for f in range(0, 90, 7):
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        for oid, ob in objs.items():
            ev = ob.evaluated_get(dg)
            got = ev.location if oid.startswith("loc_") else ev.rotation_euler
            drift = max(drift, *(abs(got[i] - curves[oid][i].evaluate(f)) for i in range(3)))
    return {"cases": out, "depsgraph_drift": drift}


OPS = {"evaluate": op_evaluate, "apply": op_apply, "snapshot": op_snapshot, "render": op_render,
       "export": op_export, "script": op_script, "import": op_import, "selftest": op_selftest,
       "texture": op_texture, "video": op_video, "encode": op_encode}
TAINTED = {"script", "import", "texture", "encode"}

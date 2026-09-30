"""Parametric studio scenes for headless Blender.

This file lives two lives:

  inside Blender   blender -b --factory-startup -P scenes.py -- --config cfg.json --out DIR
  outside Blender  render_fn.py execs it and calls normalize() to reject a bad
                   config before paying for a Blender boot.

So nothing at module level may import bpy.
"""
import json
import math
import sys

# ── limits (render_fn.py reports them; the benchmark in README.md sets them) ──
DEFAULT_RESOLUTION = (1280, 720)
DEFAULT_SAMPLES = 32                 # with OIDN, indistinguishable from 128 at 720p
MAX_SAMPLES = 256
MAX_PIXELS = 1920 * 1080
MIN_SIDE, MAX_SIDE = 64, 2048
MAX_TEXT = 24

OBJECTS = ("sphere", "ico-sphere", "cube", "rounded-cube", "torus",
           "cylinder", "cone", "monkey", "text")
LIGHTING = ("studio-3point", "softbox", "dramatic", "rim")
CAMERAS = ("front", "front-3/4", "side", "top", "low", "hero")

# Base colors are LINEAR reflectance (what the Principled BSDF wants).
# User colors arrive as sRGB (hex or 0–1 floats) and are converted.
MATERIALS = {
    "gold":         {"base_color": (1.0, 0.766, 0.336), "metallic": 1.0, "roughness": 0.15},
    "brushed-gold": {"base_color": (1.0, 0.766, 0.336), "metallic": 1.0, "roughness": 0.38},
    "chrome":       {"base_color": (0.95, 0.95, 0.95),  "metallic": 1.0, "roughness": 0.04},
    "brushed-steel": {"base_color": (0.78, 0.78, 0.8),  "metallic": 1.0, "roughness": 0.35},
    "copper":       {"base_color": (0.955, 0.638, 0.538), "metallic": 1.0, "roughness": 0.22},
    "plastic":      {"base_color": (0.6, 0.02, 0.02),   "metallic": 0.0, "roughness": 0.32},
    "matte":        {"base_color": (0.6, 0.6, 0.6),     "metallic": 0.0, "roughness": 0.9},
    "ceramic":      {"base_color": (0.85, 0.85, 0.82),  "metallic": 0.0, "roughness": 0.25, "coat": 0.8},
    "glass":        {"base_color": (1.0, 1.0, 1.0),     "metallic": 0.0, "roughness": 0.0,
                     "transmission": 1.0, "ior": 1.45},
    "rubber":       {"base_color": (0.02, 0.02, 0.02),  "metallic": 0.0, "roughness": 0.75},
    "neon":         {"base_color": (0.02, 0.35, 1.0),   "metallic": 0.0, "roughness": 0.4,
                     "emission": 2.0},     # much higher tone-maps to white
}

_DARK_LIGHTING = ("dramatic", "rim")


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _color(value, what):
    """'#rrggbb' / 'rrggbb' / [r, g, b] (0–1, sRGB) → linear (r, g, b)."""
    if isinstance(value, str):
        h = value.strip().lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in h):
            raise ValueError(f"{what}: {value!r} is not a hex color like '#d4af37'")
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    elif isinstance(value, (list, tuple)) and len(value) in (3, 4):
        try:
            rgb = [float(x) for x in value[:3]]
        except (TypeError, ValueError):
            raise ValueError(f"{what}: {value!r} must be three numbers from 0 to 1")
        if any(x > 1.0 for x in rgb):          # tolerate 0–255 input
            rgb = [x / 255 for x in rgb]
        if any(not 0.0 <= x <= 1.0 for x in rgb):
            raise ValueError(f"{what}: {value!r} must be three numbers from 0 to 1")
    else:
        raise ValueError(f"{what}: {value!r} must be a hex string or [r, g, b]")
    return tuple(round(_srgb_to_linear(x), 5) for x in rgb)


def _num(value, what, lo, hi):
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: {value!r} is not a number")
    if not lo <= x <= hi:
        raise ValueError(f"{what}: {x:g} is outside {lo:g}–{hi:g}")
    return x


def _pick(value, allowed, what):
    v = str(value).strip().lower()
    if v not in allowed:
        raise ValueError(f"{what}: {value!r} — choose one of {', '.join(allowed)}")
    return v


def normalize(config):
    """Validate a render config and fill every default. Raises ValueError with a
    message the caller (often a model) can act on. Unknown keys are rejected so
    a typo doesn't silently render the default."""
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    c = dict(config)
    known = {"preset", "engine", "object", "text", "material", "backdrop", "lighting",
             "camera", "resolution", "samples", "glb"}
    extra = sorted(set(c) - known)
    if extra:
        raise ValueError(f"unknown keys {extra} — allowed: {sorted(known)}")
    if c.get("preset", "product-shot") != "product-shot":
        raise ValueError("preset: only 'product-shot' exists so far")
    if str(c.get("engine", "CYCLES")).upper() != "CYCLES":
        raise ValueError("engine: only CYCLES — EEVEE needs a GPU, and this service is CPU-only")

    obj = _pick(c.get("object", "sphere"), OBJECTS, "object")
    text = None
    if obj == "text":
        text = str(c.get("text") or "").strip()
        if not text:
            raise ValueError("text: required when object is 'text'")
        if len(text) > MAX_TEXT:
            raise ValueError(f"text: at most {MAX_TEXT} characters")
        if any(ord(ch) > 0x24F for ch in text):
            raise ValueError("text: Latin script only — Blender's text engine doesn't shape "
                             "Arabic or other complex scripts")

    m = c.get("material", "plastic")
    if isinstance(m, str):
        m = {"preset": m}
    if not isinstance(m, dict):
        raise ValueError("material: a preset name or an object")
    mextra = sorted(set(m) - {"preset", "color", "base_color", "metallic", "roughness",
                              "coat", "transmission", "ior", "emission"})
    if mextra:
        raise ValueError(f"material: unknown keys {mextra}")
    base = dict(MATERIALS[_pick(m.get("preset", "plastic"), tuple(MATERIALS), "material.preset")])
    color = m.get("color", m.get("base_color"))
    if color is not None:
        base["base_color"] = _color(color, "material.color")
    for key, lo, hi in (("metallic", 0, 1), ("roughness", 0, 1), ("coat", 0, 1),
                        ("transmission", 0, 1), ("ior", 1, 3), ("emission", 0, 50)):
        if key in m:
            base[key] = _num(m[key], f"material.{key}", lo, hi)
    material = {"base_color": tuple(base["base_color"]), "metallic": base["metallic"],
                "roughness": base["roughness"], "coat": base.get("coat", 0.0),
                "transmission": base.get("transmission", 0.0), "ior": base.get("ior", 1.45),
                "emission": base.get("emission", 0.0)}

    lighting = _pick(c.get("lighting", "studio-3point"), LIGHTING, "lighting")
    backdrop = _color(c["backdrop"], "backdrop") if "backdrop" in c else (
        _color("#141417", "backdrop") if lighting in _DARK_LIGHTING else _color("#d6d6db", "backdrop"))

    cam = c.get("camera", "front-3/4")
    if isinstance(cam, str):
        cam = {"angle": cam}
    if not isinstance(cam, dict):
        raise ValueError("camera: an angle name or {angle, focal_mm}")
    angle = _pick(cam.get("angle", "front-3/4"), CAMERAS, "camera.angle")
    focal = _num(cam.get("focal_mm", 85 if angle == "hero" else 50), "camera.focal_mm", 18, 200)

    res = c.get("resolution", list(DEFAULT_RESOLUTION))
    if not (isinstance(res, (list, tuple)) and len(res) == 2):
        raise ValueError("resolution: [width, height]")
    w, h = (int(_num(v, "resolution", MIN_SIDE, MAX_SIDE)) for v in res)
    if w * h > MAX_PIXELS:
        raise ValueError(f"resolution: {w}x{h} is over the {MAX_PIXELS:,}-pixel cap (1920x1080)")
    samples = int(_num(c.get("samples", DEFAULT_SAMPLES), "samples", 1, MAX_SAMPLES))

    return {"preset": "product-shot", "engine": "CYCLES", "object": obj, "text": text,
            "material": material, "backdrop": backdrop, "lighting": lighting,
            "camera": {"angle": angle, "focal_mm": focal}, "resolution": [w, h],
            "samples": samples, "glb": bool(c.get("glb", True))}


# ─────────────────────────────── Blender side ───────────────────────────────

def _principled(name, spec):
    import bpy
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True        # deprecated (always on) in 5.x, required before
    except Exception:
        pass
    nodes = mat.node_tree.nodes
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None) \
            or nodes.new("ShaderNodeOutputMaterial")
        mat.node_tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def put(names, value):
        for n in names:
            if n in bsdf.inputs:
                bsdf.inputs[n].default_value = value
                return

    rgba = (*spec["base_color"], 1.0)
    put(("Base Color",), rgba)
    put(("Metallic",), spec["metallic"])
    put(("Roughness",), spec["roughness"])
    put(("IOR",), spec.get("ior", 1.45))
    put(("Coat Weight", "Coat", "Clearcoat"), spec.get("coat", 0.0))
    put(("Transmission Weight", "Transmission"), spec.get("transmission", 0.0))
    if spec.get("emission"):
        put(("Emission Color", "Emission"), rgba)
        put(("Emission Strength",), spec["emission"])
    mat.diffuse_color = rgba        # viewport + glTF fallback
    return mat


def _select_only(obj):
    import bpy
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _smooth(obj, by_angle=True):
    import bpy
    _select_only(obj)
    try:
        if by_angle:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
        else:
            bpy.ops.object.shade_smooth()
    except Exception:
        bpy.ops.object.shade_smooth()


def _apply_modifiers(obj):
    import bpy
    _select_only(obj)
    for mod in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=mod.name)


def _make_object(cfg):
    import bpy
    kind = cfg["object"]
    ops = bpy.ops.mesh
    if kind == "sphere":
        ops.primitive_uv_sphere_add(segments=96, ring_count=48, radius=1)
        obj = bpy.context.active_object
        _smooth(obj, by_angle=False)
    elif kind == "ico-sphere":
        ops.primitive_ico_sphere_add(subdivisions=2, radius=1)
        obj = bpy.context.active_object                     # faceted on purpose
    elif kind == "cube":
        ops.primitive_cube_add(size=2)
        obj = bpy.context.active_object
        obj.rotation_euler = (0, 0, math.radians(20))
    elif kind == "rounded-cube":
        ops.primitive_cube_add(size=2)
        obj = bpy.context.active_object
        bev = obj.modifiers.new("Bevel", "BEVEL")
        bev.width, bev.segments = 0.18, 8
        _apply_modifiers(obj)
        _smooth(obj)
        obj.rotation_euler = (0, 0, math.radians(20))
    elif kind == "torus":
        ops.primitive_torus_add(major_radius=1, minor_radius=0.36,
                                major_segments=128, minor_segments=48)
        obj = bpy.context.active_object
        _smooth(obj, by_angle=False)
        obj.rotation_euler = (math.radians(72), 0, math.radians(-18))
    elif kind == "cylinder":
        ops.primitive_cylinder_add(vertices=128, radius=0.75, depth=2)
        obj = bpy.context.active_object
        bev = obj.modifiers.new("Bevel", "BEVEL")
        bev.width, bev.segments = 0.04, 4
        _apply_modifiers(obj)
        _smooth(obj)
    elif kind == "cone":
        ops.primitive_cone_add(vertices=128, radius1=1, depth=2)
        obj = bpy.context.active_object
        _smooth(obj)
    elif kind == "monkey":
        ops.primitive_monkey_add(size=2)
        obj = bpy.context.active_object
        sub = obj.modifiers.new("Subsurf", "SUBSURF")
        sub.levels = sub.render_levels = 2
        _apply_modifiers(obj)
        _smooth(obj, by_angle=False)
        obj.rotation_euler = (math.radians(-10), 0, 0)
    elif kind == "text":
        bpy.ops.object.text_add()
        obj = bpy.context.active_object
        obj.data.body = cfg["text"]
        obj.data.align_x, obj.data.align_y = "CENTER", "CENTER"
        obj.data.extrude = 0.12
        obj.data.bevel_depth = 0.018
        obj.data.bevel_resolution = 4
        obj.rotation_euler = (math.radians(90), 0, 0)       # stand up, face the camera
        _select_only(obj)
        bpy.ops.object.convert(target="MESH")
        obj = bpy.context.active_object
        _smooth(obj)
    else:  # normalize() guards this
        raise ValueError(kind)
    obj.name = "Product"
    return obj


def _fit(obj, size=2.0):
    """Scale the object so its largest side is `size`, bake the transform, and
    stand it on the floor at the origin. Returns (height, bounding radius)."""
    import bpy
    from mathutils import Vector
    bpy.context.view_layer.update()
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    dims = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
    obj.scale = [s * size / max(dims) for s in obj.scale]
    _select_only(obj)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.context.view_layer.update()
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    obj.location -= Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    bpy.context.view_layer.update()
    return hi.z - lo.z, (hi - lo).length / 2


def _backdrop(color):
    """A photo-studio sweep (cyclorama): floor curving up into a back wall, so
    the object sits in a seamless infinite-looking space."""
    import bpy
    profile = [(-30.0, 0.0), (2.0, 0.0)]
    r = 5.0
    for i in range(1, 25):
        t = math.radians(90 * i / 24)
        profile.append((2.0 + r * math.sin(t), r - r * math.cos(t)))
    profile.append((2.0 + r, 30.0))
    x0, x1 = -40.0, 40.0
    verts = [(x, y, z) for (y, z) in profile for x in (x0, x1)]
    faces = [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(len(profile) - 1)]
    mesh = bpy.data.meshes.new("Backdrop")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("Backdrop", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(_principled("Backdrop", {
        "base_color": color, "metallic": 0.0, "roughness": 0.55}))
    _smooth(obj, by_angle=False)
    return obj


def _aim(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def _orbit(target, dist, az_deg, el_deg):
    """Point on a sphere around target. Azimuth 0 = in front (−Y, where the
    camera sits), positive swings to camera-right (+X)."""
    from mathutils import Vector
    az, el = math.radians(az_deg), math.radians(el_deg)
    return target + Vector((math.sin(az) * math.cos(el),
                            -math.cos(az) * math.cos(el),
                            math.sin(el))) * dist


# (azimuth, elevation, distance, size, watts, rgb) per light, and world strength
_RIGS = {
    "studio-3point": ([(-45, 35, 6, 3.0, 900, (1.0, 0.97, 0.93)),
                       (55, 15, 7, 4.0, 300, (0.93, 0.96, 1.0)),
                       (165, 45, 6, 2.0, 900, (1.0, 1.0, 1.0))], 0.35),
    "softbox":       ([(0, 75, 5, 6.0, 850, (1.0, 1.0, 1.0)),
                       (0, 12, 9, 6.0, 140, (1.0, 1.0, 1.0))], 0.4),
    # Dark rigs: back lights sit high and tight so they rake the object's
    # edges instead of flooding the floor beside it.
    "dramatic":      ([(-70, 25, 6, 1.0, 700, (1.0, 0.92, 0.82)),
                       (160, 58, 5, 0.8, 550, (0.8, 0.9, 1.0))], 0.12),
    "rim":           ([(-140, 52, 5, 0.8, 650, (1.0, 1.0, 1.0)),
                       (140, 52, 5, 0.8, 650, (1.0, 1.0, 1.0)),
                       (0, 10, 9, 5.0, 160, (1.0, 1.0, 1.0))], 0.1),
}

_ANGLES = {"front": (0, 8), "front-3/4": (32, 18), "side": (90, 8),
           "top": (0, 68), "low": (22, 1), "hero": (28, 7)}


def _lights(rig, target):
    import bpy
    specs, world_strength = _RIGS[rig]
    for i, (az, el, d, size, watts, rgb) in enumerate(specs):
        data = bpy.data.lights.new(f"Light{i}", "AREA")
        data.energy, data.size, data.color = watts, size, rgb
        obj = bpy.data.objects.new(f"Light{i}", data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = _orbit(target, d, az, el)
        _aim(obj, target)
    return world_strength


def _world(strength):
    """Studio HDRI for reflections (Blender ships a few for the viewport);
    plain grey if it isn't there."""
    import os
    import bpy
    scene = bpy.context.scene
    world = bpy.data.worlds.new("World")
    scene.world = world
    try:
        world.use_nodes = True
    except Exception:
        pass
    nt = world.node_tree
    bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None) or nt.nodes.new("ShaderNodeBackground")
    out = next((n for n in nt.nodes if n.type == "OUTPUT_WORLD"), None) or nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bg.inputs["Strength"].default_value = strength
    hdri = os.path.join(bpy.utils.system_resource("DATAFILES", path="studiolights/world"), "studio.exr")
    if os.path.exists(hdri):
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdri)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    else:
        bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)


def _camera(cfg, height, radius):
    import bpy
    from mathutils import Vector
    scene = bpy.context.scene
    w, h = cfg["resolution"]
    focal = cfg["camera"]["focal_mm"]
    data = bpy.data.cameras.new("Camera")
    data.lens, data.sensor_width, data.sensor_fit = focal, 36.0, "AUTO"
    data.clip_start, data.clip_end = 0.05, 500
    # AUTO fits the sensor width to the longer side, so the narrower field of
    # view belongs to the shorter side; fit the bounding sphere into that.
    half = math.atan(18.0 / focal)
    half_short = math.atan(math.tan(half) * min(w, h) / max(w, h))
    dist = radius * 1.08 / math.sin(half_short)
    target = Vector((0, 0, height / 2))
    az, el = _ANGLES[cfg["camera"]["angle"]]
    cam = bpy.data.objects.new("Camera", data)
    scene.collection.objects.link(cam)
    cam.location = _orbit(target, dist, az, el)
    if cam.location.z < 0.08:
        cam.location.z = 0.08
    _aim(cam, target)
    scene.camera = cam
    if cfg["camera"]["angle"] == "hero":
        data.dof.use_dof = True
        data.dof.focus_distance = dist
        data.dof.aperture_fstop = 5.6
    return target


def _render_settings(cfg, out_png):
    import bpy
    scene = bpy.context.scene
    r = scene.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y = cfg["resolution"]
    r.resolution_percentage = 100
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.image_settings.compression = 40
    r.filepath = out_png
    cy = scene.cycles
    cy.device = "CPU"
    cy.samples = cfg["samples"]
    cy.use_adaptive_sampling = True
    for attr, val in (("use_denoising", True), ("denoiser", "OPENIMAGEDENOISE"),
                      ("max_bounces", 10), ("glossy_bounces", 6),
                      ("transmission_bounces", 10), ("caustics_reflective", False),
                      ("caustics_refractive", False), ("sample_clamp_indirect", 8.0)):
        try:
            setattr(cy, attr, val)
        except Exception as e:
            print(f"scenes: skipped cycles.{attr} ({e})")
    # Khronos PBR Neutral keeps a product's base color true (AgX drifts
    # saturated golds toward olive); AgX is the fallback for older builds.
    for transform, look in (("Khronos PBR Neutral", "None"), ("AgX", "AgX - Medium High Contrast")):
        try:
            scene.view_settings.view_transform = transform
            scene.view_settings.look = look
            break
        except Exception as e:
            print(f"scenes: no {transform} ({e})")


def build_and_render(cfg, out_dir):
    import os
    import time
    import bpy
    for o in list(bpy.data.objects):             # factory cube / light / camera
        bpy.data.objects.remove(o, do_unlink=True)

    t0 = time.monotonic()
    product = _make_object(cfg)
    height, radius = _fit(product)
    product.data.materials.clear()
    product.data.materials.append(_principled("Product", cfg["material"]))
    _backdrop(cfg["backdrop"])
    target = _camera(cfg, height, radius)
    _world(_lights(cfg["lighting"], target))
    png = os.path.join(out_dir, "render.png")
    _render_settings(cfg, png)
    build_s = time.monotonic() - t0

    t1 = time.monotonic()
    bpy.ops.render.render(write_still=True)
    render_s = time.monotonic() - t1

    # A small JPEG for a model to look at (a full PNG is ~MBs of base64).
    preview = os.path.join(out_dir, "preview.jpg")
    try:
        img = bpy.data.images.load(png)
        w, h = cfg["resolution"]
        k = 768 / max(w, h)
        if k < 1:
            img.scale(max(1, int(w * k)), max(1, int(h * k)))
        img.file_format = "JPEG"
        img.filepath_raw = preview
        img.save()
    except Exception as e:
        print(f"scenes: preview skipped ({e})")

    if cfg["glb"]:
        _select_only(product)
        try:
            bpy.ops.export_scene.gltf(filepath=os.path.join(out_dir, "model.glb"),
                                      export_format="GLB", use_selection=True,
                                      export_apply=True)
        except Exception as e:
            print(f"scenes: glb export failed ({e})")

    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump({"blender": bpy.app.version_string, "build_seconds": round(build_s, 2),
                   "render_seconds": round(render_s, 2),
                   "threads": bpy.context.scene.render.threads}, f)


def _main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    with open(args.config) as f:
        cfg = normalize(json.load(f))
    build_and_render(cfg, args.out)


if __name__ == "__main__":
    _main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

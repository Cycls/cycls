"""The Studio scene document — one source of truth for the tool, the route, the
engine and (via json_schema) the app.

Stdlib only, no package-relative imports: the Blender engine captures this file's
source by value and runs it standalone.

The document lives at apps/studio/data/scene.json. Conventions:
- Blender space: Z up, metres. Angles in degrees; Euler order XYZ (Blender's —
  three.js reads the same rotation as order 'ZYX').
- Colours are sRGB hex; the engine converts to linear.
- Field names follow bpy (energy, lens, levels, width, segments…).
- objects / meshes / materials / textures are maps keyed by stable ids, so an entry
  can be diffed, patched and merged on its own. The document on disk is always normalized.
"""
import copy
import math
import re

FORMAT = "cycls.studio.scene"
VERSION = 2                 # 2: an object's material slots (`materials`); 1 had one `material`
MAX_SLOTS = 32

MAX_PIXELS = 1920 * 1080
MAX_SAMPLES = 256
MAX_OBJECTS = 500
MAX_TEXTURES = 64
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class SceneError(ValueError):
    """A document or op the caller can fix; the message names the field."""


# ─────────────────────────────── parameter specs ──────────────────────────────
# (kind, default, lo, hi) — kind: "f" float, "i" int, "b" bool, "s:<a|b|c>" choice,
# "v3" 3-vector, "b3" 3 bools, "id" object reference (or None).

PRIMITIVES = {
    "plane":     {"size": ("f", 2.0, 1e-4, 1e4)},
    "grid":      {"x_segments": ("i", 10, 1, 500), "y_segments": ("i", 10, 1, 500), "size": ("f", 2.0, 1e-4, 1e4)},
    "circle":    {"vertices": ("i", 32, 3, 1024), "radius": ("f", 1.0, 1e-4, 1e4), "fill": ("s:ngon|none|trifan", "ngon")},
    "cube":      {"size": ("f", 2.0, 1e-4, 1e4)},
    "uv_sphere": {"segments": ("i", 32, 3, 512), "ring_count": ("i", 16, 3, 256), "radius": ("f", 1.0, 1e-4, 1e4)},
    "ico_sphere": {"subdivisions": ("i", 2, 1, 7), "radius": ("f", 1.0, 1e-4, 1e4)},
    "cylinder":  {"vertices": ("i", 32, 3, 1024), "radius": ("f", 1.0, 1e-4, 1e4), "depth": ("f", 2.0, 1e-4, 1e4)},
    "cone":      {"vertices": ("i", 32, 3, 1024), "radius1": ("f", 1.0, 0, 1e4), "radius2": ("f", 0.0, 0, 1e4),
                  "depth": ("f", 2.0, 1e-4, 1e4)},
    "torus":     {"major_radius": ("f", 1.0, 1e-4, 1e4), "minor_radius": ("f", 0.25, 1e-4, 1e4),
                  "major_segments": ("i", 48, 3, 1024), "minor_segments": ("i", 12, 3, 512)},
    "monkey":    {"size": ("f", 2.0, 1e-4, 1e4)},
    # A photo-studio sweep: floor curving up into a back wall (+Y), open toward -Y.
    "cyclorama": {"width": ("f", 80.0, 1, 1e4), "depth": ("f", 32.0, 1, 1e4), "height": ("f", 30.0, 1, 1e4),
                  "radius": ("f", 5.0, 0.1, 1e3), "segments": ("i", 24, 2, 128)},
}

MODIFIERS = {
    "subsurf":     {"levels": ("i", 1, 0, 6), "render_levels": ("i", 2, 0, 6)},
    "bevel":       {"width": ("f", 0.02, 0, 100), "segments": ("i", 3, 1, 64),
                    "limit_method": ("s:angle|none", "angle"), "angle_limit": ("f", 30.0, 0, 180)},
    "mirror":      {"axis": ("b3", [True, False, False]), "use_clip": ("b", False), "mirror_object": ("id", None)},
    "array":       {"count": ("i", 2, 1, 1000), "relative_offset": ("v3", [1.0, 0.0, 0.0])},
    "solidify":    {"thickness": ("f", 0.01, -100, 100), "offset": ("f", -1.0, -1, 1)},
    "boolean":     {"operation": ("s:difference|union|intersect", "difference"), "object": ("id", None),
                    "solver": ("s:exact|fast", "exact")},
    "remesh":      {"voxel_size": ("f", 0.05, 1e-3, 100)},
    "decimate":    {"ratio": ("f", 0.5, 0, 1)},
    "weld":        {"merge_threshold": ("f", 0.001, 0, 10)},
    "triangulate": {},
    "wireframe":   {"thickness": ("f", 0.02, 1e-4, 100)},
}

LIGHTS = {
    "point": {"energy": ("f", 1000.0, 0, 1e7), "radius": ("f", 0.1, 0, 1e3)},
    "sun":   {"energy": ("f", 3.0, 0, 1e4), "angle": ("f", 0.5, 0, 180)},
    "spot":  {"energy": ("f", 1000.0, 0, 1e7), "radius": ("f", 0.1, 0, 1e3),
              "spot_size": ("f", 45.0, 1, 180), "spot_blend": ("f", 0.15, 0, 1)},
    "area":  {"energy": ("f", 500.0, 0, 1e7), "shape": ("s:square|rectangle|disk|ellipse", "square"),
              "size": ("f", 1.0, 1e-3, 1e3), "size_y": ("f", 1.0, 1e-3, 1e3)},
}

CAMERA = {"projection": ("s:persp|ortho", "persp"), "lens": ("f", 50.0, 1, 5000),
          "sensor_width": ("f", 36.0, 1, 200), "ortho_scale": ("f", 7.0, 1e-3, 1e5),
          "clip_start": ("f", 0.1, 1e-4, 1e3), "clip_end": ("f", 1000.0, 1e-2, 1e6),
          "dof_fstop": ("f", 0.0, 0, 128)}          # 0 = no depth of field; focus is `dof_focus`

TEXT = {"body": ("t", "Text"), "size": ("f", 1.0, 1e-3, 1e3), "extrude": ("f", 0.0, 0, 100),
        "bevel_depth": ("f", 0.0, 0, 10), "bevel_resolution": ("i", 4, 0, 32),
        "align": ("s:left|center|right", "center")}

MATERIAL = {"base_color": ("c", "#cccccc"), "metallic": ("f", 0.0, 0, 1), "roughness": ("f", 0.5, 0, 1),
            "coat": ("f", 0.0, 0, 1), "transmission": ("f", 0.0, 0, 1), "ior": ("f", 1.45, 1, 3),
            "emission": ("f", 0.0, 0, 100), "alpha": ("f", 1.0, 0, 1),
            # Image maps (texture ids) and how they sit on the UVs — Blender's Mapping node:
            # uv' = offset + rotate(rotation) · (scale · uv). A base-colour image with
            # transparency also drives alpha, as Blender's "Images as Planes" does.
            "base_color_texture": ("tex", None), "roughness_texture": ("tex", None),
            "normal_texture": ("tex", None), "normal_strength": ("f", 1.0, 0, 10),
            "texture_scale": ("v2", [1.0, 1.0]), "texture_offset": ("v2", [0.0, 0.0]),
            "texture_rotation": ("f", 0.0, -360, 360)}
TEXTURE_FIELDS = ("base_color_texture", "roughness_texture", "normal_texture")
# What a preset leaves alone: the name, and the images with their placement.
_KEPT_BY_PRESET = ("name", *TEXTURE_FIELDS, "normal_strength", "texture_scale", "texture_offset", "texture_rotation")

HDRIS = ("studio", "city", "courtyard", "forest", "interior", "night", "sunrise", "sunset")
WORLD = {"kind": ("s:hdri|color", "hdri"), "hdri": ("s:" + "|".join(HDRIS), "studio"),
         "strength": ("f", 0.35, 0, 100), "color": ("c", "#303030"), "rotation": ("f", 0.0, -360, 360)}

RENDER = {"camera": ("id", None), "resolution": ("res", [1280, 720]), "samples": ("i", 32, 1, MAX_SAMPLES),
          "transparent": ("b", False), "denoise": ("b", True)}


# Base colours are the scenes.py linear reflectances, stored as sRGB hex.
def _lin_to_hex(rgb):
    def enc(c):
        c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return max(0, min(255, round(c * 255)))
    return "#" + "".join(f"{enc(c):02x}" for c in rgb)


MATERIAL_PRESETS = {
    "gold":          {"base_color": _lin_to_hex((1.0, 0.766, 0.336)), "metallic": 1.0, "roughness": 0.15},
    "brushed-gold":  {"base_color": _lin_to_hex((1.0, 0.766, 0.336)), "metallic": 1.0, "roughness": 0.38},
    "chrome":        {"base_color": _lin_to_hex((0.95, 0.95, 0.95)), "metallic": 1.0, "roughness": 0.04},
    "brushed-steel": {"base_color": _lin_to_hex((0.78, 0.78, 0.8)), "metallic": 1.0, "roughness": 0.35},
    "copper":        {"base_color": _lin_to_hex((0.955, 0.638, 0.538)), "metallic": 1.0, "roughness": 0.22},
    "plastic":       {"base_color": _lin_to_hex((0.6, 0.02, 0.02)), "metallic": 0.0, "roughness": 0.32},
    "matte":         {"base_color": _lin_to_hex((0.6, 0.6, 0.6)), "metallic": 0.0, "roughness": 0.9},
    "ceramic":       {"base_color": _lin_to_hex((0.85, 0.85, 0.82)), "metallic": 0.0, "roughness": 0.25, "coat": 0.8},
    "glass":         {"base_color": "#ffffff", "metallic": 0.0, "roughness": 0.0, "transmission": 1.0, "ior": 1.45},
    "rubber":        {"base_color": _lin_to_hex((0.02, 0.02, 0.02)), "metallic": 0.0, "roughness": 0.75},
    "neon":          {"base_color": _lin_to_hex((0.02, 0.35, 1.0)), "metallic": 0.0, "roughness": 0.4, "emission": 2.0},
}

# Light rigs, ported from scenes.py: (azimuth°, elevation°, distance, size, watts, rgb) + world strength.
LIGHT_RIGS = {
    "studio-3point": ([(-45, 35, 6, 3.0, 900, (1.0, 0.97, 0.93)), (55, 15, 7, 4.0, 300, (0.93, 0.96, 1.0)),
                       (165, 45, 6, 2.0, 900, (1.0, 1.0, 1.0))], 0.35),
    "softbox":       ([(0, 75, 5, 6.0, 850, (1.0, 1.0, 1.0)), (0, 12, 9, 6.0, 140, (1.0, 1.0, 1.0))], 0.4),
    "dramatic":      ([(-70, 25, 6, 1.0, 700, (1.0, 0.92, 0.82)), (160, 58, 5, 0.8, 550, (0.8, 0.9, 1.0))], 0.12),
    "rim":           ([(-140, 52, 5, 0.8, 650, (1.0, 1.0, 1.0)), (140, 52, 5, 0.8, 650, (1.0, 1.0, 1.0)),
                       (0, 10, 9, 5.0, 160, (1.0, 1.0, 1.0))], 0.1),
}
_RIG_NAMES = ("key", "fill", "rim")
CAMERA_ANGLES = {"front": (0, 8), "front-3/4": (32, 18), "side": (90, 8), "top": (0, 68),
                 "low": (22, 1), "hero": (28, 7)}
_DARK_RIGS = ("dramatic", "rim")
STUDIO_PREFIX = "studio_"


# ─────────────────────────────── small math ───────────────────────────────────

def _deg(v):
    return [math.radians(a) for a in v]


def euler_matrix(rot_deg):
    """Blender XYZ Euler (degrees) → 3×3 row-major rotation: R = Rz·Ry·Rx."""
    x, y, z = _deg(rot_deg)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def matrix_euler(m):
    """3×3 rotation → Blender XYZ Euler in degrees (inverse of euler_matrix)."""
    sy = -m[2][0]
    sy = max(-1.0, min(1.0, sy))
    y = math.asin(sy)
    if abs(sy) < 0.9999999:
        x = math.atan2(m[2][1], m[2][2])
        z = math.atan2(m[1][0], m[0][0])
    else:                                   # gimbal lock: fold z into x
        x = math.atan2(-m[1][2], m[1][1])
        z = 0.0
    return [math.degrees(x), math.degrees(y), math.degrees(z)]


def compose(loc, rot_deg, scale):
    r = euler_matrix(rot_deg)
    return [[r[i][0] * scale[0], r[i][1] * scale[1], r[i][2] * scale[2], loc[i]] for i in range(3)] + [[0, 0, 0, 1]]


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def invert(m):
    """Inverse of an affine 4×4 (rotation·scale + translation)."""
    a = [row[:3] for row in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    if abs(det) < 1e-12:
        raise SceneError("transform is degenerate (a scale of 0?)")
    inv = [[(a[(j + 1) % 3][(i + 1) % 3] * a[(j + 2) % 3][(i + 2) % 3]
             - a[(j + 1) % 3][(i + 2) % 3] * a[(j + 2) % 3][(i + 1) % 3]) / det for j in range(3)] for i in range(3)]
    t = [m[0][3], m[1][3], m[2][3]]
    it = [-sum(inv[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [inv[0] + [it[0]], inv[1] + [it[1]], inv[2] + [it[2]], [0, 0, 0, 1]]


def decompose(m):
    """Affine 4×4 → (location, rotation°, scale). Assumes no shear."""
    loc = [m[0][3], m[1][3], m[2][3]]
    cols = [[m[i][j] for i in range(3)] for j in range(3)]
    scale = [math.sqrt(sum(c * c for c in col)) for col in cols]
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    if det < 0:
        scale[0] = -scale[0]
    r = [[m[i][j] / (scale[j] or 1.0) for j in range(3)] for i in range(3)]
    return loc, matrix_euler(r), scale


def _sub(a, b): return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
def _add(a, b): return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
def _mul(a, s): return [a[0] * s, a[1] * s, a[2] * s]
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
def _norm(a):
    n = math.sqrt(_dot(a, a))
    return [a[0] / n, a[1] / n, a[2] / n] if n > 1e-12 else [0.0, 0.0, 0.0]


def look_rotation(eye, target):
    """Rotation (degrees, XYZ) pointing an object's -Z at target with +Y as up
    as possible — Blender's to_track_quat('-Z', 'Y'), for cameras and lights."""
    f = _norm(_sub(target, eye))
    if f == [0.0, 0.0, 0.0]:
        raise SceneError("look_at target is the object's own position")
    z = _mul(f, -1)
    up = [0.0, 0.0, 1.0] if abs(f[2]) < 0.999 else [0.0, 1.0, 0.0]
    x = _norm(_cross(up, z))
    y = _cross(z, x)
    return matrix_euler([[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]])


def orbit(target, dist, az_deg, el_deg):
    """Point on a sphere round target. Azimuth 0 = in front (−Y), + swings to +X."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    return _add(target, _mul([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)], dist))


# ─────────────────────────────── field validation ─────────────────────────────

def _hex(value, where):
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        try:
            rgb = [float(c) for c in value[:3]]
        except (TypeError, ValueError):
            raise SceneError(f"{where}: {value!r} is not a colour")
        if any(c > 1 for c in rgb):
            rgb = [c / 255 for c in rgb]
        if any(not 0 <= c <= 1 for c in rgb):
            raise SceneError(f"{where}: {value!r} must be 0–1 (or 0–255) per channel")
        return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)
    m = _HEX.match(str(value).strip()) if isinstance(value, str) else None
    if not m:
        raise SceneError(f"{where}: {value!r} is not a hex colour like '#d4af37'")
    h = m.group(1).lower()
    return "#" + ("".join(c * 2 for c in h) if len(h) == 3 else h)


def hex_to_linear(value):
    h = _hex(value, "colour").lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def _field(spec, value, where):
    kind = spec[0]
    if kind in ("f", "i"):
        if isinstance(value, bool):
            raise SceneError(f"{where}: {value!r} is not a number")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise SceneError(f"{where}: {value!r} is not a number")
        if not math.isfinite(v):
            raise SceneError(f"{where}: {value!r} is not a finite number")
        lo, hi = spec[2], spec[3]
        if not lo <= v <= hi:
            raise SceneError(f"{where}: {v:g} is outside {lo:g}–{hi:g}")
        return int(round(v)) if kind == "i" else v
    if kind == "b":
        if not isinstance(value, bool):
            raise SceneError(f"{where}: {value!r} must be true or false")
        return value
    if kind.startswith("s:"):
        opts = kind[2:].split("|")
        v = str(value).strip().lower()
        if v not in opts:
            raise SceneError(f"{where}: {value!r} — choose one of {', '.join(opts)}")
        return v
    if kind == "c":
        return _hex(value, where)
    if kind == "t":
        s = str(value)
        if not s or len(s) > 200:
            raise SceneError(f"{where}: 1–200 characters")
        return s
    if kind in ("v3", "b3"):
        if not (isinstance(value, (list, tuple)) and len(value) == 3):
            raise SceneError(f"{where}: needs 3 values, like {spec[1]}")
        if kind == "b3":
            if not all(isinstance(v, bool) for v in value):
                raise SceneError(f"{where}: three true/false values")
            return list(value)
        return [_field(("f", 0, -1e6, 1e6), v, f"{where}[{i}]") for i, v in enumerate(value)]
    if kind in ("id", "tex"):
        if value is None:
            return None
        if not isinstance(value, str) or not _ID.match(value):
            raise SceneError(f"{where}: {value!r} is not {'a texture' if kind == 'tex' else 'an object'} id")
        return value
    if kind == "v2":
        if not (isinstance(value, (list, tuple)) and len(value) == 2):
            raise SceneError(f"{where}: needs 2 values, like {spec[1]}")
        return [_field(("f", 0, -1e4, 1e4), v, f"{where}[{i}]") for i, v in enumerate(value)]
    if kind == "res":
        if not (isinstance(value, (list, tuple)) and len(value) == 2):
            raise SceneError(f"{where}: [width, height]")
        w, h = (_field(("i", 0, 16, 4096), v, where) for v in value)
        if w * h > MAX_PIXELS:
            raise SceneError(f"{where}: {w}x{h} is over the {MAX_PIXELS:,}-pixel cap (1920x1080)")
        return [w, h]
    raise AssertionError(kind)


def _fill(specs, given, where, extra=()):
    """Validate `given` against `specs`, filling defaults. Unknown keys are an
    error, so a typo never silently falls back to the default."""
    given = given or {}
    if not isinstance(given, dict):
        raise SceneError(f"{where}: must be an object")
    unknown = sorted(set(given) - set(specs) - set(extra))
    if unknown:
        raise SceneError(f"{where}: unknown {', '.join(unknown)} — allowed: {', '.join(sorted(specs))}")
    out = {}
    for key, spec in specs.items():
        out[key] = _field(spec, given[key], f"{where}.{key}") if key in given else copy.deepcopy(spec[1])
    return out


def _vec3(value, where, default):
    if value is None:
        return list(default)
    if not (isinstance(value, (list, tuple)) and len(value) == 3):
        raise SceneError(f"{where}: needs [x, y, z]")
    return [_field(("f", 0, -1e6, 1e6), v, f"{where}[{i}]") for i, v in enumerate(value)]


# ─────────────────────────────── normalize ────────────────────────────────────

_OBJECT_KEYS = {"name", "type", "parent", "location", "rotation", "scale", "visible", "renderable",
                "mesh", "material", "materials", "shading", "modifiers", "light", "camera", "text", "dof_focus"}


def _mesh(mid, m):
    where = f"meshes.{mid}"
    if not isinstance(m, dict):
        raise SceneError(f"{where}: must be an object")
    if "primitive" in m:
        prim = str(m["primitive"]).lower()
        if prim not in PRIMITIVES:
            raise SceneError(f"{where}.primitive: {m['primitive']!r} — choose one of {', '.join(PRIMITIVES)}")
        params = {k: v for k, v in m.items() if k != "primitive"}
        return {"primitive": prim, **_fill(PRIMITIVES[prim], params, where)}
    if "data" in m:
        data = m["data"]
        if not (isinstance(data, str) and re.match(r"^meshes/m-[0-9a-f]{12}\.json$", data)):
            raise SceneError(f"{where}.data: must be meshes/m-<12 hex>.json")
        unknown = sorted(set(m) - {"data", "verts", "faces", "bbox"})
        if unknown:
            raise SceneError(f"{where}: unknown {', '.join(unknown)}")
        bbox = m.get("bbox") or [[-1, -1, -1], [1, 1, 1]]
        if not (isinstance(bbox, list) and len(bbox) == 2):
            raise SceneError(f"{where}.bbox: [[minx,miny,minz],[maxx,maxy,maxz]]")
        return {"data": data, "verts": _field(("i", 0, 0, 10_000_000), m.get("verts", 0), f"{where}.verts"),
                "faces": _field(("i", 0, 0, 10_000_000), m.get("faces", 0), f"{where}.faces"),
                "bbox": [_vec3(bbox[0], f"{where}.bbox[0]", [0, 0, 0]), _vec3(bbox[1], f"{where}.bbox[1]", [0, 0, 0])]}
    raise SceneError(f"{where}: needs `primitive` (e.g. \"cube\") or `data` (an explicit mesh file)")


def _texture(tid, t):
    """An image the materials use: a `cycls.texture` file under data/textures (named by its
    content), its size, and whether it has transparency."""
    where = f"textures.{tid}"
    if not isinstance(t, dict):
        raise SceneError(f"{where}: must be an object")
    unknown = sorted(set(t) - {"name", "data", "width", "height", "alpha"})
    if unknown:
        raise SceneError(f"{where}: unknown {', '.join(unknown)}")
    data = t.get("data")
    if not (isinstance(data, str) and re.match(r"^textures/t-[0-9a-f]{12}\.json$", data)):
        raise SceneError(f"{where}.data: must be textures/t-<12 hex>.json")
    return {"name": str(t.get("name") or tid)[:64], "data": data,
            "width": _field(("i", 0, 1, 8192), t.get("width", 1), f"{where}.width"),
            "height": _field(("i", 0, 1, 8192), t.get("height", 1), f"{where}.height"),
            "alpha": _field(("b", False), bool(t.get("alpha", False)), f"{where}.alpha")}


def _material(mid, m):
    where = f"materials.{mid}"
    if not isinstance(m, dict):
        raise SceneError(f"{where}: must be an object")
    m = dict(m)
    preset = m.pop("preset", None)
    name = m.pop("name", None) or mid
    base = {}
    if preset is not None:
        p = str(preset).lower()
        if p not in MATERIAL_PRESETS:
            raise SceneError(f"{where}.preset: {preset!r} — choose one of {', '.join(MATERIAL_PRESETS)}")
        base = dict(MATERIAL_PRESETS[p])
        preset = p
    base.update(m)
    out = {"name": str(name)[:64], "preset": preset, **_fill(MATERIAL, base, where)}
    return out


def _modifiers(oid, mods):
    where = f"objects.{oid}.modifiers"
    if mods is None:
        return []
    if not isinstance(mods, list):
        raise SceneError(f"{where}: must be a list")
    out = []
    for i, mod in enumerate(mods):
        w = f"{where}[{i}]"
        if not isinstance(mod, dict) or "type" not in mod:
            raise SceneError(f"{w}: needs a `type` ({', '.join(MODIFIERS)})")
        t = str(mod["type"]).lower()
        if t not in MODIFIERS:
            raise SceneError(f"{w}.type: {mod['type']!r} — choose one of {', '.join(MODIFIERS)}")
        params = {k: v for k, v in mod.items() if k not in ("type", "show")}
        show = mod.get("show", True)
        if not isinstance(show, bool):
            raise SceneError(f"{w}.show: true or false")
        out.append({"type": t, **_fill(MODIFIERS[t], params, w), "show": show})
    return out


def _object(oid, o):
    where = f"objects.{oid}"
    if not isinstance(o, dict):
        raise SceneError(f"{where}: must be an object")
    unknown = sorted(set(o) - _OBJECT_KEYS)
    if unknown:
        raise SceneError(f"{where}: unknown {', '.join(unknown)} — allowed: {', '.join(sorted(_OBJECT_KEYS))}")
    t = str(o.get("type", "mesh")).lower()
    if t not in ("mesh", "light", "camera", "empty", "text"):
        raise SceneError(f"{where}.type: {o.get('type')!r} — choose mesh, light, camera, empty or text")
    out = {"name": str(o.get("name") or oid)[:64], "type": t,
           "parent": _field(("id", None), o.get("parent"), f"{where}.parent"),
           "location": _vec3(o.get("location"), f"{where}.location", [0, 0, 0]),
           "rotation": _vec3(o.get("rotation"), f"{where}.rotation", [0, 0, 0]),
           "scale": _vec3(o.get("scale"), f"{where}.scale", [1, 1, 1]),
           "visible": _field(("b", True), o.get("visible", True), f"{where}.visible"),
           "renderable": _field(("b", True), o.get("renderable", True), f"{where}.renderable")}
    if t in ("mesh", "text"):
        out["materials"] = _slots(o, where)
        out["shading"] = _field(("s:smooth|flat|auto", "auto"), o.get("shading", "auto"), f"{where}.shading")
        out["modifiers"] = _modifiers(oid, o.get("modifiers"))
    if t == "mesh":
        if not o.get("mesh"):
            raise SceneError(f"{where}.mesh: a mesh object needs a mesh id")
        out["mesh"] = _field(("id", None), o["mesh"], f"{where}.mesh")
    elif t == "light":
        light = dict(o.get("light") or {})
        kind = str(light.pop("kind", "point")).lower()
        if kind not in LIGHTS:
            raise SceneError(f"{where}.light.kind: {kind!r} — choose one of {', '.join(LIGHTS)}")
        color = _hex(light.pop("color", "#ffffff"), f"{where}.light.color")
        out["light"] = {"kind": kind, "color": color, **_fill(LIGHTS[kind], light, f"{where}.light")}
    elif t == "camera":
        out["camera"] = _fill(CAMERA, o.get("camera"), f"{where}.camera")
        out["dof_focus"] = _field(("id", None), o.get("dof_focus"), f"{where}.dof_focus")
    elif t == "text":
        out["text"] = _fill(TEXT, o.get("text"), f"{where}.text")
    for k in ("mesh", "light", "camera", "text", "dof_focus", "material", "materials", "shading", "modifiers"):
        if k in o and k not in out and not (k in ("material", "materials", "modifiers") and not o[k]) \
                and not (k == "material" and "materials" in out):
            raise SceneError(f"{where}.{k}: not valid on {'an' if t == 'empty' else 'a'} {t} object"
                             + (f" — set \"type\": \"{k}\"" if k in ("light", "camera", "text") else ""))
    return out


def _slots(o, where):
    """An object's material slots — Blender's: a face's material_index picks one. `material`
    (version 1's single field, and still what ops accept) is slot 0."""
    slots = o.get("materials")
    if slots is None:
        slots = []
    if not isinstance(slots, list) or len(slots) > MAX_SLOTS:
        raise SceneError(f"{where}.materials: a list of up to {MAX_SLOTS} material ids (or null)")
    slots = [_field(("id", None), m, f"{where}.materials[{i}]") for i, m in enumerate(slots)]
    if "material" in o:
        m = _field(("id", None), o["material"], f"{where}.material")
        if slots:
            slots[0] = m
        elif m is not None:
            slots = [m]
    while slots and slots[-1] is None:
        slots.pop()
    return slots


def _check_refs(doc):
    objs, meshes, mats = doc["objects"], doc["meshes"], doc["materials"]
    for oid, o in objs.items():
        p = o["parent"]
        if p is not None and p not in objs:
            raise SceneError(f"objects.{oid}.parent: no object {p!r}")
        seen, cur = {oid}, p
        while cur is not None:
            if cur in seen:
                raise SceneError(f"objects.{oid}.parent: parenting loops back on itself")
            seen.add(cur)
            cur = objs[cur]["parent"]
        if o["type"] == "mesh" and o["mesh"] not in meshes:
            raise SceneError(f"objects.{oid}.mesh: no mesh {o['mesh']!r}")
        for i, m in enumerate(o.get("materials", [])):
            if m is not None and m not in mats:
                raise SceneError(f"objects.{oid}.materials[{i}]: no material {m!r}")
        for i, mod in enumerate(o.get("modifiers", [])):
            ref = mod.get("object") if mod["type"] == "boolean" else mod.get("mirror_object") if mod["type"] == "mirror" else None
            if mod["type"] == "boolean" and ref is None:
                raise SceneError(f"objects.{oid}.modifiers[{i}].object: a boolean needs a cutter object")
            if ref is not None and (ref not in objs or ref == oid):
                raise SceneError(f"objects.{oid}.modifiers[{i}]: no other object {ref!r}")
        if o.get("dof_focus") is not None and o["dof_focus"] not in objs:
            raise SceneError(f"objects.{oid}.dof_focus: no object {o['dof_focus']!r}")
    for mid, m in mats.items():
        for f in TEXTURE_FIELDS:
            if m[f] is not None and m[f] not in doc["textures"]:
                raise SceneError(f"materials.{mid}.{f}: no texture {m[f]!r}")
    cam = doc["render"]["camera"]
    if cam is not None and (cam not in objs or objs[cam]["type"] != "camera"):
        raise SceneError(f"render.camera: {cam!r} is not a camera object")


SECTIONS = ("objects", "meshes", "materials", "textures")     # the maps of id → entry


def normalize(doc):
    """Validate a whole document and fill every default. Idempotent."""
    if not isinstance(doc, dict):
        raise SceneError("scene: must be a JSON object")
    doc = migrate(doc)
    unknown = sorted(set(doc) - {"format", "version", "rev", "by", "saved_at", "units", "up",
                                 "objects", "meshes", "materials", "textures", "world", "render"})
    if unknown:
        raise SceneError(f"scene: unknown {', '.join(unknown)}")
    out = {"format": FORMAT, "version": VERSION,
           "rev": _field(("i", 0, 0, 10 ** 12), doc.get("rev", 0), "rev"),
           "by": str(doc.get("by") or "")[:64], "saved_at": str(doc.get("saved_at") or "")[:40],
           "units": "m", "up": "Z"}
    for section in SECTIONS:
        val = doc.get(section) or {}
        if not isinstance(val, dict):
            raise SceneError(f"{section}: must be a map of id → entry")
        for k in val:
            if not isinstance(k, str) or not _ID.match(k):
                raise SceneError(f"{section}: {k!r} is not a valid id (letters, digits, _ . -)")
    if len(doc.get("objects") or {}) > MAX_OBJECTS:
        raise SceneError(f"objects: at most {MAX_OBJECTS}")
    if len(doc.get("textures") or {}) > MAX_TEXTURES:
        raise SceneError(f"textures: at most {MAX_TEXTURES}")
    out["objects"] = {k: _object(k, v) for k, v in (doc.get("objects") or {}).items()}
    out["meshes"] = {k: _mesh(k, v) for k, v in (doc.get("meshes") or {}).items()}
    out["materials"] = {k: _material(k, v) for k, v in (doc.get("materials") or {}).items()}
    out["textures"] = {k: _texture(k, v) for k, v in (doc.get("textures") or {}).items()}
    out["world"] = _fill(WORLD, doc.get("world"), "world")
    out["render"] = _fill(RENDER, doc.get("render"), "render")
    _check_refs(out)
    return out


def migrate(doc):
    """Older documents read as the current one. Version 1 → 2 is `_slots` taking an
    object's single `material` as slot 0, so nothing else needs doing here."""
    v = doc.get("version", VERSION)
    if v not in (1, VERSION):
        if isinstance(v, int) and v > VERSION:
            raise SceneError(f"scene version {v} is newer than this Studio ({VERSION}) — update Studio")
        raise SceneError(f"scene version {v!r} is not supported")
    if doc.get("format", FORMAT) != FORMAT:
        raise SceneError(f"format {doc.get('format')!r} is not a Studio scene")
    return doc


def new_scene():
    """Blender's startup scene — a cube, a light, a camera looking at it — with
    the cube standing on the floor (z = 0) rather than through it."""
    eye = [7.36, -6.93, 4.96]
    return normalize({
        "objects": {
            "cube": {"name": "Cube", "type": "mesh", "mesh": "cube", "material": "material", "location": [0, 0, 1]},
            "light": {"name": "Light", "type": "light", "location": [4.08, 1.01, 5.9],
                      "rotation": [37.3, 3.2, 106.9], "light": {"kind": "point", "energy": 1000}},
            "camera": {"name": "Camera", "type": "camera", "location": eye,
                       "rotation": [round(a, 4) for a in look_rotation(eye, [0, 0, 1])], "camera": {"lens": 50}},
        },
        "meshes": {"cube": {"primitive": "cube"}},
        "materials": {"material": {"name": "Material", "base_color": "#cccccc", "roughness": 0.5}},
        "render": {"camera": "camera"},
    })


# ─────────────────────────────── bounds + transforms ──────────────────────────

def local_bounds(doc, oid):
    """Axis-aligned bounds of an object in its own space (before modifiers)."""
    o = doc["objects"][oid]
    if o["type"] == "text":
        t = o["text"]
        w = max(1, len(t["body"])) * t["size"] * 0.6
        h = t["size"] * 0.75
        x0 = {"left": 0, "center": -w / 2, "right": -w}[t["align"]]
        return [[x0, -h / 2, 0], [x0 + w, h / 2, max(t["extrude"], 1e-3)]]
    if o["type"] != "mesh":
        return [[-0.1, -0.1, -0.1], [0.1, 0.1, 0.1]]
    m = doc["meshes"][o["mesh"]]
    if "bbox" in m:
        return m["bbox"]
    p = m["primitive"]
    if p in ("plane", "grid"):
        s = m["size"] / 2
        return [[-s, -s, 0], [s, s, 0]]
    if p == "circle":
        r = m["radius"]
        return [[-r, -r, 0], [r, r, 0]]
    if p in ("cube", "monkey"):
        s = m["size"] / 2
        k = [1.37, 0.85, 0.98] if p == "monkey" else [1, 1, 1]
        return [[-s * k[0], -s * k[1], -s * k[2]], [s * k[0], s * k[1], s * k[2]]]
    if p in ("uv_sphere", "ico_sphere"):
        r = m["radius"]
        return [[-r, -r, -r], [r, r, r]]
    if p in ("cylinder", "cone"):
        r = m["radius"] if p == "cylinder" else max(m["radius1"], m["radius2"])
        d = m["depth"] / 2
        return [[-r, -r, -d], [r, r, d]]
    if p == "torus":
        r = m["major_radius"] + m["minor_radius"]
        return [[-r, -r, -m["minor_radius"]], [r, r, m["minor_radius"]]]
    if p == "cyclorama":
        return [[-m["width"] / 2, -m["depth"], 0], [m["width"] / 2, m["radius"], m["height"]]]
    raise AssertionError(p)


def world_matrix(doc, oid):
    o = doc["objects"][oid]
    m = compose(o["location"], o["rotation"], o["scale"])
    return matmul(world_matrix(doc, o["parent"]), m) if o["parent"] else m


def world_bounds(doc, oid):
    (x0, y0, z0), (x1, y1, z1) = local_bounds(doc, oid)
    w = world_matrix(doc, oid)
    pts = []
    for x in (x0, x1):
        for y in (y0, y1):
            for z in (z0, z1):
                pts.append([sum(w[i][k] * p for k, p in enumerate((x, y, z))) + w[i][3] for i in range(3)])
    return [[min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]]


def _is_ground(doc, k):
    """A floor, a ground plane, a backdrop sheet: flat and wide. Set dressing to
    stand things on, not something to frame."""
    (x0, y0, z0), (x1, y1, z1) = world_bounds(doc, k)
    return (z1 - z0) < 0.03 * max(x1 - x0, y1 - y0, 1e-9)


def subject_ids(doc):
    """What a camera should frame: renderable meshes/text that aren't studio set
    dressing or a flat ground plane."""
    return [k for k, o in doc["objects"].items()
            if o["type"] in ("mesh", "text") and o["renderable"] and o["visible"]
            and not k.startswith(STUDIO_PREFIX) and not _is_ground(doc, k)]


def _bounds_of(doc, ids):
    if not ids:
        return [[-1, -1, 0], [1, 1, 2]]
    bs = [world_bounds(doc, i) for i in ids]
    return [[min(b[0][i] for b in bs) for i in range(3)], [max(b[1][i] for b in bs) for i in range(3)]]


def _fov_short(doc, cam):
    c = doc["objects"][cam]["camera"]
    w, h = doc["render"]["resolution"]
    half = math.atan(c["sensor_width"] / 2 / c["lens"])
    return math.atan(math.tan(half) * min(w, h) / max(w, h))


# ─────────────────────────────── ops ──────────────────────────────────────────

_SINGULAR = {"objects": "object", "meshes": "mesh", "materials": "material", "textures": "texture"}


def _new_id(doc, section, base):
    fallback = _SINGULAR[section]
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(base or fallback)).strip("_.-").lower()[:48] or fallback
    if base not in doc[section]:
        return base
    n = 2
    while f"{base}_{n}" in doc[section]:
        n += 1
    return f"{base}_{n}"


def _targets(doc, ref, selection, where):
    if ref == "selected":
        ids = [i for i in (selection or []) if i in doc["objects"]]
        if not ids:
            raise SceneError(f"{where}: nothing is selected in the Studio")
        return ids
    if isinstance(ref, list):
        return [x for r in ref for x in _targets(doc, r, selection, where)]
    if ref not in doc["objects"]:
        raise SceneError(f"{where}: no object {ref!r}")
    return [ref]


def _deep_merge(base, patch):
    out = copy.deepcopy(base)
    for k, v in patch.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def _on_floor(doc, oid):
    """Drop a root object so its lowest point sits on z = 0."""
    o = doc["objects"][oid]
    if o["parent"] is None:
        o["location"][2] -= world_bounds(doc, oid)[0][2]


def _op_add(doc, op, where, selection):
    t = str(op.get("type") or ("mesh" if op.get("primitive") or op.get("mesh") or op.get("image") else
                               next((k for k in ("light", "camera", "text") if k in op), "empty"))).lower()
    oid = op.get("id") or _new_id(doc, "objects", op.get("name") or op.get("primitive") or t)
    if oid in doc["objects"]:
        raise SceneError(f"{where}.id: {oid!r} already exists — use `set` to change it")
    obj = {k: op[k] for k in ("name", "parent", "location", "rotation", "scale", "visible", "renderable",
                              "shading", "modifiers", "light", "camera", "text", "dof_focus") if k in op}
    obj["type"] = t
    obj.setdefault("name", str(op.get("name") or oid).replace("_", " ").title())
    if t == "mesh" and op.get("image") is None:
        if op.get("primitive"):
            mid = _new_id(doc, "meshes", oid)
            doc["meshes"][mid] = {"primitive": op["primitive"], **(op.get("params") or {})}
            obj["mesh"] = mid
        elif op.get("mesh"):
            obj["mesh"] = op["mesh"]
        else:
            raise SceneError(f"{where}: a mesh needs `primitive` (e.g. \"torus\") or an existing `mesh` id")
    if op.get("image") is not None:
        if t != "mesh" or op.get("primitive") not in (None, "plane"):
            raise SceneError(f"{where}.image: an image goes on a plane — drop `primitive`, or use \"plane\"")
        tex = doc["textures"].get(op["image"]) if isinstance(op["image"], str) else None
        if tex is None:
            raise SceneError(f"{where}.image: no texture {op['image']!r} — add it first with the `texture` op")
        h = _field(("f", 1.0, 1e-3, 1e3), op.get("height", 1.0), f"{where}.height")
        mid = _new_id(doc, "meshes", oid)
        doc["meshes"][mid] = {"primitive": "plane", "size": h}
        obj["mesh"] = mid
        obj.setdefault("rotation", [90, 0, 0])             # standing up, facing −Y (the front)
        sx, sy, sz = _vec3(op.get("scale"), f"{where}.scale", [1, 1, 1])
        obj["scale"] = [sx * tex["width"] / tex["height"], sy, sz]   # a given scale sizes it, never squashes it
        if op.get("material") is None:
            mat_id = _new_id(doc, "materials", f"{oid}_image")
            doc["materials"][mat_id] = {"name": tex["name"], "base_color": "#ffffff", "roughness": 0.5,
                                        "base_color_texture": op["image"]}
            op = {**op, "material": mat_id}
    if t in ("mesh", "text"):
        mat = op.get("material")
        if isinstance(mat, (dict, str)) and not (isinstance(mat, str) and mat in doc["materials"]):
            spec = {"preset": mat} if isinstance(mat, str) else dict(mat)
            mid = _new_id(doc, "materials", spec.get("name") or spec.get("preset") or f"{oid}_material")
            doc["materials"][mid] = spec
            mat = mid
        obj["material"] = mat
        if op.get("materials") is not None:
            obj["materials"] = op["materials"]
    doc["objects"][oid] = obj
    doc.update(normalize(doc))
    if op.get("on_floor"):
        _on_floor(doc, oid)
    if op.get("look_at") is not None:
        _look_at(doc, oid, op["look_at"], where, selection)
    return [f"objects.{oid}"] + ([f"meshes.{obj['mesh']}"] if t == "mesh" and op.get("primitive") else [])


def _op_set(doc, op, where, selection):
    ids = _targets(doc, op.get("id"), selection, f"{where}.id")
    patch = {k: v for k, v in op.items() if k not in ("op", "id", "on_floor", "params")}
    touched = []
    for oid in ids:
        doc["objects"][oid] = _deep_merge(doc["objects"][oid], patch)
        if op.get("params"):
            mid = doc["objects"][oid].get("mesh")
            if not mid or "primitive" not in doc["meshes"].get(mid, {}):
                raise SceneError(f"{where}.params: {oid!r} has no primitive mesh to change")
            doc["meshes"][mid] = _deep_merge(doc["meshes"][mid], op["params"])
            touched.append(f"meshes.{mid}")
        if patch or op.get("on_floor"):
            touched.append(f"objects.{oid}")
    doc.update(normalize(doc))
    if op.get("on_floor"):
        for oid in ids:
            _on_floor(doc, oid)
    return touched


def _op_delete(doc, op, where, selection):
    ids = _targets(doc, op.get("id"), selection, f"{where}.id")
    touched = []
    for oid in ids:
        # Children keep their place in the world, as in Blender.
        for cid, c in doc["objects"].items():
            if c["parent"] == oid:
                loc, rot, scl = decompose(world_matrix(doc, cid))
                c.update(parent=doc["objects"][oid]["parent"], location=loc, rotation=rot, scale=scl)
                if c["parent"]:
                    loc, rot, scl = decompose(matmul(invert(world_matrix(doc, c["parent"])),
                                                     compose(loc, rot, scl)))
                    c.update(location=loc, rotation=rot, scale=scl)
                touched.append(f"objects.{cid}")
        for o in doc["objects"].values():
            for mod in o.get("modifiers", []):
                if mod.get("object") == oid or mod.get("mirror_object") == oid:
                    raise SceneError(f"{where}: {oid!r} is used by a modifier on another object — remove that first")
            if o.get("dof_focus") == oid:
                o["dof_focus"] = None
        if doc["render"]["camera"] == oid:
            doc["render"]["camera"] = None
        del doc["objects"][oid]
        touched.append(f"objects.{oid}")
    # Drop meshes nothing uses any more.
    used = {o.get("mesh") for o in doc["objects"].values()}
    for mid in [m for m in doc["meshes"] if m not in used]:
        del doc["meshes"][mid]
        touched.append(f"meshes.{mid}")
    doc.update(normalize(doc))
    return touched


def _op_duplicate(doc, op, where, selection):
    src_ids = _targets(doc, op.get("id"), selection, f"{where}.id")
    touched = []
    for src in src_ids:
        o = copy.deepcopy(doc["objects"][src])
        nid = op.get("new_id") if len(src_ids) == 1 and op.get("new_id") else _new_id(doc, "objects", src)
        if nid in doc["objects"]:
            raise SceneError(f"{where}.new_id: {nid!r} already exists")
        o["name"] = f"{o['name']}.001" if "name" not in op else op["name"]
        if o["type"] == "mesh" and op.get("linked") is not True:
            mid = _new_id(doc, "meshes", nid)
            doc["meshes"][mid] = copy.deepcopy(doc["meshes"][o["mesh"]])
            o["mesh"] = mid
            touched.append(f"meshes.{mid}")
        o["location"] = _add(o["location"], _vec3(op.get("offset"), f"{where}.offset", [0, 0, 0]))
        doc["objects"][nid] = o
        touched.append(f"objects.{nid}")
    doc.update(normalize(doc))
    return touched


def _op_material(doc, op, where, selection):
    spec = {k: v for k, v in op.items() if k not in ("op", "id", "assign", "slot")}
    mid = op.get("id") or _new_id(doc, "materials", spec.get("name") or spec.get("preset") or "material")
    current = doc["materials"].get(mid, {})
    if spec.get("preset"):                          # a preset resets what it defines — not the images
        current = {k: v for k, v in current.items() if k in _KEPT_BY_PRESET}
    doc["materials"][mid] = {**current, **spec}
    touched = [f"materials.{mid}"]
    if op.get("assign") is not None:
        for oid in _targets(doc, op["assign"], selection, f"{where}.assign"):
            if doc["objects"][oid]["type"] not in ("mesh", "text"):
                raise SceneError(f"{where}.assign: {oid!r} is a {doc['objects'][oid]['type']}, it takes no material")
            o = doc["objects"][oid]
            slots, slot = list(o.get("materials", [])), _field(("i", 0, 0, MAX_SLOTS - 1), op.get("slot", 0),
                                                              f"{where}.slot")
            if slot > len(slots):
                raise SceneError(f"{where}.slot: {oid!r} has {len(slots)} slot(s) — use {len(slots)} to add one")
            slots[slot:slot + 1] = [mid]
            o["materials"] = slots
            o.pop("material", None)
            touched.append(f"objects.{oid}")
    doc.update(normalize(doc))
    return touched


def _op_texture(doc, op, where, selection):
    """Register an image file the caller already stored (the tool resolves a workspace
    `path` into `data`/`width`/`height`/`alpha` first). Unused textures are dropped at the
    end of the batch, so add one and use it in the same edit."""
    tid = op.get("id") or _new_id(doc, "textures", op.get("name") or "texture")
    doc["textures"][tid] = {k: op[k] for k in ("name", "data", "width", "height", "alpha") if k in op}
    doc.update(normalize(doc))
    return [f"textures.{tid}"]


def _op_modifier(doc, op, where, selection):
    ids = _targets(doc, op.get("object"), selection, f"{where}.object")
    action = str(op.get("action", "add")).lower()
    touched = []
    for oid in ids:
        o = doc["objects"][oid]
        if o["type"] not in ("mesh", "text"):
            raise SceneError(f"{where}.object: {oid!r} is a {o['type']}, it takes no modifiers")
        mods = o["modifiers"]
        params = dict(op.get("params") or {})
        if action == "add":
            if not op.get("type"):
                raise SceneError(f"{where}.type: which modifier ({', '.join(MODIFIERS)})")
            mods.append({"type": op["type"], **params})
        else:
            idx = op.get("index")
            if idx is None and op.get("type"):
                idx = next((i for i, m in enumerate(mods) if m["type"] == str(op["type"]).lower()), None)
            if not isinstance(idx, int) or not 0 <= idx < len(mods):
                raise SceneError(f"{where}.index: {oid!r} has {len(mods)} modifier(s) — give index or type")
            if action == "set":
                mods[idx] = {**mods[idx], **params}
            elif action == "remove":
                mods.pop(idx)
            elif action == "move":
                to = op.get("to")
                if not isinstance(to, int) or not 0 <= to < len(mods):
                    raise SceneError(f"{where}.to: 0–{len(mods) - 1}")
                mods.insert(to, mods.pop(idx))
            else:
                raise SceneError(f"{where}.action: add, set, remove or move")
        touched.append(f"objects.{oid}")
    doc.update(normalize(doc))
    return touched


def _op_section(section):
    def run(doc, op, where, selection):
        patch = {k: v for k, v in op.items() if k != "op"}
        doc[section] = {**doc[section], **patch}
        doc.update(normalize(doc))
        return [section]
    return run


def _look_at(doc, oid, target, where, selection):
    if isinstance(target, str):
        tid = _targets(doc, target, selection, f"{where}.target")[0]
        b = world_bounds(doc, tid)
        point = [(b[0][i] + b[1][i]) / 2 for i in range(3)]
    else:
        point = _vec3(target, f"{where}.target", [0, 0, 0])
    o = doc["objects"][oid]
    eye = world_matrix(doc, oid)
    o["rotation"] = look_rotation([eye[0][3], eye[1][3], eye[2][3]], point)
    if o["parent"]:
        _, rot, _ = decompose(matmul(invert(world_matrix(doc, o["parent"])),
                                     compose([0, 0, 0], o["rotation"], [1, 1, 1])))
        o["rotation"] = rot


def _op_look_at(doc, op, where, selection):
    ids = _targets(doc, op.get("id"), selection, f"{where}.id")
    for oid in ids:
        _look_at(doc, oid, op.get("target"), where, selection)
    doc.update(normalize(doc))
    return [f"objects.{i}" for i in ids]


def _op_frame(doc, op, where, selection):
    """Move a camera along its view direction until the targets fit the frame."""
    cam = op.get("camera") or doc["render"]["camera"]
    if cam not in doc["objects"] or doc["objects"][cam]["type"] != "camera":
        raise SceneError(f"{where}.camera: no camera to frame with — add one first")
    targets = op.get("targets")
    ids = _targets(doc, targets, selection, f"{where}.targets") if targets else subject_ids(doc)
    (x0, y0, z0), (x1, y1, z1) = _bounds_of(doc, ids)
    center = [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]
    radius = max(1e-3, math.dist((x0, y0, z0), (x1, y1, z1)) / 2)
    margin = _field(("f", 1.1, 0.5, 5), op.get("margin", 1.1), f"{where}.margin")
    angle = op.get("angle")
    o = doc["objects"][cam]
    if angle is not None:
        a = str(angle).lower()
        if a not in CAMERA_ANGLES:
            raise SceneError(f"{where}.angle: {angle!r} — choose one of {', '.join(CAMERA_ANGLES)}")
        az, el = CAMERA_ANGLES[a]
        direction = _norm(_sub(orbit([0, 0, 0], 1, az, el), [0, 0, 0]))
    else:
        r = euler_matrix(o["rotation"])
        direction = [r[0][2], r[1][2], r[2][2]]       # the camera's +Z points back at the viewer
    dist = radius * margin / math.sin(_fov_short(doc, cam))
    eye = _add(center, _mul(direction, dist))
    if eye[2] < 0.05:
        eye[2] = 0.05
    o["parent"] = None
    o["location"] = eye
    o["rotation"] = look_rotation(eye, center)
    doc.update(normalize(doc))
    return [f"objects.{cam}"]


def _op_preset(doc, op, where, selection):
    """Studio set dressing, ported from scenes.py: a cyclorama backdrop, a light
    rig aimed at the subjects, a camera angle, and the world. Re-running replaces
    the previous studio_* entries rather than stacking them."""
    spec = op.get("studio")
    if not isinstance(spec, dict):
        raise SceneError(f"{where}.studio: {{lighting, backdrop, camera}}")
    rig = str(spec.get("lighting", "studio-3point")).lower()
    if rig not in LIGHT_RIGS:
        raise SceneError(f"{where}.studio.lighting: {rig!r} — choose one of {', '.join(LIGHT_RIGS)}")
    backdrop = _hex(spec.get("backdrop") or ("#141417" if rig in _DARK_RIGS else "#d6d6db"),
                    f"{where}.studio.backdrop")
    touched = []
    for sec in ("objects", "meshes", "materials"):
        for k in [k for k in doc[sec] if k.startswith(STUDIO_PREFIX)]:
            del doc[sec][k]
            touched.append(f"{sec}.{k}")
    ids = subject_ids(doc)
    (x0, y0, z0), (x1, y1, z1) = _bounds_of(doc, ids)
    scale = max(1.0, max(x1 - x0, y1 - y0, z1 - z0) / 2)     # rigs were tuned for a 2-unit subject
    target = [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]
    floor = 0.0                      # the floor is z = 0 — where `on_floor` stands things
    doc["meshes"]["studio_backdrop"] = {"primitive": "cyclorama"}
    doc["materials"]["studio_backdrop"] = {"name": "Backdrop", "base_color": backdrop, "roughness": 0.55}
    doc["objects"]["studio_backdrop"] = {"name": "Backdrop", "type": "mesh", "mesh": "studio_backdrop",
                                         # the sweep's curve starts 2 units behind the subject
                                         "material": "studio_backdrop",
                                         "location": [target[0], target[1] + 2 * scale, floor],
                                         "shading": "smooth"}
    lights, world_strength = LIGHT_RIGS[rig]
    for (az, el, d, size, watts, rgb), name in zip(lights, _RIG_NAMES):
        lid = f"{STUDIO_PREFIX}{name}"
        eye = orbit(target, d * scale, az, el)
        doc["objects"][lid] = {"name": name.title(), "type": "light", "location": eye,
                               "rotation": look_rotation(eye, target),
                               "light": {"kind": "area", "energy": watts * scale * scale, "size": size * scale,
                                         "color": _lin_to_hex(rgb)}}
    doc["world"] = {**doc["world"], "kind": "hdri", "hdri": "studio", "strength": world_strength}
    touched += [f"objects.{STUDIO_PREFIX}{n}" for n in _RIG_NAMES[:len(lights)]]
    touched += ["objects.studio_backdrop", "meshes.studio_backdrop", "materials.studio_backdrop", "world"]
    cam = doc["render"]["camera"]
    if cam is None:
        cam = _new_id(doc, "objects", "camera")
        doc["objects"][cam] = {"name": "Camera", "type": "camera"}
        doc["render"] = {**doc["render"], "camera": cam}
        touched.append("render")
    doc.update(normalize(doc))
    angle = str(spec.get("camera", "front-3/4")).lower()
    if angle == "hero":
        doc["objects"][cam]["camera"]["lens"] = 85.0
    touched += _op_frame(doc, {"camera": cam, "angle": angle, "margin": 1.08}, where, selection)
    return touched


OPS = {"add": _op_add, "set": _op_set, "delete": _op_delete, "duplicate": _op_duplicate,
       "material": _op_material, "modifier": _op_modifier, "world": _op_section("world"),
       "render": _op_section("render"), "look_at": _op_look_at, "frame": _op_frame, "preset": _op_preset,
       "texture": _op_texture}


def apply_ops(doc, ops, selection=None):
    """Apply edit ops atomically. Returns (new_doc, touched entry keys); on any
    error the input document is untouched and SceneError names the op + field."""
    if not isinstance(ops, list) or not ops:
        raise SceneError("ops: a non-empty list")
    if len(ops) > 200:
        raise SceneError("ops: at most 200 per call")
    work = normalize(copy.deepcopy(doc))
    touched = []
    for i, op in enumerate(ops):
        where = f"ops[{i}]"
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise SceneError(f"{where}.op: one of {', '.join(OPS)}")
        try:
            touched += OPS[op["op"]](work, op, where, selection)
        except SceneError as e:
            msg = str(e)
            raise SceneError(msg if msg.startswith(where) else f"{where} ({op['op']}): {msg}") from None
    gone = {f"textures.{t}" for t in prune_textures(work)}
    return work, [k for k in dict.fromkeys(touched) if k not in gone]


def layout_check(doc, tol=0.02):
    """Mechanical QA for the model's own look: things floating above whatever is
    under them, sunk through the floor, or a studio floor that isn't at z = 0."""
    issues = []
    subjects = [k for k in subject_ids(doc) if doc["objects"][k]["parent"] is None]
    bounds = {k: world_bounds(doc, k) for k in subjects}
    for k in subjects:
        (x0, y0, z0), (x1, y1, z1) = bounds[k]
        if z0 < -tol:
            issues.append(f"{k} dips {-z0:.2f} below the floor (z = 0) — raise it or use on_floor")
            continue
        if z0 <= tol:
            continue
        # resting on (or sunk into) something whose footprint it overlaps
        support = [o for o in subjects if o != k and bounds[o][0][2] - tol <= z0 <= bounds[o][1][2] + tol
                   and bounds[o][0][0] < x1 and bounds[o][1][0] > x0 and bounds[o][0][1] < y1 and bounds[o][1][1] > y0]
        if not support:
            issues.append(f"{k} floats {z0:.2f} above the floor with nothing under it — on_floor, or rest it on something")
    bd = doc["objects"].get("studio_backdrop")
    if bd and abs(world_bounds(doc, "studio_backdrop")[0][2]) > tol:
        issues.append(f"the studio floor is at z = {world_bounds(doc, 'studio_backdrop')[0][2]:.2f}, not 0 — "
                      "re-run the preset")
    cut = out_of_frame(doc)
    if cut:
        issues.append(f"{', '.join(cut[:4])} {'is' if len(cut) == 1 else 'are'} partly outside the camera's frame — "
                      "`frame` the camera (or move it back)")
    return issues


def out_of_frame(doc, slack=0.02):
    """Subjects with any bounding-box corner outside the render camera's view."""
    cam = doc["render"]["camera"]
    if not cam or doc["objects"][cam]["camera"]["projection"] != "persp":
        return []
    c = doc["objects"][cam]["camera"]
    w, h = doc["render"]["resolution"]
    t = c["sensor_width"] / 2 / c["lens"]                       # AUTO fit: the sensor spans the longer side
    tan_h, tan_v = (t, t * h / w) if w >= h else (t * w / h, t)
    inv = invert(world_matrix(doc, cam))
    cut = []
    for k in subject_ids(doc):
        (x0, y0, z0), (x1, y1, z1) = world_bounds(doc, k)
        for p in [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]:
            q = [sum(inv[i][j] * p[j] for j in range(3)) + inv[i][3] for i in range(3)]
            depth = -q[2]
            if depth <= 1e-6 or abs(q[0]) / depth > tan_h * (1 + slack) or abs(q[1]) / depth > tan_v * (1 + slack):
                cut.append(k)
                break
    return cut


def prune_meshes(doc):
    """Drop mesh entries no object uses (a replaced primitive, a joined object's)."""
    used = {o.get("mesh") for o in doc["objects"].values()}
    for mid in [m for m in doc["meshes"] if m not in used]:
        del doc["meshes"][mid]
    return doc


def prune_textures(doc):
    """Drop texture entries no material uses; returns their ids."""
    used = {m[f] for m in doc["materials"].values() for f in TEXTURE_FIELDS if m.get(f)}
    gone = [t for t in doc.get("textures", {}) if t not in used]
    for t in gone:
        del doc["textures"][t]
    return gone


def merge_fragment(doc, frag):
    """Add another scene's objects/meshes/materials (an import) to `doc`,
    renaming ids that collide and rewriting every reference to match."""
    doc, frag = copy.deepcopy(doc), normalize(frag)
    renames = {}
    for sec in ("textures", "meshes", "materials", "objects"):
        renames[sec] = {}
        taken = set(doc[sec]) | set(frag[sec])
        for k in frag[sec]:
            if k not in doc[sec]:
                renames[sec][k] = k
                continue
            n = 2
            while f"{k}_{n}" in taken:
                n += 1
            renames[sec][k] = f"{k}_{n}"
            taken.add(f"{k}_{n}")
    for k, o in frag["objects"].items():
        o = copy.deepcopy(o)
        if o.get("parent"):
            o["parent"] = renames["objects"][o["parent"]]
        if o.get("mesh"):
            o["mesh"] = renames["meshes"][o["mesh"]]
        o["materials"] = [renames["materials"][m] if m else None for m in o.get("materials", [])]
        if o.get("dof_focus"):
            o["dof_focus"] = renames["objects"].get(o["dof_focus"])
        for mod in o.get("modifiers", []):
            for ref in ("object", "mirror_object"):
                if mod.get(ref):
                    mod[ref] = renames["objects"][mod[ref]]
        doc["objects"][renames["objects"][k]] = o
    for sec in ("textures", "meshes", "materials"):
        for k, v in frag[sec].items():
            v = copy.deepcopy(v)
            if sec == "materials":
                for f in TEXTURE_FIELDS:
                    if v.get(f):
                        v[f] = renames["textures"][v[f]]
            doc[sec][renames[sec][k]] = v
    return normalize(doc), [renames["objects"][k] for k in frag["objects"]]


# ─────────────────────────────── diff / patch / merge ─────────────────────────

def _entries(doc):
    out = {}
    for sec in SECTIONS:
        for k, v in doc.get(sec, {}).items():
            out[f"{sec}.{k}"] = v
    for sec in ("world", "render"):
        if sec in doc:
            out[sec] = doc[sec]
    return out


def diff(a, b):
    """Entry-level difference a → b: {"set": {key: entry}, "delete": [key]}."""
    ea, eb = _entries(a), _entries(b)
    return {"set": {k: copy.deepcopy(v) for k, v in eb.items() if ea.get(k) != v},
            "delete": sorted(k for k in ea if k not in eb)}


def patch(doc, p):
    out = copy.deepcopy(doc)
    for key, val in (p.get("set") or {}).items():
        if "." in key:
            sec, k = key.split(".", 1)
            out.setdefault(sec, {})[k] = copy.deepcopy(val)
        else:
            out[key] = copy.deepcopy(val)
    for key in p.get("delete") or []:
        sec, _, k = key.partition(".")
        if k:
            out.get(sec, {}).pop(k, None)
    return out


def merge3(base, local, remote):
    """Per-entry three-way merge. An entry only one side changed takes that side;
    one both sides changed (differently) keeps local and is reported."""
    eb, el, er = _entries(base), _entries(local), _entries(remote)
    merged, conflicts = {}, []
    for key in dict.fromkeys([*eb, *el, *er]):
        b, l, r = eb.get(key), el.get(key), er.get(key)
        if l == r:
            val = l
        elif l == b:
            val = r
        elif r == b:
            val = l
        else:
            val = l
            conflicts.append(key)
        if val is not None:
            merged[key] = val
    out = {k: v for k, v in local.items() if k not in (*SECTIONS, "world", "render")}
    out["rev"] = max(local.get("rev", 0), remote.get("rev", 0))
    for sec in SECTIONS:
        out[sec] = {}
    for key, val in merged.items():
        if "." in key:
            sec, k = key.split(".", 1)
            out[sec][k] = copy.deepcopy(val)
        else:
            out[key] = copy.deepcopy(val)
    return out, conflicts


# ─────────────────────────────── summary ──────────────────────────────────────

def _fmt(v):
    return "[" + ", ".join(f"{x:g}" if abs(x) >= 1e-3 or x == 0 else "0" for x in (round(c, 3) for c in v)) + "]"


def summary(doc, selection=None):
    """A compact, model-readable table of the scene."""
    lines = [f"Scene rev {doc.get('rev', 0)} — {len(doc['objects'])} objects, Z up, metres, angles in degrees."]
    sel = set(selection or [])
    if sel:
        lines.append(f"Selected in the Studio: {', '.join(sorted(sel))} (refer to them as id \"selected\").")
    for oid, o in doc["objects"].items():
        bits = [f"- {oid} ({o['type']}"]
        if o["type"] == "mesh":
            m = doc["meshes"][o["mesh"]]
            bits[0] += f" {m.get('primitive', 'explicit')}"
        if o["type"] == "light":
            bits[0] += f" {o['light']['kind']} {o['light']['energy']:g}W"
        if o["type"] == "camera":
            bits[0] += f" {o['camera']['lens']:g}mm"
        if o["type"] == "text":
            bits[0] += f" \"{o['text']['body']}\""
        bits[0] += ")"
        if o["name"] != oid:
            bits.append(f"\"{o['name']}\"")
        bits.append(f"at {_fmt(o['location'])}")
        if o["type"] in ("mesh", "text"):
            (x0, y0, z0), (x1, y1, z1) = world_bounds(doc, oid)
            bits.append(f"size {_fmt([x1 - x0, y1 - y0, z1 - z0])}")
        if any(o["rotation"]):
            bits.append(f"rot {_fmt(o['rotation'])}")
        if o["scale"] != [1, 1, 1]:
            bits.append(f"scale {_fmt(o['scale'])}")
        if o["parent"]:
            bits.append(f"parent {o['parent']}")
        slots = o.get("materials") or []
        if len(slots) == 1:
            bits.append(f"material {slots[0]}")
        elif slots:
            bits.append("materials [" + ", ".join(m or "-" for m in slots) + "] (slot per face)")
        if o.get("modifiers"):
            bits.append("mods " + ",".join(m["type"] for m in o["modifiers"]))
        if not o["visible"]:
            bits.append("hidden")
        if oid in sel:
            bits.append("[selected]")
        lines.append(" ".join(bits))
    if doc["materials"]:
        lines.append("Materials: " + "; ".join(
            f"{k} {m['base_color']} metal {m['metallic']:g} rough {m['roughness']:g}"
            + (f" glass" if m["transmission"] > 0.5 else "") + (f" emit {m['emission']:g}" if m["emission"] else "")
            + "".join(f" {f[:-8].replace('_', ' ')} image {m[f]}" for f in TEXTURE_FIELDS if m.get(f))
            for k, m in doc["materials"].items()))
    if doc.get("textures"):
        lines.append("Textures: " + "; ".join(f"{k} {t['width']}x{t['height']}" + (" with alpha" if t["alpha"] else "")
                                              for k, t in doc["textures"].items()))
    w, r = doc["world"], doc["render"]
    lines.append(f"World: {w['kind']} {w['hdri'] if w['kind'] == 'hdri' else w['color']} strength {w['strength']:g}. "
                 f"Render: camera {r['camera']}, {r['resolution'][0]}x{r['resolution'][1]}, {r['samples']} samples.")
    return "\n".join(lines)


# ─────────────────────────────── schema ───────────────────────────────────────

def _spec_schema(specs):
    props = {}
    for k, (kind, default, *rng) in specs.items():
        if kind in ("f", "i"):
            props[k] = {"type": "number" if kind == "f" else "integer", "minimum": rng[0], "maximum": rng[1],
                        "default": default}
        elif kind == "b":
            props[k] = {"type": "boolean", "default": default}
        elif kind.startswith("s:"):
            props[k] = {"enum": kind[2:].split("|"), "default": default}
        elif kind == "c":
            props[k] = {"type": "string", "pattern": _HEX.pattern, "default": default}
        elif kind == "t":
            props[k] = {"type": "string", "maxLength": 200, "default": default}
        elif kind in ("v3", "b3"):
            props[k] = {"type": "array", "minItems": 3, "maxItems": 3, "default": default}
        elif kind == "id":
            props[k] = {"type": ["string", "null"], "default": default}
        elif kind == "tex":
            props[k] = {"type": ["string", "null"], "default": default, "x-ref": "textures"}
        elif kind == "v2":
            props[k] = {"type": "array", "minItems": 2, "maxItems": 2, "default": default}
        elif kind == "res":
            props[k] = {"type": "array", "minItems": 2, "maxItems": 2, "default": default}
        else:
            raise AssertionError(f"no schema for field kind {kind!r}")
    return {"type": "object", "properties": props, "additionalProperties": False}


def json_schema():
    """The parameter vocabulary as JSON Schema fragments — what the app's panels
    and the TypeScript side are generated/checked against."""
    return {"format": FORMAT, "version": VERSION,
            "primitives": {k: _spec_schema(v) for k, v in PRIMITIVES.items()},
            "modifiers": {k: _spec_schema(v) for k, v in MODIFIERS.items()},
            "lights": {k: _spec_schema(v) for k, v in LIGHTS.items()},
            "camera": _spec_schema(CAMERA), "text": _spec_schema(TEXT), "material": _spec_schema(MATERIAL),
            "world": _spec_schema(WORLD), "render": _spec_schema(RENDER),
            "material_presets": sorted(MATERIAL_PRESETS), "light_rigs": sorted(LIGHT_RIGS),
            "camera_angles": sorted(CAMERA_ANGLES), "ops": sorted(OPS)}

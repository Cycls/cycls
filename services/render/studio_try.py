# Exercise the Studio engine ops on the fixture scene.
#
#   cd services/render && PYTHONPATH=../.. python studio_try.py dev selftest evaluate snapshot …
#   … remote …        # the deployed cycls-render instead of the dev executor
#
# Needs the SDK checkout with cycls/_agent/studio on PYTHONPATH (the schema).
import json
import sys
import time
from pathlib import Path

from cycls._agent.studio import scene as S

HERE = Path(__file__).parent
OUT = HERE / "out" / "studio"


def fixture():
    doc, _ = S.apply_ops(S.new_scene(), [
        {"op": "add", "id": "ring", "primitive": "torus", "params": {"minor_radius": 0.3}, "rotation": [90, 0, 0],
         "material": "gold", "on_floor": True},
        {"op": "add", "id": "ped", "primitive": "cylinder", "params": {"radius": 1.2, "depth": 0.4},
         "material": {"name": "Marble", "base_color": "#f1efe9", "roughness": 0.2, "coat": 0.3}, "on_floor": True},
        {"op": "add", "id": "ico", "primitive": "ico_sphere", "location": [3, 0, 1], "material": "glass"},
        {"op": "add", "id": "monkey", "primitive": "monkey", "location": [-3, 0, 1], "rotation": [0, 0, 30],
         "material": "ceramic"},
        {"op": "add", "id": "cone", "primitive": "cone", "location": [0, 3, 1], "parent": "ped"},
        {"op": "add", "id": "cone_child", "primitive": "uv_sphere", "params": {"radius": 0.3},
         "location": [0, 0, 1.5], "rotation": [10, 20, 30], "scale": [1, 2, 1], "parent": "cone"},
        {"op": "add", "id": "grid", "primitive": "grid", "location": [0, -3, 0]},
        {"op": "add", "id": "plane", "primitive": "plane", "location": [5, 5, 0]},
        {"op": "add", "id": "circle", "primitive": "circle", "location": [-5, 5, 0]},
        {"op": "add", "id": "cube2", "primitive": "cube", "params": {"size": 1}, "location": [3, 3, 0.5],
         "material": "neon"},
        {"op": "add", "id": "logo", "type": "text", "text": {"body": "CYCLS", "extrude": 0.1},
         "location": [0, -2, 2], "rotation": [90, 0, 0], "material": "chrome"},
        {"op": "add", "id": "spot", "type": "light", "light": {"kind": "spot", "energy": 800, "spot_size": 40},
         "location": [4, -4, 6], "look_at": "ring"},
        {"op": "add", "id": "sun", "type": "light", "light": {"kind": "sun", "energy": 2, "angle": 1},
         "rotation": [40, 0, 30]},
        {"op": "add", "id": "area", "type": "light",
         "light": {"kind": "area", "energy": 300, "shape": "rectangle", "size": 2, "size_y": 1},
         "location": [-4, -4, 4], "look_at": "ring"},
        {"op": "add", "id": "pivot", "type": "empty", "location": [1, 1, 1]},
        {"op": "modifier", "object": "ring", "type": "bevel", "params": {"width": 0.01, "segments": 2}},
        {"op": "modifier", "object": "monkey", "type": "subsurf", "params": {"levels": 2, "render_levels": 2}},
        {"op": "modifier", "object": "cube2", "type": "array", "params": {"count": 3}},
        {"op": "modifier", "object": "cube2", "type": "mirror"},
        {"op": "modifier", "object": "grid", "type": "solidify", "params": {"thickness": 0.1}},
        {"op": "modifier", "object": "ped", "type": "boolean", "params": {"object": "cube2"}},
        {"op": "modifier", "object": "plane", "type": "wireframe"},
        {"op": "modifier", "object": "circle", "type": "triangulate"},
        {"op": "modifier", "object": "ico", "type": "decimate", "params": {"ratio": 0.8}},
        {"op": "modifier", "object": "monkey", "type": "weld"},
        {"op": "modifier", "object": "grid", "type": "remesh", "params": {"voxel_size": 0.2}},
        {"op": "set", "id": "camera", "camera": {"dof_fstop": 4.0}, "dof_focus": "ring"},
        {"op": "preset", "studio": {"lighting": "studio-3point"}},
    ])
    return doc


def product():
    """A tidy product shot for looking at renders: gold ring on a marble pedestal."""
    doc, _ = S.apply_ops(S.new_scene(), [
        {"op": "delete", "id": "cube"},
        {"op": "delete", "id": "light"},
        {"op": "add", "id": "ped", "primitive": "cylinder", "params": {"radius": 1.1, "depth": 0.6},
         "material": {"name": "Marble", "base_color": "#ece8e1", "roughness": 0.18, "coat": 0.4}, "on_floor": True},
        # standing on the pedestal top: 0.6 high + the upright torus's half-height (1 + 0.28)
        {"op": "add", "id": "ring", "primitive": "torus", "params": {"minor_radius": 0.28},
         "rotation": [90, 0, 20], "location": [0, 0, 1.88], "material": "gold"},
        {"op": "modifier", "object": "ring", "type": "subsurf", "params": {"levels": 1, "render_levels": 2}},
        {"op": "preset", "studio": {"lighting": "dramatic", "camera": "front-3/4"}},
    ])
    return doc


def checker_png(n=256, cells=8):
    """A UV test image with no library: an 8x8 checker, and each quadrant tinted so
    orientation shows — red top-left, green top-right, blue bottom-left, yellow
    bottom-right (as the image is viewed; UV v=1 is its top row)."""
    import struct
    import zlib
    tint = {(0, 0): (230, 60, 60), (0, 1): (60, 200, 80), (1, 0): (60, 90, 230), (1, 1): (240, 210, 40)}
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            base = tint[(y * 2 // n, x * 2 // n)]
            k = 1.0 if ((x * cells // n) + (y * cells // n)) % 2 else 0.45
            row += bytes(int(c * k) for c in base)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def textured():
    """Five primitives wearing the checker, framed — for UVs vs Cycles."""
    import hashlib
    png = checker_png()
    digest = hashlib.sha256(png).hexdigest()[:12]
    doc, _ = S.apply_ops(S.new_scene(), [
        {"op": "delete", "id": "cube"},
        {"op": "texture", "id": "checker", "data": f"textures/t-{digest}.json", "width": 256, "height": 256},
        {"op": "material", "id": "uvgrid", "base_color": "#ffffff", "roughness": 0.6, "base_color_texture": "checker"},
        {"op": "add", "id": "cube", "primitive": "cube", "location": [-3, 0, 0], "material": "uvgrid", "on_floor": True},
        {"op": "add", "id": "sphere", "primitive": "uv_sphere", "location": [-1.2, 0, 0], "material": "uvgrid",
         "on_floor": True},
        {"op": "add", "id": "cyl", "primitive": "cylinder", "location": [0.6, 0, 0], "material": "uvgrid",
         "on_floor": True},
        {"op": "add", "id": "torus", "primitive": "torus", "location": [2.6, 0, 0], "rotation": [60, 0, 0],
         "material": "uvgrid", "on_floor": True},
        {"op": "add", "id": "plane", "primitive": "plane", "location": [0, 2, 1], "rotation": [90, 0, 0],
         "material": "uvgrid"},
        {"op": "world", "kind": "color", "color": "#ffffff", "strength": 1.0},
        {"op": "frame", "camera": "camera", "angle": "front", "margin": 1.1},
    ])
    return doc, {f"textures/t-{digest}.png": png}


def engine(where):
    if where == "dev":
        from cycls._function.remote import _load_module
        fn = _load_module(str(HERE / "render_fn.py")).render
        return lambda **kw: fn.remote(**kw)
    import cycls
    return cycls.remote("cycls-render", timeout=900)


def main(where, steps):
    call = engine(where)
    OUT.mkdir(parents=True, exist_ok=True)
    fx = fixture()
    (OUT / "fixture.json").write_text(json.dumps(fx, indent=1))

    def run(tag, **kw):
        t = time.monotonic()
        r = call(**kw)
        wall = time.monotonic() - t
        meta = {k: r.get(k) for k in ("ok", "seconds", "spawned", "boot_s", "sandbox", "jobs", "error") if k in r}
        print(f"{tag:22} wall {wall:5.1f}s {json.dumps(meta)}")
        if not r.get("ok") and r.get("trace"):
            print(r["trace"][-1200:])
        return r

    for step in steps:
        if step == "ping":
            r = run("ping", op="ping")
            print("   ", r.get("result"))
        elif step == "selftest":
            r = run("selftest", op="selftest", scene=fx)
            res = r.get("result", {})
            print("    problems:", json.dumps(res.get("problems"), indent=1))
            print("    notes:", res.get("notes"))
            bounds = res.get("primitive_bounds", {})
            for mid, b in bounds.items():
                print(f"    {mid:16} blender {b['blender']} counts {b['counts']}  doc {S.local_bounds({**fx, 'objects': {'x': {'type': 'mesh', 'mesh': mid}}}, 'x') if False else ''}")
        elif step == "evaluate":
            r = run("evaluate", op="evaluate", scene=fx)
            res = r.get("result", {})
            print("    tris", res.get("tris"), {k: v["tris"] for k, v in res.get("meshes", {}).items()})
            print("    files", sum(len(v) for v in r.get("files", {}).values()), "bytes")
        elif step == "snapshot":
            r = run("snapshot", op="snapshot", scene=product())
            if r.get("ok"):
                (OUT / "snapshot.jpg").write_bytes(r["files"]["preview.jpg"])
                print("    ", r["result"])
        elif step == "render":
            r = run("render", op="render", scene=product())
            if r.get("ok"):
                (OUT / "render.png").write_bytes(r["files"]["render.png"])
                print("    ", {k: v for k, v in r["result"].items() if k != "png"})
        elif step == "fixture-render":
            r = run("fixture snapshot", op="snapshot", scene=fx, params={"samples": 16})
            if r.get("ok"):
                (OUT / "fixture.jpg").write_bytes(r["files"]["preview.jpg"])
        elif step == "apply":
            for name, params in [("convert", {"id": "ring"}), ("modifier_apply", {"id": "ring", "index": 0}),
                                 ("bevel", {"id": "cube2", "selection": {"edges": [[0, 1]]}, "width": 0.1}),
                                 ("subdivide", {"id": "cube2", "selection": "all", "cuts": 2}),
                                 ("inset", {"id": "cube2", "selection": {"faces": [0]}, "thickness": 0.1}),
                                 ("triangulate", {"id": "cube2"}), ("recalc_normals", {"id": "cube2"}),
                                 ("connect", {"id": "cube2", "verts": [0, 6]}),
                                 ("bisect", {"id": "cube2", "plane_co": [0, 0, 0.1], "plane_no": [0, 0.3, 1]}),
                                 ("bisect", {"id": "cube2", "selection": {"verts": list(range(8))},
                                             "plane_co": [0, 0, 0.1], "plane_no": [0, 0.3, 1]}),
                                 ("triangulate", {"id": "cube2", "selection": {"verts": [0, 1, 2, 3]}}),
                                 ("bisect", {"id": "cube2", "plane_co": [0, 0, 0], "plane_no": [1, 0, 0],
                                             "clear_outer": True, "fill": True}),
                                 ("merge_by_distance", {"id": "cube2", "distance": 0.001}),
                                 ("remesh", {"id": "monkey", "voxel_size": 0.1}),
                                 ("decimate", {"id": "monkey", "ratio": 0.3}),
                                 ("boolean", {"id": "ped", "object": "cube2", "operation": "union"}),
                                 ("join", {"id": "ico", "others": ["cube2"]}),
                                 ("convert", {"id": "logo"})]:
                r = run(f"apply {name}", op="apply", scene=fx, params={"op": name, **params})
                if r.get("ok"):
                    res = r["result"]
                    print(f"    → {res['mesh_id']} verts {res['verts']} faces {res['faces']} "
                          f"mods_left {None if res['modifiers'] is None else len(res['modifiers'])} removed {res['removed']} selection {res.get('selection')}")
        elif step == "export":
            for fmt in ("glb", "blend", "fbx", "obj", "stl"):
                r = run(f"export {fmt}", op="export", scene=fx, params={"format": fmt})
                if r.get("ok"):
                    name = r["result"]["file"]
                    (OUT / name).write_bytes(r["files"][name])
                    print(f"    {name} {len(r['files'][name]):,} bytes")
        elif step == "script":
            code = ("for i in range(5):\n"
                    "    bpy.ops.mesh.primitive_cube_add(size=0.4, location=(i - 2, -4, 0.2))\n"
                    "bpy.data.objects['Ring'].location.z += 1\n"
                    "print('made', len(bpy.data.objects))\n")
            r = run("script", op="script", scene=fx, params={"code": code})
            if r.get("ok"):
                res = r["result"]
                sc = res["scene"]
                print("    objects", len(sc["objects"]), "new:", [k for k in sc["objects"] if k not in fx["objects"]])
                print("    ring z", fx["objects"]["ring"]["location"][2], "→", sc["objects"]["ring"]["location"][2])
                print("    stdout", res["stdout"].strip()[-200:], "| notes", res["notes"][:5])
                print("    mesh files", [k for k in r["files"] if k.startswith("meshes_out/")][:8])
        elif step == "import":
            glb = OUT / "export.glb"
            if not glb.exists():
                print("    run export first")
                continue
            r = run("import glb", op="import", scene={}, blobs={"import.glb": glb.read_bytes()},
                    params={"ext": "glb"})
            if r.get("ok"):
                sc = r["result"]["scene"]
                print("    objects", len(sc["objects"]), "meshes", len(sc["meshes"]), "materials", len(sc["materials"]))
                print("    notes", r["result"]["notes"][:6])
        elif step == "security":
            code = ("import socket, os, subprocess\n"
                    "res = {}\n"
                    "for host, port in (('1.1.1.1', 53), ('169.254.169.254', 80)):\n"
                    "    try:\n"
                    "        socket.create_connection((host, port), timeout=2); res[host] = 'OPEN'\n"
                    "    except OSError as e: res[host] = 'blocked'\n"
                    "try: open('/etc/x', 'w').write('x'); res['etc'] = 'WRITABLE'\n"
                    "except OSError: res['etc'] = 'blocked'\n"
                    "res['app'] = os.listdir('/app')\n"
                    "res['uid'] = os.getuid()\n"
                    "res['procs'] = len([p for p in os.listdir('/proc') if p.isdigit()])\n"
                    "res['jobs_visible'] = os.listdir('/tmp/cycls-studio/jobs')\n"
                    "res['own_dir'] = sorted(os.listdir(os.getcwd()))[:5]\n"
                    "import sys; sys.modules['builtins'].CYCLS_PLANTED = 'evil'\n"
                    "print(res)\n")
            r = run("security script", op="script", scene=fx, params={"code": code})
            print("    ", r.get("result", {}).get("stdout", r.get("error")))
            r = run("after script", op="ping")
            print("     next job spawned fresh worker:", r.get("spawned"), r.get("result"))
        elif step == "textures":
            doc, blobs = textured()
            (OUT / "textured.json").write_text(json.dumps(doc, indent=1))
            (OUT / "checker.png").write_bytes(blobs[next(iter(blobs))])
            r = run("evaluate uv", op="evaluate", scene=doc)
            if r.get("ok"):
                ms = r["result"]["meshes"]
                print("    uv per object:", {k: ("uv" in v) for k, v in ms.items()})
            r = run("snapshot textured", op="snapshot", scene=doc, blobs=blobs, params={"samples": 16})
            if r.get("ok"):
                (OUT / "textured.jpg").write_bytes(r["files"]["preview.jpg"])
                print("    ", r["result"], "→ out/studio/textured.jpg")
            r = run("script keeps images", op="script", scene=doc, blobs=blobs, params={"code": "pass"})
            if r.get("ok"):
                sc = r["result"]["scene"]
                print("    textures", sc["textures"], "| material", {k: sc["materials"]["uvgrid"][k]
                      for k in ("base_color_texture", "texture_scale", "base_color")})
                print("    notes", r["result"]["notes"], "| files", [k for k in r["files"] if k.startswith("textures_out/")])
            r = run("apply uv cylinder", op="apply", scene=doc, params={"op": "uv", "id": "cube", "method": "cylinder"})
            if r.get("ok"):
                print("    ", {k: r["result"][k] for k in ("mesh_id", "verts", "faces")})
            r = run("texture op", op="texture", scene={}, blobs={"texture_in.png": blobs[next(iter(blobs))]},
                    params={"ext": "png"})
            if r.get("ok"):
                print("    ", r["result"], len(r["files"][r["result"]["file"]]), "bytes")
        elif step == "slots":
            doc, _ = S.apply_ops(S.new_scene(), [
                {"op": "material", "id": "red", "base_color": "#e03030", "assign": "cube"},
                {"op": "material", "id": "blue", "base_color": "#3050e0", "assign": "cube", "slot": 1},
                {"op": "add", "id": "other", "primitive": "uv_sphere", "location": [2.5, 0, 1],
                 "material": {"name": "green", "base_color": "#30c040"}},
                {"op": "world", "kind": "color", "color": "#ffffff", "strength": 0.8}])
            r = run("apply assign top", op="apply", scene=doc,
                    params={"op": "assign", "id": "cube", "slot": 1, "selection": {"faces": [5]}})
            if r.get("ok"):
                res = r["result"]
                mid = res["mesh_id"]
                doc["meshes"][mid] = {"data": f"meshes/{mid}.json", "verts": res["verts"], "faces": res["faces"],
                                      "bbox": res["bbox"]}
                doc["objects"]["cube"]["mesh"] = mid
                side = r["files"]["mesh.json"]
                print("    material_index in file:", "material_index" in json.loads(side))
                blobs = {f"meshes/{mid}.json": side}
                r = run("evaluate slots", op="evaluate", scene=doc, blobs=blobs, params={"ids": ["cube"]})
                if r.get("ok"):
                    import array
                    m = r["result"]["meshes"]["cube"]
                    mi = array.array("H")
                    mi.frombytes(r["files"][m["material_index"]] if m.get("material_index") else b"")
                    print("    tri material index:", mi.tolist() or None)
                r = run("snapshot slots", op="snapshot", scene=doc, blobs=blobs, params={"samples": 12})
                if r.get("ok"):
                    (OUT / "slots.jpg").write_bytes(r["files"]["preview.jpg"])
                r = run("script keeps slots", op="script", scene=doc, blobs=blobs, params={"code": "pass"})
                if r.get("ok"):
                    print("    slots back:", r["result"]["scene"]["objects"]["cube"]["materials"], r["result"]["notes"])
                r = run("join slots", op="apply", scene=doc, blobs=blobs,
                        params={"op": "join", "id": "cube", "others": ["other"]})
                if r.get("ok"):
                    print("    after join:", r["result"].get("materials"), "removed", r["result"]["removed"])
        elif step == "anim":
            # keys → F-curves → keys, on the fixture; and Blender's samples of the evaluator's cases
            sdk = Path(S.__file__).resolve().parents[3]
            twin = json.loads((sdk / "studio/tests/fixtures/anim_twin.json").read_text())
            cases = {k: {"keys": v["keys"], "frames": [f for f, _ in v["samples"]]} for k, v in twin.items()}
            doc, _ = S.apply_ops(fx, [
                {"op": "animation", "fps": 30, "frame_start": 1, "frame_end": 90},
                {"op": "keyframe", "id": "ico", "frame": 1},
                {"op": "keyframe", "id": "ico", "frame": 45, "location": [3, 2, 2.5], "rotation": [0, 0, 180],
                 "interpolation": "linear"},
                {"op": "keyframe", "id": "ico", "frame": 90, "location": [3, -1, 1], "scale": [2, 1, 1]},
                {"op": "keyframe", "id": "spot", "frame": 30, "location": [5, -4, 6], "interpolation": "constant"},
                {"op": "turntable", "target": "monkey", "turns": 2},
            ])
            r = run("anim selftest", op="selftest", scene=doc, params={"anim": cases})
            res = r.get("result", {})
            print("    problems:", json.dumps(res.get("problems"), indent=1))
            print("    notes:", res.get("notes"))
            g = res.get("anim") or {}
            print("    depsgraph drift", g.get("depsgraph_drift"))
            worst = {}
            for name, c in (g.get("cases") or {}).items():
                for ch in ("location", "rotation"):
                    for f, v in c[ch]:
                        mine = S.sample(c["keys"], f)
                        worst[name] = max(worst.get(name, 0), *(abs(a - b) for a, b in zip(mine, v)))
            print("    scene.py vs Blender, worst per case:", {k: f"{v:.2e}" for k, v in worst.items()})
            if g.get("cases"):
                (sdk / "studio/tests/fixtures/anim_golden.json").write_text(json.dumps(g["cases"]))
                print("    wrote studio/tests/fixtures/anim_golden.json")
        elif step == "video":
            doc, _ = S.apply_ops(product(), [{"op": "turntable", "target": "ring", "seconds": 1, "fps": 12},
                                             {"op": "render", "resolution": [320, 180], "samples": 4}])
            segs = []
            for i, fr in enumerate(([1, 6], [7, 12])):
                r = run(f"video {fr}", op="video", scene=doc, params={"frames": fr, "poster": i == 0, "check": True})
                if r.get("ok"):
                    print("    ", r["result"])
                    segs.append(r["files"]["segment.mp4"])
                    if "poster.jpg" in r["files"]:
                        (OUT / "poster.jpg").write_bytes(r["files"]["poster.jpg"])
            if len(segs) == 2:
                r = run("encode", op="encode", scene={}, blobs={f"segments/s-{i:03d}.mp4": b for i, b in enumerate(segs)},
                        params={"segments": 2, "fps": 12, "resolution": [320, 180]})
                if r.get("ok"):
                    (OUT / "video.mp4").write_bytes(r["files"]["video.mp4"])
                    print("    ", r["result"], len(r["files"]["video.mp4"]), "bytes → out/studio/video.mp4")
        elif step == "anim-io":
            doc, _ = S.apply_ops(product(), [
                {"op": "turntable", "target": "ring", "seconds": 2, "fps": 24},
                {"op": "keyframe", "id": "ped", "frame": 1},
                {"op": "keyframe", "id": "ped", "frame": 30, "location": [0, 0, 0.8], "scale": [1.2, 1.2, 1]}])
            for fmt in ("blend", "glb", "fbx"):
                r = run(f"export {fmt}", op="export", scene=doc, params={"format": fmt})
                if not r.get("ok"):
                    continue
                data = r["files"][r["result"]["file"]]
                r = run(f"import {fmt}", op="import", scene={}, blobs={f"import.{fmt}": data}, params={"ext": fmt})
                if r.get("ok"):
                    sc = r["result"]["scene"]
                    print("    animation", sc["animation"])
                    for k, o in sc["objects"].items():
                        if o.get("keys"):
                            print(f"    {k:14} parent={o['parent']}", {ch: (len(ks), ks[0], ks[-1]) for ch, ks in o["keys"].items()})
                    print("    notes", [n for n in r["result"]["notes"] if "key" in n or "motion" in n or "anim" in n][:6])
        elif step == "legacy":
            r = call(config={"object": "torus", "material": "gold", "resolution": [640, 360], "samples": 16})
            print(f"legacy render ok={r.get('ok')} render_seconds={r.get('render_seconds')} png={len(r.get('png') or b'')}")
        else:
            print("unknown step", step)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])

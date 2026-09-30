"""The warm Blender worker (spike S2). Runs INSIDE Blender:

    blender -b --factory-startup -Y -P worker.py -- --resp-fd N

Protocol: the parent writes `run <jobdir>` lines on stdin; each job dir holds
in.json; the worker writes out.json (+ .bin buffers) there and answers
`done ok|err` on the response fd. Blender's own chatter stays on stdout/stderr,
out of the protocol. Only JSON and raw bytes ever leave: the parent never
unpickles anything that came from here.
"""
import json
import os
import sys
import time
import traceback

import bpy
import numpy as np

STARTED = time.time()
JOBS = 0
LEAK = {}          # cross-job state probe: what a job can see of the last one


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:]
    return int(argv[argv.index("--resp-fd") + 1])


def _rss_kb():
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return -1


def _reset(method):
    t = time.perf_counter()
    if method == "factory":
        bpy.ops.wm.read_factory_settings(use_empty=True)
    else:
        for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                     bpy.data.cameras, bpy.data.curves, bpy.data.images):
            if len(coll):
                bpy.data.batch_remove(list(coll))
    return round((time.perf_counter() - t) * 1000, 2)


def op_ping(job, jobdir):
    import socket
    net = "blocked"
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=1).close()
        net = "OPEN"
    except OSError as e:
        net = f"blocked ({e.__class__.__name__})"
    etc = "blocked"
    try:
        open("/etc/cycls-probe", "w").write("x")
        etc = "WRITABLE"
    except OSError as e:
        etc = f"blocked ({e.__class__.__name__})"
    parent_visible = os.path.exists(f"/proc/{os.getppid()}/cmdline")
    return {"pid": os.getpid(), "ppid": os.getppid(), "uid": os.getuid(), "euid": os.geteuid(),
            "uptime_s": round(time.time() - STARTED, 2), "jobs": JOBS, "rss_kb": _rss_kb(),
            "blender": bpy.app.version_string, "net": net, "etc_write": etc,
            "pids_visible": len([p for p in os.listdir("/proc") if p.isdigit()]),
            "parent_proc_visible": parent_visible,
            "home": os.environ.get("HOME"), "env_keys": sorted(os.environ)[:20],
            "leak_seen": dict(LEAK)}


def op_evaluate(job, jobdir):
    """Cube + subsurf, evaluated through the depsgraph, triangles out as raw
    float32/uint32 buffers — the shape of the viewport's modifier preview."""
    import bmesh
    p = job.get("params") or {}
    timings = {"reset_ms": _reset(p.get("reset", "batch"))}
    t = time.perf_counter()
    me = bpy.data.meshes.new("m")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("o", me)
    bpy.context.scene.collection.objects.link(ob)
    mod = ob.modifiers.new("s", "SUBSURF")
    mod.levels = mod.render_levels = int(p.get("levels", 5))
    timings["build_ms"] = round((time.perf_counter() - t) * 1000, 2)

    t = time.perf_counter()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    m = ev.to_mesh()
    m.calc_loop_triangles()
    timings["eval_ms"] = round((time.perf_counter() - t) * 1000, 2)

    t = time.perf_counter()
    co = np.empty(len(m.vertices) * 3, dtype=np.float32)
    m.vertices.foreach_get("co", co)
    tri = np.empty(len(m.loop_triangles) * 3, dtype=np.uint32)
    m.loop_triangles.foreach_get("vertices", tri)
    co.tofile(os.path.join(jobdir, "positions.bin"))
    tri.tofile(os.path.join(jobdir, "index.bin"))
    ev.to_mesh_clear()
    timings["extract_ms"] = round((time.perf_counter() - t) * 1000, 2)
    return {"verts": len(co) // 3, "tris": len(tri) // 3, **timings}


def op_leak(job, jobdir):
    LEAK[str(JOBS)] = (job.get("params") or {}).get("secret", "")
    return {"stored": True}


def op_fidelity(job, jobdir):
    """Spike S3: the facts the scene document leans on."""
    import math

    import bmesh
    from mathutils import Euler, Matrix
    _reset("batch")
    res = {}

    # 1. Euler: Blender 'XYZ' rotation matrix, for three.js to compare against.
    e = Euler([math.radians(a) for a in (30, 45, 60)], "XYZ")
    res["euler_xyz_30_45_60"] = [list(map(lambda v: round(v, 7), row)) for row in e.to_matrix()]

    # 2. Parent chain round trip: doc (local loc/rot°/scale) → bpy → doc.
    doc = {"a": {"parent": None, "location": [1, 2, 3], "rotation": [10, 20, 30], "scale": [1, 2, 1]},
           "b": {"parent": "a", "location": [0.5, -1, 2], "rotation": [-45, 5, 90], "scale": [0.5, 0.5, 0.5]},
           "c": {"parent": "b", "location": [3, 0, 0], "rotation": [0, 90, 0], "scale": [1, 1, 3]}}
    objs = {}
    for oid, o in doc.items():
        ob = bpy.data.objects.new(oid, None)
        bpy.context.scene.collection.objects.link(ob)
        ob["cycls_id"] = oid
        objs[oid] = ob
    for oid, o in doc.items():
        ob = objs[oid]
        if o["parent"]:
            ob.parent = objs[o["parent"]]
            ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.location = o["location"]
        ob.rotation_mode = "XYZ"
        ob.rotation_euler = [math.radians(a) for a in o["rotation"]]
        ob.scale = o["scale"]
    bpy.context.view_layer.update()
    worst = 0.0
    back = {}
    for oid, ob in objs.items():
        local = (ob.parent.matrix_world.inverted() @ ob.matrix_world) if ob.parent else ob.matrix_world.copy()
        loc, rot, scl = local.decompose()
        eul = rot.to_euler("XYZ")
        got = {"location": list(loc), "rotation": [math.degrees(a) for a in eul], "scale": list(scl)}
        back[oid] = {k: [round(v, 6) for v in vals] for k, vals in got.items()}
        for k in ("location", "scale"):
            worst = max(worst, max(abs(a - b) for a, b in zip(got[k], doc[oid][k])))
        # compare rotations as matrices (euler triples are not unique)
        want = Euler([math.radians(a) for a in doc[oid]["rotation"]], "XYZ").to_matrix()
        have = eul.to_matrix()
        worst = max(worst, max(abs(want[i][j] - have[i][j]) for i in range(3) for j in range(3)))
    res["transform_roundtrip_max_err"] = worst
    res["transform_back"] = back

    # 3. Explicit n-gon mesh via foreach_set (loop_start; loop_total derived).
    co = [0, 0, 0, 2, 0, 0, 2, 1, 0, 1, 2, 0, 0, 1, 0,  0, 0, 1]   # a pentagon + one loose-ish vertex
    loops = [0, 1, 2, 3, 4,  0, 4, 5]                              # pentagon, then a triangle
    loop_start = [0, 5]
    me = bpy.data.meshes.new("ngon")
    me.vertices.add(len(co) // 3)
    me.loops.add(len(loops))
    me.polygons.add(len(loop_start))
    me.vertices.foreach_set("co", co)
    me.loops.foreach_set("vertex_index", loops)
    try:
        me.polygons.foreach_set("loop_start", loop_start)
        res["foreach_loop_start"] = "ok"
    except Exception as ex:
        res["foreach_loop_start"] = f"FAILED {ex}"
    me.update(calc_edges=True)
    invalid = me.validate(verbose=False)
    res["ngon_mesh"] = {"verts": len(me.vertices), "edges": len(me.edges), "faces": len(me.polygons),
                        "sizes": [p.loop_total for p in me.polygons], "validate_changed": bool(invalid)}

    # 4. Primitive topology (bmesh.ops.create_*), for the app to match counts.
    def counts(build):
        bm = bmesh.new()
        build(bm)
        c = (len(bm.verts), len(bm.edges), len(bm.faces))
        bm.free()
        return c
    res["primitives"] = {
        "cube": counts(lambda bm: bmesh.ops.create_cube(bm, size=2)),
        "uv_sphere_32x16": counts(lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=1)),
        "ico_sphere_2": counts(lambda bm: bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1)),
        "cylinder_32": counts(lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=1, radius2=1, depth=2)),
        "cone_32": counts(lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=1, radius2=0, depth=2)),
        "grid_10": counts(lambda bm: bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=1)),
        "circle_32": counts(lambda bm: bmesh.ops.create_circle(bm, cap_ends=False, segments=32, radius=1)),
        "monkey": counts(lambda bm: bmesh.ops.create_monkey(bm)),
    }
    return res


def op_sleep(job, jobdir):
    time.sleep(float((job.get("params") or {}).get("seconds", 30)))
    return {"slept": True}


OPS = {"ping": op_ping, "evaluate": op_evaluate, "leak": op_leak, "fidelity": op_fidelity,
       "sleep": op_sleep}


def main():
    global JOBS
    resp = os.fdopen(_args(), "w", buffering=1)
    resp.write(f"ready {os.getpid()}\n")
    for line in sys.stdin:
        cmd, _, jobdir = line.strip().partition(" ")
        if cmd == "quit":
            break
        t = time.perf_counter()
        try:
            with open(os.path.join(jobdir, "in.json")) as f:
                job = json.load(f)
            out, status = OPS[job["op"]](job, jobdir), "ok"
        except Exception:
            out, status = {"error": traceback.format_exc()[-2000:]}, "err"
        JOBS += 1
        out["worker_ms"] = round((time.perf_counter() - t) * 1000, 2)
        with open(os.path.join(jobdir, "out.json"), "w") as f:
            json.dump(out, f)
        resp.write(f"done {status}\n")


main()

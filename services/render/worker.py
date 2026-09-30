"""The warm Studio worker. Runs INSIDE Blender, sandboxed:

    unshare --net -- bwrap … -- blender -b --factory-startup -Y -P worker.py -- --resp-fd N

Protocol: the parent writes `run <jobdir>` lines on stdin; each job dir holds
in.json {op, scene, params} (+ meshes/*.json, import.<ext>); the worker writes
out.json and any output files there and answers `done ok|err` on the response
fd. Blender's own chatter stays on stdout/stderr, out of the protocol. Only
JSON and raw files ever leave: the parent never unpickles anything from here.
"""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import studio_bpy  # noqa: E402  (next to this file, with studio_scene.py)

STARTED = time.time()


def _resp_fd():
    argv = sys.argv[sys.argv.index("--") + 1:]
    return int(argv[argv.index("--resp-fd") + 1])


def _ping(job, jobdir):
    rss = -1
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
    except OSError:
        pass
    import bpy
    return {"pid": os.getpid(), "uid": os.getuid(), "uptime_s": round(time.time() - STARTED, 2),
            "rss_kb": rss, "blender": bpy.app.version_string}


def main():
    resp = os.fdopen(_resp_fd(), "w", buffering=1)
    resp.write(f"ready {os.getpid()}\n")
    ops = {**studio_bpy.OPS, "ping": _ping}
    for line in sys.stdin:
        cmd, _, jobdir = line.strip().partition(" ")
        if cmd == "quit":
            break
        t = time.perf_counter()
        try:
            with open(os.path.join(jobdir, "in.json")) as f:
                job = json.load(f)
            out, status = ops[job["op"]](job, jobdir), "ok"
        except Exception as e:
            out, status = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}, "err"
        out["worker_ms"] = round((time.perf_counter() - t) * 1000, 2)
        with open(os.path.join(jobdir, "out.json"), "w") as f:
            json.dump(out, f)
        resp.write(f"done {status}\n")


main()

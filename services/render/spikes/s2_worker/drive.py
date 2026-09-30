# Drive spike S2 on the cloud executor (current code, no deploy):
#   cd services/render && CYCLS_API_KEY=... python spikes/s2_worker/drive.py [phase]
import json
import statistics
import sys
import time
from pathlib import Path

from cycls._function.remote import _load_module

fn = _load_module(str(Path(__file__).parent / "spike_fn.py")).studio_spike


def call(op, params=None, sandbox="unshare", timeout=120):
    t = time.monotonic()
    r = fn.remote(op, params, sandbox, timeout)
    r["wall_ms"] = round((time.monotonic() - t) * 1000)
    return r


def show(tag, r):
    out = r.get("out", {})
    keep = {k: r.get(k) for k in ("instance", "spawned", "boot_s", "status", "roundtrip_ms", "wall_ms", "error")
            if r.get(k) is not None}
    print(f"{tag:14} {json.dumps(keep)}")
    if out:
        print(f"{'':14} out={json.dumps(out)[:600]}")


phase = sys.argv[1] if len(sys.argv) > 1 else "all"

if phase in ("env", "all"):
    r = fn.remote("env")
    print("ENV", json.dumps(r, indent=1))

if phase in ("sandbox", "all"):
    for mode in ("none", "unshare"):
        try:
            show(f"ping[{mode}]", call("ping", sandbox=mode))
        except Exception as e:
            print(f"ping[{mode}]      FAILED {str(e)[:800]}")

if phase in ("fidelity", "all"):
    r = call("fidelity")
    print("FIDELITY", json.dumps(r.get("out") or r, indent=1)[:4000])
    three_zyx = [[0.3535534, -0.5732233, 0.7391989], [0.6123724, 0.7391989, 0.2803301], [-0.7071068, 0.3535534, 0.6123724]]
    got = (r.get("out") or {}).get("euler_xyz_30_45_60")
    if got:
        err = max(abs(a - b) for ra, rb in zip(got, three_zyx) for a, b in zip(ra, rb))
        print(f"Blender XYZ vs three.js 'ZYX' max |Δ| = {err:.2e}")

if phase in ("latency", "all"):
    show("warm ping 1", call("ping"))
    show("warm ping 2", call("ping"))
    rts, walls, workers = [], [], []
    for i in range(10):
        r = call("evaluate", {"levels": 5, "reset": "batch"})
        rts.append(r.get("roundtrip_ms", 0)); walls.append(r["wall_ms"]); workers.append(r.get("out", {}).get("worker_ms"))
        if i == 0:
            show("evaluate[0]", r)
    print(f"evaluate x10   server roundtrip p50={statistics.median(rts)}ms max={max(rts)}  "
          f"worker p50={statistics.median(workers)}ms  wall p50={statistics.median(walls)}ms max={max(walls)}")
    show("reset=factory", call("evaluate", {"levels": 5, "reset": "factory"}))
    show("leak write", call("leak", {"secret": "user-A-scene"}))
    show("leak read", call("ping"))

if phase in ("recovery", "all"):
    show("kill", call("kill"))
    show("after kill", call("evaluate", {"levels": 5}))
    show("timeout", call("evaluate", {"levels": 9}, timeout=2))
    show("after timeout", call("ping"))

if phase in ("memory", "all"):
    t = time.monotonic()
    for i in range(200):
        fn.remote("evaluate", {"levels": 5}, "unshare", 120)
    show("after 200", call("ping"))
    print(f"200 evaluates in {time.monotonic() - t:.0f}s")

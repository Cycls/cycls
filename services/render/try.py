# Render named shots and save them to out/ — the dev loop and the benchmark.
#
#   python try.py local  torus-gold ico-red     # local Docker (builds the image once)
#   python try.py dev    torus-gold ico-red     # current code on the cloud executor, no redeploy
#   python try.py remote torus-gold             # the deployed cycls-render
#   python try.py remote bench                  # the timing table in README.md
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent

SHOTS = {
    "cube-64":    {"object": "cube", "resolution": [64, 64], "samples": 16, "glb": False},
    "torus-gold": {"object": "torus", "material": "gold", "backdrop": "#1b1b1f",
                   "lighting": "studio-3point"},
    "ico-red":    {"preset": "product-shot", "object": "ico-sphere",
                   "material": {"base_color": [0.8, 0.1, 0.1], "metallic": 0.9, "roughness": 0.2},
                   "lighting": "studio-3point", "camera": {"angle": "front-3/4", "focal_mm": 50},
                   "resolution": [1280, 720], "samples": 64, "engine": "CYCLES"},
    "glass-soft": {"object": "sphere", "material": "glass", "lighting": "softbox"},
    "text-chrome": {"object": "text", "text": "CYCLS", "material": "chrome",
                    "lighting": "dramatic", "camera": "front"},
    "monkey-ceramic": {"object": "monkey", "material": "ceramic", "lighting": "rim",
                       "camera": "hero"},
    "cube-neon":  {"object": "rounded-cube", "material": "neon", "lighting": "dramatic",
                   "camera": "top"},
}

BENCH = [(w, h, s, f"bench-{w}x{h}-{s}") for (w, h) in ((1280, 720), (1920, 1080))
         for s in (32, 64, 128)]


def _batch(where):
    """→ fn(list of configs) → list of (result, wall seconds)."""
    from concurrent.futures import ThreadPoolExecutor
    if where in ("local", "dev"):
        from cycls._function.remote import _load_module   # by value, not by reference
        fn = _load_module(str(HERE / "render_fn.py")).render
        if where == "dev":        # the CURRENT scenes.py on the cloud executor, 4 at a time
            return lambda cfgs: [(r, None) for r in fn.map(cfgs, workers=4)]
        one = fn.run
    else:
        import cycls
        one = cycls.remote("cycls-render", timeout=900)

    def timed(cfg):
        t0 = time.monotonic()
        return one(cfg), time.monotonic() - t0
    if where == "local":
        return lambda cfgs: [timed(c) for c in cfgs]
    return lambda cfgs: list(ThreadPoolExecutor(4).map(timed, cfgs))


def main(where, names):
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    if names == ["bench"]:
        shots = {n: {"object": "torus", "material": "gold", "resolution": [w, h], "samples": s,
                     "glb": False} for (w, h, s, n) in BENCH}
    else:
        shots = {n: SHOTS[n] for n in names}
    results = _batch(where)(list(shots.values()))
    for name, (r, wall) in zip(shots, results):
        wall = wall or 0.0
        if not r or not r.get("ok"):
            print(f"{name}: FAILED {r and r.get('error')}\n{(r or {}).get('log', '')}")
            continue
        (out / f"{name}.png").write_bytes(r["png"])
        if r.get("preview"):
            (out / f"{name}.jpg").write_bytes(r["preview"])
        if r.get("glb"):
            (out / f"{name}.glb").write_bytes(r["glb"])
        print(f"{name}: render {r['render_seconds']}s · call {r['seconds']}s · wall {wall:.1f}s · "
              f"threads {r['threads']} · blender {r['blender']} · png {len(r['png']) // 1024}KB"
              + (f" · glb {len(r['glb']) // 1024}KB" if r.get("glb") else ""))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])

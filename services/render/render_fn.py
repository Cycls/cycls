# Headless Blender as a Cycls function.
#
#   render(config)                          the product-shot path: a config in, a studio render out
#   render(op=…, scene=…, blobs=…, params=…) Studio: a warm, sandboxed Blender worker runs one op
#                                           on a scene document (see studio_bpy.py)
#
#   cd services/render && PYTHONPATH=../.. uv run cycls deploy render_fn.py   (the SDK: Studio's scene.py)
#   python -c 'import cycls; r = cycls.remote("cycls-render")({"object": "torus", "material": "gold"})'
#
# The box is deliberately stateless — no volume, no secrets. It returns bytes;
# the caller decides where they live. See README.md.
import importlib
import inspect
from pathlib import Path

import cycls

BLENDER = "5.2.2"                    # current LTS line; bump deliberately
_TARBALL = (f"https://download.blender.org/release/Blender{BLENDER.rsplit('.', 1)[0]}/"
            f"blender-{BLENDER}-linux-x64.tar.xz")
RENDER_TIMEOUT = 600                 # seconds of Blender per call; the deploy timeout sits above it

_HERE = Path(__file__).parent
# Captured by value when the function is pickled, so scene/engine changes ship
# with the next deploy without rebuilding the (1 GB) image.
SCENES_SRC = (_HERE / "scenes.py").read_text(encoding="utf-8")
WORKER_SRC = (_HERE / "worker.py").read_text(encoding="utf-8")
STUDIO_BPY_SRC = (_HERE / "studio_bpy.py").read_text(encoding="utf-8")


def _scene_source():
    """The SDK's scene schema — one source of truth for tool, route and engine."""
    try:
        return inspect.getsource(importlib.import_module("cycls._agent.studio.scene"))
    except Exception:
        return None


SCENE_SRC = _scene_source()

image = (
    cycls.Image()
    # X/GL client libs Blender links against even in background mode; bubblewrap +
    # util-linux (unshare) sandbox the Studio worker.
    .apt("curl", "ca-certificates", "xz-utils", "libgl1", "libegl1", "libglib2.0-0",
         "libx11-6", "libxi6", "libxrender1", "libxxf86vm1", "libxfixes3", "libxext6",
         "libxkbcommon0", "libsm6", "libice6", "bubblewrap", "util-linux")
    # Official build, not Debian's (bookworm ships 3.4). Self-verifying layer:
    # a missing library fails the build here, not the first render.
    .run(f"curl -fsSL {_TARBALL} | tar -xJ -C /opt "
         f"&& mv /opt/blender-{BLENDER}-linux-x64 /opt/blender "
         "&& ln -s /opt/blender/blender /usr/local/bin/blender "
         "&& blender --version")
)


def _legacy(config):
    """Render one studio shot (the original path, unchanged)."""
    import json
    import os
    import subprocess
    import tempfile
    import time

    ns = {"__name__": "scenes"}
    exec(compile(SCENES_SRC, "scenes.py", "exec"), ns)
    try:
        cfg = ns["normalize"](config or {})
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        script, cfg_path, out = (os.path.join(tmp, n) for n in ("scenes.py", "config.json", "out"))
        os.mkdir(out)
        with open(script, "w", encoding="utf-8") as f:
            f.write(SCENES_SRC)
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config or {}, f)          # raw: scenes.py normalizes it itself
        cmd = ["blender", "-b", "--factory-startup", "--python-exit-code", "3", "-t", "0",
               "-P", script, "--", "--config", cfg_path, "--out", out]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"render exceeded {RENDER_TIMEOUT}s — "
                                          "lower samples or resolution"}
        log = (p.stdout or "") + (p.stderr or "")
        png = os.path.join(out, "render.png")
        if p.returncode != 0 or not os.path.exists(png):
            return {"ok": False, "error": f"blender exited {p.returncode}", "log": log[-3000:]}

        def read(name):
            path = os.path.join(out, name)
            return open(path, "rb").read() if os.path.exists(path) else None

        meta = json.loads(read("meta.json") or b"{}")
        return {"ok": True, "png": read("render.png"), "preview": read("preview.jpg"),
                "glb": read("model.glb"), "config": cfg,
                "seconds": round(time.monotonic() - t0, 2),
                "render_seconds": meta.get("render_seconds"),
                "blender": meta.get("blender"), "threads": meta.get("threads"),
                "log": log[-1500:]}


# ─────────────────────────────── Studio worker ────────────────────────────────

ROOT = "/tmp/cycls-studio"
JOBS_ROOT = ROOT + "/jobs"
# Mesh and image files a caller has sent before, kept per workspace (the caller's 32-hex key):
# their names are their content's hash, so a scene resent after a lighting change needs none of
# them again. Outside the jobs tree — a sandboxed worker never sees it — and bounded: /tmp is
# memory here, so the least recently used go first past CACHE_MAX.
CACHE_ROOT = ROOT + "/cache"
CACHE_MAX = 1_200_000_000
_CACHEABLE = r"^(meshes/m-[0-9a-f]{12}\.json|textures/t-[0-9a-f]{12}\.(png|jpg))$"
OP_TIMEOUT = {"ping": 30, "evaluate": 60, "apply": 120, "snapshot": 120, "render": RENDER_TIMEOUT,
              "export": 180, "script": 120, "import": 300, "selftest": 120, "texture": 60,
              "video": RENDER_TIMEOUT, "encode": 180}
# Untrusted input — code, a model, an image, video segments from the workspace: a fresh worker each.
TAINTED = {"script", "import", "texture", "encode"}
RECYCLE_JOBS = 100          # a warm worker this old starts over: whatever Blender leaked goes with it
MAX_IN = 110_000_000        # the SDK sends at most 100 MB of meshes + images, plus the scene
MAX_OUT = 160_000_000       # an import's meshes come back as base64 sidecars, a third bigger
_BLOB_NAME = (r"^(meshes/m-[0-9a-f]{12}\.json|textures/t-[0-9a-f]{12}\.(png|jpg)"
              r"|import\.(glb|gltf|obj|fbx|stl|ply|blend)|texture_in\.(png|jpg|jpeg|webp|bmp|tif|tiff|tga|exr|hdr)"
              r"|segments/s-\d{3}\.mp4)"
              r"(\.gz)?$")                  # .gz: gzip'd by the caller (a slow uplink), unpacked here
PACK_MIN = 256_000


def _cache_put(home, name, data):
    import os
    path = os.path.join(home, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)
    os.replace(tmp, path)


def _cache_trim():
    """Past CACHE_MAX, drop the least recently used files until the cache is at 80% of it."""
    import os
    files = []
    for dirpath, _, names in os.walk(CACHE_ROOT):
        for n in names:
            p_ = os.path.join(dirpath, n)
            try:
                st_ = os.stat(p_)
            except OSError:
                continue
            files.append((st_.st_mtime, st_.st_size, p_))
    total = sum(f[1] for f in files)
    if total <= CACHE_MAX:
        return
    for _, size, p_ in sorted(files):
        try:
            os.unlink(p_)
        except OSError:
            continue
        total -= size
        if total <= CACHE_MAX * 0.8:
            break


def _unpack(blobs, cap):
    """name.gz → name, unpacked; the unpacked total stays under `cap` (a small gzip can
    claim to be huge)."""
    import gzip
    import io
    out, total = {}, 0
    for name, data in blobs.items():
        if name.endswith(".gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                data = g.read(cap - total + 1)
            name = name[:-3]
        total += len(data)
        if total > cap:
            raise ValueError(f"inputs unpack to over {cap:,} bytes")
        out[name] = data
    return out

# The SDK's sandbox defaults (cycls/_app/sandbox/main.py) plus pid/ipc/uts
# namespaces, a non-root uid inside, a fresh session and /app masked. Network
# isolation is per mode — bwrap's --unshare-net can't bring up loopback under
# gVisor (where plain functions run), so "unshare" wraps bwrap in an empty netns.
_BOX = ["bwrap", "--ro-bind", "/", "/", "--tmpfs", "/tmp", "--tmpfs", "/app", "--dev", "/dev",
        "--proc", "/proc", "--unshare-user", "--uid", "65534", "--gid", "65534",
        "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--new-session", "--die-with-parent", "--clearenv",
        "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin", "--setenv", "HOME", "/tmp",
        "--setenv", "LANG", "C.UTF-8"]


def _wrap(mode, inner):
    if mode == "unshare":
        return ["unshare", "--net", "--", *_BOX, *inner]
    if mode == "bwrap":
        return [*_BOX, "--unshare-net", *inner]
    return inner


def _sandbox_mode():
    """The strongest isolation this runtime allows, probed once per process."""
    import subprocess
    import sys
    mode = getattr(sys, "_cycls_sandbox", None)
    if mode is None:
        mode = "none"
        for m in ("unshare", "bwrap"):
            try:
                if subprocess.run(_wrap(m, ["--", "true"]), capture_output=True, timeout=20).returncode == 0:
                    mode = m
                    break
            except Exception:
                pass
        sys._cycls_sandbox = mode
    return mode


def _readline(st, timeout):
    import os
    import select
    import time
    end = time.monotonic() + timeout
    while b"\n" not in st["buf"]:
        left = end - time.monotonic()
        if left <= 0:
            return None
        ready, _, _ = select.select([st["r"]], [], [], left)
        if ready:
            chunk = os.read(st["r"], 4096)
            if not chunk:
                return None
            st["buf"] += chunk
    line, _, st["buf"] = st["buf"].partition(b"\n")
    return line.decode()


def _kill(st):
    import os
    import signal
    p = st.get("proc")
    if p is not None and p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            p.kill()
        try:
            p.wait(timeout=10)
        except Exception:
            pass
    if st.get("r") is not None:
        try:
            os.close(st["r"])
        except OSError:
            pass
    st.update(proc=None, r=None, buf=b"")


def _spawn(st, mode, key, bind=JOBS_ROOT):
    """A worker that can see `bind` (all job dirs for the warm worker; exactly
    one job dir for a tainted op) and its own read-only code, nothing else."""
    import os
    import subprocess
    import time
    os.makedirs(JOBS_ROOT, exist_ok=True)
    os.chmod(JOBS_ROOT, 0o777)
    wdir = f"{ROOT}/worker-{key}"
    os.makedirs(wdir, exist_ok=True)
    for name, src in (("worker.py", WORKER_SRC), ("studio_bpy.py", STUDIO_BPY_SRC),
                      ("studio_scene.py", SCENE_SRC)):
        with open(os.path.join(wdir, name), "w", encoding="utf-8") as f:
            f.write(src)
    r, w = os.pipe()
    blender = ["blender", "-b", "--factory-startup", "-Y", "--python-exit-code", "3", "-t", "0",
               "-P", wdir + "/worker.py", "--", "--resp-fd", str(w)]
    argv = blender if mode == "none" else _wrap(mode, ["--ro-bind", wdir, wdir, "--bind", bind, bind,
                                                      "--", *blender])
    log = open(ROOT + "/blender.log", "ab")
    t = time.monotonic()
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=log, stderr=log, pass_fds=(w,),
                            start_new_session=True)
    os.close(w)
    st.update(proc=proc, r=r, buf=b"", key=key, mode=mode, jobs=0, boot_s=None)
    line = _readline(st, 120)
    if not line or not line.startswith("ready"):
        with open(ROOT + "/blender.log", "rb") as f:
            tail = f.read()[-1500:].decode(errors="replace")
        _kill(st)
        raise RuntimeError(f"Studio engine failed to start: {tail[-600:]}")
    st["boot_s"] = round(time.monotonic() - t, 2)


def _studio(op, scene, blobs, params, gz=False, cache=None, refs=None):
    import hashlib
    import json
    import os
    import re
    import shutil
    import sys
    import tempfile
    import threading
    import time

    if SCENE_SRC is None:
        return {"ok": False, "error": "this engine was deployed without the Studio schema"}
    if op not in OP_TIMEOUT:
        return {"ok": False, "error": f"op: one of {', '.join(sorted(OP_TIMEOUT))}"}
    key = hashlib.sha256((SCENE_SRC + WORKER_SRC + STUDIO_BPY_SRC).encode()).hexdigest()[:12]
    ns = getattr(sys, "_cycls_scene_ns", None)
    if ns is None or ns.get("_key") != key:
        ns = {"__name__": "studio_scene", "_key": key}
        exec(compile(SCENE_SRC, "studio_scene.py", "exec"), ns)
        sys._cycls_scene_ns = ns
    try:
        scene = ns["normalize"](scene or {})
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    blobs = blobs or {}
    size = 0
    for name, data in blobs.items():
        if not re.match(_BLOB_NAME, name):
            return {"ok": False, "error": f"blobs: {name!r} is not an allowed input name"}
        size += len(data)
    if size > MAX_IN:
        return {"ok": False, "error": f"inputs total {size:,} bytes — the cap is {MAX_IN:,}"}
    try:
        blobs = _unpack(blobs, MAX_IN)
    except (OSError, EOFError, ValueError) as e:
        return {"ok": False, "error": f"blobs: {e}"}
    held = {}                                  # ref → its cached file, linked into the job below
    if cache is not None:
        refs = refs or []
        if not isinstance(cache, str) or not re.match(r"^[0-9a-f]{32}$", cache):
            return {"ok": False, "error": "cache: 32 hex characters"}
        if not isinstance(refs, list) or len(refs) > 20_000 \
                or not all(isinstance(n, str) and re.match(_CACHEABLE, n) for n in refs):
            return {"ok": False, "error": "refs: mesh and texture file names"}
        home = os.path.join(CACHE_ROOT, cache)
        missing = []
        for n in refs:
            if n in blobs:                     # sent now: keep it for next time
                _cache_put(home, n, blobs.pop(n))
            path = os.path.join(home, n)
            if os.path.exists(path):
                os.utime(path)
                held[n] = path
            else:
                missing.append(n)
        if missing:
            return {"ok": False, "missing": missing,
                    "error": f"{len(missing)} file(s) aren't cached on this instance — send them"}

    mode = _sandbox_mode()
    if op in TAINTED and mode == "none":
        return {"ok": False, "error": "this runtime can't sandbox scripts or imports — refused"}

    st = getattr(sys, "_cycls_blender", None)
    if st is None:
        st = sys._cycls_blender = {"lock": threading.Lock(), "proc": None, "r": None, "buf": b""}
    with st["lock"]:
        spawned = False
        os.makedirs(JOBS_ROOT, exist_ok=True)
        os.chmod(JOBS_ROOT, 0o777)
        jobdir = tempfile.mkdtemp(dir=JOBS_ROOT)
        if op in TAINTED:
            # A script or an import gets a worker of its own that sees only this
            # job — never the warm worker, never another job's files.
            _kill(st)
            _spawn(st, mode, key, bind=jobdir)
            spawned = True
        elif st["proc"] is None or st["proc"].poll() is not None or st.get("key") != key \
                or st.get("bind", JOBS_ROOT) != JOBS_ROOT or st.get("jobs", 0) >= RECYCLE_JOBS:
            _kill(st)
            _spawn(st, mode, key)
            spawned = True
        st["bind"] = jobdir if op in TAINTED else JOBS_ROOT
        try:
            os.chmod(jobdir, 0o777)
            for sub_ in ("meshes", "textures", "segments"):
                os.makedirs(jobdir + "/" + sub_)
                os.chmod(jobdir + "/" + sub_, 0o777)
            inputs = {"in.json", "meshes", "textures", "segments"}
            for name, data in blobs.items():
                with open(os.path.join(jobdir, name), "wb") as f:
                    f.write(data.encode() if isinstance(data, str) else data)
                inputs.add(name)
            for name, path in held.items():    # read-only to the worker (another uid): a link, not a copy
                try:
                    os.link(path, os.path.join(jobdir, name))
                except OSError:
                    shutil.copyfile(path, os.path.join(jobdir, name))
                inputs.add(name)
            with open(jobdir + "/in.json", "w") as f:
                json.dump({"op": op, "scene": scene, "params": params or {}}, f)
            t = time.monotonic()
            st["proc"].stdin.write(f"run {jobdir}\n".encode())
            st["proc"].stdin.flush()
            line = _readline(st, OP_TIMEOUT[op])
            if line is None:
                _kill(st)
                return {"ok": False, "error": f"{op} took longer than {OP_TIMEOUT[op]}s — stopped"}
            st["jobs"] += 1
            with open(jobdir + "/out.json") as f:
                out = json.load(f)
            files, total = {}, 0
            for dirpath, _, names in os.walk(jobdir):
                for n in names:
                    rel = os.path.relpath(os.path.join(dirpath, n), jobdir).replace(os.sep, "/")
                    if rel in inputs or rel == "out.json" or rel.startswith(("meshes/", "textures/", "segments/")):
                        continue
                    total += os.path.getsize(os.path.join(dirpath, n))
                    if total > MAX_OUT:
                        return {"ok": False, "error": f"{op} produced over {MAX_OUT:,} bytes"}
                    with open(os.path.join(dirpath, n), "rb") as f:
                        data = f.read()
                    if gz and len(data) >= PACK_MIN:          # a caller on a slow link unpacks it
                        import gzip
                        z = gzip.compress(data, compresslevel=1)
                        if len(z) < 0.9 * len(data):
                            rel, data = rel + ".gz", z
                    files[rel] = data
            meta = {"seconds": round(time.monotonic() - t, 3), "spawned": spawned,
                    "boot_s": st.get("boot_s") if spawned else None, "sandbox": mode, "jobs": st["jobs"]}
            if line.split()[-1] != "ok":
                return {"ok": False, "error": out.get("error", "failed"), "trace": out.get("trace"), **meta}
            return {"ok": True, "op": op, "result": out, "files": files, **meta}
        finally:
            shutil.rmtree(jobdir, ignore_errors=True)
            if op in TAINTED:
                _kill(st)          # a script may have left state behind; nobody inherits it
            if held:
                _cache_trim()


@cycls.function(name="cycls-render", image=image, cpu=8, memory="8Gi",
                timeout=900, concurrency=1)
def render(config: dict = None, *, op: str = None, scene: dict = None, blobs: dict = None,
           params: dict = None, gzip: bool = False, cache: str = None, refs: list = None) -> dict:
    """Legacy: render(config) → {"ok", "png", "preview", "glb", …}.
    Studio:  render(op=…, scene=…, blobs=…, params=…) → {"ok", "result", "files", …}.
    Never raises for bad input."""
    if op is None:
        return _legacy(config)
    try:
        return _studio(op, scene, blobs, params, gz=gzip, cache=cache, refs=refs)
    except Exception as e:                           # engine trouble, reported, not raised
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:500]}"}


render.spec["max_instances"] = 4     # cost ceiling; the decorator doesn't expose it

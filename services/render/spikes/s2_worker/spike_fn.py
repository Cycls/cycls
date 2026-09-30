# Spike S2: a warm, sandboxed Blender worker behind a Cycls function.
#
#   python spikes/s2_worker/drive.py        # runs the measurements on the dev executor
#
# The worker handle lives on `sys`, which survives across calls in one process
# (the deployed shim unpickles the function once; the dev executor re-unpickles
# per call, so module globals would not). Keyed by a hash of the worker source
# + sandbox mode, so a code change respawns it.
from pathlib import Path

import cycls

BLENDER = "5.2.2"
_TARBALL = (f"https://download.blender.org/release/Blender{BLENDER.rsplit('.', 1)[0]}/"
            f"blender-{BLENDER}-linux-x64.tar.xz")
WORKER_SRC = (Path(__file__).parent / "worker.py").read_text(encoding="utf-8")
ROOT = "/tmp/cycls-studio"
JOBS_ROOT = ROOT + "/jobs"

image = (
    cycls.Image()
    .apt("curl", "ca-certificates", "xz-utils", "libgl1", "libegl1", "libglib2.0-0",
         "libx11-6", "libxi6", "libxrender1", "libxxf86vm1", "libxfixes3", "libxext6",
         "libxkbcommon0", "libsm6", "libice6", "bubblewrap", "util-linux")
    .run(f"curl -fsSL {_TARBALL} | tar -xJ -C /opt "
         f"&& mv /opt/blender-{BLENDER}-linux-x64 /opt/blender "
         "&& ln -s /opt/blender/blender /usr/local/bin/blender "
         "&& blender --version")
)

# The SDK's own sandbox defaults (cycls/_app/sandbox/main.py), plus a pid/ipc/uts
# namespace, a non-root uid inside, a fresh session (no TIOCSTI) and /app masked
# (the deployment's own files). Network isolation is added per mode: bwrap's
# --unshare-net can't bring up loopback under gVisor, so "unshare" puts bwrap in
# a fresh, unconfigured netns from outside instead.
_BOX = ["bwrap", "--ro-bind", "/", "/", "--tmpfs", "/tmp", "--tmpfs", "/app", "--dev", "/dev",
        "--proc", "/proc", "--unshare-user", "--uid", "65534", "--gid", "65534",
        "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--new-session", "--die-with-parent", "--clearenv",
        "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin", "--setenv", "HOME", "/tmp",
        "--setenv", "LANG", "C.UTF-8"]
_NET_PROBE = ["python3", "-c", "import socket\ntry:\n socket.create_connection(('1.1.1.1',53),timeout=2); print('OPEN')\n"
              "except OSError as e: print('blocked', type(e).__name__)\n"
              "try:\n socket.create_connection(('169.254.169.254',80),timeout=2); print('METADATA OPEN')\n"
              "except OSError as e: print('metadata blocked', type(e).__name__)"]


def _wrap(sandbox, inner):
    if sandbox == "none":
        return inner
    if sandbox == "bwrap":
        return [*_BOX, "--unshare-net", *inner]
    if sandbox == "unshare":
        return ["unshare", "--net", "--", *_BOX, *inner]
    raise ValueError(sandbox)


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
                return None                      # EOF: the worker died
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
        p.wait(timeout=10)
    if st.get("r") is not None:
        os.close(st["r"])
    st.update(proc=None, r=None, buf=b"")


def _spawn(st, sandbox, key):
    import os
    import subprocess
    import time
    os.makedirs(JOBS_ROOT, exist_ok=True)
    os.chmod(JOBS_ROOT, 0o777)
    wdir = ROOT + "/worker"
    os.makedirs(wdir, exist_ok=True)
    wpath = wdir + "/worker.py"
    with open(wpath, "w", encoding="utf-8") as f:
        f.write(WORKER_SRC)
    r, w = os.pipe()
    blender = ["blender", "-b", "--factory-startup", "-Y", "--python-exit-code", "3", "-t", "0",
               "-P", wpath, "--", "--resp-fd", str(w)]
    if sandbox == "none":
        argv = blender
    else:
        argv = _wrap(sandbox, ["--ro-bind", wdir, wdir, "--bind", JOBS_ROOT, JOBS_ROOT, "--", *blender])
    log = open(ROOT + "/blender.log", "ab")
    t = time.monotonic()
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=log, stderr=log,
                            pass_fds=(w,), start_new_session=True)
    os.close(w)
    st.update(proc=proc, r=r, buf=b"", key=key, sandbox=sandbox, jobs=0)
    line = _readline(st, 120)
    if not line or not line.startswith("ready"):
        with open(ROOT + "/blender.log", "rb") as f:
            tail = f.read()[-1500:].decode(errors="replace")
        _kill(st)
        raise RuntimeError(f"worker did not boot ({line!r}):\n{tail}")
    return round(time.monotonic() - t, 2)


def _job(st, op, params, timeout):
    import json
    import os
    import shutil
    import tempfile
    import time
    jobdir = tempfile.mkdtemp(dir=JOBS_ROOT)
    os.chmod(jobdir, 0o777)
    with open(jobdir + "/in.json", "w") as f:
        json.dump({"op": op, "params": params or {}}, f)
    t = time.monotonic()
    st["proc"].stdin.write(f"run {jobdir}\n".encode())
    st["proc"].stdin.flush()
    line = _readline(st, timeout)
    if line is None:
        _kill(st)
        shutil.rmtree(jobdir, ignore_errors=True)
        return {"status": "dead", "error": f"no answer in {timeout}s — worker killed"}
    with open(jobdir + "/out.json") as f:
        out = json.load(f)
    bins = {n: os.path.getsize(os.path.join(jobdir, n)) for n in os.listdir(jobdir) if n.endswith(".bin")}
    shutil.rmtree(jobdir, ignore_errors=True)
    st["jobs"] += 1
    return {"status": line.split()[1], "roundtrip_ms": round((time.monotonic() - t) * 1000, 2),
            "bins": bins, "out": out}


def _env_probe():
    import os
    import subprocess

    def run(*a):
        try:
            p = subprocess.run(a, capture_output=True, text=True, timeout=20)
            return (p.stdout + p.stderr).strip()[-300:] or f"exit {p.returncode}"
        except Exception as e:
            return f"n/a: {e}"
    userns = "n/a"
    for path in ("/proc/sys/kernel/unprivileged_userns_clone", "/proc/sys/user/max_user_namespaces"):
        if os.path.exists(path):
            userns = f"{path}={open(path).read().strip()}"
            break
    return {"uname": run("uname", "-a"), "proc_version": open("/proc/version").read().strip()[:200],
            "whoami_uid": os.getuid(), "cpus": os.cpu_count(), "bwrap": run("bwrap", "--version"),
            "userns": userns,
            "net_unsandboxed": run(*_NET_PROBE),
            "bwrap_unshare_net": run(*_wrap("bwrap", ["--", *_NET_PROBE])),
            "unshare_net_only": run("unshare", "--net", "--", *_NET_PROBE),
            "unshare_then_bwrap": run(*_wrap("unshare", ["--", *_NET_PROBE])),
            "unshare_then_bwrap_id": run(*_wrap("unshare", ["--", "id"])),
            "app_masked": run(*_wrap("unshare", ["--", "ls", "-la", "/app"])),
            "parent_procs_visible": run(*_wrap("unshare", ["--", "sh", "-c", "ls /proc | grep -c '^[0-9]'"]))}


@cycls.function(name="cycls-render-dev", image=image, cpu=8, memory="8Gi", timeout=900,
                concurrency=1)
def studio_spike(op: str, params: dict = None, sandbox: str = "bwrap", timeout: float = 120):
    import hashlib
    import socket
    import sys
    import threading
    info = {"instance": socket.gethostname(), "spawned": False}
    if op == "env":
        return {**info, **_env_probe()}
    st = getattr(sys, "_cycls_blender", None)
    if st is None:
        st = sys._cycls_blender = {"lock": threading.Lock(), "proc": None, "r": None, "buf": b""}
    key = hashlib.sha256((WORKER_SRC + sandbox).encode()).hexdigest()[:12]
    with st["lock"]:
        if op == "kill":
            _kill(st)
            return {**info, "killed": True}
        if st["proc"] is None or st["proc"].poll() is not None or st.get("key") != key:
            _kill(st)
            info["boot_s"] = _spawn(st, sandbox, key)
            info["spawned"] = True
        info["worker_pid_outside"] = st["proc"].pid
        return {**info, **_job(st, op, params, timeout)}

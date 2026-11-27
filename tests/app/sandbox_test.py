"""Sandbox argv + bwrap behavior tests."""
import asyncio
import os
import shutil
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cycls._agent import tools
from cycls._agent.tools import _exec_bash


def _proc(out=b"ok", code=0):
    """What `Sandbox.run` reads of a process: its output and return code (None: still running). No such group."""
    stdout = asyncio.StreamReader()
    stdout.feed_data(out)
    stdout.feed_eof()
    return SimpleNamespace(pid=2**22 + 7, returncode=code, stdout=stdout, stderr=None)


def _capture_bash_exec(tmp_path, **kwargs):
    captured = {}

    async def fake_exec(*args, **kw):
        captured["argv"] = args
        captured["kwargs"] = kw
        return _proc()

    with patch("asyncio.create_subprocess_exec", fake_exec):
        asyncio.run(_exec_bash("echo", str(tmp_path), **kwargs))
    return captured


def _capture_bash_argv(tmp_path, **kwargs):
    return _capture_bash_exec(tmp_path, **kwargs)["argv"]


def test_bash_sandbox_hides_db(tmp_path):
    """_exec_bash argv must tmpfs-overlay /workspace/.db so the sandboxed shell
    can't read DB internals (defense in depth; editor tools also reject
    .db/ via _resolve_path)."""
    argv = _capture_bash_argv(tmp_path)
    assert "--tmpfs" in argv
    indices = [i for i, a in enumerate(argv) if a == "--tmpfs"]
    assert any(argv[i + 1] == "/workspace/.db" for i in indices), \
        f"expected --tmpfs /workspace/.db in argv, got: {argv}"


def test_bash_sandbox_hides_credentials_and_settings(tmp_path):
    argv = _capture_bash_argv(tmp_path)
    masked = {argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"}
    assert {"/workspace/.secrets", "/workspace/.connectors", "/workspace/.settings"} <= masked


def test_bash_cannot_reach_any_slot_cycls_manages(tmp_path):
    """App data among them: an agent that found .apps/ rewrote two apps' rows with json.dump,
    around the `database` tool and every rule it keeps (2026-10-12)."""
    from cycls._agent.paths import MANAGED
    argv = _capture_bash_argv(tmp_path)
    masked = {argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"}
    assert "/workspace/.apps" in masked
    assert {f"/workspace/{name}" for name in MANAGED} <= masked


def test_bash_touches_nothing_on_the_workspace_for_scratch(tmp_path):
    """The workspace is gcsfuse in production. TMPDIR stays on the sandbox
    tmpfs so pip, tar and tempfile never write there, and a bash call creates
    no .tmp/ of its own — spill makes the directory when it has something to put in it."""
    argv = _capture_bash_argv(tmp_path)
    assert "TMPDIR" not in argv
    assert not (tmp_path / ".tmp").exists()


def test_bash_sandbox_network_off_by_default(tmp_path):
    """Default: --unshare-user + --unshare-net → fresh userns owns the new
    netns so bwrap has NET_ADMIN to bring up lo. No host net access."""
    argv = _capture_bash_argv(tmp_path)
    assert "--unshare-user" in argv
    assert "--unshare-net" in argv


def test_bash_sandbox_network_opt_in(tmp_path):
    """network=True drops --unshare-net so bash can egress (curl, pip, git)
    via the host network. Metadata server (169.254.169.254) is reachable
    in this mode — mitigation tracked separately."""
    argv = _capture_bash_argv(tmp_path, network=True)
    assert "--unshare-net" not in argv
    assert "--unshare-user" in argv


def test_bash_sandbox_clearenv(tmp_path):
    """--clearenv strips parent env so secrets like ANTHROPIC_API_KEY don't
    cross the sandbox boundary."""
    argv = _capture_bash_argv(tmp_path)
    assert "--clearenv" in argv


def test_bash_sandbox_forwards_only_safe_env(tmp_path):
    """Only PATH / HOME / TERM / LANG / LD_PRELOAD, the two fixed trash
    paths (CYCLS_WORKSPACE / CYCLS_TRASH, constants the rm shim reads), the pip
    stand-in's size limit and the fixed switches that keep a command off prompts
    may be forwarded via --setenv.
    LD_PRELOAD is the metadata-block shim path; everything else risks leaking a
    secret the caller forgot to strip."""
    argv = _capture_bash_argv(tmp_path)
    safe = {"PATH", "HOME", "TERM", "LANG", "LD_PRELOAD", "CYCLS_WORKSPACE", "CYCLS_TRASH", "CYCLS_PIP_LIMIT_MB", "PYTHONUNBUFFERED",
            "PIP_NO_INPUT", "PIP_NO_CACHE_DIR", "PIP_DISABLE_PIP_VERSION_CHECK", "DEBIAN_FRONTEND", "GIT_TERMINAL_PROMPT"}
    forwarded = {argv[i + 1] for i, a in enumerate(argv) if a == "--setenv"}
    assert forwarded <= safe, f"unexpected env forwarded: {forwarded - safe}"


def test_bash_sandbox_blockmeta_so_mounted(tmp_path):
    """The LD_PRELOAD shim must be ro-bound into the sandbox and LD_PRELOAD
    set to its mount path — closes the GCP/AWS/Azure metadata exfil vector
    for libc-using code (bypassable by static binaries; documented limit)."""
    argv = _capture_bash_argv(tmp_path)
    assert any(a == "/tmp/.blockmeta.so" for a in argv), "blockmeta.so not bound"
    setenv_pairs = [(argv[i+1], argv[i+2]) for i, a in enumerate(argv) if a == "--setenv"]
    assert ("LD_PRELOAD", "/tmp/.blockmeta.so") in setenv_pairs


def test_bash_sandbox_die_with_parent(tmp_path):
    """--die-with-parent prevents orphaned sandbox processes."""
    argv = _capture_bash_argv(tmp_path)
    assert "--die-with-parent" in argv


def test_bash_sandbox_bwrap_env_is_sanitized(tmp_path, monkeypatch):
    """REGRESSION: bwrap itself is visible as PID 1 inside the sandbox, so
    its own environ must be sanitized via subprocess env=. --clearenv only
    affects the bash child — without env= on subprocess_exec, bwrap leaks
    the parent Python's secrets via /proc/1/environ."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-LEAK")
    monkeypatch.setenv("CYCLS_API_KEY", "ak-LEAK")
    monkeypatch.setenv("GITHUB_TOKEN", "ghu_LEAK")
    captured = _capture_bash_exec(tmp_path)
    env = captured["kwargs"].get("env")
    assert env is not None, "bwrap must be launched with explicit env= to block leak"
    assert set(env.keys()) <= {"PATH", "LANG"}, f"unexpected bwrap env keys: {env.keys()}"
    blob = "\n".join(f"{k}={v}" for k, v in env.items())
    assert "LEAK" not in blob
    assert "sk-ant" not in blob
    assert "ak-" not in blob
    assert "ghu_" not in blob


def _bwrap_live_ok():
    """Probe whether bwrap can actually run with our mount config.
    Deployed containers have /workspace; dev hosts usually don't,
    and --ro-bind / / blocks creating it."""
    if shutil.which("bwrap") is None:
        return False
    try:
        out = asyncio.run(_exec_bash("echo ok", "/tmp"))
        return "ok" in out and "Read-only file system" not in out
    except Exception:
        return False


_BWRAP_LIVE = _bwrap_live_ok()


@pytest.mark.skipif(not _BWRAP_LIVE, reason="bwrap cannot run in this env (needs /workspace mount point)")
def test_bash_sandbox_blockmeta_so_blocks_metadata_live(tmp_path):
    """Live: the LD_PRELOAD shim must intercept connect() to 169.254.169.254
    via libc and return ECONNREFUSED. Catches a future where someone edits
    _blockmeta.c and forgets to rebuild — stale .so would still bind-mount
    fine but stop blocking. Without the shim, curl returns 200 (Azure
    metadata reachable on Codespace) or times out at --max-time 3s."""
    out = asyncio.run(_exec_bash(
        "curl -sS --max-time 3 -o /dev/null "
        "-w 'http=%{http_code} time=%{time_total}' "
        "http://169.254.169.254/ 2>&1",
        str(tmp_path), network=True,
    ))
    assert "Couldn't connect" in out or "Connection refused" in out, \
        f"shim did not block connect() to 169.254.169.254: {out!r}"


@pytest.mark.skipif(not _BWRAP_LIVE, reason="bwrap cannot run in this env (needs /workspace mount point)")
def test_bash_sandbox_bwrap_pid_environ_is_clean_live(tmp_path, monkeypatch):
    """Live: bwrap's own environ (visible in the sandbox's /proc) must not
    leak the parent Python's secrets. We don't --unshare-pid (breaks in
    nested containers), so the full /proc is visible — but each process's
    environ is what matters, and bwrap's must be sanitized.
    Note: without --unshare-pid, bash CAN read the parent Python's environ
    via /proc/<ppid>/environ. This is the pre-existing state documented in
    docs/notes/sandbox-security.md — eliminating it requires PID namespace isolation that
    isn't available in our nested-container runtime."""
    monkeypatch.setenv("CYCLS_SANDBOX_LEAK_SENTINEL_XYZ", "should-not-leak")
    out = asyncio.run(_exec_bash(
        r"pgrep -a bwrap | awk '{print $1}' | xargs -I{} sh -c 'tr \"\\0\" \"\\n\" < /proc/{}/environ' 2>/dev/null",
        str(tmp_path),
    ))
    assert "should-not-leak" not in out, (
        "bwrap's own environ leaked parent-process secret — env= sanitization "
        "on subprocess_exec is broken"
    )


def test_bash_sandbox_bind_targets_ship_in_the_image(tmp_path):
    """bwrap can't mkdir inside `--ro-bind / /`: a bind target outside /workspace,
    /tmp or /skills must be created by the image, or every bash call dies."""
    from cycls._agent.main import Agent
    argv = _capture_bash_argv(tmp_path)
    targets = {dst for flag, _, dst in zip(argv, argv[1:], argv[2:]) if flag in ("--bind", "--ro-bind")}
    baked = " ".join(Agent._base_run).split()
    for t in targets - {"/", "/workspace"}:
        assert t.startswith(("/workspace/", "/tmp/", "/skills/")) or t in baked, t


# ---- a command's life: real processes, behind a `bwrap` that runs the command as is ----

@pytest.fixture
def plain_bwrap(tmp_path_factory, monkeypatch):
    """Isolation is tested above and live; here, what Sandbox.run does with the processes, on any host."""
    d = tmp_path_factory.mktemp("bin")
    (d / "bwrap").write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n')
    (d / "bwrap").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")


def _gone(pid, within=10.0):
    end = time.monotonic() + within
    while time.monotonic() < end:
        try: os.kill(pid, 0)
        except ProcessLookupError: return True
        time.sleep(0.05)
    return False


def test_a_timed_out_command_stops_all_it_started_and_keeps_what_it_printed(tmp_path, plain_bwrap):
    """It killed bwrap alone: a child it started held the pipe and the call returned when the child did (34 min
    once, on a 120 s limit). What the command printed was dropped."""
    started = time.monotonic()
    out = asyncio.run(_exec_bash(f"echo started; sleep 60 & echo $! > {tmp_path}/child; sleep 60", str(tmp_path), timeout=3))
    assert time.monotonic() - started < 20   # not the 60 s the child would have held it
    assert out.startswith("Error: timed out after 3s") and out.endswith("started")
    assert _gone(int((tmp_path / "child").read_text()))


def test_a_child_left_running_does_not_hold_the_call(tmp_path, plain_bwrap):
    started = time.monotonic()
    out = asyncio.run(_exec_bash(f"sleep 60 & echo $! > {tmp_path}/child; echo done", str(tmp_path), timeout=30))
    assert time.monotonic() - started < 15 and out.startswith("done\n[exit 0 · ")   # not the 30 s limit
    assert _gone(int((tmp_path / "child").read_text()))


def test_output_comes_in_order_with_its_exit_code_and_nothing_waits_on_input(tmp_path, plain_bwrap):
    out = asyncio.run(_exec_bash("echo a; echo b >&2; read x; echo c$x; exit 3", str(tmp_path), timeout=10))
    assert out.splitlines()[:3] == ["a", "b", "c"] and out.splitlines()[-1].startswith("[exit 3 · ")


def test_a_command_asks_for_at_most_five_minutes_unless_the_agent_allows_more(monkeypatch):
    seen = []
    async def run(command, cwd, timeout, **_): seen.append(timeout)
    monkeypatch.setattr(tools, "_exec_bash", run)
    ws = SimpleNamespace(root="/tmp")
    for asked, default in ((3_600_000, 120), (30_000, 120), (None, 120), (3_600_000, 900)):
        asyncio.run(tools._run_bash({"command": "x", "timeout": asked}, ws, timeout=default, network=False))
    assert seen == [300, 30, 120, 900]


def _shim(name):
    """A stand-in from the sandbox's shim folder, loaded as a module."""
    import importlib.machinery, importlib.util, pathlib
    path = pathlib.Path(tools.__file__).parent / "shims" / name
    loader = importlib.machinery.SourceFileLoader(f"shim_{name}", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_pip_is_stopped_once_its_download_passes_the_limit(monkeypatch, capsys):
    """/tmp is memory every chat on the container shares: torch's 3 GB crashed containers. Stopped at 50 MB."""
    pip = _shim("pip")
    filled = iter([0, 20e6, 60e6])
    monkeypatch.setattr(pip, "used", lambda: next(filled))
    monkeypatch.setattr(pip.time, "sleep", lambda s: None)

    class Download:   # runs until stopped
        returncode = None
        def poll(self): return self.returncode
        def kill(self): self.returncode = -9
        def wait(self): return self.returncode
    monkeypatch.setattr(pip.subprocess, "Popen", lambda argv: Download())
    assert pip.main(["install", "torch"]) == 1
    err = capsys.readouterr().err
    assert "pip: stopped" in err and '"packages": ["torch"], "mb": 60.0, "installed": false' in err


def test_a_note_anything_could_print_sets_only_the_pip_fields(tmp_path, monkeypatch):
    rows = []
    monkeypatch.setattr(tools, "log", lambda level, **f: rows.append((level, f)))
    out = '[cycls-pip] {"packages": ["a"], "mb": 1, "installed": true, "user": "someone"}\n[cycls-pip] {"level": 1}\nhi'

    async def fake_exec(*args, **kw): return _proc(out.encode())
    with patch("asyncio.create_subprocess_exec", fake_exec):
        shown = asyncio.run(_exec_bash("x", str(tmp_path)))
    assert rows == [("pip", {"packages": ["a"], "mb": 1.0, "installed": True})]
    assert shown.startswith("hi\n[exit 0")


def test_a_flood_of_output_keeps_its_start_and_end_not_all_of_it(tmp_path, plain_bwrap):
    """Held whole, a print loop could fill the server's memory in seconds and take every chat on it down."""
    from cycls._agent.tools import MAX_OUTPUT
    out = asyncio.run(_exec_bash("echo START; head -c 30000000 /dev/zero | tr '\\0' x; echo; echo END", str(tmp_path), timeout=30))
    assert out.startswith("START") and "(truncated)" in out and out.splitlines()[-2] == "END"
    assert len(out) < MAX_OUTPUT + 100


def test_a_cut_flood_always_says_so():
    """Cut on its last chunk, a flood came back exactly at the limit and the tool added no marker: start and end read
    as if joined."""
    from cycls._app.sandbox.main import _drain
    async def go():
        stream, buf = asyncio.StreamReader(), bytearray()
        stream.feed_data(b"a" * 15 + b"b" * 10)
        stream.feed_eof()
        await _drain(stream, buf, cap=10)
        return bytes(buf)
    assert asyncio.run(go()) == b"aaaaa\n... (truncated) ...\nbbbbb"

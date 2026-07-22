"""Sandbox argv + bwrap behavior tests."""
import asyncio
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cycls._agent.tools import _exec_bash


def _capture_bash_exec(tmp_path, **kwargs):
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
    captured = {}

    async def fake_exec(*args, **kw):
        captured["argv"] = args
        captured["kwargs"] = kw
        return mock_proc

    with patch("asyncio.create_subprocess_exec", fake_exec):
        asyncio.run(_exec_bash("echo", str(tmp_path), **kwargs))
    return captured


def _capture_bash_argv(tmp_path, **kwargs):
    return _capture_bash_exec(tmp_path, **kwargs)["argv"]


def test_bash_sandbox_hides_db(tmp_path):
    """_exec_bash argv must tmpfs-overlay /workspace/.db so the sandboxed shell
    can't read DB internals (defense in depth; editor tools also reject
    .db/ via _resolve_path)."""
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))

    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["argv"] = args
        return mock_proc

    with patch("asyncio.create_subprocess_exec", fake_exec):
        asyncio.run(_exec_bash("echo", str(tmp_path)))

    argv = captured["argv"]
    assert "--tmpfs" in argv
    indices = [i for i, a in enumerate(argv) if a == "--tmpfs"]
    assert any(argv[i + 1] == "/workspace/.db" for i in indices), \
        f"expected --tmpfs /workspace/.db in argv, got: {argv}"


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
    """Only PATH / HOME / TERM / LANG / LD_PRELOAD may be forwarded via --setenv.
    LD_PRELOAD is the metadata-block shim path; everything else risks leaking
    a secret the caller forgot to strip."""
    argv = _capture_bash_argv(tmp_path)
    safe = {"PATH", "HOME", "TERM", "LANG", "LD_PRELOAD"}
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

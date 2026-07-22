"""Sandbox — bwrap fluent builder. Sandbox() ships secure-by-default;
chain methods deviate via last-flag-wins."""
import asyncio
import importlib.resources
from dataclasses import dataclass, field, replace
from typing import NamedTuple, Optional


# --unshare-user is required for --unshare-net to work in containers that
# lack CAP_NET_ADMIN (Docker default, Cloud Run): the new netns is owned
# by the new userns where bwrap has all caps, so RTM_NEWADDR for lo works.
_DEFAULT_ARGS = [
    "--ro-bind", "/", "/",
    "--tmpfs", "/tmp",
    "--dev", "/dev",
    "--proc", "/proc",
    "--unshare-user",
    "--clearenv",
    "--die-with-parent",
    "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
    "--setenv", "HOME", "/workspace",
    "--setenv", "TERM", "xterm",
    "--setenv", "LANG", "C.UTF-8",
]

# LD_PRELOAD shim — blocks libc connect() to 169.254.0.0/16 (cloud metadata).
# Bound into every sandbox via LD_PRELOAD env var. See _blockmeta.c.
# Bypassable by static binaries / raw syscall — see docs/notes/sandbox-security.md.
_BLOCKMETA_SO = str(importlib.resources.files("cycls._app.sandbox") / "_blockmeta.so")
_BLOCKMETA_DST = "/tmp/.blockmeta.so"
_METADATA_GUARD = [
    "--ro-bind", _BLOCKMETA_SO, _BLOCKMETA_DST,
    "--setenv", "LD_PRELOAD", _BLOCKMETA_DST,
]


class SandboxResult(NamedTuple):
    stdout: bytes
    stderr: bytes
    code: int
    timed_out: bool

    @property
    def output(self) -> str:
        return self.stdout.decode(errors="replace") + self.stderr.decode(errors="replace")


@dataclass(frozen=True)
class Sandbox:
    _args: list = field(default_factory=lambda: [*_DEFAULT_ARGS, *_METADATA_GUARD])
    _timeout: Optional[float] = None
    _network: bool = False

    def _add(self, *a):                   return replace(self, _args=[*self._args, *map(str, a)])
    def bind(self, src, dst=None):        return self._add("--bind", src, dst or src)
    def ro_bind(self, src, dst=None):     return self._add("--ro-bind", src, dst or src)
    def ro_bind_try(self, src, dst=None): return self._add("--ro-bind-try", src, dst or src)
    def tmpfs(self, path):                return self._add("--tmpfs", path)
    def proc(self, path="/proc"):         return self._add("--proc", path)
    def dev(self, path="/dev"):           return self._add("--dev", path)
    def chdir(self, path):                return self._add("--chdir", path)
    def die_with_parent(self):            return self._add("--die-with-parent")
    def clearenv(self):                   return self._add("--clearenv")
    def network(self, on=True):           return replace(self, _network=on)
    def timeout(self, seconds: float):    return replace(self, _timeout=seconds)

    def setenv(self, **vars):
        s = self
        for k, v in vars.items():
            s = s._add("--setenv", k, str(v))
        return s

    async def run(self, argv: list[str], env: Optional[dict] = None) -> SandboxResult:
        bwrap_argv = ["bwrap", *self._args]
        if not self._network:
            bwrap_argv.append("--unshare-net")
        bwrap_argv += ["--", *argv]
        proc = await asyncio.create_subprocess_exec(
            *bwrap_argv, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            timed_out = True; proc.kill()
            try: stdout, stderr = await proc.communicate()
            except Exception: stdout, stderr = b"", b""
        code = proc.returncode if proc.returncode is not None else -1
        return SandboxResult(stdout, stderr, code, timed_out)

"""Sandbox — fluent builder over bwrap. Linux-only.

Run untrusted commands inside the container with a restricted namespace.
Each method appends to a `bwrap` argv and returns a new Sandbox (immutable).

    sb = (cycls.Sandbox()
        .ro_bind("/", "/")
        .bind("/workspace", "/workspace")
        .tmpfs("/tmp").dev("/dev").proc("/proc")
        .chdir("/workspace").network(False)
        .timeout(30))
    result = await sb.run(["python", "-c", code])
"""
import asyncio
from typing import Optional


class SandboxResult:
    def __init__(self, stdout: bytes, stderr: bytes, code: int, timed_out: bool):
        self.stdout = stdout
        self.stderr = stderr
        self.code = code
        self.timed_out = timed_out

    @property
    def output(self) -> str:
        """stdout + stderr decoded as text."""
        return self.stdout.decode(errors="replace") + self.stderr.decode(errors="replace")


class Sandbox:
    def __init__(self):
        self._args: list[str] = []
        self._timeout: Optional[float] = None
        self._network: bool = False  # secure-by-default; opt in via .network()

    def _copy(self) -> "Sandbox":
        new = Sandbox.__new__(Sandbox)
        new._args = list(self._args)
        new._timeout = self._timeout
        new._network = self._network
        return new

    def _add(self, *args) -> "Sandbox":
        new = self._copy()
        new._args.extend(str(a) for a in args)
        return new

    def bind(self, src, dst=None):       return self._add("--bind", src, dst or src)
    def ro_bind(self, src, dst=None):    return self._add("--ro-bind", src, dst or src)
    def ro_bind_try(self, src, dst=None): return self._add("--ro-bind-try", src, dst or src)
    def tmpfs(self, path):                return self._add("--tmpfs", path)
    def proc(self, path="/proc"):         return self._add("--proc", path)
    def dev(self, path="/dev"):           return self._add("--dev", path)
    def chdir(self, path):                return self._add("--chdir", path)
    def die_with_parent(self):            return self._add("--die-with-parent")
    def clearenv(self):                   return self._add("--clearenv")

    def network(self, on=True):
        new = self._copy()
        new._network = on
        return new

    def setenv(self, **vars):
        s = self
        for k, v in vars.items():
            s = s._add("--setenv", k, str(v))
        return s

    def timeout(self, seconds: float):
        new = self._copy()
        new._timeout = seconds
        return new

    async def run(self, argv: list[str], env: Optional[dict] = None) -> SandboxResult:
        bwrap_argv = ["bwrap", *self._args]
        if not self._network:
            bwrap_argv.append("--unshare-net")
        bwrap_argv += ["--", *argv]
        proc = await asyncio.create_subprocess_exec(
            *bwrap_argv,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            try: stdout, stderr = await proc.communicate()
            except Exception: stdout, stderr = b"", b""
        return SandboxResult(stdout, stderr, proc.returncode or -1, timed_out)

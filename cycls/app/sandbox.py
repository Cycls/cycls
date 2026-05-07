"""Sandbox — bwrap fluent builder. Sandbox() ships secure-by-default;
chain methods deviate via last-flag-wins. network(True) attaches
slirp4netns with --disable-host-loopback so the sandbox gets internet
but cannot reach 169.254.169.254 (GCP metadata) or other host loopback."""
import asyncio
import json
import os
from dataclasses import dataclass, field, replace
from typing import NamedTuple, Optional


_DEFAULT_ARGS = [
    "--ro-bind", "/", "/",
    "--tmpfs", "/tmp",
    "--dev", "/dev",
    "--proc", "/proc",
    "--clearenv",
    "--die-with-parent",
    "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
    "--setenv", "HOME", "/workspace",
    "--setenv", "TERM", "xterm",
    "--setenv", "LANG", "C.UTF-8",
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
    _args: list = field(default_factory=lambda: list(_DEFAULT_ARGS))
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
        # Always own a fresh netns. network=True attaches slirp4netns with
        # --disable-host-loopback so 169.254.169.254 (GCP metadata) is blackholed.
        bwrap_argv = ["bwrap", *self._args, "--unshare-net"]
        info_r = block_w = None
        pass_fds: tuple = ()
        if self._network:
            info_r, info_w = os.pipe()
            block_r, block_w = os.pipe()
            bwrap_argv += ["--info-fd", str(info_w), "--block-fd", str(block_r)]
            pass_fds = (info_w, block_r)

        proc = await asyncio.create_subprocess_exec(
            *bwrap_argv, "--", *argv, env=env, pass_fds=pass_fds,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        if self._network:
            os.close(info_w); os.close(block_r)

        slirp = None
        try:
            if self._network:
                slirp = await self._attach_slirp(info_r)
                os.close(block_w); block_w = None  # unblocks bwrap

            timed_out = False
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            except asyncio.TimeoutError:
                timed_out = True; proc.kill()
                try: stdout, stderr = await proc.communicate()
                except Exception: stdout, stderr = b"", b""
            code = proc.returncode if proc.returncode is not None else -1
            return SandboxResult(stdout, stderr, code, timed_out)
        finally:
            for fd in (info_r, block_w):
                if fd is not None:
                    try: os.close(fd)
                    except OSError: pass
            if slirp and slirp.returncode is None: slirp.terminate()

    async def _attach_slirp(self, info_fd: int):
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, os.read, info_fd, 4096)
        if not info: raise RuntimeError("bwrap closed info-fd before child-pid")
        pid = json.loads(info.decode())["child-pid"]

        ready_r, ready_w = os.pipe()
        slirp = await asyncio.create_subprocess_exec(
            "slirp4netns", "--configure", "--mtu=65520",
            "--disable-host-loopback", f"--ready-fd={ready_w}",
            str(pid), "tap0", pass_fds=(ready_w,),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        os.close(ready_w)
        try: await loop.run_in_executor(None, os.read, ready_r, 1)
        finally: os.close(ready_r)
        return slirp

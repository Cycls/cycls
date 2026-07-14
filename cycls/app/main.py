import asyncio
import importlib.resources
import os
from functools import cached_property
from pathlib import Path
from typing import Optional

from cycls.function import Function, _get_api_key, _get_base_url
from cycls.function.remote import SHIM_PRELUDE
from cycls.app.auth import JWT, validator
from cycls.app.db import workspace

CYCLS_PATH = importlib.resources.files("cycls")


def _serve(app, port):
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    from cycls.function.remote import BARE_LOGS
    config = Config()
    config.bind = [f"0.0.0.0:{port}"]
    config.alpn_protocols = ["h2", "http/1.1"]
    config.accesslog = config.errorlog = "-"
    config.access_log_format = "%(s)s %(m)s %(U)s"
    config.logconfig_dict = BARE_LOGS
    asyncio.run(serve(app, config))


SERVE_PY = SHIM_PRELUDE + '''
import queue

state = {"app": payload()}
_subs, _real = [], sys.stdout

class _Tee:
    def write(self, s):
        _real.write(s)
        for q in list(_subs):
            q.put_nowait(s)
        return len(s)
    def flush(self):
        _real.flush()

sys.stdout = _Tee()

async def logs(scope, receive, send):
    q = queue.Queue()
    _subs.append(q)
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/plain")]})
    try:
        idle = 0.0
        while True:
            buf = b""
            while not q.empty():
                buf += q.get_nowait().encode()
            if buf:
                idle = 0.0
                await send({"type": "http.response.body", "body": buf, "more_body": True})
            elif idle > 10:
                idle = 0.0
                await send({"type": "http.response.body", "body": b"\\n", "more_body": True})
            await asyncio.sleep(0.2)
            idle += 0.2
    finally:
        _subs.remove(q)

async def dispatcher(scope, receive, send):
    if scope["type"] == "http" and scope["path"] == "/_cycls/reload" and scope["method"] == "POST":
        if (bad := check(scope)):
            return await reply(send, *bad)
        try:
            state["app"] = cloudpickle.loads(await read(receive))()
        except Exception:
            return await reply(send, 500, traceback.format_exc().encode())
        return await reply(send, 200, b"reloaded")
    if scope["type"] == "http" and scope["path"] == "/_cycls/logs":
        h = dict(scope["headers"])
        if not hmac.compare_digest(h.get(b"x-cycls-token", b"").decode(), token):
            return await reply(send, 403, b"bad token")
        return await logs(scope, receive, send)
    await state["app"](scope, receive, send)

if __name__ == "__main__":
    boot(dispatcher)
'''


class App(Function):
    _base_pip = ["hypercorn", "fastapi[standard]", "pyjwt", "cryptography"]
    _base_apt = ["bubblewrap"]
    _serves = True

    def __init__(self, func, name, image=None, memory="1Gi",
                 auth: Optional[JWT] = None):
        if auth is not None and not isinstance(auth, JWT):
            raise TypeError(f"auth must be cycls.JWT or None, got {type(auth).__name__}")
        self.user_func = func
        self.prod = False
        self.volume = Path((image or {}).get("volume", "/workspace"))
        self._auth_provider = auth

        image = dict(image or {})
        image["copy"] = {str(CYCLS_PATH): "cycls", **image.get("copy", {})}

        super().__init__(func=func, name=name, image=image, memory=memory,
                         base_url=_get_base_url(), api_key=_get_api_key())

    def __call__(self, *args, **kwargs):
        return self.user_func(*args, **kwargs)

    @property
    def storage(self) -> str:
        if self.prod and self.name:
            return f"gs://cycls-ws-{self.name}"
        return f"file://{self.volume}"

    def _depends(self, fn):
        if self._auth_provider is None:
            raise RuntimeError("Requires auth=... on the @cycls.app decorator")
        from fastapi import Depends
        return Depends(fn)

    @cached_property
    def auth(self):
        return self._depends(validator(self._auth_provider, self.prod))

    @cached_property
    def workspace(self):
        def _build_ws(user=self.auth):
            return workspace(user, self.volume, base=self.storage)
        return self._depends(_build_ws)

    def _prepare_func(self, prod):
        self.prod = prod
        user_func = self.user_func
        self.func = lambda port: _serve(user_func(), port)

    def _local(self, port=8080):
        print(f"Starting local server at localhost:{port}")
        self.prod = False
        _serve(self.user_func(), port)

    def local(self, port=8080, watch=True):
        """Run in Docker; reload on file changes unless watch=False."""
        if os.environ.get('_CYCLS_WATCH'):
            watch = False
        self._prepare_func(prod=False)
        self.watch(port=port) if watch else self.run(port=port)

    def deploy(self, port=8080):
        if self.api_key is None:
            raise RuntimeError("Missing API key. Set cycls.api_key or CYCLS_API_KEY environment variable.")
        self._prepare_func(prod=True)
        return super().deploy(port=port)

    @property
    def dev_name(self):
        return f"dev-{self.name}"

    def remote(self):
        """Serve this app's CURRENT code on its cloud dev service — provision
        once, then each call hot-swaps the running app on a stable URL."""
        import cloudpickle
        from cycls.function.remote import RemoteError, post
        if not self.api_key:
            raise RemoteError("No API key. Set CYCLS_API_KEY or cycls.api_key.")
        self.prod = False
        name, builder = self.dev_name, self.user_func
        r = post(f"https://{name}.cycls.ai/_cycls/reload", cloudpickle.dumps(builder),
                 name=name, api_key=self.api_key, timeout=120)
        if r.status_code == 404:
            print(f"Provisioning '{name}' (one-time for this image)...")
            dev = Function(builder, name, image=self._image_config(), api_key=self._api_key)
            if not dev.deploy(remote=SERVE_PY, memory=self.spec["memory"]):
                raise RemoteError(f"provisioning {name!r} failed")
        elif r.status_code != 200:
            raise RemoteError(f"{name}: {r.status_code} {r.text[:2000]}", status=r.status_code)
        else:
            print(f"  https://{name}.cycls.ai")


def _make_decorator(cls):
    def factory(name=None, image=None, **kwargs):
        def decorator(func):
            return cls(func=func, name=name or func.__name__, image=image, **kwargs)
        return decorator
    return factory


app = _make_decorator(App)

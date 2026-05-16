import asyncio
import importlib.resources
import os
from functools import cached_property
from pathlib import Path
from typing import Optional

from cycls.function import Function, _get_api_key, _get_base_url
from cycls.app.auth import JWT, validator
from cycls.app.db import workspace

CYCLS_PATH = importlib.resources.files("cycls")


def _serve(app, port):
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    config = Config()
    config.bind = [f"0.0.0.0:{port}"]
    config.alpn_protocols = ["h2", "http/1.1"]
    config.accesslog = "-"  # access logs to stdout (hypercorn defaults to none)
    config.access_log_format = '%(s)s %(r)s'  # status + request line; drop UA/referer noise
    asyncio.run(serve(app, config))


class App(Function):
    _base_pip = ["hypercorn", "fastapi[standard]", "pyjwt", "cryptography"]
    _base_apt = ["bubblewrap"]

    def __init__(self, func, name, image=None, memory="1Gi",
                 auth: Optional[JWT] = None):
        if auth is not None and not isinstance(auth, JWT):
            raise TypeError(f"auth must be cycls.JWT or None, got {type(auth).__name__}")
        self.user_func = func
        self.memory = memory
        self.prod = False
        self.volume = Path((image or {}).get("volume", "/workspace"))
        self._auth_provider = auth

        image = dict(image or {})
        image["copy"] = {str(CYCLS_PATH): "cycls", **image.get("copy", {})}

        super().__init__(func=func, name=name, image=image,
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
        return super().deploy(port=port, memory=self.memory)


def _make_decorator(cls):
    def factory(name=None, image=None, **kwargs):
        def decorator(func):
            return cls(func=func, name=name or func.__name__, image=image, **kwargs)
        return decorator
    return factory


app = _make_decorator(App)

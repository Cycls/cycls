import importlib.resources
import os
from functools import cached_property
from pathlib import Path
from typing import Optional

import uvicorn

from cycls.function import Function, _get_api_key, _get_base_url
from cycls.app.auth import JWT, make_validate
from cycls.app.tenancy import subject_for, workspace_for
from cycls.app import signing

CYCLS_PATH = importlib.resources.files("cycls")


class App(Function):
    _base_pip = ["uvicorn[standard]", "slatedb",
                 "fastapi[standard]", "pyjwt", "cryptography"]
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

        # User code referencing `cycls.DB`, `cycls.Workspace`, `app.auth`,
        # etc. inside the function gets serialized via cloudpickle — which
        # requires the cycls source to be importable in the container.
        image = dict(image or {})
        image["copy"] = {str(CYCLS_PATH): "cycls", **image.get("copy", {})}

        super().__init__(
            func=func,
            name=name,
            image=image,
            base_url=_get_base_url(),
            api_key=_get_api_key(),
        )

    def __call__(self, *args, **kwargs):
        return self.user_func(*args, **kwargs)

    @property
    def base(self) -> str:
        if self.prod and self.name:
            return f"gs://cycls-ws-{self.name}"
        return f"file://{self.volume}"

    @cached_property
    def auth(self):
        if self._auth_provider is None:
            raise RuntimeError("App.auth requires auth=... on the @cycls.app decorator")
        from fastapi import Depends
        return Depends(make_validate(self._auth_provider.resolve(self.prod)["jwks_url"]))

    @cached_property
    def workspace(self):
        if self._auth_provider is None:
            raise RuntimeError("App.workspace requires auth=... on the @cycls.app decorator")
        from fastapi import Depends
        def _build_ws(user=self.auth):
            return workspace_for(user, self.volume, base=self.base)
        return Depends(_build_ws)

    @cached_property
    def signing_key(self) -> bytes:
        """Persisted HMAC secret; rotate by deleting the file and redeploying."""
        path = self.volume / ".cycls" / "signing.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return path.read_bytes()
        key = signing.new_secret()
        path.write_bytes(key)
        return key

    def signed_url(self, path: str, user, ttl: int = 3600) -> str:
        """`chat/<id>` mints an SPA share link; `file/<path>` mints a raw-bytes URL with the path inlined."""
        from urllib.parse import quote, urlencode
        sub = user if isinstance(user, str) else subject_for(user)
        params = signing.sign(path, sub, self.signing_key, ttl=ttl)
        if path.startswith("file/"):
            params.pop("path")
            rest = quote(path[len("file/"):], safe="/")
            return f"/shared/file/{rest}?{urlencode(params)}"
        return f"/shared?{urlencode(params)}"

    def verify_signed(self, path: str, user: str, exp, sig: str) -> bool:
        return signing.verify(path, user, exp, sig, self.signing_key)

    def _prepare_func(self, prod):
        self.prod = prod
        user_func = self.user_func
        self.func = lambda port: uvicorn.run(user_func(), host="0.0.0.0", port=port)

    def _local(self, port=8080):
        """Run uvicorn directly, bypassing Docker."""
        print(f"Starting local server at localhost:{port}")
        self.prod = False
        uvicorn.run(self.user_func(), host="0.0.0.0", port=port)

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

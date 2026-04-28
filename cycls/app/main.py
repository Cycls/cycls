import importlib.resources
import os
from functools import cached_property
from pathlib import Path
from typing import Optional

import uvicorn

from cycls.function import Function, _get_api_key, _get_base_url
from cycls.app.auth import JWT, make_validate
from cycls.app.db import workspace_for
from cycls.app.sandbox import Sandbox
from cycls.app import signing

CYCLS_PATH = importlib.resources.files("cycls")


class App(Function):
    """App extends Function with a blocking ASGI service."""

    _base_pip = ["uvicorn[standard]", "slatedb",
                 "fastapi[standard]", "pyjwt", "cryptography"]
    _base_apt = ["bubblewrap"]

    def __init__(self, func, name, image=None, memory="1Gi",
                 auth: Optional[JWT] = None, sandbox: Optional[Sandbox] = None):
        for kw, val, t in (("auth", auth, JWT), ("sandbox", sandbox, Sandbox)):
            if val is not None and not isinstance(val, t):
                raise TypeError(f"{kw} must be cycls.{t.__name__} or None, got {type(val).__name__}")
        self.user_func = func
        self.memory = memory
        self.prod = False
        self.volume = Path((image or {}).get("volume", "/workspace"))
        self._auth_provider = auth
        self._sandbox = sandbox

        # User code referencing `cycls.DB`, `cycls.Workspace`, `app.auth`,
        # etc. inside the function gets serialized via cloudpickle — which
        # requires the cycls source to be importable in the container.
        image = dict(image or {})
        user_copy = image.get("copy", {})
        if isinstance(user_copy, list):
            user_copy = {f: f for f in user_copy}
        image["copy"] = {str(CYCLS_PATH): "cycls", **user_copy}

        super().__init__(
            func=func,
            name=name,
            image=image,
            base_url=_get_base_url(),
            api_key=_get_api_key(),
        )

    def __call__(self, *args, **kwargs):
        return self.user_func(*args, **kwargs)

    # ---- Substrate-derived properties ----

    @property
    def bucket(self) -> Optional[str]:
        """Object-store URL prefix for SlateDB. `gs://cycls-ws-{name}` in prod,
        else None (file:// local fallback)."""
        return f"gs://cycls-ws-{self.name}" if self.prod and self.name else None

    # ---- FastAPI Depends instances (lazy) ----

    @cached_property
    def auth(self):
        """FastAPI Depends that validates the JWT and yields a User."""
        if self._auth_provider is None:
            raise RuntimeError("App.auth requires auth=... on the @cycls.app decorator")
        from fastapi import Depends
        return Depends(make_validate(
            lambda: self._auth_provider.resolve(self.prod).get("jwks_url")
        ))

    @cached_property
    def workspace(self):
        """FastAPI Depends that yields a per-request `Workspace` for the user."""
        if self._auth_provider is None:
            raise RuntimeError("App.workspace requires auth=... on the @cycls.app decorator")
        from fastapi import Depends
        auth_dep = self.auth
        def _build_ws(user=auth_dep):
            return workspace_for(user, self.volume, self.bucket)
        return Depends(_build_ws)

    @cached_property
    def sandbox(self) -> Sandbox:
        """The configured `Sandbox` for running untrusted commands."""
        if self._sandbox is None:
            raise RuntimeError("App.sandbox requires sandbox=... on the @cycls.app decorator")
        return self._sandbox

    @cached_property
    def signing_key(self) -> bytes:
        """HMAC secret persisted in the deployment's bucket so all pods share
        it across restarts. First boot generates 32 bytes; subsequent reads
        return the same key. Delete the file and redeploy to rotate."""
        path = self.volume / ".cycls" / "signing.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return path.read_bytes()
        key = signing.new_secret()
        path.write_bytes(key)
        return key

    def signed_url(self, path: str, user_id: str, ttl: int = 3600) -> str:
        """Return a signed `/shared?path=&user=&exp=&sig=` URL granting
        access to *path* in *user_id*'s workspace for *ttl* seconds."""
        params = signing.sign(path, user_id, self.signing_key, ttl=ttl)
        return f"/shared?{signing.query_string(params)}"

    def verify_signed(self, path: str, user_id: str, exp, sig: str) -> bool:
        """True if (path, user_id, exp, sig) is a valid, unexpired signature."""
        return signing.verify(path, user_id, exp, sig, self.signing_key)

    # ---- Lifecycle ----

    def _prepare_func(self, prod):
        self.prod = prod
        user_func = self.user_func
        self.func = lambda port: uvicorn.run(user_func(), host="0.0.0.0", port=port)

    def _local(self, port=8080):
        """Run directly with uvicorn (no Docker)."""
        print(f"Starting local server at localhost:{port}")
        self.prod = False
        uvicorn.run(self.user_func(), host="0.0.0.0", port=port)

    def local(self, port=8080, watch=True):
        """Run locally in Docker with file watching by default."""
        if os.environ.get('_CYCLS_WATCH'):
            watch = False
        self._prepare_func(prod=False)
        self.watch(port=port) if watch else self.run(port=port)

    def deploy(self, port=8080, memory=None):
        """Deploy to production."""
        if self.api_key is None:
            raise RuntimeError("Missing API key. Set cycls.api_key or CYCLS_API_KEY environment variable.")
        self._prepare_func(prod=True)
        return super().deploy(port=port, memory=memory or self.memory)


def _make_decorator(cls):
    def factory(name=None, image=None, **kwargs):
        def decorator(func):
            return cls(func=func, name=name or func.__name__, image=image, **kwargs)
        return decorator
    return factory


app = _make_decorator(App)

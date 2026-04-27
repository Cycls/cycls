import os
from pathlib import Path
from typing import Optional

import uvicorn

from cycls.function import Function, _get_api_key, _get_base_url
from cycls.app.auth import JWT, make_validate
from cycls.app.db import workspace_for


class App(Function):
    """App extends Function with a blocking ASGI service.

    The user function, when called, must return an ASGI application
    (e.g., a FastAPI instance, an MCP server, a Gradio/Streamlit app).
    App wraps it in uvicorn for local runs and containerized deployment.

    Pass `auth=cycls.Clerk(...)` to wire JWT validation; `app.auth` and
    `app.workspace` are FastAPI Depends instances usable directly in the
    user's routes — multi-tenant DB and JWT validation come for free.
    """

    _base_pip = ["uvicorn[standard]", "slatedb",
                 "fastapi[standard]", "pyjwt", "cryptography"]
    _base_apt = []

    def __init__(self, func, name, image=None, memory="1Gi", auth: Optional[JWT] = None):
        if auth is not None and not isinstance(auth, JWT):
            raise TypeError(
                f"auth must be a cycls.JWT instance (e.g. cycls.Clerk(...)) or None; "
                f"got {type(auth).__name__}"
            )
        self.user_func = func
        self.memory = memory
        self.prod = False
        self.volume = Path((image or {}).get("volume", "/workspace"))
        self._auth_provider = auth
        self._auth_resolved: Optional[dict] = None

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

    @property
    def auth(self):
        """FastAPI Depends that validates the request's JWT and yields a User.
        Requires `auth=...` at decoration time."""
        if self._auth_provider is None:
            raise RuntimeError("App.auth requires auth=... on the @cycls.app decorator")
        if not hasattr(self, "_auth_dep"):
            from fastapi import Depends
            self._auth_dep = Depends(make_validate(
                lambda: (self._auth_resolved or {}).get("jwks_url")
            ))
        return self._auth_dep

    @property
    def workspace(self):
        """FastAPI Depends that yields a per-request `Workspace` for the
        authenticated user. Requires `auth=...` at decoration time."""
        if self._auth_provider is None:
            raise RuntimeError("App.workspace requires auth=... on the @cycls.app decorator")
        if not hasattr(self, "_workspace_dep"):
            from fastapi import Depends
            auth_dep = self.auth
            def _build_ws(user=auth_dep):
                return workspace_for(user, self.volume, self.bucket)
            self._workspace_dep = Depends(_build_ws)
        return self._workspace_dep

    # ---- Lifecycle ----

    def _resolve_auth(self, prod):
        """Resolve auth provider URLs for the given mode. Subclasses call
        this in their own `_prepare_func` to share the resolution path."""
        if self._auth_provider is not None:
            self._auth_resolved = self._auth_provider.resolve(prod)

    def _prepare_func(self, prod):
        self.prod = prod
        self._resolve_auth(prod)
        user_func = self.user_func
        self.func = lambda port: uvicorn.run(user_func(), host="0.0.0.0", port=port)

    def _local(self, port=8080):
        """Run directly with uvicorn (no Docker)."""
        print(f"Starting local server at localhost:{port}")
        self.prod = False
        self._resolve_auth(False)
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

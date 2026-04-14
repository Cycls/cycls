import os
import uvicorn

from cycls.function import Function, _get_api_key, _get_base_url


class App(Function):
    """App extends Function with a blocking ASGI service.

    The user function, when called, must return an ASGI application
    (e.g., a FastAPI instance, an MCP server, a Gradio/Streamlit app).
    App wraps it in uvicorn for local runs and containerized deployment.
    """

    _base_pip = ["uvicorn[standard]"]
    _base_apt = []

    def __init__(self, func, name, pip=None, apt=None, run_commands=None, copy=None,
                 memory="1Gi", force_rebuild=False):
        self.user_func = func
        self.memory = memory
        self.prod = False

        super().__init__(
            func=func,
            name=name,
            pip=[*self._base_pip, *(pip or [])],
            apt=[*self._base_apt, *(apt or [])],
            run_commands=list(run_commands or []),
            copy=copy or {},
            base_url=_get_base_url(),
            api_key=_get_api_key(),
            force_rebuild=force_rebuild,
        )

    def __call__(self, *args, **kwargs):
        return self.user_func(*args, **kwargs)

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
    def factory(name=None, **kwargs):
        if kwargs.get("plan") == "cycls_pass":
            kwargs["auth"] = True
            kwargs["analytics"] = True

        def decorator(func):
            return cls(func=func, name=name or func.__name__, **kwargs)
        return decorator
    return factory


app = _make_decorator(App)

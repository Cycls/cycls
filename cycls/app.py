import os
import uvicorn
import importlib.resources

from .function import Function, _get_api_key, _get_base_url
from .web import web, Config

CYCLS_PATH = importlib.resources.files('cycls')

THEMES = ["default", "dev"]


class App(Function):
    """App extends Function with web UI serving capabilities."""

    def __init__(self, func, name, theme="default", pip=None, apt=None, copy=None, copy_public=None,
                 auth=False, org=None, header=None, intro=None, title=None, plan="free", analytics=False,
                 state=False):
        if theme not in THEMES:
            raise ValueError(f"Unknown theme: {theme}. Available: {THEMES}")
        self.user_func = func
        self.theme = theme
        self.copy_public = copy_public or []
        self.state = state

        self.config = Config(
            header=header,
            intro=intro,
            title=title,
            auth=auth,
            plan=plan,
            analytics=analytics,
            org=org,
            state=state,
            app_name=name,
        )

        # Add state dependencies if enabled
        if state:
            pip = list(pip or [])
            pip.append("libsql-experimental")

        # Build files dict for Function (theme is inside cycls/)
        files = {str(CYCLS_PATH): "cycls"}
        files.update({f: f for f in copy or []})
        files.update({f: f"public/{f}" for f in self.copy_public})

        super().__init__(
            func=func,
            name=name,
            pip=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", "python-dotenv", "docker", *(pip or [])],
            apt=apt,
            copy=files,
            base_url=_get_base_url(),
            api_key=_get_api_key()
        )

    def __call__(self, *args, **kwargs):
        return self.user_func(*args, **kwargs)

    def _prepare_func(self, prod):
        self.config.set_prod(prod)
        self.config.debug = not prod  # debug=True in local mode
        self.config.public_path = f"cycls/themes/{self.theme}"
        user_func, config, name = self.user_func, self.config, self.name
        self.func = lambda port: __import__("cycls").web.serve(user_func, config, name, port)

    def _local(self, port=8080):
        """Run directly with uvicorn (no Docker)."""
        print(f"Starting local server at localhost:{port}")
        self.config.public_path = str(CYCLS_PATH.joinpath(f"themes/{self.theme}"))
        self.config.set_prod(False)
        self.config.debug = True
        uvicorn.run(web(self.user_func, self.config), host="0.0.0.0", port=port)

    def local(self, port=8080, watch=True):
        """Run locally in Docker with file watching by default."""
        if os.environ.get('_CYCLS_WATCH'):
            watch = False
        self._prepare_func(prod=False)
        self.watch(port=port) if watch else self.run(port=port)

    def deploy(self, port=8080):
        """Deploy to production."""
        if self.api_key is None:
            raise RuntimeError("Missing API key. Set cycls.api_key or CYCLS_API_KEY environment variable.")
        self._prepare_func(prod=True)
        return super().deploy(port=port)


def app(name=None, **kwargs):
    """Decorator that transforms a function into a deployable App."""
    if kwargs.get("plan") == "cycls_pass":
        kwargs["auth"] = True
        kwargs["analytics"] = True

    def decorator(func):
        return App(func=func, name=name or func.__name__, **kwargs)
    return decorator

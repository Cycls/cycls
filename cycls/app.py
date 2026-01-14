import os
import uvicorn
import importlib.resources

from .function import Function, _get_api_key, _get_base_url
from .web import web, Config
from .auth import PK_LIVE, PK_TEST, JWKS_PROD, JWKS_TEST

CYCLS_PATH = importlib.resources.files('cycls')

THEMES = {"default", "dev"}

def _set_prod(config: Config, prod: bool):
    config.prod = prod
    config.pk = PK_LIVE if prod else PK_TEST
    config.jwks = JWKS_PROD if prod else JWKS_TEST


class App(Function):
    """App extends Function with web UI serving capabilities."""

    def __init__(self, func, name, theme="default", pip=None, apt=None, copy=None, copy_public=None,
                 auth=False, org=None, header="", intro="", title="", plan="free", analytics=False):
        if theme not in THEMES:
            raise ValueError(f"Unknown theme: {theme}. Available: {THEMES}")
        self.user_func = func
        self.theme = theme
        self.copy_public = copy_public or []

        self.config = Config(
            header=header,
            intro=intro,
            title=title,
            auth=auth,
            plan=plan,
            analytics=analytics,
            org=org,
        )

        # Build files dict for Function (theme is inside cycls/)
        files = {str(CYCLS_PATH): "cycls"}
        files.update({f: f for f in copy or []})
        files.update({f: f"public/{f}" for f in self.copy_public})

        super().__init__(
            func=func,
            name=name,
            pip=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", *(pip or [])],
            apt=apt,
            copy=files,
            base_url=_get_base_url(),
            api_key=_get_api_key()
        )

    def __call__(self, *args, **kwargs):
        return self.user_func(*args, **kwargs)

    def _prepare_func(self, prod):
        _set_prod(self.config, prod)
        self.config.public_path = f"cycls/{self.theme}-theme"
        user_func, config, name = self.user_func, self.config, self.name
        self.func = lambda port: __import__("cycls.web", fromlist=["serve"]).serve(user_func, config, name, port)

    def _local(self, port=8080):
        """Run directly with uvicorn (no Docker)."""
        print(f"Starting local server at localhost:{port}")
        self.config.public_path = str(CYCLS_PATH.joinpath(f"{self.theme}-theme"))
        _set_prod(self.config, False)
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


def app(name=None, pip=None, apt=None, copy=None, copy_public=None, theme="default",
        auth=False, org=None, header="", intro="", title="", plan="free", analytics=False):
    """Decorator that transforms a function into a deployable App."""
    if plan == "cycls_pass":
        auth = True
        analytics = True

    def decorator(func):
        return App(
            func=func,
            name=name or func.__name__,
            theme=theme,
            pip=pip,
            apt=apt,
            copy=copy,
            copy_public=copy_public,
            auth=auth,
            org=org,
            header=header,
            intro=intro,
            title=title,
            plan=plan,
            analytics=analytics,
        )
    return decorator

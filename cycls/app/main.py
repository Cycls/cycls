import os
import uvicorn
import importlib.resources

from cycls.function import Function, _get_api_key, _get_base_url
from .web import web, Config

CYCLS_PATH = importlib.resources.files('cycls')

THEMES = ["default", "dev"]


class App(Function):
    """App extends Function with web UI serving capabilities."""

    def __init__(self, func, name, theme="default", pip=None, apt=None, run_commands=None, copy=None, copy_public=None,
                 auth=False, header=None, intro=None, title=None, plan="free", analytics=False,
                 memory="1Gi", force_rebuild=False):
        if theme not in THEMES:
            raise ValueError(f"Unknown theme: {theme}. Available: {THEMES}")
        self.user_func = func
        self.theme = theme
        self.copy_public = copy_public or []
        self.memory = memory

        self.config = Config(
            header=header,
            intro=intro,
            title=title,
            auth=auth,
            plan=plan,
            analytics=analytics,

        )

        # Build files dict for Function (theme is inside cycls/)
        files = {str(CYCLS_PATH): "cycls"}
        files.update({f: f for f in copy or []})
        files.update({f: f"public/{f}" for f in self.copy_public})

        # Fetch theme from GitHub releases during container build
        theme_cmd = "mkdir -p /app/cycls/themes/default && cd /app/cycls/themes/default && curl -fsSLO https://github.com/Cycls/agentUI/releases/download/latest/agentUI.zip && unzip -o agentUI.zip && rm agentUI.zip"
        all_run_commands = [theme_cmd, *(run_commands or [])]

        super().__init__(
            func=func,
            name=name,
            pip=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", "python-dotenv", "docker", "anthropic", *(pip or [])],
            apt=["curl", "unzip", *(apt or [])],
            run_commands=all_run_commands,
            copy=files,
            base_url=_get_base_url(),
            api_key=_get_api_key(),
            force_rebuild=force_rebuild
        )

    def __call__(self, *args, **kwargs):
        return self.user_func(*args, **kwargs)

    def _prepare_func(self, prod):
        self.config.set_prod(prod)
        self.config.public_path = f"cycls/themes/{self.theme}"
        user_func, config, name = self.user_func, self.config, self.name
        self.func = lambda port: __import__("cycls.app.web", fromlist=["serve"]).serve(user_func, config, name, port)

    def _local(self, port=8080):
        """Run directly with uvicorn (no Docker)."""
        print(f"Starting local server at localhost:{port}")
        self.config.public_path = str(CYCLS_PATH.joinpath(f"themes/{self.theme}"))
        self.config.set_prod(False)
        uvicorn.run(web(self.user_func, self.config), host="0.0.0.0", port=port)

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


def app(name=None, **kwargs):
    """Decorator that transforms a function into a deployable App."""
    if kwargs.get("plan") == "cycls_pass":
        kwargs["auth"] = True
        kwargs["analytics"] = True

    def decorator(func):
        return App(func=func, name=name or func.__name__, **kwargs)
    return decorator

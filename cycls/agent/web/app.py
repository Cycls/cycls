"""AgentApp — App flavor that serves the Cycls chat product.

Wraps a streaming chat handler in a full FastAPI service: themes, Clerk JWT auth,
sessions, share links, OG images, transcription. Subclasses App by overriding
_build_asgi to construct the chat service ASGI app around the user function.
"""
import importlib.resources

from cycls.app.main import App, _make_decorator
from ..state import install_routers
from .main import web, Config

CYCLS_PATH = importlib.resources.files('cycls')
THEMES = ["default", "dev"]


class AgentApp(App):
    _base_pip = [*App._base_pip, "fastapi[standard]", "pyjwt", "cryptography",
                 "python-dotenv", "resvg-py", "anthropic"]
    _base_apt = [*App._base_apt, "fonts-noto-core", "bubblewrap",
                 "poppler-utils", "ripgrep", "jq"]

    def __init__(self, func, name, theme="default", pip=None, apt=None,
                 run_commands=None, copy=None, copy_public=None,
                 auth=False, header=None, intro=None, title=None,
                 plan="free", analytics=False,
                 memory="1Gi", force_rebuild=False):
        if theme not in THEMES:
            raise ValueError(f"Unknown theme: {theme}. Available: {THEMES}")
        self.theme = theme
        self.copy_public = copy_public or []
        self.config = Config(
            name=name, header=header, intro=intro, title=title,
            auth=auth, plan=plan, analytics=analytics,
        )

        files = {str(CYCLS_PATH): "cycls"}
        files.update({f: f for f in copy or []})
        files.update({f: f"public/{f}" for f in self.copy_public})

        super().__init__(
            func=func,
            name=name,
            pip=pip,
            apt=apt,
            run_commands=run_commands,
            copy=files,
            memory=memory,
            force_rebuild=force_rebuild,
        )

    def _build_asgi(self):
        self.config.set_prod(self.prod)
        self.config.public_path = str(CYCLS_PATH.joinpath(f"agent/web/themes/{self.theme}"))
        return web(self.user_func, self.config, extra_routers=[install_routers])


agent = _make_decorator(AgentApp)

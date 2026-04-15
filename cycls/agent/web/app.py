"""AgentApp — App flavor that serves the Cycls chat product.

Wraps a streaming chat handler in a full FastAPI service: themes, Clerk JWT auth,
sessions, share links, OG images, transcription. Subclasses App by overriding
_build_asgi to construct the chat service ASGI app around the user function.
"""
import importlib.resources

from fastapi import APIRouter

from cycls.app.main import App, _make_decorator
from ..state import install_routers
from .main import web, serve as web_serve, Config

CYCLS_PATH = importlib.resources.files('cycls')
THEMES = ["default", "dev"]


class AgentApp(App):
    _base_pip = [*App._base_pip, "fastapi[standard]", "pyjwt", "cryptography",
                 "python-dotenv", "resvg-py", "anthropic", "openai"]
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
        self.server = APIRouter()
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

    def _prepare_func(self, prod):
        self.prod = prod
        self.config.set_prod(prod)
        self.config.public_path = f"cycls/agent/web/themes/{self.theme}"
        user_func, config, name, server = self.user_func, self.config, self.name, self.server
        routers = [install_routers, lambda app, auth: app.include_router(server)]
        self.func = lambda port: web_serve(
            user_func, config, name, port, extra_routers=routers)

    def _local(self, port=8080):
        print(f"Starting local server at localhost:{port}")
        self.prod = False
        self.config.set_prod(False)
        self.config.public_path = str(CYCLS_PATH.joinpath(f"agent/web/themes/{self.theme}"))
        server = self.server
        routers = [install_routers, lambda app, auth: app.include_router(server)]
        import uvicorn
        uvicorn.run(web(self.user_func, self.config, extra_routers=routers),
                    host="0.0.0.0", port=port)


agent = _make_decorator(AgentApp)

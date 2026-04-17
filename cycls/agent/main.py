"""Agent — App flavor that serves the Cycls chat product.

Wraps a streaming chat handler in a full FastAPI service: themes, Clerk JWT auth,
sessions, share links, OG images, transcription. Subclasses App and composes its
chat-product ASGI app via the existing extra_routers hook.
"""
import importlib.resources

from fastapi import APIRouter

from cycls.app.main import App, _make_decorator
from cycls.app.auth import make_validate, JWT
from cycls.app.web import Web
from .state import install_routers
from .web import web, serve as web_serve, Config

CYCLS_PATH = importlib.resources.files('cycls')


class Agent(App):
    _base_pip = [*App._base_pip, "fastapi[standard]", "pyjwt", "cryptography",
                 "python-dotenv", "resvg-py", "anthropic", "openai"]
    _base_apt = [*App._base_apt, "fonts-noto-core", "bubblewrap",
                 "poppler-utils", "ripgrep", "jq", "curl"]

    def __init__(self, func, name, web=None, image=None, memory="1Gi"):
        if web is None:
            web = Web()
        self.theme = web._theme
        self.copy_public = web._copy_public
        self.server = APIRouter()
        self._auth_provider = web._auth
        self.config = Config(
            name=name, title=web._title,
            auth=web._auth is not None, cycls_pass=web._cycls_pass, analytics=web._analytics,
            volume=(image or {}).get("volume", "/workspace"),
        )
        self.auth = make_validate(self.config)

        # Merge Agent's own copy requirements into the image:
        # cycls source tree (for themes + internal imports) and Web's
        # copy_public files routed under public/.
        image = dict(image or {})
        user_copy = image.get("copy", {})
        if isinstance(user_copy, list):
            user_copy = {f: f for f in user_copy}
        image["copy"] = {
            str(CYCLS_PATH): "cycls",
            **user_copy,
            **{f: f"public/{f}" for f in self.copy_public},
        }

        super().__init__(
            func=func,
            name=name,
            image=image,
            memory=memory,
        )

    def _apply_auth(self, prod):
        """Resolve the auth provider's URLs/keys for this runtime mode into
        config. Called after set_prod so the right dev/prod values land."""
        if self._auth_provider is None:
            return
        resolved = self._auth_provider.resolve(prod)
        self.config.jwks = resolved.get("jwks_url")
        if "pk" in resolved:
            self.config.pk = resolved["pk"]

    def _routers(self):
        """State routers (sessions, files, share) require auth to be meaningful.
        Agents without auth skip them entirely — no silent 401s on unused endpoints."""
        server = self.server
        routers = [lambda app, auth: app.include_router(server)]
        if self._auth_provider is not None:
            routers.insert(0, install_routers)
        return routers

    def _prepare_func(self, prod):
        self.prod = prod
        self.config.set_prod(prod)
        self._apply_auth(prod)
        self.config.public_path = f"cycls/agent/web/themes/{self.theme}"
        user_func, config, name = self.user_func, self.config, self.name
        routers = self._routers()
        self.func = lambda port: web_serve(
            user_func, config, name, port, extra_routers=routers)

    def _local(self, port=8080):
        print(f"Starting local server at localhost:{port}")
        self.prod = False
        self.config.set_prod(False)
        self._apply_auth(False)
        self.config.public_path = str(CYCLS_PATH.joinpath(f"agent/web/themes/{self.theme}"))
        import uvicorn
        uvicorn.run(web(self.user_func, self.config, extra_routers=self._routers()),
                    host="0.0.0.0", port=port)


agent = _make_decorator(Agent)

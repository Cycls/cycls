"""Agent — App flavor that serves the Cycls chat product.

Wraps a streaming chat handler in a full FastAPI service: themes, Clerk JWT auth,
sessions, share links, OG images, transcription. Subclasses App and composes its
chat-product ASGI app via the existing extra_routers hook.
"""
import importlib.resources
from pathlib import Path

from fastapi import APIRouter

from cycls.app.main import App, _make_decorator
from .web.routers import install_routers
from .web import Web, web, serve as web_serve, Config

CYCLS_PATH = importlib.resources.files('cycls')


class Agent(App):
    _base_pip = [*App._base_pip, "resvg-py", "anthropic", "openai", "python-dotenv"]
    _base_apt = [*App._base_apt, "fonts-noto-core",
                 "poppler-utils", "ripgrep", "jq", "curl"]

    def __init__(self, func, name, web=None, image=None, memory="1Gi"):
        if web is None:
            web = Web()
        self.theme = web._theme
        self.copy_public = web._copy_public
        self.server = APIRouter()
        self.config = Config(
            name=name, title=web._title,
            auth=web._auth is not None, cms=web._cms, analytics=web._analytics,
            volume=(image or {}).get("volume", "/workspace"),
        )

        # Merge Web's copy_public files under public/. App.__init__ adds
        # the cycls source tree on top.
        image = dict(image or {})
        image["copy"] = {**image.get("copy", {}), **{f: f"public/{f}" for f in self.copy_public}}

        super().__init__(
            func=func,
            name=name,
            image=image,
            memory=memory,
            auth=web._auth,
        )
        self.config.name = self.name

    def _sync_config_pk(self, prod):
        if self._auth_provider is None:
            return
        resolved = self._auth_provider.resolve(prod)
        if "pk" in resolved:
            self.config.pk = resolved["pk"]

    def _routers(self):
        """State routers (chats, files, share) require auth to be meaningful.
        Agents without auth skip them entirely — no silent 401s on unused endpoints."""
        server = self.server
        routers = [lambda app, auth: app.include_router(server)]
        if self._auth_provider is not None:
            cycls_app = self
            volume = Path(self.config.volume)
            storage = self.storage
            routers.insert(0, lambda app, auth: install_routers(cycls_app, app, auth, volume, storage))
        return routers

    def _prepare_func(self, prod):
        self.prod = prod
        self._sync_config_pk(prod)
        self.config.set_prod(prod)
        self.config.public_path = f"cycls/agent/web/themes/{self.theme}"
        user_func, config, name = self.user_func, self.config, self.name
        routers = self._routers()
        provider = self._auth_provider
        self.func = lambda port: web_serve(
            user_func, config, name, port, extra_routers=routers, auth=provider)

    def _local(self, port=8080):
        print(f"Starting local server at localhost:{port}")
        self.prod = False
        self._sync_config_pk(False)
        self.config.set_prod(False)
        self.config.public_path = str(CYCLS_PATH.joinpath(f"agent/web/themes/{self.theme}"))
        import uvicorn
        uvicorn.run(web(self.user_func, self.config, extra_routers=self._routers(),
                        auth=self._auth_provider),
                    host="0.0.0.0", port=port)


agent = _make_decorator(Agent)

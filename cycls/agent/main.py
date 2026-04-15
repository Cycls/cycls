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
                 "poppler-utils", "ripgrep", "jq"]

    def __init__(self, func, name, web=None, pip=None, apt=None,
                 run_commands=None, copy=None, memory="1Gi", force_rebuild=False,
                 # Chat config sugar — equivalent to cycls.Web().<method>(...).
                 # Mutually exclusive with web=.
                 auth=None, title=None, theme=None, plan=None,
                 analytics=None, copy_public=None):
        if web is not None and any(v is not None for v in (auth, title, theme, plan, analytics, copy_public)):
            raise TypeError(
                "Pass chat config via `web=cycls.Web()...` OR individual kwargs "
                "(auth/title/theme/plan/analytics/copy_public), not both."
            )
        if web is None:
            web = Web()
            if auth is not None:      web = web.auth(auth)
            if title is not None:     web = web.title(title)
            if theme is not None:     web = web.theme(theme)
            if plan is not None:      web = web.plan(plan)
            if analytics is not None: web = web.analytics(analytics)
            if copy_public is not None: web = web.copy_public(*copy_public)

        self.theme = web._theme
        self.copy_public = web._copy_public
        self.server = APIRouter()
        self._auth_provider = web._auth
        self.config = Config(
            name=name, title=web._title,
            auth=web._auth is not None, plan=web._plan, analytics=web._analytics,
        )
        self.auth = make_validate(self.config)

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

    def _apply_auth(self, prod):
        """Resolve the auth provider's URLs/keys for this runtime mode into
        config. Called after set_prod so the right dev/prod values land."""
        if self._auth_provider is None:
            return
        resolved = self._auth_provider.resolve(prod)
        self.config.jwks = resolved.get("jwks_url")
        if "pk" in resolved:
            self.config.pk = resolved["pk"]

    def _prepare_func(self, prod):
        self.prod = prod
        self.config.set_prod(prod)
        self._apply_auth(prod)
        self.config.public_path = f"cycls/agent/web/themes/{self.theme}"
        user_func, config, name, server = self.user_func, self.config, self.name, self.server
        routers = [install_routers, lambda app, auth: app.include_router(server)]
        self.func = lambda port: web_serve(
            user_func, config, name, port, extra_routers=routers)

    def _local(self, port=8080):
        print(f"Starting local server at localhost:{port}")
        self.prod = False
        self.config.set_prod(False)
        self._apply_auth(False)
        self.config.public_path = str(CYCLS_PATH.joinpath(f"agent/web/themes/{self.theme}"))
        server = self.server
        routers = [install_routers, lambda app, auth: app.include_router(server)]
        import uvicorn
        uvicorn.run(web(self.user_func, self.config, extra_routers=routers),
                    host="0.0.0.0", port=port)


agent = _make_decorator(Agent)

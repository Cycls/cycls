import os
import time
import uvicorn
import importlib.resources

from .function import Function, _get_api_key, _get_base_url
from .web import web, Config
from .auth import PK_LIVE, PK_TEST, JWKS_PROD, JWKS_TEST

CYCLS_PATH = importlib.resources.files('cycls')

THEMES = {
    "default": CYCLS_PATH.joinpath('default-theme'),
    "dev": CYCLS_PATH.joinpath('dev-theme'),
}

def _resolve_theme(theme):
    if isinstance(theme, str):
        if theme in THEMES:
            return THEMES[theme]
        raise ValueError(f"Unknown theme: {theme}. Available: {list(THEMES.keys())}")
    return theme

def _set_prod(config: Config, prod: bool):
    config.prod = prod
    config.pk = PK_LIVE if prod else PK_TEST
    config.jwks = JWKS_PROD if prod else JWKS_TEST


class Agent(Function):
    """Agent extends Function with web UI serving capabilities."""

    def __init__(self, func, name, theme="default", pip=None, apt=None, copy=None, copy_public=None,
                 modal_keys=None, auth=False, org=None, domain=None, header="", intro="", title="",
                 plan="free", analytics=False):
        self.user_func = func
        self.theme = _resolve_theme(theme)
        self.copy_public = copy_public or []
        self.modal_keys = modal_keys or ["", ""]
        self.domain = domain or f"{name}.cycls.ai"
        self._pip = pip or []

        self.config = Config(
            header=header,
            intro=intro,
            title=title,
            auth=auth,
            plan=plan,
            analytics=analytics,
            org=org,
        )

        # Build files dict for Function
        files = {str(self.theme): "theme", str(CYCLS_PATH)+"/web.py": "web.py"}
        files.update({f: f for f in copy or []})
        files.update({f: f"public/{f}" for f in self.copy_public})

        super().__init__(
            func=func,
            name=name,
            pip_packages=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", *self._pip],
            apt_packages=apt,
            copy=files,
            base_url=_get_base_url(),
            api_key=_get_api_key()
        )

    def __call__(self, *args, **kwargs):
        return self.user_func(*args, **kwargs)

    def _prepare_func(self, prod):
        _set_prod(self.config, prod)
        config_dict = self.config.model_dump()
        user_func = self.user_func
        name = self.name
        self.func = lambda port: __import__("web").serve(user_func, config_dict, name, port)

    def _local(self, port=8080):
        """Run directly with uvicorn (no Docker)."""
        print(f"Starting local server at localhost:{port}")
        self.config.public_path = self.theme
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

    def modal(self, prod=False):
        import modal
        from modal.runner import run_app

        user_func = self.user_func
        name = self.name
        domain = self.domain

        client = modal.Client.from_credentials(*self.modal_keys)
        image = (modal.Image.debian_slim()
                            .pip_install("fastapi[standard]", "pyjwt", "cryptography", *self._pip)
                            .apt_install(*self.apt_packages)
                            .add_local_dir(self.theme, "/root/theme")
                            .add_local_file(str(CYCLS_PATH)+"/web.py", "/root/web.py"))

        for src, dst in self.copy.items():
            if dst not in ("theme", "web.py") and not dst.startswith("public/"):
                image = image.add_local_file(src, f"/root/{dst}") if "." in src else image.add_local_dir(src, f'/root/{dst}')

        for item in self.copy_public:
            image = image.add_local_file(item, f"/root/public/{item}") if "." in item else image.add_local_dir(item, f'/root/public/{item}')

        app = modal.App("development", image=image)

        _set_prod(self.config, prod)
        config_dict = self.config.model_dump()

        app.function(serialized=True, name=name)(
            modal.asgi_app(label=name, custom_domains=[domain])
            (lambda: __import__("web").web(user_func, config_dict))
        )

        if prod:
            print(f"Deployed to => https://{domain}")
            app.deploy(client=client, name=name)
        else:
            with modal.enable_output():
                run_app(app=app, client=client)
                print("Modal development server is running. Press Ctrl+C to stop.")
                with modal.enable_output(), run_app(app=app, client=client):
                    while True: time.sleep(10)


def agent(name=None, pip=None, apt=None, copy=None, copy_public=None, theme="default",
          modal_keys=None, auth=False, org=None, domain=None, header="", intro="",
          title="", plan="free", analytics=False):
    """Decorator that transforms a function into a deployable Agent."""
    if plan == "cycls_pass":
        auth = True
        analytics = True

    def decorator(func):
        agent_name = name or func.__name__.replace('_', '-')
        return Agent(
            func=func,
            name=agent_name,
            theme=theme,
            pip=pip,
            apt=apt,
            copy=copy,
            copy_public=copy_public,
            modal_keys=modal_keys,
            auth=auth,
            org=org,
            domain=domain,
            header=header,
            intro=intro,
            title=title,
            plan=plan,
            analytics=analytics,
        )
    return decorator

"""App module - streaming chat applications."""

import os
import time
import uvicorn
import importlib.resources

from .runtime import Runtime
from .web import web, Config
from .auth import PK_LIVE, PK_TEST, JWKS_PROD, JWKS_TEST

CYCLS_PATH = importlib.resources.files('cycls')

# Module-level configuration
api_key = None
base_url = None

def _get_api_key():
    """Get API key from module variable or environment variable (lazy)."""
    return api_key or os.getenv("CYCLS_API_KEY")

def _get_base_url():
    """Get base URL from module variable or environment variable (lazy)."""
    return base_url or os.getenv("CYCLS_BASE_URL")

themes = {
    "default": CYCLS_PATH.joinpath('default-theme'),
    "dev": CYCLS_PATH.joinpath('dev-theme'),
}

def _resolve_theme(theme):
    """Resolve theme - accepts string name or path"""
    if isinstance(theme, str):
        if theme in themes:
            return themes[theme]
        raise ValueError(f"Unknown theme: {theme}. Available: {list(themes.keys())}")
    return theme

def _set_prod(config: Config, prod: bool):
    config.prod = prod
    config.pk = PK_LIVE if prod else PK_TEST
    config.jwks = JWKS_PROD if prod else JWKS_TEST


class AppRuntime:
    """Wraps an app function with local/deploy/modal capabilities."""

    def __init__(self, func, name, theme, pip, apt, copy, copy_public, modal_keys, auth, org, domain, header, intro, title, plan, analytics):
        self.func = func
        self.name = name
        self.theme = _resolve_theme(theme)
        self.pip = pip
        self.apt = apt
        self.copy = copy
        self.copy_public = copy_public
        self.modal_keys = modal_keys
        self.domain = domain or f"{name}.cycls.ai"

        self.config = Config(
            header=header,
            intro=intro,
            title=title,
            auth=auth,
            plan=plan,
            analytics=analytics,
            org=org,
        )

    def __call__(self, *args, **kwargs):
        """Make the runtime callable - delegates to the wrapped function."""
        return self.func(*args, **kwargs)

    def _local(self, port=8080):
        """Run directly with uvicorn (no Docker)."""
        print(f"Starting local server at localhost:{port}")
        self.config.public_path = self.theme
        _set_prod(self.config, False)
        uvicorn.run(web(self.func, self.config), host="0.0.0.0", port=port)

    def _runtime(self, prod=False):
        """Create a Runtime instance for deployment."""
        _set_prod(self.config, prod)
        config_dict = self.config.model_dump()

        func = self.func
        name = self.name

        files = {str(self.theme): "theme", str(CYCLS_PATH)+"/web.py": "web.py"}
        files.update({f: f for f in self.copy})
        files.update({f: f"public/{f}" for f in self.copy_public})

        return Runtime(
            func=lambda port: __import__("web").serve(func, config_dict, name, port),
            name=name,
            apt_packages=self.apt,
            pip_packages=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", *self.pip],
            copy=files,
            base_url=_get_base_url(),
            api_key=_get_api_key()
        )

    def local(self, port=8080, watch=True):
        """Run locally in Docker with file watching by default."""
        if os.environ.get('_CYCLS_WATCH'):
            watch = False
        runtime = self._runtime(prod=False)
        runtime.watch(port=port) if watch else runtime.run(port=port)

    def deploy(self, port=8080):
        """Deploy to production."""
        key = _get_api_key()
        if key is None:
            raise RuntimeError("Missing API key. Set cycls.api_key or CYCLS_API_KEY environment variable.")
        runtime = self._runtime(prod=True)
        return runtime.deploy(port=port)

    def modal(self, prod=False):
        import modal
        from modal.runner import run_app

        func = self.func
        name = self.name
        domain = self.domain

        client = modal.Client.from_credentials(*self.modal_keys)
        image = (modal.Image.debian_slim()
                            .pip_install("fastapi[standard]", "pyjwt", "cryptography", *self.pip)
                            .apt_install(*self.apt)
                            .add_local_dir(self.theme, "/root/theme")
                            .add_local_file(str(CYCLS_PATH)+"/web.py", "/root/web.py"))

        for item in self.copy:
            image = image.add_local_file(item, f"/root/{item}") if "." in item else image.add_local_dir(item, f'/root/{item}')

        for item in self.copy_public:
            image = image.add_local_file(item, f"/root/public/{item}") if "." in item else image.add_local_dir(item, f'/root/public/{item}')

        app = modal.App("development", image=image)

        _set_prod(self.config, prod)
        config_dict = self.config.model_dump()

        app.function(serialized=True, name=name)(
            modal.asgi_app(label=name, custom_domains=[domain])
            (lambda: __import__("web").web(func, config_dict))
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


def app(name=None, pip=None, apt=None, copy=None, copy_public=None, theme="default", modal_keys=None, auth=False, org=None, domain=None, header="", intro="", title="", plan="free", analytics=False):
    """Decorator that transforms a function into a deployable app."""
    pip = pip or []
    apt = apt or []
    copy = copy or []
    copy_public = copy_public or []
    modal_keys = modal_keys or ["", ""]

    if plan == "cycls_pass":
        auth = True
        analytics = True

    def decorator(func):
        app_name = name or func.__name__.replace('_', '-')
        return AppRuntime(
            func=func,
            name=app_name,
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

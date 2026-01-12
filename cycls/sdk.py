import os, time, uvicorn
from .runtime import Runtime
from .web import web, Config
from .auth import PK_LIVE, PK_TEST, JWKS_PROD, JWKS_TEST
import importlib.resources

CYCLS_PATH = importlib.resources.files('cycls')

# Module-level configuration
api_key = None
base_url = None

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

class AgentRuntime:
    """Wraps an agent function with local/deploy/modal capabilities."""

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

        # Extract to local variables to avoid capturing self in lambda (cloudpickle issue)
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
            base_url=base_url,
            api_key=api_key
        )

    def local(self, port=8080, watch=True):
        """Run locally in Docker with file watching by default."""
        if os.environ.get('_CYCLS_WATCH'):
            watch = False
        runtime = self._runtime(prod=False)
        runtime.watch(port=port) if watch else runtime.run(port=port)

    def deploy(self, port=8080):
        """Deploy to production."""
        if api_key is None:
            raise RuntimeError("Missing API key. Set cycls.api_key before calling deploy().")
        runtime = self._runtime(prod=True)
        return runtime.deploy(port=port)

    def modal(self, prod=False):
        import modal
        from modal.runner import run_app

        # Extract to local variables to avoid capturing self in lambda
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


def agent(name=None, pip=None, apt=None, copy=None, copy_public=None, theme="default", modal_keys=None, auth=False, org=None, domain=None, header="", intro="", title="", plan="free", analytics=False):
    """Decorator that transforms a function into a deployable agent."""
    pip = pip or []
    apt = apt or []
    copy = copy or []
    copy_public = copy_public or []
    modal_keys = modal_keys or ["", ""]

    if plan == "cycls_pass":
        auth = True
        analytics = True

    def decorator(func):
        agent_name = name or func.__name__.replace('_', '-')
        return AgentRuntime(
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

def function(python_version=None, pip=None, apt=None, run_commands=None, copy=None, name=None):
    """Decorator that transforms a Python function into a containerized, remotely executable object."""
    def decorator(func):
        func_name = name or func.__name__
        copy_dict = {i: i for i in copy or []}
        return Runtime(func, func_name.replace('_', '-'), python_version, pip, apt, run_commands, copy_dict, base_url, api_key)
    return decorator
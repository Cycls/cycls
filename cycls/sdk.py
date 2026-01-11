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


def function(python_version=None, pip=None, apt=None, run_commands=None, copy=None, name=None):
    """Decorator that transforms a Python function into a containerized, remotely executable object."""
    def decorator(func):
        func_name = name or func.__name__
        copy_dict = {i: i for i in copy or []}
        return Runtime(func, func_name.replace('_', '-'), python_version, pip, apt, run_commands, copy_dict, base_url, api_key)
    return decorator


class AgentRuntime:
    """Wraps an agent function with local/deploy/modal capabilities."""

    def __init__(self, func, name, theme, pip, apt, copy, copy_public, modal_keys, auth, org, domain, header, intro, title, tier, analytics):
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
            tier=tier,
            analytics=analytics,
            org=org,
        )

    def __call__(self, *args, **kwargs):
        """Make the runtime callable - delegates to the wrapped function."""
        return self.func(*args, **kwargs)

    def _local(self, port=8080, watch=True):
        """Run directly with uvicorn (no Docker)."""
        print(f"Starting local server at localhost:{port}")
        self.config.public_path = self.theme
        _set_prod(self.config, False)
        uvicorn.run(web(self.func, self.config), host="0.0.0.0", port=port, reload=watch)

    def _runtime(self, prod=False):
        """Create a Runtime instance for deployment."""
        _set_prod(self.config, prod)
        config_dict = self.config.model_dump()

        files = {str(self.theme): "theme", str(CYCLS_PATH)+"/web.py": "web.py"}
        files.update({f: f for f in self.copy})
        files.update({f: f"public/{f}" for f in self.copy_public})

        return Runtime(
            func=lambda port: __import__("web").serve(self.func, config_dict, self.name, port),
            name=self.name,
            apt_packages=self.apt,
            pip_packages=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", *self.pip],
            copy=files,
            base_url=base_url,
            api_key=api_key
        )

    def local(self, port=8080, watch=True):
        """Run locally in Docker with file watching by default."""
        if os.environ.get('_CYCLS_WATCH_CHILD'):
            watch = False
        runtime = self._runtime(prod=False)
        runtime.watch(port=port) if watch else runtime.run(port=port)

    def deploy(self, port=8080):
        """Deploy to production."""
        if api_key is None:
            print("Error: Please set cycls.api_key")
            return
        runtime = self._runtime(prod=True)
        runtime.deploy(port=port)

    def modal(self, prod=False):
        import modal
        from modal.runner import run_app

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

        app.function(serialized=True, name=self.name)(
            modal.asgi_app(label=self.name, custom_domains=[self.domain])
            (lambda: __import__("web").web(self.func, config_dict))
        )

        if prod:
            print(f"Deployed to => https://{self.domain}")
            app.deploy(client=client, name=self.name)
        else:
            with modal.enable_output():
                run_app(app=app, client=client)
                print("Modal development server is running. Press Ctrl+C to stop.")
                with modal.enable_output(), run_app(app=app, client=client):
                    while True: time.sleep(10)


def agent(name=None, pip=[], apt=[], copy=[], copy_public=[], theme="default", modal_keys=["", ""], auth=False, org=None, domain=None, header="", intro="", title="", tier="free", analytics=False):
    """Decorator that transforms an async function into a deployable agent."""
    if tier == "cycls_pass":
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
            tier=tier,
            analytics=analytics,
        )
    return decorator


# Keep Agent class for backwards compatibility (deprecated)
class Agent:
    def __init__(self, theme="default", org=None, api_token=None, pip=[], apt=[], copy=[], copy_public=[], modal_keys=["",""], key=None, base_url=None):
        import warnings
        warnings.warn("Agent class is deprecated. Use @cycls.agent decorator instead.", DeprecationWarning, stacklevel=2)
        self.org, self.api_token = org, api_token
        self.theme = _resolve_theme(theme)
        self._key, self.modal_keys, self.pip, self.apt, self.copy, self.copy_public = key, modal_keys, pip, apt, copy, copy_public
        self._base_url = base_url
        self.registered_functions = []

    def __call__(self, name=None, header="", intro="", title="", domain=None, auth=False, tier="free", analytics=False):
        if tier=="cycls_pass":
            auth=True
            analytics=True
        def decorator(f):
            agent_name = name or f.__name__.replace('_', '-')
            runtime = AgentRuntime(
                func=f,
                name=agent_name,
                theme=self.theme,
                pip=self.pip,
                apt=self.apt,
                copy=self.copy,
                copy_public=self.copy_public,
                modal_keys=self.modal_keys,
                auth=auth,
                org=self.org,
                domain=domain,
                header=header,
                intro=intro,
                title=title,
                tier=tier,
                analytics=analytics,
            )
            self.registered_functions.append(runtime)
            return f
        return decorator

    def _local(self, port=8080, watch=True):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        self.registered_functions[0]._local(port=port, watch=watch)

    def local(self, port=8080, watch=True):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        self.registered_functions[0].local(port=port, watch=watch)

    def deploy(self, port=8080):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        if self._key:
            global api_key
            api_key = self._key
        self.registered_functions[0].deploy(port=port)

    def modal(self, prod=False):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        self.registered_functions[0].modal(prod=prod)

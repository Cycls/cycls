import time, inspect, uvicorn
from .runtime import Runtime
from .web import web, Config
from .auth import PK_LIVE, PK_TEST, JWKS_PROD, JWKS_TEST
import importlib.resources
from pydantic import BaseModel
from typing import Callable

CYCLS_PATH = importlib.resources.files('cycls')

class RegisteredAgent(BaseModel):
    func: Callable
    name: str
    domain: str
    config: Config

def set_prod(config: Config, prod: bool):
    config.prod = prod
    config.pk = PK_LIVE if prod else PK_TEST
    config.jwks = JWKS_PROD if prod else JWKS_TEST

themes = {
    "default": CYCLS_PATH.joinpath('default-theme'),
    "dev": CYCLS_PATH.joinpath('dev-theme'),
}

def resolve_theme(theme):
    """Resolve theme - accepts string name or path"""
    if isinstance(theme, str):
        if theme in themes:
            return themes[theme]
        raise ValueError(f"Unknown theme: {theme}. Available: {list(themes.keys())}")
    return theme

def function(python_version=None, pip=None, apt=None, run_commands=None, copy=None, name=None, base_url=None, key=None):
    # """
    # A decorator factory that transforms a Python function into a containerized,
    # remotely executable object.
    def decorator(func):
        Name = name or func.__name__
        copy_dict = {i:i for i in copy or []}
        return Runtime(func, Name.replace('_', '-'), python_version, pip, apt, run_commands, copy_dict, base_url, key)
    return decorator

class Agent:
    def __init__(self, theme="default", org=None, api_token=None, pip=[], apt=[], copy=[], copy_public=[], modal_keys=["",""], key=None, base_url=None):
        self.org, self.api_token = org, api_token
        self.theme = resolve_theme(theme)
        self.key, self.modal_keys, self.pip, self.apt, self.copy, self.copy_public = key, modal_keys, pip, apt, copy, copy_public
        self.base_url = base_url

        self.registered_functions = []

    def __call__(self, name=None, header="", intro="", title="", domain=None, auth=False, tier="free", analytics=False):
        if tier=="cycls_pass":
            auth=True
            analytics=True
        def decorator(f):
            agent_name = name or f.__name__.replace('_', '-')
            self.registered_functions.append(RegisteredAgent(
                func=f,
                name=agent_name,
                domain=domain or f"{agent_name}.cycls.ai",
                config=Config(
                    header=header,
                    intro=intro,
                    title=title,
                    auth=auth,
                    tier=tier,
                    analytics=analytics,
                    org=self.org,
                ),
            ))
            return f
        return decorator

    def local(self, port=8080):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return

        agent = self.registered_functions[0]
        if len(self.registered_functions) > 1:
            print(f"⚠️  Warning: Multiple agents found. Running '{agent.name}'.")
        print(f"🚀 Starting local server at localhost:{port}")
        agent.config.public_path = self.theme
        set_prod(agent.config, False)
        uvicorn.run(web(agent.func, agent.config), host="0.0.0.0", port=port)
        return

    def deploy(self, prod=False, port=8080, watch=False):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        if (self.key is None) and prod:
            print("🛑  Error: Please add your Cycls API key")
            return
        if prod and watch:
            print("⚠️  Warning: watch=True ignored in production mode.")
            watch = False

        agent = self.registered_functions[0]
        if len(self.registered_functions) > 1:
            print(f"⚠️  Warning: Multiple agents found. Running '{agent.name}'.")

        set_prod(agent.config, prod)
        func = agent.func
        name = agent.name
        config_dict = agent.config.model_dump()

        files = {str(self.theme): "theme", str(CYCLS_PATH)+"/web.py": "web.py"}
        files.update({f: f for f in self.copy})
        files.update({f: f"public/{f}" for f in self.copy_public})

        new = Runtime(
            func=lambda port: __import__("web").serve(func, config_dict, name, port),
            name=name,
            apt_packages=self.apt,
            pip_packages=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", *self.pip],
            copy=files,
            base_url=self.base_url,
            api_key=self.key
        )
        if prod:
            new.deploy(port=port)
        elif watch:
            new.watch(port=port)
        else:
            new.run(port=port)
        return
        
    def modal(self, prod=False):
        import modal
        from modal.runner import run_app
        self.client = modal.Client.from_credentials(*self.modal_keys)
        image = (modal.Image.debian_slim()
                            .pip_install("fastapi[standard]", "pyjwt", "cryptography", *self.pip)
                            .apt_install(*self.apt)
                            .add_local_dir(self.theme, "/root/theme")
                            .add_local_file(str(CYCLS_PATH)+"/web.py", "/root/web.py"))
       
        for item in self.copy:
            image = image.add_local_file(item, f"/root/{item}") if "." in item else image.add_local_dir(item, f'/root/{item}')
        
        for item in self.copy_public:
            image = image.add_local_file(item, f"/root/public/{item}") if "." in item else image.add_local_dir(item, f'/root/public/{item}')

        self.app = modal.App("development", image=image)
    
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return

        for agent in self.registered_functions:
            set_prod(agent.config, prod)
            func = agent.func
            name = agent.name
            domain = agent.domain
            config_dict = agent.config.model_dump()
            self.app.function(serialized=True, name=name)(
                modal.asgi_app(label=name, custom_domains=[domain])
                (lambda: __import__("web").web(func, config_dict))
            )
        if prod:
            for agent in self.registered_functions:
                print(f"✅ Deployed to ⇒ https://{agent.domain}")
            self.app.deploy(client=self.client, name=self.registered_functions[0].name)
            return
        else:
            with modal.enable_output():
                run_app(app=self.app, client=self.client)
                print(" Modal development server is running. Press Ctrl+C to stop.")
                with modal.enable_output(), run_app(app=self.app, client=self.client):
                    while True: time.sleep(10)

# docker system prune -af
# poetry config pypi-token.pypi <your-token>
# poetry run python cake.py
# poetry publish --build
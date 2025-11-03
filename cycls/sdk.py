import json, time, modal, inspect, uvicorn
from .runtime import Runtime
from modal.runner import run_app
from .web import web
import importlib.resources
from pathlib import Path

theme_path = importlib.resources.files('cycls').joinpath('theme')
cycls_path = importlib.resources.files('cycls')

class Agent:
    def __init__(self, theme=theme_path, org=None, api_token=None, pip=[], apt=[], copy=[], keys=["",""], api_key=None):
        self._validate_theme(theme)
        self.org, self.api_token = org, api_token
        self.theme = theme
        self.keys, self.pip, self.apt, self.copy = keys, pip, apt, copy
        self.api_key = api_key

        self.registered_functions = []

    def _validate_theme(self, theme):
        """Validate theme folder has required files"""
        theme_path = Path(theme)

        # Check if theme folder exists
        if not theme_path.exists():
            raise FileNotFoundError(
                f"\n❌ Theme folder not found: {theme_path}\n"
                f"   Please provide a valid theme directory.\n"
                f"   Make sure the folder exists."
            )

        # Check if index.html exists
        index_file = theme_path / "index.html"
        if not index_file.exists():
            raise FileNotFoundError(
                f"\n❌ index.html not found in theme folder\n"
                f"   Theme path: {theme_path}\n"
                f"   Expected file: {index_file}\n"
                f"   \n"
                f"   Required theme structure:\n"
                f"   {theme_path}/\n"
                f"   ├── index.html\n"
                f"   └── assets/\n"
                f"       └── index-*.js"
            )

        # Check if assets folder has JavaScript files
        assets_dir = theme_path / "assets"
        if not assets_dir.exists():
            print(f"\n⚠️  Warning: assets folder not found in {theme_path}")
            print(f"   Frontend may not work properly")
        else:
            js_files = list(assets_dir.glob("*.js"))
            if not js_files:
                print(f"\n⚠️  Warning: No JavaScript files found in {assets_dir}")
                print(f"   Frontend may not work properly")

    def __call__(self, name=None, header="", intro="", domain=None, auth=False):
        def decorator(f):
            self.registered_functions.append({
                "func": f,
                "config": ["public", False, self.org, self.api_token, header, intro, auth],
                # "name": name,
                "name": name or (f.__name__).replace('_', '-'),
                "domain": domain or f"{name}.cycls.ai",
            })
            return f
        return decorator

    def run(self, port=8080):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        
        i = self.registered_functions[0]
        if len(self.registered_functions) > 1:
            print(f"⚠️  Warning: Multiple agents found. Running '{i['name']}'.")
        print(f"🚀 Starting local server at localhost:{port}")
        i["config"][0], i["config"][6] = self.theme, False
        uvicorn.run(web(i["func"], *i["config"]), host="0.0.0.0", port=port)
        return

    def cycls(self, prod=False, port=8080):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        if (self.api_key is None) and prod:
            print("🛑  Error: Please add your Cycls API key")
            return

        i = self.registered_functions[0]
        if len(self.registered_functions) > 1:
            print(f"⚠️  Warning: Multiple agents found. Running '{i['name']}'.")

        i["config"][6] = False

        # copy={str(cycls_path.joinpath('theme')):"public", str(cycls_path)+"/web.py":"web.py"}
        copy={str(self.theme):"public", str(cycls_path)+"/web.py":"web.py"}
        copy.update({i:i for i in self.copy})

        new = Runtime(
            func=lambda port: __import__("uvicorn").run(__import__("web").web(i["func"], *i["config"]), host="0.0.0.0", port=port),
            name=i["name"],
            apt_packages=self.apt,
            pip_packages=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", *self.pip],
            copy=copy,
            api_key=self.api_key
        )
        new.deploy(port=port) if prod else new.run(port=port) 
        return
        
    def push(self, prod=False):
        self.client = modal.Client.from_credentials(*self.keys)
        image = (modal.Image.debian_slim()
                            .pip_install("fastapi[standard]", "pyjwt", "cryptography", *self.pip)
                            .apt_install(*self.apt)
                            .add_local_dir(self.theme, "/root/public")
                            .add_local_file(str(cycls_path)+"/web.py", "/root/web.py"))
        for item in self.copy:
            image = image.add_local_file(item, f"/root/{item}") if "." in item else image.add_local_dir(item, f'/root/{item}')
        self.app = modal.App("development", image=image)
    
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return

        for i in self.registered_functions:
            i["config"][1] = True if prod else False
            self.app.function(serialized=True, name=i["name"])(
                modal.asgi_app(label=i["name"], custom_domains=[i["domain"]])
                (lambda: __import__("web").web(i["func"], *i["config"]))
            )
        if prod:
            for i in self.registered_functions:
                print(f"✅ Deployed to ⇒ https://{i['domain']}")
            self.app.deploy(client=self.client, name=self.registered_functions[0]["name"])
            return
        else:
            with modal.enable_output():
                run_app(app=self.app, client=self.client)
                print(" Modal development server is running. Press Ctrl+C to stop.")
                with modal.enable_output(), run_app(app=self.app, client=self.client): 
                    while True: time.sleep(10)

# docker system prune -af
# poetry config pypi-token.pypi <your-token>
# poetry run python agent-cycls.py
# poetry publish --build
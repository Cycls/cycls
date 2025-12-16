import json, time, modal, inspect, uvicorn
from .runtime import Runtime
from modal.runner import run_app
from .web import web
import importlib.resources

CYCLS_PATH = importlib.resources.files('cycls')

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
    def __init__(self, theme=CYCLS_PATH.joinpath('theme'), org=None, api_token=None, pip=[], apt=[], copy=[], copy_public=[], modal_keys=["",""], key=None, base_url=None):
        self.org, self.api_token = org, api_token
        self.theme = theme
        self.key, self.modal_keys, self.pip, self.apt, self.copy, self.copy_public = key, modal_keys, pip, apt, copy, copy_public
        self.base_url = base_url

        self.registered_functions = []

    def __call__(self, name=None, header="", intro="", title="", domain=None, auth=False, tier="free", analytics=False):
        if tier=="cycls_pass":
            auth=True
            analytics=True
        def decorator(f):
            self.registered_functions.append({
                "func": f,
                "config": ["theme", False, self.org, self.api_token, header, intro, title, auth, tier, analytics],
                # "name": name,
                "name": name or (f.__name__).replace('_', '-'),
                "domain": domain or f"{name}.cycls.ai",
            })
            return f
        return decorator

    def local(self, port=8080):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        
        i = self.registered_functions[0]
        if len(self.registered_functions) > 1:
            print(f"⚠️  Warning: Multiple agents found. Running '{i['name']}'.")
        print(f"🚀 Starting local server at localhost:{port}")
        i["config"][0] = self.theme
        uvicorn.run(web(i["func"], *i["config"]), host="0.0.0.0", port=port)
        return

    def deploy(self, prod=False, port=8080):
        if not self.registered_functions:
            print("Error: No @agent decorated function found.")
            return
        if (self.key is None) and prod:
            print("🛑  Error: Please add your Cycls API key")
            return

        i = self.registered_functions[0]
        if len(self.registered_functions) > 1:
            print(f"⚠️  Warning: Multiple agents found. Running '{i['name']}'.")

        # i["config"][1] = False
        i["config"][1] = prod

        copy={str(self.theme):"theme", str(CYCLS_PATH)+"/web.py":"web.py"}
        copy.update({i:i for i in self.copy})
        copy.update({i:f"public/{i}" for i in self.copy_public})

        def server(port):
            import uvicorn, logging
            # This one-liner hides the confusing "0.0.0.0" message
            logging.getLogger("uvicorn.error").addFilter(type("F",(),{"filter": lambda s,r: "0.0.0.0" not in r.getMessage()})())
            print(f"\n🔨 Visit {i['name']} => http://localhost:{port}\n")
            uvicorn.run(__import__("web").web(i["func"], *i["config"]), host="0.0.0.0", port=port)

        new = Runtime(
            # func=lambda port: __import__("uvicorn").run(__import__("web").web(i["func"], *i["config"]), host="0.0.0.0", port=port),
            func=server,
            name=i["name"],
            apt_packages=self.apt,
            pip_packages=["fastapi[standard]", "pyjwt", "cryptography", "uvicorn", *self.pip],
            copy=copy,
            base_url=self.base_url,
            api_key=self.key
        )
        new.deploy(port=port) if prod else new.run(port=port) 
        return
        
    def modal(self, prod=False):
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
# poetry run python cake.py
# poetry publish --build
"""Remote execution — a bare `@cycls.function` (no `port` param) deploys
behind a pickle-RPC shim: POST / takes a cloudpickled (args, kwargs) and
returns a cloudpickled result.

Call a deployment by name with `cycls.remote(name)(...)`, or run the code
you're holding with `f.remote(...)` (see Function.remote). Auth is a token
derived from the deployer's API key — any machine holding the key can compute
it; nothing is stored. Each request carries its python/cloudpickle versions
and the shim refuses pickles that couldn't cross (bytecode is version-bound).
URLs follow the platform convention https://{name}.cycls.ai — pass url= to
override.

The shim serves via hypercorn like everything else cycls deploys — one
serving stack, h2 end-to-end on Cloud Run (no 32MB body cap).
"""
import hashlib
import sys

from .main import _get_api_key

def post(url, blob, *, name, api_key, timeout=3600):
    """One authed, runtime-stamped POST of a pickle."""
    import cloudpickle
    import requests
    return requests.post(
        url, data=blob, timeout=timeout,
        headers={"X-Cycls-Token": token_for(api_key, name),
                 "X-Cycls-Runtime": f"{sys.version_info.major}.{sys.version_info.minor}/{cloudpickle.__version__}",
                 "Content-Type": "application/octet-stream"})


SHIM_PRELUDE = '''import asyncio, hmac, os, sys, traceback
sys.path.insert(0, '/app')
import cloudpickle

pkl = sys.argv[1] if len(sys.argv) > 1 else "/app/function.pkl"
with open(pkl, "rb") as f:
    payload, token = cloudpickle.load(f)

RUNTIME = f"{sys.version_info.major}.{sys.version_info.minor}/{cloudpickle.__version__}"

def gate(runtime):
    py, _, cp = runtime.partition("/")
    return py, cp.split(".")[0]

async def reply(send, status, body, ctype=b"text/plain"):
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", ctype)]})
    await send({"type": "http.response.body", "body": body})

def check(scope):
    """None if the request may proceed, else (status, message)."""
    h = dict(scope["headers"])
    if not hmac.compare_digest(h.get(b"x-cycls-token", b"").decode(), token):
        return 403, b"bad token"
    caller = h.get(b"x-cycls-runtime", b"?/?").decode()
    if gate(caller) != gate(RUNTIME):
        return 409, (f"runtime mismatch: server {RUNTIME}, caller {caller} — pickles "
                     "won't cross; redeploy from the calling environment "
                     "or match it.").encode()
    return None

async def read(receive):
    body, more = b"", True
    while more:
        msg = await receive()
        body += msg.get("body", b"")
        more = msg.get("more_body", False)
    return body

def boot(asgi):
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    cfg = Config()
    cfg.bind = [f"0.0.0.0:{int(os.environ.get('PORT', 8080))}"]
    cfg.accesslog = "-"
    asyncio.run(serve(asgi, cfg))
'''

REMOTE_PY = SHIM_PRELUDE + '''
func = payload

import concurrent.futures
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=64)

async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    if scope["method"] != "POST":
        return await reply(send, 404, b"not found")
    if (bad := check(scope)):
        return await reply(send, *bad)
    try:
        args, kwargs = cloudpickle.loads(await read(receive))
        result = await asyncio.get_running_loop().run_in_executor(
            POOL, lambda: func(*args, **kwargs))
        await reply(send, 200, cloudpickle.dumps(result), b"application/octet-stream")
    except Exception:
        await reply(send, 500, traceback.format_exc().encode())

if __name__ == "__main__":
    boot(app)
'''


def token_for(api_key, name):
    return hashlib.sha256(f"{api_key}:{name}".encode()).hexdigest()


class RemoteError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def local_entrypoint(fn=None):
    """Mark the file's `cycls run` driver — runs locally on every save;
    `.remote()` calls inside it run in the cloud."""
    def mark(f):
        f._cycls_entry = True
        return f
    return mark(fn) if callable(fn) else mark


def _load_module(path_str):
    """Import a user file by path. Not registered in sys.modules, so its
    functions pickle by value."""
    import importlib.util
    from pathlib import Path
    path = Path(path_str).resolve()
    if not path.exists():
        sys.exit(f"Error: {path} not found")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(module)
    return module


def _drive(path):
    """`cycls run`'s per-save driver: run the file's @local_entrypoint, or
    call its function with defaults and print the result."""
    from .main import Function
    objs = list(_load_module(path).__dict__.values())
    entry = next((o for o in objs if getattr(o, "_cycls_entry", False)), None)
    if entry:
        entry()
        return
    fn = next((o for o in objs if isinstance(o, Function)), None)
    if fn is None:
        sys.exit(f"{path}: nothing to run — no @cycls.local_entrypoint or @cycls.function")
    result = fn.remote()
    if result is not None:
        print(result)


def remote(name, *, url=None, api_key=None):
    """Call a deployment by name: `cycls.remote("simulate")(n)`."""
    name = name.replace('_', '-')

    def call(*args, **kwargs):
        import cloudpickle
        key = api_key or _get_api_key()
        if not key:
            raise RemoteError("No API key. Set CYCLS_API_KEY or cycls.api_key.")
        r = post(url or f"https://{name}.cycls.ai", cloudpickle.dumps((args, kwargs)),
                 name=name, api_key=key)
        if r.status_code == 404:
            raise RemoteError(f"{name}: 404 — no such deployment. Run `cycls deploy <file>` first.",
                              status=404)
        if r.status_code != 200:
            raise RemoteError(f"{name}: {r.status_code} {r.text[:2000]}", status=r.status_code)
        return cloudpickle.loads(r.content)

    def fan_out(items, *, workers=16):
        """One call per item, fanned out across the deployment's autoscaled
        instances. Results in input order; raises on the first failure."""
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(workers) as pool:
            return list(pool.map(call, items))

    call.map = fan_out
    return call

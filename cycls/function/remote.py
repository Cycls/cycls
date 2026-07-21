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

def _stamp(api_key, name):
    import cloudpickle
    return {"X-Cycls-Token": token_for(api_key, name),
            "X-Cycls-Runtime": f"{sys.version_info.major}.{sys.version_info.minor}/{cloudpickle.__version__}",
            "Content-Type": "application/octet-stream"}


def post(url, blob, *, name, api_key, timeout=3600):
    """One authed, runtime-stamped POST of a pickle."""
    import httpx
    return httpx.post(url, content=blob, timeout=timeout,
                      headers=_stamp(api_key, name))


BARE_LOGS = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"bare": {"format": "%(message)s"}},
    "handlers": {"c": {"class": "logging.StreamHandler", "formatter": "bare",
                       "stream": "ext://sys.stdout"}},
    "loggers": {"hypercorn.access": {"handlers": ["c"], "level": "INFO", "propagate": False},
                "hypercorn.error": {"handlers": ["c"], "level": "INFO", "propagate": False}},
}

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
''' + f"\nBARE_LOGS = {BARE_LOGS!r}\n" + '''
def boot(asgi):
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    cfg = Config()
    cfg.bind = [f"0.0.0.0:{int(os.environ.get('PORT', 8080))}"]
    cfg.accesslog = cfg.errorlog = "-"
    cfg.access_log_format = "%(s)s %(m)s %(U)s"
    cfg.logconfig_dict = BARE_LOGS
    asyncio.run(serve(asgi, cfg))
'''

REMOTE_PY = SHIM_PRELUDE + '''
import queue, threading
import concurrent.futures

func = payload
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=64)

_routes, _real = {}, sys.stdout

class _Router:
    def write(self, s):
        q = _routes.get(threading.get_ident())
        (q.put if q else _real.write)(s)
        return len(s)
    def flush(self):
        _real.flush()

sys.stdout = _Router()

def _call(q, args, kwargs):
    _routes[threading.get_ident()] = q
    try:
        return func(*args, **kwargs)
    finally:
        del _routes[threading.get_ident()]

def frame(kind, data):
    return kind + len(data).to_bytes(4, "big") + data

async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    if scope["method"] != "POST":
        return await reply(send, 404, b"not found")
    if (bad := check(scope)):
        return await reply(send, *bad)
    try:
        args, kwargs = cloudpickle.loads(await read(receive))
    except Exception:
        return await reply(send, 500, traceback.format_exc().encode())
    q = queue.Queue()
    task = asyncio.get_running_loop().run_in_executor(POOL, _call, q, args, kwargs)
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/x-cycls-stream")]})

    async def out():
        buf = b""
        while not q.empty():
            buf += q.get_nowait().encode()
        if buf:
            await send({"type": "http.response.body", "body": frame(b"o", buf), "more_body": True})

    while not task.done():
        await out()
        await asyncio.wait({task}, timeout=0.05)
    await out()
    try:
        last = frame(b"r", cloudpickle.dumps(task.result()))
    except Exception:
        last = frame(b"e", traceback.format_exc().encode())
    await send({"type": "http.response.body", "body": last})

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


def _bind(fn, argv):
    """Bind `--name value` args to fn's signature. Annotated params convert
    via their annotation; the rest literal_eval, falling back to str."""
    import argparse
    import ast
    import inspect
    sig = inspect.signature(fn)
    parser = argparse.ArgumentParser(prog=getattr(fn, "__name__", "entrypoint"))
    for name, param in sig.parameters.items():
        parser.add_argument(f"--{name}", required=param.default is param.empty)
    given = {k: v for k, v in vars(parser.parse_args(list(argv))).items() if v is not None}
    for k, v in given.items():
        ann = sig.parameters[k].annotation
        if ann is not inspect.Parameter.empty and callable(ann):
            given[k] = ann(v)
        else:
            try:
                given[k] = ast.literal_eval(v)
            except (ValueError, SyntaxError):
                pass
    return given


def _drive(path, argv=(), remote=False):
    """`cycls run`'s per-save driver. Runs the file's @local_entrypoint (its
    code chooses the verbs), or calls its function — locally with .run(), or
    with .remote() under --remote. CLI args bind to the signature."""
    from .main import Function
    objs = list(_load_module(path).__dict__.values())
    entry = next((o for o in objs if getattr(o, "_cycls_entry", False)), None)
    if entry:
        entry(**_bind(entry, argv))
        return
    fn = next((o for o in objs if isinstance(o, Function)), None)
    if fn is None:
        sys.exit(f"{path}: nothing to run — no @cycls.local_entrypoint or @cycls.function")
    if fn._serves:
        if argv:
            sys.exit(f"{fn.name}: apps take no arguments")
        fn.remote()
        return
    kwargs = _bind(fn.func, argv)
    result = fn.remote(**kwargs) if remote else fn.run(**kwargs)
    if result is not None:
        print(result)


_MISSING = object()


def _consume(name, r):
    """Relay a framed response: `o` frames are the call's live stdout,
    `r` is the pickled result, `e` a remote traceback."""
    import cloudpickle
    result, buf, need = _MISSING, b"", None
    for chunk in r.iter_bytes(8192):
        buf += chunk
        while True:
            if need is None:
                if len(buf) < 5:
                    break
                kind, need, buf = buf[:1], int.from_bytes(buf[1:5], "big"), buf[5:]
            if len(buf) < need:
                break
            data, buf = buf[:need], buf[need:]
            need = None
            if kind == b"o":
                sys.stdout.write(data.decode(errors="replace"))
                sys.stdout.flush()
            elif kind == b"e":
                raise RemoteError(f"{name}: {data.decode(errors='replace')[:2000]}", status=500)
            else:
                result = cloudpickle.loads(data)
    if result is _MISSING:
        raise RemoteError(f"{name}: stream ended without a result", status=502)
    return result


def remote(name, *, url=None, api_key=None):
    """Call a deployment by name: `cycls.remote("simulate")(n)`."""
    name = name.replace('_', '-')

    def call(*args, **kwargs):
        import cloudpickle
        import httpx
        key = api_key or _get_api_key()
        if not key:
            raise RemoteError("No API key. Set CYCLS_API_KEY or cycls.api_key.")
        with httpx.stream("POST", url or f"https://{name}.cycls.ai",
                          content=cloudpickle.dumps((args, kwargs)),
                          timeout=3600, headers=_stamp(key, name)) as r:
            if r.status_code == 404:
                raise RemoteError(f"{name}: 404 — no such deployment. Run `cycls deploy <file>` first.",
                                  status=404)
            if r.status_code != 200:
                r.read()
                raise RemoteError(f"{name}: {r.status_code} {r.text[:2000]}", status=r.status_code)
            if r.headers.get("content-type") != "application/x-cycls-stream":
                r.read()
                return cloudpickle.loads(r.content)
            return _consume(name, r)

    def fan_out(items, *, workers=16):
        """One call per item, fanned out across the deployment's autoscaled
        instances. Results in input order; raises on the first failure."""
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(workers) as pool:
            return list(pool.map(call, items))

    call.map = fan_out
    return call

"""Remote execution — deploy a function behind a pickle-RPC shim (`cycls
deploy --remote`), call it from anywhere: `cycls.remote(name)(...)`.

The shim (REMOTE_PY, stdlib-only) accepts POST /: cloudpickled (args, kwargs)
in, cloudpickled result out. Auth is a token derived from the deployer's API
key — any machine holding the key can compute it; nothing is stored. Each
request carries its python/cloudpickle versions and the shim refuses pickles
that couldn't cross (bytecode is version-bound). URLs follow the platform
convention https://{name}.cycls.ai — pass url= to override.
"""
import hashlib
import sys

from .main import _get_api_key

REMOTE_PY = '''import hmac, http.server, os, sys, traceback
sys.path.insert(0, '/app')
import cloudpickle

pkl = sys.argv[1] if len(sys.argv) > 1 else "/app/function.pkl"
with open(pkl, "rb") as f:
    func, token = cloudpickle.load(f)

RUNTIME = f"{sys.version_info.major}.{sys.version_info.minor}/{cloudpickle.__version__}"

def gate(runtime):
    py, _, cp = runtime.partition("/")
    return py, cp.split(".")[0]

class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # Custom header, NOT Authorization: Cloud Run reserves that for IAM
        # and its front end 401s non-Google bearer tokens before we see them.
        if not hmac.compare_digest(self.headers.get("X-Cycls-Token", ""), token):
            self._send(403, b"bad token", "text/plain")
            return
        caller = self.headers.get("X-Cycls-Runtime", "?/?")
        if gate(caller) != gate(RUNTIME):
            self._send(409, (f"runtime mismatch: server {RUNTIME}, caller {caller} — "
                             "pickles won't cross; redeploy from the calling "
                             "environment or match it.").encode(), "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            args, kwargs = cloudpickle.loads(self.rfile.read(n))
            self._send(200, cloudpickle.dumps(func(*args, **kwargs)))
        except Exception:
            self._send(500, traceback.format_exc().encode(), "text/plain")

port = int(os.environ.get("PORT", 8080))
http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
'''


def token_for(api_key, name):
    return hashlib.sha256(f"{api_key}:{name}".encode()).hexdigest()


class RemoteError(Exception):
    pass


def remote(name, *, url=None, api_key=None):
    """Call a `--remote` deployment: `cycls.remote("simulate")(n)`."""
    name = name.replace('_', '-')

    def call(*args, **kwargs):
        import cloudpickle
        import requests
        key = api_key or _get_api_key()
        if not key:
            raise RemoteError("No API key. Set CYCLS_API_KEY or cycls.api_key.")
        r = requests.post(
            url or f"https://{name}.cycls.ai",
            data=cloudpickle.dumps((args, kwargs)),
            headers={"X-Cycls-Token": token_for(key, name),
                     "X-Cycls-Runtime": f"{sys.version_info.major}.{sys.version_info.minor}/{cloudpickle.__version__}",
                     "Content-Type": "application/octet-stream"},
            timeout=3600,
        )
        if r.status_code == 404:
            raise RemoteError(f"{name}: 404 — no such deployment. Run `cycls deploy <file>` first.")
        if r.status_code != 200:
            raise RemoteError(f"{name}: {r.status_code} {r.text[:2000]}")
        return cloudpickle.loads(r.content)

    def fan_out(items, *, workers=16):
        """One call per item, fanned out across the deployment's autoscaled
        instances. Results in input order; raises on the first failure."""
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(workers) as pool:
            return list(pool.map(call, items))

    call.map = fan_out
    return call

"""Remote execution — deploy a function behind a pickle-RPC shim, call it
from anywhere with `cycls.remote(name)(...)` or `func.remote(...)`.

The shim (REMOTE_PY, stdlib-only) serves POST / (cloudpickled (args, kwargs)
in, cloudpickled result out) and GET /health (python + cloudpickle versions
for the parity check). Auth is a bearer token derived from the deployer's
API key — any machine holding the same key can compute it; nothing is stored.
Pickles only cross same-python-minor / same-cloudpickle-major boundaries, so
the client hard-errors on /health mismatch before sending anything.
"""
import hashlib
import sys

from .main import _get_api_key, _get_base_url

REMOTE_PY = '''import http.server, hmac, json, os, sys, traceback
sys.path.insert(0, '/app')
import cloudpickle

pkl = sys.argv[1] if len(sys.argv) > 1 else "/app/function.pkl"
with open(pkl, "rb") as f:
    func, token = cloudpickle.load(f)

class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/octet-stream"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, json.dumps({
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                "cloudpickle": cloudpickle.__version__,
            }).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
            self._send(403, b"bad token", "text/plain")
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


class RemoteFunction:
    """Callable proxy for a `--remote` deployment. Resolves the URL by name
    via the deployment API (skipped when `url` is given) and checks /health
    parity once before the first call."""

    def __init__(self, name, *, url=None, api_key=None):
        self._name = name.replace('_', '-')
        self._url = url
        self._api_key = api_key
        self._checked = False

    def _key(self):
        key = self._api_key or _get_api_key()
        if not key:
            raise RemoteError("No API key. Set CYCLS_API_KEY or cycls.api_key.")
        return key

    def _resolve(self):
        if self._url:
            return self._url
        import requests
        base = (_get_base_url() or "https://api.cycls.ai").rstrip("/")
        r = requests.get(f"{base}/v1/deployment/list",
                         headers={"X-API-Key": self._key()}, timeout=30)
        r.raise_for_status()
        for svc in r.json():
            if svc.get("name") == self._name and svc.get("url"):
                self._url = svc["url"].rstrip("/")
                return self._url
        raise RemoteError(
            f"no deployment named {self._name!r} — run `cycls deploy <file> --remote`")

    def _ensure(self):
        url = self._resolve()
        if self._checked:
            return url
        import cloudpickle
        import requests
        r = requests.get(f"{url}/health", timeout=30)
        if r.status_code != 200:
            raise RemoteError(
                f"{self._name!r} didn't answer /health ({r.status_code}) — "
                "was it deployed with --remote?")
        info = r.json()
        host_py = f"{sys.version_info.major}.{sys.version_info.minor}"
        cp_major = cloudpickle.__version__.split(".")[0]
        if (info.get("python") != host_py
                or info.get("cloudpickle", "").split(".")[0] != cp_major):
            raise RemoteError(
                f"{self._name!r} runs Python {info.get('python')} / cloudpickle "
                f"{info.get('cloudpickle')}; you are calling from Python {host_py} / "
                f"cloudpickle {cloudpickle.__version__}. Pickles won't cross that "
                "boundary — redeploy from this environment or match it.")
        self._checked = True
        return url

    def __call__(self, *args, **kwargs):
        import cloudpickle
        import requests
        url = self._ensure()
        r = requests.post(
            url,
            data=cloudpickle.dumps((args, kwargs)),
            headers={"Authorization": f"Bearer {token_for(self._key(), self._name)}",
                     "Content-Type": "application/octet-stream"},
            timeout=3600,
        )
        if r.status_code == 200:
            return cloudpickle.loads(r.content)
        raise RemoteError(f"remote call failed ({r.status_code}): {r.text[:2000]}")


def remote(name, *, url=None, api_key=None):
    """Callable proxy for a `--remote` deployment: `cycls.remote("simulate")(n)`."""
    return RemoteFunction(name, url=url, api_key=api_key)

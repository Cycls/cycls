"""The reloadable ASGI dev-service shim behind app.remote(). SERVE_PY's
hypercorn boot sits behind a __main__ guard, so we exec the source and drive
`dispatcher` as raw ASGI — no hypercorn, no network."""
import asyncio
import sys

import cloudpickle
import pytest

from cycls.app.main import SERVE_PY, App
from cycls.function.remote import token_for

API_KEY, NAME = "test-key", "dev-demo"
TOKEN = token_for(API_KEY, NAME)
RUNTIME = f"{sys.version_info.major}.{sys.version_info.minor}/{cloudpickle.__version__}"


def builder(text):
    """A picklable zero-arg callable returning a tiny ASGI app — the same
    contract @cycls.app functions satisfy."""
    def build():
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": text})
        return app
    return build


@pytest.fixture
def dispatcher(tmp_path, monkeypatch):
    (tmp_path / "function.pkl").write_bytes(cloudpickle.dumps((builder(b"v1"), TOKEN)))
    monkeypatch.setattr("sys.argv", ["shim.py", str(tmp_path / "function.pkl")])
    ns = {"__name__": "shim"}          # not __main__ → defines, doesn't serve
    exec(SERVE_PY, ns)
    return ns["dispatcher"]


def call(dispatcher, path="/", method="GET", headers=(), body=b""):
    """Drive the dispatcher as raw ASGI; return (status, body)."""
    scope = {"type": "http", "path": path, "method": method, "headers": list(headers)}
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        sent.append(msg)

    asyncio.run(dispatcher(scope, receive, send))
    return sent[0]["status"], b"".join(m.get("body", b"") for m in sent[1:])


def reload_headers(token=TOKEN, runtime=RUNTIME):
    return [(b"x-cycls-token", token.encode()), (b"x-cycls-runtime", runtime.encode())]


def test_serves_the_baked_app(dispatcher):
    assert call(dispatcher) == (200, b"v1")


def test_reload_swaps_the_live_app(dispatcher):
    status, _ = call(dispatcher, "/_cycls/reload", "POST",
                     reload_headers(), cloudpickle.dumps(builder(b"v2")))
    assert status == 200
    assert call(dispatcher) == (200, b"v2")     # in-process pointer swap


def test_reload_needs_the_token(dispatcher):
    status, _ = call(dispatcher, "/_cycls/reload", "POST",
                     reload_headers(token="wrong"), cloudpickle.dumps(builder(b"v2")))
    assert status == 403
    assert call(dispatcher) == (200, b"v1")     # untouched


def test_reload_gates_on_runtime(dispatcher):
    status, body = call(dispatcher, "/_cycls/reload", "POST",
                        reload_headers(runtime="3.9/0.1"), cloudpickle.dumps(builder(b"v2")))
    assert status == 409 and b"won't cross" in body
    assert call(dispatcher) == (200, b"v1")


def test_broken_builder_keeps_the_old_app(dispatcher):
    def boom():
        raise RuntimeError("bad build")

    status, body = call(dispatcher, "/_cycls/reload", "POST",
                        reload_headers(), cloudpickle.dumps(boom))
    assert status == 500 and b"bad build" in body
    assert call(dispatcher) == (200, b"v1")     # a bad save never takes the app down


def test_app_remote_pushes_current_builder(monkeypatch, capsys):
    """app.remote() = one authed POST of the pickled builder to the dev URL."""
    import requests
    seen = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        seen.update(url=url, data=data, headers=headers)
        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(requests, "post", fake_post)
    a = App(func=builder(b"hi"), name="demo", image={}, auth=None)
    a._api_key = API_KEY
    a.remote()

    assert seen["url"] == "https://dev-demo.cycls.ai/_cycls/reload"
    assert seen["headers"]["X-Cycls-Token"] == token_for(API_KEY, "dev-demo")
    assert cloudpickle.loads(seen["data"])()  # the builder round-trips
    assert "https://dev-demo.cycls.ai" in capsys.readouterr().out


def test_load_target_returns_entrypoint(tmp_path):
    from cycls.cli import _load_target
    (tmp_path / "with_entry.py").write_text(
        "import cycls\n"
        "@cycls.function()\n"
        "def g(x): return x\n"
        "@cycls.local_entrypoint\n"
        "def m(): return 7\n")
    (tmp_path / "without.py").write_text(
        "import cycls\n"
        "@cycls.function()\n"
        "def g(x): return x\n")
    instance, entry = _load_target(str(tmp_path / "with_entry.py"))
    assert instance.name == "g" and entry() == 7
    _, entry = _load_target(str(tmp_path / "without.py"))
    assert entry is None

"""The reloadable ASGI dev-service shim behind app.remote(). SERVE_PY's
hypercorn boot sits behind a __main__ guard, so we exec the source and drive
`dispatcher` as raw ASGI — no hypercorn, no network."""
import asyncio
import sys

import cloudpickle
import pytest

from cycls._app.main import SERVE_PY, App
from cycls._function.remote import token_for

API_KEY, NAME = "test-key", "dev-demo"
TOKEN = token_for(API_KEY, NAME)
RUNTIME = f"{sys.version_info.major}.{sys.version_info.minor}/{cloudpickle.__version__}"


def builder(text):
    """A picklable zero-arg callable returning a tiny ASGI app — the same
    contract @cycls._app functions satisfy."""
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
    import httpx
    seen = {}

    def fake_post(url, content=None, headers=None, timeout=None):
        seen.update(url=url, data=content, headers=headers)
        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(httpx, "post", fake_post)
    a = App(func=builder(b"hi"), name="demo", image={}, auth=None)
    a._api_key = API_KEY
    a.remote()

    assert seen["url"] == "https://dev-demo.cycls.ai/_cycls/reload"
    assert seen["headers"]["X-Cycls-Token"] == token_for(API_KEY, "dev-demo")
    assert cloudpickle.loads(seen["data"])()  # the builder round-trips
    assert "https://dev-demo.cycls.ai" in capsys.readouterr().out


@pytest.fixture
def shim_ns(tmp_path, monkeypatch):
    (tmp_path / "function.pkl").write_bytes(cloudpickle.dumps((builder(b"v1"), TOKEN)))
    monkeypatch.setattr("sys.argv", ["shim.py", str(tmp_path / "function.pkl")])
    saved = sys.stdout           # SERVE_PY installs its tee on the real sys.stdout
    ns = {"__name__": "shim"}
    exec(SERVE_PY, ns)
    yield ns
    sys.stdout = saved


def test_log_tee_broadcasts_to_subscribers(shim_ns):
    import queue
    q = queue.Queue()
    shim_ns["_subs"].append(q)
    shim_ns["_Tee"]().write("hello from the app\n")   # this namespace's tee
    shim_ns["_subs"].remove(q)
    seen = "".join(q.get_nowait() for _ in range(q.qsize()))
    assert "hello from the app" in seen


def test_logs_endpoint_needs_token(shim_ns):
    status, _ = call(shim_ns["dispatcher"], "/_cycls/logs", "GET",
                     [(b"x-cycls-token", b"wrong")])
    assert status == 403


def test_stream_logs_relays_lines(monkeypatch, capsys):
    import threading
    import httpx
    from cycls import cli

    stop = threading.Event()

    class Streaming:
        status_code = 200
        def iter_lines(self):
            yield "200 GET / 2"
            stop.set()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setenv("CYCLS_API_KEY", "k")
    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: Streaming())
    cli._stream_logs("dev-demo", stop)
    assert "GET /" in capsys.readouterr().out


def test_stream_logs_gives_up_on_old_service(monkeypatch, capsys):
    import threading
    import httpx
    from cycls import cli

    class Missing:
        status_code = 404
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setenv("CYCLS_API_KEY", "k")
    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: Missing())
    cli._stream_logs("dev-old", threading.Event())
    assert "cycls rm dev-old" in capsys.readouterr().out


def test_pretty_log_shapes():
    from cycls.cli import _pretty_log
    assert _pretty_log("200 GET /").endswith("GET /")             # hypercorn access line
    assert "\033[31m500" in _pretty_log("500 GET /boom")          # red on 5xx
    assert "\033[33m404" in _pretty_log("404 GET /x")             # yellow on 4xx
    assert _pretty_log("200 POST /_cycls/reload") is None         # loop's own traffic hidden
    assert _pretty_log("Error in ASGI Framework") == "Error in ASGI Framework"
    assert _pretty_log('  File "app.py", line 8') == '  File "app.py", line 8'   # traceback indent kept
    assert _pretty_log("   ") is None


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

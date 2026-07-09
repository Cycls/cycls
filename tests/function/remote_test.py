"""Pickle-RPC shim + client, no Docker: REMOTE_PY runs as a host subprocess
(same python + cloudpickle as the client, so the runtime gate passes)."""
import os
import socket
import subprocess
import sys
import time

import cloudpickle
import pytest

from cycls.function.remote import REMOTE_PY, RemoteError, remote, token_for

API_KEY = "test-key"
NAME = "doubler"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_shim(tmp, func, name):
    (tmp / "function.pkl").write_bytes(
        cloudpickle.dumps((func, token_for(API_KEY, name))))
    (tmp / "shim.py").write_text(REMOTE_PY)

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(tmp / "shim.py"), str(tmp / "function.pkl")],
        env={**os.environ, "PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    url = f"http://127.0.0.1:{port}"
    import requests
    for _ in range(50):
        try:
            requests.get(url, timeout=1)
            break
        except requests.exceptions.ConnectionError:
            if proc.poll() is not None:
                raise RuntimeError("shim died on startup")
            time.sleep(0.1)
    return url, proc


@pytest.fixture(scope="module")
def shim_url(tmp_path_factory):
    def doubler(x, add=0):
        if x < 0:
            raise ValueError("negative input")
        print("doubling", x)
        return x * 2 + add

    url, proc = _start_shim(tmp_path_factory.mktemp("remote"), doubler, NAME)
    yield url
    proc.terminate()
    proc.wait(timeout=5)


def test_local_entrypoint_forms():
    import cycls

    @cycls.local_entrypoint
    def bare():
        return 41

    @cycls.local_entrypoint()          # Modal-style parens
    def parens():
        return 42

    # The decorated object stays a plain function — just marked.
    assert bare._cycls_entry and bare() == 41
    assert parens._cycls_entry and parens() == 42


def test_drive_runs_entrypoint(tmp_path, shim_url, monkeypatch, capsys):
    # The `cycls run` per-save path, minus the watcher: load the file, find
    # its entrypoint, run it — its .remote() call lands on the local shim.
    import cycls
    from cycls.function import remote as rmod

    monkeypatch.setattr(cycls, "remote",
                        lambda n, **kw: rmod.remote(n, url=shim_url, api_key=API_KEY))
    (tmp_path / "loop.py").write_text(
        "import cycls\n"
        "@cycls.function()\n"
        "def unused(x): return x\n"
        "@cycls.local_entrypoint\n"
        "def main():\n"
        f"    print('driver:', cycls.remote('{NAME}')(21))\n")

    rmod._drive(str(tmp_path / "loop.py"))
    assert "driver: 42" in capsys.readouterr().out


@pytest.fixture(scope="module")
def exec_url(tmp_path_factory):
    def execute(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    url, proc = _start_shim(tmp_path_factory.mktemp("exec"), execute, "exec-x")
    yield url
    proc.terminate()
    proc.wait(timeout=5)


def test_function_remote_and_map_ship_current(exec_url, monkeypatch):
    from cycls.function import remote as rmod
    from cycls.function.main import Function

    orig = rmod.remote
    monkeypatch.setattr(rmod, "remote",
                        lambda n, **kw: orig("exec-x", url=exec_url, api_key=API_KEY))
    f = Function(lambda x: x * 2, "t")
    assert f.remote(21) == 42
    assert f.map([1, 2, 3]) == [2, 4, 6]     # same symmetry as cycls.remote(name).map
    f.func = lambda x: x * 3                 # "edit" — the next call ships the new code
    assert f.map([1, 2]) == [3, 6]


def test_executor_shared_per_image():
    from cycls.function.main import Function
    a = Function(lambda x: x, "aa", image={"pip": ["numpy"]})
    b = Function(lambda y: y * 2, "bb", image={"pip": ["numpy"]})   # same image, other code
    c = Function(lambda z: z, "cc", image={"pip": ["pandas"]})
    assert a._executor_name() == b._executor_name()                 # shared executor
    assert a._executor_name() != c._executor_name()                 # deps differ → own executor
    assert a._executor_name().startswith("exec-")


def test_bind_converts_by_signature():
    from cycls.function.remote import _bind

    def fn(n: int = 5, name="x", data=None, flag=True):
        pass

    assert _bind(fn, []) == {}                                        # defaults untouched
    assert _bind(fn, ["--n", "10"]) == {"n": 10}                      # annotation converts
    assert _bind(fn, ["--name", "abc"]) == {"name": "abc"}            # unparseable → str
    assert _bind(fn, ["--data", "[1, 2]", "--flag", "False"]) == {"data": [1, 2], "flag": False}

    def required(x):
        pass

    with pytest.raises(SystemExit):                                   # missing required arg
        _bind(required, [])


def test_drive_binds_args_to_entrypoint(tmp_path, capsys):
    from cycls.function.remote import _drive
    (tmp_path / "argy.py").write_text(
        "import cycls\n"
        "@cycls.function()\n"
        "def g(x): return x\n"
        "@cycls.local_entrypoint\n"
        "def main(n: int = 1):\n"
        "    print('n is', n * 2)\n")
    _drive(str(tmp_path / "argy.py"), ["--n", "21"])
    assert "n is 42" in capsys.readouterr().out


def test_drive_routes_run_vs_remote(tmp_path, capsys, monkeypatch):
    from cycls.function.main import Function
    from cycls.function.remote import _drive
    (tmp_path / "r.py").write_text(
        "import cycls\n"
        "@cycls.function()\n"
        "def g(x: int = 1): return x\n")
    monkeypatch.setattr(Function, "run", lambda self, **kw: ("local", kw))
    monkeypatch.setattr(Function, "remote", lambda self, **kw: ("cloud", kw))
    _drive(str(tmp_path / "r.py"), ["--x", "5"])
    assert "('local', {'x': 5})" in capsys.readouterr().out
    _drive(str(tmp_path / "r.py"), ["--x", "5"], remote=True)
    assert "('cloud', {'x': 5})" in capsys.readouterr().out


def test_deploy_mode_reads_signature():
    from cycls.function.main import Function
    f = lambda func: Function(func, "t")
    assert f(lambda url: url)._is_remote()                    # bare function → endpoint
    assert not f(lambda port: port)._is_remote()              # server contract
    assert not f(lambda **kwargs: None)._is_remote()          # can absorb port → server


def test_token_deterministic():
    assert token_for("k", "n") == token_for("k", "n")
    assert token_for("k", "n") != token_for("k2", "n") != token_for("k", "n2")


def test_call_roundtrip(shim_url):
    fn = remote(NAME, url=shim_url, api_key=API_KEY)
    assert fn(21) == 42
    assert fn(20, add=2) == 42  # kwargs travel too


def test_stdout_streams_back(shim_url, capsys):
    fn = remote(NAME, url=shim_url, api_key=API_KEY)
    assert fn(21) == 42
    assert "doubling 21" in capsys.readouterr().out   # the remote print, relayed


def test_legacy_shim_response(monkeypatch):
    import cloudpickle
    from cycls.function import remote as rmod

    class R:
        status_code = 200
        headers = {"content-type": "application/octet-stream"}
        content = cloudpickle.dumps(42)

    monkeypatch.setattr(rmod, "post", lambda *a, **kw: R())
    assert remote("old", url="http://x", api_key=API_KEY)(1) == 42


def test_map_fans_out_in_order(shim_url):
    fn = remote(NAME, url=shim_url, api_key=API_KEY)
    assert fn.map(range(5)) == [0, 2, 4, 6, 8]      # ordered despite concurrency
    with pytest.raises(RemoteError, match="negative input"):
        fn.map([1, -1, 2])                          # first failure propagates


def test_bad_token_rejected(shim_url):
    fn = remote(NAME, url=shim_url, api_key="wrong-key")
    with pytest.raises(RemoteError, match="403") as e:
        fn(21)
    assert e.value.status == 403


def test_exception_propagates(shim_url):
    # User-code failures surface as 500 with the remote traceback — and carry
    # the status, so provisioning logic never mistakes them for a missing
    # deployment (even if the error text itself mentions "404").
    fn = remote(NAME, url=shim_url, api_key=API_KEY)
    with pytest.raises(RemoteError, match="negative input") as e:
        fn(-1)
    assert e.value.status == 500


def test_runtime_mismatch_blocks_call(shim_url):
    import requests
    r = requests.post(shim_url,
                      data=cloudpickle.dumps(((21,), {})),
                      headers={"X-Cycls-Token": token_for(API_KEY, NAME),
                               "X-Cycls-Runtime": "3.9/0.1"},
                      timeout=5)
    assert r.status_code == 409
    assert "won't cross" in r.text

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


@pytest.fixture(scope="module")
def shim_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("remote")

    def doubler(x, add=0):
        if x < 0:
            raise ValueError("negative input")
        return x * 2 + add

    (tmp / "function.pkl").write_bytes(
        cloudpickle.dumps((doubler, token_for(API_KEY, NAME))))
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
    yield url
    proc.terminate()
    proc.wait(timeout=5)


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


def test_map_fans_out_in_order(shim_url):
    fn = remote(NAME, url=shim_url, api_key=API_KEY)
    assert fn.map(range(5)) == [0, 2, 4, 6, 8]      # ordered despite concurrency
    with pytest.raises(RemoteError, match="negative input"):
        fn.map([1, -1, 2])                          # first failure propagates


def test_bad_token_rejected(shim_url):
    fn = remote(NAME, url=shim_url, api_key="wrong-key")
    with pytest.raises(RemoteError, match="403"):
        fn(21)


def test_exception_propagates(shim_url):
    fn = remote(NAME, url=shim_url, api_key=API_KEY)
    with pytest.raises(RemoteError, match="negative input"):
        fn(-1)


def test_runtime_mismatch_blocks_call(shim_url):
    import requests
    r = requests.post(shim_url,
                      data=cloudpickle.dumps(((21,), {})),
                      headers={"X-Cycls-Token": token_for(API_KEY, NAME),
                               "X-Cycls-Runtime": "3.9/0.1"},
                      timeout=5)
    assert r.status_code == 409
    assert "won't cross" in r.text

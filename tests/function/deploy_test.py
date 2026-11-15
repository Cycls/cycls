"""Deploy wire format, no network or Docker: the form POSTed to /v1/deploy
carries the resource spec, and the NDJSON stream is abandoned at DONE."""
import json
from unittest.mock import MagicMock, patch

import cycls


def _responses(events=None):
    stream = MagicMock()
    resp = stream.return_value.__enter__.return_value
    resp.is_error = False
    resp.iter_lines.return_value = events if events is not None else iter(
        [json.dumps({"status": "DONE", "url": "https://x.cycls.ai"})])
    check = MagicMock()
    check.status_code = 200
    check.json.return_value = {"available": True}
    return stream, check


def _deploy(fn, events=None):
    stream, check = _responses(events)
    with patch("cycls._function.main._deploy_request", stream), patch("httpx.get", return_value=check):
        url = fn.deploy()
    return url, stream.call_args.kwargs["data"]


def test_decorator_spec_reaches_the_form():
    @cycls.function(image=cycls.Image(), cpu=2, memory="4Gi", timeout=1800, concurrency=1)
    def f(x):
        return x

    _, form = _deploy(f)
    assert form["cpu"] == 2
    assert form["memory"] == "4Gi"
    assert form["timeout"] == 1800
    assert form["concurrency"] == 1


def test_bare_function_sends_legacy_defaults():
    @cycls.function(image=cycls.Image())
    def f(x):
        return x

    _, form = _deploy(f)
    assert form["memory"] == "1Gi"
    assert form["timeout"] == 1200
    assert "cpu" not in form
    assert "concurrency" not in form
    assert "max_instances" not in form


def test_dev_provision_caps_instances():
    from cycls._function.main import Function

    f = Function(lambda context: None, "dev-demo", max_instances=1)
    _, form = _deploy(f)
    assert form["max_instances"] == 1


def test_stream_abandoned_at_done():
    @cycls.function(image=cycls.Image())
    def f(x):
        return x

    events = iter([json.dumps({"status": "DONE", "url": "https://f.cycls.ai"}), "sentinel"])
    url, _ = _deploy(f, events=events)
    assert url == "https://f.cycls.ai"
    assert next(events) == "sentinel"


def test_executor_inherits_spec():
    @cycls.function(image=cycls.Image(), cpu=4, concurrency=1)
    def f(x):
        return x

    stream, check = _responses()
    with patch("cycls._function.main._deploy_request", stream), patch("httpx.get", return_value=check):
        f._deploy_executor("exec-test")
    form = stream.call_args.kwargs["data"]
    assert form["function_name"] == "exec-test"
    assert form["cpu"] == 4
    assert form["concurrency"] == 1


def test_the_status_stream_is_kept_alive_while_the_build_is_quiet():
    import socket

    from cycls._function import main
    opts = main._keepalive_options()
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in opts
    idle = getattr(socket, "TCP_KEEPIDLE", None) or getattr(socket, "TCP_KEEPALIVE", None)
    if idle is not None:
        assert (socket.IPPROTO_TCP, idle, main.KEEPALIVE_S) in opts
    # the request goes through a client whose transport carries them, with a bounded wait for the next line
    seen = {}

    class Client:
        def __init__(self, transport=None, timeout=None):
            seen["transport"], seen["timeout"] = transport, timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, **kw):
            seen["call"] = (method, url, kw)
            resp = MagicMock()
            cm = MagicMock()
            cm.__enter__.return_value = resp
            return cm

    with patch("httpx.Client", Client):
        with main._deploy_request("https://api/v1/deploy", data={"a": 1}) as r:
            assert r is not None
    assert seen["call"][0] == "POST" and seen["call"][2]["data"] == {"a": 1}
    assert seen["timeout"].read == main.STATUS_SILENCE_S < 9000
    assert seen["transport"] is not None


def _dropping(after_lines):
    """A deploy stream that says a few lines, then loses its connection."""
    import httpx

    def lines():
        yield from after_lines
        raise httpx.ReadError("connection lost")
    return iter(lines())


def test_a_connection_lost_while_building_says_the_deploy_goes_on(capsys):
    @cycls.function(image=cycls.Image(), name="probe-x")
    def f(x):
        return x

    events = _dropping([json.dumps({"status": "BUILDING", "message": "Build working"})])
    url, _ = _deploy(f, events=events)
    out = capsys.readouterr().out
    assert url is None
    assert "[BUILDING] Build working" in out and "while it was building 'probe-x'" in out
    assert "cycls logs probe-x --since 10m" in out and "Running on" in out


def test_a_connection_lost_before_any_answer_says_it_may_not_have_started(capsys):
    @cycls.function(image=cycls.Image(), name="probe-y")
    def f(x):
        return x

    url, _ = _deploy(f, events=_dropping([]))
    out = capsys.readouterr().out
    assert url is None and "before it answered" in out and "may or may not have started" in out

"""Deploy wire format, no network or Docker: the form POSTed to /v1/deploy
carries the resource spec, and the NDJSON stream is abandoned at DONE."""
import json
from unittest.mock import MagicMock, patch

import cycls


def _responses(events=None):
    resp = MagicMock()
    resp.ok = True
    resp.iter_lines.return_value = events if events is not None else iter(
        [json.dumps({"status": "DONE", "url": "https://x.cycls.ai"})])
    check = MagicMock()
    check.status_code = 200
    check.json.return_value = {"available": True}
    return resp, check


def _deploy(fn, events=None, **kwargs):
    resp, check = _responses(events)
    with patch("requests.post", return_value=resp) as post, \
         patch("requests.get", return_value=check):
        url = fn.deploy(**kwargs)
    return url, post.call_args.kwargs["data"]


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


def test_deploy_kwargs_override_decorator():
    @cycls.function(image=cycls.Image(), cpu=2)
    def f(x):
        return x

    _, form = _deploy(f, cpu=4, memory="8Gi")
    assert form["cpu"] == 4
    assert form["memory"] == "8Gi"


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

    resp, check = _responses()
    with patch("requests.post", return_value=resp) as post, \
         patch("requests.get", return_value=check):
        f._deploy_executor("exec-test")
    form = post.call_args.kwargs["data"]
    assert form["function_name"] == "exec-test"
    assert form["cpu"] == 4
    assert form["concurrency"] == 1
    assert "memory" in form and "timeout" in form

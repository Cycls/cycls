"""Phase 1 — the browser-service client (cycls._agent.browser.client).

Covers the pure logic: the configured() gate, CDP-endpoint resolution per
provider, the Steel session-create HTTP path (mocked), and graceful Unavailable
when unconfigured. The live CDP drive (connect/goto/click/screenshot) is proven
separately against a real Chrome; here we never touch a browser."""
import asyncio
import json

import pytest

from cycls._agent import browser
from cycls._agent.browser import client


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for k in ("BROWSER_URL", "BROWSER_SECRET", "BROWSER_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    client._STEEL_SESSIONS.clear()   # module-level session caches — isolate tests
    client._REST_SESSIONS.clear()


# ---- configured() gate ----

def test_configured_needs_url(monkeypatch):
    assert browser.configured() is False               # nothing set
    monkeypatch.setenv("BROWSER_PROVIDER", "cdp")
    monkeypatch.setenv("BROWSER_URL", "http://host:9222")
    assert browser.configured() is True                # cdp needs only a URL


def test_configured_steel_needs_secret(monkeypatch):
    monkeypatch.setenv("BROWSER_URL", "https://steel.internal")
    assert browser.configured() is False               # steel (default) needs a secret too
    monkeypatch.setenv("BROWSER_SECRET", "s")
    assert browser.configured() is True


# ---- endpoint resolution ----

def test_cdp_provider_returns_url_verbatim(monkeypatch):
    monkeypatch.setenv("BROWSER_PROVIDER", "cdp")
    monkeypatch.setenv("BROWSER_URL", "http://host:9222")
    assert asyncio.run(client._cdp_endpoint()) == "http://host:9222"


def test_unconfigured_raises_unavailable():
    with pytest.raises(browser.Unavailable):
        asyncio.run(client._cdp_endpoint())


def test_steel_without_secret_raises(monkeypatch):
    monkeypatch.setenv("BROWSER_URL", "https://steel.internal")   # provider defaults to steel
    with pytest.raises(browser.Unavailable):
        asyncio.run(client._cdp_endpoint())


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("BROWSER_PROVIDER", "wat")
    monkeypatch.setenv("BROWSER_URL", "https://x")
    monkeypatch.setenv("BROWSER_SECRET", "s")
    with pytest.raises(browser.Unavailable):
        asyncio.run(client._cdp_endpoint())


# ---- Steel session-create HTTP path (mocked) ----

class _FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p

    @property
    def text(self):
        return json.dumps(self._p)


class _FakeClient:
    """Async-context stand-in for httpx.AsyncClient that records the call."""
    last = {}

    def __init__(self, resp, **_):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeClient.last = {"url": url, "headers": headers or {}}
        return self._resp


def _mock_httpx(monkeypatch, resp):
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **k: _FakeClient(resp, **k))


def test_steel_session_returns_cdp_ws(monkeypatch):
    monkeypatch.setenv("BROWSER_URL", "https://steel.internal/")
    monkeypatch.setenv("BROWSER_SECRET", "sekret")
    _mock_httpx(monkeypatch, _FakeResp(200, {"websocketUrl": "ws://steel/devtools/browser/abc"}))
    ws = asyncio.run(client._cdp_endpoint("org_1:user_1"))
    assert ws == "ws://steel/devtools/browser/abc"
    # secret as Bearer, subject as X-User-Id (attribution, not auth), trailing slash trimmed
    assert _FakeClient.last["url"] == "https://steel.internal/v1/sessions"
    assert _FakeClient.last["headers"]["Authorization"] == "Bearer sekret"
    assert _FakeClient.last["headers"]["X-User-Id"] == "org_1:user_1"


def test_steel_accepts_alternate_url_keys(monkeypatch):
    monkeypatch.setenv("BROWSER_URL", "https://steel.internal")
    monkeypatch.setenv("BROWSER_SECRET", "s")
    _mock_httpx(monkeypatch, _FakeResp(201, {"connectUrl": "ws://steel/x"}))
    assert asyncio.run(client._cdp_endpoint()) == "ws://steel/x"


def test_steel_non_200_is_unavailable(monkeypatch):
    monkeypatch.setenv("BROWSER_URL", "https://steel.internal")
    monkeypatch.setenv("BROWSER_SECRET", "s")
    _mock_httpx(monkeypatch, _FakeResp(502, {"error": "no capacity"}))
    with pytest.raises(browser.Unavailable):
        asyncio.run(client._cdp_endpoint())


def test_steel_missing_ws_url_is_unavailable(monkeypatch):
    monkeypatch.setenv("BROWSER_URL", "https://steel.internal")
    monkeypatch.setenv("BROWSER_SECRET", "s")
    _mock_httpx(monkeypatch, _FakeResp(200, {"id": "sess_1"}))   # no websocketUrl/connectUrl
    with pytest.raises(browser.Unavailable):
        asyncio.run(client._cdp_endpoint())


def test_steel_session_reused_across_calls(monkeypatch):
    """The same caller reuses its live session (no re-POST) so page state
    persists across the stateless per-call cycles; a different caller mints its
    own."""
    monkeypatch.setenv("BROWSER_URL", "https://steel.internal")
    monkeypatch.setenv("BROWSER_SECRET", "s")
    posts = {"n": 0}

    class _Counting(_FakeClient):
        async def post(self, url, headers=None, json=None):
            posts["n"] += 1
            return _FakeResp(200, {"websocketUrl": f"ws://steel/{posts['n']}"})

    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **k: _Counting(None, **k))
    a = asyncio.run(client._cdp_endpoint("u1"))
    b = asyncio.run(client._cdp_endpoint("u1"))
    assert a == b == "ws://steel/1" and posts["n"] == 1     # reused, one POST
    c = asyncio.run(client._cdp_endpoint("u2"))
    assert c == "ws://steel/2" and posts["n"] == 2          # other caller → own session


def test_cycls_provider_configured(monkeypatch):
    monkeypatch.setenv("BROWSER_PROVIDER", "cycls")
    monkeypatch.setenv("BROWSER_URL", "https://browser.cycls.ai")
    assert browser.configured() is False          # needs a secret too
    monkeypatch.setenv("BROWSER_SECRET", "s")
    assert browser.configured() is True


def test_cycls_provider_dispatches_to_rest_session(monkeypatch):
    """The `cycls` provider talks to the REST browser service (RestSession),
    not CDP — the tool executor gets the same method surface either way."""
    monkeypatch.setenv("BROWSER_PROVIDER", "cycls")
    monkeypatch.setenv("BROWSER_URL", "https://browser.cycls.ai")
    monkeypatch.setenv("BROWSER_SECRET", "s")

    async def _fake_connect(self):
        self._sid = "sess-1"

    monkeypatch.setattr(client.RestSession, "_connect", _fake_connect)
    s = asyncio.run(browser.session("org_1:user_1"))
    assert isinstance(s, client.RestSession)
    assert s._sid == "sess-1" and s._user_id == "org_1:user_1"


def test_session_helper_raises_when_unconfigured():
    with pytest.raises(browser.Unavailable):
        asyncio.run(browser.session())


# ---- the Browser tool (executor + gating + labels), with a fake session ----

import types

from cycls._agent.tools import _exec_browser, _browser_snapshot_text, build_tools, tool_step


class _FakeSession:
    def __init__(self):
        self.calls = []
        self.snap = {"url": "http://x/", "title": "X", "text": "hello world",
                     "text_truncated": False, "refs_truncated": False,
                     "refs": [{"ref": 0, "tag": "input", "type": "text", "label": "q"},
                              {"ref": 1, "tag": "button", "type": "", "label": "Go"}]}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def goto(self, url, **k):
        self.calls.append(("goto", url))

    async def snapshot(self):
        return self.snap

    async def click_ref(self, ref):
        self.calls.append(("click", ref))

    async def type_ref(self, ref, value):
        self.calls.append(("type", ref, value))

    async def press(self, key):
        self.calls.append(("press", key))

    async def back(self):
        self.calls.append(("back",))

    async def info(self):
        return {"url": "http://x/", "title": "X"}

    async def screenshot(self, full_page=False):
        self.calls.append(("screenshot", full_page))
        return b"\x89PNG\r\n\x1a\nfake"


def _use_fake(monkeypatch):
    fake = _FakeSession()
    async def _session(user_id=None):
        _session.subject = user_id
        return fake
    monkeypatch.setattr("cycls._agent.browser.session", _session)
    return fake, _session


def _ws(tmp_path):
    return types.SimpleNamespace(root=str(tmp_path), subject="org_1:user_1")


def test_snapshot_text_formats_refs():
    txt = _browser_snapshot_text({"url": "http://x/", "title": "T", "text": "body text",
                                  "text_truncated": False, "refs_truncated": False,
                                  "refs": [{"ref": 0, "tag": "input", "type": "text", "label": "q"},
                                           {"ref": 1, "tag": "button", "type": "", "label": "Go"}]})
    assert "T — http://x/" in txt and "body text" in txt
    assert '[0] input(text) "q"' in txt and '[1] button "Go"' in txt


def test_open_navigates_and_reads(tmp_path, monkeypatch):
    fake, sess = _use_fake(monkeypatch)
    out = asyncio.run(_exec_browser({"action": "open", "url": "http://x/"}, _ws(tmp_path)))
    assert ("goto", "http://x/") in fake.calls          # navigated
    assert sess.subject == "org_1:user_1"               # subject passed for attribution
    assert '[1] button "Go"' in out                     # returns a fresh read


def test_click_and_type_by_ref(tmp_path, monkeypatch):
    fake, _ = _use_fake(monkeypatch)
    asyncio.run(_exec_browser({"action": "type", "ref": 0, "text": "hi"}, _ws(tmp_path)))
    asyncio.run(_exec_browser({"action": "click", "ref": 1}, _ws(tmp_path)))
    assert ("type", 0, "hi") in fake.calls and ("click", 1) in fake.calls


def test_screenshot_saves_and_opens_on_canvas(tmp_path, monkeypatch):
    _use_fake(monkeypatch)
    out = asyncio.run(_exec_browser({"action": "screenshot"}, _ws(tmp_path)))
    shots = list((tmp_path / "screenshots").glob("*.png"))
    assert len(shots) == 1 and shots[0].read_bytes().startswith(b"\x89PNG")
    # model channel: a text ack; ui channel: an open_canvas event for the PNG
    assert "saved to screenshots/" in out["_model"] and "canvas" in out["_model"]
    ui = out["_ui"]
    assert ui["type"] == "ui" and ui["action"] == "open_canvas"
    assert ui["path"].startswith("screenshots/") and ui["path"].endswith(".png")
    assert ui["path"].rsplit("/", 1)[-1] == ui["name"]


def test_action_arg_validation(tmp_path, monkeypatch):
    _use_fake(monkeypatch)
    ws = _ws(tmp_path)
    assert asyncio.run(_exec_browser({"action": "open"}, ws)).startswith("Error")        # no url
    assert asyncio.run(_exec_browser({"action": "click"}, ws)).startswith("Error")       # no ref
    assert asyncio.run(_exec_browser({"action": "type", "ref": 0}, ws)).startswith("Error")  # no text
    assert asyncio.run(_exec_browser({"action": "nope"}, ws)).startswith("Error")        # unknown


def test_executor_reports_unavailable(tmp_path, monkeypatch):
    async def _boom(user_id=None):
        raise browser.Unavailable("service down")
    monkeypatch.setattr("cycls._agent.browser.session", _boom)
    out = asyncio.run(_exec_browser({"action": "read"}, _ws(tmp_path)))
    assert out.startswith("Error: browser unavailable")


def test_build_tools_gates_on_configured(monkeypatch):
    for k in ("BROWSER_URL", "BROWSER_SECRET", "BROWSER_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    assert "browser" not in [t.get("name") for t in build_tools(["Browser"], [], vendor="openai")]
    monkeypatch.setenv("BROWSER_PROVIDER", "cdp")
    monkeypatch.setenv("BROWSER_URL", "http://host:9222")
    assert "browser" in [t.get("name") for t in build_tools(["Browser"], [], vendor="openai")]


def test_browser_step_label():
    assert tool_step("browser", {"action": "open", "url": "example.com"})["step"] == "open example.com"
    assert tool_step("browser", {"action": "click", "ref": 3})["step"] == "click [3]"

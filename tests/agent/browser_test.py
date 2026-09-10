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
    for k in ("BROWSER_URL", "BROWSER_SECRET", "BROWSER_PROVIDER", "BROWSER_HUMANIZE",
              "BROWSER_PROXY", "BROWSER_PROXY_SERVER", "BROWSER_PROXY_USERNAME",
              "BROWSER_PROXY_PASSWORD"):
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


# ---- stealth (fingerprint patches applied where Chrome is driven) ----

from cycls._agent.browser import stealth


def test_chrome_ua_drops_headless_and_uses_major():
    ua = stealth.chrome_ua("141.0.7390.54")
    assert "Chrome/141.0.0.0" in ua and "Headless" not in ua
    assert stealth.chrome_ua("") .startswith("Mozilla/5.0")   # empty → a sane default major


def test_context_kwargs_shape():
    kw = stealth.context_kwargs()
    assert kw["locale"] == "en-US" and "timezone_id" in kw and "viewport" in kw
    assert "user_agent" not in kw                              # omitted unless given
    assert stealth.context_kwargs("UA/1")["user_agent"] == "UA/1"


def test_apply_registers_iife_init_script():
    """apply() must register the arrow-function source WRAPPED in an IIFE — a bare
    arrow passed to add_init_script would define, not run, the patches."""
    class _Ctx:
        def __init__(self):
            self.scripts = []
        async def add_init_script(self, script):
            self.scripts.append(script)

    ctx = _Ctx()
    asyncio.run(stealth.apply(ctx))
    assert len(ctx.scripts) == 1
    s = ctx.scripts[0]
    assert s.startswith("(") and s.rstrip().endswith(")();")   # invoked, not just defined
    assert "navigator" in s and "webdriver" in s


def test_service_js_kept_in_sync():
    """The cycls browser service duplicates _SNAPSHOT_JS / _STEALTH_JS / launch
    args (it deploys standalone). Guard the "kept in sync" contract so a patch to
    one side can't silently diverge from the other."""
    import importlib.util
    import pathlib

    svc = (pathlib.Path(__file__).resolve().parents[2]
           / "examples" / "browser_service" / "browser_service.py")
    if not svc.exists():
        pytest.skip("browser_service.py not present")
    spec = importlib.util.spec_from_file_location("_bs_sync_check", svc)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    from cycls._agent.browser import behavior
    assert m._SNAPSHOT_JS == client._SNAPSHOT_JS
    assert m._STEALTH_JS == stealth.STEALTH_JS
    assert m._STEALTH_ARGS == stealth.LAUNCH_ARGS
    # behavioral-emulation tunables mirrored into the standalone service
    assert m._MOVE_STEPS == behavior.MOVE_STEPS
    assert m._TYPE_DELAY_MS == behavior.TYPE_DELAY_MS
    assert m._PRE_DELAY_MS == behavior.PRE_DELAY_MS
    assert m._CLICK_JITTER == behavior.CLICK_JITTER


def test_session_connect_applies_stealth(monkeypatch):
    """The CDP Session applies stealth to its context before navigating (so the
    steel/cdp providers get the fingerprint patches too)."""
    import playwright.async_api as pa

    applied = {"ctx": None}

    async def _fake_apply(context):
        applied["ctx"] = context
    monkeypatch.setattr(stealth, "apply", _fake_apply)

    async def _co(v):
        return v

    class _Ctx:
        pages = []
        def set_default_timeout(self, _): pass
        def new_page(self): return _co("page")
    ctx = _Ctx()

    class _Browser:
        contexts = [ctx]
        def connect_over_cdp(self, *a, **k): return _co(self)   # placeholder

    browser_obj = types.SimpleNamespace(contexts=[ctx])
    chromium = types.SimpleNamespace(connect_over_cdp=lambda *a, **k: _co(browser_obj))
    pw = types.SimpleNamespace(chromium=chromium, stop=lambda: _co(None))
    monkeypatch.setattr(pa, "async_playwright", lambda: types.SimpleNamespace(start=lambda: _co(pw)))

    s = client.Session("ws://x")
    asyncio.run(s._connect())
    assert applied["ctx"] is ctx          # stealth applied to the connected context


# ---- behavioral emulation (human-like click/type/settle) ----

from cycls._agent.browser import behavior


async def _noop(*a, **k):
    return None


class _FakeEl:
    def __init__(self, page):
        self.page = page
    async def scroll_into_view_if_needed(self, timeout=None):
        self.page.calls.append("scroll")
    async def bounding_box(self):
        return {"x": 100, "y": 200, "width": 40, "height": 20}
    async def click(self, timeout=None):
        self.page.calls.append("el.click")
    async def fill(self, v, timeout=None):
        self.page.calls.append(("fill", v))


class _FakeMouse:
    def __init__(self, page):
        self.page = page
    async def move(self, x, y, steps=None):
        self.page.calls.append(("move", round(x), round(y)))
    async def click(self, x, y):
        self.page.calls.append("mouse.click")
    async def wheel(self, dx, dy):
        self.page.calls.append(("wheel", dy))


class _FakeKeyboard:
    def __init__(self, page):
        self.page = page
    async def type(self, ch):
        self.page.calls.append(("key", ch))


class _FakePage:
    viewport_size = {"width": 1280, "height": 800}

    def __init__(self):
        self.calls = []
        self.mouse = _FakeMouse(self)
        self.keyboard = _FakeKeyboard(self)

    def locator(self, sel):
        return types.SimpleNamespace(first=_FakeEl(self))


def test_behavior_enabled_env(monkeypatch):
    monkeypatch.delenv("BROWSER_HUMANIZE", raising=False)
    assert behavior.enabled() is True
    monkeypatch.setenv("BROWSER_HUMANIZE", "0")
    assert behavior.enabled() is False


def test_human_click_moves_then_clicks(monkeypatch):
    monkeypatch.setattr(behavior, "_sleep_ms", _noop)
    p = _FakePage()
    asyncio.run(behavior.human_click(p, '[data-cy-ref="1"]', 1000))
    assert "scroll" in p.calls
    assert any(isinstance(c, tuple) and c[0] == "move" for c in p.calls)   # cursor approach
    assert "el.click" in p.calls                                           # reliable click (actionability)


def test_human_type_focuses_clears_then_types(monkeypatch):
    monkeypatch.setattr(behavior, "_sleep_ms", _noop)
    p = _FakePage()
    asyncio.run(behavior.human_type(p, '[data-cy-ref="2"]', "hi", 1000))
    assert "el.click" in p.calls and ("fill", "") in p.calls               # focus + clear
    keys = [c for c in p.calls if isinstance(c, tuple) and c[0] == "key"]
    assert keys == [("key", "h"), ("key", "i")]                            # per-character


def test_human_settle_moves_and_scrolls(monkeypatch):
    monkeypatch.setattr(behavior, "_sleep_ms", _noop)
    p = _FakePage()
    asyncio.run(behavior.human_settle(p))
    assert any(isinstance(c, tuple) and c[0] == "move" for c in p.calls)
    assert any(isinstance(c, tuple) and c[0] == "wheel" for c in p.calls)


# ---- proxy plumbing (the IP layer — operator supplies the pool) ----

def test_proxy_config_none_when_unset():
    assert client._proxy_config() is None


def test_proxy_config_split_env(monkeypatch):
    monkeypatch.setenv("BROWSER_PROXY_SERVER", "http://gw.example:8000")
    monkeypatch.setenv("BROWSER_PROXY_USERNAME", "u")
    monkeypatch.setenv("BROWSER_PROXY_PASSWORD", "p")
    assert client._proxy_config() == {
        "server": "http://gw.example:8000", "username": "u", "password": "p"}


def test_proxy_config_url_form(monkeypatch):
    monkeypatch.setenv("BROWSER_PROXY", "http://user:pass@gw.example:9000")
    assert client._proxy_config() == {
        "server": "http://gw.example:9000", "username": "user", "password": "pass"}


def test_session_body_carries_proxy(monkeypatch):
    assert client._session_body() == {}
    monkeypatch.setenv("BROWSER_PROXY_SERVER", "http://gw:1")
    assert client._session_body() == {"proxy": {"server": "http://gw:1"}}


def test_rest_session_forwards_proxy_on_create(monkeypatch):
    """RestSession sends the configured proxy to the service at session-create."""
    monkeypatch.setenv("BROWSER_PROXY_SERVER", "http://gw:7")
    captured = {}

    class _H:
        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return _FakeResp(200, {"id": "sid-9"})

    s = client.RestSession("https://svc", "sek", "u1")
    s._http = _H()
    asyncio.run(s._ensure_session())
    assert captured["json"] == {"proxy": {"server": "http://gw:7"}}
    assert s._sid == "sid-9"


def test_service_env_proxy(monkeypatch):
    import importlib.util
    import pathlib
    svc = (pathlib.Path(__file__).resolve().parents[2]
           / "examples" / "browser_service" / "browser_service.py")
    if not svc.exists():
        pytest.skip("browser_service.py not present")
    spec = importlib.util.spec_from_file_location("_bs_proxy", svc)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m._env_proxy() is None
    monkeypatch.setenv("BROWSER_PROXY_SERVER", "http://s:1")
    monkeypatch.setenv("BROWSER_PROXY_USERNAME", "x")
    assert m._env_proxy() == {"server": "http://s:1", "username": "x"}

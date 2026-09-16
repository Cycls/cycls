"""Phase 3 — the Design tool: the cycls-design service client, the tool executor,
gating, and label. Pure logic — no service is contacted (httpx mocked). The live
render is proven separately against the real cycls-design service."""
import asyncio
import base64
import json
import types

import pytest

from cycls._agent import design
from cycls._agent.design import client
from cycls._agent.tools import _exec_design, build_tools, tool_step


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for k in ("DESIGN_URL", "DESIGN_SECRET"):
        monkeypatch.delenv(k, raising=False)


# ---- configured() gate ----

def test_configured_needs_url(monkeypatch):
    assert design.configured() is False                       # nothing set
    monkeypatch.setenv("DESIGN_URL", "https://cycls-design.cycls.ai")
    assert design.configured() is True                        # secret optional


# ---- client HTTP path (mocked) ----

class _FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        if self._p is None:
            raise ValueError("no json")
        return self._p

    @property
    def text(self):
        return json.dumps(self._p)


class _FakeClient:
    last = {}

    def __init__(self, resp, **_):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeClient.last = {"url": url, "headers": headers or {}, "json": json}
        return self._resp


def _mock(monkeypatch, resp):
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **k: _FakeClient(resp, **k))


def _ok(image=b"\x89PNG", fig=b"FIGB"):
    return {"ok": True, "frameId": "0:6", "format": "png",
            "image_base64": base64.b64encode(image).decode(),
            "fig_base64": base64.b64encode(fig).decode()}


def test_render_posts_and_decodes(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d.cycls.ai/")     # trailing slash trimmed
    monkeypatch.setenv("DESIGN_SECRET", "sek")
    _mock(monkeypatch, _FakeResp(200, _ok(b"\x89PNGdata", b"figdata")))
    img, fig, fid, fmt = asyncio.run(design.render({"size": [1080, 1080]}, fmt="png", scale=2, user_id="org:u"))
    assert img == b"\x89PNGdata" and fig == b"figdata" and fid == "0:6" and fmt == "png"
    last = _FakeClient.last
    assert last["url"] == "https://d.cycls.ai/render"
    assert last["headers"]["Authorization"] == "Bearer sek"
    assert last["headers"]["X-User-Id"] == "org:u"             # attribution, not auth
    assert last["json"] == {"spec": {"size": [1080, 1080]}, "format": "png", "scale": 2}


def test_eval_posts_script(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d.cycls.ai")
    _mock(monkeypatch, _FakeResp(200, _ok()))
    asyncio.run(design.evaluate("console.log('__FRAME__0:1')", fmt="pptx", scale=1))
    assert _FakeClient.last["url"].endswith("/eval")
    assert _FakeClient.last["json"]["script"].startswith("console.log")
    assert "Authorization" not in _FakeClient.last["headers"]  # no secret set


def test_render_unconfigured_raises():
    with pytest.raises(design.Unavailable):
        asyncio.run(design.render({"size": [1, 1]}))


def test_401_is_unavailable(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    monkeypatch.setenv("DESIGN_SECRET", "bad")
    _mock(monkeypatch, _FakeResp(401, {"ok": False, "error": "unauthorized"}))
    with pytest.raises(design.Unavailable):
        asyncio.run(design.render({}))


def test_service_error_is_runtimeerror(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(422, {"ok": False, "error": "bad spec"}))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(design.render({}))
    assert "bad spec" in str(ei.value)
    assert not isinstance(ei.value, design.Unavailable)        # service is up → a plain error


# ---- the Design tool (executor + gating + label), with render faked ----

def _ws(tmp_path):
    return types.SimpleNamespace(root=str(tmp_path), subject="org_1:user_1")


def _fake_render(monkeypatch, image=b"\x89PNGrender", fig=b"FIGZ"):
    calls = {}

    async def _r(spec, fmt="png", scale=2, user_id=None):
        calls.update(spec=spec, fmt=fmt, scale=scale, user_id=user_id)
        return image, fig, "0:6", fmt

    monkeypatch.setattr("cycls._agent.design.render", _r)
    return calls


def test_render_saves_and_opens_canvas(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design(
        {"action": "render", "name": "launch", "spec": {"size": [1080, 1080]}, "format": "png"},
        _ws(tmp_path)))
    assert (tmp_path / "designs" / "launch.png").read_bytes() == b"\x89PNGrender"
    assert (tmp_path / "designs" / "launch.fig").read_bytes() == b"FIGZ"   # editable source beside it
    assert calls["user_id"] == "org_1:user_1" and calls["spec"] == {"size": [1080, 1080]}
    assert "saved to designs/launch.png" in out["_model"] and "canvas" in out["_model"]
    ui = out["_ui"]
    assert ui["action"] == "open_canvas" and ui["path"] == "designs/launch.png" and ui["name"] == "launch.png"


def test_script_escape_hatch(tmp_path, monkeypatch):
    got = {}

    async def _e(script, fmt="png", scale=2, user_id=None):
        got.update(script=script, fmt=fmt)
        return b"PPTX", b"FIG", "0:1", fmt

    monkeypatch.setattr("cycls._agent.design.evaluate", _e)
    out = asyncio.run(_exec_design(
        {"action": "script", "name": "deck", "script": "console.log('__FRAME__0:1')", "format": "pptx"},
        _ws(tmp_path)))
    assert (tmp_path / "designs" / "deck.pptx").read_bytes() == b"PPTX"
    assert got["script"].startswith("console.log") and out["_ui"]["path"] == "designs/deck.pptx"


def test_arg_validation(tmp_path, monkeypatch):
    _fake_render(monkeypatch)
    ws = _ws(tmp_path)
    assert asyncio.run(_exec_design({"action": "render"}, ws)).startswith("Error")                       # no spec
    assert asyncio.run(_exec_design({"action": "script"}, ws)).startswith("Error")                       # no script
    assert asyncio.run(_exec_design({"action": "render", "spec": {}, "format": "gif"}, ws)).startswith("Error")  # bad fmt
    assert asyncio.run(_exec_design({"action": "nope"}, ws)).startswith("Error")                         # unknown


def test_executor_reports_unavailable(tmp_path, monkeypatch):
    async def _boom(*a, **k):
        raise design.Unavailable("service down")
    monkeypatch.setattr("cycls._agent.design.render", _boom)
    out = asyncio.run(_exec_design({"action": "render", "spec": {}}, _ws(tmp_path)))
    assert out.startswith("Error: design unavailable")


def test_name_is_sanitized(tmp_path, monkeypatch):
    _fake_render(monkeypatch)
    out = asyncio.run(_exec_design(
        {"action": "render", "spec": {}, "name": "../../evil.png"}, _ws(tmp_path)))
    # basename only, extension stripped → designs/evil.png, no traversal out of the workspace
    assert out["_ui"]["path"] == "designs/evil.png"
    assert (tmp_path / "designs" / "evil.png").exists()


def test_build_tools_gates_on_configured(monkeypatch):
    monkeypatch.delenv("DESIGN_URL", raising=False)
    assert "design" not in [t.get("name") for t in build_tools(["Design"], [], vendor="openai")]
    monkeypatch.setenv("DESIGN_URL", "https://cycls-design.cycls.ai")
    assert "design" in [t.get("name") for t in build_tools(["Design"], [], vendor="openai")]


def test_design_step_label():
    assert tool_step("design", {"action": "render", "name": "launch"})["step"] == "render launch"

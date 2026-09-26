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
    for k in ("DESIGN_URL", "DESIGN_SECRET", "DESIGN_EDITOR_URL"):
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


def _text(out):
    """The ack the model reads — a raster render is [image, text], else a string."""
    m = out["_model"]
    return m if isinstance(m, str) else next(b["text"] for b in m if b["type"] == "text")


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
    assert "saved to designs/launch.png" in _text(out) and "canvas" in _text(out)
    ui = out["_ui"]
    assert ui["action"] == "open_canvas" and ui["path"] == "designs/launch.png" and ui["name"] == "launch.png"


def test_render_opens_the_fig_editor_when_editor_configured(tmp_path, monkeypatch):
    # With an editor wired up (DESIGN_EDITOR_URL), a render lands the user directly in
    # the editable .fig editor — not a flat PNG — so any design is immediately editable.
    monkeypatch.setenv("DESIGN_EDITOR_URL", "https://cycls-design.cycls.ai")
    _fake_render(monkeypatch)
    out = asyncio.run(_exec_design(
        {"action": "render", "name": "launch", "spec": {"size": [1080, 1080]}, "format": "png"},
        _ws(tmp_path)))
    # both files still saved; the canvas opens the EDITABLE .fig, not the image
    assert (tmp_path / "designs" / "launch.png").read_bytes() == b"\x89PNGrender"
    assert (tmp_path / "designs" / "launch.fig").read_bytes() == b"FIGZ"
    ui = out["_ui"]
    assert ui["action"] == "open_canvas" and ui["path"] == "designs/launch.fig" and ui["name"] == "launch.fig"
    assert "designs/launch.fig" in _text(out) and "editor" in _text(out)


def test_render_dedupes_name_so_nothing_overwrites(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    _fake_render(monkeypatch, image=b"FIRST", fig=b"FIRSTFIG")
    out1 = asyncio.run(_exec_design({"action": "render", "name": "launch", "spec": {}}, ws))
    assert out1["_ui"]["path"] == "designs/launch.png"

    # Same name again → bumped to launch-2; the first pair is left untouched.
    _fake_render(monkeypatch, image=b"SECOND", fig=b"SECONDFIG")
    out2 = asyncio.run(_exec_design({"action": "render", "name": "launch", "spec": {}}, ws))
    assert out2["_ui"]["path"] == "designs/launch-2.png"
    assert out2["_ui"]["name"] == "launch-2.png"
    assert "launch-2" in _text(out2) and "launch" in _text(out2)         # ack explains the rename
    assert (tmp_path / "designs" / "launch.png").read_bytes() == b"FIRST"        # untouched
    assert (tmp_path / "designs" / "launch.fig").read_bytes() == b"FIRSTFIG"     # untouched
    assert (tmp_path / "designs" / "launch-2.png").read_bytes() == b"SECOND"
    assert (tmp_path / "designs" / "launch-2.fig").read_bytes() == b"SECONDFIG"

    # A third, even in a different format, still dedupes off the shared .fig base.
    _fake_render(monkeypatch, image=b"THIRD", fig=b"THIRDFIG")
    out3 = asyncio.run(_exec_design({"action": "render", "name": "launch", "spec": {}, "format": "webp"}, ws))
    assert out3["_ui"]["path"] == "designs/launch-3.webp"


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


def test_edit_sends_design_command(tmp_path, monkeypatch):
    # `edit` drives the LIVE editor — no service is contacted; it emits a
    # `design_command` UI event the FE forwards to the open .fig's editor.
    called = {"n": 0}

    async def _r(*a, **k):
        called["n"] += 1
    monkeypatch.setattr("cycls._agent.design.render", _r)
    monkeypatch.setattr("cycls._agent.design.evaluate", _r)

    script = "const t=figma.currentPage.children[0]; t.fills=[{type:'SOLID',color:{r:0,g:0,b:0}}]; figma.currentPage.selection=[t]"
    out = asyncio.run(_exec_design(
        {"action": "edit", "name": "launch", "script": script, "intent": "darken the background"},
        _ws(tmp_path)))
    assert called["n"] == 0                                     # never hits the render service
    ui = out["_ui"]
    assert ui["action"] == "design_command" and ui["path"] == "designs/launch.fig" and ui["script"] == script
    assert ui["intent"] == "darken the background"             # narrated on the live cursor
    assert "designs/launch.fig" in out["_model"]               # ack names the open design

    # intent is optional — omit it and the key simply isn't sent.
    out2 = asyncio.run(_exec_design({"action": "edit", "name": "launch", "script": script}, _ws(tmp_path)))
    assert "intent" not in out2["_ui"]


def test_edit_needs_script(tmp_path):
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch"}, _ws(tmp_path)))
    assert out.startswith("Error")                             # no script → nothing to apply


def test_edit_name_is_sanitized(tmp_path):
    out = asyncio.run(_exec_design(
        {"action": "edit", "name": "../../evil", "script": "figma.root"}, _ws(tmp_path)))
    assert out["_ui"]["path"] == "designs/evil.fig"            # basename only, no traversal


def test_arg_validation(tmp_path, monkeypatch):
    _fake_render(monkeypatch)
    ws = _ws(tmp_path)
    assert asyncio.run(_exec_design({"action": "render"}, ws)).startswith("Error")                       # no spec
    assert asyncio.run(_exec_design({"action": "script"}, ws)).startswith("Error")                       # no script
    assert asyncio.run(_exec_design({"action": "edit"}, ws)).startswith("Error")                         # no edit script
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


# ---- self-QA: the render comes back to the model as an image ----

def test_render_attaches_the_image_for_self_qa(tmp_path, monkeypatch):
    _fake_render(monkeypatch, image=b"\x89PNGpixels")
    out = asyncio.run(_exec_design({"action": "render", "name": "launch", "spec": {}}, _ws(tmp_path)))
    img, txt = out["_model"]
    assert img["type"] == "image" and img["source"]["media_type"] == "image/png"
    assert base64.b64decode(img["source"]["data"]) == b"\x89PNGpixels"      # the model sees its own render
    assert "QA it before you present" in txt["text"] and "a fresh render" in txt["text"]

    # With the editor wired, a fix goes through the live editor, not a re-render.
    monkeypatch.setenv("DESIGN_EDITOR_URL", "https://cycls-design.cycls.ai")
    out = asyncio.run(_exec_design({"action": "render", "name": "launch", "spec": {}}, _ws(tmp_path)))
    assert "Design edit" in _text(out)


def test_no_qa_image_for_decks_svg_or_oversized(tmp_path, monkeypatch):
    _fake_render(monkeypatch)
    ws = _ws(tmp_path)
    for fmt in ("pptx", "svg"):
        out = asyncio.run(_exec_design({"action": "render", "spec": {}, "format": fmt}, ws))
        assert isinstance(out["_model"], str) and "QA" not in out["_model"]
    monkeypatch.setattr("cycls._agent.tools._DESIGN_QA_MAX", 4)             # bigger than `read` allows
    out = asyncio.run(_exec_design({"action": "render", "spec": {}}, ws))
    assert isinstance(out["_model"], str)


# ---- size presets ----

def test_size_preset_resolves_to_pixels(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    spec = {"size": "Story", "nodes": []}
    asyncio.run(_exec_design({"action": "render", "spec": spec}, _ws(tmp_path)))
    assert calls["spec"]["size"] == [1080, 1920]
    assert spec["size"] == "Story"                                          # the model's input is untouched

    asyncio.run(_exec_design({"action": "render", "spec": {"frames": [{"size": "slide"}, {"size": [800, 600]}]},
                              "format": "pptx"}, _ws(tmp_path)))
    assert [f["size"] for f in calls["spec"]["frames"]] == [[1920, 1080], [800, 600]]   # arrays pass through


def test_unknown_size_preset_is_an_error(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": "billboard"}}, _ws(tmp_path)))
    assert out.startswith("Error") and "story" in out                       # names the valid presets
    assert calls == {}                                                      # never reached the service


# ---- auto-brand ----

def _brand(tmp_path, text):
    (tmp_path / "brand").mkdir()
    (tmp_path / "brand" / "brand.yaml").write_text(text, encoding="utf-8")


def test_brand_fills_only_what_the_spec_left_unset(tmp_path, monkeypatch):
    # As the brand-kit skill writes it (yaml.safe_dump: single-quoted hex, block list).
    _brand(tmp_path, "entity_name: Acme\nprimary_color: '#0C2340'\naccent_color: '#c9a227'\n"
                     "palette:\n- '#0c2340'\n- '#c9a227'\n")
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "text", "text": "Hi"},                         # unset → readable on the navy
        {"type": "rect", "x": 0, "y": 0, "w": 10, "h": 10},     # unset → accent
        {"type": "ellipse", "fill": "#ff0000"},                 # explicit → kept
        {"type": "text", "text": "Yo", "color": "#00ff00"},     # explicit → kept
    ]}}, _ws(tmp_path)))
    s = calls["spec"]
    assert s["fill"] == "#0c2340"
    assert [n.get("color") or n.get("fill") for n in s["nodes"]] == ["#ffffff", "#c9a227", "#ff0000", "#00ff00"]
    assert "Brand kit applied to 2 unset fill(s)" in _text(out)


def test_brand_never_overrides_an_explicit_background(tmp_path, monkeypatch):
    _brand(tmp_path, 'primary_color: "#0c2340"\n')
    calls = _fake_render(monkeypatch)
    spec = {"fill": {"gradient": ["#fafafa", "#eeeeee"]}, "nodes": [{"type": "text", "text": "x"}]}
    out = asyncio.run(_exec_design({"action": "render", "spec": spec}, _ws(tmp_path)))
    assert calls["spec"]["fill"] == spec["fill"]
    assert calls["spec"]["nodes"][0]["color"] == "#111111"                  # dark text on the light gradient
    assert "uses neither" in _text(out)                                     # off-brand → the model is told


def test_brand_reads_the_legacy_nested_shape(tmp_path, monkeypatch):
    _brand(tmp_path, "colors:\n  primary: '#abc'\n  accent: '#123456'\nlogo:\n  primary: brand/logo.png\n")
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [{"type": "line"}]}}, _ws(tmp_path)))
    assert calls["spec"]["fill"] == "#aabbcc" and calls["spec"]["nodes"][0]["fill"] == "#123456"


def test_no_brand_kit_leaves_the_spec_alone(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    spec = {"size": [1080, 1080], "nodes": [{"type": "rect"}, {"type": "text", "text": "x"}]}
    out = asyncio.run(_exec_design({"action": "render", "spec": spec}, _ws(tmp_path)))
    assert calls["spec"] == spec                                            # no fill to pick against → nothing added
    assert "brand kit" not in _text(out).lower()
    _brand(tmp_path, "primary_color: navy\n")                               # no hex primary → still no brand
    asyncio.run(_exec_design({"action": "render", "spec": spec}, _ws(tmp_path)))
    assert calls["spec"] == spec


# ---- renderer guards: what the service would silently drop or blank ----

def test_untyped_text_node_is_typed_not_dropped(tmp_path, monkeypatch):
    # A real Kimi turn left `type` off every text node — the renderer skips an untyped
    # node, so the post came back with no text at all.
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"text": "NEW ARRIVAL", "x": 140, "y": 150, "size": 26}]}}, _ws(tmp_path)))
    assert calls["spec"]["nodes"][0]["type"] == "text"


def test_unknown_node_type_is_an_error(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    for node in ({"type": "circle", "w": 10}, {"x": 0, "y": 0, "w": 10, "h": 10}):
        out = asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [node]}}, _ws(tmp_path)))
        assert out.startswith("Error") and "text, rect, ellipse or line" in out
    assert calls == {}                                                      # never rendered a silently-missing node


def test_fonts_map_onto_inter(tmp_path, monkeypatch):
    # Arial (once advertised) and any other family render the text BLANK — Inter only.
    calls = _fake_render(monkeypatch)
    fonts = ["Arial", "Arial Bold", "Playfair Display SemiBold", "Montserrat Black", "Inter Medium", "Lato Light"]
    out = asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "text", "text": "x", "font": f} for f in fonts]}}, _ws(tmp_path)))
    assert [n["font"] for n in calls["spec"]["nodes"]] == [
        "Inter Regular", "Inter Bold", "Inter Bold", "Inter Black", "Inter Medium", "Inter Light"]
    assert "Arial → Inter Regular" in _text(out) and "Inter Medium →" not in _text(out)   # only real changes named

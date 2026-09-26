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
    img, fig, fid, fmt, preview, notes = asyncio.run(design.render({"size": [1080, 1080]}, fmt="png", scale=2, user_id="org:u"))
    assert img == b"\x89PNGdata" and fig == b"figdata" and fid == "0:6" and fmt == "png"
    assert preview is None and notes == []                     # a service that predates previews / notes
    last = _FakeClient.last
    assert last["url"] == "https://d.cycls.ai/render"
    assert last["headers"]["Authorization"] == "Bearer sek"
    assert last["headers"]["X-User-Id"] == "org:u"             # attribution, not auth
    assert last["json"] == {"spec": {"size": [1080, 1080]}, "format": "png", "scale": 2, "preview": True}


def test_render_decodes_the_qa_preview(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(200, {**_ok(), "preview_base64": base64.b64encode(b"JPEGsmall").decode()}))
    assert asyncio.run(design.render({}))[4] == b"JPEGsmall"


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


def _fake_render(monkeypatch, image=b"\x89PNGrender", fig=b"FIGZ", preview=None, notes=()):
    calls = {}

    async def _r(spec, fmt="png", scale=2, user_id=None):
        calls.update(spec=spec, fmt=fmt, scale=scale, user_id=user_id)
        return image, fig, "0:6", fmt, preview, list(notes)

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
        return b"PPTX", b"FIG", "0:1", fmt, None, []

    monkeypatch.setattr("cycls._agent.design.evaluate", _e)
    out = asyncio.run(_exec_design(
        {"action": "script", "name": "deck", "script": "console.log('__FRAME__0:1')", "format": "pptx"},
        _ws(tmp_path)))
    assert (tmp_path / "designs" / "deck.pptx").read_bytes() == b"PPTX"
    assert got["script"].startswith("console.log") and out["_ui"]["path"] == "designs/deck.pptx"


def _fake_apply(monkeypatch, result=b"EDITED-FIG", error=None):
    """`design.apply` faked: records the call, returns the edited .fig or raises the
    script's error. `refresh.schedule` is captured instead of run."""
    calls = {}

    async def _apply(fig, script, user_id=None):
        calls.update(fig=fig, script=script, user_id=user_id)
        if error:
            raise RuntimeError(error)
        return result
    monkeypatch.setattr("cycls._agent.design.apply", _apply)
    scheduled = []
    monkeypatch.setattr("cycls._agent.design.refresh.schedule",
                        lambda root, rel, user_id=None: scheduled.append(rel))
    return calls, scheduled


def _design(tmp_path, name="launch", data=b"ORIGINAL-FIG"):
    (tmp_path / "designs").mkdir(exist_ok=True)
    (tmp_path / "designs" / f"{name}.fig").write_bytes(data)


def test_edit_applies_saves_and_replays(tmp_path, monkeypatch):
    # `edit` runs the script on the saved .fig first (the editor's plugin API,
    # headless), saves the result and re-exports its image — whether or not an editor
    # is open — then replays it in the live editor with the Super cursor.
    _design(tmp_path)
    calls, scheduled = _fake_apply(monkeypatch)
    script = "const t=figma.currentPage.children[0]; t.fills=[{type:'SOLID',color:{r:0,g:0,b:0}}]; figma.currentPage.selection=[t]"
    out = asyncio.run(_exec_design(
        {"action": "edit", "name": "launch", "script": script, "intent": "darken the background"},
        _ws(tmp_path)))
    assert calls["fig"] == b"ORIGINAL-FIG" and calls["script"] == script and calls["user_id"] == "org_1:user_1"
    assert (tmp_path / "designs" / "launch.fig").read_bytes() == b"EDITED-FIG"   # persisted
    assert scheduled == ["designs/launch.fig"]                                    # the image follows
    ui = out["_ui"]
    assert ui["action"] == "design_command" and ui["path"] == "designs/launch.fig" and ui["script"] == script
    assert ui["intent"] == "darken the background"             # narrated on the live cursor
    assert "applied and saved to designs/launch.fig" in out["_model"]

    # intent is optional — omit it and the key simply isn't sent.
    out2 = asyncio.run(_exec_design({"action": "edit", "name": "launch", "script": script}, _ws(tmp_path)))
    assert "intent" not in out2["_ui"]


def test_edit_script_error_reaches_the_model(tmp_path, monkeypatch):
    # A script that throws used to fail silently inside the browser while the model
    # said "done". Now the model reads the script's own error and nothing changes.
    _design(tmp_path)
    _, scheduled = _fake_apply(monkeypatch, error="null is not an object (evaluating 't.characters = \"x\"')")
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "script": "t.characters='x'"}, _ws(tmp_path)))
    assert isinstance(out, str) and out.startswith("Error") and "null is not an object" in out
    assert (tmp_path / "designs" / "launch.fig").read_bytes() == b"ORIGINAL-FIG"
    assert scheduled == []                                      # no replay, no re-export


def test_edit_needs_a_rendered_design(tmp_path, monkeypatch):
    calls, _ = _fake_apply(monkeypatch)
    out = asyncio.run(_exec_design({"action": "edit", "name": "nope", "script": "figma.root"}, _ws(tmp_path)))
    assert out.startswith("Error") and "doesn't exist" in out and calls == {}


def test_edit_needs_script(tmp_path):
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch"}, _ws(tmp_path)))
    assert out.startswith("Error")                             # no script → nothing to apply


def test_edit_name_is_sanitized(tmp_path, monkeypatch):
    _design(tmp_path, "evil")
    _fake_apply(monkeypatch)
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
        assert out.startswith("Error") and "text, rect, ellipse, line or image" in out
    assert calls == {}                                                      # never rendered a silently-missing node


def test_fonts_go_to_the_service_as_written(tmp_path, monkeypatch):
    # The service resolves any Google Font (and swaps what isn't open); the SDK no
    # longer forces Inter — that guard hid a working capability.
    calls = _fake_render(monkeypatch, notes=["Arial isn't an open font; used Arimo, its closest open match"])
    fonts = ["Playfair Display Bold", {"family": "Cairo", "style": "Semi Bold"}, "Arial"]
    out = asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "text", "text": "x", "font": f, "weight": 800} for f in fonts]}}, _ws(tmp_path)))
    assert [n["font"] for n in calls["spec"]["nodes"]] == fonts
    assert all(n["weight"] == 800 for n in calls["spec"]["nodes"])          # weight / italic ride along
    assert "used Arimo" in _text(out)                                     # the service's note reaches the model


def test_brand_fonts_fill_only_unset_fonts(tmp_path, monkeypatch):
    _brand(tmp_path, "primary_color: '#0c2340'\nfont_heading: Playfair Display\nfont_body: \"DM Sans\"\n")
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "text", "text": "Big", "size": 96},                     # display size → heading face
        {"type": "text", "text": "small", "size": 28},                   # body
        {"type": "text", "text": "mine", "size": 96, "font": "Bebas Neue"},   # explicit → kept
    ]}}, _ws(tmp_path)))
    assert [n["font"] for n in calls["spec"]["nodes"]] == ["Playfair Display", "DM Sans", "Bebas Neue"]
    assert "Brand fonts applied to 2 text node(s)" in _text(out)


def test_a_fonts_only_brand_kit_leaves_colours_alone(tmp_path, monkeypatch):
    _brand(tmp_path, "fonts:\n  heading: Cairo\n  body: Tajawal\n")
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "rect", "w": 10, "h": 10}, {"type": "text", "text": "x", "size": 20}]}}, _ws(tmp_path)))
    s = calls["spec"]
    assert "fill" not in s and "fill" not in s["nodes"][0]                # no colours to apply
    assert s["nodes"][1]["font"] == "Tajawal"



# ---- the QA look prefers the service's small preview ----

def test_qa_uses_the_preview_even_when_the_render_is_huge(tmp_path, monkeypatch):
    _fake_render(monkeypatch, image=b"\x89PNG" + b"x" * 64, preview=b"\xff\xd8JPEGpreview")
    monkeypatch.setattr("cycls._agent.tools._DESIGN_QA_MAX", 32)             # the @2x PNG is over the bound
    img, txt = asyncio.run(_exec_design({"action": "render", "spec": {}}, _ws(tmp_path)))["_model"]
    assert img["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(img["source"]["data"]) == b"\xff\xd8JPEGpreview"
    assert (tmp_path / "designs" / "design.png").read_bytes().startswith(b"\x89PNG")   # the saved render is full size


def test_a_deck_gets_its_first_slide_to_qa(tmp_path, monkeypatch):
    _fake_render(monkeypatch, image=b"PPTX", preview=b"\xff\xd8slide1")
    img, txt = asyncio.run(_exec_design({"action": "render", "spec": {"frames": [{}]}, "format": "pptx"},
                                        _ws(tmp_path)))["_model"]
    assert base64.b64decode(img["source"]["data"]) == b"\xff\xd8slide1" and "first slide" in txt["text"]


# ---- images ----

import struct
from cycls._agent.tools import _image_size


def _png(w, h):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00" + b"\x00" * 8


def _jpeg(w, h, orientation=None):
    out = b"\xff\xd8"
    if orientation:
        tiff = b"II*\x00\x08\x00\x00\x00" + struct.pack("<H", 1) + struct.pack("<HHIHH", 0x0112, 3, 1, orientation, 0) + b"\x00" * 4
        out += b"\xff\xe1" + struct.pack(">H", 2 + 6 + len(tiff)) + b"Exif\x00\x00" + tiff
    out += b"\xff\xdb" + struct.pack(">H", 4) + b"\x00\x00"                       # a DQT to skip
    return out + b"\xff\xc2" + struct.pack(">HBHHB", 11, 8, h, w, 3) + b"\x00" * 9   # progressive SOF2


def test_image_size_reads_headers():
    assert _image_size(_png(1600, 900)) == (1600, 900)
    assert _image_size(b"GIF89a" + struct.pack("<HH", 32, 16) + b"\x00" * 8) == (32, 16)
    assert _image_size(_jpeg(4032, 3024)) == (4032, 3024)
    assert _image_size(_jpeg(4032, 3024, orientation=6)) == (3024, 4032)     # a portrait phone photo: drawn turned
    assert _image_size(_jpeg(4032, 3024, orientation=3)) == (4032, 3024)     # 180° keeps the shape
    riff = lambda chunk: b"RIFF" + b"\x00" * 4 + b"WEBP" + chunk
    assert _image_size(riff(b"VP8X" + b"\x00" * 8 + (1199).to_bytes(3, "little") + (799).to_bytes(3, "little"))) == (1200, 800)
    assert _image_size(riff(b"VP8L" + b"\x00" * 5 + ((640 - 1) | (480 - 1) << 14).to_bytes(4, "little"))) == (640, 480)
    assert _image_size(riff(b"VP8 " + b"\x00" * 10 + struct.pack("<HH", 300, 200))) == (300, 200)
    assert _image_size(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None


def _img(tmp_path, rel, data):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return data


def test_image_cover_ships_bytes_in_the_box(tmp_path, monkeypatch):
    data = _img(tmp_path, "attachments/photo.png", _png(1600, 900))
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "src": "attachments/photo.png", "x": 0, "y": 0, "w": 1080, "h": 1080, "radius": 24}]}},
        _ws(tmp_path)))
    n = calls["spec"]["nodes"][0]
    assert base64.b64decode(n["image"]) == data and "src" not in n
    assert (n["x"], n["y"], n["w"], n["h"], n["radius"]) == (0, 0, 1080, 1080, 24)   # cover keeps the box


def test_image_missing_side_follows_the_aspect(tmp_path, monkeypatch):
    _img(tmp_path, "logo.png", _png(400, 100))
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "image", "src": "logo.png", "x": 10, "y": 10, "w": 200},
        {"src": "logo.png", "h": 50}]}}, _ws(tmp_path)))                # untyped + src → an image
    a, b = calls["spec"]["nodes"]
    assert (a["w"], a["h"]) == (200, 50) and (b["type"], b["w"], b["h"]) == ("image", 200, 50)


def test_image_contain_centres_the_whole_image(tmp_path, monkeypatch):
    _img(tmp_path, "brand/logo.png", _png(1128, 191))
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "image", "src": "brand/logo.png", "x": 90, "y": 60, "w": 900, "h": 400, "fit": "contain"}]}},
        _ws(tmp_path)))
    n = calls["spec"]["nodes"][0]
    assert n["w"] == 900 and n["h"] == round(191 * 900 / 1128, 2)          # the image's aspect, full width
    assert n["x"] == 90 and abs(n["y"] - (60 + (400 - 191 * 900 / 1128) / 2)) < 1e-6   # centred vertically
    assert "fit" not in n


def test_image_errors_name_the_fix(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    ws = _ws(tmp_path)
    _img(tmp_path, "logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    _img(tmp_path, "p.png", _png(10, 10))
    def err(node):
        out = asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [{"type": "image", **node}]}}, ws))
        assert isinstance(out, str) and out.startswith("Error"), out
        return out
    assert "workspace file" in err({"w": 10})                                       # no src
    assert "does not exist" in err({"src": "nope.png", "w": 10})
    assert "escapes" in err({"src": "../../etc/passwd", "w": 10})                   # traversal
    assert "save it into the workspace" in err({"src": "https://x.com/a.png", "w": 10})
    assert "SVG" in err({"src": "logo.svg", "w": 10})
    assert "w` and/or `h" in err({"src": "p.png"})
    assert "cover or contain" in err({"src": "p.png", "w": 10, "fit": "stretch"})
    monkeypatch.setattr("cycls._agent.tools._DESIGN_IMAGE_MAX", 8)
    assert "smaller copy" in err({"src": "p.png", "w": 10})
    assert calls == {}                                                             # none reached the service


def test_images_have_a_total_budget(tmp_path, monkeypatch):
    _img(tmp_path, "a.png", _png(10, 10))
    calls = _fake_render(monkeypatch)
    monkeypatch.setattr("cycls._agent.tools._DESIGN_IMAGES_MAX", 40)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "image", "src": "a.png", "w": 10}, {"type": "image", "src": "a.png", "w": 10}]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "total" in out and calls == {}


def test_brand_never_fills_an_image(tmp_path, monkeypatch):
    _brand(tmp_path, 'primary_color: "#0c2340"\naccent_color: "#c9a227"\n')
    _img(tmp_path, "a.png", _png(10, 10))
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [{"type": "image", "src": "a.png", "w": 10}]}},
                             _ws(tmp_path)))
    assert "fill" not in calls["spec"]["nodes"][0]


def test_a_shape_color_is_its_fill(tmp_path, monkeypatch):
    # A live turn wrote `color` on a divider line — a shape draws `fill` only, so it came
    # out black (or brand-accent). Shapes take either, as text does.
    _brand(tmp_path, 'primary_color: "#0c2340"\naccent_color: "#c9a227"\n')
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "line", "w": 120, "color": "#3d2b1f"}, {"type": "rect", "fill": "#ff0000", "color": "#00ff00"}]}},
        _ws(tmp_path)))
    line, rect = calls["spec"]["nodes"]
    assert line["fill"] == "#3d2b1f" and "color" not in line               # the model's colour, not the accent
    assert rect["fill"] == "#ff0000"                                        # an explicit fill wins


# ---- an edited .fig re-exports the image beside it ----

from cycls._agent.design import refresh


def test_export_posts_the_fig(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(200, {"ok": True, "format": "png", "image_base64": base64.b64encode(b"NEWPNG").decode()}))
    assert asyncio.run(design.export(b"FIGBYTES", fmt="png", width=2160, user_id="u")) == b"NEWPNG"
    last = _FakeClient.last
    assert last["url"] == "https://d/export"
    assert last["json"] == {"fig": base64.b64encode(b"FIGBYTES").decode(), "format": "png", "scale": 2, "width": 2160}


def _refresh_env(tmp_path, monkeypatch, fail=False):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    monkeypatch.setattr(refresh, "DELAY", 0.05)
    calls = []

    async def _export(fig, fmt="png", scale=2, width=None, user_id=None):
        calls.append({"fig": fig, "fmt": fmt, "width": width, "user_id": user_id})
        if fail:
            raise RuntimeError("service down")
        return f"NEW-{fmt}".encode()
    monkeypatch.setattr(refresh, "export", _export)
    d = tmp_path / "designs"
    d.mkdir()
    (d / "launch.fig").write_bytes(b"EDITED-FIG")
    (d / "launch.png").write_bytes(_png(2160, 2160))
    (d / "launch.pptx").write_bytes(b"OLD-PPTX")
    return calls


def _saves(root, *rels):
    async def go():
        for rel in rels:
            refresh.schedule(root, rel, "org:u")
        tasks = [t for t in refresh._pending.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(go())


def test_saved_fig_reexports_its_existing_images(tmp_path, monkeypatch):
    calls = _refresh_env(tmp_path, monkeypatch)
    _saves(tmp_path, "designs/launch.fig")
    d = tmp_path / "designs"
    assert (d / "launch.png").read_bytes() == b"NEW-png" and (d / "launch.pptx").read_bytes() == b"NEW-pptx"
    assert not (d / "launch.jpg").exists()                                  # only images already beside it
    by = {c["fmt"]: c for c in calls}
    assert set(by) == {"png", "pptx"} and by["png"]["fig"] == b"EDITED-FIG"
    assert by["png"]["width"] == 2160 and by["pptx"]["width"] is None       # a raster keeps its resolution
    assert by["png"]["user_id"] == "org:u"
    assert refresh._pending == {}


def test_a_burst_of_saves_exports_once(tmp_path, monkeypatch):
    calls = _refresh_env(tmp_path, monkeypatch)
    _saves(tmp_path, "designs/launch.fig", "designs/launch.fig", "designs/launch.fig")
    assert sorted(c["fmt"] for c in calls) == ["png", "pptx"]               # debounced: the last save only


def test_reexport_failure_keeps_the_old_image(tmp_path, monkeypatch):
    _refresh_env(tmp_path, monkeypatch, fail=True)
    old = (tmp_path / "designs" / "launch.png").read_bytes()
    _saves(tmp_path, "designs/launch.fig")                                  # logs, never raises
    assert (tmp_path / "designs" / "launch.png").read_bytes() == old


def test_only_design_figs_reexport(tmp_path, monkeypatch):
    calls = _refresh_env(tmp_path, monkeypatch)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "logo.fig").write_bytes(b"FIG")
    (tmp_path / "notes" / "logo.png").write_bytes(_png(10, 10))             # a user's own pair — never overwritten
    _saves(tmp_path, "notes/logo.fig", "designs/launch.png")
    assert calls == [] and (tmp_path / "notes" / "logo.png").read_bytes() == _png(10, 10)
    monkeypatch.delenv("DESIGN_URL")                                        # no service → nothing to do
    _saves(tmp_path, "designs/launch.fig")
    assert calls == []


# ---- layouts that would silently pile up at the frame edge ----

def test_quoted_numbers_are_numbers(tmp_path, monkeypatch):
    # A string y reached the renderer as "1300": its bounds check concatenated strings and
    # clamped EVERY text box to the bottom — the whole post piled up (a live prod turn).
    calls = _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1920], "nodes": [
        {"type": "text", "text": "Hi", "x": "90", "y": "1300", "size": "96px", "opacity": "0.8"}]}}, _ws(tmp_path)))
    n = calls["spec"]["nodes"][0]
    assert (n["x"], n["y"], n["size"], n["opacity"]) == (90, 1300, 96, 0.8)


def test_a_non_number_is_an_error(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "text", "text": "Hi", "y": "50%"}]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "`y` must be a number" in out and calls == {}


def test_size_shapes_resolve(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    for spec, want in (({"size": "1080x1920"}, [1080, 1920]), ({"size": {"w": 800, "h": "600"}}, [800, 600]),
                       ({"width": 1200, "height": 627}, [1200, 627]), ({}, [1080, 1080])):
        asyncio.run(_exec_design({"action": "render", "spec": spec}, _ws(tmp_path)))
        assert calls["spec"]["size"] == want and "width" not in calls["spec"]
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [0, 5]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "isn't a size" in out


def test_content_outside_the_frame_is_an_error(tmp_path, monkeypatch):
    # A story laid out in a frame left at the 1080² default: the renderer would clamp every
    # box below 1080 up to the bottom edge. Name the frame size instead.
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"nodes": [
        {"type": "text", "text": "EYEBROW", "x": 90, "y": 200},
        {"type": "text", "text": "Big Headline", "x": 90, "y": 1300}]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "'Big Headline'" in out and "1080×1080" in out and "story" in out
    _img(tmp_path, "a.png", _png(10, 10))
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": "square", "nodes": [
        {"type": "image", "src": "a.png", "x": 1200, "y": 0, "w": 100}]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "an image" in out
    assert calls == {}
    # Bleeding past an edge (a decorative circle, text the clamp nudges back in) is fine.
    asyncio.run(_exec_design({"action": "render", "spec": {"size": "square", "nodes": [
        {"type": "ellipse", "x": 900, "y": -200, "w": 600, "h": 600},
        {"type": "text", "text": "Hi", "x": -20, "y": 1000, "w": 400}]}}, _ws(tmp_path)))
    assert len(calls["spec"]["nodes"]) == 2


def test_apply_posts_fig_and_script(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(200, {"ok": True, "fig_base64": base64.b64encode(b"EDITED").decode()}))
    assert asyncio.run(design.apply(b"FIG", "t.characters='x'", user_id="u")) == b"EDITED"
    assert _FakeClient.last["url"] == "https://d/apply"
    assert _FakeClient.last["json"] == {"fig": base64.b64encode(b"FIG").decode(), "script": "t.characters='x'"}
    _mock(monkeypatch, _FakeResp(422, {"ok": False, "error": "null is not an object"}))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(design.apply(b"FIG", "t.characters='x'"))
    assert "null is not an object" in str(ei.value)             # the script's own error, verbatim

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
    r = asyncio.run(design.render({"size": [1080, 1080]}, fmt="png", scale=2, user_id="org:u"))
    assert r.image == b"\x89PNGdata" and r.fig == b"figdata" and r.frame_id == "0:6" and r.fmt == "png"
    assert r.preview is None and r.notes == [] and r.previews == [] and r.slides == []   # an older service
    last = _FakeClient.last
    assert last["url"] == "https://d.cycls.ai/render"
    assert last["headers"]["Authorization"] == "Bearer sek"
    assert last["headers"]["X-User-Id"] == "org:u"             # attribution, not auth
    assert last["json"] == {"spec": {"size": [1080, 1080]}, "format": "png", "scale": 2, "preview": True}


def test_render_decodes_the_qa_preview(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(200, {**_ok(), "preview_base64": base64.b64encode(b"JPEGsmall").decode()}))
    assert asyncio.run(design.render({})).preview == b"JPEGsmall"


def test_render_decodes_a_decks_slides_and_carousel(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    b64 = lambda b: base64.b64encode(b).decode()
    _mock(monkeypatch, _FakeResp(200, {**_ok(), "previews_base64": [b64(b"J1"), b64(b"J2")],
                                       "images_base64": [b64(b"P1"), b64(b"P2")],
                                       "slides": [{"name": "cover", "notes": "Hi"}, {"name": "slide-2"}], "dir": "rtl"}))
    r = asyncio.run(design.render({"frames": [{}, {}]}, every=True))
    assert r.previews == [b"J1", b"J2"] and r.images == [b"P1", b"P2"]
    assert r.slides[0] == {"name": "cover", "notes": "Hi"} and r.dir == "rtl"
    assert _FakeClient.last["json"]["every"] is True


def test_slides_and_every_export(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    b64 = lambda b: base64.b64encode(b).decode()
    _mock(monkeypatch, _FakeResp(200, {"ok": True, "format": "jpg", "count": 2, "slides": [b64(b"S1"), b64(b"S2")],
                                       "sizes": [[1920, 1080], [1920, 1080]], "meta": [{"name": "a"}, {"name": "b"}]}))
    s = asyncio.run(design.slides(b"FIG"))
    assert s["images"] == [b"S1", b"S2"] and s["sizes"][1] == [1920, 1080] and s["meta"][1]["name"] == "b"
    assert _FakeClient.last["url"] == "https://d/slides"
    _mock(monkeypatch, _FakeResp(200, {"ok": True, "format": "png", "image_base64": b64(b"P1"),
                                       "images_base64": [b64(b"P1"), b64(b"P2")]}))
    assert asyncio.run(design.export(b"FIG", fmt="png", width=1080, every=True)) == [b"P1", b"P2"]
    assert _FakeClient.last["json"]["every"] is True


def test_eval_posts_script(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d.cycls.ai")
    _mock(monkeypatch, _FakeResp(200, _ok()))
    asyncio.run(design.evaluate("console.log('__FRAME__0:1')", fmt="pptx", scale=1))
    assert _FakeClient.last["url"].endswith("/eval")
    assert _FakeClient.last["json"]["script"].startswith("console.log")
    assert "Authorization" not in _FakeClient.last["headers"]  # no secret set


# ---- a deploy of the service is not a failed render ----

class _SeqClient:
    """An HTTP client whose posts go as listed: an exception is raised, a response returned."""
    posts = 0

    def __init__(self, outcomes, **_):
        self._outcomes = outcomes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        outcome = self._outcomes[min(_SeqClient.posts, len(self._outcomes) - 1)]
        _SeqClient.posts += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _sequence(monkeypatch, *outcomes):
    _SeqClient.posts = 0
    monkeypatch.setenv("DESIGN_URL", "https://d.cycls.ai")
    monkeypatch.setattr(client, "_RETRY_WAITS", (0, 0))                    # (no waiting in a test)
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **k: _SeqClient(outcomes, **k))


def test_a_connection_dropped_while_the_service_is_being_deployed_is_tried_again(monkeypatch):
    """For a few minutes after the service is deployed its instances are swapped under the
    requests in flight: on prod one render came back "Server disconnected without sending a
    response" — a failed design, for a user — and the same request a moment later was fine."""
    import httpx
    gone = httpx.RemoteProtocolError("Server disconnected without sending a response.")
    _sequence(monkeypatch, gone, _FakeResp(200, _ok()))
    r = asyncio.run(design.render({"size": [1, 1]}))
    assert r.image == b"\x89PNG" and _SeqClient.posts == 2
    # The platform's front end answering for a service that isn't there yet (no JSON of the service's): the same.
    _sequence(monkeypatch, httpx.ConnectError("refused"), _FakeResp(503, None), _FakeResp(200, _ok()))
    assert asyncio.run(design.render({"size": [1, 1]})).fig == b"FIGB" and _SeqClient.posts == 3
    # Still gone after three tries: said as unreachable, with how hard it was tried.
    _sequence(monkeypatch, gone)
    with pytest.raises(design.Unavailable) as ei:
        asyncio.run(design.render({"size": [1, 1]}))
    assert _SeqClient.posts == 3 and "3 tries" in str(ei.value) and "Server disconnected" in str(ei.value)


def test_what_trying_again_would_not_cure_is_not_tried_again(monkeypatch):
    import httpx
    # A render that takes too long would take as long again.
    _sequence(monkeypatch, httpx.ReadTimeout("timed out"), _FakeResp(200, _ok()))
    with pytest.raises(design.Unavailable):
        asyncio.run(design.render({"size": [1, 1]}))
    assert _SeqClient.posts == 1
    # The service's own answer — a spec it refuses, a render that failed — is its answer.
    for status, payload in ((422, {"ok": False, "error": "bad spec"}), (500, {"ok": False, "error": "the script threw"}), (503, {"ok": False, "error": "busy"})):
        _sequence(monkeypatch, _FakeResp(status, payload), _FakeResp(200, _ok()))
        with pytest.raises(RuntimeError) as ei:
            asyncio.run(design.render({"size": [1, 1]}))
        assert _SeqClient.posts == 1 and payload["error"] in str(ei.value)
        assert not isinstance(ei.value, design.Unavailable)


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


@pytest.mark.parametrize("status,words", [(413, "too large"), (429, "too many")])
def test_bare_413_and_429_read_as_sentences(monkeypatch, status, words):
    # The platform's front end refuses an oversized body before the service sees
    # it (no JSON) — the agent still gets a sentence, not "design service 413: ".
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(status, None))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(design.render({}))
    assert words in str(ei.value)


def test_the_services_own_429_message_wins(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(429, {"ok": False, "error": "too many design requests — retry in 7 s"}))
    with pytest.raises(RuntimeError, match="retry in 7 s"):
        asyncio.run(design.render({}))


# ---- the Design tool (executor + gating + label), with render faked ----

def _ws(tmp_path):
    return types.SimpleNamespace(root=str(tmp_path), subject="org_1:user_1")


def _text(out):
    """The ack the model reads — a raster render is [image, text], else a string."""
    m = out["_model"]
    return m if isinstance(m, str) else next(b["text"] for b in m if b["type"] == "text")


def _fake_render(monkeypatch, image=b"\x89PNGrender", fig=b"FIGZ", preview=None, notes=(), lint=(),
                 previews=(), images=(), slides=(), dir=None, pages=(), page_images=(), preview_pages=(), size=None,
                 sheets=(), sheet_pages=(), hashes=(), preview_of=None):
    calls = {}

    async def _r(spec, fmt="png", scale=2, user_id=None, every=False, **kw):
        calls.update(spec=spec, fmt=fmt, scale=scale, user_id=user_id, every=every, sheets=kw.get("sheets", False),
                     known=list(kw.get("known") or []), renders=calls.get("renders", 0) + 1, lead=kw.get("lead"))
        return design.Rendered(image, fig, "0:6", fmt, preview, list(notes), list(lint),
                               list(previews), list(images) if every else [], list(slides), dir,
                               list(pages), list(page_images), list(preview_pages), size,
                               list(sheets), [list(p) for p in sheet_pages],
                               list(hashes), None if preview_of is None else list(preview_of))

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
    assert "saved (designs/launch.png" in _text(out) and "canvas" in _text(out)
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
        return design.Rendered(b"PPTX", b"FIG", "0:1", fmt, None, [], [], [], [], [])

    monkeypatch.setattr("cycls._agent.design.evaluate", _e)
    out = asyncio.run(_exec_design(
        {"action": "script", "name": "deck", "script": "console.log('__FRAME__0:1')", "format": "pptx"},
        _ws(tmp_path)))
    assert (tmp_path / "designs" / "deck.pptx").read_bytes() == b"PPTX"
    assert got["script"].startswith("console.log") and out["_ui"]["path"] == "designs/deck.pptx"


def _fake_apply(monkeypatch, result=b"EDITED-FIG", error=None, compiled=None, preview=None, lint=(),
                previews=(), touched=(), slides=(), pages=(), page="", started="", **names):
    """`design.apply` faked: records the call, returns the edited .fig (plus the
    compiled script, preview and lint the service sends) or raises the edit's error.
    `refresh.schedule` is captured instead of run."""
    calls = {}

    async def _apply(fig, script=None, user_id=None, ops=None, preview_=None, **kw):
        calls.update(fig=fig, script=script, ops=ops, user_id=user_id, preview=kw.get("preview"), page=kw.get("page"))
        if error:
            raise RuntimeError(error)
        return {"fig": result, "lint": list(lint), "script": compiled, "preview": preview,
                "previews": list(previews), "touched": list(touched), "slides": list(slides),
                "pages": list(pages), "page": page, "started": started,
                **{k: list(names.get(k) or []) for k in ("changed", "added", "resolved", "notes")}}
    monkeypatch.setattr("cycls._agent.design.apply", _apply)
    scheduled = []

    def _schedule(root, rel, user_id=None, ensure=False, pages=False):
        scheduled.append(rel)
        calls["pages_asked"] = pages
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", _schedule)
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
    # A fix is an edit of the same design (checked and saved by the service, with or
    # without an editor open) — never a re-render.
    assert "QA it before you present" in txt["text"] and "Design edit" in txt["text"]
    monkeypatch.setenv("DESIGN_EDITOR_URL", "https://cycls-design.cycls.ai")
    out = asyncio.run(_exec_design({"action": "render", "name": "launch", "spec": {}}, _ws(tmp_path)))
    assert "Design edit" in _text(out)


def test_no_qa_image_for_decks_svg_or_oversized(tmp_path, monkeypatch):
    _fake_render(monkeypatch)
    ws = _ws(tmp_path)
    for fmt in ("pptx", "svg"):
        out = asyncio.run(_exec_design({"action": "render", "spec": {}, "format": fmt}, ws))
        assert isinstance(out["_model"], str) and "QA" not in out["_model"]
    monkeypatch.setattr("cycls._agent.design.run._DESIGN_QA_MAX", 4)             # bigger than `read` allows
    out = asyncio.run(_exec_design({"action": "render", "spec": {}}, ws))
    assert isinstance(out["_model"], str)


# ---- decks and carousels: the whole file, a deck document, every slide QA'd ----

def test_deck_saves_the_file_a_deck_document_and_qas_every_slide(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch, image=b"PPTXDECK", previews=[b"J1", b"J2", b"J3"],
                         slides=[{"name": "cover"}, {"name": "slide-2"}, {"name": "slide-3"}])
    spec = {"frames": [{"size": "slide", "notes": "Open with the story", "transition": "fade"},
                       {"size": "slide"}, {"size": "slide"}]}
    out = asyncio.run(_exec_design({"action": "render", "name": "pitch", "format": "pptx", "spec": spec}, _ws(tmp_path)))
    d = tmp_path / "designs"
    assert (d / "pitch.pptx").read_bytes() == b"PPTXDECK" and (d / "pitch.fig").read_bytes() == b"FIGZ"
    assert json.loads((d / "pitch.deck.json").read_text()) == {
        "type": "cycls.deck", "version": 1, "fig": "designs/pitch.fig", "size": [1920, 1080],
        "slides": 3, "exports": ["designs/pitch.pptx"]}
    assert calls["every"] is False                                          # a PPTX is one file
    assert calls["spec"]["frames"][0]["notes"] == "Open with the story"     # notes reach the service
    m = out["_model"]
    assert [b["text"] for b in m if b["type"] == "text"][:3] == ["Slide 1:", "Slide 2:", "Slide 3:"]
    assert [base64.b64decode(b["source"]["data"]) for b in m if b["type"] == "image"] == [b"J1", b"J2", b"J3"]
    assert "Deck saved (designs/pitch.pptx, 3 slides" in m[-1]["text"]
    assert out["_ui"] == {"type": "ui", "action": "open_canvas", "path": "designs/pitch.deck.json", "name": "pitch.deck.json"}
    assert "deck viewer" in m[-1]["text"] and "Present" in m[-1]["text"]
    assert "All 3 slides are attached" in m[-1]["text"] and "CONSISTENT" in m[-1]["text"]


def test_a_long_deck_is_seen_whole_twelve_slides_to_read_and_the_rest_on_contact_sheets(tmp_path, monkeypatch):
    # Of a 20-slide deck the model was shown slides 1–12 and told "inspect lists the rest":
    # eight slides it presented without having looked at.
    calls = _fake_render(monkeypatch, image=b"PDF", previews=[b"J%d" % i for i in range(1, 13)],
                         slides=[{"name": f"slide-{n}"} for n in range(1, 21)], sheets=[b"S1"], sheet_pages=[[13, 20]])
    out = asyncio.run(_exec_design({"action": "render", "name": "long", "format": "pdf",
                                    "spec": {"frames": [{"size": "slide"}] * 20}}, _ws(tmp_path)))
    assert (tmp_path / "designs" / "long.pdf").read_bytes() == b"PDF"       # a PDF is a deck format too
    assert calls["sheets"] is True and calls["lead"] == 12                   # twelve to read, as before
    m = out["_model"]
    assert [b["text"] for b in m if b["type"] == "text"][11:13] == ["Slide 12:", "Slides 13–20, small:"]
    assert [base64.b64decode(b["source"]["data"]) for b in m if b["type"] == "image"][-2:] == [b"J12", b"S1"]
    assert "Slides 1–12 are attached to read, and slides 13–20 on 1 contact sheet" in m[-1]["text"]
    assert "inspect lists the rest" not in m[-1]["text"]
    # A deck of twelve or fewer asks for none; a service that sends none is said as before.
    calls = _fake_render(monkeypatch, image=b"PDF", previews=[b"J"] * 3)
    asyncio.run(_exec_design({"action": "render", "name": "short", "format": "pdf", "spec": {"frames": [{"size": "slide"}] * 3}}, _ws(tmp_path)))
    assert calls["sheets"] is False
    _fake_render(monkeypatch, image=b"PDF", previews=[b"J%d" % i for i in range(15)])
    out = asyncio.run(_exec_design({"action": "render", "name": "older", "format": "pdf", "spec": {"frames": [{"size": "slide"}] * 15}}, _ws(tmp_path)))
    assert sum(b["type"] == "image" for b in out["_model"]) == 12 and "Slides 1–12 of 15 are attached" in out["_model"][-1]["text"]


def test_carousel_saves_every_slide(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch, image=b"P1", images=[b"P1", b"P2", b"P3"], previews=[b"J1", b"J2", b"J3"])
    spec = {"frames": [{"size": "post-portrait"}] * 3}
    out = asyncio.run(_exec_design({"action": "render", "name": "tips", "spec": spec}, _ws(tmp_path)))
    d = tmp_path / "designs"
    assert calls["every"] is True                                           # several frames as png: a carousel
    assert [(d / f"tips-slide-{n}.png").read_bytes() for n in (1, 2, 3)] == [b"P1", b"P2", b"P3"]
    assert not (d / "tips.png").exists()
    assert json.loads((d / "tips.deck.json").read_text())["exports"] == [
        "designs/tips-slide-1.png", "designs/tips-slide-2.png", "designs/tips-slide-3.png"]
    assert "Carousel saved (3 slides: designs/tips-slide-1.png … designs/tips-slide-3.png" in out["_model"][-1]["text"]
    assert out["_ui"]["path"] == "designs/tips.deck.json"                   # the deck viewer opens
    said = out["_model"][-1]["text"]
    assert "deck viewer" in said and "its images (a .zip)" in said          # where it opened, and how a carousel downloads
    # The same name again is bumped — a carousel's slide files count as taken.
    _fake_render(monkeypatch, image=b"Q1", images=[b"Q1", b"Q2", b"Q3"])
    asyncio.run(_exec_design({"action": "render", "name": "tips", "spec": spec}, _ws(tmp_path)))
    assert (d / "tips-2-slide-1.png").read_bytes() == b"Q1" and (d / "tips-slide-1.png").read_bytes() == b"P1"


# ---- size presets ----

def test_size_preset_resolves_to_pixels(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    spec = {"size": "Story", "nodes": []}
    asyncio.run(_exec_design({"action": "render", "spec": spec}, _ws(tmp_path)))
    assert calls["spec"]["size"] == [1080, 1920]
    assert spec["size"] == "Story"                                          # the model's input is untouched

    asyncio.run(_exec_design({"action": "render", "spec": {"frames": [{"size": "slide"}, {"size": [1920, 1080]}]},
                              "format": "pptx"}, _ws(tmp_path)))
    assert [f["size"] for f in calls["spec"]["frames"]] == [[1920, 1080], [1920, 1080]]   # arrays pass through


def test_a_deck_of_mixed_sizes_is_an_error(tmp_path, monkeypatch):
    # PowerPoint takes one slide size for the whole file and letterboxes the rest.
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "format": "pptx",
                                    "spec": {"frames": [{"size": "slide"}, {"size": [800, 600]}]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "same size" in out and "slide 2 is 800×600" in out
    assert calls == {}


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
        assert out.startswith("Error") and "text, rect, ellipse, line, image, stack, list, table, chart, icon, svg or qr" in out
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
    monkeypatch.setattr("cycls._agent.design.run._DESIGN_QA_MAX", 32)             # the @2x PNG is over the bound
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
    monkeypatch.setattr("cycls._agent.design.images._DESIGN_IMAGE_MAX", 8)
    assert "smaller copy" in err({"src": "p.png", "w": 10})
    assert calls == {}                                                             # none reached the service


def test_images_have_a_total_budget(tmp_path, monkeypatch):
    _img(tmp_path, "a.png", _png(10, 10))
    calls = _fake_render(monkeypatch)
    monkeypatch.setattr("cycls._agent.design.prepare._DESIGN_IMAGES_MAX", 40)
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

    async def _export(fig, fmt="png", scale=2, width=None, user_id=None, every=False):
        calls.append({"fig": fig, "fmt": fmt, "width": width, "user_id": user_id, "every": every})
        if fail:
            raise RuntimeError("service down")
        return [f"NEW-{fmt}-{n}".encode() for n in (1, 2)] if every else f"NEW-{fmt}".encode()
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


def test_a_decks_pdf_and_a_carousels_slides_reexport(tmp_path, monkeypatch):
    calls = _refresh_env(tmp_path, monkeypatch)
    d = tmp_path / "designs"
    (d / "launch.pdf").write_bytes(b"OLD-PDF")
    for n in (1, 2, 3):                                                     # 3 slides; one was deleted since
        (d / f"launch-slide-{n}.png").write_bytes(_png(1080, 1350))
    _saves(tmp_path, "designs/launch.fig")
    assert (d / "launch.pdf").read_bytes() == b"NEW-pdf"
    assert [(d / f"launch-slide-{n}.png").read_bytes() for n in (1, 2)] == [b"NEW-png-1", b"NEW-png-2"]
    assert not (d / "launch-slide-3.png").exists()                          # its old image goes
    every = [c for c in calls if c["every"]]
    assert len(every) == 1 and every[0]["width"] == 1080                    # the slides keep their resolution


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


def _bare_copy(tmp_path, monkeypatch):
    """A design with nothing beside it — what "Save a copy" leaves."""
    calls = _refresh_env(tmp_path, monkeypatch)
    (tmp_path / "designs" / "launch copy.fig").write_bytes(b"COPY-FIG")
    return calls, tmp_path / "designs"


def test_a_design_with_no_image_gets_one_when_asked(tmp_path, monkeypatch):
    calls, d = _bare_copy(tmp_path, monkeypatch)
    _saves(tmp_path, "designs/launch copy.fig")                             # a plain save: only what's there
    assert calls == [] and not (d / "launch copy.png").exists()

    async def copy():
        refresh.schedule(tmp_path, "designs/launch copy.fig", "org:u", ensure=True)
        await asyncio.gather(*refresh._pending.values(), return_exceptions=True)
    asyncio.run(copy())
    assert (d / "launch copy.png").read_bytes() == b"NEW-png"
    assert calls == [{"fig": b"COPY-FIG", "fmt": "png", "width": None, "user_id": "org:u", "every": False}]
    assert refresh._ensure == set() and refresh._pending == {}


def test_a_save_right_after_the_copy_still_leaves_it_an_image(tmp_path, monkeypatch):
    # The copy opens in the editor, which saves it at once (its Brand variables): that
    # save restarts the wait, and must not drop what the copy asked for.
    calls, d = _bare_copy(tmp_path, monkeypatch)

    async def copy_then_save():
        refresh.schedule(tmp_path, "designs/launch copy.fig", "org:u", ensure=True)
        refresh.schedule(tmp_path, "designs/launch copy.fig", "org:u")
        await asyncio.gather(*refresh._pending.values(), return_exceptions=True)
    asyncio.run(copy_then_save())
    assert (d / "launch copy.png").read_bytes() == b"NEW-png" and len(calls) == 1


def test_a_deck_or_a_carousel_is_not_given_a_png(tmp_path, monkeypatch):
    calls = _refresh_env(tmp_path, monkeypatch)
    d = tmp_path / "designs"
    (d / "launch.png").unlink()                                             # a deck: its .pptx only
    (d / "reel.fig").write_bytes(b"REEL-FIG")
    (d / "reel-slide-1.png").write_bytes(_png(1080, 1350))                  # a carousel: its slides only

    async def go():
        for name in ("launch", "reel"):
            refresh.schedule(tmp_path, f"designs/{name}.fig", "org:u", ensure=True)
        await asyncio.gather(*refresh._pending.values(), return_exceptions=True)
    asyncio.run(go())
    assert not (d / "launch.png").exists() and not (d / "reel.png").exists()
    assert sorted((c["fmt"], c["every"]) for c in calls) == [("png", True), ("pptx", False)]
    assert refresh._ensure == set()


def test_an_agent_edit_asks_for_the_image(tmp_path, monkeypatch):
    _fake_apply(monkeypatch)
    asked = []
    monkeypatch.setattr("cycls._agent.design.refresh.schedule",
                        lambda root, rel, user_id=None, ensure=False, pages=False: asked.append((rel, ensure)))
    _design(tmp_path)
    asyncio.run(_exec_design({"action": "edit", "name": "launch", "script": "x"}, _ws(tmp_path)))
    assert asked == [("designs/launch.fig", True)]


def test_a_background_op_goes_through_as_it_is(tmp_path, monkeypatch):
    # The slide's own fill: no node to name, and `frame` a number even when quoted.
    calls, _ = _fake_apply(monkeypatch)
    _design(tmp_path)
    ops = [{"op": "background", "frame": "1", "fill": {"gradient": ["#0f172a", "#1e3a8a"], "angle": 90}}]
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": ops}, _ws(tmp_path)))
    assert not (isinstance(out, str) and out.startswith("Error")), out
    assert calls["ops"] == [{"op": "background", "frame": 1, "fill": {"gradient": ["#0f172a", "#1e3a8a"], "angle": 90}}]


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
    assert asyncio.run(design.apply(b"FIG", "t.characters='x'", user_id="u")) == \
        {"fig": b"EDITED", "lint": [], "script": None, "preview": None, "previews": [], "touched": [], "slides": [],
         "pages": [], "page": "", "started": "", "changed": [], "added": [], "resolved": [], "notes": []}
    assert _FakeClient.last["url"] == "https://d/apply"
    assert _FakeClient.last["json"] == {"fig": base64.b64encode(b"FIG").decode(), "script": "t.characters='x'"}
    _mock(monkeypatch, _FakeResp(422, {"ok": False, "error": "null is not an object"}))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(design.apply(b"FIG", "t.characters='x'"))
    assert "null is not an object" in str(ei.value)             # the script's own error, verbatim


# ---- M3: stacks, the layout check ----

def test_a_stack_and_its_children_are_prepared(tmp_path, monkeypatch):
    _brand(tmp_path, "primary_color: '#0C2340'\naccent_color: '#c9a227'\nfont_heading: Playfair Display\nfont_body: Inter\n")
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": "square", "nodes": [
        {"type": "stack", "x": "90", "y": 120, "gap": "24", "children": [
            {"text": "Big title", "size": 96},                  # untyped → text; brand heading; readable colour
            {"type": "text", "text": "Body", "size": "32"},
            {"type": "ellipse", "w": 40, "h": 40, "stroke": "#ffffff"},   # an outline stays hollow — no accent fill
        ]}]}}, _ws(tmp_path)))
    assert not _text(out).startswith("Error"), _text(out)
    stack = calls["spec"]["nodes"][0]
    assert stack["x"] == 90 and stack["gap"] == 24
    title, body, ring = stack["children"]
    assert title["type"] == "text" and title["font"] == "Playfair Display" and title["color"]
    assert body["size"] == 32 and body["font"] == "Inter"
    assert "fill" not in ring


def test_a_stack_needs_children_and_must_start_inside(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    for node, words in (({"type": "stack", "x": 0, "y": 0}, "needs `children`"),
                        ({"type": "stack", "x": 0, "y": 5000, "children": [{"type": "text", "text": "x"}]}, "outside the")):
        out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1080], "nodes": [node]}}, _ws(tmp_path)))
        assert out.startswith("Error") and words in out, out
    assert calls == {}


def test_the_layout_check_reaches_the_ack(tmp_path, monkeypatch):
    _fake_render(monkeypatch, lint=[{"frame": 0, "node": '"Subtitle"', "issue": 'overlaps "Headline"', "fix": "move one"}])
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1080]}}, _ws(tmp_path)))
    assert 'Layout check found 1 issue: "Subtitle" overlaps "Headline" — move one' in _text(out)
    _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1080]}}, _ws(tmp_path)))
    assert "Layout check: clean." in _text(out)


def test_the_client_decodes_lint(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(200, {**_ok(), "lint": [{"frame": 1, "node": "x", "issue": "y", "fix": "z"}]}))
    assert asyncio.run(design.render({}))[6] == [{"frame": 1, "node": "x", "issue": "y", "fix": "z"}]


# ---- M4: inspect, edit ops ----

def test_edit_with_ops_resolves_files_and_replays_the_compiled_script(tmp_path, monkeypatch):
    _design(tmp_path)
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "p.png").write_bytes(_png(40, 20))
    calls, scheduled = _fake_apply(monkeypatch, compiled="/*compiled*/ await applyOps([])", preview=_jpeg(8, 8),
                                   lint=[{"frame": 0, "node": "tag", "issue": "sits 4px from the edge", "fix": "keep margins"}])
    ops = [{"op": "set_text", "node": "headline", "text": "New"},
           {"op": "move", "node": "cta", "dy": "40"},                              # quoted number → number
           {"op": "replace_image", "node": "photo", "src": "attachments/p.png"},   # file → bytes
           {"op": "add", "node": {"text": "NEW", "x": 10, "y": 10, "size": "24"}}]  # untyped → text; numbers
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": ops, "intent": "swap the photo"}, _ws(tmp_path)))
    sent = calls["ops"]
    assert calls["script"] is None and calls["preview"] is True
    assert sent[1]["dy"] == 40
    assert "src" not in sent[2] and base64.b64decode(sent[2]["image"]) == _png(40, 20)
    assert sent[3]["node"]["type"] == "text" and sent[3]["node"]["size"] == 24
    assert (tmp_path / "designs" / "launch.fig").read_bytes() == b"EDITED-FIG" and scheduled == ["designs/launch.fig"]
    assert out["_ui"]["script"] == "/*compiled*/ await applyOps([])"         # the editor replays the same code
    text = _text(out)
    assert "Layout check found 1 issue: tag sits 4px from the edge" in text
    assert out["_model"][0]["type"] == "image"                               # the edited design comes back to check


def test_an_edit_says_by_name_what_it_changed_and_made(tmp_path, monkeypatch):
    # A copy and an added part get names of their own, and a part can be found by what it
    # says rather than its name: the reply gives the names, so the next edit uses them
    # without an `inspect` in between (production: an edit that named a headline by its
    # words failed, and was sent again after one).
    _design(tmp_path)
    ops = [{"op": "set_text", "node": "Night Roast", "text": "Morning Roast"}]
    _fake_apply(monkeypatch, compiled="/*c*/", changed=["text-1", "icon-2"], added=["icon-3"],
                resolved=[["Night Roast", "text-1"]])
    text = _text(asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": ops}, _ws(tmp_path))))
    assert "Changed: text-1, icon-2." in text and "Added: icon-3." in text
    assert '"Night Roast" is named text-1' in text
    _fake_apply(monkeypatch, compiled="/*c*/")                               # nothing to say: nothing said
    text = _text(asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": ops}, _ws(tmp_path))))
    assert "Changed:" not in text and "Added:" not in text and "is named" not in text


def test_inspect_shows_a_mark_as_one_part_with_its_icon_and_colour(tmp_path, monkeypatch):
    _design(tmp_path)

    async def _outline(fig, user_id=None, page=None):
        return {"pages": [{"name": "design", "frames": 1}], "page": "design", "frames": [
                {"slide": 1, "name": "slide-1", "size": [1200, 900], "nodes": [
            {"name": "icon-1", "type": "icon", "x": 40, "y": 120, "w": 64, "h": 64, "icon": "lucide:trophy", "color": "#b45309"},
            {"name": "qr-1", "type": "qr", "x": 340, "y": 120, "w": 96, "h": 96, "color": "#000000", "opacity": 0.5},
            {"name": "chart-1", "type": "chart", "x": 40, "y": 480, "w": 500, "h": 320, "fill": "none"}]}]}
    monkeypatch.setattr("cycls._agent.design.outline", _outline)
    out = asyncio.run(_exec_design({"action": "inspect", "name": "launch"}, _ws(tmp_path)))
    assert "icon-1  icon  (40,120 64×64)  lucide:trophy  color #b45309" in out
    assert "qr-1  qr  (340,120 96×96)  color #000000  opacity 0.5" in out
    assert "chart-1  chart  (40,480 500×320)" in out and "fill none" not in out
    assert "more part" not in out


def test_inspect_says_how_many_parts_a_long_slide_has_beyond_those_it_lists(tmp_path, monkeypatch):
    _design(tmp_path)

    async def _outline(fig, user_id=None, page=None):
        return {"pages": [{"name": "design", "frames": 1}], "page": "design", "frames": [
                {"slide": 1, "name": "slide-1", "size": [1200, 900], "more": 57, "nodes": [
            {"name": "rect-1", "type": "rect", "x": 0, "y": 0, "w": 10, "h": 10, "fill": "#000000"}]}]}
    monkeypatch.setattr("cycls._agent.design.outline", _outline)
    out = asyncio.run(_exec_design({"action": "inspect", "name": "launch"}, _ws(tmp_path)))
    assert "… and 57 more parts of this slide are not listed" in out


def test_edit_ops_errors_come_back_verbatim(tmp_path, monkeypatch):
    _design(tmp_path)
    _fake_apply(monkeypatch, error='op 1 (set_text nope): no node named "nope" — this design has: headline, cta')
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": [{"op": "set_text", "node": "nope", "text": "x"}]}, _ws(tmp_path)))
    assert out.startswith("Error") and 'no node named "nope"' in out and "headline, cta" in out
    bad = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": [{"op": "move", "node": "cta", "dy": "lots"}]}, _ws(tmp_path)))
    assert bad.startswith("Error") and "`dy` must be a number" in bad


def test_inspect_lists_frames_and_nodes(tmp_path, monkeypatch):
    _design(tmp_path)
    got = {}

    async def _outline(fig, user_id=None, page=None):
        got.update(fig=fig, user_id=user_id, page=page)
        return {"pages": [{"name": "design", "frames": 1}], "page": "design", "frames": [
                {"slide": 1, "name": "cover", "title": "Cover", "notes": "Open with the story.", "transition": "fade",
                 "size": [1080, 1080], "fill": "#0f172a", "nodes": [
            {"name": "headline", "type": "text", "x": 90, "y": 120, "w": 900, "h": 220, "text": "Night Roast",
             "font": "Playfair Display Bold", "size": 96, "color": "#ffffff"},
            {"name": "cta", "type": "rect", "x": 90, "y": 900, "w": 240, "h": 72, "fill": "#f5a623", "radius": 36}]}]}
    monkeypatch.setattr("cycls._agent.design.outline", _outline)
    out = asyncio.run(_exec_design({"action": "inspect", "name": "launch"}, _ws(tmp_path)))
    assert got["fig"] == b"ORIGINAL-FIG" and got["page"] is None
    assert out.startswith("designs/launch.fig — 1 frame.") and "pages" not in out   # one page: nothing about pages
    assert 'slide 1 "cover" (1080×1080, fill #0f172a, title "Cover", transition "fade"):' in out
    assert '  notes: "Open with the story."' in out
    assert 'headline  text  (90,120 900×220)  "Night Roast"  Playfair Display Bold 96px #ffffff' in out
    assert "cta  rect  (90,900 240×72)  fill #f5a623  radius 36" in out
    missing = asyncio.run(_exec_design({"action": "inspect", "name": "nope"}, _ws(tmp_path)))
    assert missing.startswith("Error") and "doesn't exist" in missing


def test_the_client_inspects_and_applies_ops(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    _mock(monkeypatch, _FakeResp(200, {"ok": True, "frames": [{"slide": 1, "nodes": []}]}))
    assert asyncio.run(design.inspect(b"FIG")) == [{"slide": 1, "nodes": []}]
    assert _FakeClient.last["url"] == "https://d/inspect"
    _mock(monkeypatch, _FakeResp(200, {"ok": True, "fig_base64": base64.b64encode(b"E").decode(), "script": "S",
                                       "preview_base64": base64.b64encode(b"J").decode(), "lint": []}))
    r = asyncio.run(design.apply(b"FIG", ops=[{"op": "delete", "node": "x"}], preview=True))
    assert r == {"fig": b"E", "lint": [], "script": "S", "preview": b"J", "previews": [], "touched": [], "slides": [],
                 "pages": [], "page": "", "started": "", "changed": [], "added": [], "resolved": [], "notes": []}
    assert _FakeClient.last["json"] == {"fig": base64.b64encode(b"FIG").decode(), "ops": [{"op": "delete", "node": "x"}], "preview": True}
    # What the edit changed and made, by name, and which part a name that wasn't one turned out to be.
    _mock(monkeypatch, _FakeResp(200, {"ok": True, "fig_base64": base64.b64encode(b"E").decode(), "changed": ["text-1"],
                                       "added": ["icon-3"], "resolved": [["Night Roast", "text-1"], "junk"]}))
    r = asyncio.run(design.apply(b"FIG", ops=[{"op": "delete", "node": "x"}]))
    assert (r["changed"], r["added"], r["resolved"]) == (["text-1"], ["icon-3"], [["Night Roast", "text-1"]])


# ---- pages: a design's variants (a post, a story, a banner of one piece of work) ----

_PAGES = [{"name": "Post", "frames": 1}, {"name": "Story", "frames": 1}, {"name": "Banner", "frames": 1}]


def test_the_client_names_the_page_and_reads_the_pages(monkeypatch):
    monkeypatch.setenv("DESIGN_URL", "https://d")
    b64 = lambda b: base64.b64encode(b).decode()
    paged = {"pages": _PAGES, "page": "Story"}
    _mock(monkeypatch, _FakeResp(200, {"ok": True, "frames": [{"slide": 1, "nodes": []}], **paged}))
    assert asyncio.run(design.outline(b"FIG", page="Story")) == {"frames": [{"slide": 1, "nodes": []}], **paged}
    assert _FakeClient.last["json"] == {"fig": b64(b"FIG"), "page": "Story"}
    asyncio.run(design.outline(b"FIG"))
    assert "page" not in _FakeClient.last["json"]                            # none named: the first page

    _mock(monkeypatch, _FakeResp(200, {"ok": True, "format": "png", "image_base64": b64(b"STORY"), **paged}))
    assert asyncio.run(design.export_page(b"FIG", "Story", fmt="png")) == (b"STORY", _PAGES, "Story")
    assert _FakeClient.last["json"]["page"] == "Story"
    assert asyncio.run(design.export(b"FIG", page=2)) == b"STORY" and _FakeClient.last["json"]["page"] == 2   # or its place

    _mock(monkeypatch, _FakeResp(200, {"ok": True, "slides": [b64(b"J")], "sizes": [[300, 600]], "meta": [{}], **paged}))
    s = asyncio.run(design.slides(b"FIG", page="Story"))
    assert s["pages"] == _PAGES and s["page"] == "Story" and _FakeClient.last["json"]["page"] == "Story"

    _mock(monkeypatch, _FakeResp(200, {"ok": True, "fig_base64": b64(b"E"), "started": "Story", **paged}))
    r = asyncio.run(design.apply(b"FIG", ops=[{"op": "delete", "node": "x"}], page="Story"))
    assert (r["started"], r["page"], r["pages"]) == ("Story", "Story", _PAGES)
    assert _FakeClient.last["json"]["page"] == "Story"

    _mock(monkeypatch, _FakeResp(200, {**_ok(), "pages": _PAGES, "page_images_base64": [b64(b"A"), b64(b"B"), b64(b"C")],
                                       "preview_pages": ["Post", "Story", "Banner"]}))
    out = asyncio.run(design.render({"pages": []}))
    assert out.pages == _PAGES and out.page_images == [b"A", b"B", b"C"] and out.preview_pages == ["Post", "Story", "Banner"]


def _variants():
    node = lambda text: [{"text": text, "x": 40, "y": 40, "size": 64}]
    return {"pages": [{"name": "Post", "size": "square", "fill": "#0f172a", "nodes": node("Launch")},
                      {"name": "Story", "size": "story", "fill": "#0f172a", "nodes": node("Launch day")},
                      {"name": "Banner", "size": [1600, 400], "nodes": node("Launch")}]}


def test_a_render_of_pages_is_one_design_with_an_image_a_page(tmp_path, monkeypatch):
    """"A post, a story and a banner" is one design of three pages — not three files to
    keep alike by hand: one .fig, each page's own image beside it, every page back to QA."""
    monkeypatch.setenv("DESIGN_EDITOR_URL", "https://ed")
    calls = _fake_render(monkeypatch, pages=_PAGES, page_images=[b"POST", b"STORY", b"BANNER"],
                         previews=[b"\xff\xd8p", b"\xff\xd8s", b"\xff\xd8b"], preview_pages=["Post", "Story", "Banner"],
                         lint=[{"page": "Story", "frame": 0, "node": "headline", "issue": "runs off the right edge", "fix": "narrow it"}])
    out = asyncio.run(_exec_design({"action": "render", "name": "launch", "spec": _variants()}, _ws(tmp_path)))
    sent = calls["spec"]["pages"]
    assert [p["name"] for p in sent] == ["Post", "Story", "Banner"]
    assert [p["size"] for p in sent] == [[1080, 1080], [1080, 1920], [1600, 400]]      # each its own size
    assert sent[1]["nodes"][0]["type"] == "text" and sent[1]["nodes"][0]["color"]     # prepared like any design
    assert calls["every"] is False
    d = tmp_path / "designs"
    assert sorted(f.name for f in d.iterdir()) == ["launch-page-2.png", "launch-page-3.png", "launch.fig", "launch.png"]
    assert (d / "launch.png").read_bytes() == b"POST" and (d / "launch-page-3.png").read_bytes() == b"BANNER"
    assert out["_ui"] == {"type": "ui", "action": "open_canvas", "path": "designs/launch.fig", "name": "launch.fig"}
    text = [b["text"] for b in out["_model"] if b["type"] == "text"][-1]
    assert 'with 3 pages: "Post" (designs/launch.png); "Story" (designs/launch-page-2.png); "Banner" (designs/launch-page-3.png)' in text
    assert 'page "Story": headline runs off the right edge' in text           # the layout check says which page
    labels = [b["text"] for b in out["_model"] if b["type"] == "text"][:3]
    assert labels == ['Page "Post":', 'Page "Story":', 'Page "Banner":']       # every page is looked at
    assert sum(b["type"] == "image" for b in out["_model"]) == 3


def test_pages_say_what_they_need(tmp_path, monkeypatch):
    _fake_render(monkeypatch)
    run = lambda spec, **kw: asyncio.run(_exec_design({"action": "render", "name": "x", "spec": spec, **kw}, _ws(tmp_path)))
    page = lambda name: {"name": name, "size": "square", "nodes": []}
    assert "needs a `name`" in run({"pages": [{"size": "square", "nodes": []}]})
    assert "two pages are named 'post'" in run({"pages": [page("Post"), page("post")]})
    assert "a deck of layouts is a design of its own" in run({"pages": [{"name": "Deck", "deck": {"slides": []}}]})
    assert "`pages` is a list of pages" in run({"pages": []})
    # A page's own mistakes say which page.
    assert "page 'Story': unknown size 'tall'" in run({"pages": [page("Post"), {"name": "Story", "size": "tall", "nodes": []}]})
    # Asked for as a PDF: rendered — as its images, said — not refused for a second call.
    as_pdf = run({"pages": [page("Post"), page("Story")]}, format="pdf")
    assert not _text(as_pdf).startswith("Error") and "rendered as png" in _text(as_pdf)


def test_inspect_and_edit_work_on_the_page_named(tmp_path, monkeypatch):
    _design(tmp_path)
    got = {}

    async def _outline(fig, user_id=None, page=None):
        got["page"] = page
        return {"pages": _PAGES, "page": "Story", "frames": [
            {"slide": 1, "name": "slide-1", "size": [1080, 1920], "nodes": []}]}
    monkeypatch.setattr("cycls._agent.design.outline", _outline)
    out = asyncio.run(_exec_design({"action": "inspect", "name": "launch", "page": "Story"}, _ws(tmp_path)))
    assert got["page"] == "Story"
    assert out.startswith('designs/launch.fig — page "Story" — 1 frame.')
    assert 'This design has 3 pages: "Post", "Story", "Banner"' in out and "passing its name as `page`" in out

    calls, scheduled = _fake_apply(monkeypatch, compiled="S", pages=_PAGES, page="Story", started="Story")
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "page": "Story",
                                    "ops": [{"op": "set_text", "node": "headline", "text": "Tomorrow"}]}, _ws(tmp_path)))
    assert calls["page"] == "Story" and calls["pages_asked"] is False
    assert out["_ui"]["page"] == "Story" and "reload" not in out["_ui"]        # an open editor shows that page first, and replays
    assert 'on page "Story"' in out["_model"] and "designs/launch-page-2.png" in out["_model"]


def test_a_page_an_edit_makes_is_prepared_and_gets_its_image(tmp_path, monkeypatch):
    _design(tmp_path)
    grown = [{"name": "design", "frames": 1}, {"name": "Story", "frames": 1}]
    calls, _ = _fake_apply(monkeypatch, compiled="S", pages=grown, page="Story", started="design")
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": [
        {"op": "page_add", "name": "Story", "spec": {"size": "story", "nodes": [{"text": "Hi", "x": 40, "y": 40}]}}]}, _ws(tmp_path)))
    spec = calls["ops"][0]["spec"]
    assert spec["size"] == [1080, 1920] and spec["nodes"][0]["type"] == "text"   # as a render prepares it
    assert calls["pages_asked"] is True                                        # the new page gets its image
    # Pages changed: an open editor re-opens the saved file, on the page the edit ended on.
    assert out["_ui"]["reload"] is True and out["_ui"]["page"] == "Story"
    assert 'on page "Story"' in out["_model"] and '"design", "Story"' in out["_model"]
    bad = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": [{"op": "page_add", "name": "X"}]}, _ws(tmp_path)))
    assert bad.startswith("Error: op 1: `page_add` needs `spec`")


def _page_env(tmp_path, monkeypatch, pages=3, empty=()):
    """A design of `pages` pages with its images beside it; exports are recorded."""
    monkeypatch.setenv("DESIGN_URL", "https://d")
    monkeypatch.setattr(refresh, "DELAY", 0.05)
    listed = [{"name": f"p{n}", "frames": 0 if n in empty else 1} for n in range(1, pages + 1)]
    calls = []

    async def _export(fig, fmt="png", scale=2, width=None, user_id=None, every=False):
        return _png(width or 1080, 1080) + b"NEW"            # the design's own image, at the width it had

    async def _export_page(fig, page, fmt="png", scale=2, width=None, user_id=None):
        calls.append((page, fmt, scale))
        return f"NEW-{fmt}-page-{page + 1}".encode(), listed, listed[page]["name"]

    async def _outline(fig, user_id=None, page=None):
        return {"frames": [{"size": [720, 720]}], "pages": listed, "page": listed[0]["name"]}
    monkeypatch.setattr(refresh, "export", _export)
    monkeypatch.setattr(refresh, "export_page", _export_page)
    monkeypatch.setattr(refresh, "outline", _outline)
    d = tmp_path / "designs"
    d.mkdir()
    (d / "launch.fig").write_bytes(b"FIG")
    (d / "launch.png").write_bytes(_png(1080, 1080))
    return d, calls


def test_page_images_follow_the_designs_pages(tmp_path, monkeypatch):
    """Each page after the first keeps its image as <name>-page-<n>: re-exported with the
    design, one for a page added since, none left for a page that's gone."""
    d, calls = _page_env(tmp_path, monkeypatch, pages=3)
    (d / "launch-page-2.png").write_bytes(_png(540, 960))
    (d / "launch-page-5.png").write_bytes(b"OLD")                            # its page was removed
    (d / "launch-page-2.pdf").write_bytes(b"OLD-PDF")                        # someone exported page 2 as a PDF
    _saves(tmp_path, "designs/launch.fig")
    assert (d / "launch.png").read_bytes().endswith(b"NEW")                    # the first page is the design's own image
    assert (d / "launch-page-2.png").read_bytes() == b"NEW-png-page-2"
    assert (d / "launch-page-3.png").read_bytes() == b"NEW-png-page-3"         # a page added since gets one
    assert not (d / "launch-page-5.png").exists()
    assert (d / "launch-page-2.pdf").read_bytes() == b"NEW-pdf-page-2"
    assert not (d / "launch-page-3.pdf").exists()                             # a PDF only where there was one
    # Each at the design's own scale — its 1080 px image of a 720 px frame — whatever
    # was in that place before (a page's place changes when one before it goes).
    assert (1, "png", 1.5) in calls and (2, "png", 1.5) in calls and (1, "pdf", 2) in calls
    assert refresh.managed(tmp_path, "designs/launch-page-2.png")
    assert not refresh.managed(tmp_path, "designs/other-page-2.png")


def test_a_design_with_no_page_images_is_exported_as_before(tmp_path, monkeypatch):
    d, calls = _page_env(tmp_path, monkeypatch, pages=3)
    _saves(tmp_path, "designs/launch.fig")                                    # pages made by hand: no page images asked for
    assert calls == [] and sorted(f.name for f in d.iterdir()) == ["launch.fig", "launch.png"]

    async def go():                                                           # an agent made a page: now they are
        refresh.schedule(tmp_path, "designs/launch.fig", "org:u", pages=True)
        await asyncio.gather(*refresh._pending.values(), return_exceptions=True)
    asyncio.run(go())
    assert sorted(f.name for f in d.iterdir()) == ["launch-page-2.png", "launch-page-3.png", "launch.fig", "launch.png"]


def test_an_empty_page_has_no_image(tmp_path, monkeypatch):
    d, calls = _page_env(tmp_path, monkeypatch, pages=3, empty=(3,))
    (d / "launch-page-2.png").write_bytes(_png(540, 960))
    _saves(tmp_path, "designs/launch.fig")
    assert [c[0] for c in calls] == [1] and not (d / "launch-page-3.png").exists()


# ---- M5: more node types, bigger photos ----

def test_new_node_types_are_prepared(tmp_path, monkeypatch):
    (tmp_path / "brand").mkdir()
    (tmp_path / "brand" / "logo.svg").write_text("<svg viewBox='0 0 10 10'><circle cx='5' cy='5' r='4'/></svg>", encoding="utf-8")
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1080], "fill": "#0f172a", "nodes": [
        {"type": "icon", "name": "lucide:rocket", "x": 10, "y": 10, "size": "64"},
        {"type": "svg", "src": "brand/logo.svg", "x": 100, "y": 10, "w": 200},
        {"type": "qr", "text": "https://cycls.com", "x": 10, "y": 300, "size": 240},
        {"type": "list", "items": ["one", "two"], "x": 400, "y": 300, "w": 500},
        {"type": "chart", "kind": "column", "x": 10, "y": 600, "w": 500, "h": 300, "data": {"labels": ["a"], "series": [{"name": "s", "values": [1]}]}},
        {"type": "table", "x": 520, "y": 600, "w": 500, "columns": ["a"], "rows": [["1"]]},
        {"type": "line", "from": [0, 1000], "to": [500, 1000], "width": "4", "end": "arrow"},
    ]}}, _ws(tmp_path)))
    assert not _text(out).startswith("Error"), _text(out)
    icon, svg, qr, lst, chart, table, line = calls["spec"]["nodes"]
    assert icon["size"] == 64 and icon["color"] == "#ffffff"          # reads on the navy like text
    assert "<svg" in svg["svg"] and "src" not in svg                  # the file's markup travels
    assert lst["color"] == "#ffffff" and chart["color"] == "#ffffff" and table["color"] == "#ffffff"
    assert line["width"] == 4


def test_new_node_types_say_what_they_need(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    cases = [({"type": "icon", "name": "rocket"}, "Iconify name"),
             ({"type": "svg", "x": 0, "y": 0}, "needs `svg`"),
             ({"type": "qr", "x": 0, "y": 0}, "needs `text`"),
             ({"type": "chart", "x": 0, "y": 0}, "needs `data`"),
             ({"type": "table", "x": 0, "y": 0}, "needs `rows`")]
    for node, words in cases:
        out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [100, 100], "nodes": [node]}}, _ws(tmp_path)))
        assert out.startswith("Error") and words in out, out
    assert calls == {}


def test_photos_up_to_15_mb_go_through(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    (tmp_path / "attachments").mkdir()
    big = _png(4000, 3000) + b"\0" * (12 * 1024 * 1024)                 # a 12 MB photo: fine now
    (tmp_path / "attachments" / "big.png").write_bytes(big)
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "src": "attachments/big.png", "x": 0, "y": 0, "w": 1080, "h": 1080, "focus": [0.5, 0.2]}]}}, _ws(tmp_path)))
    assert not _text(out).startswith("Error"), _text(out)
    assert calls["spec"]["nodes"][0]["focus"] == [0.5, 0.2]              # the service crops around it
    (tmp_path / "attachments" / "huge.png").write_bytes(_png(10, 10) + b"\0" * (16 * 1024 * 1024))
    out = asyncio.run(_exec_design({"action": "render", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "src": "attachments/huge.png", "x": 0, "y": 0, "w": 100}]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "over the 15 MB" in out



# ---- decks of layouts: the SDK resolves images and the brand theme; the service lays out ----

from cycls._agent.tools import _brand_theme, _contrast, _prepare_spec


def test_a_deck_of_layouts_resolves_its_images(tmp_path, monkeypatch):
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "farm.png").write_bytes(_png(1600, 900))
    (tmp_path / "attachments" / "sara.png").write_bytes(_png(400, 400))
    (tmp_path / "attachments" / "mark.svg").write_text('<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>')
    deck = {"deck": {"theme": "editorial", "logo": "attachments/mark.svg", "slides": [
        {"layout": "image-left", "title": "Farms", "text": "Direct.", "image": {"src": "attachments/farm.png", "focus": [0.3, 0.5]}},
        {"layout": "team", "title": "Team", "people": [{"name": "Sara", "photo": "attachments/sara.png"}, {"name": "Omar"}]},
        {"layout": "custom", "nodes": [{"text": "hand-built", "x": 100, "y": 100}]}]}}
    spec, err, notes = _prepare_spec(deck, None, tmp_path)
    assert err is None and notes == []
    d = spec["deck"]
    assert d["size"] == [1920, 1080] and d["theme"] == "editorial"                  # the size a deck defaults to
    assert d["slides"][0]["image"]["src"] == "attachments/farm.png" and d["slides"][0]["image"]["focus"] == [0.3, 0.5]
    assert base64.b64decode(d["slides"][0]["image"]["image"]) == _png(1600, 900)
    assert base64.b64decode(d["slides"][1]["people"][0]["photo"]["image"]) == _png(400, 400)
    assert "photo" not in d["slides"][1]["people"][1]
    assert d["logo"]["svg"].startswith("<svg") and d["logo"]["src"] == "attachments/mark.svg"
    assert d["slides"][2]["nodes"][0]["type"] == "text"                              # custom nodes: prepared like a design
    assert deck["deck"]["slides"][0]["image"] == {"src": "attachments/farm.png", "focus": [0.3, 0.5]}   # input untouched


def test_deck_errors_name_the_fix(tmp_path):
    assert _prepare_spec({"deck": {"slides": []}}, None, tmp_path)[1].startswith("Error: a deck needs `slides`")
    err = _prepare_spec({"deck": {"slides": [{"layout": "image", "image": "attachments/none.jpg"}]}}, None, tmp_path)[1]
    assert "does not exist in the workspace" in err
    err = _prepare_spec({"deck": {"theme": "brand", "slides": [{"layout": "title", "title": "x"}]}}, None, tmp_path)[1]
    assert 'theme "brand" needs a brand kit' in err and "editorial" in err
    err = _prepare_spec({"deck": {"slides": [{"layout": "image", "image": "https://x.com/a.jpg"}]}}, None, tmp_path)[1]
    assert "must be a workspace file" in err


def test_a_brand_kit_is_the_decks_default_theme(tmp_path):
    _brand(tmp_path, "primary_color: '#0C2340'\naccent_color: '#c9a227'\nfont_heading: Playfair Display\nfont_body: Inter\n")
    (tmp_path / "brand" / "logo.png").write_bytes(_png(300, 100))
    from cycls._agent.tools import _load_brand
    spec, err, notes = _prepare_spec({"deck": {"slides": [{"layout": "title", "title": "x"}]}}, _load_brand(tmp_path), tmp_path)
    theme = spec["deck"]["theme"]
    assert err is None and theme["hero"] == "#0c2340" and theme["heading"] == "Playfair Display Bold"
    assert spec["deck"]["logo"]["src"] == "brand/logo.png"
    assert "brand kit as its theme" in notes[0]
    # An explicit theme is the model's choice — the brand kit doesn't override it.
    spec, _, notes = _prepare_spec({"deck": {"theme": "mono", "slides": [{"layout": "title", "title": "x"}]}}, _load_brand(tmp_path), tmp_path)
    assert spec["deck"]["theme"] == "mono" and notes == []


def test_the_brand_theme_keeps_text_readable():
    t = _brand_theme({"primary": "#0c2340", "accent": "#c9a227", "heading": None, "body": None})
    assert t["heroText"] == "#ffffff" and t["heroAccent"] == "#c9a227"                # gold reads on navy
    assert _contrast(t["accent"], "#ffffff") >= 4.5 and t["accent"] == "#0c2340"      # gold on white doesn't: navy
    t = _brand_theme({"primary": "#fde047", "accent": "#fde047", "heading": None, "body": None})
    assert t["heroText"] == "#111111" and t["accent"] == "#0f172a"                   # a yellow brand: ink on white


def test_rendering_a_deck_of_layouts(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch, image=b"PPTX", previews=[b"J1", b"J2"])
    out = asyncio.run(_exec_design({"action": "render", "name": "pitch", "format": "pptx", "spec": {"deck": {
        "theme": "editorial", "slides": [{"layout": "title", "title": "Brewly"}, {"layout": "closing", "title": "Thanks"}]}}},
        _ws(tmp_path)))
    assert calls["spec"]["deck"]["slides"][1]["layout"] == "closing" and calls["every"] is False
    assert json.loads((tmp_path / "designs" / "pitch.deck.json").read_text())["size"] == [1920, 1080]
    assert out["_ui"]["path"] == "designs/pitch.deck.json" and "2 slides" in out["_model"][-1]["text"]


def test_a_deck_keeps_its_direction_for_later_slides(tmp_path, monkeypatch):
    """The service decides a deck's direction from its words; the deck document keeps it, so
    a bilingual slide added or rebuilt later is laid out the same way round as the rest."""
    _fake_render(monkeypatch, image=b"PPTX", previews=[b"J1", b"J2"], dir="rtl")
    asyncio.run(_exec_design({"action": "render", "name": "pitch", "format": "pptx", "spec": {"deck": {
        "theme": "editorial", "slides": [{"layout": "title", "title": "Brewly"}, {"layout": "closing", "title": "Thanks"}]}}},
        _ws(tmp_path)))
    assert json.loads((tmp_path / "designs" / "pitch.deck.json").read_text())["settings"]["dir"] == "rtl"
    asyncio.run(_exec_design({"action": "render", "name": "own", "format": "pptx", "spec": {"deck": {
        "dir": "ltr", "slides": [{"layout": "title", "title": "x"}, {"layout": "closing", "title": "y"}]}}}, _ws(tmp_path)))
    assert json.loads((tmp_path / "designs" / "own.deck.json").read_text())["settings"]["dir"] == "ltr"   # the model's own wins


# ---- slide actions: add / update / move / duplicate / delete, on the saved .fig ----

def _deck(tmp_path, settings=None, slides=3):
    d = tmp_path / "designs"
    d.mkdir(exist_ok=True)
    (d / "pitch.fig").write_bytes(b"DECK-FIG")
    doc = {"type": "cycls.deck", "version": 1, "fig": "designs/pitch.fig", "size": [1920, 1080], "slides": slides,
           "exports": ["designs/pitch.pptx"]}
    if settings:
        doc["settings"] = settings
    (d / "pitch.deck.json").write_text(json.dumps(doc))
    return d


def test_add_slide_lays_it_out_with_the_decks_settings(tmp_path, monkeypatch):
    d = _deck(tmp_path, {"theme": "editorial", "size": [1920, 1080], "footer": {"text": "Brewly"}, "logo": "brand/mark.svg"})
    (tmp_path / "brand").mkdir()
    (tmp_path / "brand" / "mark.svg").write_text('<svg viewBox="0 0 4 4"><rect width="4" height="4"/></svg>')
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "farm.png").write_bytes(_png(1600, 900))
    calls, scheduled = _fake_apply(monkeypatch, result=b"NEW-FIG", compiled="S", touched=[1], previews=[b"JPEG-two"],
                                   slides=[{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}])
    out = asyncio.run(_exec_design({"action": "add_slide", "name": "pitch", "at": 2, "slide": {
        "layout": "image-left", "title": "Farms", "text": "Direct.", "image": "attachments/farm.png"}, "notes": "Slowly"}, _ws(tmp_path)))
    op = calls["ops"][0]
    assert op["op"] == "slide_add" and op["at"] == 1
    assert op["slide"]["image"]["src"] == "attachments/farm.png" and op["slide"]["notes"] == "Slowly"
    assert op["deck"]["theme"] == "editorial" and op["deck"]["footer"] == {"text": "Brewly"}
    assert op["deck"]["logo"]["svg"].startswith("<svg")                     # the deck's logo, resolved again
    assert (d / "pitch.fig").read_bytes() == b"NEW-FIG" and scheduled == ["designs/pitch.fig"]
    assert json.loads((d / "pitch.deck.json").read_text())["slides"] == 4
    from cycls._agent.design.store import version_of
    assert out["_ui"] == [{"type": "ui", "action": "design_command", "path": "designs/pitch.fig", "script": "S",
                           "version": version_of(b"NEW-FIG")},   # an open editor's saves go on from it
                          {"type": "ui", "action": "open_canvas", "path": "designs/pitch.deck.json", "name": "pitch.deck.json"}]
    m = out["_model"]
    assert m[0]["text"] == "Slide 2:" and "Slide added at position 2" in m[-1]["text"] and "now has 4 slides" in m[-1]["text"]


def test_update_move_duplicate_delete_map_to_ops(tmp_path, monkeypatch):
    _deck(tmp_path)
    calls, _ = _fake_apply(monkeypatch, slides=[{}, {}, {}])
    ws = _ws(tmp_path)
    run = lambda **inp: asyncio.run(_exec_design({"name": "pitch", **inp}, ws))
    run(action="update_slide", number=3, notes="New notes", transition="slide")
    assert calls["ops"] == [{"op": "slide_meta", "index": 2, "notes": "New notes", "transition": "slide"}]
    run(action="update_slide", number=1, slide={"layout": "title", "title": "Brewly 2"})
    assert calls["ops"][0]["op"] == "slide_update" and calls["ops"][0]["index"] == 0
    assert calls["ops"][0]["deck"]["size"] == [1920, 1080]                  # a hand-built deck: its size
    run(action="move_slide", number=4, to=2)
    assert calls["ops"] == [{"op": "slide_move", "index": 3, "to": 1}]
    run(action="duplicate_slide", number=2)
    assert calls["ops"] == [{"op": "slide_duplicate", "index": 1}]
    run(action="delete_slide", number=1)
    assert calls["ops"] == [{"op": "slide_delete", "index": 0}]


def test_slide_action_errors(tmp_path, monkeypatch):
    calls, _ = _fake_apply(monkeypatch, error="there is no slide 9 — the deck has 3")
    ws = _ws(tmp_path)
    run = lambda **inp: asyncio.run(_exec_design({"name": "pitch", **inp}, ws))
    assert "doesn't exist" in run(action="move_slide", number=1, to=2)
    _deck(tmp_path)
    assert "`number` is a slide number from 1" in run(action="delete_slide", number=0)
    assert "needs `slide`" in run(action="update_slide", number=1)
    assert "is a layout slide" in run(action="add_slide", slide={"title": "no layout"})
    out = run(action="move_slide", number=9, to=1)
    assert "there is no slide 9" in out and "Nothing was changed" in out
    assert (tmp_path / "designs" / "pitch.fig").read_bytes() == b"DECK-FIG"


def test_parallel_slide_actions_on_one_deck_dont_lose_a_change(tmp_path, monkeypatch):
    # The model calls tools in parallel: a move and an update in one turn each read
    # the .fig — without a lock the later write dropped the other's change.
    _deck(tmp_path)

    async def slow_apply(fig, script=None, user_id=None, ops=None, preview=False):
        await asyncio.sleep(0.05)
        return {"fig": fig + b"+" + ops[0]["op"].encode(), "lint": [], "script": "S", "preview": None,
                "previews": [], "touched": [], "slides": [{}] * 3}
    monkeypatch.setattr("cycls._agent.design.apply", slow_apply)
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda *a, **k: None)
    ws = _ws(tmp_path)

    async def both():
        await asyncio.gather(_exec_design({"action": "move_slide", "name": "pitch", "number": 3, "to": 1}, ws),
                             _exec_design({"action": "update_slide", "name": "pitch", "number": 2, "notes": "x"}, ws))
    asyncio.run(both())
    fig = (tmp_path / "designs" / "pitch.fig").read_bytes()
    assert fig.count(b"+") == 2 and b"slide_move" in fig and b"slide_meta" in fig    # both changes kept


# ---- stock photos: {"stock": "…"} is found (Pexels), saved to the workspace, credited ----

def _fake_stock(monkeypatch, photos=None):
    """The Pexels search and download faked; records the calls."""
    monkeypatch.setenv("PEXELS_API_KEY", "test-key")
    calls = {"search": [], "download": []}
    photos = photos if photos is not None else [
        {"id": 101, "photographer": "Ana", "url": "https://www.pexels.com/photo/101/",
         "src": {"large2x": "https://images.pexels.com/101-large2x.jpg", "original": "https://images.pexels.com/101.jpg"}},
        {"id": 102, "photographer": "Omar", "url": "https://www.pexels.com/photo/102/",
         "src": {"large2x": "https://images.pexels.com/102-large2x.jpg"}}]

    async def _search(query, orientation, per_page):
        calls["search"].append((query, orientation))
        return {"photos": photos}

    async def _download(url):
        calls["download"].append(url)
        return _jpeg(1880, 1253)
    monkeypatch.setattr("cycls._agent.design.stock._search", _search)
    monkeypatch.setattr("cycls._agent.design.stock._download", _download)
    return calls


def test_a_stock_photo_is_found_saved_and_credited(tmp_path, monkeypatch):
    calls = _fake_stock(monkeypatch)
    render = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "cafe", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "stock": "coffee beans on wood", "x": 0, "y": 0, "w": 1080, "h": 720}]}}, _ws(tmp_path)))
    saved = tmp_path / "attachments" / "stock" / "coffee-beans-on-wood-101.jpg"
    assert saved.is_file() and calls["download"] == ["https://images.pexels.com/101-large2x.jpg"]
    assert calls["search"] == [("coffee beans on wood", "landscape")]       # the box is wide
    node = render["spec"]["nodes"][0]
    assert "stock" not in node and node["image"]                            # an ordinary workspace photo now
    assert "Photo by Ana on Pexels (https://www.pexels.com/photo/101/)." in _text(out)


def test_the_same_stock_query_is_found_once(tmp_path, monkeypatch):
    calls = _fake_stock(monkeypatch)
    _fake_render(monkeypatch)
    spec = lambda: {"size": [1080, 1080], "nodes": [{"type": "image", "stock": "Coffee beans on wood", "x": 0, "y": 0, "w": 1080, "h": 720}]}
    asyncio.run(_exec_design({"action": "render", "name": "a", "spec": spec()}, _ws(tmp_path)))
    asyncio.run(_exec_design({"action": "render", "name": "b", "spec": spec()}, _ws(tmp_path)))
    assert len(calls["search"]) == 1 and len(calls["download"]) == 1


def test_pick_takes_another_stock_photo(tmp_path, monkeypatch):
    calls = _fake_stock(monkeypatch)
    _fake_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "name": "a", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "stock": "latte art", "pick": 1, "x": 0, "y": 0, "w": 600, "h": 600}]}}, _ws(tmp_path)))
    assert calls["download"] == ["https://images.pexels.com/102-large2x.jpg"] and calls["search"][0][1] == "square"


def test_a_deck_slot_takes_a_stock_photo(tmp_path, monkeypatch):
    _fake_stock(monkeypatch)
    render = _fake_render(monkeypatch, image=b"PPTX", previews=[b"J1", b"J2"])
    asyncio.run(_exec_design({"action": "render", "name": "pitch", "format": "pptx", "spec": {"deck": {"slides": [
        {"layout": "title", "title": "Brewly", "image": {"stock": "coffee shop interior"}},
        {"layout": "closing", "title": "Thanks"}]}}}, _ws(tmp_path)))
    slot = render["spec"]["deck"]["slides"][0]["image"]
    assert slot["src"].startswith("attachments/stock/coffee-shop-interior-") and slot["image"]


def test_stock_without_a_key_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "a", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "stock": "coffee", "x": 0, "y": 0, "w": 500, "h": 500}]}}, _ws(tmp_path)))
    assert out.startswith("Error: stock photos aren't set up here") and "`src`" in out


def test_no_stock_result_is_an_error(tmp_path, monkeypatch):
    _fake_stock(monkeypatch, photos=[])
    _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "a", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "stock": "zxqv", "x": 0, "y": 0, "w": 500, "h": 500}]}}, _ws(tmp_path)))
    assert "no stock photo found for 'zxqv'" in out


def test_an_edit_replaces_an_image_with_a_stock_photo(tmp_path, monkeypatch):
    _fake_stock(monkeypatch)
    calls, _ = _fake_apply(monkeypatch)
    _design(tmp_path)
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": [
        {"op": "replace_image", "node": "hero", "stock": "espresso"}]}, _ws(tmp_path)))
    op = calls["ops"][0]
    assert "stock" not in op and op.get("image")
    assert "Photo by Ana on Pexels" in _text(out)


# ---- documents: content that flows over paper pages, saved as a PDF ----

_DOC = {"title": "State of Coffee", "author": "Brewly", "theme": "editorial", "sections": [
    {"title": "Summary", "blocks": [{"lead": "Demand grew 18%."}, "A paragraph.", {"image": "attachments/beans.png", "caption": "Figure 1"}]},
    {"title": "Numbers", "blocks": [{"columns": [[{"image": "attachments/beans.png"}], ["Beside it."]]},
                                    {"nodes": [{"type": "image", "src": "attachments/beans.png", "x": 0, "y": 0, "w": 200, "h": 100}], "h": 120}]}]}


def _doc_render(monkeypatch, pages=3, **kw):
    return _fake_render(monkeypatch, image=b"%PDF-report", previews=[f"J{n}".encode() for n in range(1, pages + 1)],
                        slides=[{"name": "cover"}] + [{"name": f"page-{n}"} for n in range(2, pages + 1)], size=[1240, 1754], **kw)


def test_a_document_saves_its_pdf_and_opens_the_page_viewer(tmp_path, monkeypatch):
    _img(tmp_path, "attachments/beans.png", _png(1600, 900))
    calls = _doc_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "coffee-report", "spec": {"document": _DOC}}, _ws(tmp_path)))
    d = tmp_path / "designs"
    assert (d / "coffee-report.pdf").read_bytes() == b"%PDF-report" and (d / "coffee-report.fig").read_bytes() == b"FIGZ"
    assert calls["fmt"] == "pdf"                                              # whatever `format` says: a document is a PDF
    deck = json.loads((d / "coffee-report.deck.json").read_text(encoding="utf-8"))
    from cycls._agent.design.store import version_of
    assert deck == {"type": "cycls.deck", "version": 1, "kind": "document", "fig": "designs/coffee-report.fig",
                    "size": [1240, 1754], "slides": 3, "exports": ["designs/coffee-report.pdf"], "document": _DOC,
                    "rendered": version_of(b"FIGZ")}
    # The source is kept as it was written — paths, not the images' bytes.
    assert deck["document"]["sections"][0]["blocks"][2]["image"] == "attachments/beans.png"
    assert out["_ui"] == {"type": "ui", "action": "open_canvas", "path": "designs/coffee-report.deck.json", "name": "coffee-report.deck.json"}
    m = out["_model"]
    assert [b["text"] for b in m if b["type"] == "text"][:3] == ["Page 1:", "Page 2:", "Page 3:"]
    ack = m[-1]["text"]
    assert "Document saved (designs/coffee-report.pdf, 3 pages" in ack and "page viewer" in ack
    assert "All 3 pages are attached" in ack and '"replace": true' in ack


def test_a_long_document_is_seen_whole_its_first_pages_and_the_rest_on_contact_sheets(tmp_path, monkeypatch):
    """Past twelve pages the service sends four previews and every other page on contact sheets; the
    model gets them all, each sheet said for the pages it holds. (Of a 33-page report it was shown
    the first twelve pages, and nothing of the rest.)"""
    calls = _fake_render(monkeypatch, image=b"%PDF-long", previews=[f"J{n}".encode() for n in range(1, 5)],
                         slides=[{"name": f"page-{n}"} for n in range(1, 34)], size=[1240, 1754],
                         sheets=[b"S1", b"S2", b"S3"], sheet_pages=[[5, 16], [17, 28], [29, 33]])
    doc = {"title": "Long", "sections": [{"title": "One", "blocks": ["Text."]}]}
    out = asyncio.run(_exec_design({"action": "render", "name": "long", "spec": {"document": doc}}, _ws(tmp_path)))
    assert calls["sheets"] is True                                           # a document always asks
    m = out["_model"]
    assert [b["text"] for b in m if b["type"] == "text"][:7] == [
        "Page 1:", "Page 2:", "Page 3:", "Page 4:", "Pages 5–16, small:", "Pages 17–28, small:", "Pages 29–33, small:"]
    assert [base64.b64decode(b["source"]["data"]) for b in m if b["type"] == "image"] == [b"J1", b"J2", b"J3", b"J4", b"S1", b"S2", b"S3"]
    ack = m[-1]["text"]
    assert "33 pages" in ack
    assert "Pages 1–4 are attached to read, and pages 5–33 on 3 contact sheets" in ack
    assert "Design inspect lists the rest" not in ack


def test_a_document_rendered_again_is_looked_at_where_it_changed(tmp_path, monkeypatch):
    """After a section was rewritten the model was shown every page again — a dozen previews, or
    four and the contact sheets — though it had looked at all but one or two a moment before. The
    tool keeps each page's fingerprint, says with the next render which it has seen, and attaches
    only the pages the service says differ."""
    doc = {"title": "Report", "sections": [{"title": "One", "blocks": ["Text."]}, {"title": "Two", "blocks": ["More."]}]}
    three = [{"name": f"page-{n}"} for n in (1, 2, 3)]
    deck = lambda: json.loads((tmp_path / "designs" / "report.deck.json").read_text(encoding="utf-8"))
    calls = _fake_render(monkeypatch, image=b"%PDF-1", previews=[b"J1", b"J2", b"J3"], slides=three, size=[1240, 1754], hashes=["a1", "b2", "c3"])
    out = asyncio.run(_exec_design({"action": "render", "name": "report", "spec": {"document": doc}}, _ws(tmp_path)))
    assert calls["known"] == [] and "All 3 pages are attached" in out["_model"][-1]["text"]   # a first render: all of it
    assert deck()["hashes"] == ["a1", "b2", "c3"]
    # A section rewritten: the service is told what was seen, and previews the page that differs.
    calls = _fake_render(monkeypatch, image=b"%PDF-2", previews=[b"K3"], slides=three, size=[1240, 1754], hashes=["a1", "b2", "d4"], preview_of=[3])
    out = asyncio.run(_exec_design({"action": "update_section", "name": "report", "number": 2, "section": {"blocks": ["Rewritten."]}}, _ws(tmp_path)))
    assert calls["known"] == ["a1", "b2", "c3"]
    m = out["_model"]
    assert [b["text"] for b in m if b["type"] == "text"][0] == "Page 3:"
    assert [base64.b64decode(b["source"]["data"]) for b in m if b["type"] == "image"] == [b"K3"]
    ack = m[-1]["text"]
    assert "Page 3 changed and is attached; the other 2 pages are as you last saw them" in ack
    assert "All 3 pages are attached" not in ack
    assert deck()["hashes"] == ["a1", "b2", "d4"]
    # Two pages of three.
    calls = _fake_render(monkeypatch, image=b"%PDF-3", previews=[b"L2", b"L3"], slides=three, size=[1240, 1754], hashes=["a1", "e5", "f6"], preview_of=[2, 3])
    out = asyncio.run(_exec_design({"action": "update_section", "name": "report", "number": 2, "section": {"blocks": ["Longer now."]}}, _ws(tmp_path)))
    assert [b["text"] for b in out["_model"] if b["type"] == "text"][:2] == ["Page 2:", "Page 3:"]
    assert "Pages 2 and 3 changed and are attached; the other page is as you last saw it" in out["_model"][-1]["text"]
    # Nothing changed: nothing to look at again, and said so.
    calls = _fake_render(monkeypatch, image=b"%PDF-4", previews=[], slides=three, size=[1240, 1754], hashes=["a1", "e5", "f6"], preview_of=[])
    out = asyncio.run(_exec_design({"action": "update_section", "name": "report", "number": 2, "section": {"blocks": ["Longer now."]}}, _ws(tmp_path)))
    assert isinstance(out["_model"], str) and "No page changed" in out["_model"]


def test_a_documents_images_are_read_wherever_they_sit(tmp_path, monkeypatch):
    data = _img(tmp_path, "attachments/beans.png", _png(1600, 900))
    _img(tmp_path, "attachments/cover.png", _png(800, 1200))
    calls = _doc_render(monkeypatch)
    doc = {**_DOC, "cover": {"style": "full", "image": "attachments/cover.png"}, "logo": "attachments/beans.png",
           "pages": [{"fill": "#111111", "nodes": [{"type": "image", "src": "attachments/beans.png", "x": 0, "y": 0, "w": 620, "h": 400}]}]}
    asyncio.run(_exec_design({"action": "render", "name": "r", "spec": {"document": doc}}, _ws(tmp_path)))
    sent = calls["spec"]["document"]
    b64 = base64.b64encode(data).decode()
    figure = sent["sections"][0]["blocks"][2]["image"]
    assert figure == {"image": b64, "src": "attachments/beans.png", "w": 1600, "h": 900}    # its own shape: the page sizes it from that
    assert sent["cover"]["image"]["w"] == 800 and sent["cover"]["image"]["h"] == 1200
    assert sent["logo"]["image"] == b64
    assert sent["sections"][1]["blocks"][0]["columns"][0][0]["image"]["image"] == b64       # inside a column
    assert sent["sections"][1]["blocks"][1]["nodes"][0]["image"] == b64                     # a hand-built area's nodes
    assert sent["pages"][0]["nodes"][0]["image"] == b64                                     # a hand-built page's
    assert sent["theme"] == "editorial"


def test_a_document_takes_the_brand_kit_unless_it_names_a_theme(tmp_path, monkeypatch):
    _brand(tmp_path, "colors:\n  primary: '#0b3d2e'\n  accent: '#e0a526'\nfonts:\n  heading: Fraunces\n  body: Inter\n")
    _img(tmp_path, "brand/logo.png", _png(400, 120))
    calls = _doc_render(monkeypatch)
    plain = {"title": "T", "sections": [{"title": "A", "blocks": ["Text."]}]}
    out = asyncio.run(_exec_design({"action": "render", "name": "r", "spec": {"document": plain}}, _ws(tmp_path)))
    theme = calls["spec"]["document"]["theme"]
    assert theme["hero"] == "#0b3d2e" and theme["accent2"] == "#e0a526" and theme["heading"] == "Fraunces Bold"
    assert calls["spec"]["document"]["logo"]["src"] == "brand/logo.png"
    assert "uses the workspace brand kit" in out["_model"][-1]["text"]
    # A theme the agent (or the user) chose stands; so does a document with no kit at all.
    asyncio.run(_exec_design({"action": "render", "name": "r2", "spec": {"document": {**plain, "theme": "tech-dark"}}}, _ws(tmp_path)))
    assert calls["spec"]["document"]["theme"] == "tech-dark" and "logo" not in calls["spec"]["document"]


def test_what_is_wrong_with_a_document_is_said_in_words(tmp_path, monkeypatch):
    calls = _doc_render(monkeypatch)
    run = lambda doc: asyncio.run(_exec_design({"action": "render", "name": "r", "spec": {"document": doc}}, _ws(tmp_path)))
    assert "needs `sections`" in run({"title": "T"})
    assert "needs a `title`" in run({"sections": [{"title": "A", "blocks": ["x"]}]})
    assert 'theme "brand" needs a brand kit' in run({"title": "T", "theme": "brand", "sections": [{"title": "A", "blocks": ["x"]}]})
    assert "missing.png" in run({"title": "T", "sections": [{"title": "A", "blocks": [{"image": "attachments/missing.png"}]}]})
    assert "renders" not in calls and not (tmp_path / "designs").exists()   # nothing was sent, nothing saved


def test_replace_renders_the_same_document_again_and_keeps_the_old_one(tmp_path, monkeypatch):
    from cycls._agent import versions
    ws = _ws(tmp_path)
    plain = {"title": "T", "sections": [{"title": "A", "blocks": ["Text."]}]}
    _doc_render(monkeypatch, fig=b"FIG-ONE")
    asyncio.run(_exec_design({"action": "render", "name": "report", "spec": {"document": plain}}, ws))
    _doc_render(monkeypatch, pages=4, fig=b"FIG-TWO")
    longer = {**plain, "sections": [*plain["sections"], {"title": "B", "blocks": ["More."]}]}
    out = asyncio.run(_exec_design({"action": "render", "name": "report", "replace": True, "spec": {"document": longer}}, ws))
    d = tmp_path / "designs"
    assert sorted(p.name for p in d.iterdir() if p.is_file()) == ["report.deck.json", "report.fig", "report.pdf"]   # no report-2
    assert (d / "report.fig").read_bytes() == b"FIG-TWO"
    deck = json.loads((d / "report.deck.json").read_text(encoding="utf-8"))
    assert deck["slides"] == 4 and len(deck["document"]["sections"]) == 2
    kept = versions.listing(tmp_path, "designs/report.fig")
    assert len(kept) == 1 and kept[0]["by"] == "agent"                         # the earlier pages are in its history
    assert "Document re-rendered (designs/report.pdf, 4 pages" in out["_model"][-1]["text"]
    # What is open follows: an editor on the .fig re-opens it, the viewer fetches its pages again.
    assert [e["action"] for e in out["_ui"]] == ["design_command", "open_canvas"]
    assert out["_ui"][0]["path"] == "designs/report.fig" and out["_ui"][0]["reload"] is True
    # Without `replace`, the same name is a new document beside it — nothing is overwritten.
    asyncio.run(_exec_design({"action": "render", "name": "report", "spec": {"document": plain}}, ws))
    assert (d / "report-2.pdf").is_file() and (d / "report.fig").read_bytes() == b"FIG-TWO"


def test_an_argument_whose_json_text_is_broken_is_said_where_it_breaks(tmp_path, monkeypatch):
    """A real agent's 19-page report: its 6,000-token `spec` came as text with a flaw in it. The
    tool answered "`render` needs a `spec` object" — nothing about the text, or where — and
    the whole document was written out again, blind."""
    calls = _doc_render(monkeypatch)
    good = json.dumps({"document": {"title": "Remote Work", "sections": [{"title": "Summary", "blocks": ["Hybrid has won."]}]}})
    # A quote left unescaped inside a string.
    broken = good.replace("Hybrid has won.", 'The "hybrid" model has won.')
    out = asyncio.run(_exec_design({"action": "render", "name": "r", "spec": broken}, _ws(tmp_path)))
    assert isinstance(out, str) and out.startswith("Error: `spec` came as text that isn't valid JSON")
    assert f"character {broken.index('hybrid')}" in out and 'The "hybrid" model' in out            # where, and what is there
    assert "unescaped" in out and "add_section" in out
    assert "renders" not in calls                                                    # nothing was rendered
    # Cut off before its end (the reply ran out): said as that.
    out = asyncio.run(_exec_design({"action": "render", "name": "r", "spec": good[:-30]}, _ws(tmp_path)))
    assert "isn't valid JSON" in out and "cut off" in out and "add_section" in out
    # `ops` and `slide` the same.
    out = asyncio.run(_exec_design({"action": "edit", "name": "r", "ops": '[{"op": "set_text", "node": "title", "text": "A "b""}]'}, _ws(tmp_path)))
    assert out.startswith("Error: `ops` came as text that isn't valid JSON")
    # Text that isn't trying to be JSON is left to the action to explain, as before.
    out = asyncio.run(_exec_design({"action": "render", "name": "r", "spec": "a poster for the launch"}, _ws(tmp_path)))
    assert "`render` needs a `spec` object" in out


def test_an_argument_sent_as_its_json_text_is_read_as_the_object(tmp_path, monkeypatch):
    # Some models hand a large nested argument over as a JSON string (seen on prod:
    # a document's spec, refused as "needs a `spec` object" — one wasted round trip).
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "launch", "format": "png",
                                    "spec": json.dumps({"size": [1080, 1080]})}, _ws(tmp_path)))
    assert calls["spec"] == {"size": [1080, 1080]} and "saved (designs/launch.png" in _text(out)
    calls = _doc_render(monkeypatch)
    doc = {"title": "T", "sections": [{"title": "A", "blocks": ["Text."]}]}
    out = asyncio.run(_exec_design({"action": "render", "name": "r", "spec": json.dumps({"document": doc})}, _ws(tmp_path)))
    assert calls["spec"]["document"]["title"] == "T" and "Document saved" in out["_model"][-1]["text"]
    # An edit's ops the same way.
    _design(tmp_path, "poster")
    applied, _ = _fake_apply(monkeypatch)
    asyncio.run(_exec_design({"action": "edit", "name": "poster",
                              "ops": json.dumps([{"op": "set_text", "node": "title", "text": "Hi"}])}, _ws(tmp_path)))
    assert applied["ops"] == [{"op": "set_text", "node": "title", "text": "Hi"}]
    # Text that isn't an object is still told what's needed.
    assert "needs a `spec` object" in asyncio.run(_exec_design({"action": "render", "name": "x", "spec": "a poster, please"}, _ws(tmp_path)))
    assert "needs a `spec` object" in asyncio.run(_exec_design({"action": "render", "name": "x", "spec": ""}, _ws(tmp_path)))


# ---- a document's own changes: the part that changes is sent, not the whole document ----

def _saved_document(tmp_path, monkeypatch, name="report"):
    doc = {"title": "State of Coffee", "author": "Brewly", "theme": "editorial", "sections": [
        {"title": "Summary", "blocks": [{"lead": "Demand grew 18%."}, "A paragraph."]},
        {"title": "Numbers", "blocks": [{"table": {"columns": ["A"], "rows": [["1"]]}}]},
        {"title": "Outlook", "blocks": ["Short."]}]}
    _doc_render(monkeypatch, fig=b"FIG-ONE")
    asyncio.run(_exec_design({"action": "render", "name": name, "spec": {"document": doc}}, _ws(tmp_path)))
    return doc


def _source(tmp_path, name="report"):
    return json.loads((tmp_path / "designs" / f"{name}.deck.json").read_text(encoding="utf-8"))["document"]


def test_a_documents_sections_are_added_rewritten_moved_and_removed_in_place(tmp_path, monkeypatch):
    from cycls._agent import versions
    ws = _ws(tmp_path)
    _saved_document(tmp_path, monkeypatch)
    calls = _doc_render(monkeypatch, pages=4, fig=b"FIG-TWO")
    run = lambda inp: asyncio.run(_exec_design({"name": "report", **inp}, ws))

    out = run({"action": "update_section", "number": 2, "section": {"blocks": ["Rewritten.", {"note": "Source: a panel."}]}})
    # The whole document goes to the service — the section changed, the rest as it was — and it stays one document.
    assert [s["title"] for s in calls["spec"]["document"]["sections"]] == ["Summary", "Numbers", "Outlook"]
    assert calls["spec"]["document"]["sections"][1]["blocks"] == ["Rewritten.", {"note": "Source: a panel."}]
    assert calls["spec"]["document"]["sections"][0]["blocks"] == [{"lead": "Demand grew 18%."}, "A paragraph."]
    assert _source(tmp_path)["sections"][1]["blocks"][0] == "Rewritten."
    assert "Document re-rendered (designs/report.pdf, 4 pages" in out["_model"][-1]["text"]
    assert [e["action"] for e in out["_ui"]] == ["design_command", "open_canvas"]
    assert sorted(p.name for p in (tmp_path / "designs").iterdir() if p.is_file()) == ["report.deck.json", "report.fig", "report.pdf"]
    assert len(versions.listing(tmp_path, "designs/report.fig")) == 1                       # the earlier pages are kept

    run({"action": "update_section", "number": 1, "section": {"title": "Executive summary"}})   # a title alone: its blocks stay
    assert _source(tmp_path)["sections"][0] == {"title": "Executive summary", "blocks": [{"lead": "Demand grew 18%."}, "A paragraph."]}

    run({"action": "add_section", "at": 2, "section": {"title": "Method", "blocks": ["How it was measured."]}})
    assert [s["title"] for s in _source(tmp_path)["sections"]] == ["Executive summary", "Method", "Numbers", "Outlook"]
    run({"action": "add_section", "section": {"title": "Appendix", "blocks": ["Tables."]}})       # no `at`: the end
    run({"action": "move_section", "number": 5, "to": 2})
    assert [s["title"] for s in _source(tmp_path)["sections"]] == ["Executive summary", "Appendix", "Method", "Numbers", "Outlook"]
    run({"action": "delete_section", "number": 2})
    assert [s["title"] for s in _source(tmp_path)["sections"]] == ["Executive summary", "Method", "Numbers", "Outlook"]

    # Its title, look and cover: the keys given are changed, null takes one away, the sections stay.
    run({"action": "update_document", "document": {"title": "State of Coffee 2026", "theme": "corporate", "author": None,
                                                   "cover": {"style": "band"}}})
    src = _source(tmp_path)
    assert (src["title"], src["theme"], src["cover"], "author" in src, len(src["sections"])) == ("State of Coffee 2026", "corporate", {"style": "band"}, False, 4)
    assert calls["spec"]["document"]["theme"] == "corporate"


def test_a_section_action_that_cannot_be_made_says_why_and_changes_nothing(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    doc = _saved_document(tmp_path, monkeypatch)
    calls = _doc_render(monkeypatch)
    run = lambda inp: asyncio.run(_exec_design({"name": "report", **inp}, ws))
    assert "has 3 sections" in run({"action": "update_section", "number": 7, "section": {"blocks": ["x"]}})
    assert "`number`" in run({"action": "delete_section"})
    assert "needs `section`" in run({"action": "add_section"})
    assert "needs `section`" in run({"action": "update_section", "number": 1})
    assert "needs `document`" in run({"action": "update_document"})
    assert "`sections`" in run({"action": "update_document", "document": {"sections": []}})      # that's what the section actions are for
    for n in (1, 1):
        run({"action": "delete_section", "number": n})
    assert "keeps at least one section" in run({"action": "delete_section", "number": 1})
    assert "renders" in calls and calls["renders"] == 2 and len(_source(tmp_path)["sections"]) == 1
    # A deck, or a design that isn't there, isn't a document.
    _fake_render(monkeypatch, image=b"PPTX", previews=[b"J1", b"J2"], slides=[{"name": "a"}, {"name": "b"}])
    asyncio.run(_exec_design({"action": "render", "name": "pitch", "format": "pptx", "spec": {"frames": [{"size": "slide"}, {"size": "slide"}]}}, ws))
    assert "isn't a document" in asyncio.run(_exec_design({"action": "delete_section", "name": "pitch", "number": 1}, ws))
    assert "isn't a document" in asyncio.run(_exec_design({"action": "add_section", "name": "nope", "section": {"title": "A", "blocks": ["x"]}}, ws))
    # What the service refuses (a block it doesn't know) leaves the document as it was.
    async def refuse(spec, **kw):
        raise RuntimeError('section 1 (Outlook), block 1: unknown block "sparkles"')
    monkeypatch.setattr("cycls._agent.design.render", refuse)
    before = _source(tmp_path)
    assert 'unknown block "sparkles"' in run({"action": "update_section", "number": 1, "section": {"blocks": [{"sparkles": 1}]}})
    assert _source(tmp_path) == before


def test_inspect_lists_a_documents_sections(tmp_path, monkeypatch):
    _saved_document(tmp_path, monkeypatch)

    async def outline(fig, user_id=None, page=None):
        return {"frames": [{"slide": 1, "name": "cover", "size": [1240, 1754], "nodes": []}], "pages": [], "page": ""}
    monkeypatch.setattr("cycls._agent.design.outline", outline)
    text = asyncio.run(_exec_design({"action": "inspect", "name": "report"}, _ws(tmp_path)))
    assert "A document of 3 sections" in text
    assert "1. Summary — lead, p" in text and "2. Numbers — table" in text and "3. Outlook — p" in text
    assert "update_section" in text


# ---- charts and tables straight from a workspace spreadsheet ----

def test_a_chart_and_a_table_are_read_from_a_workspace_spreadsheet(tmp_path, monkeypatch):
    _img(tmp_path, "data/quarters.csv", "Quarter,2025,2026,Note\nQ1,96.2,104.1,a\nQ2,98.9,106.4,b\nQ3,101.3,108.7,c\n".encode("utf-8-sig"))
    calls = _doc_render(monkeypatch)
    doc = {"title": "T", "sections": [{"title": "A", "blocks": [
        {"chart": {"kind": "column", "from": "data/quarters.csv"}, "caption": "By quarter"},
        {"chart": {"kind": "line", "from": "data/quarters.csv", "x": "Quarter", "y": ["2026"]}},
        {"table": {"from": "data/quarters.csv", "columns": ["Quarter", "2026"], "limit": 2}, "caption": "Latest"},
        {"table": {"from": "data/quarters.csv"}}]}]}
    asyncio.run(_exec_design({"action": "render", "name": "r", "spec": {"document": doc}}, _ws(tmp_path)))
    blocks = calls["spec"]["document"]["sections"][0]["blocks"]
    # Numbers are numbers; the first column names the points; the columns that aren't numbers are left out.
    assert blocks[0]["chart"] == {"kind": "column", "data": {"labels": ["Q1", "Q2", "Q3"], "series": [
        {"name": "2025", "values": [96.2, 98.9, 101.3]}, {"name": "2026", "values": [104.1, 106.4, 108.7]}]}}
    assert blocks[1]["chart"]["data"] == {"labels": ["Q1", "Q2", "Q3"], "series": [{"name": "2026", "values": [104.1, 106.4, 108.7]}]}
    assert blocks[2]["table"] == {"columns": ["Quarter", "2026"], "rows": [["Q1", "104.1"], ["Q2", "106.4"]]}
    assert blocks[3]["table"] == {"columns": ["Quarter", "2025", "2026", "Note"], "rows": [["Q1", "96.2", "104.1", "a"], ["Q2", "98.9", "106.4", "b"], ["Q3", "101.3", "108.7", "c"]]}
    # The document's kept source names the file, not its rows: a re-render reads it again.
    kept = json.loads((tmp_path / "designs" / "r.deck.json").read_text(encoding="utf-8"))["document"]["sections"][0]["blocks"]
    assert kept[0]["chart"] == {"kind": "column", "from": "data/quarters.csv"}


def test_what_is_wrong_with_a_spreadsheet_is_said_in_words(tmp_path, monkeypatch):
    _img(tmp_path, "data/q.csv", b"Quarter,2025\nQ1,96.2\n")
    _img(tmp_path, "data/words.csv", b"Name,City\nA,Riyadh\n")
    calls = _doc_render(monkeypatch)
    run = lambda block: asyncio.run(_exec_design({"action": "render", "name": "r", "spec": {"document": {
        "title": "T", "sections": [{"title": "A", "blocks": [block]}]}}}, _ws(tmp_path)))
    assert "data/missing.csv" in run({"chart": {"from": "data/missing.csv"}})
    assert 'no column "2030"' in run({"chart": {"from": "data/q.csv", "y": ["2030"]}}) and "Quarter, 2025" in run({"chart": {"from": "data/q.csv", "y": ["2030"]}})
    assert "no column of numbers" in run({"chart": {"from": "data/words.csv"}})
    assert ".csv" in run({"table": {"from": "notes/readme.md"}})
    assert "renders" not in calls


def test_a_spreadsheet_xlsx_is_read_when_openpyxl_is_there(tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = "Teams"
    for row in (["Team", "Headcount"], ["Engineering", 184], ["Design", 46]):
        wb.active.append(row)
    (tmp_path / "data").mkdir()
    wb.save(tmp_path / "data" / "teams.xlsx")
    calls = _doc_render(monkeypatch)
    asyncio.run(_exec_design({"action": "render", "name": "r", "spec": {"document": {"title": "T", "sections": [{"title": "A", "blocks": [
        {"table": {"from": "data/teams.xlsx"}}, {"chart": {"kind": "bar", "from": "data/teams.xlsx", "sheet": "Teams"}}]}]}}}, _ws(tmp_path)))
    blocks = calls["spec"]["document"]["sections"][0]["blocks"]
    assert blocks[0]["table"] == {"columns": ["Team", "Headcount"], "rows": [["Engineering", "184"], ["Design", "46"]]}
    assert blocks[1]["chart"]["data"] == {"labels": ["Engineering", "Design"], "series": [{"name": "Headcount", "values": [184, 46]}]}


# ---- from an existing PDF: its words and its pictures, to make a document of ----

def test_a_pdfs_text_and_pictures_are_taken_out_for_a_redesign(tmp_path, monkeypatch):
    import pathlib
    from cycls._agent.tools import _pdf_parts
    _img(tmp_path, "attachments/old-report.pdf", b"%PDF-1.4 fake")
    ran = []

    async def tool(*argv, timeout=60):
        ran.append(argv)
        if argv[0] == "pdfinfo":
            return 0, b"Title:          Old Report\nPages:          3\nPage size:      595 x 842 pts (A4)\n"
        if argv[0] == "pdftotext":
            return 0, "Old Report\n\nA first page of text.\n\fSecond page.\n\f\fTrailing".encode()
        if argv[0] == "pdfimages":
            prefix = pathlib.Path(argv[-1])
            (prefix.parent / f"{prefix.name}-000.png").write_bytes(_png(1600, 900))
            (prefix.parent / f"{prefix.name}-001.jpg").write_bytes(_jpeg(1200, 800))
            (prefix.parent / f"{prefix.name}-002.png").write_bytes(_png(24, 24))            # an icon: left behind
            (prefix.parent / f"{prefix.name}-003.png").write_bytes(_png(1600, 900))          # the same picture again
            return 0, b""
        return 1, b""
    monkeypatch.setattr("cycls._agent.design.extract._run_tool", tool)
    out = asyncio.run(_exec_design({"action": "extract", "path": "attachments/old-report.pdf", "name": "old-report"}, _ws(tmp_path)))
    assert isinstance(out, str)
    assert "attachments/old-report.pdf — 3 pages" in out and "Old Report" in out
    assert "Page 1:" in out and "A first page of text." in out and "Page 2:" in out and "Second page." in out
    saved = sorted(p.name for p in (tmp_path / "designs" / "old-report-assets").iterdir())
    assert saved == ["picture-1.png", "picture-2.jpg"]                                       # no icon, no repeat
    assert "designs/old-report-assets/picture-1.png (1600×900)" in out and "designs/old-report-assets/picture-2.jpg (1200×800)" in out
    assert '"image": "designs/old-report-assets/picture-1.png"' in out                       # how to use one
    assert _pdf_parts is not None
    # Not a PDF, not there, no poppler: said in words.
    run = lambda path: asyncio.run(_exec_design({"action": "extract", "path": path}, _ws(tmp_path)))
    assert "doesn't exist" in run("attachments/none.pdf")
    _img(tmp_path, "attachments/notes.txt", b"hi")
    assert "a PDF" in run("attachments/notes.txt")

    async def missing(*argv, timeout=60):
        raise FileNotFoundError(argv[0])
    monkeypatch.setattr("cycls._agent.design.extract._run_tool", missing)
    assert "poppler" in run("attachments/old-report.pdf")


def _pdf_tools(monkeypatch, info, flow, layout, images=(), ran=None):
    """Poppler, faked: pdfinfo's answer, pdftotext's two readings (in reading order; as
    laid out, with -layout), the files pdfimages leaves, and a page drawn by pdftoppm."""
    import pathlib
    ran = [] if ran is None else ran

    async def tool(*argv, timeout=60):
        ran.append(argv)
        if argv[0] == "pdfinfo":
            return 0, info.encode()
        if argv[0] == "pdftotext":
            return 0, (layout if "-layout" in argv else flow).encode()
        if argv[0] == "pdfimages":
            prefix = pathlib.Path(argv[-1])
            for k, data in enumerate(images):
                (prefix.parent / f"{prefix.name}-{k:03d}.png").write_bytes(data)
            return 0, b""
        if argv[0] == "pdftoppm":
            out = pathlib.Path(argv[-1])
            ext = "jpg" if "-jpeg" in argv else "png"
            w, h = (int(argv[argv.index("-W") + 1]), int(argv[argv.index("-H") + 1])) if "-W" in argv else (850, 1100)
            (out.parent / f"{out.name}.{ext}").write_bytes(_jpeg(w, h) if ext == "jpg" else _png(w, h))
            return 0, b""
        return 1, b""
    monkeypatch.setattr("cycls._agent.design.extract._run_tool", tool)
    return ran


_LETTER = "Title:          \nSubject:        \nPages:          2\nPage size:      612 x 792 pts (letter)\n"   # (no title: pdfTeX)


def test_a_real_pdfs_words_come_in_reading_order_and_its_tables_as_they_are_laid_out(tmp_path, monkeypatch):
    """A two-column paper read "as laid out" came back with its columns side by side on every
    line — the left column's sentence cut by the right one's — and most of each page's
    allowance spent on the gap between them. The words are read in reading order; a table's
    rows, which only the laid-out reading keeps together, are added from it."""
    _img(tmp_path, "attachments/paper.pdf", b"%PDF-1.5 fake")
    flow = ("Deep Residual Learning\n\nDeeper neural networks are more difficult to train. We\npresent a residual learning framework.\n"
            "model\ntop-1 err.\ntop-5 err.\nVGG-16\n28.07\n9.33\n\fSecond page, first column.\nSecond page, second column.\n")
    layout = ("                    Deep Residual Learning\n\n"
              "   Deeper neural networks are more difficult to train. We          The depth of representations is of central\n"
              "   present a residual learning framework.                          importance for many visual tasks.\n\n"
              "        model            top-1 err.     top-5 err.\n"
              "        VGG-16 [41]        28.07           9.33\n"
              "        GoogLeNet [44]       -             9.15\n"
              "        PReLU-net [13]     24.27           7.38\n"
              "        ResNet-152         19.38           4.49\n\n"
              "   Table 3. Error rates on ImageNet validation.\n"
              "\fSecond page, first column.              Second page, second column.\n")
    ran = _pdf_tools(monkeypatch, _LETTER, flow, layout)
    out = asyncio.run(_exec_design({"action": "extract", "path": "attachments/paper.pdf"}, _ws(tmp_path)))
    assert out.startswith("attachments/paper.pdf — 2 pages, 612 x 792 pts (letter).")    # no title is no title (not the line after it)
    assert "Deeper neural networks are more difficult to train. We\npresent a residual learning framework." in out   # in reading order
    assert "train. We          The depth" not in out                                    # not the two columns side by side
    assert "Its tables, as they are laid out:" in out
    assert "model | top-1 err. | top-5 err." in out and "VGG-16 [41] | 28.07 | 9.33" in out and "ResNet-152 | 19.38 | 4.49" in out
    assert "Second page, first column.\nSecond page, second column." in out
    assert [a for a in ran if a[0] == "pdftotext" and "-layout" not in a] and [a for a in ran if a[0] == "pdftotext" and "-layout" in a]
    # A paper's charts are drawn, not stored: how to take one is said.
    assert "no pictures" in out and '"page": 1' in out and '"area"' in out


def test_arabic_saved_as_shaped_glyphs_is_put_back_into_letters_and_said_not_to_be_trusted(tmp_path, monkeypatch):
    """A real Arabic PDF (Word → Distiller) keeps each letter as the glyph it was drawn with
    — ﻟ ﺎ ﻋ — some of them twice, lines out of order. The glyphs are put back into letters,
    and the model is told to take the wording from the pages it can see."""
    _img(tmp_path, "attachments/declaration.pdf", b"%PDF-1.5 fake")
    shaped = "\u202b\ufedf\ufee4\ufe8e \ufedb\ufe8e\ufee5 \u202a2026\u202c \ufe8d\ufefb\ufecb\ufe98\ufeae\ufe8d\ufed1\u202c " * 4
    _pdf_tools(monkeypatch, "Pages:          1\nPage size:      595 x 842 pts (A4)\n", shaped + "\n", shaped + "\n")
    out = asyncio.run(_exec_design({"action": "extract", "path": "attachments/declaration.pdf"}, _ws(tmp_path)))
    assert out.startswith("attachments/declaration.pdf — 1 page, ")
    assert "\u0644\u0645\u0627 \u0643\u0627\u0646 2026 " in out                     # لما كان, in letters — and none of the reader's direction marks
    assert not [ch for ch in out if "\ufe70" <= ch <= "\ufeff" or "\u202a" <= ch <= "\u202e"]
    assert "can't be trusted" in out and '"page": 1' in out


def test_a_scan_is_said_to_be_one_and_its_pages_are_not_offered_as_pictures(tmp_path, monkeypatch):
    _img(tmp_path, "attachments/scan.pdf", b"%PDF-1.5 fake")
    _pdf_tools(monkeypatch, "Pages:          2\nPage size:      612 x 792 pts (letter)\n", "\f\f", "\f\f",
               images=[_png(1275, 1650), _png(1274, 1649)])
    out = asyncio.run(_exec_design({"action": "extract", "path": "attachments/scan.pdf"}, _ws(tmp_path)))
    assert "a scan" in out and '"page": 1' in out
    assert not (tmp_path / "designs" / "scan-assets").exists()                           # a picture of a page is not a picture to reuse
    assert "picture-1" not in out


def test_a_long_pdfs_text_fits_the_reply_and_the_rest_is_read_on_by_page(tmp_path, monkeypatch):
    """A tool's reply of 20,000 characters or more is put in a file and the model shown its
    first lines. `extract` allowed 60,000 — so a real agent redesigning a 12-page paper got a
    600-character preview, and read the file back with five shell commands."""
    from cycls._agent import spill
    _img(tmp_path, "attachments/paper.pdf", b"%PDF-1.5 fake")
    pages = [f"Page {n} opens here. " + "words " * 660 for n in range(1, 13)]      # ~4,000 characters a page
    ran = []

    async def tool(*argv, timeout=60):
        ran.append(argv)
        if argv[0] == "pdfinfo":
            return 0, b"Pages:          12\nPage size:      612 x 792 pts (letter)\n"
        if argv[0] == "pdftotext":
            first = int(argv[argv.index("-f") + 1]) if "-f" in argv else 1
            last = int(argv[argv.index("-l") + 1]) if "-l" in argv else 12
            return 0, "\f".join(pages[first - 1:last]).encode()
        return 0, b""
    monkeypatch.setattr("cycls._agent.design.extract._run_tool", tool)
    run = lambda **kw: asyncio.run(_exec_design({"action": "extract", "path": "attachments/paper.pdf", **kw}, _ws(tmp_path)))
    out = run()
    assert len(out) < spill.SPILL_AT                                              # it is read, not filed
    assert "Page 1 opens here." in out and "Page 4 opens here." in out and "Page 5 opens here." not in out
    assert '(Pages 5–12 are not shown here: extract {"path": "attachments/paper.pdf", "pages": "5-12"} reads on.)' in out
    # Reading on: those pages' text, numbered as they are in the PDF; its pictures are not taken again.
    ran.clear()
    out = run(pages="5-12")
    # (Its first line names the pages it holds — not the range asked for, which a real agent took for what it was shown.)
    assert out.startswith("attachments/paper.pdf — pages 5–8 of 12.") and len(out) < spill.SPILL_AT
    assert "Page 5:" in out and "Page 5 opens here." in out and "Page 8 opens here." in out and "Page 9 opens here." not in out
    assert '"pages": "9-12"' in out
    asked = [a for a in ran if a[0] == "pdftotext"]
    assert asked and all(a[a.index("-f") + 1] == "5" and a[a.index("-l") + 1] == "12" for a in asked)
    assert not [a for a in ran if a[0] == "pdfimages"] and "pictures" not in out
    # The other ways to name pages; and what is wrong with a request, in words.
    assert "Page 10 opens here." in run(pages=[9, 10]) and "Page 12 opens here." in run(pages=12) and "Page 7 opens here." in run(pages="7")
    assert run(pages=12).startswith("attachments/paper.pdf — page 12 of 12.")
    assert "12 pages" in run(pages="13-14")
    assert '"5-8"' in run(pages="the end")


def test_a_page_of_a_pdf_is_looked_at_and_a_figure_cut_out_of_it(tmp_path, monkeypatch):
    """A chart drawn in the PDF (not a photo in it) is not among its pictures. The page is
    looked at, and the figure cut out of it by where it is: [left, top, width, height] as
    parts of the page."""
    _img(tmp_path, "attachments/paper.pdf", b"%PDF-1.5 fake")
    ran = _pdf_tools(monkeypatch, "Pages:          12\nPage    3 size: 612 x 792 pts (letter)\n", "", "")
    out = asyncio.run(_exec_design({"action": "extract", "path": "attachments/paper.pdf", "page": 3}, _ws(tmp_path)))
    m = out["_model"]
    assert m[0]["type"] == "image" and m[0]["source"]["media_type"] == "image/jpeg"
    assert "page 3 of 12" in m[-1]["text"].lower() and '"area"' in m[-1]["text"]
    look = next(a for a in ran if a[0] == "pdftoppm")
    assert look[look.index("-f") + 1] == "3" and look[look.index("-l") + 1] == "3" and "-x" not in look
    assert not (tmp_path / "designs" / "paper-assets").exists()                          # looking saves nothing

    ran.clear()
    out = asyncio.run(_exec_design({"action": "extract", "path": "attachments/paper.pdf", "page": 3, "area": [0.1, 0.2, 0.5, 0.25]}, _ws(tmp_path)))
    cut = next(a for a in ran if a[0] == "pdftoppm")
    opt = lambda k: cut[cut.index(k) + 1]
    # Letter at 200 to the inch is 1700 × 2200 px.
    assert (opt("-r"), opt("-x"), opt("-y"), opt("-W"), opt("-H")) == ("200", "170", "440", "850", "550")
    assert (tmp_path / "designs" / "paper-assets" / "figure-1.png").read_bytes() == _png(850, 550)
    m = out["_model"]
    assert m[0]["type"] == "image" and "designs/paper-assets/figure-1.png (850×550)" in m[-1]["text"]
    assert '"image": "designs/paper-assets/figure-1.png"' in m[-1]["text"]
    # The next one is its own file; what is wrong with the request is said.
    asyncio.run(_exec_design({"action": "extract", "path": "attachments/paper.pdf", "page": 3, "area": [0, 0.5, 1, 0.3]}, _ws(tmp_path)))
    assert (tmp_path / "designs" / "paper-assets" / "figure-2.png").is_file()
    run = lambda **kw: asyncio.run(_exec_design({"action": "extract", "path": "attachments/paper.pdf", **kw}, _ws(tmp_path)))
    assert "12 pages" in run(page=13) and "from 1" in run(page=0)
    assert "[left, top, width, height]" in run(page=3, area=[0.5, 0.5, 0.8, 0.2])           # runs off the page
    assert "[left, top, width, height]" in run(page=3, area="top half")


# ---- a document edited by hand is not laid out again over those edits without a word ----

def _outlines(monkeypatch, by_fig):
    """`design.outline` faked: each saved .fig's pages, by its bytes."""
    asked = []

    async def outline(fig, user_id=None, page=None, full=False):
        asked.append((bytes(fig), full))
        return {"frames": by_fig[bytes(fig)], "pages": [], "page": ""}
    monkeypatch.setattr("cycls._agent.design.outline", outline)
    return asked


def _page(*nodes):
    return {"slide": 1, "name": "page-2", "size": [1240, 1754], "nodes": [dict(n) for n in nodes]}


_LEAD = {"name": "lead-1", "type": "text", "x": 124, "y": 300, "w": 992, "h": 80, "text": "Demand grew 18%.", "font": "Inter", "size": 28, "color": "#111111"}
_RULE = {"name": "rule", "type": "rect", "x": 124, "y": 280, "w": 96, "h": 5, "fill": "#b45309"}


def test_a_document_edited_by_hand_is_not_rendered_over_until_the_edits_are_accounted_for(tmp_path, monkeypatch):
    from cycls._agent import versions
    from cycls._agent.design.store import version_of
    ws = _ws(tmp_path)
    _saved_document(tmp_path, monkeypatch)                                   # rendered: FIG-ONE
    d = tmp_path / "designs"
    deck = json.loads((d / "report.deck.json").read_text(encoding="utf-8"))
    assert deck["rendered"] == version_of(b"FIG-ONE")                         # what its pages were, as rendered
    # The person rewords the lead and moves a rule in the editor: the .fig is saved, the source knows nothing of it.
    (d / "report.fig").write_bytes(b"FIG-BY-HAND")
    asked = _outlines(monkeypatch, {
        b"FIG-ONE": [_page(), _page(_LEAD, _RULE)],                        # the cover, then page 2
        b"FIG-BY-HAND": [_page(), _page({**_LEAD, "text": "Demand grew 21% — a record year.", "h": 120}, {**_RULE, "y": 320},
                                        {"name": "sticker", "type": "rect", "x": 900, "y": 200, "w": 80, "h": 80, "fill": "#ff0000"})]})
    calls = _doc_render(monkeypatch, pages=4, fig=b"FIG-TWO")
    run = lambda extra: asyncio.run(_exec_design({"action": "update_section", "name": "report", "number": 3,
                                                  "section": {"blocks": ["Rewritten."]}, **extra}, ws))
    out = run({})
    assert isinstance(out, str) and out.startswith("Error: not rendered")
    assert 'page 2: "lead-1" now reads "Demand grew 21% — a record year." (was "Demand grew 18%.")' in out
    assert '"rule" moved, resized or restyled' in out and "1 node added" in out
    assert '"discard_edits": true' in out and "History" in out
    assert all(full for _, full in asked)                                    # compared word for word, not by the first lines
    # Nothing happened: not rendered, not saved, the hand-edited pages still there.
    assert "renders" not in calls and (d / "report.fig").read_bytes() == b"FIG-BY-HAND"
    assert _source(tmp_path)["sections"][2]["blocks"] == ["Short."]

    # Once they are accounted for, it renders — and the hand-edited pages are kept as a version.
    out = run({"discard_edits": True})
    assert "Document re-rendered" in out["_model"][-1]["text"] and "kept in History" in out["_model"][-1]["text"]
    assert (d / "report.fig").read_bytes() == b"FIG-TWO"
    kept = versions.listing(tmp_path, "designs/report.fig")
    assert versions.read(tmp_path, "designs/report.fig", kept[0]["id"]) == b"FIG-BY-HAND"
    assert json.loads((d / "report.deck.json").read_text(encoding="utf-8"))["rendered"] == version_of(b"FIG-TWO")
    # …and the next change, with no edits since, needs no such word.
    assert "Document re-rendered" in run({})["_model"][-1]["text"]


def test_the_whole_render_again_is_held_the_same_way_and_a_resave_with_no_change_is_not_an_edit(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    doc = _saved_document(tmp_path, monkeypatch)
    d = tmp_path / "designs"
    (d / "report.fig").write_bytes(b"FIG-BY-HAND")
    _outlines(monkeypatch, {b"FIG-ONE": [_page(_LEAD)], b"FIG-BY-HAND": [_page({**_LEAD, "text": "Demand grew 21%."})]})
    calls = _doc_render(monkeypatch, fig=b"FIG-TWO")
    out = asyncio.run(_exec_design({"action": "render", "name": "report", "replace": True, "spec": {"document": doc}}, ws))
    assert isinstance(out, str) and out.startswith("Error: not rendered") and "renders" not in calls
    # A new name is a new document: nothing of the old one is at stake.
    assert not isinstance(asyncio.run(_exec_design({"action": "render", "name": "report", "spec": {"document": doc}}, ws)), str)
    assert (d / "report-2.pdf").is_file() and (d / "report.fig").read_bytes() == b"FIG-BY-HAND"
    # The editor saved the file again without changing a thing (the bytes differ, the pages don't): not an edit.
    (d / "report.fig").write_bytes(b"FIG-RESAVED")
    _outlines(monkeypatch, {b"FIG-ONE": [_page(_LEAD)], b"FIG-RESAVED": [_page(dict(_LEAD))]})
    out = asyncio.run(_exec_design({"action": "render", "name": "report", "replace": True, "spec": {"document": doc}}, ws))
    assert not isinstance(out, str) and "Document re-rendered" in out["_model"][-1]["text"]


def test_when_what_changed_cannot_be_told_the_hold_still_asks(tmp_path, monkeypatch):
    import shutil
    ws = _ws(tmp_path)
    _saved_document(tmp_path, monkeypatch)
    d = tmp_path / "designs"
    (d / "report.fig").write_bytes(b"FIG-BY-HAND")
    shutil.rmtree(tmp_path / ".cache", ignore_errors=True)                    # the pages as rendered are no longer kept
    calls = _doc_render(monkeypatch, fig=b"FIG-TWO")
    out = asyncio.run(_exec_design({"action": "delete_section", "name": "report", "number": 3}, ws))
    assert isinstance(out, str) and out.startswith("Error: not rendered") and "changed after it was last rendered" in out
    assert "renders" not in calls
    # A document rendered before any of this was kept has nothing to compare with: it renders as it always did.
    deck = json.loads((d / "report.deck.json").read_text(encoding="utf-8"))
    deck.pop("rendered")
    (d / "report.deck.json").write_text(json.dumps(deck), encoding="utf-8")
    out = asyncio.run(_exec_design({"action": "delete_section", "name": "report", "number": 3}, ws))
    assert not isinstance(out, str) and "Document re-rendered" in out["_model"][-1]["text"]


def test_a_long_texts_change_is_shown_where_it_is():
    from cycls._agent.tools import _page_changes
    long = "Specialty coffee kept growing through the year, though not evenly. " * 8
    page = lambda text: [{"nodes": []}, {"nodes": [{"name": "p-1", "type": "text", "x": 0, "y": 0, "w": 700, "h": 300, "text": text}]}]
    said = _page_changes(page(long + "It ends with these last words."), page(long + "It ends with different words now."))
    assert len(said) == 1 and said[0].startswith('page 2: "p-1" now reads "…')
    assert "It ends with different words now." in said[0] and "It ends with these last words." in said[0]   # the part that changed, both ways
    assert len(said[0]) < 800                                                # not the whole paragraph twice
    # A short text is shown whole.
    short = _page_changes(page("Demand grew 18%."), page("Demand grew 21%."))
    assert short == ['page 2: "p-1" now reads "Demand grew 21%." (was "Demand grew 18%.")']


# ---- together: an agent's change to a design people have open at once ----
#
# The people in a design keep one shared document in step (the live relay), and one of
# their editors saves it. So an agent's edit must reach that document once: the tool
# writes the file as always, then hands the edit to the room (`live.notify`) — the
# saver's editor makes it for everyone — and tells the chat's own editor not to make it
# again (`live: true` on the event). A change that writes the file anew is told to the
# room as "open it again".

def _fake_room(monkeypatch, peers=2):
    from cycls._agent.design import live
    said = []

    async def notify(root, rel, body):
        said.append((rel, body))
        if not peers:
            return {"ok": True, "peers": 0, "delivered": 0}
        return {"ok": True, "peers": peers, "delivered": 1 if body["kind"] == "command" else peers}
    monkeypatch.setattr(live, "notify", notify)
    return said


def test_an_edit_to_a_design_people_have_open_together_is_handed_to_their_room(tmp_path, monkeypatch):
    from cycls._agent.design.store import version_of
    _design(tmp_path)
    _fake_apply(monkeypatch, compiled="COMPILED")
    said = _fake_room(monkeypatch)
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": [{"op": "set_text", "node": "headline", "text": "Hi"}],
                                    "intent": "retitle"}, _ws(tmp_path)))
    assert said == [("designs/launch.fig", {"kind": "command", "script": "COMPILED", "intent": "retitle",
                                            "version": version_of(b"EDITED-FIG")})]
    assert out["_ui"]["live"] is True                 # the chat's own editor leaves it to the room
    assert out["_ui"]["version"] == version_of(b"EDITED-FIG")


def test_an_edit_to_a_design_nobody_has_open_together_is_replayed_as_before(tmp_path, monkeypatch):
    _design(tmp_path)
    _fake_apply(monkeypatch, compiled="COMPILED")
    said = _fake_room(monkeypatch, peers=0)
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "script": "S"}, _ws(tmp_path)))
    assert len(said) == 1 and "live" not in out["_ui"]
    # …and with no relay at all the answer is None: nothing changes either.
    from cycls._agent.design import live

    async def nothing(root, rel, body):
        return None
    monkeypatch.setattr(live, "notify", nothing)
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "script": "S"}, _ws(tmp_path)))
    assert "live" not in out["_ui"]


def test_an_edit_that_changes_the_pages_tells_the_room_to_open_the_file_again(tmp_path, monkeypatch):
    from cycls._agent.design.store import version_of
    _design(tmp_path)
    _fake_apply(monkeypatch, compiled="COMPILED", pages=[{"name": "Post"}, {"name": "Story"}], page="Story", started="Post")
    said = _fake_room(monkeypatch)
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch",
                                    "ops": [{"op": "page_duplicate", "name": "Story"}]}, _ws(tmp_path)))
    assert said == [("designs/launch.fig", {"kind": "reload", "version": version_of(b"EDITED-FIG")})]
    assert out["_ui"]["reload"] is True and out["_ui"]["live"] is True


def test_a_slide_added_to_a_deck_people_have_open_together_is_handed_to_their_room(tmp_path, monkeypatch):
    from cycls._agent.design.store import version_of
    _deck(tmp_path)
    _fake_apply(monkeypatch, result=b"NEW-FIG", compiled="S", touched=[1], previews=[b"JPEG"],
                slides=[{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}])
    said = _fake_room(monkeypatch)
    out = asyncio.run(_exec_design({"action": "add_slide", "name": "pitch", "at": 2,
                                    "slide": {"layout": "bullets", "title": "Farms", "bullets": ["Direct"]},
                                    "intent": "add the farms slide"}, _ws(tmp_path)))
    assert said == [("designs/pitch.fig", {"kind": "command", "script": "S", "intent": "add the farms slide",
                                           "version": version_of(b"NEW-FIG")})]
    command = out["_ui"][0]
    assert command["action"] == "design_command" and command["live"] is True


def test_a_document_rendered_again_tells_the_room_to_open_the_file_again(tmp_path, monkeypatch):
    from cycls._agent.design.store import version_of
    _fake_render(monkeypatch, image=b"%PDF-1", fig=b"FIG-ONE", slides=[b"a"])
    spec = {"document": {"title": "Plan", "sections": [{"title": "One", "blocks": [{"p": "Text."}]}]}}
    asyncio.run(_exec_design({"action": "render", "name": "plan", "spec": spec}, _ws(tmp_path)))
    said = _fake_room(monkeypatch)
    _fake_render(monkeypatch, image=b"%PDF-2", fig=b"FIG-TWO", slides=[b"a"])
    out = asyncio.run(_exec_design({"action": "render", "name": "plan", "spec": spec, "replace": True}, _ws(tmp_path)))
    assert said == [("designs/plan.fig", {"kind": "reload", "version": version_of(b"FIG-TWO")})]
    command = out["_ui"][0]
    assert command["action"] == "design_command" and command["reload"] is True and command["live"] is True


def test_waking_a_relay_that_is_not_there_is_not_an_error(monkeypatch):
    from cycls._agent.design import live
    monkeypatch.setenv("DESIGN_LIVE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("DESIGN_LIVE_SECRET", "s3cret")
    assert asyncio.run(live.wake()) is None
    monkeypatch.delenv("DESIGN_LIVE_URL")
    assert asyncio.run(live.wake()) is None                   # nothing set up: nothing rung


# ---- shapes a model sent that were refused, and looks it was not given (production, Sep–Oct 2026) ----

def test_a_slide_whose_layout_had_no_room_for_everything_says_so(tmp_path, monkeypatch):
    # Six figures given to a "stats" slide, four drawn: said with the slide, not found out by the audience.
    _deck(tmp_path, {"theme": "editorial", "size": [1920, 1080]})
    left = "the slide (stats): 6 figures were given and the layout holds 4 — the last 2 were left out. Put them on a slide of their own."
    _fake_apply(monkeypatch, result=b"NEW-FIG", compiled="S", touched=[1], previews=[b"J"], slides=[{}, {}], notes=[left])
    out = asyncio.run(_exec_design({"action": "add_slide", "name": "pitch", "slide": {
        "layout": "stats", "title": "Numbers", "items": [{"value": f"{n}0%", "label": "x"} for n in range(6)]}}, _ws(tmp_path)))
    assert left in out["_model"][-1]["text"]


def test_an_edit_of_a_deck_or_a_carousel_shows_the_slides_it_changed(tmp_path, monkeypatch):
    # The look that came back with an edit was the first slide, whichever one it had changed.
    _design(tmp_path)
    ops = [{"op": "set_text", "node": "x", "text": "y", "frame": 2}]
    _fake_apply(monkeypatch, compiled="/*c*/", preview=b"FIRST", previews=[b"S3", b"S5"], touched=[2, 4], slides=[{}] * 6)
    m = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": ops}, _ws(tmp_path)))["_model"]
    assert [b["text"] for b in m if b["type"] == "text"][:2] == ["Slide 3:", "Slide 5:"]
    assert [base64.b64decode(b["source"]["data"]) for b in m if b["type"] == "image"] == [b"S3", b"S5"]
    assert "The slides it changed are attached" in m[-1]["text"]
    # One frame, or the first of several: as before, one picture with nothing before it.
    for touched, slides in (([0], [{}]), ([], [])):
        _fake_apply(monkeypatch, compiled="/*c*/", preview=b"ONE", previews=[b"ONE"], touched=touched, slides=slides)
        m = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": ops}, _ws(tmp_path)))["_model"]
        assert [b["type"] for b in m] == ["image", "text"] and "The edited design is attached" in m[-1]["text"]


_DESCRIBED = "modern Riyadh skyline at dusk, glass towers, deep blue tones"


def test_a_picture_described_where_a_file_goes_is_found_as_a_stock_photo(tmp_path, monkeypatch):
    # `src` — and a slide's `image` — held a description of the picture wanted: three failed
    # calls in one chat, and the slide was made without its picture.
    calls = _fake_stock(monkeypatch)
    render = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "city", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "src": _DESCRIBED, "x": 0, "y": 0, "w": 1080, "h": 720}]}}, _ws(tmp_path)))
    assert calls["search"] == [("modern Riyadh skyline at dusk", "landscape")]   # what a photo search can find
    assert render["spec"]["nodes"][0]["image"]
    text = _text(out)
    assert not text.startswith("Error")
    assert "is not a file in the workspace" in text and "stock photo" in text and "Photo by Ana on Pexels" in text
    # A deck slide's image, the same.
    _fake_render(monkeypatch, image=b"PPTX", previews=[b"J1", b"J2"])
    out = asyncio.run(_exec_design({"action": "render", "name": "pitch", "format": "pptx", "spec": {"deck": {"slides": [
        {"layout": "image-right", "title": "Riyadh", "image": "a quiet street in old Jeddah"},
        {"layout": "closing", "title": "Thanks"}]}}}, _ws(tmp_path)))
    assert not _text(out).startswith("Error") and calls["search"][-1][0] == "a quiet street in old Jeddah"
    # An edit that swaps a photo, too.
    _design(tmp_path)
    apply = _fake_apply(monkeypatch, compiled="/*c*/")[0]
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "ops": [
        {"op": "replace_image", "node": "photo", "src": "coffee beans on a wooden table"}]}, _ws(tmp_path)))
    assert not _text(out).startswith("Error") and apply["ops"][0]["image"]
    # A file that is named and isn't there is still an error.
    out = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "src": "attachments/riyadh skyline.jpg", "x": 0, "y": 0, "w": 100, "h": 100}]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "does not exist in the workspace" in out


def test_a_described_picture_where_no_photos_can_be_found_says_what_src_is(tmp_path, monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "city", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "image", "src": _DESCRIBED, "x": 0, "y": 0, "w": 1080, "h": 720}]}}, _ws(tmp_path)))
    assert out.startswith("Error") and "describes a picture" in out and "save a photo into the workspace" in out


def test_a_spec_that_closes_with_the_wrong_brackets_is_read_as_what_it_plainly_is(tmp_path, monkeypatch):
    # 5,064 characters of a document written right, and one bracket wrong in the last
    # four: refused, and all of it was written out again.
    good = {"size": [1080, 1080], "nodes": [{"type": "text", "text": 'A "quoted" } word', "x": 10, "y": 10},
                                           {"type": "stack", "x": 10, "y": 90, "children": [{"type": "text", "text": "In"}]}]}
    text = json.dumps(good)
    assert text.endswith("}]}]}")
    for broken in (text[:-1] + "]}", text + "}", text[:-2], text[:-1] + "}}]}", text[:-3] + "}\n"):
        calls = _fake_render(monkeypatch)
        out = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": broken}, _ws(tmp_path)))
        assert not _text(out).startswith("Error"), broken[-12:]
        assert calls["spec"]["nodes"][0]["text"] == 'A "quoted" } word' and calls["spec"]["nodes"][1]["children"][0]["text"] == "In"
        assert "closing brackets" in _text(out)                              # said, so the next one is written right
    # Wrong anywhere else — or cut off inside its content — it is refused, with where, as before.
    calls = _fake_render(monkeypatch)
    for broken in (text[:30] + '"' + text[30:], text[:-9], text[: text.index("In") + 1]):
        out = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": broken}, _ws(tmp_path)))
        assert out.startswith("Error") and "isn't valid JSON" in out, broken[-12:]
    assert "renders" not in calls
    # Wrapped in a code fence: the object inside it.
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": f"```json\n{text}\n```"}, _ws(tmp_path)))
    assert not _text(out).startswith("Error") and calls["spec"]["nodes"][0]["text"] == 'A "quoted" } word'


def test_a_design_sent_beside_the_action_is_its_spec_and_nothing_sent_is_said_so(tmp_path, monkeypatch):
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "x", "size": [1080, 1080], "fill": "#ffffff",
                                    "nodes": [{"type": "text", "text": "Hi", "x": 1, "y": 1}]}, _ws(tmp_path)))
    assert not _text(out).startswith("Error")
    assert calls["spec"]["nodes"][0]["text"] == "Hi" and calls["spec"]["size"] == [1080, 1080]
    calls = _fake_render(monkeypatch, image=b"PPTX", previews=[b"J1"])
    out = asyncio.run(_exec_design({"action": "render", "name": "d", "format": "pptx",
                                    "deck": {"slides": [{"layout": "title", "title": "Brewly"}]}}, _ws(tmp_path)))
    assert not _text(out).startswith("Error") and "deck" in calls["spec"]
    # Nothing that could be a design: the error says what did come, not only what is wanted.
    none = asyncio.run(_exec_design({"action": "render", "name": "x", "format": "png"}, _ws(tmp_path)))
    assert none.startswith("Error") and "`render` needs a `spec`" in none and "this call has: action, name, format" in none
    words = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": "a poster about coffee"}, _ws(tmp_path)))
    assert words.startswith("Error") and "`spec` came as text" in words and "a poster about coffee" in words
    listed = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": [{"type": "text", "text": "Hi"}]}, _ws(tmp_path)))
    assert listed.startswith("Error") and "`spec` came as a list" in listed


def test_a_gradient_written_as_a_node_is_a_glow_over_the_frame(tmp_path, monkeypatch):
    # {"type": "radial", "center": …, "gradient": […]} among the nodes: a fill, written
    # where a node goes. Refused as an unknown type; it plainly meant a glow.
    calls = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": {"size": [1080, 1080], "fill": "#0b0b0b", "nodes": [
        {"type": "radial", "center": [0.5, 0.42], "radius": 0.55, "gradient": ["#ffd98a99", "#f2a13c00"]},
        {"type": "text", "text": "Hi", "x": 10, "y": 10}]}}, _ws(tmp_path)))
    assert not _text(out).startswith("Error")
    n = calls["spec"]["nodes"][0]
    assert n["type"] == "rect" and (n["x"], n["y"], n["w"], n["h"]) == (0, 0, 1080, 1080)
    assert n["fill"] == {"gradient": ["#ffd98a99", "#f2a13c00"], "type": "radial", "center": [0.5, 0.42], "radius": 0.55}
    assert "a gradient is a fill" in _text(out)
    # A type that is nothing: refused, as before.
    bad = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": {"size": [1080, 1080], "nodes": [{"type": "sparkle"}]}}, _ws(tmp_path)))
    assert bad.startswith("Error") and "type 'sparkle'" in bad


def test_a_lists_items_are_read_however_they_are_written(tmp_path, monkeypatch):
    for given in ("First point\nSecond point", [{"text": "First point"}, {"text": "Second point"}],
                  ["- First point", "• Second point"]):
        calls = _fake_render(monkeypatch)
        out = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": {"size": [1080, 1080], "nodes": [
            {"type": "list", "items": given, "x": 40, "y": 40, "w": 600}]}}, _ws(tmp_path)))
        assert not _text(out).startswith("Error"), given
        assert calls["spec"]["nodes"][0]["items"] == ["First point", "Second point"], given
    calls = _fake_render(monkeypatch)                                         # its own `text`, when `items` is missing
    asyncio.run(_exec_design({"action": "render", "name": "x", "spec": {"size": [1080, 1080], "nodes": [
        {"type": "list", "text": "One\nTwo", "x": 40, "y": 40}]}}, _ws(tmp_path)))
    assert calls["spec"]["nodes"][0]["items"] == ["One", "Two"]
    none = asyncio.run(_exec_design({"action": "render", "name": "x", "spec": {"size": [1080, 1080], "nodes": [{"type": "list", "x": 1, "y": 1}]}}, _ws(tmp_path)))
    assert none.startswith("Error") and "a list needs `items`" in none


# ---- a saved design as another file; a design as a file ----

def _fake_export(monkeypatch, data=b"EXPORTED", images=(), pages=(), page=""):
    """`design.export` / `export_page` faked: records what was asked."""
    calls = []

    async def _export(fig, fmt="png", scale=2, width=None, user_id=None, every=False, page=None):
        calls.append({"fig": fig, "fmt": fmt, "scale": scale, "every": every, "page": page})
        return list(images) if every else data

    async def _export_page(fig, page_, fmt="png", scale=2, width=None, user_id=None):
        calls.append({"fig": fig, "fmt": fmt, "scale": scale, "page": page_})
        return data, list(pages), page
    monkeypatch.setattr("cycls._agent.design.export", _export)
    monkeypatch.setattr("cycls._agent.design.export_page", _export_page)
    return calls


def test_export_makes_another_file_of_a_saved_design_and_renders_nothing(tmp_path, monkeypatch):
    # "Send me this as a PDF": with no way to ask for that, the model rendered the design
    # again from the spec it remembered — a second design (launch-2), without anything
    # the person had changed by hand since.
    _design(tmp_path)
    calls = _fake_export(monkeypatch, data=b"%PDF-1")
    render = _fake_render(monkeypatch)
    out = asyncio.run(_exec_design({"action": "export", "name": "launch", "format": "pdf"}, _ws(tmp_path)))
    assert (tmp_path / "designs" / "launch.pdf").read_bytes() == b"%PDF-1"
    assert calls == [{"fig": b"ORIGINAL-FIG", "fmt": "pdf", "scale": 2, "every": False, "page": None}]
    assert "renders" not in render and sorted(f.name for f in (tmp_path / "designs").iterdir()) == ["launch.fig", "launch.pdf"]
    assert "Exported designs/launch.pdf" in _text(out) and "as it is now" in _text(out)
    assert out["_ui"] == {"type": "ui", "action": "open_canvas", "path": "designs/launch.pdf", "name": "launch.pdf"}
    # What it needs, said.
    assert "needs `format`" in asyncio.run(_exec_design({"action": "export", "name": "launch"}, _ws(tmp_path)))
    missing = asyncio.run(_exec_design({"action": "export", "name": "nope", "format": "pdf"}, _ws(tmp_path)))
    assert missing.startswith("Error") and "doesn't exist" in missing and "launch" in missing    # …and what there is


def test_export_of_a_deck_is_one_file_or_an_image_a_slide_and_of_a_page_that_page(tmp_path, monkeypatch):
    d = _deck(tmp_path, slides=3)
    calls = _fake_export(monkeypatch, data=b"PK-pptx", images=[b"S1", b"S2", b"S3"])
    out = asyncio.run(_exec_design({"action": "export", "name": "pitch", "format": "pdf"}, _ws(tmp_path)))
    assert (d / "pitch.pdf").read_bytes() == b"PK-pptx" and calls[-1]["every"] is False
    out = asyncio.run(_exec_design({"action": "export", "name": "pitch", "format": "jpg", "scale": 1}, _ws(tmp_path)))
    assert calls[-1] == {"fig": b"DECK-FIG", "fmt": "jpg", "scale": 1, "every": True, "page": None}
    assert [(d / f"pitch-slide-{n}.jpg").read_bytes() for n in (1, 2, 3)] == [b"S1", b"S2", b"S3"]
    assert "3 images" in _text(out) and "designs/pitch-slide-1.jpg" in _text(out) and "designs/pitch-slide-3.jpg" in _text(out)
    # One page of a design of several pages: that page's own file.
    _design(tmp_path)
    calls = _fake_export(monkeypatch, data=b"STORY", pages=_PAGES, page="Story")
    out = asyncio.run(_exec_design({"action": "export", "name": "launch", "format": "png", "page": "story"}, _ws(tmp_path)))
    assert calls[-1]["page"] == "story" and (tmp_path / "designs" / "launch-page-2.png").read_bytes() == b"STORY"
    assert 'page "Story"' in _text(out)


def test_a_design_is_renamed_with_what_is_kept_beside_it(tmp_path, monkeypatch):
    d = _deck(tmp_path)
    (d / "pitch.pptx").write_bytes(b"PPTX")
    (d / "pitch-slide-1.png").write_bytes(b"S1")
    out = asyncio.run(_exec_design({"action": "rename", "name": "pitch", "new_name": "seed-deck.fig"}, _ws(tmp_path)))
    assert sorted(f.name for f in d.iterdir()) == ["seed-deck-slide-1.png", "seed-deck.deck.json", "seed-deck.fig", "seed-deck.pptx"]
    doc = json.loads((d / "seed-deck.deck.json").read_text())
    assert doc["fig"] == "designs/seed-deck.fig" and doc["exports"] == ["designs/seed-deck.pptx"]
    assert "designs/seed-deck.fig" in _text(out)
    assert out["_ui"]["path"] == "designs/seed-deck.deck.json"               # the deck is opened where it is now
    # Never over a design that is there; and it says what it needs.
    _design(tmp_path)
    taken = asyncio.run(_exec_design({"action": "rename", "name": "launch", "new_name": "seed-deck"}, _ws(tmp_path)))
    assert taken.startswith("Error") and "already" in taken and (d / "launch.fig").is_file()
    assert "needs `new_name`" in asyncio.run(_exec_design({"action": "rename", "name": "launch"}, _ws(tmp_path)))


def test_a_design_is_copied_to_change_freely(tmp_path, monkeypatch):
    d = _deck(tmp_path)
    (d / "pitch.pptx").write_bytes(b"PPTX")
    scheduled = []
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda root, rel, user_id=None, ensure=False, pages=False: scheduled.append((rel, ensure)))
    out = asyncio.run(_exec_design({"action": "duplicate", "name": "pitch"}, _ws(tmp_path)))
    assert (d / "pitch-copy.fig").read_bytes() == b"DECK-FIG" and (d / "pitch.fig").is_file()
    assert (d / "pitch-copy.pptx").read_bytes() == b"PPTX"
    assert json.loads((d / "pitch-copy.deck.json").read_text())["fig"] == "designs/pitch-copy.fig"
    assert json.loads((d / "pitch.deck.json").read_text())["fig"] == "designs/pitch.fig"       # the original is as it was
    assert scheduled == [("designs/pitch-copy.fig", True)] and "designs/pitch-copy.fig" in _text(out)
    # A name of its own when asked; never over one that is there.
    asyncio.run(_exec_design({"action": "duplicate", "name": "pitch", "new_name": "pitch-ar"}, _ws(tmp_path)))
    asyncio.run(_exec_design({"action": "duplicate", "name": "pitch", "new_name": "pitch-ar"}, _ws(tmp_path)))
    assert (d / "pitch-ar.fig").is_file() and (d / "pitch-ar-2.fig").is_file()


def test_a_design_is_deleted_to_the_trash_with_what_is_kept_beside_it(tmp_path, monkeypatch):
    from cycls._agent import trash
    d = _deck(tmp_path)
    (d / "pitch.pptx").write_bytes(b"PPTX")
    _design(tmp_path)                                                        # another design, untouched
    out = asyncio.run(_exec_design({"action": "delete", "name": "pitch"}, _ws(tmp_path)))
    assert sorted(f.name for f in d.iterdir()) == ["launch.fig"]
    gone = sorted(e["path"] for e in trash.list_trash(str(tmp_path)))
    assert gone == ["designs/pitch.deck.json", "designs/pitch.fig", "designs/pitch.pptx"]
    assert "trash" in out and "restore" in out.lower()


def test_a_designs_earlier_versions_are_listed_and_one_is_gone_back_to(tmp_path, monkeypatch):
    from cycls._agent import versions
    from cycls._agent.design.store import version_of
    _design(tmp_path, data=b"NOW")
    one = versions.snapshot(str(tmp_path), "designs/launch.fig", b"FIRST", by="agent", reason="agent", intent="making the headline gold", always=True)
    two = versions.snapshot(str(tmp_path), "designs/launch.fig", b"SECOND", by="user", reason="save", always=True)
    listing = asyncio.run(_exec_design({"action": "versions", "name": "launch"}, _ws(tmp_path)))
    ids = [v["id"] for v in versions.listing(str(tmp_path), "designs/launch.fig")]
    assert len(ids) == 2 and all(i in listing for i in ids)
    assert "making the headline gold" in listing and listing.index(ids[0]) < listing.index(ids[1])   # newest first, as listed
    scheduled, told = [], []
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda root, rel, user_id=None, ensure=False, pages=False: scheduled.append(rel))

    async def _notify(root, rel, body):
        told.append((rel, body))
    monkeypatch.setattr("cycls._agent.design.live.notify", _notify)
    oldest = ids[-1]
    out = asyncio.run(_exec_design({"action": "restore", "name": "launch", "version": oldest}, _ws(tmp_path)))
    assert (tmp_path / "designs" / "launch.fig").read_bytes() == b"FIRST"
    assert b"NOW" in [versions.read(str(tmp_path), "designs/launch.fig", v["id"]) for v in versions.listing(str(tmp_path), "designs/launch.fig")]   # what it was is kept
    assert scheduled == ["designs/launch.fig"]
    assert told == [("designs/launch.fig", {"kind": "reload", "version": version_of(b"FIRST")})]     # people in it open it again
    assert out["_ui"]["action"] == "design_command" and out["_ui"]["reload"] is True and out["_ui"]["version"] == version_of(b"FIRST")
    assert "Restored" in _text(out)
    # By its place too (1 = the newest); and one that isn't there is said, with those that are.
    asyncio.run(_exec_design({"action": "restore", "name": "launch", "version": 1}, _ws(tmp_path)))
    assert (tmp_path / "designs" / "launch.fig").read_bytes() == b"NOW"
    bad = asyncio.run(_exec_design({"action": "restore", "name": "launch", "version": "nope"}, _ws(tmp_path)))
    assert bad.startswith("Error") and "versions" in bad
    none = asyncio.run(_exec_design({"action": "versions", "name": "launch2"}, _ws(tmp_path)))
    assert none.startswith("Error") and "doesn't exist" in none


def test_the_tool_says_export_is_for_another_format_and_names_the_file_actions():
    from cycls._agent.tools import _DESIGN_TOOL, design_tool
    for action in ("export", "rename", "duplicate", "delete", "versions", "restore"):
        assert action in _DESIGN_TOOL["input_schema"]["properties"]["action"]["enum"]
        assert action in design_tool(False)["input_schema"]["properties"]["action"]["description"]
    assert "- export {name, format" in _DESIGN_TOOL["description"] and "NOT render" in _DESIGN_TOOL["description"]
    assert {"new_name", "version"} <= set(_DESIGN_TOOL["input_schema"]["properties"])


def test_the_tool_says_what_a_document_can_be_asked_for():
    """Three columns, a list of figures and the PDF's own details are built in the service;
    the model only asks for what it is told of."""
    from cycls._agent.tools import _DESIGN_TOOL
    text = _DESIGN_TOOL["description"]
    assert '"columns"?: 1|2|3' in text and "3 for a dense bulletin" in text
    assert '"figures": true lists them' in text
    assert '"lang"' in text and "Arabic is known without" in text


def test_the_design_tool_lives_in_its_package_and_is_still_reached_through_tools(monkeypatch):
    """The Design tool was two thirds of tools/__init__.py. It is in cycls/_agent/design now —
    what the model is given, what it wrote made ready, what the tool does — and everything
    that took a Design name from `cycls._agent.tools` still gets the very same object."""
    from cycls._agent import paths, tools
    from cycls._agent.design import actions, brand, extract, files, images, prepare, report, run, tool
    homes = {"_DESIGN_TOOL": tool, "design_tool": tool, "design_wanted": tool, "DESIGN_LOADED": tool,
             "_norm_hex": brand, "_load_brand": brand, "_brand_palette": brand,
             "_image_size": images, "_place_image": images, "_DESIGN_QA_MAX": images,
             "_prepare_spec": prepare, "_prepare_deck": prepare, "_prepare_document": prepare, "_prepare_slide": prepare,
             "_prepare_ops": prepare, "_mend_json_tail": prepare, "_DESIGN_SIZES": prepare,
             "_pdf_parts": extract, "_run_tool": extract,
             "_outline_text": report, "_layout_check": report, "_page_changes": report,
             "_dedupe_design_name": files, "_save_pages": files,
             "_exec_slides": actions, "_exec_document": actions, "_exec_design_file": actions, "_render_document": actions,
             "_exec_design": run, "_design_step": run}
    for name, home in homes.items():
        assert getattr(tools, name) is getattr(home, name), name
        if callable(getattr(home, name)) and hasattr(getattr(home, name), "__module__"):
            assert getattr(home, name).__module__ == home.__name__, name      # defined there, not passed through
    # The tool is registered from where it lives…
    assert tools._TOOLS["design"].step is run._design_step
    monkeypatch.setenv("DESIGN_URL", "https://cycls-design.cycls.ai")
    assert any(t is tool._DESIGN_TOOL for t in tools.build_tools(["Design"], []))
    # …and what a tool was given as a path is in a module of its own, which both use.
    assert tools._resolve_path is paths._resolve_path and tools._safe_filename is paths._safe_filename
    assert paths._resolve_path.__module__ == "cycls._agent.paths"

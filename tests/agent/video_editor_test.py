"""The video editor (cycls/_agent/video/editor.py, web/video_routes.py): a session opened on the service
with what the video names, the files it may write back saved against their versions, an older video's
upgrade kept as a version, the selection it sends to chat, a render it asks for, and the agent's edit
that meets a save from the editor."""
import asyncio
import json
import types
from types import SimpleNamespace

import httpx
import pytest

from cycls._agent import versions
from cycls._agent.design.store import version_of
from cycls._agent.video import editor
from cycls._agent.video import run as vrun
from cycls._agent.video.tool import VIDEO_LOADED

COMP = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="root" data-composition-id="main" data-no-timeline data-start="0" data-duration="6" data-width="1080" data-height="1920">
<section id="s1" class="clip" data-start="0" data-duration="6" data-track-index="2"><h1 id="t">Hi</h1><img src="../brand/logo.png"></section>
<audio id="vo" src="videos/voice/intro.m4a" data-start="0"></audio>
<div class="cap" data-captions="vo"></div>
</div><script>at("#t", [{ opacity: 0 }, { opacity: 1 }], 200, 600);</script></body></html>
"""
WORDS = {"version": 1, "duration": 1.0, "text": "Hello.", "words": [{"text": "Hello.", "start": 0.1, "end": 0.6}]}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda *a, **k: None)
    versions._last.clear()
    editor._renders.clear()


def _on(monkeypatch, editor_url="https://editor.test"):
    monkeypatch.setenv("VIDEO_URL", "https://video.test/")
    monkeypatch.setenv("VIDEO_SECRET", "k" * 40)
    monkeypatch.setenv("VIDEO_ORGS", "org_1")
    if editor_url:
        monkeypatch.setenv("VIDEO_EDITOR_URL", editor_url)


def _client(tmp_path):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from cycls._app.auth import User
    from cycls._agent.web.routers import install_routers

    user = User(id="user_1", org_id="org_1")
    stub = SimpleNamespace(prod=False, _auth_provider=None, config=SimpleNamespace(workspaces="member", max_upload=512))
    app = FastAPI()
    install_routers(stub, app, Depends(lambda: user), tmp_path, f"file://{tmp_path}")
    return TestClient(app), tmp_path / "org_1" / "ws" / "u-user_1"


def _video(root, html=COMP):
    (root / "videos" / "voice").mkdir(parents=True, exist_ok=True)
    (root / "brand").mkdir(parents=True, exist_ok=True)
    (root / "videos" / "launch.video.html").write_bytes(html.encode("utf-8"))
    (root / "brand" / "logo.png").write_bytes(b"\x89PNG fake")
    (root / "videos" / "voice" / "intro.m4a").write_bytes(b"not really audio")
    (root / "videos" / "voice" / "intro.words.json").write_bytes(json.dumps(WORDS).encode("utf-8"))


class FakeEditor:
    """The service's editor: what the SDK sent, and what it answers."""

    def __init__(self, monkeypatch, *, upgraded=None, status=200):
        self.calls, self.upgraded, self.status = [], upgraded, status
        real = httpx.AsyncClient

        def transport(request):
            self.calls.append(request)
            if request.method == "POST" and request.url.path == "/v1/sessions":
                if self.status != 200:
                    return httpx.Response(self.status, json={"error": "nope"})
                html = self.upgraded or json.loads(_meta(request))["html"]
                return httpx.Response(200, json={"sid": "a" * 32, "url": "/s/" + "a" * 32 + "/", "html": html,
                                                 "upgraded": bool(self.upgraded), "notice": None})
            if request.method == "PUT":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(200, json={"ok": True})

        monkeypatch.setattr(editor.httpx, "AsyncClient",
                            lambda **kw: real(transport=httpx.MockTransport(transport), **kw))


def _meta(request):
    body = request.read().decode("latin-1")
    start = body.index('name="meta"')
    chunk = body[start:].split("\r\n\r\n", 1)[1]
    return chunk.split("\r\n--", 1)[0]


# ---- the routes ----------------------------------------------------------------------------------

def test_a_video_and_its_words_are_saved_against_their_versions(tmp_path):
    client, root = _client(tmp_path)
    _video(root)
    got = client.get("/files/videos/launch.video.html")
    assert got.headers["x-version"] == version_of(COMP.encode()) and got.headers["content-type"].startswith("text/html")
    edited = COMP.replace("Hi", "Hello").encode()
    ok = client.put(f"/files/videos/launch.video.html?base={got.headers['x-version']}", content=edited)
    assert ok.status_code == 200 and ok.json()["version"] == version_of(edited)
    stale = client.put(f"/files/videos/launch.video.html?base={got.headers['x-version']}", content=b"<html>x</html>")
    assert stale.status_code == 412 and stale.json()["detail"] == "This video changed since it was opened."
    assert versions.listing(root, "videos/launch.video.html")[0]["by"] == "user"
    big = client.put("/files/videos/launch.video.html", content=b"x" * 400_001)
    assert big.status_code == 413
    words = client.get("/files/videos/voice/intro.words.json")
    assert words.headers["x-version"] == version_of((root / "videos/voice/intro.words.json").read_bytes())
    fixed = json.dumps({**WORDS, "words": [{"text": "Hi.", "start": 0.1, "end": 0.6}]}).encode()
    assert client.put(f"/files/videos/voice/intro.words.json?base={words.headers['x-version']}", content=fixed).status_code == 200
    assert client.put(f"/files/videos/voice/intro.words.json?base={words.headers['x-version']}", content=b"{}").status_code == 412


def test_the_editor_is_offered_only_where_video_is(monkeypatch, tmp_path):
    client, root = _client(tmp_path)
    _video(root)
    assert client.post("/video/editor?path=videos/launch.video.html").status_code == 503      # not configured
    _on(monkeypatch, editor_url=None)
    assert client.post("/video/editor?path=videos/launch.video.html").status_code == 503      # no editor URL
    _on(monkeypatch)
    monkeypatch.setenv("VIDEO_ORGS", "someone-else")
    assert client.post("/video/editor?path=videos/launch.video.html").status_code == 503      # not this organisation
    assert client.post("/video/editor?path=designs/a.fig").status_code == 400
    assert client.post("/video/editor?path=videos/none.video.html").status_code == 404


def test_a_session_carries_what_the_video_names_and_the_versions_it_may_write(monkeypatch, tmp_path):
    client, root = _client(tmp_path)
    _video(root)
    (root / "videos" / "other.video.html").write_text('<audio src="videos/voice/intro.m4a">', encoding="utf-8")
    _on(monkeypatch)
    fake = FakeEditor(monkeypatch)
    r = client.post("/video/editor?path=videos/launch.video.html", headers={"Origin": "https://app.cycls.test"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == "https://editor.test/s/" + "a" * 32 + "/" and body["sid"] == "a" * 32
    assert body["versions"] == {"videos/launch.video.html": version_of(COMP.encode()),
                                "videos/voice/intro.words.json": version_of((root / "videos/voice/intro.words.json").read_bytes())}
    sent = fake.calls[0]
    assert sent.headers["x-video-key"] == "k" * 40 and sent.headers["x-video-tenant"] and "x-video-proto" not in sent.headers
    meta = json.loads(_meta(sent))
    assert meta["path"] == "videos/launch.video.html" and meta["host_origin"] == "https://app.cycls.test"
    assert set(meta["images"]) == {"../brand/logo.png"} and set(meta["audio"]) == {"videos/voice/intro.m4a"}
    w = meta["words"]["videos/voice/intro.words.json"]
    assert w["media"] == "videos/voice/intro.m4a" and w["json"]["text"] == "Hello." and w["shared"] is True


def test_an_older_video_is_upgraded_and_the_upgrade_kept_as_a_version(monkeypatch, tmp_path):
    client, root = _client(tmp_path)
    _video(root)
    _on(monkeypatch)
    upgraded = COMP.replace('data-track-index="2"', 'data-track-index="2" data-upgraded')
    FakeEditor(monkeypatch, upgraded=upgraded)
    body = client.post("/video/editor?path=videos/launch.video.html").json()
    assert (root / "videos/launch.video.html").read_text(encoding="utf-8") == upgraded
    assert body["versions"]["videos/launch.video.html"] == version_of(upgraded.encode())
    [kept] = versions.listing(root, "videos/launch.video.html")
    assert kept["reason"] == "upgrade" and versions.read(root, "videos/launch.video.html", kept["id"]) == COMP.encode()


def test_the_editor_refusing_a_video_says_why(monkeypatch, tmp_path):
    client, root = _client(tmp_path)
    _video(root)
    _on(monkeypatch)
    FakeEditor(monkeypatch, status=413)
    r = client.post("/video/editor?path=videos/launch.video.html")
    assert r.status_code == 422 and r.json()["detail"] == "nope"


def test_the_page_is_told_the_editor_is_there(monkeypatch):
    from cycls._agent.web.server import Config

    assert "video_editor" not in Config().public()
    _on(monkeypatch)
    assert Config().public()["video_editor"] is True


# ---- the selection -------------------------------------------------------------------------------

def test_a_selection_in_a_video_reaches_the_model_with_its_time():
    from cycls._agent.harness.main import _with_selection
    from cycls._agent.web.server import _clean_selection

    sel = _clean_selection({"path": "videos/launch.video.html", "time": 4.23, "frame": None,
                            "nodes": [{"name": "t", "type": "h1", "text": "Hi"}]})
    assert sel == {"path": "videos/launch.video.html", "frame": None, "nodes": [{"name": "t", "type": "h1", "text": "Hi"}],
                   "time": 4.2}
    assert _with_selection("bigger", sel)[-1]["text"] == '[Selected in videos/launch.video.html at 4.2 s: t (h1) "Hi"]'
    assert _clean_selection({"path": "../x.video.html", "nodes": [{"name": "a", "type": "b"}]}) is None
    assert "time" not in _clean_selection({"path": "designs/a.fig", "time": 3, "nodes": [{"name": "a", "type": "b"}]})


# ---- the agent's edit meets a save from the editor ------------------------------------------------

def _text(out):
    """What the model reads of a reply: its text (a reply with a sheet carries image blocks first)."""
    model = out["_model"] if isinstance(out, dict) else out
    return model if isinstance(model, str) else model[-1]["text"]


def _run(inp, root, chat="chat-1"):
    ws = types.SimpleNamespace(root=root, subject="org_1:user_1", ws=None)
    return asyncio.run(vrun._exec_video(inp, ws, types.SimpleNamespace(chat_id=chat)))


def test_an_edit_after_a_save_from_the_editor_says_to_read_the_file_again(monkeypatch, tmp_path):
    from tests.agent.video_test import FakeService

    _on(monkeypatch)
    FakeService(monkeypatch)
    VIDEO_LOADED.set(True)
    _run({"action": "write", "name": "launch", "html": COMP}, tmp_path)
    from cycls._agent.design.store import write_fig
    asyncio.run(write_fig(tmp_path, "videos/launch.video.html", COMP.replace("<h1 id=\"t\">", "<h1 class=\"x\" id=\"t\">").encode(),
                          by="user", reason="save"))
    out = _run({"action": "edit", "name": "launch", "changes": [{"old": '<h1 id="t">Hi', "new": '<h1 id="t">Hey'}]}, tmp_path)
    assert "read the file again" in out
    ok = _run({"action": "edit", "name": "launch", "changes": [{"old": ">Hi<", "new": ">Hey<"}]}, tmp_path)
    assert _text(ok).startswith("Edited") and ok["_ui"][-1]["version"] == version_of(
        (tmp_path / "videos/launch.video.html").read_bytes())


def test_an_edit_that_meets_a_save_reads_and_applies_once_more(monkeypatch, tmp_path):
    from tests.agent.video_test import FakeService

    _on(monkeypatch)
    FakeService(monkeypatch)
    VIDEO_LOADED.set(True)
    _run({"action": "write", "name": "launch", "html": COMP}, tmp_path)
    real = vrun.write_fig
    raced = []

    async def racing(root, rel, data, **kw):
        if not raced:            # the person saves from the editor between the agent's read and write
            raced.append(True)
            await real(root, rel, COMP.replace("6", "7", 1).encode(), by="user", reason="save")
        return await real(root, rel, data, **kw)

    monkeypatch.setattr(vrun, "write_fig", racing)
    out = _run({"action": "edit", "name": "launch", "changes": [{"old": ">Hi<", "new": ">Hey<"}]}, tmp_path)
    assert _text(out).startswith("Edited")
    text = (tmp_path / "videos/launch.video.html").read_text(encoding="utf-8")
    assert ">Hey<" in text and text.count("7") >= 1          # both the person's save and the agent's edit


# ---- a render the editor asks for ----------------------------------------------------------------

def test_a_render_from_the_editor_lands_beside_the_video(monkeypatch, tmp_path):
    from cycls._agent import video

    client, root = _client(tmp_path)
    _video(root)
    (root / "videos" / "launch.mp4").write_bytes(b"OLD")
    (root / "videos" / "launch.ar.srt").write_text("1\n00:00:00,100 --> 00:00:00,900\nold\n", encoding="utf-8")
    _on(monkeypatch)
    calls = []
    sound = {"tracks": [{"id": "vo", "kind": "voice", "src": "videos/voice/intro.m4a", "start": 0, "end": 1.0, "media_start": 0}]}

    async def submit(ws, kind, html, images=None, files=None, **kw):
        calls.append((kind, kw.get("params")))
        return {"token": "tok", "eta_s": 30, "sound": sound}

    async def poll(ws, token, wait=25):
        return {"state": "done"}

    async def fetch(ws, token, dest, scratch, what="video"):
        dest.write_bytes(b"NEW MP4")
        return 7

    monkeypatch.setattr(video, "submit", submit)
    monkeypatch.setattr(video, "poll", poll)
    monkeypatch.setattr(video, "fetch", fetch)
    client.__enter__()          # one event loop for the whole test: the render runs in it after the request
    started = client.post("/video/render?path=videos/launch.video.html&quality=standard")
    assert started.status_code == 200 and started.json()["state"] in ("rendering", "done")
    for _ in range(50):
        state = client.get("/video/render?path=videos/launch.video.html").json()
        if state["state"] != "rendering":
            break
        asyncio.run(asyncio.sleep(0.02))
    assert state == {**state, "state": "done", "path": "videos/launch.mp4"}
    # The editor asks for "standard"; the service is asked for "final" (it renders final or draft).
    assert (root / "videos" / "launch.mp4").read_bytes() == b"NEW MP4" and calls == [("render", {"quality": "final"})]
    # Its subtitle files are made again for the new cut; a translation of the old one goes to the trash.
    assert "Hello." in (root / "videos" / "launch.srt").read_text(encoding="utf-8")
    assert not (root / "videos" / "launch.ar.srt").exists() and list((root / ".trash").glob("*/data/videos/launch.ar.srt"))
    from cycls._agent.video import files as vfiles
    assert vfiles.load_sound(root, "launch") == sound
    assert client.post("/video/render?path=videos/launch.video.html&quality=huge").status_code == 400
    client.__exit__(None, None, None)

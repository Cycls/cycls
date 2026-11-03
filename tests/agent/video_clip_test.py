"""A clip the person sent, made into a video they edit by hand (cycls/_agent/video/clip.py): Edit on an
MP4 in the canvas (GET/POST /video/clip, web/video_routes.py) and the Video tool's `editor` action. The
service is faked at the client's functions: what it holds, what was sent, what was asked."""
import asyncio
import hashlib
import json
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from cycls._agent import versions, video
from cycls._agent.video import clip, editor, files
from cycls._agent.video import run as vrun

SAID = {"version": 1, "kind": "footage", "language": "en", "duration": 40.0, "text": "We opened in March.",
        "sentences": [{"i": 0, "start": 12.4, "end": 14.0, "text": "We opened in March."}],
        "words": [{"text": "We", "start": 12.4, "end": 12.6}, {"text": "opened", "start": 12.65, "end": 13.1},
                  {"text": "in", "start": 13.15, "end": 13.3}, {"text": "March.", "start": 13.35, "end": 14.0}]}
INFO = {"duration": 40.0, "width": 1920, "height": 1080, "fps": 30, "has_audio": True, "lufs": -19.2,
        "shots": [[0, 40.0]], "transcript": SAID}
CLIP = "attachments/1a2b3c4d-interview.mp4"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("VIDEO_URL", "VIDEO_SECRET", "VIDEO_ORGS", "VIDEO_EDITOR_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda *a, **k: None)
    versions._last.clear()


def _on(monkeypatch, org="org1"):
    monkeypatch.setenv("VIDEO_URL", "https://video.test/")
    monkeypatch.setenv("VIDEO_SECRET", "k" * 40)
    monkeypatch.setenv("VIDEO_ORGS", org)
    monkeypatch.setenv("VIDEO_EDITOR_URL", "https://editor.test")


class FakeDoor:
    """The service's clip routes: what it holds, what was sent, what was asked, how the read ends."""

    def __init__(self, monkeypatch, state="none", info=INFO):
        self.state, self.info, self.sent, self.ingests, self.waits = state, info, [], [], []
        self.whole, self.result, self.refuse = True, None, None
        monkeypatch.setattr(video, "clip_state", self.clip_state)
        monkeypatch.setattr(video, "send_clip", self.send_clip)
        monkeypatch.setattr(video, "ingest", self.ingest)
        monkeypatch.setattr(video, "wait", self.wait)

    async def clip_state(self, ws, sha, *, sheet=False):
        if self.state == "ready":
            return {"state": "ready", "info": self.info}
        return {"state": self.state, "at": 0}

    async def send_clip(self, ws, path, sha, *, at=0, budget=240):
        if self.refuse:
            raise video.Refused(self.refuse, [])
        self.sent.append({"sha": sha, "at": at, "budget": budget})
        size = Path(path).stat().st_size
        return (size, True) if self.whole else (size // 2, False)

    async def ingest(self, ws, sha, *, language=None, key=None):
        self.ingests.append({"sha": sha, "key": key})
        return {"token": f"i{len(self.ingests)}", "eta_s": 30}

    async def wait(self, ws, token, budget):
        self.waits.append(token)
        r = self.result or {"state": "done", "info": self.info}
        if r.get("state") == "done":
            self.state = "ready"
        return r


def _clip(root, rel=CLIP, data=b"\x00\x00\x00\x18ftypmp42" + b"clip" * 200):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _ws(root, subject="org1:user1"):
    return types.SimpleNamespace(root=root, subject=subject, ws=None)


def _open(root, rel=CLIP):
    steps = []

    async def progress(step):
        steps.append(step)

    out = asyncio.run(clip.open_clip(_ws(root), root, rel, progress=progress))
    return out, steps


# ---- the clip's own video ----------------------------------------------------------------------------

def test_the_format_follows_the_clips_shape():
    assert clip.shape_for(1920, 1080) == ("wide", 1920, 1080)
    assert clip.shape_for(1440, 1080) == ("wide", 1920, 1080)          # 4:3 filmed sideways stays wide
    assert clip.shape_for(1080, 1080) == ("square", 1080, 1080)
    assert clip.shape_for(1080, 1350) == ("portrait", 1080, 1350)
    assert clip.shape_for(1080, 1440) == ("portrait", 1080, 1350)       # 3:4
    assert clip.shape_for(1080, 1920) == ("vertical", 1080, 1920)
    assert clip.shape_for(None, None)[0] == "wide"


def test_a_clip_becomes_a_video_of_itself_once(monkeypatch, tmp_path):
    _on(monkeypatch)
    door = FakeDoor(monkeypatch)
    sha = _clip(tmp_path)
    out, steps = _open(tmp_path)
    assert out == {"state": "ready", "path": "videos/interview.video.html", "made": True}    # the chat's id taken off
    assert [s["state"] for s in steps][:2] == ["sending", "sending"] and steps[-1]["state"] == "reading"
    assert door.sent[0]["sha"] == sha and len(door.ingests) == 1
    html = (tmp_path / "videos" / "interview.video.html").read_text(encoding="utf-8")
    assert 'data-width="1920" data-height="1080"' in html and '<meta name="viewport" content="width=1920, height=1080">' in html
    assert f'<video id="clip" src="{CLIP}" data-start="0" data-media-start="0" data-duration="40"' in html
    assert 'data-duration="40" data-width' in html and "object-fit: contain" in html and '<html lang="en">' in html
    assert versions.listing(tmp_path, "videos/interview.video.html") == []          # a new file: no earlier version
    said = json.loads((tmp_path / "attachments" / "1a2b3c4d-interview.words.json").read_text(encoding="utf-8"))
    assert said["sha"] == sha and said["clip"] == CLIP                               # what is said, beside the clip
    # Changed by hand, then Edit again: the same video, nothing sent or read again, nothing written over.
    (tmp_path / "videos" / "interview.video.html").write_text(html.replace('data-media-start="0"', 'data-media-start="2"'),
                                                              encoding="utf-8")
    again, steps = _open(tmp_path)
    assert again == {"state": "ready", "path": "videos/interview.video.html", "made": False} and steps == []
    assert len(door.sent) == 1 and len(door.ingests) == 1
    assert 'data-media-start="2"' in (tmp_path / "videos" / "interview.video.html").read_text(encoding="utf-8")


def test_a_long_clip_holds_its_first_90_seconds_and_a_short_one_is_refused(monkeypatch, tmp_path):
    _on(monkeypatch)
    door = FakeDoor(monkeypatch, state="ready", info={**INFO, "duration": 250.437, "width": 1080, "height": 1920,
                                                       "transcript": {**SAID, "language": "ar"}})
    _clip(tmp_path, "uploads/long.mov")
    out, _ = _open(tmp_path, "uploads/long.mov")
    assert out["path"] == "videos/long.video.html" and "first 90 s" in out["notice"] and "4:10" in out["notice"]
    html = (tmp_path / "videos" / "long.video.html").read_text(encoding="utf-8")
    assert 'data-duration="90"' in html and 'data-width="1080" data-height="1920"' in html and '<html lang="ar">' in html
    door.info = {**INFO, "duration": 2.4}
    _clip(tmp_path, "uploads/blink.mp4")
    with pytest.raises(clip.NotReady, match="at least 3 seconds"):
        _open(tmp_path, "uploads/blink.mp4")
    assert not (tmp_path / "videos" / "blink.video.html").exists()


def test_a_rendered_video_opens_what_it_was_rendered_from_and_names_never_clash(monkeypatch, tmp_path):
    _on(monkeypatch)
    door = FakeDoor(monkeypatch, state="ready")
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "launch.video.html").write_text("<html></html>", encoding="utf-8")
    for rel in ("videos/launch.mp4", "videos/launch.vertical.mp4"):
        _clip(tmp_path, rel)
        out, _ = _open(tmp_path, rel)
        assert out == {"state": "ready", "path": "videos/launch.video.html", "made": False}
    assert door.sent == [] and door.ingests == []
    # A clip that is itself videos/<name>.mp4 with no video beside it, and a name a video already has.
    _clip(tmp_path, "videos/raw.mp4")
    assert _open(tmp_path, "videos/raw.mp4")[0]["path"] == "videos/raw-2.video.html"
    _clip(tmp_path, "uploads/launch.mp4")
    assert _open(tmp_path, "uploads/launch.mp4")[0]["path"] == "videos/launch-2.video.html"
    assert (tmp_path / "videos" / "launch.video.html").read_text(encoding="utf-8") == "<html></html>"


def test_what_the_service_refuses_is_said(monkeypatch, tmp_path):
    _on(monkeypatch)
    door = FakeDoor(monkeypatch)
    _clip(tmp_path)
    door.refuse = "That file is not a video."
    with pytest.raises(clip.NotReady, match="the clip was not taken: That file is not a video"):
        _open(tmp_path)
    door.refuse, door.result = None, {"state": "failed", "error": "no picture a video can use"}
    with pytest.raises(clip.NotReady, match="could not be made ready: no picture"):
        _open(tmp_path)


# ---- the agent's `editor` ------------------------------------------------------------------------------

def _run(inp, root, chat="chat-1"):
    return asyncio.run(vrun._exec_video(inp, _ws(root), types.SimpleNamespace(chat_id=chat)))


def test_the_agent_opens_a_clip_in_the_editor(monkeypatch, tmp_path):
    _on(monkeypatch)
    door = FakeDoor(monkeypatch)
    _clip(tmp_path)
    out = _run({"action": "editor", "path": CLIP}, tmp_path)
    assert out["_ui"] == [{"type": "ui", "action": "open_canvas", "path": "videos/interview.video.html",
                           "name": "interview.video.html", "edit": True}]
    assert out["_model"].startswith("Made videos/interview.video.html: the clip alone")
    assert "open in the editor" in out["_model"] and "We opened in March." in out["_model"]   # what the clip is
    assert files.mine(tmp_path, "chat-1", "interview")                       # this chat's, to change when asked
    assert door.sent[0]["budget"] == vrun.BUDGET["send"]                      # within the call's budget
    again = _run({"action": "editor", "path": CLIP}, tmp_path, chat="chat-2")
    assert again["_model"].startswith("videos/interview.video.html is the video made from this clip before")
    assert _run({"action": "editor", "name": "interview"}, tmp_path)["_ui"][0]["edit"] is True
    assert _run({"action": "editor", "name": "nope"}, tmp_path).startswith("Error: there is no videos/nope.video.html")
    assert _run({"action": "editor"}, tmp_path).startswith("Error: editor needs path")
    assert "not a file in the workspace" in _run({"action": "editor", "path": "uploads/none.mp4"}, tmp_path)


def test_a_long_upload_from_the_agent_is_gone_on_with(monkeypatch, tmp_path):
    _on(monkeypatch)
    door = FakeDoor(monkeypatch)
    _clip(tmp_path)
    door.whole = False
    out = _run({"action": "editor", "path": CLIP}, tmp_path)
    assert out.startswith(f"Still sending {CLIP}") and "Call editor again" in out and door.ingests == []
    door.whole, door.result = True, {"state": "pending", "eta_s": 45}
    out = _run({"action": "editor", "path": CLIP}, tmp_path)
    assert out.startswith(f"Still reading {CLIP} (about 45 s more") and "Call editor again" in out
    door.result = None
    out = _run({"action": "editor", "path": CLIP}, tmp_path)
    assert len(door.ingests) == 1 and door.waits == ["i1", "i1"]               # collected, not read twice
    assert out["_ui"][0]["path"] == "videos/interview.video.html"


# ---- the routes ----------------------------------------------------------------------------------------

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


def _lines(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_edit_is_offered_on_a_clip_only_where_video_is(monkeypatch, tmp_path):
    client, root = _client(tmp_path)
    _clip(root)
    assert client.get(f"/video/clip?path={CLIP}").json() == {"editor": False, "video": None}     # not configured
    _on(monkeypatch, org="someone-else")
    assert client.get(f"/video/clip?path={CLIP}").json() == {"editor": False, "video": None}     # not this organisation
    assert client.post(f"/video/clip?path={CLIP}").status_code == 503
    _on(monkeypatch, org="org_1")
    assert client.get(f"/video/clip?path={CLIP}").json() == {"editor": True, "video": None}
    assert client.get("/video/clip?path=notes/readme.txt").status_code == 400
    assert client.get("/video/clip?path=uploads/none.mp4").status_code == 404


def test_edit_on_a_clip_streams_its_steps_and_ends_with_its_video(monkeypatch, tmp_path):
    client, root = _client(tmp_path)
    _on(monkeypatch, org="org_1")
    door = FakeDoor(monkeypatch)
    _clip(root)
    resp = client.post(f"/video/clip?path={CLIP}")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("application/x-ndjson")
    steps = _lines(resp)
    assert steps[0]["state"] == "sending" and steps[0]["size"] > 0 and any(s["state"] == "reading" for s in steps)
    assert steps[-1] == {"state": "ready", "path": "videos/interview.video.html", "made": True}
    assert (root / "videos" / "interview.video.html").is_file()
    assert versions.listing(root, "videos/interview.video.html") == []
    assert client.get(f"/video/clip?path={CLIP}").json() == {"editor": True, "video": "videos/interview.video.html"}
    # What cannot be made ready ends the stream with why, said as a sentence.
    _clip(root, "uploads/odd.mp4", b"odd bytes" * 50)
    door.state, door.refuse = "none", "That file is not a video."
    assert _lines(client.post("/video/clip?path=uploads/odd.mp4"))[-1] == {
        "state": "failed", "message": "The clip was not taken: That file is not a video."}

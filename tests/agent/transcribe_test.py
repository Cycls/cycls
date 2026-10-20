"""The Transcribe tool and the microphone on the cycls-transcribe service: the client, the executor
(files written beside the recording, a saved transcript kept, a long job collected later), the hint
on an attached recording, and the /transcribe route with its OpenAI fallback. Pure logic: no service
is contacted (httpx is mocked, or the client's functions are)."""
import asyncio
import hashlib
import importlib.resources
import json
import types

import httpx
import pytest

from cycls._agent import transcribe
from cycls._agent.harness.main import _ingest
from cycls._agent.tools import _TOOLS, build_tools
from cycls._agent.transcribe import client
from cycls._agent.transcribe import run as trun

THEME_PATH = str(importlib.resources.files("cycls").joinpath("_agent/web/themes/dev"))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("TRANSCRIBE_URL", "TRANSCRIBE_SECRET", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def _on(monkeypatch):
    monkeypatch.setenv("TRANSCRIBE_URL", "https://transcribe.test/")
    monkeypatch.setenv("TRANSCRIBE_SECRET", "k" * 40)


def _ws(tmp_path, subject="org1:user1"):
    return types.SimpleNamespace(root=tmp_path, subject=subject, ws=None)


def _said(text="مرحبا بكم. اليوم نتكلم عن الميزانية.", lang="ar", start=0.5):
    words, t = [], start
    for w in text.split():
        words.append({"text": w, "start": round(t, 2), "end": round(t + 0.4, 2), "score": 0.9})
        t += 0.5
    return {"version": 1, "kind": "audio", "language": lang, "duration": round(t + 1, 2), "text": text,
            "sentences": [{"i": 0, "start": words[0]["start"], "end": words[-1]["end"], "text": text}],
            "words": words, "engine": {"asr": "CohereLabs/cohere-transcribe-arabic-07-2026@c3e911b42149"}}


# ---- offered -----------------------------------------------------------------------------------

def test_offered_only_when_the_service_is_configured(monkeypatch):
    assert [t["name"] for t in build_tools(["Transcribe"], None)] == []
    _on(monkeypatch)
    tools = build_tools(["Transcribe", "Bash"], None)
    assert [t["name"] for t in tools] == ["transcribe", "bash"]
    schema = tools[0]["input_schema"]
    assert schema["required"] == ["path"] and set(schema["properties"]["language"]["enum"]) == {"auto", "ar", "en"}
    assert _TOOLS["transcribe"].step({"path": "notes/call.m4a"}) == {"tool_name": "Transcribing", "step": "notes/call.m4a"}


# ---- the client over a mocked door -------------------------------------------------------------

_REAL_CLIENT = httpx.AsyncClient


def _transport(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(client.httpx, "AsyncClient",
                        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(wrapped), **kw))
    monkeypatch.setattr(client, "_RETRY_WAITS", (0, 0))
    return seen


def test_headers_carry_the_key_and_hashes_never_the_names(monkeypatch, tmp_path):
    _on(monkeypatch)
    seen = _transport(monkeypatch, lambda r: httpx.Response(200, json={"state": "none", "at": 0}))
    asyncio.run(transcribe.state(_ws(tmp_path), "a" * 64))
    h = seen[0].headers
    assert h["x-transcribe-key"] == "k" * 40 and h["x-transcribe-proto"] == str(client.PROTO)
    assert h["x-transcribe-tenant"] == hashlib.sha256(b"tenant:org1").hexdigest()[:32]
    assert h["x-transcribe-user"] == hashlib.sha256(b"user:org1:user1").hexdigest()[:32]
    assert "org1" not in json.dumps(dict(h)) and str(seen[0].url) == "https://transcribe.test/v1/assets/" + "a" * 64


def test_the_mics_person_is_named_as_a_workspace_would_be():
    assert client.subject_of(None) == "local"
    assert client.subject_of(types.SimpleNamespace(id="u1", org_id="o1")) == "o1:u1"
    assert client.subject_of(types.SimpleNamespace(id="u1", org_id=None)) == "u1"


def test_refusals_are_told_apart(monkeypatch, tmp_path):
    _on(monkeypatch)
    answers = {"status": 401, "body": {"error": "unauthorised"}}
    _transport(monkeypatch, lambda r: httpx.Response(answers["status"], json=answers["body"]))
    with pytest.raises(transcribe.Unavailable, match="refused the key"):
        asyncio.run(transcribe.short(b"x", subject="o:u"))
    answers.update(status=429, body={"error": "You have transcribed today's allowance"})
    with pytest.raises(transcribe.OverAllowance, match="allowance"):
        asyncio.run(transcribe.short(b"x", subject="o:u"))
    answers.update(status=504, body={"error": "too slow", "busy": True})
    with pytest.raises(transcribe.Busy):
        asyncio.run(transcribe.short(b"x", subject="o:u"))
    answers.update(status=422, body={"error": "not audio", "refused": "unreadable"})
    with pytest.raises(transcribe.Refused) as e:
        asyncio.run(transcribe.short(b"x", subject="o:u"))
    assert e.value.code == "unreadable"
    answers.update(status=503, body={"error": "paused for maintenance", "paused": True})
    with pytest.raises(transcribe.Unavailable, match="maintenance"):
        asyncio.run(transcribe.short(b"x", subject="o:u"))
    answers.update(status=302, body={})
    with pytest.raises(transcribe.Unavailable, match="redirect"):
        asyncio.run(transcribe.state(_ws(tmp_path), "a" * 64))


def test_only_calls_safe_to_repeat_are_tried_again(monkeypatch, tmp_path):
    _on(monkeypatch)
    seen = _transport(monkeypatch, lambda r: httpx.Response(502, text="bad gateway"))
    with pytest.raises(transcribe.Unavailable):
        asyncio.run(transcribe.state(_ws(tmp_path), "a" * 64))
    assert len(seen) == 3
    seen.clear()
    with pytest.raises(transcribe.Unavailable):
        asyncio.run(transcribe.short(b"x", subject="o:u"))        # a short recording heard twice costs twice
    assert len(seen) == 1
    seen.clear()
    with pytest.raises(transcribe.Unavailable):
        asyncio.run(transcribe.start(_ws(tmp_path), "a" * 64, key="k1"))   # a job with a key is safe
    assert len(seen) == 3


def test_a_recording_is_sent_in_pieces_and_resumed_where_the_door_is(monkeypatch, tmp_path):
    _on(monkeypatch)
    monkeypatch.setattr(client, "_PIECE", 4)
    data = b"0123456789"
    rec = tmp_path / "a.m4a"
    rec.write_bytes(data)
    got = bytearray()
    first = {"gap": True}

    def door(r):
        offset = int(r.url.params["offset"])
        if first.pop("gap", False):
            return httpx.Response(409, json={"error": "does not follow", "at": 0})
        assert offset == len(got)
        got.extend(r.content)
        done = r.url.params["last"] == "1"
        return httpx.Response(200, json={"state": "uploaded" if done else "partial", "at": len(got)})

    _transport(monkeypatch, door)
    at, whole = asyncio.run(transcribe.send(_ws(tmp_path), rec, "s" * 64, at=4))
    assert (at, whole) == (10, True) and bytes(got) == data


# ---- the executor ------------------------------------------------------------------------------

class FakeService:
    """The client's functions, as the executor calls them."""

    def __init__(self, monkeypatch, transcript=None, pending=0, gone=0):
        self.transcript = transcript if transcript is not None else _said()
        self.pending, self.gone = pending, gone
        self.sent, self.started, self.waited = [], [], []
        self.have = set()
        for name in ("state", "send", "start", "wait"):
            monkeypatch.setattr(transcribe, name, getattr(self, name))

    async def state(self, ws, sha):
        return {"state": "uploaded" if sha in self.have else "none", "at": 0}

    async def send(self, ws, path, sha, *, at=0, budget=240):
        self.sent.append(sha)
        self.have.add(sha)
        return path.stat().st_size, True

    async def start(self, ws, sha, *, language="auto", key=None):
        self.started.append((sha, language, key))
        return {"token": f"t{len(self.started)}", "eta_s": 30}

    async def wait(self, ws, token, budget):
        self.waited.append(token)
        if self.pending:
            self.pending -= 1
            return {"state": "pending"}
        if self.gone:
            self.gone -= 1
            return {"state": "gone", "error": "restarted"}
        return {"state": "done", "transcript": self.transcript}


def _run(inp, ws, chat="c1"):
    return asyncio.run(trun.exec_transcribe(inp, ws, types.SimpleNamespace(chat_id=chat)))


def test_a_recording_is_transcribed_and_kept_beside_it(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch)
    (tmp_path / "calls").mkdir()
    (tmp_path / "calls" / "client.m4a").write_bytes(b"audio" * 100)
    out = _run({"path": "calls/client.m4a"}, _ws(tmp_path))
    assert out.startswith("Transcript of calls/client.m4a (00:", ) and "Arabic" in out and "Cohere Transcribe Arabic" in out
    assert "[00:00] مرحبا بكم. اليوم نتكلم عن الميزانية." in out and "calls/client.transcript.md" in out
    md = (tmp_path / "calls" / "client.transcript.md").read_text(encoding="utf-8")
    assert md.startswith("# Transcript: client.m4a") and "[00:00] مرحبا بكم." in md
    words = json.loads((tmp_path / "calls" / "client.words.json").read_text(encoding="utf-8"))
    sha = hashlib.sha256(b"audio" * 100).hexdigest()
    assert words["sha"] == sha and words["clip"] == "calls/client.m4a" and words["words"][0]["text"] == "مرحبا"
    assert svc.sent == [sha] and svc.started[0][:2] == (sha, "auto")
    # Asked again: the saved transcript, no service call.
    again = _run({"path": "calls/client.m4a"}, _ws(tmp_path))
    assert "saved earlier" in again and len(svc.started) == 1
    # A word corrected by hand in the words file is kept; `fresh` asks the service again.
    words["words"][0]["text"] = "أهلاً"
    (tmp_path / "calls" / "client.words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "calls" / "client.transcript.md").unlink()
    _run({"path": "calls/client.m4a"}, _ws(tmp_path))
    assert "أهلاً" in json.dumps(json.loads((tmp_path / "calls" / "client.words.json").read_text(encoding="utf-8")),
                                ensure_ascii=False)
    assert (tmp_path / "calls" / "client.transcript.md").is_file() and len(svc.started) == 1
    _run({"path": "calls/client.m4a", "fresh": True, "language": "ar"}, _ws(tmp_path))
    assert len(svc.started) == 2 and svc.started[1][1] == "ar"


def test_new_bytes_under_the_same_name_are_heard_again(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch)
    rec = tmp_path / "memo.mp3"
    rec.write_bytes(b"one")
    _run({"path": "memo.mp3"}, _ws(tmp_path))
    rec.write_bytes(b"two two")
    _run({"path": "memo.mp3"}, _ws(tmp_path))
    assert len(svc.started) == 2


def test_a_long_recording_is_collected_on_a_later_call(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch, pending=1)
    (tmp_path / "meeting.wav").write_bytes(b"x" * 1000)
    first = _run({"path": "meeting.wav"}, _ws(tmp_path))
    assert first.startswith("Still transcribing meeting.wav") and not (tmp_path / "meeting.transcript.md").exists()
    second = _run({"path": "meeting.wav"}, _ws(tmp_path))
    assert second.startswith("Transcript of meeting.wav") and len(svc.started) == 1 and svc.waited == ["t1", "t1"]
    # Another chat starts its own job.
    _run({"path": "meeting.wav", "fresh": True}, _ws(tmp_path), chat="c2")
    assert len(svc.started) == 2


def test_a_job_lost_to_a_restart_is_started_once_more(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch, gone=1)
    (tmp_path / "a.ogg").write_bytes(b"x" * 10)
    out = _run({"path": "a.ogg"}, _ws(tmp_path))
    assert out.startswith("Transcript of a.ogg") and len(svc.started) == 2
    svc2 = FakeService(monkeypatch, gone=2)
    out = _run({"path": "a.ogg", "fresh": True}, _ws(tmp_path))
    assert out.startswith("Error:") and "restarted" in out and len(svc2.started) == 2


def test_silence_says_nobody_speaks(monkeypatch, tmp_path):
    _on(monkeypatch)
    FakeService(monkeypatch, transcript={"version": 1, "kind": "audio", "language": None, "duration": 12.0,
                                         "text": "", "sentences": [], "words": [], "note": "Nobody is heard"})
    (tmp_path / "room.wav").write_bytes(b"x")
    out = _run({"path": "room.wav"}, _ws(tmp_path))
    assert out.startswith("Nobody is heard speaking in room.wav (00:12)")
    assert "Nobody is heard" in (tmp_path / "room.transcript.md").read_text(encoding="utf-8")


def test_a_long_transcript_is_given_in_part_with_where_the_rest_is(monkeypatch, tmp_path):
    _on(monkeypatch)
    words = [{"text": f"word{i}", "start": i * 0.5, "end": i * 0.5 + 0.4, "score": 0.9} for i in range(8000)]
    sentences = [{"i": k, "start": words[k * 10]["start"], "end": words[k * 10 + 9]["end"],
                  "text": " ".join(w["text"] for w in words[k * 10:k * 10 + 10]) + "."} for k in range(800)]
    FakeService(monkeypatch, transcript={"version": 1, "kind": "audio", "language": "en", "duration": 4000.0,
                                         "text": "…", "sentences": sentences, "words": words,
                                         "engine": {"asr": "openai/whisper-large-v3-turbo@41f01f3fe87f"},
                                         "unheard": [[600.0, 640.0]]})
    (tmp_path / "lecture.mp3").write_bytes(b"x")
    out = _run({"path": "lecture.mp3"}, _ws(tmp_path))
    assert len(out) < trun.REPLY_CHARS + 2000 and "the rest is in lecture.transcript.md" in out
    assert "1:06:40" in out and "Whisper large-v3-turbo" in out and "10:00–10:40" in out
    md = (tmp_path / "lecture.transcript.md").read_text(encoding="utf-8")
    assert "word7999." in md and md.count("\n[") > 10


def test_what_the_tool_refuses(monkeypatch, tmp_path):
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "a.m4a").write_bytes(b"x")
    assert "not configured" in _run({"path": "a.m4a"}, _ws(tmp_path))
    _on(monkeypatch)
    FakeService(monkeypatch)
    assert _run({}, _ws(tmp_path)).startswith("Error: transcribe needs path")
    assert "not a recording" in _run({"path": "notes.txt"}, _ws(tmp_path))
    assert "not a file" in _run({"path": "gone.mp3"}, _ws(tmp_path))
    assert "escapes" in _run({"path": "../../etc/passwd.mp3"}, _ws(tmp_path))
    assert "language" in _run({"path": "a.m4a", "language": "fr"}, _ws(tmp_path))
    monkeypatch.setattr(trun, "MAX_BYTES", 0)
    assert "at most" in _run({"path": "a.m4a"}, _ws(tmp_path))


def test_the_services_refusals_reach_the_model_as_errors(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch)

    async def over(*a, **k):
        raise transcribe.OverAllowance("You have transcribed today's allowance (6 hours of audio)")

    monkeypatch.setattr(transcribe, "state", over)
    (tmp_path / "a.m4a").write_bytes(b"x")
    assert _run({"path": "a.m4a"}, _ws(tmp_path)) == "Error: You have transcribed today's allowance (6 hours of audio)"

    async def down(*a, **k):
        raise transcribe.Unavailable("the transcription service is unreachable: ConnectError")

    monkeypatch.setattr(transcribe, "state", down)
    assert "unavailable" in _run({"path": "a.m4a"}, _ws(tmp_path))
    assert svc.started == []


# ---- an attached recording ---------------------------------------------------------------------

def test_an_attached_recording_points_at_the_tool(tmp_path):
    (tmp_path / "voice.m4a").write_bytes(b"x")
    (tmp_path / "clip.webm").write_bytes(b"x")
    msg = [{"type": "file", "file": "voice.m4a"}, {"type": "text", "text": "summarise this"}]
    out = asyncio.run(_ingest(msg, str(tmp_path), transcribe=True))
    assert "call the Transcribe tool with this path" in out[0]["text"] and out[1]["text"] == "summarise this"
    # A clip goes to Video when it is on (and the note names Transcribe for its words alone).
    out = asyncio.run(_ingest([{"type": "file", "file": "clip.webm"}], str(tmp_path), video=True, transcribe=True))
    assert "`footage`" in out[0]["text"] and "Transcribe tool writes it down" in out[0]["text"]
    # With Video off, a clip is a recording too.
    out = asyncio.run(_ingest([{"type": "file", "file": "clip.webm"}], str(tmp_path), transcribe=True))
    assert "call the Transcribe tool" in out[0]["text"]
    # Without the tool, nothing changes.
    out = asyncio.run(_ingest([{"type": "file", "file": "voice.m4a"}], str(tmp_path)))
    assert "Transcribe" not in json.dumps(out)


# ---- the microphone ----------------------------------------------------------------------------

def _app():
    from fastapi.testclient import TestClient

    from cycls._agent.web import Config, web
    return TestClient(web(lambda context: iter(()), Config(public_path=THEME_PATH, auth=False)))


def test_the_mic_goes_to_the_service_when_it_is_configured(monkeypatch):
    _on(monkeypatch)
    calls = []

    async def short(data, **kw):
        calls.append(kw)
        return {"text": "مرحبا", "language": "ar", "words": []}

    monkeypatch.setattr(transcribe, "short", short)
    c = _app()
    r = c.post("/transcribe", files={"file": ("voice.webm", b"x" * 2000, "audio/webm")})
    assert r.json() == {"text": "مرحبا", "language": "ar", "engine": "cycls"}
    assert calls[0]["filename"] == "voice.webm" and calls[0]["language"] == "auto" and calls[0]["subject"] == "local"
    assert calls[0]["timeout"] == 130.0                      # no OpenAI behind it: wait for a cold listener
    cfg = c.get("/config").json()
    assert cfg["voice"] is True and cfg["voice_warm"] is True


def test_the_mic_falls_back_to_openai_when_the_service_is_slow(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = {}

    async def short(data, **kw):
        seen["timeout"] = kw["timeout"]
        raise transcribe.Busy("The listeners took too long to start")

    async def post(self, url, **kw):
        seen["openai"] = url
        return httpx.Response(200, json={"text": "hello"})

    monkeypatch.setattr(transcribe, "short", short)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    r = _app().post("/transcribe", files={"file": ("voice.m4a", b"x" * 2000, "audio/mp4")})
    assert r.json() == {"text": "hello"} and "openai.com" in seen["openai"] and seen["timeout"] == 45.0


def test_the_mic_says_why_when_it_cannot(monkeypatch):
    _on(monkeypatch)

    async def busy(data, **kw):
        raise transcribe.Busy("The listeners took too long to start")

    async def over(data, **kw):
        raise transcribe.OverAllowance("You have transcribed today's allowance")

    c = _app()
    monkeypatch.setattr(transcribe, "short", busy)
    r = c.post("/transcribe", files={"file": ("voice.m4a", b"x" * 2000)})
    assert r.status_code == 503 and "too long to start" in r.text
    monkeypatch.setattr(transcribe, "short", over)
    r = c.post("/transcribe", files={"file": ("voice.m4a", b"x" * 2000)})
    assert r.status_code == 429 and "allowance" in r.text
    r = c.post("/transcribe", files={"file": ("voice.m4a", b"x" * (client.SHORT_BYTES + 1))})
    assert r.status_code == 413


def test_the_mic_warms_a_listener_only_when_there_is_a_service(monkeypatch):
    warmed = []

    async def warm(workspace=None, *, subject=None):
        warmed.append(subject)
        return {"started": True}

    monkeypatch.setattr(transcribe, "warm", warm)
    c = _app()
    assert c.post("/transcribe/warm").json() == {"ok": True} and warmed == []
    assert "voice_warm" not in c.get("/config").json()
    _on(monkeypatch)
    assert c.post("/transcribe/warm").json() == {"ok": True}
    assert warmed == ["local"]

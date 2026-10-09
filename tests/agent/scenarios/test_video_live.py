"""Live Video tests: the SDK's client and tool against a REAL cycls-video service (the dev one).

Off by default:

    set -a && source ~/.cycls/cycls-video-dev.env && set +a      # VIDEO_URL, VIDEO_SECRET
    uv run pytest tests/agent/scenarios/test_video_live.py --live

Skipped unless --live AND video.configured(). Checks shapes, not pixels. A cold renderer takes a
minute or more (longer when Modal is short of L4s); a render of the 5 s fixture costs about a cent.
"""
import asyncio
import base64
import types

import pytest

from cycls._agent import video
from cycls._agent.video import contract
from cycls._agent.video import run as vrun
from cycls._agent.video.tool import VIDEO_LOADED


@pytest.fixture(autouse=True)
def _need_service(request, monkeypatch):
    if not request.config.getoption("--live"):
        pytest.skip("live video test (run with --live)")
    if not video.configured():
        pytest.skip("no video service configured (set VIDEO_URL and VIDEO_SECRET)")
    monkeypatch.setenv("VIDEO_ORGS", "*")
    contract.reset()


COMP = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=1080, height=1080">
<style>
@property --n { syntax: "<integer>"; initial-value: 0; inherits: true; }
body { margin: 0; font-family: "Inter", sans-serif; color: #fff; }
#root { position: relative; width: 1080px; height: 1080px; overflow: hidden; background: #0b1530; }
.clip { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.big { font-size: 220px; font-weight: 800; counter-reset: n var(--n); }
.big::after { content: counter(n) "%"; }
</style></head>
<body>
<div id="root" data-composition-id="main" data-no-timeline data-start="0" data-duration="5" data-width="1080" data-height="1080">
  <section id="s1" class="clip" data-start="0" data-duration="5" data-track-index="1">
    <div class="big" id="num"></div><p id="cap" style="font-size: 48px">answered by agents</p>
  </section>
</div>
<script>
const at = (s, f, d, u) => { const a = document.querySelector(s).animate(f, { delay: d, duration: u, easing: "ease-out", fill: "both" }); a.pause(); return a; };
at("#num", [{ "--n": 0 }, { "--n": 87 }], 300, 3000);
at("#cap", [{ opacity: 0 }, { opacity: 1 }], 600, 600);
</script>
</body></html>
"""


def _ws(tmp_path):
    return types.SimpleNamespace(root=tmp_path, subject="live-test", ws=None)


def test_the_contract_verifies():
    c = asyncio.run(contract.get(30))
    assert "fallback" not in c, c.get("fallback")
    assert c["version"] == "v1" and "Web Animations" in c["text"] and c["formats"]["reel"] == [1080, 1920]


def test_compile_lints_and_builds_the_preview(tmp_path):
    r = asyncio.run(video.compile(_ws(tmp_path), COMP, preview=True))
    assert r["ok"] is True, r["findings"]
    assert "<hyperframes-player" in r["preview"] and r["families"] == ["Inter"]
    bad = asyncio.run(video.compile(_ws(tmp_path), COMP.replace('"Inter"', '"Comic Sans MS"')))
    assert bad["ok"] is False and any(f["code"] == "font_not_in_catalogue" for f in bad["findings"])


def test_write_then_render_through_the_tool(tmp_path):
    """The executor end to end: save, lint, the browser check and a sheet; then the MP4."""
    VIDEO_LOADED.set(True)
    ctx = types.SimpleNamespace(chat_id="live-chat")
    out = asyncio.run(vrun._exec_video({"action": "write", "name": "live-check", "html": COMP}, _ws(tmp_path), ctx))
    assert isinstance(out, dict), out
    image = next(b for b in out["_model"] if b.get("type") == "image")
    assert base64.b64decode(image["source"]["data"])[:3] == b"\xff\xd8\xff"
    assert "Lint clean (5 s, 1080x1080)" in out["_model"][-1]["text"]
    out = asyncio.run(vrun._exec_video({"action": "render", "name": "live-check", "quality": "draft"}, _ws(tmp_path), ctx))
    assert isinstance(out, dict), out
    mp4 = (tmp_path / "videos" / "live-check.mp4").read_bytes()
    assert mp4[4:8] == b"ftyp" and len(mp4) > 10_000
    assert out["_ui"]["path"] == "videos/live-check.mp4"


def test_a_template_through_the_tool(tmp_path):
    """The contract lists the templates; one filled by the service, saved, checked."""
    c = asyncio.run(contract.get(30))
    assert "stats-reel" in c["text"]
    VIDEO_LOADED.set(True)
    ctx = types.SimpleNamespace(chat_id="live-chat-2")
    out = asyncio.run(vrun._exec_video({"action": "template", "name": "q3", "template": "stats-reel", "vars": {
        "title": "Q3 in numbers", "stats": [{"value": 42, "suffix": "%", "label": "more chats answered"}],
        "closing": "Onwards."}}, _ws(tmp_path), ctx))
    assert isinstance(out, dict), out
    assert "from the stats-reel template" in out["_model"][-1]["text"] and "Lint clean" in out["_model"][-1]["text"]
    assert "Q3 in numbers" in (tmp_path / "videos" / "q3.video.html").read_text(encoding="utf-8")

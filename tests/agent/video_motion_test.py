"""Motion in the Video tool (protocol 5): a workspace's Lottie files sent with a video, the animation
library searched from the signed contract, and the `motion` action putting a piece in through the service
with the brand kit's accent, font and logo."""
import asyncio
import json

from cycls._agent import video
from cycls._agent.video import media
from cycls._agent.video import run as vrun
from cycls._agent.video.fallback import FALLBACK
from cycls._agent.video.tool import ACTIONS, VIDEO_LOADED

from tests.agent.video_test import COMP, FakeService, _kit, _on, _run, _ws

LOTTIE = json.dumps({"v": "5.7.4", "fr": 30, "ip": 0, "op": 30, "w": 100, "h": 100, "layers": []})


def test_a_videos_lottie_files_are_sent_and_the_library_is_not(tmp_path):
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "wave.json").write_text(LOTTIE)
    (tmp_path / "uploads" / "big.json").write_text("x" * 1_600_000)
    (tmp_path / "uploads" / "clip.lottie").write_bytes(b"PK")
    html = ('<div data-lottie="uploads/wave.json"></div><div data-lottie="lottie:accent-check"></div>'
            "<div data-lottie='uploads/big.json'></div><div data-lottie=\"uploads/clip.lottie\"></div>"
            '<div data-lottie="uploads/none.json"></div>')
    lotties, files, errors = media.collect_lotties(html, tmp_path)
    assert list(lotties) == ["uploads/wave.json"] and lotties["uploads/wave.json"].endswith(".json")
    assert files[lotties["uploads/wave.json"]] == LOTTIE.encode()
    assert len(errors) == 2 and "1.5 MB" in errors[0] and ".json file" in errors[1]


def test_the_library_is_searched_from_the_signed_contract():
    assert {"lottie", "motion"} <= set(ACTIONS)
    assert FALLBACK["version"] == "v5" and len(FALLBACK["data"]["lottie"]) > 100
    out = vrun._lottie("checkmark")
    assert "accent-check" in out and 'data-lottie=\\"lottie:<id>\\"' not in out
    party = vrun._lottie("party")
    assert "emoji-party-popper" in party and "CC BY 4.0" in party, "an emoji says its credit"
    assert "accent-underline" in vrun._lottie(""), "no words: the accents"
    assert vrun._lottie("zzzzqq").startswith("Nothing in the animation library")


def test_motion_puts_a_piece_in_through_the_service_with_the_brand_kit(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch)
    VIDEO_LOADED.set(True)
    _kit(tmp_path)
    asked = []

    async def piece(ws, html, name, at, variables):
        asked.append((name, at, variables))
        if name == "chart" and not variables.get("items"):
            raise ValueError("items: 2 to 6, each {label, value}")
        return {"html": html.replace("Hi", 'Hi<div id="lower" class="clip"></div>'), "id": "lower"}

    monkeypatch.setattr(video, "piece", piece)
    _run({"action": "write", "name": "m", "html": COMP}, _ws(tmp_path))
    out = _run({"action": "motion", "name": "m", "piece": "lower-third", "start": 2.5, "vars": {"name": "Sara"}}, _ws(tmp_path))
    text = out["_model"][-1]["text"]
    assert "Added a lower-third" in text and "its id is lower" in text
    assert 'id="lower"' in (tmp_path / "videos" / "m.video.html").read_text()
    name, at, variables = asked[-1]
    assert name == "lower-third" and at == 2.5 and variables["name"] == "Sara"
    assert variables["accent"].lower() == "#f5a623" and variables["font"] == "Playfair Display", "the brand kit's"
    _run({"action": "motion", "name": "m", "piece": "logo-reveal", "start": 0}, _ws(tmp_path))
    assert asked[-1][2]["logo"] == "brand/logo.png" and asked[-1][2]["background"].lower() == "#0b1020"
    bad = _run({"action": "motion", "name": "m", "piece": "chart", "vars": {}}, _ws(tmp_path))
    assert bad.startswith("Error: chart: items")
    assert _run({"action": "motion", "name": "m", "piece": "confetti"}, _ws(tmp_path)).startswith("Error: motion needs piece")
    assert len(svc.submitted) == 3, "write and the two pieces were checked"

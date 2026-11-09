"""A small edit (quick.py): words and inline styles only get lint and a frame of each scene they touched
instead of the full check, and the render runs the browser check they left for it, beside the render.
Also: a motion piece that took the video's own colours says so."""
from cycls._agent import video
from cycls._agent.video import files, quick
from cycls._agent.video.tool import VIDEO_LOADED

from tests.agent.video_test import FakeService, _on, _run, _ws

PROMO = """<!doctype html><html lang="en"><head><style>h1 { color: #e8a33d; }</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="10" data-width="1080" data-height="1920">
  <div id="s1" class="clip" data-start="0" data-duration="4" data-track-index="1"><h1 id="t1" style="color:#fff">SLOW</h1></div>
  <div id="s2" class="clip" data-start="s1" data-duration="4" data-track-index="1"><h1>STAY <em>A WHILE</em></h1></div>
  <div id="s3" class="clip" data-start="s2 + 0.5" data-duration="1.5" data-track-index="1"><p>Dune Roast</p></div>
  <div id="s4" class="clip" data-start="9.5" data-duration="0.5" data-track-index="2"><p>end</p></div>
  <div id="glow" style="opacity:0.2"></div>
</div>
<script>at("#t1", [{ opacity: 0 }, { opacity: 1 }], 0, 300);</script>
</body></html>"""


def test_words_and_inline_styles_are_a_small_edit_looked_at_where_they_are():
    assert quick.moments(PROMO, PROMO.replace("SLOW", "SLOWER")) == [2.4]               # 0 + 4 x 0.6
    assert quick.moments(PROMO, PROMO.replace("A WHILE", "AWHILE")) == [6.4], "inner text: its scene"
    assert quick.moments(PROMO, PROMO.replace("color:#fff", "color:#f3e9dc")) == [2.4]
    # starts that name another scene, and two scenes at once
    both = PROMO.replace("SLOW", "Slow").replace("Dune Roast", "DUNE ROAST")
    assert quick.moments(PROMO, both) == [2.4, 9.4]                                      # s3: 8.5 + 1.5 x 0.6
    assert quick.moments(PROMO, PROMO.replace(">end<", ">fin<")) == [9.8], "kept inside the video"


def test_anything_more_is_the_full_check():
    big = [
        PROMO.replace("<p>end</p>", "<p>end</p><p>new</p>"),                             # an element added
        PROMO.replace('data-duration="1.5"', 'data-duration="2"'),                        # timing
        PROMO.replace('class="clip" data-start="9.5"', 'class="clip hot" data-start="9.5"'),  # a class
        PROMO.replace("h1 { color: #e8a33d; }", "h1 { color: #fff; }"),                   # a <style> rule
        PROMO.replace("0, 300", "0, 500"),                                                 # the script
        PROMO.replace('data-height="1920">', 'data-height="1920" style="background:#000">'),  # the root
        PROMO.replace('opacity:0.2', 'opacity:0.4'),                                       # untimed, on all along
        PROMO.replace("SLOW", "S").replace("A WHILE", "B").replace("Dune", "D").replace(">end<", ">E<"),  # 4 scenes
        PROMO,                                                                             # nothing seen changed
    ]
    for after in big:
        assert quick.moments(PROMO, after) is None, after[:0]
    assert quick.moments("<div", "<div>x") is None


def test_a_small_edit_is_looked_at_and_the_render_runs_the_check_it_left(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch)
    VIDEO_LOADED.set(True)
    ws = _ws(tmp_path)
    _run({"action": "write", "name": "promo", "html": PROMO}, ws)
    assert files.checked(tmp_path, "videos/promo.video.html"), "the write had the full check"
    # rendered straight after a full check: nothing beside it
    out = _run({"action": "render", "name": "promo"}, ws)
    assert [s["kind"] for s in svc.submitted] == ["review", "render"]
    assert "left for the render" not in out["_model"]

    out = _run({"action": "edit", "name": "promo", "changes": [{"old": "SLOW", "new": "SLOWER"}]}, ws)
    last = svc.submitted[-1]
    assert last["kind"] == "look" and last["params"]["at"] == [2.4]
    text = out["_model"][-1]["text"]
    assert "A small change (words and inline styles only)" in text and "at 2.4 s" in text
    assert "beside the render" in text

    out = _run({"action": "render", "name": "promo"}, ws)
    kinds = [s["kind"] for s in svc.submitted[-2:]]
    assert sorted(kinds) == ["render", "review"], kinds
    assert "The browser check the last small edits left for the render" in out["_model"]
    assert "Browser check: no issues." in out["_model"] and "render again" not in out["_model"]
    assert files.checked(tmp_path, "videos/promo.video.html"), "checked now: the next render runs it no more"

    # a structural edit: the full check, as before
    _run({"action": "edit", "name": "promo", "changes": [{"old": "<p>end</p>", "new": "<p>end</p><p>!</p>"}]}, ws)
    assert svc.submitted[-1]["kind"] == "review"


def test_the_check_beside_the_render_says_what_it_found(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch)
    VIDEO_LOADED.set(True)
    ws = _ws(tmp_path)
    _run({"action": "write", "name": "promo", "html": PROMO}, ws)
    _run({"action": "edit", "name": "promo", "changes": [{"old": "Dune Roast", "new": "A much longer line of words"}]}, ws)
    svc.result = {"state": "done", "kind": "review", "sheet": None, "video": {"duration": 10},
                  "findings": [{"code": "text_overflow", "severity": "error", "message": "#s3 p runs off the frame"}]}
    out = _run({"action": "render", "name": "promo"}, ws)
    assert "runs off the frame" in out["_model"] and "render again before you hand it over" in out["_model"]


def test_a_render_at_60_frames_a_second_is_asked_for_and_never_mistaken_for_the_30(monkeypatch, tmp_path):
    _on(monkeypatch)
    svc = FakeService(monkeypatch)
    VIDEO_LOADED.set(True)
    ws = _ws(tmp_path)
    _run({"action": "write", "name": "promo", "html": PROMO}, ws)
    svc.state = "pending"                         # the 30 fps render is still running when 60 is asked for
    _run({"action": "render", "name": "promo"}, ws)
    thirty = svc.submitted[-1]
    assert thirty["kind"] == "render" and thirty["params"] == {"quality": "final"}
    _run({"action": "render", "name": "promo", "fps": 60}, ws)
    sixty = svc.submitted[-1]
    assert sixty["params"] == {"quality": "final", "fps": 60} and sixty["key"] != thirty["key"], "a job of its own"
    assert _run({"action": "render", "name": "promo", "fps": 24}, ws).startswith("Error: fps: 30 or 60")


def test_a_clips_best_stretch_weak_stretches_and_light_are_said_and_the_example_starts_at_the_best():
    from cycls._agent.video import report
    info = {"duration": 12, "width": 1920, "height": 1080, "has_audio": False, "shots": [[0, 9], [9, 12]],
            "quality": {"best": [{"start": 4.5, "end": 7, "why": ["sharp", "steady"]}, {"start": 9.5, "end": 11.5, "why": []}],
                        "avoid": [{"start": 1, "end": 4.5, "what": "shaky"}, {"start": 9, "end": 12, "what": "dark"}],
                        "words": "dim, warm, natural colour"}}
    text = report.footage_text("videos/footage/beans.mp4", info)
    assert "Best stretch: 4.5–7 s (sharp, steady); also 9.5–11.5 s. Start a piece there." in text
    assert "Weak: 1–4.5 s shakes; 9–12 s is dark." in text
    assert "Light: dim, warm, natural colour" in text
    assert 'data-media-start="4.5" data-duration="2.5"' in text and "that example is its best stretch" in text
    # a talking clip keeps its first sentence as the example
    talk = {**info, "transcript": {"language": "en", "sentences": [{"start": 1.0, "end": 3.0, "text": "Hello."}]}}
    assert 'data-media-start="0.85"' in report.footage_text("a.mp4", talk)
    assert report.quality_lines(None) == []


def test_footage_the_service_matched_is_said():
    from cycls._agent.video import report
    said = report.matched_text([{"id": "v3", "src": "videos/footage/night.mp4", "adjust": {"exposure": 0.8, "temperature": 0.3},
                                 "limited": True}, {"id": "v2", "src": "b.mp4", "adjust": {"saturation": -0.2}}])
    assert said.startswith("Footage evened out under the look: v3 (night.mp4) lifted 0.8 stops, warmed; v2 (b.mp4) calmer in colour.")
    assert "v3 still stands out" in said
    assert report.matched_text(None) == "" and report.matched_text([]) == ""
    # the floor under dark footage (cycls-video match.mjs): its shadows opened, and why
    dark = report.matched_text([{"id": "v1", "src": "c.mp4", "adjust": {"exposure": 0.4, "shadows": 0.2},
                                 "off": ["dark under the grade (its middle grey 0.17, lifted to 0.30)"]}])
    assert "v1 (c.mp4) lifted 0.4 stops, its shadows opened (too dark under the look's grade)." in dark


def test_a_piece_in_the_videos_own_colours_says_so(monkeypatch, tmp_path):
    _on(monkeypatch)
    FakeService(monkeypatch)
    VIDEO_LOADED.set(True)

    async def piece(ws, html, name, at, variables):
        return {"html": html.replace("<p>end</p>", '<p>end</p><div id="lower" class="clip"></div>'), "id": "lower",
                "colours": {"accent": "#e8a33d", "dark": "#1a120c"}}

    monkeypatch.setattr(video, "piece", piece)
    ws = _ws(tmp_path)
    _run({"action": "write", "name": "promo", "html": PROMO}, ws)
    out = _run({"action": "motion", "name": "promo", "piece": "lower-third", "vars": {"name": "Omar"}}, ws)
    assert "takes the video's own colours (accent #e8a33d and dark ground #1a120c)" in out["_model"][-1]["text"]

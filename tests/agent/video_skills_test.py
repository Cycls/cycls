"""The Video tool's own skills: loaded in one call as text, listed in the tool (whole and short form), read as
the harness reads a skill, kept to our video format, and asked for by a first save in a chat without them."""
import pathlib
import re

from cycls._agent.tools.skills import MAX_DESCRIPTION, MAX_SKILL_BYTES, parse_frontmatter
from cycls._agent.video import skill, tool
from cycls._agent.video.tool import VIDEO_LOADED, VIDEO_SKILLED, video_skills_loaded

from tests.agent.video_test import COMP, FakeService, _on, _run, _ws

NAMES = ["video-direction", "motion-design", "promo-reel", "explainer-video", "footage-video"]
FILES = sorted(p for p in pathlib.Path(skill.__file__).with_name("skills").glob("*.md") if p.name != "NOTICE.md")


def test_the_five_skills_are_there_in_order():
    assert list(skill.SKILLS) == NAMES
    assert skill.suggested() == NAMES[:2] and skill.suggested("footage-video") == [*NAMES[:2], "footage-video"]
    assert skill.suggested("nope") == NAMES[:2]


def test_skills_load_in_one_call_and_say_nothing_was_made(monkeypatch, tmp_path):
    _on(monkeypatch)
    out = _run({"action": "skill", "skill": ["video-direction", "promo-reel"]}, _ws(tmp_path))
    assert out.index('<video-skill name="video-direction">') < out.index('<video-skill name="promo-reel">')
    assert skill.SKILLS["promo-reel"][1] in out and "Nothing was made" in out
    # names in one string, repeated, any case — and `name` when that's where they came
    one = _run({"action": "skill", "skill": "Motion-Design, motion-design"}, _ws(tmp_path))
    assert one.count("<video-skill ") == 1 and skill.SKILLS["motion-design"][1] in one
    assert '<video-skill name="footage-video">' in _run({"action": "skill", "name": "footage-video"}, _ws(tmp_path))
    assert not list(tmp_path.iterdir())                                       # nothing written


def test_an_unknown_skill_is_one_error_naming_them_all(monkeypatch, tmp_path):
    _on(monkeypatch)
    out = _run({"action": "skill", "skill": ["promo-reel", "viral-magic"]}, _ws(tmp_path))
    assert out.startswith("Error: no skill named 'viral-magic'") and all(n in out for n in NAMES)
    assert _run({"action": "skill"}, _ws(tmp_path)).startswith("Error: `skill` names the skills")


def test_the_tool_says_what_its_skills_are_whole_and_short():
    whole, short = tool.video_tool(True, "THE CONTRACT"), tool.video_tool(False)
    for name, (description, _) in skill.SKILLS.items():
        assert f"· {name} — {description}" in whole["description"]
        assert name in short["description"] and name in whole["input_schema"]["properties"]["skill"]["description"]
    assert "skill" in whole["input_schema"]["properties"]["action"]["enum"]
    assert short["input_schema"]["properties"]["skill"]["type"] == ["string", "array"]
    assert '"action": "skill"' in short["description"]


def test_a_skill_loaded_on_the_short_form_says_the_instructions_loaded_too(monkeypatch, tmp_path):
    _on(monkeypatch)
    token = VIDEO_LOADED.set(False)
    try:
        out = _run({"action": "skill", "skill": "motion-design"}, _ws(tmp_path))
    finally:
        VIDEO_LOADED.reset(token)
    assert '<video-skill name="motion-design">' in out and "full instructions were not loaded" in out


def test_the_skill_files_are_read_as_the_harness_reads_a_skill_and_fit_its_limits():
    assert len(FILES) == len(skill.SKILLS) == 5
    for f in FILES:
        raw = f.read_bytes()
        meta, body = parse_frontmatter(raw.decode("utf-8").replace("\r\n", "\n"))
        assert skill.SKILLS[meta["name"]] == (meta["description"], body.strip()), f.name
        assert meta["name"] == f.stem and len(meta["description"]) <= min(MAX_DESCRIPTION, 240)
        assert 4_000 <= len(raw) <= min(MAX_SKILL_BYTES, 24 * 1024), f"{f.name}: {len(raw)} bytes"


def test_the_skills_speak_our_format_only():
    """Nothing the video cannot do: no animation library, no outside files, no tool the model doesn't have."""
    for f in FILES:
        text = f.read_text("utf-8")
        low = text.lower()
        for word in ("gsap", "npx ", "hyperframes", "remotion", "bash", "subagent", "tl.to", "tl.from"):
            assert word not in low, f"{f.name} mentions {word!r}"
        assert not re.search(r"@keyframes\s+[\w-]+\s*\{", text), f"{f.name} defines CSS @keyframes"
        assert not re.search(r"<script[^>]*\bsrc=|<link\b|@import|@font-face|https?://", text), f"{f.name}: outside files"
        used = [line for line in text.splitlines()          # a line that forbids it ("never Math.random") is fine
                if re.search(r"\.animate\(|requestAnimationFrame|Math\.random|setTimeout", line) and "never" not in line.lower()]
        assert not used, f"{f.name}: not at(): {used}"
        assert not re.search(r'<html[^>]*\bdir=', text), f"{f.name}: dir on <html> blanks the render"
    assert (FILES[0].parent / "NOTICE.md").is_file() and (FILES[0].parent / "LICENSE-Apache-2.0.txt").is_file()


def test_a_first_save_without_skills_says_which_to_load(monkeypatch, tmp_path):
    import asyncio
    from cycls._agent import video
    _on(monkeypatch)
    FakeService(monkeypatch)
    monkeypatch.setattr(video, "get_contract", lambda etag=None: asyncio.sleep(0, result=None))
    token = VIDEO_SKILLED.set(False)
    try:
        promo = _run({"action": "write", "name": "a", "html": COMP}, _ws(tmp_path))
        clip = COMP.replace("Hi", '<video id="v" src="uploads/i.mp4"></video>')
        footage = _run({"action": "write", "name": "b", "html": clip}, _ws(tmp_path))
        guide = _run({"action": "guide"}, _ws(tmp_path))
    finally:
        VIDEO_SKILLED.reset(token)
    text = lambda out: out if isinstance(out, str) else out["_model"][-1]["text"]
    assert '"skill": ["video-direction", "motion-design", "promo-reel"]' in text(promo)
    assert '"skill": ["video-direction", "motion-design", "footage-video"]' in text(footage)
    assert "load its skills in one call" in guide and "footage-video" in guide
    quiet = _run({"action": "write", "name": "c", "html": COMP}, _ws(tmp_path))      # loaded (the default): nothing said
    assert "No video skill" not in text(quiet)
    assert "load its skills" not in _run({"action": "guide"}, _ws(tmp_path))


def test_the_kind_of_a_video_is_read_from_what_it_holds():
    assert skill.kind_of('<video id="a" src="uploads/x.mp4">') == "footage-video"
    assert skill.kind_of('<audio id="vo" src="videos/voice/a.m4a">') == "explainer-video"
    assert skill.kind_of('<audio id="m" src="music:calm-1">') == "promo-reel"
    assert skill.kind_of(None) is None


def test_the_skills_come_back_whole_and_are_never_cleared():
    """Three skills run past the size a tool result is spilled to a file at (an agent once had to `read` them back in
    pieces): like Design's, they are instructions, not history."""
    from cycls._agent.harness.compact import clear
    from cycls._agent.spill import SPILL_AT
    from cycls._agent.tools.skills import loads_skill
    assert sum(len(skill.SKILLS[n][1]) for n in skill.suggested("promo-reel")) > SPILL_AT
    assert loads_skill({"name": "video", "input": {"action": "skill", "skill": ["promo-reel"]}})
    assert not loads_skill({"name": "video", "input": {"action": "write"}})
    said = skill.load(skill.suggested("promo-reel"))
    chat = [{"role": "assistant", "content": [{"type": "tool_use", "id": "s", "name": "video", "input": {"action": "skill"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "s", "content": said}]}]
    assert clear(chat)[1]["content"][0]["content"] == said


def test_a_chat_has_loaded_skills_once_it_called_skill():
    use = lambda action: {"role": "assistant", "content": [{"type": "tool_use", "name": "video", "input": {"action": action}}]}
    assert not video_skills_loaded([use("guide"), use("write"), {"role": "user", "content": "hi"}])
    assert video_skills_loaded([use("guide"), use("skill")])

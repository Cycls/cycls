"""What a first task fetched with its own tool calls before it could start is given with the message: the person's
memory index, the workspace's top level, a design request's skills, and the calendar. A new design spent its first
2–3 turns on these (measured on super-dev, 2026-11-25)."""
import asyncio, json
from datetime import datetime, timezone

from cycls._agent import state
from cycls._agent.harness.main import _calendar, _first_given, _first_task_context
from cycls._agent.design.run import design_preload
from cycls._agent.design.tool import design_skills_loaded
from cycls._app.db import workspace


def _ws(tmp_path):
    return workspace("org:u1", tmp_path, base=f"file://{tmp_path}")


def test_memory_and_top_level_come_with_the_first_task(tmp_path):
    ws = _ws(tmp_path)
    ws.root.mkdir(parents=True, exist_ok=True)
    # as a model stores it: its markdown sent as a JSON string, so the store holds a string of a string
    asyncio.run(state.memory_db(ws).put("memory/index", json.dumps("# Memory index\n- brand: teal and sand")))
    (ws.root / "designs").mkdir()
    (ws.root / "notes.md").write_text("x")
    (ws.root / ".db").mkdir(exist_ok=True)
    lines = asyncio.run(_first_task_context(ws))
    assert lines[0].startswith("[Your memory of this person")
    assert "# Memory index\n- brand: teal and sand" in lines[0]                 # read as the markdown it is
    assert "don't fetch it again" in lines[0]
    assert lines[-1].startswith("[This workspace's top level")
    assert "designs/" in lines[-1] and "notes.md" in lines[-1] and ".db" not in lines[-1]


def test_no_memory_says_so_and_an_empty_workspace_too(tmp_path):
    ws = _ws(tmp_path)
    ws.root.mkdir(parents=True, exist_ok=True)
    lines = asyncio.run(_first_task_context(ws))
    assert "is empty" in lines[0] and "nothing to fetch" in lines[0]
    assert lines[-1].endswith("empty]")


def test_given_once_per_chat():
    given = [{"role": "user", "content": [{"type": "text", "text": "make a poster"},
                                          {"type": "text", "text": "[Your memory of this person — …]\n# Memory"}]}]
    assert _first_given(given)
    assert not _first_given([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}])


def test_the_added_lines_stay_out_of_the_chat_bubble():
    msg = {"role": "user", "content": [
        {"type": "text", "text": "Design a poster for our 5K"},
        {"type": "text", "text": "[Your memory of this person — `memory/index`…]\n# Memory"},
        {"type": "text", "text": "[This workspace's top level as this chat starts…: designs/]"},
        {"type": "text", "text": "[The design this chat is working on, as it is now …]"},
        {"type": "text", "text": "[The Design skills for this request, loaded for you …]\n\n<design-skill name=\"x\">"}]}
    assert state.user_text(msg) == "Design a poster for our 5K"


def test_a_design_request_comes_with_its_skills(tmp_path):
    post = asyncio.run(design_preload([], "Design an Instagram post for our pottery workshop", str(tmp_path)))
    assert post.startswith("[The Design skills for this request")
    assert '<design-skill name="design-direction">' in post and '<design-skill name="graphic-design">' in post
    deck = asyncio.run(design_preload([], "Make a six-slide pitch deck for Tidepool", str(tmp_path)))
    assert '<design-skill name="deck-design">' in deck
    report = asyncio.run(design_preload([], "Create a two-page PDF report on our Q3", str(tmp_path)))
    assert '<design-skill name="document-design">' in report
    ar = asyncio.run(design_preload([], "صمم بوستر لافتتاح مقهى", str(tmp_path)))
    assert '<design-skill name="graphic-design">' in ar
    # and the chat counts as having loaded them: the render gate needs no `skill` call
    assert design_skills_loaded([{"role": "user", "content": [{"type": "text", "text": "Design a post"},
                                                              {"type": "text", "text": post}]}])


def test_no_skills_for_a_question_or_a_chat_that_has_them(tmp_path):
    assert asyncio.run(design_preload([], "What makes a good PDF report?", str(tmp_path))) is None   # no ask to make one
    assert asyncio.run(design_preload([], "thanks!", str(tmp_path))) is None
    had = [{"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "design",
                                              "input": {"action": "skill", "skill": ["design-direction"]}}]}]
    assert asyncio.run(design_preload(had, "Design another poster", str(tmp_path))) is None


def test_the_calendar_names_each_weekday():
    cal = _calendar(datetime(2026, 11, 25, 9, tzinfo=timezone.utc))
    assert "today is Wednesday 25 November 2026" in cal
    assert "Thu 26 Nov" in cal and "Wed 9 Dec" in cal and "Thu 10 Dec" not in cal

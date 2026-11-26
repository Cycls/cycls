"""Routines (docs/rfc-routines.md): when each runs, in its own time zone and a little early; set up only from the
card; the clock starting each once; a run as its owner's message in a chat of its own, off the chat list; `tell`
reaching its owner; three failures pausing it."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from cycls._agent import inbox, routines, state
from cycls._app.auth import User
from cycls._app.db import workspace

SARA = User(id="sara", org_id="org_1", name="Sara Alharbi", plan="u:pro")
UTC = timezone.utc


def _ws(tmp_path):
    return workspace(SARA, tmp_path, base=f"file://{tmp_path}", ws="u-sara")


def test_a_routine_runs_at_its_local_time_on_its_days_a_little_early():
    at = lambda *a: datetime(*a, tzinfo=UTC)
    morning = {"every": "day", "time": "08:00", "tz": "Asia/Riyadh"}   # 05:00 UTC
    t = routines.next_run(routines.when_ok(morning), at(2026, 11, 23, 6, 0), "r1")
    assert at(2026, 11, 24, 4, 50) <= t <= at(2026, 11, 24, 5, 0)   # tomorrow's, up to ten minutes before 8
    weekdays = routines.when_ok({"every": "days", "days": ["sun", "mon", "tue", "wed", "thu"], "time": "08:00", "tz": "Asia/Riyadh"})
    friday = routines.next_run(weekdays, at(2026, 11, 26, 6, 0))   # a Thursday, after its time
    assert friday.date().isoformat() == "2026-11-29"   # Sunday: Friday and Saturday are the weekend there
    london, tz = routines.when_ok({"every": "day", "time": "09:00", "tz": "Europe/London"}), ZoneInfo("Europe/London")
    local = [routines.next_run(london, at(2026, 10, d, 12), "r1").astimezone(tz).strftime("%H:%M") for d in (23, 25)]
    assert all("08:50" <= t <= "09:00" for t in local)   # either side of the clocks changing, 9 stays 9
    month_end = routines.when_ok({"every": "month", "day": 31, "time": "10:00", "tz": "UTC"})
    assert routines.next_run(month_end, at(2027, 2, 1)).date().isoformat() == "2027-02-28"
    once = routines.when_ok({"every": "once", "date": "2026-12-01", "time": "10:00", "tz": "UTC"})
    assert routines.next_run(once, at(2026, 12, 2)) is None


def test_made_from_the_card_five_at_most_and_the_clock_follows_it(tmp_path):
    ws = _ws(tmp_path)
    spec = lambda i: {"id": f"p{i}", "name": f"Tenders {i}", "prompt": "Look up new tenders", "chat": "c1",
                      "when": {"every": "day", "time": "08:00", "tz": "Asia/Riyadh"}}
    made = asyncio.run(routines.make(ws, spec(0), "sara"))
    assert made["id"] == "p0" and made["on"] and made["fresh"] and made["next"]
    assert asyncio.run(routines.make(ws, spec(0), "sara")) == made   # the same card twice: one routine
    for i in range(1, routines.LIMIT):
        asyncio.run(routines.make(ws, spec(i), "sara"))
    try:
        asyncio.run(routines.make(ws, spec(9), "sara"))
        assert False, "a sixth"
    except ValueError as e:
        assert "5" in str(e)
    clock = routines._clock(tmp_path, f"file://{tmp_path}")
    assert len(asyncio.run(clock.keys(prefix="due/"))) == routines.LIMIT
    asyncio.run(routines.change(ws, "p0", {"on": False}))
    asyncio.run(routines.remove(ws, "p1"))
    assert len(asyncio.run(clock.keys(prefix="due/"))) == routines.LIMIT - 2   # paused and deleted: off the clock
    assert asyncio.run(routines.make(ws, {**spec(7), "chat": "team-x", "fresh": False}, "sara"))["fresh"]   # never a team's chat


def test_the_clock_starts_each_due_routine_once_and_moves_it_on(tmp_path):
    ws = _ws(tmp_path)
    asyncio.run(routines.make(ws, {"id": "p0", "name": "Tenders", "prompt": "Look up new tenders",
                                   "when": {"every": "day", "time": "08:00", "tz": "UTC"}}, "sara"))
    due = datetime.fromisoformat(asyncio.run(routines.get(ws, "p0"))["next"])
    started = []

    async def start(w, record, chat):
        started.append((w.ws, record["id"], chat))
    later = due.replace(minute=due.minute) + (datetime(2026, 1, 1, 0, 1, tzinfo=UTC) - datetime(2026, 1, 1, tzinfo=UTC))
    asyncio.run(routines.tick(tmp_path, f"file://{tmp_path}", later, start))
    asyncio.run(routines.tick(tmp_path, f"file://{tmp_path}", later, start))   # the platform's retry: nothing twice
    record = asyncio.run(routines.get(ws, "p0"))
    assert [(w, r) for w, r, _ in started] == [("u-sara", "p0")]
    assert datetime.fromisoformat(record["next"]) > later and record["runs"][0]["chat"] == started[0][2]


def test_a_run_is_its_owners_message_in_a_chat_of_its_own_and_tell_reaches_them(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import cycls._agent.web.server as server
    from cycls._agent.web.server import Config
    from tests.agent.web_test import THEME_PATH
    monkeypatch.setattr(server, "validator", lambda *a, **k: (lambda: SARA))
    monkeypatch.setenv("CYCLS_SECRET_KEY", "k")   # what signs a run, as it signs a connector's state
    seen = []

    async def agent(context):
        s = await state.Session.open(context)
        await s.add_user(context.messages.raw[-1]["content"])
        seen.append((context.user.plan, context.routine, context.connectors))
        await routines.tell({"text": "3 new construction tenders"}, context.workspace,
                            SimpleNamespace(routine=context.routine, chat_id=context.chat_id))
        yield "Found 3."

    web = TestClient(server.web(agent, Config(public_path=THEME_PATH, auth=True, workspaces="member", volume=str(tmp_path),
                                              routines=[])))
    h = {"X-Workspace": "u-sara"}
    web.post("/chat", json={"messages": [{"role": "user", "content": "hi"}], "tz": "Asia/Riyadh"}, headers=h)   # who she is, kept
    ws = _ws(tmp_path)
    asyncio.run(routines.make(ws, {"id": "p0", "name": "Tenders", "prompt": "Look up new tenders", "connectors": ["outlook"],
                                   "when": {"every": "day", "time": "08:00", "tz": "Asia/Riyadh"}}, "sara"))
    record, chat = asyncio.run(routines.now(ws, "p0"))
    assert web.post("/routines/run", params={"id": chat}, json={"sig": "forged.x"}, headers=h).status_code == 403
    r = web.post("/routines/run", params={"id": chat}, json={"sig": routines.signed(ws, record, chat)}, headers=h)
    assert r.status_code == 200 and seen[-1][0] == "u:pro" and seen[-1][1]["id"] == "p0" and seen[-1][2] == ["outlook"]
    from tests.agent.team_chats_test import _routers
    routes = _routers(tmp_path)
    shown = routes.get(f"/chats/{chat}", headers=h).json()["messages"]
    assert chat not in {c["id"] for c in routes.get("/chats", headers=h).json()}   # a run is on its routine's page, not the list
    assert shown[0]["routine"]["name"] == "Tenders" and shown[0]["content"].startswith("Look up new tenders")
    told = asyncio.run(inbox.read(SARA, tmp_path, f"file://{tmp_path}"))["items"][0]
    assert (told["kind"], told["text"], told["title"], told["chat"]) == ("routine", "3 new construction tenders", "Tenders", chat)
    assert asyncio.run(routines.get(ws, "p0"))["runs"][0]["said"] == "3 new construction tenders"


def test_three_failures_in_a_row_pause_it_and_its_owner_hears(tmp_path):
    ws = _ws(tmp_path)
    asyncio.run(routines.make(ws, {"id": "p0", "name": "Tenders", "prompt": "Look up new tenders",
                                   "when": {"every": "day", "time": "08:00", "tz": "UTC"}}, "sara"))
    for _ in range(routines.FAILS):
        _, chat = asyncio.run(routines.now(ws, "p0"))
        asyncio.run(routines.ended(ws, "p0", chat, "failed"))
    record = asyncio.run(routines.get(ws, "p0"))
    assert not record["on"] and record["next"] is None and [r["ok"] for r in record["runs"]] == [False] * routines.FAILS
    states = [i["state"] for i in asyncio.run(inbox.read(SARA, tmp_path, f"file://{tmp_path}"))["items"]]
    assert states == ["paused", "stuck", "stuck"]


def test_the_routine_tool_shows_a_card_and_only_set_up_makes_it(tmp_path):
    ws = _ws(tmp_path)
    ctx = SimpleNamespace(chat_id="c1", tz="Asia/Riyadh", routine=None)
    card = asyncio.run(routines.tool({"action": "make", "name": "Tenders", "prompt": "Look up new tenders",
                                      "when": {"every": "day", "time": "08:00"}}, ws, ctx))
    assert card["action"] == "routine" and card["routine"]["when"]["tz"] == "Asia/Riyadh" and card["routine"]["chat"] == "c1"
    assert "end your turn" in card["ack"] and asyncio.run(routines.listing(ws)) == []   # nothing made yet
    asyncio.run(routines.make(ws, card["routine"], "sara"))
    assert "Tenders" in asyncio.run(routines.tool({"action": "list"}, ws, ctx))
    assert asyncio.run(routines.tool({"action": "pause", "id": card["routine"]["id"]}, ws, ctx)) == "Tenders is paused."

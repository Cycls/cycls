"""The inbox: one per person across their workspaces. A team message tells whoever it names, @all every member, and
whoever wrote the message it answers; never its sender, nor whoever had the chat open, and a replay never twice. The
bell reads it and marks it read, and opening a chat reads what it had about that chat."""
import asyncio

from cycls._agent import activity, inbox, state
from cycls._app.auth import User
from cycls._app.db import workspace
from tests.agent.team_chats_test import OMAR, SARA, _routers, _team

LINA = User(id="lina", org_id="org_1", name="Lina Saad")


def _web(tmp_path, monkeypatch, ws_id):
    from fastapi.testclient import TestClient
    import cycls._agent.web.server as server
    from cycls._agent.web.server import Config
    from tests.agent.web_test import THEME_PATH
    me = {"user": SARA}
    monkeypatch.setattr(server, "validator", lambda *a, **k: (lambda: me["user"]))

    async def agent(context):
        s = await state.Session.open(context)
        await s.add_user(context.messages.raw[-1]["content"])
        yield "On it"

    for u in (SARA, OMAR, LINA):   # their names, as their sign-in gives them: what an @ matches
        asyncio.run(activity.put_person(workspace(u, tmp_path, base=f"file://{tmp_path}", ws=ws_id), name=u.name))
    web = TestClient(server.web(agent, Config(public_path=THEME_PATH, auth=True, workspaces="member", volume=str(tmp_path))))
    h = {"X-Workspace": ws_id}

    def say(who, text, mid, chat=None, **kw):
        me["user"] = who
        r = web.post(f"/chat?id={chat}" if chat else "/chat", headers=h, json={"messages": [{"role": "user", "content": text, "id": mid}], **kw})
        return r.json().get("chat_id") if r.headers.get("content-type", "").startswith("application/json") else chat
    return say


def test_a_mention_and_a_reply_reach_who_they_name_and_never_the_sender(tmp_path, monkeypatch):
    ws_id = _team(tmp_path)
    say, bell = _web(tmp_path, monkeypatch, ws_id), _routers(tmp_path)
    box = lambda who, **q: bell.get("/inbox", params=q, headers={"X-Test-User": who}).json()
    chat = say(SARA, "@Omar Khalid can you check slide 4?", "m-sara-1", post=True, team=True)
    [told] = box("omar")["items"]
    assert told["kind"] == "mention" and told["by"] == {"id": "sara", "name": "Sara Alharbi"}
    assert (told["ws"], told["chat"], told["turn"], told["text"]) == (ws_id, chat, "m-sara-1", "@Omar Khalid can you check slide 4?")
    assert told["title"] == "@Omar Khalid can you check slide 4?" and box("sara") == {"items": [], "unread": 0}
    say(OMAR, "Done, @Sara Alharbi", "m-omar-1", chat, post=True, reply="m-sara-1")   # named and answered: told once
    assert [(i["kind"], i["by"]["id"]) for i in box("sara")["items"]] == [("reply", "omar")]
    say(SARA, "@Super and @Omar Khalid, the totals", "m-sara-2", chat)   # one that asks the agent tells too
    assert box("omar", limit=1)["unread"] == 2 and len(box("omar", limit=1)["items"]) == 1
    say(SARA, "@Super and @Omar Khalid, the totals", "m-sara-2", chat, regenerate="m-sara-2")   # run again: not again
    assert box("omar")["unread"] == 2
    assert bell.post("/inbox/seen", headers={"X-Test-User": "omar"}).json() == {"ok": True, "unread": 0}
    assert box("omar")["unread"] == 0 and len(box("omar")["items"]) == 2


def test_all_tells_every_member_but_the_sender(tmp_path, monkeypatch):
    ws_id = _team(tmp_path)
    asyncio.run(state.org_db("org_1", tmp_path, f"file://{tmp_path}").put(f"members/{ws_id}/lina", {"role": "editor"}))
    say = _web(tmp_path, monkeypatch, ws_id)
    say(OMAR, "@all standup at 10", "m-omar-1", post=True, team=True)
    unread = {u.id: asyncio.run(inbox.read(u, tmp_path, f"file://{tmp_path}"))["unread"] for u in (SARA, OMAR, LINA)}
    assert unread == {"sara": 1, "omar": 0, "lina": 1}


def test_a_push_says_who_and_what_where_it_opens_and_goes_only_to_those_who_picked_it(tmp_path, monkeypatch):
    import httpx
    ws_id = _team(tmp_path)
    say, bell = _web(tmp_path, monkeypatch, ws_id), _routers(tmp_path)
    sent = []

    async def post(self, url, json=None, headers=None):
        sent.append((url, json, headers["Authorization"].split()[0]))
        return httpx.Response(200, json={"id": "x"})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(inbox, "_PUSH", {"app_id": "app-1", "key": "os_v2_test", "agent": "super"})
    assert bell.get("/notifications", headers={"X-Test-User": "omar"}).json() == {"mention": "push", "away": "push", "routine": "push"}
    chat = say(SARA, "@Omar Khalid slide 4?", "m-1", post=True, team=True)
    [(url, body, scheme)] = sent
    assert url == "https://api.onesignal.com/notifications?c=push" and scheme == "Key"
    assert body["include_aliases"] == {"external_id": ["omar"]} and body["contents"] == {"en": "Sara Alharbi mentioned you", "ar": "إشارة إليك من Sara Alharbi"}
    assert body["data"] == {"path": f"/agent/super?chat={chat}&ws={ws_id}"} and body["web_url"] == f"https://testserver/?ws={ws_id}&id={chat}"
    assert "slide" not in str(body["contents"])   # never the message: it is behind sign-in, in the bell
    assert bell.patch("/notifications", json={"mention": "off", "away": "loud"}, headers={"X-Test-User": "omar"}).json() == {"mention": "off", "away": "push", "routine": "push"}
    say(SARA, "@Omar Khalid and the totals", "m-2", chat, post=True)
    assert len(sent) == 1 and bell.get("/inbox", headers={"X-Test-User": "omar"}).json()["unread"] == 2   # the bell still has it


def test_a_run_that_ends_while_its_owner_is_away_tells_them_how_it_ended(tmp_path):
    from cycls._agent.web.server import Run, _finish
    mine = workspace(SARA, tmp_path, base=f"file://{tmp_path}", ws="u-sara")
    asyncio.run(state.touch_meta(mine, "c1", "Make the launch deck"))

    def ended(status, waiting=None, attached=False):
        run = Run(detach=True, workspace=mine, chat_id="c1", user=SARA, agent="super")
        run.attached, run.waiting = attached, waiting
        asyncio.run(_finish(run, status, None))
    ended("done"), ended("done", "ask"), ended("done", "confirm"), ended("failed")
    ended("done", attached=True)   # they watched it end
    ended("stopped")               # they stopped it
    items = asyncio.run(inbox.read(SARA, tmp_path, f"file://{tmp_path}"))["items"]
    assert [i["state"] for i in items] == ["failed", "approve", "asks", "done"]
    assert {(i["kind"], i["chat"], i["title"], i["ws"]) for i in items} == {("away", "c1", "Make the launch deck", "u-sara")}


def test_an_inbox_keeps_the_newest_thirty(tmp_path):
    team = state.team_chats(workspace(SARA, tmp_path, base=f"file://{tmp_path}", ws=_team(tmp_path)))
    for n in range(inbox.KEEP + 2):
        asyncio.run(inbox.notify(team, ["omar"], "mention", by="sara", text=f"#{n}"))
    got = asyncio.run(inbox.read(OMAR, tmp_path, f"file://{tmp_path}"))
    assert len(got["items"]) == inbox.KEEP and got["items"][0]["text"] == f"#{inbox.KEEP + 1}" and got["unread"] == inbox.KEEP


def test_whoever_has_the_chat_open_reads_a_mention_in_the_hold_and_is_not_told(tmp_path, monkeypatch):
    ws_id, base = _team(tmp_path), f"file://{tmp_path}"
    sara, omar = (workspace(u, tmp_path, base=base, ws=ws_id) for u in (SARA, OMAR))
    monkeypatch.setattr(inbox, "HOLD", 0.2)
    by = {"id": "sara", "name": "Sara Alharbi", "mentions": ["omar", "lina"], "turn": "m-1"}

    async def go():
        told = asyncio.create_task(inbox.mentioned(sara, "team-1", {"role": "user", "content": "@Omar @Lina slide 4?"}, by))
        await asyncio.sleep(0.05)
        await state.see(omar, "team-1", "9")   # his open chat looks again, and reads it
        await told
    asyncio.run(go())
    assert {u.id: asyncio.run(inbox.read(u, tmp_path, base))["unread"] for u in (OMAR, LINA)} == {"omar": 0, "lina": 1}


def test_opening_a_chat_reads_what_the_bell_had_about_it(tmp_path, monkeypatch):
    ws_id = _team(tmp_path)
    say, bell = _web(tmp_path, monkeypatch, ws_id), _routers(tmp_path)
    omar = {"X-Test-User": "omar", "X-Workspace": ws_id}
    chat = say(SARA, "@Omar Khalid slide 4?", "m-1", post=True, team=True)
    other = say(SARA, "@Omar Khalid and the budget?", "m-2", post=True, team=True)
    assert bell.get("/inbox", headers=omar).json()["unread"] == 2
    bell.get(f"/chats/{chat}", params={"last": 30}, headers=omar)   # opened, on any device
    got = bell.get("/inbox", headers=omar).json()
    assert got["unread"] == 1 and len(got["items"]) == 2   # still in the list
    assert bell.post("/inbox/seen", json={"chat": other}, headers=omar).json() == {"ok": True, "unread": 0}   # the one in front

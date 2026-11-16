"""Team chats: a team workspace's own chats, read and written by its members. A message to the team alone runs
nothing; the next one that asks the agent reads it, and who wrote each."""
import asyncio

from cycls._agent import state
from cycls._app.auth import User
from cycls._app.db import workspace

SARA = User(id="sara", org_id="org_1", name="Sara Alharbi")
OMAR = User(id="omar", org_id="org_1", name="Omar Khalid")


def _team(tmp_path):
    orgdb = state.org_db("org_1", tmp_path, f"file://{tmp_path}")
    ws_id = asyncio.run(state.create_team_ws(orgdb, "Marketing", "sara"))["id"]
    asyncio.run(orgdb.put(f"members/{ws_id}/omar", {"role": "editor"}))
    return ws_id


def _routers(tmp_path):
    from types import SimpleNamespace
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    from cycls._agent.web.routers import install_routers
    who = {"sara": SARA, "omar": OMAR, "out": User(id="out", org_id="org_2")}
    stub = SimpleNamespace(prod=False, _auth_provider=None, config=SimpleNamespace(workspaces="member", max_upload=512))
    def auth(request: Request):
        return who[request.headers.get("x-test-user", "sara")]

    fapp = FastAPI()
    install_routers(stub, fapp, Depends(auth), tmp_path, f"file://{tmp_path}")
    return TestClient(fapp)


def test_a_team_chat_is_the_workspaces_and_no_one_elses(tmp_path):
    ws_id = _team(tmp_path)
    client = _routers(tmp_path)
    team, omar = {"X-Workspace": ws_id}, {"X-Workspace": ws_id, "X-Test-User": "omar"}
    assert client.put("/chats/team-1", json={"title": "Café launch"}, headers=team).status_code == 200
    client.put("/chats/mine", json={"title": "Just mine"}, headers=team)
    assert [(c["id"], c.get("team")) for c in client.get("/chats", headers=omar).json()] == [("team-1", True)]
    assert {c["id"] for c in client.get("/chats", headers=team).json()} == {"team-1", "mine"}
    assert client.get("/chats").json() == []   # Sara's personal workspace has no team chats
    assert client.put("/chats/team-1", json={"title": "x"}).status_code == 404   # nor reaches one
    assert client.get("/chats", headers={"X-Workspace": ws_id, "X-Test-User": "out"}).status_code == 404
    # a favorite is the member's own
    client.put("/chats/team-1", json={"favoritedAt": "2026-11-12T09:00:00Z"}, headers=omar)
    fav = lambda h: {c["id"]: c["favoritedAt"] for c in client.get("/chats", headers=h).json()}["team-1"]
    assert fav(omar) and not fav(team)
    client.put("/chats/team-1", json={"favoritedAt": None}, headers=omar)
    assert not fav(omar)
    # deleted, it is in the team's trash, and comes back
    client.delete("/chats/team-1", headers=omar)
    assert [r["id"] for r in client.get("/trash", headers=team).json()] == ["chat:team-1"]
    assert client.post("/trash/chat:team-1/restore", headers=team).status_code == 200
    assert "team-1" in {c["id"] for c in client.get("/chats", headers=omar).json()}


def test_a_chat_moves_to_the_team_with_its_turns_signed(tmp_path):
    ws_id = _team(tmp_path)
    client = _routers(tmp_path)
    mine = workspace(SARA, tmp_path, base=f"file://{tmp_path}", ws=ws_id)
    asyncio.run(state.append_messages(mine, "c1", [{"role": "user", "content": "Make a deck"},
                                                  {"role": "assistant", "content": "Done"}], 0))
    asyncio.run(state.touch_meta(mine, "c1", "Make a deck"))
    client.put("/chats/c1", json={"favoritedAt": "2026-11-12T09:00:00Z"}, headers={"X-Workspace": ws_id})
    r = client.post("/chats/c1/team", headers={"X-Workspace": ws_id})
    new = r.json()["id"]
    assert new.startswith("team-") and client.get("/chats/c1", headers={"X-Workspace": ws_id}).status_code == 204
    chat = client.get(f"/chats/{new}", headers={"X-Workspace": ws_id, "X-Test-User": "omar"}).json()
    assert chat["title"] == "Make a deck"
    favs = {c["id"]: c["favoritedAt"] for c in client.get("/chats", headers={"X-Workspace": ws_id}).json()}
    assert favs[new] and not {c["id"]: c["favoritedAt"] for c in client.get("/chats", headers={"X-Workspace": ws_id, "X-Test-User": "omar"}).json()}[new]
    assert [(m["role"], m.get("by", {}).get("id")) for m in chat["messages"]] == [("user", "sara"), ("assistant", None)]
    assert client.post("/chats/c1/team").status_code == 404   # a personal workspace has no team


def test_a_post_runs_nothing_and_the_next_ask_reads_who_wrote_each(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import cycls._agent.web.server as server
    from cycls._agent.web.server import Config
    from tests.agent.web_test import THEME_PATH
    ws_id = _team(tmp_path)
    me = {"user": OMAR}
    monkeypatch.setattr(server, "validator", lambda *a, **k: (lambda: me["user"]))
    seen = []

    async def agent(context):
        s = await state.Session.open(context)
        await s.add_user(context.messages.raw[-1]["content"])
        seen.append(s.context())
        yield "On it"

    client = TestClient(server.web(agent, Config(public_path=THEME_PATH, auth=True, workspaces="member", volume=str(tmp_path))))
    h = {"X-Workspace": ws_id}
    r = client.post("/chat", json={"messages": [{"role": "user", "content": "Nice, I'll check slide 4"}],
                                   "post": True, "team": True}, headers=h)
    chat_id = r.json()["chat_id"]
    assert r.json()["posted"] and chat_id.startswith("team-") and not seen
    me["user"] = SARA
    client.post(f"/chat?id={chat_id}", json={"messages": [{"role": "user", "content": "@Super fix the rent line"}]}, headers=h)
    [context] = seen
    assert len(context) == 1 and context[0]["role"] == "user"   # the two turns, as one
    said = " ".join(b["text"] for b in context[0]["content"])
    assert "[From: Omar Khalid]" in said and "@Super fix the rent line" in said and "[From: Sara Alharbi]" in said
    team = state.chats_of(workspace(SARA, tmp_path, base=f"file://{tmp_path}", ws=ws_id), chat_id)
    turns = asyncio.run(state.load_messages(team, chat_id))
    assert [t.get("by") for t in turns if t["role"] == "user"] == ["omar", "sara"]
    assert [state.user_text(t) for t in turns if t["role"] == "user"] == ["Nice, I'll check slide 4", "@Super fix the rent line"]
    assert asyncio.run(state.get_meta(team, chat_id))["title"] == "Nice, I'll check slide 4"
    # a personal workspace cannot hold one
    assert client.post("/chat?id=team-x", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 404


def test_only_a_team_chats_turns_are_joined():
    a, b = {"role": "user", "content": "one"}, {"role": "user", "content": [{"type": "text", "text": "two"}]}
    result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t"}]}
    assert state._joined([a, b])[0]["content"] == [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}]
    assert len(state._joined([result, a])) == 2
    s = state.Session(None, "c1", [a, b])
    assert len(s.context()) == 2 and len(state.Session(None, "team-1", [a, b]).context()) == 1


def test_a_team_chat_opens_on_its_newest_and_reacts_edits_types_and_knows_what_you_have_not_read(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import cycls._agent.web.server as server
    from cycls._agent import activity
    from cycls._agent.web.server import Config
    from tests.agent.web_test import THEME_PATH
    ws_id = _team(tmp_path)
    activity._people.clear()   # another test's org of the same id
    for u in (SARA, OMAR):
        asyncio.run(activity.put_person(workspace(u, tmp_path, base=f"file://{tmp_path}", ws=ws_id), name=u.name))
    activity._people.clear()
    me = {"user": SARA}
    monkeypatch.setattr(server, "validator", lambda *a, **k: (lambda: me["user"]))

    async def agent(context):
        yield "unused"

    web, routes = TestClient(server.web(agent, Config(public_path=THEME_PATH, auth=True, workspaces="member", volume=str(tmp_path)))), _routers(tmp_path)
    sara, omar = {"X-Workspace": ws_id}, {"X-Workspace": ws_id, "X-Test-User": "omar"}
    def say(text, mid, chat=""):
        return web.post(f"/chat{'?id=' + chat if chat else ''}", headers=sara,
                        json={"messages": [{"role": "user", "content": text, "id": mid}], "post": True, "team": True}).json()["chat_id"]
    row = lambda: next(c for c in routes.get("/chats", headers=sara).json() if c["id"] == chat)
    chat = say("Draft is up", "m-sara-1")
    me["user"] = OMAR
    say("@sara alharbi looks good", "m-omar-1", chat)
    assert row()["unread"] and row()["mention"]
    view = routes.get(f"/chats/{chat}?last=1", headers=sara).json()   # the newest only, and reading it is reading the chat
    assert [m["id"] for m in view["messages"]] == ["m-omar-1"] and view["start"] == 1 and view["messages"][0]["at"]
    assert [m["id"] for m in routes.get(f"/chats/{chat}?last=1&before=1", headers=sara).json()["messages"]] == ["m-sara-1"]
    assert not row()["unread"] and not row()["mention"]
    assert routes.post(f"/chats/{chat}/reactions", json={"id": "m-omar-1", "emoji": "👍"}, headers=sara).json() == {"m-omar-1": {"👍": ["sara"]}}
    assert routes.put(f"/chats/{chat}/messages/m-omar-1", json={"content": "x"}, headers=sara).status_code == 404   # not hers
    assert routes.put(f"/chats/{chat}/messages/m-sara-1", json={"content": "Draft v2 is up"}, headers=sara).status_code == 204
    routes.post(f"/chats/{chat}/typing", headers=sara)
    live = routes.get(f"/chats/{chat}?since=2", headers=omar).json()["live"]   # what changed reaches a chat already open
    assert live["reactions"] == {"m-omar-1": {"👍": ["sara"]}} and live["edits"]["m-sara-1"]["content"] == "Draft v2 is up"
    assert [p["name"] for p in live["typing"]] == ["Sara Alharbi"]
    assert routes.delete(f"/chats/{chat}/messages/m-omar-1", headers=omar).status_code == 204
    said = [(m["content"], bool(m.get("edited")), bool(m.get("deleted"))) for m in routes.get(f"/chats/{chat}", headers=sara).json()["messages"]]
    assert said == [("Draft v2 is up", True, False), ("", False, True)]


def test_a_message_to_the_team_during_someone_elses_run_is_held_shown_and_saved_after_it(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    import cycls._agent.web.server as server
    from cycls._agent import activity
    from cycls._agent.web.server import Config
    from tests.agent.web_test import THEME_PATH
    ws_id = _team(tmp_path)
    activity._people.clear()
    asyncio.run(activity.put_person(workspace(OMAR, tmp_path, base=f"file://{tmp_path}", ws=ws_id), name=OMAR.name))
    activity._people.clear()
    monkeypatch.setattr(server, "validator", lambda *a, **k: (lambda: SARA))

    async def agent(context):
        yield "unused"

    web, routes = TestClient(server.web(agent, Config(public_path=THEME_PATH, auth=True, workspaces="member", volume=str(tmp_path)))), _routers(tmp_path)
    h = {"X-Workspace": ws_id}
    def say(text, mid, chat=""):
        return web.post(f"/chat{'?id=' + chat if chat else ''}", headers=h,
                        json={"messages": [{"role": "user", "content": text, "id": mid}], "post": True, "team": True}).json()
    chat = say("Draft is up", "msg-001")["chat_id"]
    team = state.chats_of(workspace(SARA, tmp_path, base=f"file://{tmp_path}", ws=ws_id), chat)
    now = datetime.now(timezone.utc).isoformat()
    asyncio.run(state.put_run(team, chat, {"run": "r1", "status": "running", "heartbeat": now, "started": now, "user": "omar"}))
    assert say("While you work", "msg-002", chat)["posted"]   # not refused, not queued
    live = routes.get(f"/chats/{chat}?since=1", headers=h).json()["live"]
    assert [m["id"] for m in live["held"]] == ["msg-002"] and live["asker"]["name"] == "Omar Khalid"
    assert [t["id"] for t in asyncio.run(state.load_messages(team, chat))] == ["msg-001"]   # nothing between the run's turns
    asyncio.run(state.put_run(team, chat, {"run": "r1", "status": "done", "heartbeat": now, "started": now, "user": "omar"}))
    say("After", "msg-003", chat)
    assert [t["id"] for t in asyncio.run(state.load_messages(team, chat))] == ["msg-001", "msg-002", "msg-003"]
    assert routes.get(f"/chats/{chat}?since=3", headers=h).json()["live"]["held"] == []


def test_deleting_a_message_puts_its_upload_in_the_trash_and_leaves_a_workspace_file(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import cycls._agent.web.server as server
    from cycls._agent.web.server import Config
    from tests.agent.web_test import THEME_PATH
    ws_id = _team(tmp_path)
    monkeypatch.setattr(server, "validator", lambda *a, **k: (lambda: SARA))

    async def agent(context):
        yield "unused"

    web, routes = TestClient(server.web(agent, Config(public_path=THEME_PATH, auth=True, workspaces="member", volume=str(tmp_path)))), _routers(tmp_path)
    root = workspace(SARA, tmp_path, base=f"file://{tmp_path}", ws=ws_id).root
    for rel in ("attachments/ab12-plan.png", "reports/q3.pdf"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")
    h = {"X-Workspace": ws_id}
    att = lambda rel: {"name": rel.rsplit("/", 1)[1], "type": "image/png", "size": 1, "url": "", "path": rel}
    chat = web.post("/chat", headers=h, json={"post": True, "team": True, "messages": [{"role": "user", "content": "both", "id": "msg-file-1",
                                                                                    "attachments": [att("attachments/ab12-plan.png"), att("reports/q3.pdf")]}]}).json()["chat_id"]
    assert routes.delete(f"/chats/{chat}/messages/msg-file-1", headers=h).status_code == 204
    assert not (root / "attachments/ab12-plan.png").exists() and (root / "reports/q3.pdf").exists()
    assert [r["path"] for r in routes.get("/trash", headers=h).json() if r.get("kind") == "file"] == ["attachments/ab12-plan.png"]


def test_at_the_same_moment_nothing_said_is_lost_or_saved_twice_and_a_quiet_look_lists_nothing(tmp_path, monkeypatch):
    ws_id = _team(tmp_path)
    team = state.chats_of(workspace(SARA, tmp_path, base=f"file://{tmp_path}", ws=ws_id), "team-1")
    sara, omar = {"id": "sara", "name": SARA.name}, {"id": "omar", "name": OMAR.name}
    monkeypatch.setattr(state, "EDITS", 2)

    async def go():
        await asyncio.gather(*(state.hold(team, "team-1", {"content": f"held {i}"}, sara) for i in range(4)))
        await asyncio.gather(state.flush_held(team, "team-1"), state.flush_held(team, "team-1"))
        await state.typing(team, "team-1", "omar")
        await asyncio.gather(*(state.post(team, "team-1", {"content": f"posted {i}"}, {**omar, "turn": f"msg-omar-{i}"}) for i in range(3)))
        said = [state.user_text(t) for t in await state.load_messages(team, "team-1")]
        assert sorted(said) == [*(f"held {i}" for i in range(4)), *(f"posted {i}" for i in range(3))]
        assert await state.typing(team, "team-1") == {}   # their message is in
        await asyncio.gather(*(state.react(team, "team-1", "m1", e, u) for e in ("👍", "✅") for u in ("sara", "omar")))
        assert {e: sorted(ps) for e, ps in (await state.get_live(team, "team-1"))["reactions"]["m1"].items()} == {"👍": ["omar", "sara"], "✅": ["omar", "sara"]}
        for i in range(3):
            await state.rewrite(team, "team-1", f"msg-omar-{i}", omar, f"again {i}")
        assert list((await state.get_live(team, "team-1"))["edits"]) == ["msg-omar-1", "msg-omar-2"]   # the latest; the turns have all
    asyncio.run(go())

    client, h = _routers(tmp_path), {"X-Workspace": ws_id}
    listed = []
    tail = state.load_tail
    monkeypatch.setattr(state, "load_tail", lambda *a: listed.append(a) or tail(*a))
    first = client.get("/chats/team-1?last=60", headers=h).json()
    assert client.get(f"/chats/team-1?since={first['next']}&v={first['v']}", headers=h).json()["messages"] == [] and not listed
    asyncio.run(state.post(team, "team-1", {"content": "one more"}, sara))
    after = client.get(f"/chats/team-1?since={first['next']}&v={first['v']}", headers=h).json()
    assert [m["content"] for m in after["messages"]] == ["one more"] and after["v"] != first["v"]

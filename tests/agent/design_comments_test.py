"""Comments on a design (cycls/_agent/design/comments.py): a pin on a spot of a slide and
the thread under it — kept by the workspace, so everyone it lets in reads and answers
them; the routes; and what happens to them when the design is renamed or deleted."""
import asyncio, json

import pytest

from cycls._app.auth import User
from cycls._agent import trash
from cycls._agent.design import comments

USERS = {
    "user_1": User(id="user_1", org_id="org_1"),
    "user_2": User(id="user_2", org_id="org_1"),
    "outsider": User(id="outsider", org_id="org_2"),
}
SARA, OMAR = {"X-Test-User": "user_1"}, {"X-Test-User": "user_2"}


def _client(tmp_path):
    """The real routers behind a fake auth switched by `X-Test-User` (workspaces_test's
    pattern), so one client is several people."""
    from types import SimpleNamespace
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    from cycls._agent.web.routers import install_routers

    def fake_auth(request: Request):
        return USERS[request.headers.get("x-test-user", "user_1")]

    stub = SimpleNamespace(prod=False, _auth_provider=None,
                           config=SimpleNamespace(workspaces="member", max_upload=512))
    app = FastAPI()
    install_routers(stub, app, Depends(fake_auth), tmp_path, f"file://{tmp_path}")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_refresh(monkeypatch):
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda *a, **k: None)


def _team(client, *members):
    """A team workspace of user_1's, with `members` let in → the headers that name it."""
    ws_id = client.post("/workspaces", json={"name": "Launch"}).json()["id"]
    for m in members:
        assert client.put(f"/workspaces/{ws_id}/members/{m}", json={"role": "editor"}).status_code == 200
    return {"X-Workspace": ws_id}


def _design(client, name="launch", headers=None):
    assert client.put(f"/files/designs/{name}.fig", content=b"FIG", headers=headers or {}).status_code == 200
    return f"/comments/designs/{name}.fig"


def _pin(client, url, text="Make the headline bigger", headers=None, **at):
    body = {"text": text, "frame": 0, "x": 120, "y": 80, "name": "Sara", **at}
    r = client.post(url, json=body, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["thread"]


def _threads(client, url, headers=None):
    return client.get(url, headers=headers or {}).json()["threads"]


# ---- a pin and its thread ----

def test_a_comment_is_pinned_to_a_spot_and_read_back(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    assert client.get(url).json()["threads"] == []
    made = _pin(client, url, page="Story", frame=2, frame_name="cover", x=512.4, y=300)
    [t] = _threads(client, url)
    assert t == made
    assert t["n"] == 1 and t["text"] == "Make the headline bigger"
    assert (t["page"], t["frame"], t["frame_name"], t["x"], t["y"]) == ("Story", 2, "cover", 512.4, 300)
    assert t["author"] == {"id": "user_1", "name": "Sara"}     # who it is comes from the sign-in, not the request
    assert t["resolved"] is False and t["replies"] == [] and t["at"] == t["updated"]
    assert client.get(url).json()["me"] == "user_1"


def test_the_author_is_whoever_is_signed_in(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    t = client.post(url, json={"text": "hi", "frame": 0, "x": 1, "y": 1, "name": "Sara",
                               "author": {"id": "user_2", "name": "Omar"}, "id": "user_2"}).json()["thread"]
    assert t["author"]["id"] == "user_1"
    nameless = client.post(url, json={"text": "hi", "frame": 0, "x": 1, "y": 1}).json()["thread"]
    assert nameless["author"]["name"]                          # never an empty name beside a comment


def test_a_teammate_reads_and_answers_it(tmp_path):
    client = _client(tmp_path)
    ws = _team(client, "user_2")
    sara, omar = {**ws, **SARA}, {**ws, **OMAR}
    url = _design(client, headers=sara)
    t = _pin(client, url, headers=sara)
    [seen] = _threads(client, url, omar)                       # a person's own store would have hidden it
    assert seen["id"] == t["id"] and seen["author"]["id"] == "user_1"
    r = client.post(url, params={"id": t["id"]}, json={"op": "reply", "text": "On it", "name": "Omar"}, headers=omar)
    assert r.status_code == 200, r.text
    [reply] = _threads(client, url, sara)[0]["replies"]
    assert reply["text"] == "On it" and reply["author"] == {"id": "user_2", "name": "Omar"}
    # someone the workspace does not let in sees nothing of it
    assert client.get(url, headers={**ws, "X-Test-User": "outsider"}).status_code == 404


def test_each_workspace_has_its_own(tmp_path):
    client = _client(tmp_path)
    ws = _team(client)
    mine, team = _design(client), _design(client, headers=ws)   # the same name in two workspaces
    _pin(client, mine, "mine")
    assert _threads(client, team, ws) == []
    _pin(client, team, "ours", headers=ws)
    assert [t["text"] for t in _threads(client, mine)] == ["mine"]


def test_resolved_reopened_and_a_reply_reopens(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    t = _pin(client, url)
    op = lambda body: client.post(url, params={"id": t["id"]}, json={"name": "Sara", **body})
    done = op({"op": "resolve"}).json()["thread"]
    assert done["resolved"] is True and done["resolved_by"] == {"id": "user_1", "name": "Sara"} and done["resolved_at"]
    assert op({"op": "reopen"}).json()["thread"]["resolved"] is False
    op({"op": "resolve"})
    again = op({"op": "reply", "text": "Not quite"}).json()["thread"]
    assert again["resolved"] is False and "resolved_by" not in again


def test_only_its_author_changes_or_removes_a_comment(tmp_path):
    client = _client(tmp_path)
    ws = _team(client, "user_2")
    sara, omar = {**ws, **SARA}, {**ws, **OMAR}
    url = _design(client, headers=sara)
    t = _pin(client, url, headers=sara)
    at = {"id": t["id"]}
    reply = client.post(url, params=at, json={"op": "reply", "text": "ok", "name": "Omar"}, headers=omar).json()["thread"]["replies"][0]
    for body in ({"op": "edit", "text": "mine now"}, {"op": "delete"}, {"op": "move", "frame": 1, "x": 5, "y": 5}):
        assert client.post(url, params=at, json=body, headers=omar).status_code == 403, body
    assert client.post(url, params=at, json={"op": "edit", "reply": reply["id"], "text": "x"}, headers=sara).status_code == 403
    # the author may: the words, where it is pinned, a reply of their own
    edited = client.post(url, params=at, json={"op": "edit", "text": "Bigger, please"}, headers=sara).json()["thread"]
    assert edited["text"] == "Bigger, please" and edited["edited"]
    moved = client.post(url, params=at, json={"op": "move", "frame": 1, "frame_name": "agenda", "x": 9, "y": 7}, headers=sara).json()["thread"]
    assert (moved["frame"], moved["frame_name"], moved["x"], moved["y"]) == (1, "agenda", 9, 7)
    theirs = client.post(url, params=at, json={"op": "edit", "reply": reply["id"], "text": "okay"}, headers=omar).json()["thread"]
    assert theirs["replies"][0]["text"] == "okay"
    assert client.post(url, params=at, json={"op": "delete", "reply": reply["id"]}, headers=omar).json()["thread"]["replies"] == []
    assert client.post(url, params=at, json={"op": "delete"}, headers=sara).status_code == 200
    assert _threads(client, url, omar) == []


def test_a_removed_comment_keeps_its_number(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    first, second = _pin(client, url, "one"), _pin(client, url, "two")
    client.post(url, params={"id": first["id"]}, json={"op": "delete"})
    third = _pin(client, url, "three")
    assert [(t["n"], t["text"]) for t in _threads(client, url)] == [(2, "two"), (3, "three")]
    assert second["n"] == 2 and third["n"] == 3
    # …and its words are gone from the store, not just from the answer
    doc, _ = asyncio.run(comments.read(_ws(tmp_path), "designs/launch.fig"))
    assert "one" not in json.dumps(doc)


def test_asking_again_with_the_version_costs_nothing(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    empty = client.get(url).json()
    assert client.get(url, params={"v": empty["version"]}).json() == {"unchanged": True, "version": empty["version"]}
    _pin(client, url)
    now = client.get(url, params={"v": empty["version"]}).json()
    assert len(now["threads"]) == 1 and now["version"] != empty["version"]
    assert client.get(url, params={"v": now["version"]}).json()["unchanged"] is True


def test_comments_are_on_a_design_and_nothing_else(tmp_path):
    client = _client(tmp_path)
    _design(client, "pitch")
    client.put("/files/designs/notes.json", content=b"{}")
    assert client.get("/comments/designs/notes.json").status_code == 404


def test_two_people_writing_at_once_both_land(tmp_path, monkeypatch):
    client = _client(tmp_path)
    url = _design(client)
    ws = _ws(tmp_path)
    store = comments.db(ws)
    real, raced = type(store).put, []

    async def put(self, key, value, **kw):
        if not raced:                                  # someone else's comment lands between this read and its write
            raced.append(1)
            await comments.add(ws, "designs/launch.fig", {"id": "user_2", "name": "Omar"}, "theirs", {"frame": 0, "x": 1, "y": 1})
        return await real(self, key, value, **kw)
    monkeypatch.setattr(type(store), "put", put)
    _pin(client, url, "mine")
    assert sorted(t["text"] for t in _threads(client, url)) == ["mine", "theirs"]
    assert sorted(t["n"] for t in _threads(client, url)) == [1, 2]


# ---- the design renamed, deleted, brought back ----

def test_comments_follow_a_renamed_design(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    t = _pin(client, url)
    assert client.patch("/files/designs/launch.fig", json={"to": "designs/spring.fig"}).status_code == 200
    assert [x["id"] for x in _threads(client, "/comments/designs/spring.fig")] == [t["id"]]
    _design(client)                                    # a new design under the old name starts with none
    assert _threads(client, url) == []


def test_a_deleted_design_takes_its_comments_to_the_trash_and_back(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    t = _pin(client, url)
    tid = client.delete("/files/designs/launch.fig").json()["trash_id"]
    _design(client)                                    # the name is free again: a new design has no pins on it
    assert _threads(client, url) == []
    _pin(client, url, "about the new one")
    restored = client.post(f"/trash/{tid}/restore").json()["path"].replace("\\", "/")
    assert restored != "designs/launch.fig"            # the path was taken: it came back beside it
    assert [x["id"] for x in _threads(client, f"/comments/{restored}")] == [t["id"]]
    assert [x["text"] for x in _threads(client, url)] == ["about the new one"]


def test_a_design_gone_for_good_takes_its_comments(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    _pin(client, url)
    tid = client.delete("/files/designs/launch.fig").json()["trash_id"]
    assert client.delete(f"/trash/{tid}").status_code == 200
    assert not [p for p in (tmp_path / "org_1").rglob("*.json") if comments.SLOT in p.parts]


def test_the_agents_own_rename_and_delete_carry_them_too(tmp_path):
    from cycls._agent.tools import _exec_design
    client = _client(tmp_path)
    url = _design(client)
    t = _pin(client, url)
    ws = _ws(tmp_path)
    asyncio.run(_exec_design({"action": "rename", "name": "launch", "new_name": "spring"}, ws))
    assert [x["id"] for x in _threads(client, "/comments/designs/spring.fig")] == [t["id"]]
    asyncio.run(_exec_design({"action": "delete", "name": "spring"}, ws))
    _design(client, "spring")
    assert _threads(client, "/comments/designs/spring.fig") == []
    [entry] = trash.list_trash(ws.root)
    back = client.post(f"/trash/{entry['id']}/restore").json()["path"].replace("\\", "/")
    assert [x["id"] for x in _threads(client, f"/comments/{back}")] == [t["id"]]


# ---- what is refused ----

def test_the_store_is_managed_by_cycls(tmp_path):
    from cycls._agent.paths import _resolve_path
    client = _client(tmp_path)
    url = _design(client)
    _pin(client, url)
    root = tmp_path / "org_1" / "ws" / "u-user_1"
    [kept] = (root / comments.SLOT).rglob("*.json")    # where the local store keeps it: inside the workspace
    rel = kept.relative_to(root).as_posix()
    assert client.get(f"/files/{rel}").status_code in (400, 403)
    assert client.put(f"/files/{rel}", content=b"{}").status_code in (400, 403)
    assert comments.SLOT not in [e["name"] for e in client.get("/files").json()]
    with pytest.raises(ValueError):
        _resolve_path(rel, root)                       # nor do the agent's file tools reach it


def test_what_is_not_a_comment_is_refused(tmp_path):
    client = _client(tmp_path)
    url = _design(client)
    ok = {"text": "hi", "frame": 0, "x": 1, "y": 1}
    for bad in ({**ok, "text": "   "}, {**ok, "text": "x" * (comments.TEXT_MAX + 1)}, {**ok, "frame": -1},
                {**ok, "frame": "0"}, {**ok, "x": "left"}, {**ok, "y": float("1e9")}, {k: v for k, v in ok.items() if k != "x"}, []):
        assert client.post(url, json=bad).status_code in (400, 422), bad
    assert client.get(url).json()["threads"] == []
    assert client.post("/comments/designs/nope.fig", json=ok).status_code == 404         # no such design
    client.put("/files/notes.md", content=b"# notes")
    assert client.post("/comments/notes.md", json=ok).status_code == 404                 # comments are on designs
    assert client.get("/comments/../../etc/passwd").status_code in (400, 403, 404)
    t = _pin(client, url)
    assert client.post(url, params={"id": "nope"}, json={"op": "reply", "text": "x"}).status_code == 404
    assert client.post(url, params={"id": t["id"]}, json={"op": "shout"}).status_code == 400
    assert client.post(url, params={"id": t["id"]}, json={"op": "reply", "text": ""}).status_code == 400


def test_a_design_holds_only_so_many(tmp_path, monkeypatch):
    monkeypatch.setattr(comments, "THREADS_MAX", 2)
    monkeypatch.setattr(comments, "REPLIES_MAX", 1)
    client = _client(tmp_path)
    url = _design(client)
    t = _pin(client, url, "one")
    _pin(client, url, "two")
    assert client.post(url, json={"text": "three", "frame": 0, "x": 1, "y": 1}).status_code == 409
    reply = lambda: client.post(url, params={"id": t["id"]}, json={"op": "reply", "text": "r"})
    assert reply().status_code == 200 and reply().status_code == 409
    client.post(url, params={"id": t["id"]}, json={"op": "resolve"})
    assert client.post(url, json={"text": "three", "frame": 0, "x": 1, "y": 1}).status_code == 200   # a resolved one makes room


def _ws(tmp_path, user="user_1", ws_id=None):
    from cycls._app.db import workspace
    return workspace(USERS[user], tmp_path, base=f"file://{tmp_path}", ws=ws_id or f"u-{user}")


# ---- the agent ----

FRAMES = [
    {"slide": 1, "name": "cover", "size": [1920, 1080], "nodes": [
        {"name": "bg", "type": "rect", "x": 0, "y": 0, "w": 1920, "h": 1080},
        {"name": "headline", "type": "text", "x": 100, "y": 200, "w": 900, "h": 220, "text": "Design that ships itself"}]},
    {"slide": 2, "name": "agenda", "size": [1920, 1080], "nodes": [
        {"name": "title", "type": "text", "x": 100, "y": 80, "w": 600, "h": 90, "text": "Agenda"}]},
]


def _agent(tmp_path, monkeypatch, frames=FRAMES, pages=None):
    """A design with comments on it, and the Design tool over a stubbed service."""
    from cycls._agent.tools import _exec_design
    pages = pages or [{"name": "Page 1", "frames": len(frames)}]

    async def outline(fig, **kw):
        return {"frames": frames, "pages": pages, "page": kw.get("page") or pages[0]["name"]}
    monkeypatch.setattr("cycls._agent.design.outline", outline)
    client = _client(tmp_path)
    url = _design(client)
    ws = _ws(tmp_path)
    return client, url, lambda **inp: asyncio.run(_exec_design({"name": "launch", **inp}, ws))


def test_inspect_says_what_people_pinned_and_on_what(tmp_path, monkeypatch):
    client, url, design = _agent(tmp_path, monkeypatch)
    assert "omment" not in design(action="inspect")            # none yet: nothing is said
    t = _pin(client, url, "Make the headline bigger", frame=0, frame_name="cover", x=300, y=260)
    _pin(client, url, "Too empty down here", frame=0, frame_name="cover", x=1500, y=900)
    done = _pin(client, url, "typo", frame=1, frame_name="agenda", x=120, y=100)
    client.post(url, params={"id": t["id"]}, json={"op": "reply", "text": "Agreed", "name": "Omar"})
    client.post(url, params={"id": done["id"]}, json={"op": "resolve"})
    text = design(action="inspect")
    assert "2 open comments" in text
    first = next(line for line in text.splitlines() if line.lstrip().startswith("#1 "))
    assert "slide 1" in first and "on headline" in first and 'Sara: "Make the headline bigger"' in first
    assert "1 reply" in first and 'Omar: "Agreed"' in first
    second = next(line for line in text.splitlines() if line.lstrip().startswith("#2 "))
    assert "on bg" in second                                   # nothing else is there: the slide's background
    assert "typo" not in text                                  # a resolved one is done with


def test_a_comment_stays_with_its_slide_when_the_slides_are_reordered(tmp_path, monkeypatch):
    moved = [{**FRAMES[1], "slide": 1}, {**FRAMES[0], "slide": 2}]   # the cover is now slide 2
    client, url, design = _agent(tmp_path, monkeypatch, frames=moved)
    _pin(client, url, "Make the headline bigger", frame=0, frame_name="cover", x=300, y=260)
    line = next(l for l in design(action="inspect").splitlines() if l.lstrip().startswith("#1 "))
    assert "slide 2" in line and "on headline" in line
    assert comments.place({"frame": 0, "frame_name": "cover"}, ["agenda", "cover"]) == 1
    assert comments.place({"frame": 1, "frame_name": "gone"}, ["agenda", "cover"]) is None  # its slide was deleted: not the one in its place
    assert comments.place({"frame": 1}, ["agenda", "cover"]) == 1                           # it names no slide: where it was pinned
    assert comments.place({"frame": 0, "frame_name": "renamed since"}, ["post"]) == 0       # a page of one slide has them all
    assert comments.place({"frame": 0, "frame_name": "slide"}, ["slide", "slide"]) == 0    # a name two slides share says nothing
    assert comments.place({"frame": 2, "frame_name": "slide"}, ["slide", "slide", "other"]) == 2
    assert comments.place({"frame": 5, "frame_name": "gone"}, ["agenda", "cover"]) is None  # its slide is gone


def test_inspect_shows_the_comments_of_the_page_it_shows(tmp_path, monkeypatch):
    pages = [{"name": "Post", "frames": 2}, {"name": "Story", "frames": 2}]
    client, url, design = _agent(tmp_path, monkeypatch, pages=pages)
    _pin(client, url, "on the post", page="Post", frame=0, x=300, y=260)
    _pin(client, url, "on the story", page="Story", frame=0, x=300, y=260)
    assert "on the post" in design(action="inspect") and "on the story" not in design(action="inspect")
    story = design(action="inspect", page="Story")
    assert "on the story" in story and "on the post" not in story


def test_the_agent_reads_answers_and_resolves(tmp_path, monkeypatch):
    client, url, design = _agent(tmp_path, monkeypatch)
    assert "no comments" in design(action="comments")
    t = _pin(client, url, "Make the headline bigger", frame=0, frame_name="cover", x=300, y=260)
    done = _pin(client, url, "typo", frame=1, frame_name="agenda", x=120, y=100)
    client.post(url, params={"id": done["id"]}, json={"op": "resolve"})
    listed = design(action="comments")
    assert '#1' in listed and 'Sara: "Make the headline bigger"' in listed and "slide 1" in listed
    assert "resolved" in listed and "typo" in listed           # here the closed ones are told too
    said = design(action="comments", number=1, reply="Done — the headline is 120px now.", resolve=True)
    assert "Error" not in said and "resolved" in said
    [thread] = [x for x in _threads(client, url) if x["id"] == t["id"]]
    assert thread["resolved"] is True and thread["resolved_by"]["agent"] is True
    [reply] = thread["replies"]
    assert reply["text"] == "Done — the headline is 120px now." and reply["author"]["agent"] is True
    assert design(action="comments", number=1, resolve=False).startswith("Reopened")
    assert _threads(client, url)[0]["resolved"] is False
    assert design(action="comments", number=9, reply="?").startswith("Error")
    assert design(action="comments", number=1).startswith("Error")       # a number with nothing to do to it
    assert design(action="comments", name="nope").startswith("Error")


def test_a_design_with_no_store_to_reach_has_no_comments(tmp_path, monkeypatch):
    """The tool is also run on a bare workspace (tests, a local script): it says so, and
    `inspect` goes on without them."""
    from types import SimpleNamespace
    from cycls._agent.tools import _exec_design

    async def outline(fig, **kw):
        return {"frames": FRAMES, "pages": [{"name": "Page 1", "frames": 2}], "page": "Page 1"}
    monkeypatch.setattr("cycls._agent.design.outline", outline)
    (tmp_path / "designs").mkdir()
    (tmp_path / "designs/launch.fig").write_bytes(b"FIG")
    bare = SimpleNamespace(root=tmp_path, subject="org_1:user_1")
    assert "slide 1" in asyncio.run(_exec_design({"action": "inspect", "name": "launch"}, bare))
    assert "Error" in asyncio.run(_exec_design({"action": "comments", "name": "launch"}, bare))

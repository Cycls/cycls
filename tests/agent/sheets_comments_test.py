"""Comments on a workbook's cells (docs/notes/office.md, "Comments"): kept in the workspace's `.comments` shelf like a
design's, pinned to a sheet and a cell; the routes; anyone's edit moves a comment with its cell; the agent's
`sheets` tool lists, answers and resolves them, read shows the open ones, and its row and column edits move them."""
import asyncio

import pytest

from cycls._agent import trash
from cycls._agent.design import comments
from tests.agent.design_comments_test import OMAR, SARA, _client, _threads, _ws


def _workbook(client, name="budget", headers=None):
    assert client.put(f"/files/reports/{name}.xlsx", content=b"PK\x03\x04", headers=headers or {}).status_code == 200
    return f"/comments/reports/{name}.xlsx"


def _on_cell(client, url, text="Check this total", headers=None, **at):
    body = {"text": text, "sheet": "s1", "sheet_name": "الميزانية", "cell": "B5", "name": "Sara", **at}
    r = client.post(url, json=body, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()["thread"]


# ---- the store ----

def test_a_cell_is_where_a_workbook_comment_is():
    assert comments.kind_of("a/b.xlsx") == "sheet" and comments.kind_of("deck.fig") == "design"
    assert comments.commentable("x.XLSM") and comments.commentable("d.fig") and not comments.commentable("n.json")
    assert comments._sheet_spot({"sheet": "s2", "cell": "$c$12", "sheet_name": "Sales"}) == {"sheet": "s2", "cell": "C12", "sheet_name": "Sales"}
    assert comments.cell_at("XFD1048576") == (1048575, 16383) and comments.cell_at("XFE1") is None and comments.cell_at("A0") is None
    for bad in ({"cell": "B5"}, {"sheet": "s1"}, {"sheet": "s1", "cell": "5B"}, {"sheet": "../x", "cell": "A1"}):
        with pytest.raises(comments.Refused):
            comments._sheet_spot(bad)
    assert comments._sheet_spot({"sheet": "s1", "cell": None}, gone_ok=True) == {"sheet": "s1", "cell": None}


def test_rows_and_columns_inserted_or_removed_move_comments():
    threads = [{"sheet": "s1", "cell": "B5"}, {"sheet": "s1", "cell": "D2"}, {"sheet": "s2", "cell": "B5"}, {"sheet": "s1", "cell": None}]
    assert comments.shift_threads(threads, [{"kind": "insert-rows", "sheetId": "s1", "start": 3, "count": 2}])
    assert [t["cell"] for t in threads] == ["B7", "D2", "B5", None]           # below the insert: down; above, other sheet: stay
    comments.shift_threads(threads, [{"kind": "remove-cols", "sheetId": "s1", "start": 1, "count": 1}])
    assert [t["cell"] for t in threads] == [None, "C2", "B5", None]            # its column removed: on no cell
    comments.shift_threads(threads, [{"kind": "insert-cols", "sheetId": "s1", "start": 0, "count": 1, "band": [5, 9]}])
    assert threads[1]["cell"] == "C2"                                           # cells shifted in rows 6–10 only
    assert not comments.shift_threads(threads, [{"kind": "remove-rows", "sheetId": "s9", "start": 0, "count": 3}])


# ---- the routes ----

def test_a_comment_on_a_cell_is_kept_and_read_back(tmp_path):
    client = _client(tmp_path)
    url = _workbook(client)
    made = _on_cell(client, url)
    [t] = _threads(client, url)
    assert t == made and t["n"] == 1
    assert (t["sheet"], t["sheet_name"], t["cell"]) == ("s1", "الميزانية", "B5")
    assert "frame" not in t and t["author"] == {"id": "user_1", "name": "Sara"}
    assert client.post(url, json={"text": "no cell", "sheet": "s1"}).status_code == 400
    assert client.post(url, json={"text": "a slide's spot", "frame": 0, "x": 1, "y": 1}).status_code == 400


def test_anyone_moves_a_cell_s_comment_but_only_its_author_changes_the_words(tmp_path):
    client = _client(tmp_path)
    from tests.agent.design_comments_test import _team
    team = _team(client, "user_2")
    url = _workbook(client, headers=team)
    t = _on_cell(client, url, headers=team)
    moved = client.post(url, params={"id": t["id"]}, json={"op": "move", "sheet": "s1", "cell": "B7", "sheet_name": "الميزانية"}, headers={**team, **OMAR})
    assert moved.status_code == 200 and moved.json()["thread"]["cell"] == "B7"
    gone = client.post(url, params={"id": t["id"]}, json={"op": "move", "sheet": "s1", "cell": None}, headers={**team, **OMAR})
    assert gone.json()["thread"]["cell"] is None
    assert client.post(url, params={"id": t["id"]}, json={"op": "edit", "text": "mine now"}, headers={**team, **OMAR}).status_code == 403
    assert client.post(url, params={"id": t["id"]}, json={"op": "reply", "text": "Fixed it"}, headers={**team, **OMAR}).status_code == 200


def test_comments_follow_a_renamed_workbook(tmp_path):
    client = _client(tmp_path)
    url = _workbook(client)
    t = _on_cell(client, url)
    assert client.patch("/files/reports/budget.xlsx", json={"to": "reports/2027.xlsx"}).status_code == 200
    assert [x["id"] for x in _threads(client, "/comments/reports/2027.xlsx")] == [t["id"]]
    _workbook(client)                                  # a new workbook under the old name starts with none
    assert _threads(client, url) == []


def test_a_workbook_s_comments_go_to_the_trash_and_back(tmp_path):
    client = _client(tmp_path)
    url = _workbook(client)
    t = _on_cell(client, url)
    assert client.delete("/files/reports/budget.xlsx").status_code == 200
    _workbook(client)
    assert _threads(client, url) == []                                         # a new file of that name has none
    ws = _ws(tmp_path)
    [entry] = [e for e in trash.list_trash(ws.root) if e["path"].replace("\\", "/") == "reports/budget.xlsx"]
    client.delete("/files/reports/budget.xlsx")
    back = client.post(f"/trash/{entry['id']}/restore").json()["path"].replace("\\", "/")
    assert [x["id"] for x in _threads(client, f"/comments/{back}")] == [t["id"]]


# ---- the agent ----

def _sheets(tmp_path, monkeypatch):
    from cycls._agent.office import client as office
    from cycls._agent.office.sheets import exec_sheets
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("SHEETS_ORGS", "*")
    client = _client(tmp_path)
    url = _workbook(client)
    ws = _ws(tmp_path)
    calls = {}

    async def sheets_read(data, name, target=None, raw=False):
        return f"{name} — 1 sheet"

    async def sheets_apply(data, name, edits, create=None):
        calls["edits"] = edits
        return {"unchanged": False, "bytes": b"PK\x03\x04 new", "mutations": [], "report": "done",
                "ops": [{"kind": "insert-rows", "sheetId": "s1", "start": 0, "count": 2}]}

    monkeypatch.setattr(office, "sheets_read", sheets_read)
    monkeypatch.setattr(office, "sheets_apply", sheets_apply)
    run = lambda **inp: asyncio.run(exec_sheets({"path": "reports/budget.xlsx", "ops": [], **inp}, ws))
    return client, url, run


def test_the_agent_reads_answers_and_resolves_comments_on_cells(tmp_path, monkeypatch):
    client, url, sheets = _sheets(tmp_path, monkeypatch)
    assert "No one has commented" in sheets(action="comments")
    t = _on_cell(client, url, "Is this the final number?")
    done = _on_cell(client, url, "typo", cell="A2")
    client.post(url, params={"id": done["id"]}, json={"op": "resolve"})
    read = sheets(action="read")
    assert 'Open comments:\n  #1 الميزانية!B5 — Sara: "Is this the final number?"' in read and "typo" not in read
    listed = sheets(action="comments")
    assert "1 open, 1 resolved" in listed and "typo" in listed
    said = sheets(action="comments", number=1, reply="Yes — 245,000 is final.", resolve=True)
    assert "Error" not in said and "resolved" in said
    [thread] = [x for x in _threads(client, url) if x["id"] == t["id"]]
    assert thread["resolved"] is True and thread["replies"][0]["author"]["agent"] is True
    assert sheets(action="comments", number=7, reply="?").startswith("Error")
    assert sheets(action="comments", reply="x").startswith("Error")             # a reply needs its number


def test_the_agent_s_inserted_rows_move_the_comments(tmp_path, monkeypatch):
    client, url, sheets = _sheets(tmp_path, monkeypatch)
    t = _on_cell(client, url)
    out = sheets(action="edit", ops=[{"op": "insert_rows", "target": "1", "count": 2}])
    assert isinstance(out, dict) and "Edited" in out["_model"]
    [thread] = [x for x in _threads(client, url) if x["id"] == t["id"]]
    assert thread["cell"] == "B7"

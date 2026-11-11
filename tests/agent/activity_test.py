"""Who made and changed each file, and an org's audit log (cycls/_agent/activity.py, docs/rfc-file-metadata.md)."""
import asyncio, os, time

import pytest

from cycls._app.db import workspace
from cycls._agent import activity, state
from cycls._agent.paths import _resolve_path


def _ws(tmp_path, subject="org_1:u_sara", ws="t-team"):
    w = workspace(subject, tmp_path, base=f"file://{tmp_path}", ws=ws)
    os.makedirs(w.root, exist_ok=True)
    return w


def _write(w, rel, text="x"):
    p = w.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _listing(w, rel_dir=""):
    entries = []
    for e in os.scandir(w.root / rel_dir if rel_dir else w.root):
        if e.name.startswith("."): continue
        st = e.stat()
        entries.append({"name": e.name, "type": "directory" if e.is_dir() else "file", "size": 0 if e.is_dir() else st.st_size,
                        "modified": activity.datetime.fromtimestamp(st.st_mtime, activity.timezone.utc).isoformat()})
    return asyncio.run(activity.folder(w, rel_dir, entries))


def test_a_change_shows_on_the_file_with_the_person_and_their_face(tmp_path):
    w = _ws(tmp_path)
    asyncio.run(activity.put_person(w, "Sara Alharbi", "https://img.example/sara.png"))
    _write(w, "plan.docx")
    asyncio.run(activity.record(w, "plan.docx", activity.change(w, "uploaded")))
    [e] = _listing(w)
    assert e["created"]["by"] == e["edited"]["by"] == {"id": "u_sara", "name": "Sara Alharbi",
                                                          "image": "https://img.example/sara.png", "you": True}
    assert e["edited"]["action"] == "uploaded"


def test_a_change_made_outside_drops_the_name_but_keeps_the_history(tmp_path):
    w = _ws(tmp_path)
    _write(w, "notes.md")
    asyncio.run(activity.record(w, "notes.md", activity.change(w, "uploaded")))
    time.sleep(0.01)
    _write(w, "notes.md", "changed by a script, bigger")
    [e] = _listing(w)
    assert "edited" not in e and e["created"]["action"] == "uploaded"
    got = asyncio.run(activity.info(w, "notes.md"))
    assert got["edited"] is None and len(got["activity"]) == 1


def test_an_agents_change_belongs_to_the_person_and_names_the_chat(tmp_path):
    w = _ws(tmp_path)
    _write(w, "deck.fig")
    asyncio.run(activity.record(w, "deck.fig", activity.change(w, "created", agent="super", chat="c1", title="Café plan")))
    [e] = _listing(w)
    assert e["created"]["by"]["id"] == "u_sara" and e["created"]["agent"] == "super"
    assert e["created"]["chat"] == {"id": "c1", "title": "Café plan"}


def test_saves_in_a_row_are_one_edit(tmp_path):
    w = _ws(tmp_path)
    _write(w, "a.md")
    for _ in range(3):
        asyncio.run(activity.record(w, "a.md", activity.change(w, "edited")))
    assert [c["action"] for c in asyncio.run(activity.info(w, "a.md"))["activity"]] == ["edited"]


def test_a_rename_and_a_delete_carry_the_history(tmp_path):
    w = _ws(tmp_path)
    _write(w, "old.md")
    asyncio.run(activity.record(w, "old.md", activity.change(w, "uploaded")))
    os.rename(w.root / "old.md", w.root / "new.md")
    asyncio.run(activity.moved(w, "old.md", "new.md", activity.change(w, "renamed", frm="old.md")))
    got = asyncio.run(activity.info(w, "new.md"))
    assert [c["action"] for c in got["activity"]] == ["renamed", "uploaded"] and got["activity"][0]["from"] == "old.md"
    asyncio.run(activity.trashed(w, "new.md", "t1", activity.change(w, "deleted")))
    assert asyncio.run(activity.info(w, "new.md")) == {"activity": []}
    asyncio.run(activity.restored(w, "t1", "new.md", activity.change(w, "restored")))
    assert [c["action"] for c in asyncio.run(activity.info(w, "new.md"))["activity"]] == ["restored", "renamed", "uploaded"]


def test_after_a_run_every_file_it_changed_is_its_change(tmp_path):
    w = _ws(tmp_path)
    _write(w, "kept.md")
    _write(w, "edited.md")
    _write(w, "theirs.md")
    before = activity.names(w.root)
    since = activity._now()
    time.sleep(0.01)
    _write(w, "made.docx")                      # bash made it
    _write(w, "edited.md", "changed by the run")
    asyncio.run(activity.record(w, "theirs.md", activity.change(w, "edited")))   # someone else, recorded meanwhile
    os.utime(w.root / "kept.md", (time.time() - 3600, time.time() - 3600))
    asyncio.run(activity.after_run(w, before, since, None, "super"))
    made = asyncio.run(activity.info(w, "made.docx"))["created"]
    assert made["action"] == "created" and made["agent"] == "super"
    assert asyncio.run(activity.info(w, "edited.md"))["edited"]["action"] == "edited"
    assert [c.get("agent") for c in asyncio.run(activity.info(w, "theirs.md"))["activity"]] == [None]
    assert asyncio.run(activity.info(w, "kept.md")) == {"activity": []}


def test_the_audit_log_keeps_team_workspaces_newest_first_and_pages(tmp_path):
    team, mine = _ws(tmp_path), _ws(tmp_path, ws="u-u_sara")
    for i in range(3):
        _write(team, f"f{i}.md")
        asyncio.run(activity.record(team, f"f{i}.md", activity.change(team, "uploaded")))
        time.sleep(0.002)
    _write(mine, "private.md")
    asyncio.run(activity.record(mine, "private.md", activity.change(mine, "uploaded")))   # personal: stays out
    orgdb = state.org_db("org_1", tmp_path, f"file://{tmp_path}")
    first, nxt = asyncio.run(activity.audit_page(orgdb, team, limit=2))
    rest, end = asyncio.run(activity.audit_page(orgdb, team, after=nxt, limit=2))
    assert [e["target"] for e in first + rest] == ["f2.md", "f1.md", "f0.md"] and end is None


def test_a_solo_account_keeps_no_audit_log(tmp_path):
    w = _ws(tmp_path, subject="u_solo", ws="t-team")
    _write(w, "a.md")
    asyncio.run(activity.record(w, "a.md", activity.change(w, "uploaded")))
    assert asyncio.run(state.org_db("u_solo", tmp_path, f"file://{tmp_path}").keys(prefix="audit/")) == []


def test_the_agent_reading_a_team_file_is_told_who_last_edited_it(tmp_path):
    w = _ws(tmp_path)
    asyncio.run(activity.put_person(w, "Sara Alharbi"))
    _write(w, "budget.xlsx")
    asyncio.run(activity.record(w, "budget.xlsx", activity.change(w, "edited", agent="super", chat="c1", title="Café plan")))
    note = asyncio.run(activity.note(w, "budget.xlsx"))
    assert note.startswith("[Last edited by Sara Alharbi on ") and "via super in “Café plan”" in note
    assert asyncio.run(activity.note(_ws(tmp_path, ws="u-u_sara"), "budget.xlsx")) == ""


@pytest.mark.parametrize("slot", [".files", ".org"])
def test_no_tool_reaches_the_records_or_the_log(tmp_path, slot):
    with pytest.raises(ValueError, match="managed by cycls"):
        _resolve_path(f"{slot}/budget.xlsx", tmp_path)


def _files_app(tmp_path, role="admin"):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls._app.auth import User
    from cycls._agent.web.routers import files_router
    import cycls

    @cycls.app(image={"volume": str(tmp_path)})
    def svc():
        return None

    user = User(id="u_sara", org_id="org_1", org_role=role, name="Sara Alharbi")
    w = _ws(tmp_path)
    fapp = FastAPI()
    fapp.include_router(files_router(svc, Depends(lambda: w), Depends(lambda: user), tmp_path, f"file://{tmp_path}"))
    return TestClient(fapp)


def test_the_routes_record_a_persons_changes_and_admins_read_the_log(tmp_path):
    client = _files_app(tmp_path)
    assert client.put("/people/me", json={"image": "https://img.example/sara.png"}).status_code == 200
    assert client.put("/files/plan.md", content=b"hello").status_code == 200
    assert client.patch("/files/plan.md", json={"to": "drafts/plan.md"}).status_code == 200
    [e] = [e for e in client.get("/files?path=drafts").json() if e["name"] == "plan.md"]
    assert e["edited"]["action"] == "moved" and e["edited"]["by"]["name"] == "Sara Alharbi"
    info = client.get("/files-info/drafts/plan.md").json()
    assert [c["action"] for c in info["activity"]] == ["moved", "uploaded"]
    log = client.get("/audit").json()
    assert [r["action"] for r in log["events"]] == ["moved", "uploaded"] and log["next"] is None
    csv = client.get("/audit.csv").text.splitlines()
    assert csv[0].startswith("time,person") and len(csv) == 4 and ",audit_exported," in csv[1]   # an export is logged too


def test_only_org_admins_read_the_audit_log(tmp_path):
    client = _files_app(tmp_path, role="member")
    assert client.get("/audit").status_code == 403 and client.get("/audit.csv").status_code == 403


def test_a_run_that_called_tools_records_the_files_it_made(tmp_path):
    """Its steps reach the run through the encoder; as it ends, each file it made is its person's, via the agent."""
    from cycls._agent.web.server import Run, _supervise, encoder
    w = _ws(tmp_path)

    async def go():
        async def agent():
            yield {"type": "step", "id": "s1", "tool_name": "Bash", "step": "make it"}
            await asyncio.sleep(0.2)   # the run's names walk reads the folder before
            (w.root / "made.md").write_text("x")
            yield {"type": "text", "text": "done"}
        runs, key = {}, ("ws", "c1")
        run = Run(detach=True, workspace=w, chat_id="c1", user=None, agent="super")
        runs[key] = run
        run.task = asyncio.create_task(_supervise(run, encoder(agent(), chat_id="c1", run=run), runs, key, None))
        await asyncio.wait({run.task}, timeout=5)
        return await activity.info(w, "made.md")

    made = asyncio.run(go())["created"]
    assert made["action"] == "created" and made["agent"] == "super" and made["by"]["id"] == "u_sara"


def test_audit_rows_go_after_180_days_and_never_carry_a_chats_title(tmp_path):
    w = _ws(tmp_path)
    orgdb = state.org_db("org_1", tmp_path, f"file://{tmp_path}")
    old = f"audit/{10 ** 13 - int((time.time() - 181 * 86400) * 1000):013d}-aaaaaa"
    asyncio.run(orgdb.put(old, {"action": "uploaded"}))
    activity._swept.clear()
    _write(w, "a.md")
    asyncio.run(activity.record(w, "a.md", activity.change(w, "edited", agent="super", chat="c1", title="Salary talk")))
    keys = asyncio.run(orgdb.keys(prefix="audit/"))
    assert old not in keys and len(keys) == 1
    assert "title" not in asyncio.run(orgdb.get(keys[0]))


def test_a_teammate_sees_the_agent_but_never_anothers_chat(tmp_path):
    sara, omar = _ws(tmp_path), _ws(tmp_path, subject="org_1:u_omar")
    _write(sara, "plan.md")
    asyncio.run(activity.record(sara, "plan.md", activity.change(sara, "created", agent="super", chat="c1", title="Salary talk")))
    mine, theirs = asyncio.run(activity.info(sara, "plan.md"))["created"], asyncio.run(activity.info(omar, "plan.md"))["created"]
    assert mine["chat"]["title"] == "Salary talk"
    assert theirs["agent"] == "super" and "chat" not in theirs


def test_a_run_leaves_builds_out_counts_an_app_once_and_sums_up_past_its_cap(tmp_path, monkeypatch):
    w = _ws(tmp_path)
    monkeypatch.setattr(activity, "RUN_MOST", 2)
    since = activity._now()
    time.sleep(0.01)
    for rel in ("node_modules/x/index.js", "apps/tips/index.html", "apps/tips/app.json", "a.md", "b.md", "c.md", "d.md"):
        _write(w, rel)
    asyncio.run(activity.after_run(w, set(), since, None, "super"))
    rows = asyncio.run(activity.audit_page(state.org_db("org_1", tmp_path, f"file://{tmp_path}"), w))[0]
    assert sorted(r["action"] for r in rows) == ["app_published", "created", "created", "files_changed"]
    assert next(r for r in rows if r["action"] == "files_changed")["count"] == "2"
    assert asyncio.run(activity.info(w, "node_modules/x/index.js")) == {"activity": []}


def test_a_connector_action_is_logged_without_its_arguments(tmp_path):
    from types import SimpleNamespace
    w = _ws(tmp_path)
    activity.ORIGIN.set({"ip": "203.0.113.4", "client": "web", "agent": "super", "chat": "c1"})
    asyncio.run(activity.acted(SimpleNamespace(workspace=w), "gmail_send", "gmail", "auto"))
    [row] = asyncio.run(activity.audit_page(state.org_db("org_1", tmp_path, f"file://{tmp_path}"), w))[0]
    assert (row["action"], row["target"], row["connector"], row["how"], row["agent"], row["ip"], row["client"]) == \
        ("connector_action", "gmail_send", "gmail", "auto", "super", "203.0.113.4", "web")
    activity.ORIGIN.set({})


def test_downloads_are_logged_and_previews_are_not(tmp_path):
    client = _files_app(tmp_path)
    client.put("/files/plan.md", content=b"hello")
    client.get("/files/plan.md")
    client.get("/files/plan.md?download=1")
    assert [r["action"] for r in client.get("/audit").json()["events"]] == ["downloaded", "uploaded"]


def test_where_a_request_came_from():
    assert activity.origin_of({"user-agent": "Mozilla/5.0", "x-forwarded-for": "203.0.113.4, 10.0.0.1"}) == \
        {"ip": "203.0.113.4", "client": "web"}
    assert activity.origin_of({"user-agent": "Cycls/28 CFNetwork/1568 Darwin/24.0"})["client"] == "ios"
    assert activity.origin_of({"user-agent": "okhttp/4.12.0"})["client"] == "android"
    assert activity.origin_of({"user-agent": "python-requests/2.32"})["client"] == "api"

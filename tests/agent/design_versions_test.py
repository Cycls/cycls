"""A design's saves don't overwrite what they didn't see, and its earlier versions are
kept (cycls/_agent/design/store.py, cycls/_agent/versions.py): the write helper, the
files and version routes, and the agent's edits on top of them."""
import asyncio
from types import SimpleNamespace

import pytest

from cycls._agent import trash, versions
from cycls._agent.design.store import Stale, version_of, write_fig


def _client(tmp_path):
    """The real state routers behind a stub app and a fixed user (web_test's pattern)."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls._app.auth import User
    from cycls._agent.web.routers import install_routers
    user = User(id="user_1", org_id="org_1")
    stub = SimpleNamespace(prod=False, _auth_provider=None, config=SimpleNamespace(workspaces="member", max_upload=512))
    app = FastAPI()
    install_routers(stub, app, Depends(lambda: user), tmp_path, f"file://{tmp_path}")
    return TestClient(app), tmp_path / "org_1" / "ws" / "u-user_1"


@pytest.fixture(autouse=True)
def _no_refresh(monkeypatch):
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda *a, **k: None)
    versions._last.clear()


def _put(root, rel, data):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)


# ---- the write helper ----

def test_a_write_from_an_old_version_is_refused_and_nothing_changes(tmp_path):
    _put(tmp_path, "designs/a.fig", b"MINE")
    with pytest.raises(Stale) as e:
        asyncio.run(write_fig(tmp_path, "designs/a.fig", b"THEIRS", base=version_of(b"OLDER")))
    assert e.value.current == version_of(b"MINE")
    assert (tmp_path / "designs/a.fig").read_bytes() == b"MINE"


def test_a_current_write_lands_and_keeps_what_it_replaced(tmp_path):
    _put(tmp_path, "designs/a.fig", b"ONE")
    v = asyncio.run(write_fig(tmp_path, "designs/a.fig", b"TWO", base=version_of(b"ONE")))
    assert v == version_of(b"TWO") and (tmp_path / "designs/a.fig").read_bytes() == b"TWO"
    [kept] = versions.listing(tmp_path, "designs/a.fig")
    assert kept["reason"] == "save" and versions.read(tmp_path, "designs/a.fig", kept["id"]) == b"ONE"
    assert not list((tmp_path / ".tmp").iterdir())   # no temp file left behind


def test_autosaves_keep_one_version_per_five_minutes_an_agent_edit_always(tmp_path):
    _put(tmp_path, "designs/a.fig", b"V0")
    for i in range(1, 4):   # an editing session's autosaves
        asyncio.run(write_fig(tmp_path, "designs/a.fig", f"V{i}".encode()))
    assert [versions.read(tmp_path, "designs/a.fig", e["id"]) for e in versions.listing(tmp_path, "designs/a.fig")] == [b"V0"]
    asyncio.run(write_fig(tmp_path, "designs/a.fig", b"AGENT", by="agent", reason="agent", intent="move slide 4"))
    newest = versions.listing(tmp_path, "designs/a.fig")[0]
    assert newest["by"] == "agent" and newest["intent"] == "move slide 4"
    assert versions.read(tmp_path, "designs/a.fig", newest["id"]) == b"V3"


def test_keep_mine_writes_over_a_newer_file_and_keeps_it(tmp_path):
    _put(tmp_path, "designs/a.fig", b"THEIRS")
    asyncio.run(write_fig(tmp_path, "designs/a.fig", b"MINE", base=version_of(b"OLD"), reason="keep", force=True))
    assert (tmp_path / "designs/a.fig").read_bytes() == b"MINE"
    assert versions.read(tmp_path, "designs/a.fig", versions.listing(tmp_path, "designs/a.fig")[0]["id"]) == b"THEIRS"


def test_old_versions_go(tmp_path, monkeypatch):
    monkeypatch.setattr(versions, "KEEP", 3)
    _put(tmp_path, "designs/a.fig", b"V0")
    for i in range(1, 6):
        asyncio.run(write_fig(tmp_path, "designs/a.fig", f"V{i}".encode(), reason="agent"))
    kept = versions.listing(tmp_path, "designs/a.fig")
    assert [versions.read(tmp_path, "designs/a.fig", e["id"]) for e in kept] == [b"V4", b"V3", b"V2"]
    assert len([p for p in (tmp_path / ".versions/designs/a.fig").iterdir() if p.name != "index.json"]) == 3


# ---- routes ----

def test_a_design_is_served_with_its_version_and_saved_against_it(tmp_path):
    client, root = _client(tmp_path)
    _put(root, "designs/a.fig", b"ONE")
    got = client.get("/files/designs/a.fig")
    assert got.content == b"ONE" and got.headers["x-version"] == version_of(b"ONE")
    ok = client.put(f"/files/designs/a.fig?base={version_of(b'ONE')}", content=b"TWO")
    assert ok.status_code == 200 and ok.json()["version"] == version_of(b"TWO")
    stale = client.put(f"/files/designs/a.fig?base={version_of(b'ONE')}", content=b"THREE")
    assert stale.status_code == 412
    assert stale.json() == {"detail": "This design changed since it was opened.", "version": version_of(b"TWO")}
    assert (root / "designs/a.fig").read_bytes() == b"TWO"
    forced = client.put(f"/files/designs/a.fig?base={version_of(b'ONE')}&force=1", content=b"THREE")
    assert forced.status_code == 200 and (root / "designs/a.fig").read_bytes() == b"THREE"
    assert client.put("/files/designs/a.fig", content=b"FOUR").status_code == 200   # no base: as before


def test_versions_list_fetch_and_restore(tmp_path):
    client, root = _client(tmp_path)
    _put(root, "designs/a.fig", b"FIRST")
    client.put("/files/designs/a.fig", content=b"SECOND")
    [v] = client.get("/versions/designs/a.fig").json()["versions"]
    assert v["reason"] == "save" and v["size"] == 5
    assert client.get(f"/versions/designs/a.fig?id={v['id']}").content == b"FIRST"
    r = client.post(f"/versions/designs/a.fig?restore={v['id']}")
    assert r.json() == {"ok": True, "version": version_of(b"FIRST")}
    assert (root / "designs/a.fig").read_bytes() == b"FIRST"
    newest = client.get("/versions/designs/a.fig").json()["versions"][0]
    assert newest["reason"] == "restore"            # what the restore replaced is kept: undo by restoring
    assert client.get(f"/versions/designs/a.fig?id={newest['id']}").content == b"SECOND"
    assert client.get("/versions/designs/a.fig?id=../../x").status_code == 404
    assert client.post("/versions/designs/a.fig?restore=nope").status_code == 404


def test_versions_are_managed_by_cycls(tmp_path):
    client, root = _client(tmp_path)
    _put(root, "designs/a.fig", b"FIRST")
    client.put("/files/designs/a.fig", content=b"SECOND")
    assert client.get("/files/.versions/designs/a.fig/index.json").status_code in (400, 403)
    assert client.put("/files/.versions/designs/a.fig/x", content=b"X").status_code in (400, 403)
    assert ".versions" not in [e["name"] for e in client.get("/files").json()]


def test_a_rename_carries_the_history_and_a_purge_ends_it(tmp_path):
    client, root = _client(tmp_path)
    _put(root, "designs/a.fig", b"FIRST")
    client.put("/files/designs/a.fig", content=b"SECOND")
    assert client.patch("/files/designs/a.fig", json={"to": "designs/b.fig"}).status_code == 200
    assert len(client.get("/versions/designs/b.fig").json()["versions"]) == 1
    tid = client.delete("/files/designs/b.fig").json()["trash_id"]
    assert len(client.get("/versions/designs/b.fig").json()["versions"]) == 1   # in the trash: kept
    trash.purge(root, tid)
    assert client.get("/versions/designs/b.fig").json()["versions"] == []


def test_a_rename_carries_the_history_where_a_directory_cannot_be_renamed(tmp_path, monkeypatch):
    """The gcsfuse workspace mount refuses to rename a directory (EMFILE, "Too many open
    files") — and a design's history is one. It is copied across instead."""
    import errno, os
    from pathlib import Path
    client, root = _client(tmp_path)
    _put(root, "designs/a.fig", b"FIRST")
    client.put("/files/designs/a.fig", content=b"SECOND")

    def refusing(real):
        def rename(src, dst, *a, **k):
            if os.path.isdir(src):
                raise OSError(errno.EMFILE, "Too many open files", str(src))
            return real(src, dst, *a, **k)
        return rename
    monkeypatch.setattr(os, "rename", refusing(os.rename))
    monkeypatch.setattr(Path, "replace", lambda self, target, _real=Path.replace: refusing(_real)(self, target))

    assert client.patch("/files/designs/a.fig", json={"to": "designs/b.fig"}).status_code == 200
    [v] = client.get("/versions/designs/b.fig").json()["versions"]
    assert client.get(f"/versions/designs/b.fig?id={v['id']}").content == b"FIRST"
    assert not (root / ".versions/designs/a.fig").exists()


def test_a_rename_succeeds_even_when_its_history_cannot_follow(tmp_path, monkeypatch):
    client, root = _client(tmp_path)
    _put(root, "designs/a.fig", b"FIRST")
    client.put("/files/designs/a.fig", content=b"SECOND")

    def broken(*a):
        raise OSError(5, "Input/output error")
    monkeypatch.setattr(versions, "move", broken)
    assert client.patch("/files/designs/a.fig", json={"to": "designs/b.fig"}).status_code == 200
    assert (root / "designs/b.fig").read_bytes() == b"SECOND"


# ---- the agent's edits ----

def test_an_agent_edit_applies_to_a_save_made_while_it_ran(tmp_path, monkeypatch):
    from cycls._agent.tools import _exec_design
    _put(tmp_path, "designs/launch.fig", b"ORIGINAL")
    seen = []

    async def apply(fig, script=None, ops=None, **kw):
        seen.append(fig)
        if len(seen) == 1:   # the person saves in the editor while the service works
            (tmp_path / "designs/launch.fig").write_bytes(b"PERSON")
        return {"fig": fig + b"+AGENT", "lint": [], "script": "S", "preview": None, "previews": [], "touched": [], "slides": []}
    monkeypatch.setattr("cycls._agent.design.apply", apply)
    ws = SimpleNamespace(root=tmp_path, subject="org_1:user_1")
    out = asyncio.run(_exec_design({"action": "edit", "name": "launch", "script": "x", "intent": "tidy"}, ws))
    assert seen == [b"ORIGINAL", b"PERSON"]                          # applied again, to the save
    assert (tmp_path / "designs/launch.fig").read_bytes() == b"PERSON+AGENT"
    assert out["_ui"]["version"] == version_of(b"PERSON+AGENT")
    kept = versions.listing(tmp_path, "designs/launch.fig")[0]
    assert kept["by"] == "agent" and kept["intent"] == "tidy"
    assert versions.read(tmp_path, "designs/launch.fig", kept["id"]) == b"PERSON"

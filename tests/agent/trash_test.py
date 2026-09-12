"""Workspace trash — a delete is a move (docs/notes/trash.md): the files route,
the edit tool's overwrite snapshot, and the sandbox rm shim all land in one
layout; restore brings things back; entries expire lazily after 30 days."""
import json, os, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cycls._agent import trash

SHIM = Path("cycls/_agent/tools/shims/rm").resolve()


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def test_trash_moves_and_lists(tmp_path):
    ws = _ws(tmp_path)
    (ws / "report.md").write_text("v1")
    meta = trash.trash_path(ws, "report.md")
    assert not (ws / "report.md").exists()
    assert meta["kind"] == "file" and meta["by"] == "user" and meta["reason"] == "delete"
    assert (ws / ".trash" / meta["id"] / "data" / "report.md").read_text() == "v1"
    assert [m["path"] for m in trash.list_trash(ws)] == ["report.md"]


def test_kinds(tmp_path):
    ws = _ws(tmp_path)
    (ws / "apps" / "demo").mkdir(parents=True)
    (ws / "apps" / "demo" / "index.html").write_text("<h1>")
    (ws / "notes").mkdir()
    assert trash.trash_path(ws, "apps/demo")["kind"] == "app"
    assert trash.trash_path(ws, "notes")["kind"] == "dir"


def test_restore_and_conflict(tmp_path):
    ws = _ws(tmp_path)
    (ws / "report.md").write_text("old")
    tid = trash.trash_path(ws, "report.md")["id"]
    (ws / "report.md").write_text("new")            # the path was taken since
    assert trash.restore(ws, tid) == "report (restored).md"
    assert (ws / "report.md").read_text() == "new"
    assert (ws / "report (restored).md").read_text() == "old"
    assert trash.list_trash(ws) == []


def test_sweep_expires_after_ttl(tmp_path):
    ws = _ws(tmp_path)
    (ws / "a.md").write_text("a"); (ws / "b.md").write_text("b")
    old = trash.trash_path(ws, "a.md"); trash.trash_path(ws, "b.md")
    meta_path = ws / ".trash" / old["id"] / "meta.json"
    m = json.loads(meta_path.read_text())
    m["deleted_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    meta_path.write_text(json.dumps(m))
    assert [x["path"] for x in trash.list_trash(ws)] == ["b.md"]   # a.md swept, b.md kept
    assert not (ws / ".trash" / old["id"]).exists()


def test_purge_and_empty(tmp_path):
    ws = _ws(tmp_path)
    for n in ("a", "b"):
        (ws / f"{n}.md").write_text(n)
    a = trash.trash_path(ws, "a.md")["id"]; trash.trash_path(ws, "b.md")
    trash.purge(ws, a)
    assert [x["path"] for x in trash.list_trash(ws)] == ["b.md"]
    trash.empty(ws)
    assert trash.list_trash(ws) == []
    with pytest.raises(FileNotFoundError):
        trash.purge(ws, a)


def test_rejects_reserved_and_missing(tmp_path):
    ws = _ws(tmp_path)
    (ws / "x.md").write_text("x"); trash.trash_path(ws, "x.md")
    for bad in ("", ".trash", ".trash/whatever", "../outside"):
        with pytest.raises(ValueError):
            trash.trash_path(ws, bad)
    with pytest.raises(FileNotFoundError):
        trash.trash_path(ws, "nope.md")


def test_path_guards_reject_trash(tmp_path):
    from cycls._agent.tools import _resolve_path
    from cycls._agent.web.routers import resolve_path
    (tmp_path / ".trash").mkdir()
    with pytest.raises(ValueError):
        _resolve_path(".trash/x/meta.json", tmp_path)
    with pytest.raises(ValueError):
        resolve_path(tmp_path, ".trash")


def test_edit_create_over_existing_snapshots(tmp_path):
    """An overwrite is a deletion of the old content — it goes to the trash
    as an agent action tagged `overwrite` before the new text lands."""
    from cycls._agent.tools import _exec_edit
    ws = _ws(tmp_path)
    (ws / "a.md").write_text("v1")
    _exec_edit({"path": "a.md", "command": "create", "file_text": "v2"}, ws)
    assert (ws / "a.md").read_text() == "v2"
    (row,) = trash.list_trash(ws)
    assert row["path"] == "a.md" and row["by"] == "agent" and row["reason"] == "overwrite"
    assert (ws / ".trash" / row["id"] / "data" / "a.md").read_text() == "v1"


def test_rm_shim_moves_into_trash_and_falls_through_outside(tmp_path):
    """The sandbox rm: workspace targets become trash entries by the agent;
    paths outside the workspace go to the real rm; missing files behave like rm."""
    ws = _ws(tmp_path)
    (ws / "a.txt").write_text("a")
    (ws / "notes").mkdir(); (ws / "notes" / "n.md").write_text("n")
    outside = tmp_path / "scratch.txt"; outside.write_text("tmp")
    env = {**os.environ, "CYCLS_WORKSPACE": str(ws), "CYCLS_TRASH": str(ws / ".trash")}
    run = lambda *args: subprocess.run([sys.executable, str(SHIM), *args], cwd=ws, env=env,
                                       capture_output=True, text=True)
    assert run("a.txt").returncode == 0 and not (ws / "a.txt").exists()
    assert run("-rf", "notes").returncode == 0 and not (ws / "notes").exists()
    assert run("-f", str(outside)).returncode == 0 and not outside.exists()   # real rm
    assert run("missing.txt").returncode == 1
    assert run("-f", "missing.txt").returncode == 0
    rows = trash.list_trash(ws)
    assert sorted((r["path"], r["by"]) for r in rows) == [("a.txt", "agent"), ("notes", "agent")]
    assert (ws / ".trash" / [r for r in rows if r["path"] == "notes"][0]["id"] / "data" / "notes" / "n.md").exists()
    # the trash itself is off limits
    assert run("-rf", ".trash").returncode == 1

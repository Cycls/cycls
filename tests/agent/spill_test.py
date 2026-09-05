"""Large tool results land in .tmp/{chat}/ with a preview; small ones, and
anything with nowhere to go, pass through untouched."""
import json, os, subprocess, sys, time
from pathlib import Path
from cycls._agent import spill

BIG = [{"id": i, "total": i * 1.5} for i in range(2000)]


def test_small_and_homeless_pass_through(tmp_path):
    assert spill.spill("short", tmp_path, "c1", "bash-1") == "short"
    text = "x" * spill.SPILL_AT
    assert spill.spill(text, tmp_path, None, "bash-1") == text
    assert not (tmp_path / ".tmp").exists()


def test_json_array_spills_with_records_preview(tmp_path):
    out = spill.spill(json.dumps(BIG), tmp_path, "c1", "salla-abc123")
    path = tmp_path / ".tmp" / "c1" / "salla-abc123.json"
    assert json.loads(path.read_text()) == BIG
    assert ".tmp/c1/salla-abc123.json" in out and "2,000 records" in out and "jq" in out
    assert '"id": 0' in out and '"id": 5' not in out


def test_text_spills_with_lines_preview(tmp_path):
    text = "\n".join(f"line {i}" for i in range(5000))
    out = spill.spill(text, tmp_path, "c1", "bash-1")
    assert (tmp_path / ".tmp" / "c1" / "bash-1.txt").read_text() == text
    assert "5,000 lines" in out and "line 0" in out and "line 4999" not in out


def test_write_failure_returns_the_original(tmp_path):
    root = tmp_path / "file"
    root.write_text("not a directory")
    text = "x" * spill.SPILL_AT
    assert spill.spill(text, root, "c1", "bash-1") == text


def test_hidden_from_the_file_list(tmp_path):
    from cycls._agent.web.routers import _walk_catalog
    spill.spill(json.dumps(BIG), tmp_path, "c1", "salla-1")
    (tmp_path / "report.md").write_text("visible")
    assert [e["name"] for e in _walk_catalog(tmp_path)[0]] == ["report.md"]


def test_sweep_drops_idle_chats_and_throttles(tmp_path):
    tmp = tmp_path / ".tmp"
    old, fresh = tmp / "old", tmp / "fresh"
    for d in (old, fresh):
        d.mkdir(parents=True); (d / "f").write_text("x")
    stale = time.time() - spill.TTL - 1
    os.utime(old / "f", (stale, stale))
    spill._sweep(tmp)
    assert not old.exists() and fresh.exists()
    os.utime(fresh / "f", (stale, stale))
    spill._sweep(tmp)                      # within SWEEP_EVERY: no-op
    assert fresh.exists()


def test_purge_removes_the_chat_directory(tmp_path):
    spill.spill(json.dumps(BIG), tmp_path, "c1", "a")
    spill.spill(json.dumps(BIG), tmp_path, "c2", "a")
    spill.purge(tmp_path, "c1")
    assert not (tmp_path / ".tmp" / "c1").exists() and (tmp_path / ".tmp" / "c2").exists()


def test_rm_shim_deletes_scratch_for_real(tmp_path):
    ws, trash = tmp_path / "ws", tmp_path / "trash"
    f = ws / ".tmp" / "c1" / "dump.json"
    f.parent.mkdir(parents=True); f.write_text("x"); trash.mkdir()
    shim = Path(__file__).parents[2] / "cycls/_agent/tools/shims/rm"
    subprocess.run([sys.executable, shim, str(f)], check=True,
                   env={**os.environ, "CYCLS_WORKSPACE": str(ws), "CYCLS_TRASH": str(trash)})
    assert not f.exists() and not any(trash.iterdir())


def test_canvas_refuses_scratch(tmp_path):
    import asyncio
    from cycls._agent.tools import _exec_canvas
    f = tmp_path / ".tmp" / "c1" / "report.html"
    f.parent.mkdir(parents=True); f.write_text("<p>x</p>")
    out = asyncio.run(_exec_canvas({"path": ".tmp/c1/report.html"}, str(tmp_path)))
    assert out.startswith("Error") and "scratch" in out

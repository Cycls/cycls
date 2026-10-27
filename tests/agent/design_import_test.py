"""The Design tool's `import` action: a PowerPoint deck brought in as a Design deck (the service faked)."""
import asyncio
import types

from cycls._agent.design.importer import import_name
from cycls._agent.design.tool import _DESIGN_TOOL, _DESIGN_TOOL_SHORT
from cycls._agent.tools import _exec_design


def _ws(tmp_path):
    return types.SimpleNamespace(root=str(tmp_path), subject="org_1:user_1")


def _text(out):
    m = out["_model"] if isinstance(out, dict) else out
    return m if isinstance(m, str) else [b["text"] for b in m if b["type"] == "text"][-1]   # the ack, after the slides


def _fake_import(monkeypatch, parts=None, report=()):
    """The service's /import: one part (12 slides) unless `parts` says otherwise — each [slides made so far, next]."""
    calls = []
    parts = parts or [[12, None]]

    async def _i(pptx, user_id=None, start=0, fig=None, keep=None, preview=True):
        k = len(calls)
        calls.append({"pptx": pptx, "start": start, "fig": fig, "keep": keep, "preview": preview, "user_id": user_id})
        made, nxt = parts[k]
        return {"fig": f"FIG{k}".encode(), "slides": [{"name": f"slide-{i + 1}"} for i in range(made)],
                "previews": [b"\xff\xd8jpg"] * min(made, 12) if preview else [], "sheets": [], "sheet_pages": [],
                "report": list(report), "fonts": {"Source Sans 3": "Aptos"}, "deck": {"slides": parts[-1][0]},
                "count": parts[-1][0], "next": nxt}
    monkeypatch.setattr("cycls._agent.design.import_pptx", _i)
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda *a, **k: None)
    return calls


def test_an_upload_comes_in_as_a_deck_in_the_folder_open_named_as_the_person_named_it(tmp_path, monkeypatch):
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "73322f0d-Q3 review.pptx").write_bytes(b"PK\x03\x04deck")
    calls = _fake_import(monkeypatch, report=["animations aren't kept", "Aptos isn't an open font; used Source Sans 3"])
    out = asyncio.run(_exec_design({"action": "import", "path": "attachments/73322f0d-Q3 review.pptx"}, _ws(tmp_path)))
    assert (tmp_path / "Q3 review.fig").read_bytes() == b"FIG0"
    assert out["_ui"] == {"type": "ui", "action": "open_canvas", "path": "Q3 review.fig", "name": "Q3 review.fig"}
    said = _text(out)
    assert "Deck imported from attachments/73322f0d-Q3 review.pptx (12 slides)" in said
    assert "left as it was" in said and "animations aren't kept" in said and "duplicate_slide" in said
    assert calls[0]["pptx"] == b"PK\x03\x04deck" and calls[0]["keep"] == {"kind": "deck", "imported": {"from": "attachments/73322f0d-Q3 review.pptx"}}
    # The slides as they came in, to look at.
    assert sum(1 for b in out["_model"] if b["type"] == "image") == 12


def test_a_long_deck_comes_in_parts_each_added_to_the_last(tmp_path, monkeypatch):
    (tmp_path / "decks").mkdir()
    (tmp_path / "decks" / "board.pptx").write_bytes(b"PK\x03\x04big")
    calls = _fake_import(monkeypatch, parts=[[60, 60], [120, 120], [130, None]])
    out = asyncio.run(_exec_design({"action": "import", "path": "decks/board.pptx"}, _ws(tmp_path)))
    assert [c["start"] for c in calls] == [0, 60, 120]
    assert [c["fig"] for c in calls] == [None, b"FIG0", b"FIG1"]
    assert [bool(c["keep"]) for c in calls] == [True, False, False]          # the record, once
    assert [c["preview"] for c in calls] == [True, False, False]             # the first slides, once
    assert (tmp_path / "decks" / "board.fig").read_bytes() == b"FIG2"           # beside the .pptx
    assert "(130 slides)" in _text(out)


def test_an_import_never_overwrites_a_design(tmp_path, monkeypatch):
    (tmp_path / "pitch.pptx").write_bytes(b"PK")
    (tmp_path / "pitch.fig").write_bytes(b"MINE")
    _fake_import(monkeypatch)
    out = asyncio.run(_exec_design({"action": "import", "path": "pitch.pptx"}, _ws(tmp_path)))
    assert (tmp_path / "pitch.fig").read_bytes() == b"MINE" and (tmp_path / "pitch-2.fig").read_bytes() == b"FIG0"
    assert "named 'pitch-2'" in _text(out)


def test_what_isnt_a_deck_is_refused_and_nothing_is_saved(tmp_path, monkeypatch):
    calls = _fake_import(monkeypatch)
    (tmp_path / "report.pdf").write_bytes(b"%PDF")
    ws = _ws(tmp_path)
    assert "`extract`" in asyncio.run(_exec_design({"action": "import", "path": "report.pdf"}, ws))
    assert "doesn't exist" in asyncio.run(_exec_design({"action": "import", "path": "nope.pptx"}, ws))
    assert asyncio.run(_exec_design({"action": "import"}, ws)).startswith("Error: `import` needs `path`")
    (tmp_path / "huge.pptx").write_bytes(b"0" * (23 * 1024 * 1024))
    assert "more than the 22 MB" in asyncio.run(_exec_design({"action": "import", "path": "huge.pptx"}, ws))
    assert calls == [] and not list(tmp_path.glob("*.fig"))


def test_a_service_failure_is_said_and_nothing_is_saved(tmp_path, monkeypatch):
    (tmp_path / "broken.pptx").write_bytes(b"PK")

    async def _i(*a, **k):
        raise RuntimeError("this isn't a PowerPoint presentation (no ppt/presentation.xml)")
    monkeypatch.setattr("cycls._agent.design.import_pptx", _i)
    out = asyncio.run(_exec_design({"action": "import", "path": "broken.pptx"}, _ws(tmp_path)))
    assert out.startswith("Error: broken.pptx couldn't be brought into Design — this isn't a PowerPoint presentation")
    assert not list(tmp_path.glob("*.fig"))


def test_where_an_imported_deck_is_saved():
    assert import_name("attachments/73322f0d-Q3 review.pptx") == "Q3 review"
    assert import_name("attachments/73322f0d-Q3 review.pptx", "clients/acme") == "clients/acme/Q3 review"
    assert import_name("decks/board.pptx", "elsewhere") == "decks/board"
    assert import_name("board.PPTX") == "board"


def test_the_tool_offers_import_in_both_forms():
    assert "import" in _DESIGN_TOOL["input_schema"]["properties"]["action"]["enum"]
    assert "- import {path, name?}" in _DESIGN_TOOL["description"]
    assert "import" in _DESIGN_TOOL_SHORT["input_schema"]["properties"]["action"]["description"]
    assert "PowerPoint" in _DESIGN_TOOL_SHORT["description"]

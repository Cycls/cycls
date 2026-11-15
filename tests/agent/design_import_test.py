"""A PowerPoint deck the person brought, opened as a design to change (cycls/_agent/design/powerpoint.py):
the service's /import asked for part by part, the deck written once whole, the same file brought in only
once, what can't be brought in said once — and an attached deck pointed at `import`. No service is
contacted (the client's wire and the import call are faked)."""
import asyncio
import pathlib
import base64
import hashlib
import types

import pytest

from cycls._agent import design, versions
from cycls._agent.design import client, powerpoint
from cycls._agent.tools import _exec_design, tool_step


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for k in ("DESIGN_URL", "DESIGN_SECRET", "DESIGN_EDITOR_URL"):
        monkeypatch.delenv(k, raising=False)


def _ws(tmp_path):
    return types.SimpleNamespace(root=str(tmp_path), subject="org_1:user_1")


def _text(out):
    if isinstance(out, str):
        return out
    m = out["_model"]
    return m if isinstance(m, str) else next(b["text"] for b in reversed(m) if b["type"] == "text")


def _run(tmp_path, **inp):
    return asyncio.run(_exec_design({"action": "import", **inp}, _ws(tmp_path)))


def _pptx(tmp_path, rel="attachments/Q3 pitch.pptx", data=b"PK\x03\x04 a deck"):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def _fake_import(monkeypatch, parts=None, error=None):
    """The service's /import faked: `parts` answered in turn (each what differs from a 3-slide deck)."""
    calls = []
    parts = list(parts or [{}])

    async def _imp(pptx, start=0, fig=None, keep=None, preview=True, user_id=None):
        calls.append({"pptx": pptx, "start": start, "fig": fig, "keep": keep, "preview": preview, "user_id": user_id})
        if error:
            raise error
        part = {"fig": b"IMPORTED-%d" % len(calls), "slides": [{"name": "Slide 1"}], "count": 3, "next": None,
                "report": [], "fonts": {}, "previews": [b"J1", b"J2", b"J3"] if len(calls) == 1 else [],
                "sheets": [], "sheet_pages": []}
        part.update(parts[min(len(calls), len(parts)) - 1])
        return part

    monkeypatch.setattr("cycls._agent.design.import_deck", _imp)
    return calls


# ---- the client ----

def test_the_client_imports_a_deck_part_by_part(monkeypatch):
    sent = []

    async def _post(path, body, user_id=None):
        sent.append((path, body, user_id))
        return answers.pop(0)
    monkeypatch.setattr(client, "_post", _post)
    b64 = lambda b: base64.b64encode(b).decode()
    answers = [{"ok": True, "fig_base64": b64(b"FIG1"), "slides": [{"name": "Slide 1"}], "count": 70, "next": 60,
                "report": ["animations aren't kept (3×)"], "fonts": {"Carlito": "Calibri"},
                "previews_base64": [b64(b"P1")], "sheets_base64": [b64(b"S1")], "sheet_pages": [[5, 60]]},
               {"ok": True, "fig_base64": b64(b"FIG2"), "deck": {"slides": 70}}]
    r = asyncio.run(client.import_deck(b"PPTX", keep={"kind": "deck"}, user_id="org:u"))
    assert sent[0] == ("/import", {"pptx": b64(b"PPTX"), "from": 0, "preview": True, "keep": {"kind": "deck"}}, "org:u")
    assert r["fig"] == b"FIG1" and r["count"] == 70 and r["next"] == 60 and r["fonts"] == {"Carlito": "Calibri"}
    assert r["previews"] == [b"P1"] and r["sheets"] == [b"S1"] and r["sheet_pages"] == [[5, 60]]
    # A later part goes with the design so far, from where the rest start; the last says no `next`.
    r = asyncio.run(client.import_deck(b"PPTX", start=60, fig=b"FIG1", preview=False))
    assert sent[1][1] == {"pptx": b64(b"PPTX"), "from": 60, "preview": False, "fig": b64(b"FIG1")}
    assert r["fig"] == b"FIG2" and r["next"] is None and r["count"] == 70 and r["report"] == [] and r["previews"] == []


# ---- the action ----

def test_an_uploaded_deck_is_imported_as_one_design_open_on_the_canvas(tmp_path, monkeypatch):
    calls = _fake_import(monkeypatch, [{"report": ["Calibri isn't an open font; used Carlito, its closest open match",
                                                   "animations aren't kept (4×)"]}])
    src = _pptx(tmp_path)
    out = _run(tmp_path, path=src)
    # Named after the deck, where the person is (here the top of the workspace) — not beside the upload.
    assert (tmp_path / "Q3 pitch.fig").read_bytes() == b"IMPORTED-1"
    assert out["_ui"] == {"type": "ui", "action": "open_canvas", "path": "Q3 pitch.fig", "name": "Q3 pitch.fig"}
    assert len(calls) == 1 and calls[0]["start"] == 0 and calls[0]["fig"] is None and calls[0]["preview"] is True
    assert calls[0]["user_id"] == "org_1:user_1" and calls[0]["pptx"] == b"PK\x03\x04 a deck"
    sha = hashlib.sha256(b"PK\x03\x04 a deck").hexdigest()
    assert calls[0]["keep"] == {"kind": "deck", "imported": {"source": src, "sha256": sha}}   # kept in the .fig
    m = out["_model"]
    assert [b["text"] for b in m if b["type"] == "text"][:3] == ["Slide 1:", "Slide 2:", "Slide 3:"]
    assert [base64.b64decode(b["source"]["data"]) for b in m if b["type"] == "image"] == [b"J1", b"J2", b"J3"]
    text = _text(out)
    assert "brought in as a deck (3 slides)" in text and "ONE file, Q3 pitch.fig" in text
    assert "named after its PowerPoint shape" in text and "`edit`" in text and "don't import the file again" in text
    assert "Calibri isn't an open font" in text and "animations aren't kept" in text and "tell the person once" in text
    assert "their own file with your changes written into it" in text and "`export` says" in text   # what the download is
    assert "not yours to QA" in text


def test_a_deck_is_saved_in_the_folder_the_person_has_open_or_where_its_name_says(tmp_path, monkeypatch):
    from cycls._agent.design.tool import DESIGN_FOLDER
    _fake_import(monkeypatch)
    src = _pptx(tmp_path)
    token = DESIGN_FOLDER.set("clients/acme")
    try:
        out = _run(tmp_path, path=src)
    finally:
        DESIGN_FOLDER.reset(token)
    assert (tmp_path / "clients" / "acme" / "Q3 pitch.fig").is_file() and out["_ui"]["path"] == "clients/acme/Q3 pitch.fig"
    _run(tmp_path, path=_pptx(tmp_path, "attachments/other.pptx", b"PK other"), name="decks/board")
    assert (tmp_path / "decks" / "board.fig").is_file()


def test_a_deck_imported_in_parts_is_written_once_whole(tmp_path, monkeypatch):
    calls = _fake_import(monkeypatch, [{"count": 130, "next": 60, "report": ["SmartArt kept as its shapes"]},
                                       {"count": 130, "next": 110, "report": ["SmartArt kept as its shapes", "3D isn't kept"]},
                                       {"count": 130, "next": None}])
    out = _run(tmp_path, path=_pptx(tmp_path), name="decks/pitch")
    assert [(c["start"], c["fig"], c["preview"], c["keep"] is None) for c in calls] == [
        (0, None, True, False), (60, b"IMPORTED-1", False, True), (110, b"IMPORTED-2", False, True)]
    assert (tmp_path / "decks" / "pitch.fig").read_bytes() == b"IMPORTED-3"        # the whole deck, once
    text = _text(out)
    assert "(130 slides)" in text and text.count("SmartArt kept as its shapes") == 1 and "3D isn't kept" in text


def test_the_same_deck_imported_again_points_at_its_design_and_makes_nothing(tmp_path, monkeypatch):
    calls = _fake_import(monkeypatch)
    src = _pptx(tmp_path)
    _run(tmp_path, path=src)
    again = _run(tmp_path, path=src)
    assert len(calls) == 1                                                       # no second service call
    assert sorted(p.name for p in tmp_path.glob("*.fig")) == ["Q3 pitch.fig"]    # no "Q3 pitch-2"
    assert "already in as Q3 pitch.fig" in _text(again) and "Nothing new was made" in _text(again)
    assert again["_ui"]["action"] == "open_canvas" and again["_ui"]["path"] == "Q3 pitch.fig"
    # Twice at once (the model calls tools in parallel) is still one import.
    calls.clear()
    other = _pptx(tmp_path, "attachments/other.pptx", b"PK other deck")

    async def both():
        return await asyncio.gather(*(_exec_design({"action": "import", "path": other}, _ws(tmp_path)) for _ in range(2)))
    asyncio.run(both())
    assert len(calls) == 1 and (tmp_path / "other.fig").is_file() and not (tmp_path / "other-2.fig").exists()
    # Its design gone (renamed, deleted), the file comes in again.
    (tmp_path / "other.fig").unlink()
    _run(tmp_path, path=other)
    assert len(calls) == 2 and (tmp_path / "other.fig").is_file()
    # Another version of the file under a name already taken gets a fresh name, as a render does.
    _pptx(tmp_path, src, b"PK the next version")
    out = _run(tmp_path, path=src)
    assert (tmp_path / "Q3 pitch-2.fig").is_file() and "named 'Q3 pitch-2'" in _text(out)


def test_a_deck_brought_in_again_with_replace_goes_over_its_design_its_version_kept(tmp_path, monkeypatch):
    calls = _fake_import(monkeypatch)
    src = _pptx(tmp_path)
    _run(tmp_path, path=src)
    out = _run(tmp_path, path=src, name="Q3 pitch", replace=True)
    assert len(calls) == 2 and (tmp_path / "Q3 pitch.fig").read_bytes() == b"IMPORTED-2"
    assert not (tmp_path / "Q3 pitch-2.fig").exists()
    assert "earlier version is kept in its history" in _text(out)
    assert out["_ui"]["action"] == "design_command" and out["_ui"]["reload"] is True
    assert versions.listing(str(tmp_path), "Q3 pitch.fig")                      # what it was, kept


def test_an_import_that_cannot_be_made_says_why_and_saves_nothing(tmp_path, monkeypatch):
    _fake_import(monkeypatch)
    assert _run(tmp_path).startswith("Error: `import` needs `path`")
    assert _run(tmp_path, path="attachments/missing.pptx") == "Error: attachments/missing.pptx doesn't exist in the workspace."
    old = _run(tmp_path, path=_pptx(tmp_path, "old.ppt"))
    assert "old PowerPoint file (.ppt)" in old and "Save As" in old
    assert "isn't a PowerPoint file" in _run(tmp_path, path=_pptx(tmp_path, "notes.docx"))
    monkeypatch.setattr(powerpoint, "_IMPORT_MAX", 4)
    big = _run(tmp_path, path=_pptx(tmp_path, "big.pptx"))
    assert "MB — a deck comes in at up to" in big and "won't change that" in big and "Compress Pictures" in big
    monkeypatch.setattr(powerpoint, "_IMPORT_MAX", 22 << 20)
    # The service can't read it: said once, with no retry to make.
    _fake_import(monkeypatch, error=RuntimeError("this isn't a PowerPoint presentation (no ppt/presentation.xml)"))
    bad = _run(tmp_path, path=_pptx(tmp_path, "broken.pptx"))
    assert "couldn't be brought in — this isn't a PowerPoint presentation" in bad and "Nothing was saved" in bad
    assert "importing it again won't change that" in bad
    _fake_import(monkeypatch, error=design.Unavailable("design service unreachable"))
    assert _run(tmp_path, path="broken.pptx").startswith("Error: design unavailable")
    # A deck that never ends is given up on, and nothing half-made is left behind…
    calls = _fake_import(monkeypatch, [{"next": n} for n in range(10, 200, 10)])
    huge = _run(tmp_path, path="broken.pptx")
    assert "too large to bring in" in huge and len(calls) == powerpoint._IMPORT_PARTS
    # …nor one that stops moving on…
    _fake_import(monkeypatch, [{"next": 60}, {"next": 60}])
    assert "past slide 61" in _run(tmp_path, path="broken.pptx")
    # …nor one whose pictures would fill a later request.
    monkeypatch.setattr(powerpoint, "_SERVICE_BODY", 1 << 20)
    calls = _fake_import(monkeypatch, [{"next": 60}, {}])
    assert "too large to bring in whole" in _run(tmp_path, path="broken.pptx") and len(calls) == 1
    assert not list(tmp_path.rglob("*.fig"))


# ---- the tool, and an attached deck ----

def test_the_tool_offers_import_whole_and_short():
    from cycls._agent.design import tool
    whole, short = tool._DESIGN_TOOL, tool._DESIGN_TOOL_SHORT
    assert "import" in whole["input_schema"]["properties"]["action"]["enum"]
    assert "import" in short["input_schema"]["properties"]["action"]["enum"]
    assert "- import {path, name?}" in whole["description"] and "a script over the .pptx only" in whole["description"]
    assert "PowerPoint deck the person brought" in short["description"]
    assert "import" in short["input_schema"]["properties"]["action"]["description"]
    assert tool_step("design", {"action": "import", "path": "attachments/pitch.pptx"})["step"] == "import attachments/pitch.pptx"


def test_an_attached_deck_is_pointed_at_import_when_design_is_offered(tmp_path, monkeypatch):
    from cycls._agent.harness import main
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "pitch.pptx").write_bytes(b"PK deck")

    async def _read(inp, workspace, chat_id=None):
        return "# Slide 1\nOur year"
    monkeypatch.setattr(main, "_exec_read", _read)
    block = [{"type": "file", "file": "attachments/pitch.pptx"}]
    out = asyncio.run(main._ingest(block, str(tmp_path), design=True))
    assert out[0]["text"].startswith("[Attached: attachments/pitch.pptx, a PowerPoint deck; its text is below.")
    assert '{"action": "import", "path": "attachments/pitch.pptx"}' in out[0]["text"]
    assert out[1]["text"] == "# Slide 1\nOur year"
    # Without Design, as before.
    assert asyncio.run(main._ingest(block, str(tmp_path)))[0] == {"type": "text", "text": "[Attached: attachments/pitch.pptx]"}

    async def _unread(inp, workspace, chat_id=None):
        return "Error: the parser is unavailable"
    monkeypatch.setattr(main, "_exec_read", _unread)
    out = asyncio.run(main._ingest(block, str(tmp_path), design=True))
    assert len(out) == 1 and "its text couldn't be read here" in out[0]["text"] and '"action": "import"' in out[0]["text"]


# ---- the deck back into the person's own file ----

def _imported_deck(tmp_path, monkeypatch, data=b"PK\x03\x04 a deck"):
    """A deck imported (its file kept), the service's `inspect` answering with its record."""
    _fake_import(monkeypatch)
    _run(tmp_path, path=_pptx(tmp_path, data=data))
    sha = hashlib.sha256(data).hexdigest()

    async def _outline(fig, user_id=None, page=None, full=False, sheets=False):
        return {"frames": [], "pages": [], "page": "", "keep": {"kind": "deck", "imported": {"sha256": sha}}}
    monkeypatch.setattr("cycls._agent.design.outline", _outline)
    return sha


def test_the_file_a_deck_came_from_is_kept_and_found_for_its_design(tmp_path, monkeypatch):
    sha = _imported_deck(tmp_path, monkeypatch)
    assert (tmp_path / ".cache" / "design" / "decks" / f"{sha}.pptx").read_bytes() == b"PK\x03\x04 a deck"
    # Found by the design's own record — wherever the design is now, whatever it is called.
    (tmp_path / "Q3 pitch.fig").rename(tmp_path / "renamed.fig")
    assert asyncio.run(powerpoint.original_for(str(tmp_path), b"FIG", "u")) == b"PK\x03\x04 a deck"
    # Not when the record names another file, or there's no record, or the two wouldn't fit one request.
    async def _other(fig, **kw):
        return {"keep": {"kind": "deck"}}
    monkeypatch.setattr("cycls._agent.design.outline", _other)
    assert asyncio.run(powerpoint.original_for(str(tmp_path), b"FIG")) is None
    _imported_deck(tmp_path, monkeypatch)
    monkeypatch.setattr(powerpoint, "_SERVICE_BODY", 10)
    assert asyncio.run(powerpoint.original_for(str(tmp_path), b"FIG")) is None


def test_a_workspace_that_never_imported_a_deck_asks_the_service_nothing(tmp_path, monkeypatch):
    async def _outline(*a, **k):
        raise AssertionError("asked")
    monkeypatch.setattr("cycls._agent.design.outline", _outline)
    assert asyncio.run(powerpoint.original_for(str(tmp_path), b"FIG")) is None


def test_exporting_an_imported_deck_writes_into_the_persons_own_file_and_says_so(tmp_path, monkeypatch):
    _imported_deck(tmp_path, monkeypatch)
    sent = {}

    async def _back(fig, original, scale=2, user_id=None):
        sent.update(fig=fig, original=original)
        return b"PPTX-BACK", sent.get("written", {"kept": [2, 3], "changed": [1], "copies": [], "removed": 0})
    monkeypatch.setattr("cycls._agent.design.export_back", _back)
    out = asyncio.run(_exec_design({"action": "export", "name": "Q3 pitch", "format": "pptx"}, _ws(tmp_path)))
    assert sent["original"] == b"PK\x03\x04 a deck" and (tmp_path / "Q3 pitch.pptx").read_bytes() == b"PPTX-BACK"
    assert "person's own file with the changes written in (slides 1 changed)" in _text(out)
    sent["written"] = {"rebuilt": True, "why": ['slide 2: "Title 1" was restyled']}
    out = asyncio.run(_exec_design({"action": "export", "name": "Q3 pitch", "format": "pptx"}, _ws(tmp_path)))
    assert "written anew from the design" in _text(out) and "restyled" in _text(out)


def test_the_canvas_download_of_an_imported_deck_is_the_persons_own_file(tmp_path, monkeypatch):
    from cycls._agent.web.design_routes import _design_export
    _imported_deck(tmp_path, monkeypatch)

    async def _back(fig, original, scale=2, user_id=None):
        return b"PPTX-BACK", {"kept": [1]}

    async def _plain(*a, **k):
        return b"PPTX-ANEW"
    monkeypatch.setattr("cycls._agent.design.export_back", _back)
    monkeypatch.setattr("cycls._agent.design.export", _plain)
    path, name = asyncio.run(_design_export(str(tmp_path), str(tmp_path / "Q3 pitch.fig"), "pptx", "u"))
    assert pathlib.Path(path).read_bytes() == b"PPTX-BACK" and name == "Q3 pitch.pptx"
    path, _ = asyncio.run(_design_export(str(tmp_path), str(tmp_path / "Q3 pitch.fig"), "pdf", "u"))
    assert pathlib.Path(path).read_bytes() == b"PPTX-ANEW"                     # a PDF is made as before

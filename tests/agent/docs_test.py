"""The `docs` tool: its schema, who is offered it, the wire to the office service, and the executor
(read, edit with the stale-file retry, create) over a mocked service. No service is contacted."""
import asyncio
import base64
import json
import types

import httpx
import pytest

from cycls._agent import versions
from cycls._agent.office import client as office
from cycls._agent.office import docs

_REAL_CLIENT = httpx.AsyncClient
DOCX = b"PK\x03\x04 original document"
PATCHED = b"PK\x03\x04 patched document"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("OFFICE_URL", "OFFICE_SECRET", "OFFICE_EDITOR_URL", "SHEETS_ORGS", "DOCS_ORGS"):
        monkeypatch.delenv(k, raising=False)


def _on(monkeypatch):
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("OFFICE_SECRET", "k" * 40)
    monkeypatch.setenv("DOCS_ORGS", "org1")


def _ws(tmp_path, subject="org1:user1"):
    return types.SimpleNamespace(root=tmp_path, subject=subject, ws=None)


def _mock(monkeypatch, handler):
    monkeypatch.setattr(office.httpx, "AsyncClient",
                        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def _form(request):
    """The multipart parts a request carried: {name: bytes}."""
    body = request.read()
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    parts = {}
    for chunk in body.split(b"--" + boundary):
        if b'name="' not in chunk:
            continue
        head, _, data = chunk.partition(b"\r\n\r\n")
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        parts[name] = data.rstrip(b"\r\n")
    return parts


def _run(inp, ws):
    return asyncio.run(docs.exec_docs(inp, ws, types.SimpleNamespace(chat_id="c1")))


def _applied(report="¶3 replaced.", unchanged=False, touched=()):
    return httpx.Response(200, json={"unchanged": unchanged, "file": None if unchanged else base64.b64encode(PATCHED).decode(),
                                     "report": report, "touched": list(touched)})


# ---- the schema and who gets it ----------------------------------------------------------------

def test_the_choices_that_matter_are_required():
    schema = docs.DOCS_TOOL["input_schema"]
    assert schema["required"] == ["action", "path", "ops", "content"]     # models drop optional fields
    assert schema["properties"]["action"]["enum"] == ["read", "edit", "create"]
    op = schema["properties"]["ops"]["items"]
    assert op["required"] == ["op"]
    assert set(op["properties"]["op"]["enum"]) == set(docs.OPS)


def test_offered_only_with_the_service_and_the_organisation(monkeypatch, tmp_path):
    from cycls._agent.tools import _TOOLS, build_tools
    assert not [t for t in build_tools(["Docs"], None) if t["name"] == "docs"]
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    assert [t["name"] for t in build_tools(["Docs"], None)] == ["docs"]
    assert "docs" in _TOOLS and "python-docx" in _TOOLS["docs"].prompt
    # In the list, but the organisation is not on DOCS_ORGS (Sheets being on does not switch Docs on).
    monkeypatch.setenv("SHEETS_ORGS", "org1")
    out = _run({"action": "read", "path": "a.docx", "ops": []}, _ws(tmp_path))
    assert out.startswith("Error:") and "not switched on" in out


def test_the_step_names_the_action_and_what_it_does():
    assert docs.docs_step({"action": "edit", "path": "q3.docx", "intent": "Tighten the summary"}) == \
        {"tool_name": "Docs", "step": "edit Tighten the summary"}
    assert docs.docs_step({"action": "read", "path": "q3.docx"})["step"] == "read q3.docx"


# ---- the wire --------------------------------------------------------------------------------

def test_read_and_apply_send_the_file_and_the_request(monkeypatch):
    _on(monkeypatch)
    seen = []

    def handler(request):
        seen.append((request.url.path, _form(request)))
        if request.url.path == "/v1/docs/read":
            return httpx.Response(200, json={"text": "q3.docx — 20 paragraphs"})
        return _applied()

    _mock(monkeypatch, handler)
    assert asyncio.run(office.docs_read(DOCX, "q3.docx", start=12)) == "q3.docx — 20 paragraphs"
    path, form = seen[0]
    assert path == "/v1/docs/read" and form["file"] == DOCX
    assert json.loads(form["request"]) == {"name": "q3.docx", "from": 12}

    r = asyncio.run(office.docs_apply(DOCX, "q3.docx", [{"op": "delete", "para": "¶3·abc"}]))
    assert r == {"unchanged": False, "bytes": PATCHED, "report": "¶3 replaced.", "touched": []}
    assert seen[1][0] == "/v1/docs/apply" and json.loads(seen[1][1]["request"])["ops"] == [{"op": "delete", "para": "¶3·abc"}]

    asyncio.run(office.docs_apply(None, "new.docx", [], create={"content": "# مرحبا"}))
    assert "file" not in seen[2][1] and json.loads(seen[2][1]["request"])["create"] == {"content": "# مرحبا"}


def test_the_service_s_own_words_reach_the_model_once(monkeypatch, tmp_path):
    _on(monkeypatch)
    (tmp_path / "q3.docx").write_bytes(DOCX)
    said = "op 1 (replace): ¶3 is not the paragraph you read (it is ¶3·u22 now): read the document again. Nothing was changed."
    _mock(monkeypatch, lambda r: httpx.Response(422, json={"error": said}))
    out = _run({"action": "edit", "path": "q3.docx", "ops": [{"op": "replace", "para": "¶3·zzz", "text": "x"}]}, _ws(tmp_path))
    assert out == f"Error: {said}"
    assert (tmp_path / "q3.docx").read_bytes() == DOCX
    _mock(monkeypatch, lambda r: httpx.Response(503))
    assert "unavailable" in _run({"action": "read", "path": "q3.docx", "ops": []}, _ws(tmp_path))


# ---- the executor ------------------------------------------------------------------------------

def test_edit_writes_the_file_keeps_the_old_version_and_tells_an_open_editor(monkeypatch, tmp_path):
    _on(monkeypatch)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "q3.docx").write_bytes(DOCX)

    def handler(request):
        assert _form(request)["file"] == DOCX
        return _applied("¶3 replaced.\n\nNow:\n¶3·h10 Revenue grew **15%**.", touched=["3E1A0B2C"])

    _mock(monkeypatch, handler)
    out = _run({"action": "edit", "path": "reports/q3.docx", "intent": "Update revenue",
                "ops": [{"op": "replace", "para": "¶3·u22", "text": "Revenue grew **15%**."}]}, _ws(tmp_path))
    assert out["_model"].startswith("Edited reports/q3.docx.\n¶3 replaced.") and "¶3·h10" in out["_model"]
    from cycls._agent.design.store import version_of
    # an open Docs editor takes the new file in, the changed paragraph marked
    assert out["_ui"] == {"type": "ui", "action": "docs_command", "path": "reports/q3.docx", "version": version_of(PATCHED),
                          "touched": ["3E1A0B2C"], "intent": "Update revenue"}
    assert (tmp_path / "reports" / "q3.docx").read_bytes() == PATCHED
    kept = versions.listing(tmp_path, "reports/q3.docx")
    assert kept and versions.read(tmp_path, "reports/q3.docx", kept[0]["id"]) == DOCX   # the old file, kept


def test_a_save_meanwhile_is_edited_again_once(monkeypatch, tmp_path):
    _on(monkeypatch)
    f = tmp_path / "q3.docx"
    f.write_bytes(DOCX)
    calls = []

    def handler(request):
        sent = _form(request)["file"]
        calls.append(sent)
        if len(calls) == 1:
            f.write_bytes(b"PK\x03\x04 saved by hand")    # a save lands while the edit runs
        return httpx.Response(200, json={"unchanged": False, "file": base64.b64encode(PATCHED + sent[-4:]).decode(), "report": "done"})

    _mock(monkeypatch, handler)
    out = _run({"action": "edit", "path": "q3.docx", "ops": [{"op": "delete", "para": "¶2"}]}, _ws(tmp_path))
    assert calls == [DOCX, b"PK\x03\x04 saved by hand"]          # applied again, to the newer file
    assert f.read_bytes() == PATCHED + b"hand" and out["_ui"]["action"] == "docs_command"
    assert out["_ui"]["touched"] == []


def test_nothing_to_change_writes_nothing(monkeypatch, tmp_path):
    _on(monkeypatch)
    (tmp_path / "q3.docx").write_bytes(DOCX)
    _mock(monkeypatch, lambda r: _applied("Nothing in the file changed.", unchanged=True))
    out = _run({"action": "edit", "path": "q3.docx", "ops": [{"op": "find_replace", "find": "a", "replace": "a"}]}, _ws(tmp_path))
    assert out.startswith("Nothing in q3.docx changed.") and not versions.listing(tmp_path, "q3.docx")


def test_create_makes_a_new_document_from_markdown_and_opens_it(monkeypatch, tmp_path):
    _on(monkeypatch)
    seen = []

    def handler(request):
        seen.append(json.loads(_form(request)["request"]))
        return _applied("notes.docx — 3 paragraphs\n\n¶1·gxk [Heading 1] Notes")

    _mock(monkeypatch, handler)
    out = _run({"action": "create", "path": "new/notes.docx", "ops": [], "content": "# Notes\n- one", "rtl": False}, _ws(tmp_path))
    assert seen[0]["create"] == {"content": "# Notes\n- one", "rtl": False}
    assert (tmp_path / "new" / "notes.docx").read_bytes() == PATCHED
    assert out["_model"].startswith("Created new/notes.docx.\nnotes.docx — 3 paragraphs")
    assert out["_ui"] == {"type": "ui", "action": "open_canvas", "path": "new/notes.docx"}
    assert "already exists" in _run({"action": "create", "path": "new/notes.docx", "ops": [], "content": "x"}, _ws(tmp_path))
    assert "needs `content`" in _run({"action": "create", "path": "new/other.docx", "ops": []}, _ws(tmp_path))


def test_only_docx_files_and_known_ops(monkeypatch, tmp_path):
    _on(monkeypatch)
    assert "not a .docx file" in _run({"action": "read", "path": "a.doc", "ops": []}, _ws(tmp_path))
    (tmp_path / "q3.docx").write_bytes(DOCX)
    out = _run({"action": "edit", "path": "q3.docx", "ops": [{"op": "rewrite_everything"}]}, _ws(tmp_path))
    assert "unknown op" in out and (tmp_path / "q3.docx").read_bytes() == DOCX
    assert "needs `ops`" in _run({"action": "edit", "path": "q3.docx", "ops": []}, _ws(tmp_path))


def test_a_picture_is_sent_from_the_workspace_and_comments_are_signed(monkeypatch, tmp_path):
    _on(monkeypatch)
    (tmp_path / "q3.docx").write_bytes(DOCX)
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "logo.png").write_bytes(b"\x89PNG fake image")
    seen = []

    def handler(request):
        seen.append(json.loads(_form(request)["request"]))
        return _applied("A picture added after the paragraph.")

    _mock(monkeypatch, handler)
    out = _run({"action": "edit", "path": "q3.docx", "content": "",
                "ops": [{"op": "picture", "para": "¶2·abc", "path": "img/logo.png", "width": 200},
                        {"op": "comment", "para": "¶3·def", "text": "Check this"}]}, _ws(tmp_path))
    assert out["_model"].startswith("Edited q3.docx.")
    sent = seen[0]
    picture = sent["ops"][0]
    assert "path" not in picture and picture["name"] == "logo.png" and picture["width"] == 200
    assert base64.b64decode(picture["data"]) == b"\x89PNG fake image"
    assert sent["author"] == "Super"


def test_a_picture_that_is_not_there_or_not_an_image_changes_nothing(monkeypatch, tmp_path):
    _on(monkeypatch)
    (tmp_path / "q3.docx").write_bytes(DOCX)
    (tmp_path / "notes.txt").write_text("x")
    _mock(monkeypatch, lambda r: pytest.fail("the service was called"))
    missing = _run({"action": "edit", "path": "q3.docx", "ops": [{"op": "picture", "para": "¶2", "path": "nope.png"}]}, _ws(tmp_path))
    assert "does not exist" in missing and "Nothing was changed" in missing
    text = _run({"action": "edit", "path": "q3.docx", "ops": [{"op": "picture", "para": "¶2", "path": "notes.txt"}]}, _ws(tmp_path))
    assert "not a PNG, JPEG or GIF" in text
    outside = _run({"action": "edit", "path": "q3.docx", "ops": [{"op": "picture", "para": "¶2", "path": "../../etc/x.png"}]}, _ws(tmp_path))
    assert outside.startswith("Error:") and (tmp_path / "q3.docx").read_bytes() == DOCX


# ---- what the person selected in an open document ---------------------------------------------------------------

def test_a_selection_in_a_word_document_reaches_the_model_by_its_references():
    from cycls._agent.harness.main import _with_selection
    from cycls._agent.web.server import _clean_selection
    raw = {"path": "reports/q3.docx", "frame": None,
           "nodes": [{"name": "¶12·h10", "type": "words", "text": "15%"}, {"name": "T1 r2c3", "type": "cell", "text": "1,500"}]}
    sel = _clean_selection(raw)
    assert sel == {"path": "reports/q3.docx", "frame": None, "nodes": raw["nodes"]}
    assert _with_selection("make it 17%", sel)[-1]["text"] == \
        '[Selected in reports/q3.docx: ¶12·h10 (words) "15%", T1 r2c3 (cell) "1,500"]'
    assert "Selected in" in docs.DOCS_TOOL["description"]


def test_a_cell_value_sent_in_cells_counts_as_its_text():
    from cycls._agent.office.docs import _check_ops
    op = {"op": "cell", "table": "T1", "row": 2, "col": 2, "cells": ["1,550"], "rows": []}
    assert _check_ops([op]) is None and op["text"] == "1,550"
    # an empty `cells` (hosts that fill every field) still says what is missing
    assert "needs `words`" in _check_ops([{"op": "cell", "table": "T1", "row": 2, "col": 2, "cells": [], "width": 0}])


def test_words_go_to_the_service_as_text():
    from cycls._agent.office.docs import DOCS_TOOL, _check_ops
    props = DOCS_TOOL["input_schema"]["properties"]["ops"]["items"]["properties"]
    assert "words" in props and "text" not in props   # some hosts' parsers drop a key named `text`
    reply = {"op": "reply", "comment": 4, "words": "Done.", "done": True}
    assert _check_ops([reply]) is None and reply == {"op": "reply", "comment": 4, "text": "Done.", "done": True}
    old = {"op": "replace", "para": "¶3·u22", "text": "Still taken."}   # a model that sends `text` anyway
    assert _check_ops([old]) is None and old["text"] == "Still taken."
    assert "needs `words`" in _check_ops([{"op": "reply", "comment": 4, "done": True}])


def test_page_layout_ops_are_offered_and_cleaned_of_what_a_host_filled_with_nothing():
    from cycls._agent.office.docs import DOCS_TOOL, OPS, _check_ops
    for name in ("header", "footer", "section_break", "remove_section_break", "page_setup"):
        assert name in OPS and name in DOCS_TOOL["description"]
    props = DOCS_TOOL["input_schema"]["properties"]["ops"]["items"]["properties"]
    for field in ("section", "page", "start", "paper", "orientation", "margin", "margins", "columns", "gap", "line", "page_start", "page_numbers"):
        assert field in props
    footer = {"op": "footer", "words": "Page {page} of {pages}", "align": "center", "section": 0, "page": ""}
    assert _check_ops([footer]) is None
    assert footer == {"op": "footer", "text": "Page {page} of {pages}", "align": "center"}
    cover = {"op": "header", "remove": True, "page": "first", "section": 1}   # none is said with remove
    assert _check_ops([cover]) is None and cover == {"op": "header", "text": "", "page": "first", "section": 1}
    # no words (models leave the field out when retrying) is not taken for none: it says what to send
    assert "or remove: true for none" in _check_ops([{"op": "footer", "page": "first", "align": "center"}])
    assert "needs `words`" in _check_ops([{"op": "header", "words": "", "section": 2}])
    setup = {"op": "page_setup", "paper": "A4", "section": 0, "columns": 0, "page_start": 0, "margin": "2cm",
             "margins": {"top": ""}, "orientation": "", "line": False, "gap": ""}
    assert _check_ops([setup]) is None
    assert setup == {"op": "page_setup", "paper": "A4", "margins": "2cm", "line": False}

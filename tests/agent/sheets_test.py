"""The `sheets` tool: its schema, who is offered it, the wire to the office service, and the executor
(read, edit with the stale-file retry, create) over a mocked service. No service is contacted."""
import asyncio
import base64
import json
import types

import httpx
import pytest

from cycls._agent import versions
from cycls._agent.office import client as office
from cycls._agent.office import sheets

_REAL_CLIENT = httpx.AsyncClient
XLSX = b"PK\x03\x04 original workbook"
PATCHED = b"PK\x03\x04 patched workbook"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("OFFICE_URL", "OFFICE_SECRET", "OFFICE_EDITOR_URL", "SHEETS_ORGS", "DOCS_ORGS"):
        monkeypatch.delenv(k, raising=False)


def _on(monkeypatch):
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("OFFICE_SECRET", "k" * 40)
    monkeypatch.setenv("SHEETS_ORGS", "org1")


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
    return asyncio.run(sheets.exec_sheets(inp, ws, types.SimpleNamespace(chat_id="c1")))


# ---- the schema and who gets it ----------------------------------------------------------------

def test_the_choices_that_matter_are_required():
    schema = sheets.SHEETS_TOOL["input_schema"]
    assert schema["required"] == ["action", "path", "ops"]     # ops too: models drop optional fields
    assert schema["properties"]["action"]["enum"] == ["read", "edit", "create", "comments"]
    op = schema["properties"]["ops"]["items"]
    assert op["required"] == ["op", "target"]
    assert set(op["properties"]["op"]["enum"]) == set(sheets.OPS)


def test_offered_only_with_the_service_and_the_organisation(monkeypatch, tmp_path):
    from cycls._agent.tools import _TOOLS, build_tools
    assert not [t for t in build_tools(["Sheets"], None) if t["name"] == "sheets"]
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    assert [t["name"] for t in build_tools(["Sheets"], None)] == ["sheets"]
    assert "sheets" in _TOOLS and "openpyxl" in _TOOLS["sheets"].prompt
    # The tool is in the list but the organisation is not on SHEETS_ORGS: the call says so.
    out = _run({"action": "read", "path": "a.xlsx"}, _ws(tmp_path))
    assert out.startswith("Error:") and "not switched on" in out


def test_the_step_names_the_action_and_what_it_does():
    assert sheets.sheets_step({"action": "edit", "path": "b.xlsx", "intent": "Totals"}) == \
        {"tool_name": "Sheets", "step": "edit Totals"}
    assert sheets.sheets_step({"action": "read", "path": "b.xlsx"})["step"] == "read b.xlsx"


# ---- the wire --------------------------------------------------------------------------------

def test_read_and_apply_send_the_file_and_the_request(monkeypatch):
    _on(monkeypatch)
    seen = []

    def handler(request):
        seen.append((request.url.path, _form(request)))
        if request.url.path == "/v1/sheets/read":
            return httpx.Response(200, json={"text": "budget.xlsx — 1 sheet"})
        return httpx.Response(200, json={"unchanged": False, "file": base64.b64encode(PATCHED).decode(),
                                         "mutations": [{"id": "sheet.mutation.x", "params": {}}],
                                         "ops": [], "report": "1. set_values"})

    _mock(monkeypatch, handler)
    assert asyncio.run(office.sheets_read(XLSX, "budget.xlsx", target="'المبيعات'!A1:C4")) == "budget.xlsx — 1 sheet"
    path, form = seen[0]
    assert path == "/v1/sheets/read" and form["file"] == XLSX
    assert json.loads(form["request"])["target"] == "'المبيعات'!A1:C4"

    r = asyncio.run(office.sheets_apply(XLSX, "budget.xlsx", [{"op": "clear", "target": "A1"}]))
    assert r["bytes"] == PATCHED and r["mutations"][0]["id"] == "sheet.mutation.x"
    assert json.loads(seen[1][1]["request"])["edits"] == [{"op": "clear", "target": "A1"}]

    asyncio.run(office.sheets_apply(None, "new.xlsx", [], create={"sheet": "ورقة1", "rightToLeft": True}))
    assert "file" not in seen[2][1] and json.loads(seen[2][1]["request"])["create"]["rightToLeft"] is True


def test_the_engine_s_own_words_reach_the_model(monkeypatch, tmp_path):
    _on(monkeypatch)
    (tmp_path / "b.xlsx").write_bytes(XLSX)
    _mock(monkeypatch, lambda r: httpx.Response(422, json={"error": '1. merge: there is no sheet "Nope"'}))
    out = _run({"action": "edit", "path": "b.xlsx", "ops": [{"op": "merge", "target": "Nope!A1:B2"}]}, _ws(tmp_path))
    assert out == 'Error: 1. merge: there is no sheet "Nope" — nothing was changed.'
    assert (tmp_path / "b.xlsx").read_bytes() == XLSX
    _mock(monkeypatch, lambda r: httpx.Response(503))
    assert "unavailable" in _run({"action": "read", "path": "b.xlsx"}, _ws(tmp_path))


# ---- the executor ------------------------------------------------------------------------------

def test_edit_writes_the_file_keeps_the_old_version_and_tells_an_open_editor(monkeypatch, tmp_path):
    _on(monkeypatch)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "b.xlsx").write_bytes(XLSX)
    mutations = [{"id": "sheet.mutation.set-range-values", "params": {"unitId": "book"}}]

    def handler(request):
        assert _form(request)["file"] == XLSX
        return httpx.Response(200, json={"unchanged": False, "file": base64.b64encode(PATCHED).decode(),
                                         "mutations": mutations, "ops": [],
                                         "report": "1. set_values: 1×1 values at Sheet1!B3\nSheet1!B3 now: 150,000.00"})

    _mock(monkeypatch, handler)
    out = _run({"action": "edit", "path": "reports/b.xlsx", "intent": "Raise salaries",
                "ops": [{"op": "set_values", "target": "B3", "values": [[150000]]}]}, _ws(tmp_path))
    assert out["_model"].startswith("Edited reports/b.xlsx.\n1. set_values") and "150,000.00" in out["_model"]
    ui = out["_ui"]
    assert ui["action"] == "sheets_command" and ui["path"] == "reports/b.xlsx" and ui["mutations"] == mutations
    assert ui["intent"] == "Raise salaries" and ui["version"]
    assert (tmp_path / "reports" / "b.xlsx").read_bytes() == PATCHED
    kept = versions.listing(tmp_path, "reports/b.xlsx")
    assert kept and versions.read(tmp_path, "reports/b.xlsx", kept[0]["id"]) == XLSX   # the old file, kept


def test_a_save_in_the_editor_meanwhile_is_edited_again_once(monkeypatch, tmp_path):
    _on(monkeypatch)
    f = tmp_path / "b.xlsx"
    f.write_bytes(XLSX)
    calls = []

    def handler(request):
        sent = _form(request)["file"]
        calls.append(sent)
        if len(calls) == 1:
            f.write_bytes(b"PK\x03\x04 saved by hand")    # the person's save lands while the edit runs
        return httpx.Response(200, json={"unchanged": False, "file": base64.b64encode(PATCHED + sent[-4:]).decode(),
                                         "mutations": [], "ops": [], "report": "done"})

    _mock(monkeypatch, handler)
    out = _run({"action": "edit", "path": "b.xlsx", "ops": [{"op": "clear", "target": "A1"}]}, _ws(tmp_path))
    assert calls == [XLSX, b"PK\x03\x04 saved by hand"]          # applied again, to the newer file
    assert f.read_bytes() == PATCHED + b"hand" and out["_ui"]["action"] == "sheets_command"


def test_nothing_to_change_writes_nothing(monkeypatch, tmp_path):
    _on(monkeypatch)
    (tmp_path / "b.xlsx").write_bytes(XLSX)
    _mock(monkeypatch, lambda r: httpx.Response(200, json={"unchanged": True, "file": None, "mutations": [],
                                                           "ops": [], "report": "1. clear: cleared A1"}))
    out = _run({"action": "edit", "path": "b.xlsx", "ops": [{"op": "clear", "target": "A1"}]}, _ws(tmp_path))
    assert out.startswith("Nothing in b.xlsx changed.") and not versions.listing(tmp_path, "b.xlsx")


def test_create_makes_a_new_workbook_and_opens_it(monkeypatch, tmp_path):
    _on(monkeypatch)
    seen = []

    def handler(request):
        seen.append(json.loads(_form(request)["request"]))
        return httpx.Response(200, json={"unchanged": False, "file": base64.b64encode(PATCHED).decode(),
                                         "mutations": [], "ops": [], "report": "1. set_values"})

    _mock(monkeypatch, handler)
    out = _run({"action": "create", "path": "new/sales.xlsx", "target": "المبيعات", "rtl": True,
                "ops": [{"op": "set_values", "target": "A1", "values": [["المنتج"]]}]}, _ws(tmp_path))
    assert seen[0]["create"] == {"sheet": "المبيعات", "rightToLeft": True}
    assert (tmp_path / "new" / "sales.xlsx").read_bytes() == PATCHED
    assert out["_ui"] == {"type": "ui", "action": "open_canvas", "path": "new/sales.xlsx"}
    again = _run({"action": "create", "path": "new/sales.xlsx"}, _ws(tmp_path))
    assert "already exists" in again


def test_create_without_rtl_reads_the_workbook_s_language(monkeypatch, tmp_path):
    """DeepSeek dropped the optional `rtl` on a real create (super-dev, 2026-10-24) and needed a second call."""
    _on(monkeypatch)
    seen = []

    def handler(request):
        seen.append(json.loads(_form(request)["request"])["create"])
        return httpx.Response(200, json={"unchanged": False, "file": base64.b64encode(PATCHED).decode(),
                                         "mutations": [], "ops": [], "report": ""})

    _mock(monkeypatch, handler)
    arabic_values = [{"op": "set_values", "target": "A1", "values": [["البند", "الربع الأول"]]}]
    _run({"action": "create", "path": "a.xlsx", "ops": arabic_values}, _ws(tmp_path))
    _run({"action": "create", "path": "b.xlsx", "target": "الميزانية", "ops": []}, _ws(tmp_path))
    _run({"action": "create", "path": "c.xlsx", "target": "Budget", "ops": [{"op": "set_values", "target": "A1", "values": [["Item"]]}]}, _ws(tmp_path))
    _run({"action": "create", "path": "d.xlsx", "rtl": False, "ops": arabic_values}, _ws(tmp_path))
    assert [c["rightToLeft"] for c in seen] == [True, True, False, False]
    assert seen[0]["sheet"] == "ورقة1" and seen[2]["sheet"] == "Budget"


def test_notes_and_names_are_ops_the_tool_takes():
    assert sheets._check_ops([{"op": "note", "target": "B3", "text": "راجع"}, {"op": "define_name", "target": "D2:D9", "name": "Total"}]) is None
    items = sheets.SHEETS_TOOL["input_schema"]["properties"]["ops"]["items"]["properties"]
    assert {"note", "define_name"} <= set(items["op"]["enum"]) and "text" in items


@pytest.mark.parametrize("inp, says", [
    ({"action": "draw", "path": "b.xlsx"}, "action must be one of"),
    ({"action": "read", "path": ""}, "path"),
    ({"action": "read", "path": "b.csv"}, "not an .xlsx file"),
    ({"action": "read", "path": "../b.xlsx"}, "escapes"),
    ({"action": "read", "path": "missing.xlsx"}, "does not exist"),
    ({"action": "edit", "path": "b.xlsx"}, "edit needs `ops`"),
    ({"action": "edit", "path": "b.xlsx", "ops": [{"op": "explode", "target": "A1"}]}, "unknown op"),
    ({"action": "edit", "path": "b.xlsx", "ops": [{"op": "merge"}]}, "needs a `target`"),
    ({"action": "edit", "path": "b.xlsx", "ops": "A1=1"}, "must be a list"),
])
def test_mistakes_are_answered_before_the_service_is_called(monkeypatch, tmp_path, inp, says):
    _on(monkeypatch)
    (tmp_path / "b.xlsx").write_bytes(XLSX)
    _mock(monkeypatch, lambda r: pytest.fail("the service was called"))
    out = _run(inp, _ws(tmp_path))
    assert out.startswith("Error:") and says in out


# ---- what the person selected ----------------------------------------------------------------

def test_a_selection_in_a_workbook_reaches_the_model_with_its_sheet():
    from cycls._agent.harness.main import _with_selection
    from cycls._agent.web.server import _clean_selection
    raw = {"path": "reports/ميزانية.xlsx", "frame": None, "page": "الميزانية",
           "nodes": [{"name": "B8:E8", "type": "cells"}, {"name": "B4", "type": "cell", "text": "47,000.00"}]}
    sel = _clean_selection(raw)
    assert sel == {"path": "reports/ميزانية.xlsx", "frame": None, "page": "الميزانية", "nodes": raw["nodes"]}
    assert _with_selection("make this bold", sel)[-1]["text"] == \
        '[Selected in reports/ميزانية.xlsx sheet "الميزانية": B8:E8 (cells), B4 (cell) "47,000.00"]'
    assert _clean_selection({**raw, "path": "reports/x.csv"}) is None
    assert _clean_selection({**raw, "path": "../x.xlsx"}) is None

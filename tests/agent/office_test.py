"""Cycls Sheets and Cycls Docs (the office editors): who gets it, the config the browser sees, the route that answers
per file, and the client over a mocked service. No service is contacted."""
import asyncio
import types
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from cycls._agent.office import client as office


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("OFFICE_URL", "OFFICE_SECRET", "OFFICE_EDITOR_URL", "SHEETS_ORGS", "DOCS_ORGS"):
        monkeypatch.delenv(k, raising=False)


def _ws(tmp_path, subject="org1:user1", ws=None):
    return types.SimpleNamespace(root=tmp_path, subject=subject, ws=ws)


# ---- who gets it -------------------------------------------------------------------------------

def test_the_url_alone_does_not_switch_sheets_on(monkeypatch, tmp_path):
    assert not office.configured() and not office.offered(_ws(tmp_path))
    monkeypatch.setenv("OFFICE_URL", "https://office.test/")
    assert office.configured() and not office.offered(_ws(tmp_path))          # nobody on the list
    monkeypatch.setenv("SHEETS_ORGS", "org2, org1")
    assert office.offered(_ws(tmp_path)) and not office.offered(_ws(tmp_path, "org3:u"))
    assert not office.offered(_ws(tmp_path), "docs")                          # Docs has its own list
    monkeypatch.setenv("SHEETS_ORGS", "solo")
    assert office.offered(_ws(tmp_path, "solo"))                              # a personal account
    monkeypatch.setenv("SHEETS_ORGS", "t-team")
    assert office.offered(_ws(tmp_path, "org9:u", ws="t-team"))               # a team workspace
    monkeypatch.setenv("SHEETS_ORGS", "*")
    assert office.offered(_ws(tmp_path, "anyone"))
    assert not office.offered(_ws(tmp_path), "slides")                        # not a product


def test_the_editor_url_is_the_service_unless_set(monkeypatch):
    assert office.editor_url() is None
    monkeypatch.setenv("OFFICE_URL", "https://office.test/")
    assert office.editor_url() == "https://office.test"
    monkeypatch.setenv("OFFICE_EDITOR_URL", "https://editors.test//")
    assert office.editor_url() == "https://editors.test"


def test_the_browser_is_told_sheets_exists_only_when_configured(monkeypatch):
    from cycls._agent.web.server import Config
    assert "sheets_editor" not in Config().public()
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    public = Config().public()
    assert public["sheets_editor"] is True
    assert "SHEETS_ORGS" not in str(public) and "office.test" not in str(public)   # the list and URL stay server-side


# ---- the route ---------------------------------------------------------------------------------

def _app(ws):
    from cycls._agent.web.office_routes import office_router
    app = FastAPI()
    app.include_router(office_router(Depends(lambda: ws)))
    return TestClient(app)


def test_the_route_answers_per_file_and_per_organisation(monkeypatch, tmp_path):
    (tmp_path / "budget.xlsx").write_bytes(b"PK\x03\x04")
    (tmp_path / "notes.txt").write_text("hi")
    c = _app(_ws(tmp_path))
    assert c.get("/office/sheets", params={"path": "notes.txt"}).status_code == 400
    assert c.get("/office/sheets", params={"path": "missing.xlsx"}).status_code == 404
    assert c.get("/office/sheets", params={"path": "../outside.xlsx"}).status_code in (400, 403, 404)
    assert c.get("/office/sheets", params={"path": "budget.xlsx"}).json() == {"editor": False, "reason": "off"}

    monkeypatch.setenv("OFFICE_URL", "https://office.test/")
    monkeypatch.setenv("SHEETS_ORGS", "org1")
    got = c.get("/office/sheets", params={"path": "budget.xlsx"}).json()
    assert got == {"editor": True, "url": "https://office.test/sheets/", "name": "budget.xlsx"}
    other = _app(_ws(tmp_path, "org2:u"))
    assert other.get("/office/sheets", params={"path": "budget.xlsx"}).json()["editor"] is False


# ---- the client over a mocked service ---------------------------------------------------------

_REAL_CLIENT = httpx.AsyncClient


def _mock(monkeypatch, handler):
    monkeypatch.setattr(office.httpx, "AsyncClient",
                        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def test_the_client_sends_the_key_and_never_follows_a_redirect(monkeypatch):
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("OFFICE_SECRET", "s" * 40)
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True, "engine": {"tag": "v1.2.0"}})
        return httpx.Response(302, headers={"location": "https://elsewhere.test/"})

    _mock(monkeypatch, handler)
    assert asyncio.run(office.health())["engine"]["tag"] == "v1.2.0"
    assert seen[0].headers["authorization"] == "Bearer " + "s" * 40
    with pytest.raises(office.Unavailable):
        asyncio.run(office.smoke())
    assert all(r.url.host == "office.test" for r in seen)


def test_the_client_says_what_went_wrong(monkeypatch):
    with pytest.raises(office.Unavailable, match="not configured"):
        asyncio.run(office.health())
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    _mock(monkeypatch, lambda r: httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(office.Unavailable, match="refused the key"):
        asyncio.run(office.smoke())

    def down(request):
        raise httpx.ConnectError("no route", request=request)

    _mock(monkeypatch, down)
    with pytest.raises(office.Unavailable, match="unreachable"):
        asyncio.run(office.health())


# ---- opening a workbook for the editor -------------------------------------------------------

def test_open_reads_once_then_serves_the_cache(monkeypatch, tmp_path):
    import gzip
    import json

    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("SHEETS_ORGS", "org1")
    (tmp_path / "b.xlsx").write_bytes(b"PK\x03\x04 workbook")
    calls = []

    async def read_xlsx(data, name=None):
        calls.append((data, name))
        return {"workbook": {"id": "book", "name": name, "sheetOrder": ["s1"]}, "notices": [{"kind": "chart", "message": "kept"}],
                "activeSheet": "s1", "stats": {"cells": 3}}

    monkeypatch.setattr(office, "read_xlsx", read_xlsx)
    c = _app(_ws(tmp_path))
    first = c.get("/office/sheets/open", params={"path": "b.xlsx"})
    assert first.status_code == 200 and first.headers["x-version"] and first.headers["x-modified"]
    body = first.json()                       # the client decoded the gzip
    assert body["snapshot"]["name"] == "b" and body["activeSheet"] == "s1" and body["notices"][0]["kind"] == "chart"
    assert body["version"] == first.headers["x-version"]
    cached = list((tmp_path / ".cache" / "sheets").glob("*.json.gz"))
    assert len(cached) == 1 and json.loads(gzip.decompress(cached[0].read_bytes()))["version"] == body["version"]

    again = c.get("/office/sheets/open", params={"path": "b.xlsx"})
    assert again.json() == body and len(calls) == 1          # the second open is the cache

    (tmp_path / "b.xlsx").write_bytes(b"PK\x03\x04 changed")  # a new version is read again
    assert c.get("/office/sheets/open", params={"path": "b.xlsx"}).json()["version"] != body["version"]
    assert len(calls) == 2


def test_version_is_the_one_open_and_save_name(monkeypatch, tmp_path):
    """An open editor asks for the file's version after it may have changed some other way; it must be the same
    version open answers with (and a save names as its base)."""
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    (tmp_path / "b.xlsx").write_bytes(b"PK\x03\x04 workbook")
    c = _app(_ws(tmp_path))
    assert c.get("/office/sheets/version", params={"path": "b.xlsx"}).status_code == 403   # not switched on
    monkeypatch.setenv("SHEETS_ORGS", "org1")

    async def read_xlsx(data, name=None):
        return {"workbook": {"id": "book"}, "notices": []}

    monkeypatch.setattr(office, "read_xlsx", read_xlsx)
    opened = c.get("/office/sheets/open", params={"path": "b.xlsx"}).json()["version"]
    got = c.get("/office/sheets/version", params={"path": "b.xlsx"}).json()
    assert got["version"] == opened and got["modified"]
    (tmp_path / "b.xlsx").write_bytes(b"PK\x03\x04 written by a script")
    assert c.get("/office/sheets/version", params={"path": "b.xlsx"}).json()["version"] != opened
    assert c.get("/office/sheets/version", params={"path": "missing.xlsx"}).status_code == 404


def test_open_says_why_it_cannot(monkeypatch, tmp_path):
    (tmp_path / "b.xlsx").write_bytes(b"PK\x03\x04")
    c = _app(_ws(tmp_path))
    assert c.get("/office/sheets/open", params={"path": "b.xlsx"}).status_code == 403     # not switched on
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("SHEETS_ORGS", "*")

    async def refuse(data, name=None):
        raise office.Refused("not a zip (an Office file is one)", 422)

    monkeypatch.setattr(office, "read_xlsx", refuse)
    r = c.get("/office/sheets/open", params={"path": "b.xlsx"})
    assert r.status_code == 422 and "not a zip" in r.json()["detail"]

    async def down(data, name=None):
        raise office.Unavailable("the office service is unreachable (ConnectError)")

    monkeypatch.setattr(office, "read_xlsx", down)
    assert c.get("/office/sheets/open", params={"path": "b.xlsx"}).status_code == 503

    from cycls._agent.web import office_routes
    monkeypatch.setattr(office_routes, "MAX_BYTES", 2)
    assert c.get("/office/sheets/open", params={"path": "b.xlsx"}).status_code == 413
    assert c.get("/office/sheets", params={"path": "b.xlsx"}).json() == {"editor": False, "reason": "too-large"}


def test_read_xlsx_posts_the_bytes_and_maps_a_refusal(monkeypatch):
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    seen = []

    def handler(request):
        seen.append(request)
        if request.content == b"bad":
            return httpx.Response(422, json={"error": "not a zip"})
        return httpx.Response(200, json={"workbook": {"id": "book"}, "notices": [], "stats": {}})

    _mock(monkeypatch, handler)
    assert asyncio.run(office.read_xlsx(b"PK..", name="b"))["workbook"]["id"] == "book"
    assert seen[0].url.path == "/v1/xlsx/read" and seen[0].url.params["name"] == "b"
    with pytest.raises(office.Refused, match="not a zip") as e:
        asyncio.run(office.read_xlsx(b"bad"))
    assert e.value.status == 422


# ---- saving -------------------------------------------------------------------------------------

def test_save_patches_through_the_service_and_keeps_versions(monkeypatch, tmp_path):
    import gzip
    import json

    from cycls._agent.design.store import version_of

    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("SHEETS_ORGS", "org1")
    original = b"PK\x03\x04 original workbook"
    (tmp_path / "b.xlsx").write_bytes(original)
    sent = []

    async def patch_xlsx(data, snapshot_gz):
        snap = json.loads(gzip.decompress(snapshot_gz))
        sent.append((data, snap))
        if snap.get("same"):
            return {"unchanged": True, "bytes": None, "summary": {"cellsWritten": 0}}
        return {"unchanged": False, "bytes": b"PK\x03\x04 patched " + json.dumps(snap).encode(), "summary": {"cellsWritten": 1}}

    monkeypatch.setattr(office, "patch_xlsx", patch_xlsx)
    c = _app(_ws(tmp_path))
    v0 = version_of(original)

    same = c.put("/office/sheets/save", params={"path": "b.xlsx", "base": v0}, content=gzip.compress(b'{"same": true}'))
    assert same.status_code == 200 and same.json() == {"version": v0, "unchanged": True, "summary": {"cellsWritten": 0}}
    assert (tmp_path / "b.xlsx").read_bytes() == original

    saved = c.put("/office/sheets/save", params={"path": "b.xlsx", "base": v0}, content=b'{"edit": 1}')   # plain JSON is gzipped here
    assert saved.status_code == 200 and saved.json()["unchanged"] is False
    stamp = datetime.fromtimestamp((tmp_path / "b.xlsx").stat().st_mtime, timezone.utc).isoformat()
    assert saved.json()["modified"] == stamp, "the editor's Last modified follows its own saves"
    v1 = saved.json()["version"]
    assert v1 != v0 and (tmp_path / "b.xlsx").read_bytes().startswith(b"PK\x03\x04 patched")
    assert sent[-1] == (original, {"edit": 1})
    assert list((tmp_path / ".versions").rglob("*")), "the replaced version is kept"

    stale = c.put("/office/sheets/save", params={"path": "b.xlsx", "base": v0}, content=gzip.compress(b'{"edit": 2}'))
    assert stale.status_code == 412 and stale.json()["version"] == v1
    kept = c.put("/office/sheets/save", params={"path": "b.xlsx", "base": v0, "force": "true"}, content=gzip.compress(b'{"edit": 2}'))
    assert kept.status_code == 200 and b'"edit": 2' in (tmp_path / "b.xlsx").read_bytes()


def test_save_says_why_it_cannot(monkeypatch, tmp_path):
    (tmp_path / "b.xlsx").write_bytes(b"PK\x03\x04")
    c = _app(_ws(tmp_path))
    assert c.put("/office/sheets/save", params={"path": "b.xlsx"}, content=b"{}").status_code == 403
    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("SHEETS_ORGS", "*")
    assert c.put("/office/sheets/save", params={"path": "b.xlsx"}, content=b"").status_code == 400

    async def refuse(data, snapshot_gz):
        raise office.Refused("the workbook sent is not a workbook snapshot", 422)

    monkeypatch.setattr(office, "patch_xlsx", refuse)
    r = c.put("/office/sheets/save", params={"path": "b.xlsx"}, content=b"{}")
    assert r.status_code == 422 and "not a workbook snapshot" in r.json()["detail"]

    async def down(data, snapshot_gz):
        raise office.Unavailable("the office service is unreachable (ConnectError)")

    monkeypatch.setattr(office, "patch_xlsx", down)
    assert c.put("/office/sheets/save", params={"path": "b.xlsx"}, content=b"{}").status_code == 503
    assert (tmp_path / "b.xlsx").read_bytes() == b"PK\x03\x04"


def test_patch_xlsx_sends_both_parts_and_reads_the_answer(monkeypatch):
    import base64
    import json

    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    seen = []

    def handler(request):
        seen.append(request)
        if b"same" in request.content:
            return httpx.Response(200, json={"unchanged": True, "summary": {"cellsWritten": 0}})
        summary = base64.b64encode(json.dumps({"cellsWritten": 2}).encode()).decode()
        return httpx.Response(200, content=b"PK new", headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "x-patch-summary": summary})

    _mock(monkeypatch, handler)
    out = asyncio.run(office.patch_xlsx(b"PK old", b"same"))
    assert out == {"unchanged": True, "bytes": None, "summary": {"cellsWritten": 0}}
    out = asyncio.run(office.patch_xlsx(b"PK old", b"edit"))
    assert out == {"unchanged": False, "bytes": b"PK new", "summary": {"cellsWritten": 2}}
    assert seen[-1].url.path == "/v1/xlsx/patch" and b'name="file"' in seen[-1].content and b'name="snapshot"' in seen[-1].content


# ---- Cycls Docs: the same routes for Word documents -------------------------------------------

def _docx(path, body_xml):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body>{body_xml}</w:body></w:document>')


def test_docs_opens_word_files_left_to_right_and_right_to_left(monkeypatch, tmp_path):
    _docx(tmp_path / "report.docx", "<w:p><w:r><w:t>Hello</w:t></w:r></w:p>")
    _docx(tmp_path / "arabic.docx", "<w:p><w:pPr><w:bidi/></w:pPr><w:r><w:t>مرحبا</w:t></w:r></w:p>")
    _docx(tmp_path / "off.docx", '<w:p><w:pPr><w:bidi w:val="0"/></w:pPr></w:p>')
    (tmp_path / "budget.xlsx").write_bytes(b"PK\x03\x04")
    c = _app(_ws(tmp_path))
    assert c.get("/office/docs", params={"path": "budget.xlsx"}).status_code == 400
    assert c.get("/office/docs", params={"path": "report.docx"}).json() == {"editor": False, "reason": "off"}

    monkeypatch.setenv("OFFICE_URL", "https://office.test/")
    monkeypatch.setenv("SHEETS_ORGS", "org1")
    assert c.get("/office/docs", params={"path": "report.docx"}).json()["editor"] is False, "Sheets on is not Docs on"
    monkeypatch.setenv("DOCS_ORGS", "org1")
    assert c.get("/office/docs", params={"path": "report.docx"}).json() == {
        "editor": True, "url": "https://office.test/docs/", "name": "report.docx"}
    assert c.get("/office/docs", params={"path": "arabic.docx"}).json()["editor"] is True, "Arabic documents open in Docs too"
    assert c.get("/office/docs", params={"path": "off.docx"}).json()["editor"] is True


def test_docs_open_and_save_go_through_the_docx_calls(monkeypatch, tmp_path):
    import gzip
    import json

    from cycls._agent.design.store import version_of

    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("DOCS_ORGS", "*")
    original = b"PK\x03\x04 original document"
    (tmp_path / "r.docx").write_bytes(original)
    reads, patches = [], []

    async def read_docx(data, name=None):
        reads.append(name)
        return {"document": {"id": "doc", "title": name, "body": {"dataStream": "Hi\r\n"}}, "notices": [],
                "readonly": True, "stats": {"paragraphs": 1}}

    async def patch_docx(data, snapshot_gz):
        patches.append((data, json.loads(gzip.decompress(snapshot_gz))))
        return {"unchanged": False, "bytes": b"PK\x03\x04 patched document", "summary": {"paragraphs": 1}}

    monkeypatch.setattr(office, "read_docx", read_docx)
    monkeypatch.setattr(office, "patch_docx", patch_docx)
    c = _app(_ws(tmp_path))
    opened = c.get("/office/docs/open", params={"path": "r.docx"}).json()
    assert opened["snapshot"]["title"] == "r" and opened["readonly"] is True and opened["version"] == version_of(original)
    assert list((tmp_path / ".cache" / "docs").glob("*.json.gz")), "kept apart from the workbooks' cache"
    c.get("/office/docs/open", params={"path": "r.docx"})
    assert reads == ["r"]

    saved = c.put("/office/docs/save", params={"path": "r.docx", "base": opened["version"]}, content=b'{"body": 1}')
    assert saved.status_code == 200 and saved.json()["unchanged"] is False
    assert (tmp_path / "r.docx").read_bytes() == b"PK\x03\x04 patched document" and patches[0] == (original, {"body": 1})
    stale = c.put("/office/docs/save", params={"path": "r.docx", "base": opened["version"]}, content=b"{}")
    assert stale.status_code == 412 and stale.json()["detail"] == "This document changed since it was opened."


def test_read_and_patch_docx_call_the_service(monkeypatch):
    import gzip

    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("OFFICE_SECRET", "s")
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers.get("content-type", "")))
        if request.url.path == "/v1/docx/read":
            return httpx.Response(200, json={"document": {"id": "d"}, "notices": [], "readonly": False})
        return httpx.Response(200, content=b"PK patched", headers={"content-type": "application/octet-stream"})

    _mock(monkeypatch, handler)
    got = asyncio.run(office.read_docx(b"PK", name="r"))
    assert got["document"]["id"] == "d"
    patched = asyncio.run(office.patch_docx(b"PK", gzip.compress(b"{}")))
    assert patched["bytes"] == b"PK patched" and not patched["unchanged"]
    assert seen[0] == ("/v1/docx/read", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert seen[1][0] == "/v1/docx/patch" and seen[1][1].startswith("multipart/form-data")


def test_every_save_is_logged_with_what_it_changed_and_the_editors_trail(monkeypatch, tmp_path, capsys):
    import gzip
    import json
    from urllib.parse import quote

    monkeypatch.setenv("OFFICE_URL", "https://office.test")
    monkeypatch.setenv("DOCS_ORGS", "*")
    (tmp_path / "r.docx").write_bytes(b"PK\x03\x04 original")

    async def patch_docx(data, snapshot_gz):
        same = json.loads(gzip.decompress(snapshot_gz)).get("same")
        if same:
            return {"unchanged": True, "bytes": None, "summary": {"paragraphsChanged": 0, "notices": []}}
        return {"unchanged": False, "bytes": b"PK\x03\x04 patched",
                "summary": {"paragraphsChanged": 1, "paragraphsRemoved": 4, "notices": [{"kind": "x"}]}}

    monkeypatch.setattr(office, "patch_docx", patch_docx)
    c = _app(_ws(tmp_path))
    trail = ["0.0 load r.docx@v1", "12.4 operation.set-selections 113-140", "12.5 mutation.rich-text-editing r113 d27 i1"]
    capsys.readouterr()
    r = c.put("/office/docs/save", params={"path": "r.docx"}, content=b'{"edit": 1}',
              headers={"X-Edit-Trail": quote(json.dumps(trail))})
    assert r.status_code == 200
    lines = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if '"office_save"' in ln]
    assert len(lines) == 1
    got = lines[0]
    assert got["outcome"] == "written" and got["product"] == "docs" and got["path"] == "r.docx"
    assert got["summary"] == {"paragraphsChanged": 1, "paragraphsRemoved": 4, "notices": 1}
    assert got["trail"] == trail and got["version"] and got["replaced"]

    c.put("/office/docs/save", params={"path": "r.docx"}, content=b'{"same": true}', headers={"X-Edit-Trail": "not json"})
    unchanged = [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if '"office_save"' in ln][0]
    assert unchanged["outcome"] == "unchanged" and unchanged["trail"] is None


def test_the_trail_header_is_bounded():
    import json
    from urllib.parse import quote

    from cycls._agent.web.office_routes import edit_trail
    assert edit_trail(None) is None and edit_trail("%7B") is None and edit_trail(quote('{"a": 1}')) is None
    long = [f"{i} " + "x" * 300 for i in range(100)]
    got = edit_trail(quote(json.dumps(long)))
    assert len(got) == 64 and all(len(x) <= 120 for x in got) and got[0].startswith("0 ")

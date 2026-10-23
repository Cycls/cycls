"""Cycls Sheets (the office editors): who gets it, the config the browser sees, the route that answers
per file, and the client over a mocked service. No service is contacted."""
import asyncio
import types

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

"""WOPI host + the Web.office_edit() opt-in — the editable-Office (Collabora) path."""
import base64
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from cycls._agent.web import wopi
from cycls._agent.web.builder import Web
from cycls._agent.web.server import Config
from cycls._app.auth import User
from cycls._agent.web.routers import install_routers


# ---- Web.office_edit() opt-in flows to the public config ----

def test_office_edit_builder_is_opt_in_and_immutable():
    assert Web()._office_edit is False                 # off by default
    assert Web().office_edit()._office_edit is True
    assert Web().office_edit(False)._office_edit is False
    base = Web()
    base.office_edit()                                 # returns a copy…
    assert base._office_edit is False                  # …the original is untouched


def test_config_carries_office_edit_flag():
    assert Config(name="t", office_edit=True).public()["office_edit"] is True
    assert Config(name="t").public()["office_edit"] is False


def test_final_flag_needs_optin_AND_service(monkeypatch):
    # The bool the client reads = author opted in AND Collabora is wired (env).
    final = lambda intent: bool(intent) and wopi.configured()
    monkeypatch.delenv("COLLABORA_URL", raising=False)
    assert final(True) is False                        # opted in, no service → off
    monkeypatch.setenv("COLLABORA_URL", "https://collabora.cycls.ai")
    assert final(True) is True                         # opted in, service wired → on
    assert final(False) is False                       # service wired but not opted in → off


# ---- token: signed, single-file scoped, expiring ----

def test_token_roundtrip_and_rejects_tampering(monkeypatch):
    monkeypatch.setenv("WOPI_SECRET", "s3cret")
    monkeypatch.setattr(wopi, "_SECRET", None)
    t = wopi.mint("org_1:user_1", "u-user_1", "a/b.docx", "user_1", True)
    c = wopi.verify(t)
    assert c and c["p"] == "a/b.docx" and c["rw"] is True and c["s"] == "org_1:user_1"
    assert wopi.verify(t[:-2] + "xx") is None           # broken signature
    assert wopi.verify("not-a-token") is None
    assert wopi.verify(None) is None


def test_token_expires(monkeypatch):
    monkeypatch.setenv("WOPI_SECRET", "s3cret")
    monkeypatch.setattr(wopi, "_SECRET", None)
    monkeypatch.setattr(wopi, "_TOKEN_TTL", -1)         # minted already-expired
    assert wopi.verify(wopi.mint("s", "w", "p", "u", True)) is None


def test_editable_and_configured(monkeypatch):
    assert wopi.editable("a.docx") and wopi.editable("B.XLSX") and wopi.editable("c.pptx")
    assert not wopi.editable("d.pdf") and not wopi.editable("e.txt")
    monkeypatch.delenv("COLLABORA_URL", raising=False)
    assert wopi.configured() is False
    monkeypatch.setenv("COLLABORA_URL", "https://x")
    assert wopi.configured() is True


# ---- the WOPI host endpoints, over a real workspace ----

def _client(tmp_path):
    user = User(id="user_1", org_id="org_1")
    stub = SimpleNamespace(prod=False, _auth_provider=None,
                           config=SimpleNamespace(workspaces="member", max_upload=512))
    app = FastAPI()
    install_routers(stub, app, Depends(lambda: user), tmp_path, f"file://{tmp_path}")
    return TestClient(app)


def _seed(tmp_path, rel, data):
    p = tmp_path / "org_1" / "ws" / "u-user_1" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _tok(path, rw=True):
    return wopi.mint("org_1:user_1", "u-user_1", path, "user_1", rw)


def _fid(path):
    return base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


def test_checkfileinfo_and_getfile(tmp_path, monkeypatch):
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    _seed(tmp_path, "deck.pptx", b"PPTXBYTES")
    c = _client(tmp_path)
    fid, tok = _fid("deck.pptx"), _tok("deck.pptx")

    info = c.get(f"/wopi/files/{fid}", params={"access_token": tok})
    assert info.status_code == 200
    j = info.json()
    assert j["BaseFileName"] == "deck.pptx" and j["Size"] == 9 and j["UserCanWrite"] is True

    body = c.get(f"/wopi/files/{fid}/contents", params={"access_token": tok})
    assert body.status_code == 200 and body.content == b"PPTXBYTES"


def test_putfile_saves_back_to_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    p = _seed(tmp_path, "doc.docx", b"OLD")
    c = _client(tmp_path)
    fid, tok = _fid("doc.docx"), _tok("doc.docx")
    r = c.post(f"/wopi/files/{fid}/contents", params={"access_token": tok}, content=b"NEWBYTES")
    assert r.status_code == 200
    assert p.read_bytes() == b"NEWBYTES"                # the edit reached the real file


def test_readonly_token_cannot_save(tmp_path, monkeypatch):
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    p = _seed(tmp_path, "doc.docx", b"OLD")
    c = _client(tmp_path)
    fid, tok = _fid("doc.docx"), _tok("doc.docx", rw=False)
    r = c.post(f"/wopi/files/{fid}/contents", params={"access_token": tok}, content=b"NEW")
    assert r.status_code == 403 and p.read_bytes() == b"OLD"


def test_bad_and_mismatched_tokens_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    _seed(tmp_path, "doc.docx", b"X")
    c = _client(tmp_path)
    fid = _fid("doc.docx")
    assert c.get(f"/wopi/files/{fid}", params={"access_token": "garbage"}).status_code == 401
    # a valid token, but for a different file than the id in the URL
    assert c.get(f"/wopi/files/{fid}", params={"access_token": _tok("other.docx")}).status_code == 403


def test_editor_endpoint_returns_url_and_token(tmp_path, monkeypatch):
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    monkeypatch.setenv("COLLABORA_URL", "https://collabora.cycls.ai")
    async def fake_src(mime):
        return "https://collabora.cycls.ai/browser/abc/cool.html?"
    monkeypatch.setattr(wopi, "_editor_src", fake_src)
    _seed(tmp_path, "deck.pptx", b"X")
    c = _client(tmp_path)
    r = c.get("/wopi/editor", params={"path": "deck.pptx"})
    assert r.status_code == 200
    j = r.json()
    assert "cool.html?" in j["editor_url"] and "WOPISrc=" in j["editor_url"]
    assert wopi.verify(j["access_token"])["p"] == "deck.pptx"


def test_editor_rejects_non_office(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLABORA_URL", "https://x")
    _seed(tmp_path, "a.txt", b"X")
    c = _client(tmp_path)
    assert c.get("/wopi/editor", params={"path": "a.txt"}).status_code == 415

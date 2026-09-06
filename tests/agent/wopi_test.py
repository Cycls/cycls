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


# ---- Web.office_edit() (on by default when configured) flows to the config ----

def test_office_edit_defaults_on_and_is_immutable():
    assert Web()._office_edit is True                  # on by default
    assert Web().office_edit(False)._office_edit is False   # opt out
    assert Web().office_edit()._office_edit is True
    base = Web()
    base.office_edit(False)                            # returns a copy…
    assert base._office_edit is True                   # …the original is untouched


def test_config_carries_office_edit_flag():
    assert Config(name="t", office_edit=True).public()["office_edit"] is True
    assert Config(name="t").public()["office_edit"] is False


def test_final_flag_on_when_configured_unless_opted_out(monkeypatch):
    # The bool the client reads = (author didn't opt out) AND Collabora fully
    # wired (URL AND a shared secret). Default intent is on.
    final = lambda intent: bool(intent) and wopi.configured()
    monkeypatch.delenv("COLLABORA_URL", raising=False)
    monkeypatch.delenv("WOPI_SECRET", raising=False)
    assert final(True) is False                        # default-on, no service → off (PDF preview)
    monkeypatch.setenv("COLLABORA_URL", "https://collabora.cycls.ai")
    assert final(True) is False                        # URL but no shared secret → still off
    monkeypatch.setenv("WOPI_SECRET", "shared")
    assert final(True) is True                         # default-on + fully wired → on
    assert final(False) is False                       # fully wired but opted out → off


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
    monkeypatch.delenv("WOPI_SECRET", raising=False)
    assert wopi.configured() is False
    monkeypatch.setenv("COLLABORA_URL", "https://x")
    assert wopi.configured() is False              # URL alone isn't enough
    monkeypatch.setenv("WOPI_SECRET", "s")
    assert wopi.configured() is True               # both → on
    monkeypatch.delenv("COLLABORA_URL")
    assert wopi.configured() is False              # shared secret alone isn't enough


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


def test_checkfileinfo_carries_identity_and_postmessage(tmp_path, monkeypatch):
    """Co-editor cursor labels + host integration: real name/avatar, a stable
    OwnerId (the workspace, not the requester), and the page's PostMessageOrigin."""
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    _seed(tmp_path, "deck.pptx", b"X")
    c = _client(tmp_path)
    fid = _fid("deck.pptx")
    tok = wopi.mint("org_1:user_1", "u-user_1", "deck.pptx", "user_1", True,
                    name="Sara Ali", avatar="https://img/a.png", origin="https://app.cycls.ai")
    j = c.get(f"/wopi/files/{fid}", params={"access_token": tok}).json()
    assert j["UserFriendlyName"] == "Sara Ali"
    assert j["UserId"] == "user_1"                    # distinct per user → distinct cursors
    assert j["OwnerId"] == "u-user_1"                 # the workspace: same for every co-editor
    assert j["UserExtraInfo"]["avatar"] == "https://img/a.png"
    assert j["PostMessageOrigin"] == "https://app.cycls.ai"
    assert j["DisableInactiveMessages"] is True
    # No identity in the token → falls back to the id, and PostMessageOrigin to "*".
    j2 = c.get(f"/wopi/files/{fid}", params={"access_token": _tok("deck.pptx")}).json()
    assert j2["UserFriendlyName"] == "user_1" and "UserExtraInfo" not in j2
    assert j2["PostMessageOrigin"] == "*"


def test_editor_passes_identity_and_closebutton(tmp_path, monkeypatch):
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    monkeypatch.setenv("COLLABORA_URL", "https://collabora.cycls.ai")
    async def fake_src(mime):
        return "https://collabora.cycls.ai/browser/abc/cool.html?"
    monkeypatch.setattr(wopi, "_editor_src", fake_src)
    _seed(tmp_path, "deck.pptx", b"X")
    c = _client(tmp_path)
    r = c.get("/wopi/editor",
              params={"path": "deck.pptx", "name": "Sara", "avatar": "https://img/a.png"},
              headers={"origin": "https://app.cycls.ai"})
    j = r.json()
    assert "closebutton=false" in j["editor_url"]     # the canvas owns the close button
    claims = wopi.verify(j["access_token"])
    assert claims["n"] == "Sara" and claims["a"] == "https://img/a.png"
    assert claims["o"] == "https://app.cycls.ai"      # captured for PostMessageOrigin


def test_same_file_yields_one_session_for_every_coeditor():
    """Live co-editing hinges on one property: every user opening the same file
    produces the same WOPI file id (→ same WOPISrc), so Collabora joins them into
    a single session. The id is a pure function of the path, and two users in one
    team workspace hit the same path — so it cannot diverge, while their tokens
    still carry distinct identities for distinct cursors."""
    a = wopi.mint("org_1:user_1", "t-team", "shared/report.docx", "user_1", True, name="A")
    b = wopi.mint("org_1:user_2", "t-team", "shared/report.docx", "user_2", True, name="B")
    assert wopi.verify(a)["p"] == wopi.verify(b)["p"] == "shared/report.docx"  # same file scope
    assert wopi.verify(a)["u"] != wopi.verify(b)["u"]                          # distinct users
    assert _fid("shared/report.docx") == "c2hhcmVkL3JlcG9ydC5kb2N4"           # id from path alone


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
    assert "lang=en-US" in j["editor_url"]            # no lang → English, not a leftover default
    assert wopi.verify(j["access_token"])["p"] == "deck.pptx"


def test_editor_url_carries_the_caller_locale(tmp_path, monkeypatch):
    """The editor chrome follows the app's UI language; an unknown/absent locale
    falls back to English (the value lands in a URL, so it's a whitelist)."""
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    monkeypatch.setenv("COLLABORA_URL", "https://collabora.cycls.ai")
    async def fake_src(mime):
        return "https://collabora.cycls.ai/browser/abc/cool.html?"
    monkeypatch.setattr(wopi, "_editor_src", fake_src)
    _seed(tmp_path, "deck.pptx", b"X")
    c = _client(tmp_path)
    assert "lang=ar" in c.get("/wopi/editor", params={"path": "deck.pptx", "lang": "ar"}).json()["editor_url"]
    assert "lang=en-US" in c.get("/wopi/editor", params={"path": "deck.pptx", "lang": "en"}).json()["editor_url"]
    # a locale we don't ship (or a would-be injection) never reaches the URL raw
    assert "lang=en-US" in c.get("/wopi/editor", params={"path": "deck.pptx", "lang": "fr&x=1"}).json()["editor_url"]


def test_discovery_prefers_the_edit_action(monkeypatch):
    """An empty <action/> is falsy in ElementTree, so selection must use
    `is None`, not `or` — otherwise the 'view' action listed first would win."""
    xml = """<wopi-discovery><net-zone>
      <app name="application/vnd.openxmlformats-officedocument.presentationml.presentation">
        <action name="view" ext="pptx" urlsrc="https://c/view.html?"/>
        <action name="edit" ext="pptx" urlsrc="https://c/edit.html?"/>
      </app>
      <app name="application/vnd.oasis.opendocument.text">
        <action name="view" ext="odt" urlsrc="https://c/only-view.html?"/>
      </app>
    </net-zone></wopi-discovery>"""
    m = wopi._parse_discovery(xml)
    assert m["application/vnd.openxmlformats-officedocument.presentationml.presentation"] == "https://c/edit.html?"
    # no edit action → fall back to whatever the mimetype lists
    assert m["application/vnd.oasis.opendocument.text"] == "https://c/only-view.html?"


def test_editor_rejects_non_office(tmp_path, monkeypatch):
    monkeypatch.setenv("COLLABORA_URL", "https://x")
    monkeypatch.setenv("WOPI_SECRET", "s")
    _seed(tmp_path, "a.txt", b"X")
    c = _client(tmp_path)
    assert c.get("/wopi/editor", params={"path": "a.txt"}).status_code == 415


def test_lock_lifecycle_shared_via_workspace_db(tmp_path, monkeypatch):
    """Locks live in the workspace DB (shared across instances), not in process
    memory: LOCK → GET_LOCK → conflicting LOCK 409 → UNLOCK."""
    monkeypatch.setenv("WOPI_SECRET", "s"); monkeypatch.setattr(wopi, "_SECRET", None)
    _seed(tmp_path, "doc.docx", b"X")
    c = _client(tmp_path)
    fid, tok = _fid("doc.docx"), _tok("doc.docx")

    def op(name, lock):
        return c.post(f"/wopi/files/{fid}", params={"access_token": tok},
                      headers={"X-WOPI-Override": name, "X-WOPI-Lock": lock})

    assert op("GET_LOCK", "").headers.get("X-WOPI-Lock", "") == ""     # nothing held yet
    assert op("LOCK", "LOCK-1").status_code == 200                     # take it
    assert op("GET_LOCK", "").headers["X-WOPI-Lock"] == "LOCK-1"       # persisted
    conflict = op("LOCK", "LOCK-2")                                    # someone else tries
    assert conflict.status_code == 409 and conflict.headers["X-WOPI-Lock"] == "LOCK-1"
    assert op("UNLOCK", "LOCK-1").status_code == 200                   # release
    assert op("GET_LOCK", "").headers.get("X-WOPI-Lock", "") == ""     # gone

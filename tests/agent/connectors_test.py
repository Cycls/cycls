"""cycls.OAuth2: a signed state that names its user, PKCE end to end, a bearer
that refreshes itself, and routes that store the grant where its scope says."""
import asyncio, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse
import pytest
from cycls._agent import connectors as c, credentials
from cycls._app.db import workspace


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("CYCLS_SECRET_KEY", "k1")
    monkeypatch.setenv("GID", "cid")
    monkeypatch.setenv("GSECRET", "shh")


def _google(scope="user"):
    return c.OAuth2("google", authorize="https://accounts.google.com/o/oauth2/v2/auth",
                    token="https://oauth2.googleapis.com/token", client_id=c.env("GID"), secret=c.env("GSECRET"),
                    scopes=["https://www.googleapis.com/auth/drive.file"], scope=scope,
                    extra={"access_type": "offline", "prompt": "consent"})


def test_state_round_trips_and_rejects_tampering_and_age():
    s = c.sign({"c": "google", "n": "x"})
    assert c.verify(s)["n"] == "x"
    with pytest.raises(ValueError, match="bad state"):
        c.verify(s[:-1] + ("a" if s[-1] != "a" else "b"))
    with pytest.raises(ValueError, match="expired"):
        c.verify(c.sign({"c": "google"}, ttl=-1))


def test_authorize_url_carries_pkce_state_and_resolved_client_id():
    url = _google().authorize_url("http://h/cb", "st", "verifier-xyz")
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid"] and q["state"] == ["st"] and q["code_challenge_method"] == ["S256"]
    assert q["access_type"] == ["offline"] and "verifier-xyz" not in url


def test_bearer_refreshes_a_stale_grant_and_writes_it_back(tmp_path):
    ws = workspace("org:u1", tmp_path, base=f"file://{tmp_path}")
    g = _google()
    asyncio.run(credentials.put(ws, "google", {"access_token": "old", "refresh_token": "r", "expires_at": time.time() - 1}))
    fresh = {"access_token": "new", "refresh_token": None, "expires_at": time.time() + 3600}
    with patch.object(c.OAuth2, "_token", AsyncMock(return_value=fresh)) as tok:
        assert asyncio.run(g.bearer(ws)) == "new"
    tok.assert_awaited_once_with(grant_type="refresh_token", refresh_token="r")
    assert asyncio.run(credentials.get(ws, "google"))["refresh_token"] == "r"   # kept when the provider omits it
    assert asyncio.run(g.bearer(workspace("org:u2", tmp_path, base=f"file://{tmp_path}"))) is None


def test_mcp_handler_uses_the_grant_or_asks_to_connect(tmp_path):
    from cycls._agent import mcp as m
    from cycls._agent.tools import ToolContext
    m._discovered.clear()
    ws = workspace("org:u1", tmp_path, base=f"file://{tmp_path}")
    tool = SimpleNamespace(name="search_files", description="d", input_schema={"type": "object"})
    with patch.object(m, "_list", AsyncMock(return_value=[tool])) as listed, \
         patch.object(m, "_call", AsyncMock(return_value="found")) as called:
        _, handlers, _ = asyncio.run(m.MCP("https://drivemcp.googleapis.com/mcp/v1").name("drive").connector(_google()).discover())
        h = handlers["drive_search_files"]
        assert asyncio.run(h({}, ToolContext(None, ws)))["action"] == "connect"
        asyncio.run(credentials.put(ws, "google", {"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600}))
        assert asyncio.run(h({"q": "x"}, ToolContext(None, ws))) == "found"
    listed.assert_awaited_once_with("https://drivemcp.googleapis.com/mcp/v1", {})   # anonymous discovery
    called.assert_awaited_once_with("https://drivemcp.googleapis.com/mcp/v1", {"Authorization": "Bearer tok"}, "search_files", {"q": "x"})


def _app(tmp_path, *oauths):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls._app.auth import User
    from cycls._agent.web.routers import connectors_router
    user = User(id="u1")
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    app = FastAPI()
    app.include_router(connectors_router(SimpleNamespace(connectors=list(oauths)), Depends(lambda: ws),
                                         Depends(lambda: user), tmp_path, f"file://{tmp_path}"))
    return TestClient(app), ws


def test_routes_connect_list_and_disconnect(tmp_path):
    client, ws = _app(tmp_path, _google())
    assert client.get("/connectors").json() == [{"name": "google", "scope": "user", "connected": False}]
    url = client.post("/connectors/google/authorize").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == ["http://testserver/connectors/google/callback"]
    grant = {"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600}
    with patch.object(c.OAuth2, "exchange", AsyncMock(return_value=grant)) as ex:
        r = client.get("/connectors/google/callback", params={"code": "the-code", "state": q["state"][0]})
    assert r.status_code == 200 and "Connected" in r.text
    ex.assert_awaited_once()
    assert ex.await_args.args[0] == "the-code" and ex.await_args.args[1] == q["redirect_uri"][0]
    assert asyncio.run(credentials.get(ws, "google")) == grant
    assert client.get("/connectors").json()[0]["connected"] is True
    r = client.get("/connectors/google/callback", params={"code": "again", "state": q["state"][0]})
    assert r.status_code == 400                                                  # a state is spent once
    assert client.delete("/connectors/google").json() == {"ok": True}
    assert asyncio.run(credentials.get(ws, "google")) is None


def test_routes_refuse_a_bad_state_and_a_non_admin_on_shared(tmp_path):
    client, _ = _app(tmp_path, _google("workspace"))
    assert client.get("/connectors/google/callback", params={"code": "c", "state": "nope.bad"}).status_code == 400
    with patch("cycls._agent.web.routers._admin", AsyncMock(return_value=False)):
        assert client.post("/connectors/google/authorize").status_code == 403
        assert client.delete("/connectors/google").status_code == 403

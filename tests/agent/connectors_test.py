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
    g = _google()
    url = g.authorize_url(asyncio.run(g.client(None, "http://h/cb")), "http://h/cb", "st", "verifier-xyz")
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
    tok.assert_awaited_once_with({"token": g.token, "client_id": c._val(g.client_id), "resource": None}, grant_type="refresh_token", refresh_token="r")   # an old grant: the fixed app's
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


def _app(tmp_path, *oauths, user=None, ws_id=None):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls._app.auth import User
    from cycls._agent.web.routers import connectors_router, tools_router
    user = user or User(id="u1")
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}", ws=ws_id)
    app = FastAPI()
    app.include_router(connectors_router(SimpleNamespace(connectors=list(oauths)), Depends(lambda: ws),
                                         Depends(lambda: user), tmp_path, f"file://{tmp_path}"))
    app.include_router(tools_router(Depends(lambda: ws), Depends(lambda: user)))
    return TestClient(app), ws


def test_routes_connect_list_and_disconnect(tmp_path):
    client, ws = _app(tmp_path, _google())
    assert client.get("/connectors").json() == [{"name": "google", "title": None, "scope": "user", "description": None,
                                                 "kind": "oauth", "hint": None,
                                                 "about": None, "icon": None, "prompts": [], "use_cases": [], "skills": [],
                                                 "developer": None, "category": None, "website": None,
                                                 "privacy": None, "terms": None, "docs": None, "team": None,
                                                 "admin": False, "allowed": True, "org_admin": False, "connected": False,
                                                 "connected_as": None}]
    url = client.post("/connectors/google/authorize").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == ["http://testserver/connectors/google/callback"]
    grant = {"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600}
    with patch.object(c.OAuth2, "exchange", AsyncMock(return_value=grant)) as ex:
        r = client.get("/connectors/google/callback", params={"code": "the-code", "state": q["state"][0]})
    assert r.status_code == 200 and "Connected" in r.text and "cycls:connected" in r.text
    ex.assert_awaited_once()
    assert ex.await_args.args[1:3] == ("the-code", q["redirect_uri"][0])
    assert asyncio.run(credentials.get(ws, "google")) == grant
    assert client.get("/connectors").json()[0]["connected"] is True
    assert client.put("/connectors/google/key", json={"key": "k"}).json()["detail"] == "This connector signs in with OAuth"
    r = client.get("/connectors/google/callback", params={"code": "again", "state": q["state"][0]})
    assert r.status_code == 400                                                  # a state is spent once
    assert client.delete("/connectors/google").json() == {"ok": True}
    assert asyncio.run(credentials.get(ws, "google")) is None


def test_connect_and_disconnect_are_audited(tmp_path):
    client, _ = _app(tmp_path, _google())
    state = parse_qs(urlparse(client.post("/connectors/google/authorize").json()["url"]).query)["state"][0]
    grant = {"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600}
    lines = []
    with patch.object(c.OAuth2, "exchange", AsyncMock(return_value=grant)), \
         patch("cycls._agent.web.routers.log", lambda level, **f: lines.append((level, f))):
        client.get("/connectors/google/callback", params={"code": "c", "state": state})
        client.delete("/connectors/google")
    assert [(l, f["action"], f["connector"]) for l, f in lines if l == "connector"] == \
        [("connector", "connected", "google"), ("connector", "disconnected", "google")]


def test_routes_refuse_a_bad_state_and_a_non_admin_on_shared(tmp_path):
    from cycls._app.auth import User
    member = User(id="m", org_id="o1", org_role="member")
    client, _ = _app(tmp_path, _google("workspace"), user=member, ws_id="t-shared")
    assert client.get("/connectors/google/callback", params={"code": "c", "state": "nope.bad"}).status_code == 400
    with patch("cycls._agent.web.routers._admin", AsyncMock(return_value=False)):
        assert client.post("/connectors/google/authorize?scope=workspace").status_code == 403
        assert client.delete("/connectors/google?scope=workspace").status_code == 403
    solo = _app(tmp_path, _google("workspace"), user=member)[0]                  # personal workspace: nothing to share with
    assert solo.post("/connectors/google/authorize?scope=workspace").status_code == 400


def test_an_org_admin_switches_a_connector_off_for_everyone(tmp_path):
    from cycls._app.auth import User
    admin, member = User(id="a", org_id="o1", org_role="admin"), User(id="m", org_id="o1", org_role="member")
    boss, lines = _app(tmp_path, _google(), user=admin)[0], []
    with patch("cycls._agent.web.routers.log", lambda level, **f: lines.append((level, f))):
        assert boss.patch("/connectors/google", json={"allowed": False}).json() == {"allowed": False}
    row = boss.get("/connectors").json()[0]
    assert (row["allowed"], row["org_admin"]) == (False, True)                    # the admin still sees it, greyed
    assert boss.post("/connectors/google/authorize").status_code == 403           # and nobody can connect it
    peer = _app(tmp_path, _google(), user=member)[0]
    assert peer.get("/connectors").json() == []                                   # members never see it
    assert peer.patch("/connectors/google", json={"allowed": True}).status_code == 403
    assert boss.patch("/connectors/google", json={"allowed": True}).json() == {"allowed": True}
    assert peer.get("/connectors").json()[0]["allowed"] is True
    assert [f["action"] for l, f in lines if l == "connector"] == ["blocked"]
    solo = _app(tmp_path, _google())[0]                                           # no org: nothing to switch
    assert solo.patch("/connectors/google", json={"allowed": False}).status_code == 403


def test_either_scope_lets_an_admin_share_and_a_member_keep_their_own(tmp_path):
    from cycls._app.auth import User
    o, grant = _google("either"), {"access_token": "team", "refresh_token": "r", "expires_at": time.time() + 3600}
    admin = User(id="a", org_id="o1", org_role="admin")
    alone = _app(tmp_path, o, user=admin)[0]                                     # a personal workspace: nothing to share with
    assert alone.post("/connectors/google/authorize?scope=workspace").status_code == 400
    boss, _ = _app(tmp_path, o, user=admin, ws_id="t-shared")
    with patch.object(c.OAuth2, "exchange", AsyncMock(return_value=grant)):
        q = parse_qs(urlparse(boss.post("/connectors/google/authorize?scope=workspace").json()["url"]).query)
        boss.get("/connectors/google/callback", params={"code": "c", "state": q["state"][0]})
    row = boss.get("/connectors").json()[0]
    assert (row["connected_as"], row["admin"], row["team"]) == ("workspace", True, "t-shared")   # the split button, named
    peer, pws = _app(tmp_path, o, user=User(id="m", org_id="o1", org_role="member"), ws_id="t-shared")
    assert peer.get("/connectors").json()[0]["connected_as"] == "workspace"       # the team grant reaches everyone
    with patch("cycls._agent.web.routers._admin", AsyncMock(return_value=False)):
        assert peer.delete("/connectors/google?scope=workspace").status_code == 403   # but only an admin removes it
        assert peer.post("/connectors/google/authorize?scope=workspace").status_code == 403
    with patch.object(c.OAuth2, "exchange", AsyncMock(return_value={**grant, "access_token": "mine"})):
        q = parse_qs(urlparse(peer.post("/connectors/google/authorize").json()["url"]).query)
        peer.get("/connectors/google/callback", params={"code": "c", "state": q["state"][0]})
    assert peer.get("/connectors").json()[0]["connected_as"] == "user"            # their own wins
    assert asyncio.run(credentials.get(pws, "google"))["access_token"] == "mine"
    assert peer.delete("/connectors/google").json() == {"ok": True}
    assert asyncio.run(credentials.get(pws, "google"))["access_token"] == "team"  # and the team's is still there
    assert boss.post("/connectors/google/authorize?scope=nope").status_code == 400


def test_tool_permissions_read_write_and_gate_the_turn(tmp_path):
    from cycls._agent.tools import ToolContext
    tools = [SimpleNamespace(name="search_files", title="Search files", description="d", annotations=None),
             SimpleNamespace(name="create_file", title=None, description="d", annotations=None)]
    server = SimpleNamespace(label="drive", tools=AsyncMock(return_value=tools), _connector=None, _url="https://x/mcp", _writes=None,
                             prompts=AsyncMock(return_value=[SimpleNamespace(name="weekly_review", title=None, description="p")]))
    o = _google(); o.servers, server._connector = [server], o
    client, ws = _app(tmp_path, o)
    assert client.get("/connectors/google/prompts").json() == [{"name": "weekly_review", "title": "weekly review", "description": "p"}]
    rows = client.get("/connectors/google/tools").json()
    assert [(r["name"], r["title"], r["writes"], r["mode"]) for r in rows] == \
        [("drive_search_files", "Search files", False, "allow"), ("drive_create_file", "create file", True, "ask")]
    assert client.put("/connectors/google/tools", json={"tools": {"drive_create_file": "sometimes"}}).status_code == 400
    assert client.put("/connectors/google/tools", json={"tools": {"drive_create_file": "allow", "drive_search_files": "never"}}).json() == {"ok": True}
    assert [r["mode"] for r in client.get("/connectors/google/tools").json()] == ["never", "allow"]
    assert client.put("/connectors/google/tools/drive_search_files", json={"mode": "allow"}).json() == {"ok": True}   # one tool; the rest kept
    assert [r["mode"] for r in client.get("/connectors/google/tools").json()] == ["allow", "allow"]
    asyncio.run(c.set_permissions(ws, "google", {"drive_create_file": "allow", "drive_search_files": "never"}))

    async def run(inp, ctx): return "ran"
    schemas = [{"name": "drive_search_files"}, {"name": "drive_create_file"}]
    names = {"drive_search_files": "drive · search_files", "drive_create_file": "drive · create_file"}
    server.discover = AsyncMock(return_value=(schemas, {"drive_search_files": run, "drive_create_file": run}, names))
    kept, fns, _ = asyncio.run(c.tools_for(server, ws))
    assert [s["name"] for s in kept] == ["drive_create_file"]                # never: gone from the turn
    assert asyncio.run(fns["drive_create_file"](None, ToolContext(None, ws))) == "ran"   # allow: runs
    asyncio.run(c.set_permissions(ws, "google", {}))
    kept, fns, _ = asyncio.run(c.tools_for(server, ws))
    assert asyncio.run(fns["drive_create_file"]({"name": "q3.xlsx"}, ToolContext(None, ws))) == "ran"   # auto: a write runs
    card = asyncio.run(fns["drive_create_file"]({"name": "q3.xlsx"}, ToolContext(None, ws, auto=False)))
    assert (card["action"], card["tool"], card["connector"], card["args"]) == ("confirm", "drive_create_file", "google", {"name": "q3.xlsx"})   # manual: the card
    ok = ToolContext(None, ws, approvals=frozenset({card["key"]}), auto=False)
    assert asyncio.run(fns["drive_create_file"]({"name": "q3.xlsx"}, ok)) == "ran"                     # approved: this call
    assert asyncio.run(fns["drive_create_file"]({"name": "q4.xlsx"}, ok))["action"] == "confirm"        # not another
    asyncio.run(c.set_permissions(ws, "google", {"drive_create_file": "ask"}))
    _, fns, _ = asyncio.run(c.tools_for(server, ws))
    assert asyncio.run(fns["drive_create_file"]({"name": "q3.xlsx"}, ToolContext(None, ws)))["action"] == "confirm"   # the person said ask: auto defers


def test_auto_still_pauses_for_a_destructive_tool(tmp_path):
    from cycls._agent.tools import ToolContext
    ws = workspace("org:u1", tmp_path, base=f"file://{tmp_path}")
    asyncio.run(credentials.put(ws, "google", {"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600}))
    async def run(inp, ctx): return "ran"
    tools = [SimpleNamespace(name="create_file", annotations=None), SimpleNamespace(name="delete_file", annotations=None)]
    server = SimpleNamespace(label="drive", _connector=_google(), _writes=None, tools=AsyncMock(return_value=tools),
                             discover=AsyncMock(return_value=([{"name": "drive_create_file"}, {"name": "drive_delete_file"}],
                                                              {"drive_create_file": run, "drive_delete_file": run}, {"drive_create_file": "c", "drive_delete_file": "d"})))
    _, fns, _ = asyncio.run(c.tools_for(server, ws))
    assert asyncio.run(fns["drive_create_file"]({"name": "a"}, ToolContext(None, ws))) == "ran"
    assert asyncio.run(fns["drive_delete_file"]({"name": "a"}, ToolContext(None, ws)))["action"] == "confirm"
    assert c.destructive(SimpleNamespace(name="update_row", annotations=SimpleNamespace(destructive_hint=True)))   # the server's word


def test_a_key_connector_stores_the_pasted_key_and_hands_it_to_its_servers(tmp_path):
    ph = c.Key("posthog", hint="phx_…", scope="either", website="https://posthog.com")
    async def listing(token=None):
        if not token:
            raise RuntimeError("401")
        return [SimpleNamespace(name="insight_get", title=None, description="d", annotations=None)]
    server = SimpleNamespace(label="posthog", _connector=ph, _url="https://mcp.posthog.com/mcp", _writes=None,
                             tools=AsyncMock(side_effect=listing), prompts=AsyncMock(return_value=[]))
    ph.servers = [server]
    client, ws = _app(tmp_path, ph)
    row = client.get("/connectors").json()[0]
    assert (row["kind"], row["hint"], row["connected"]) == ("key", "phx_…", False)
    assert client.get("/connectors/posthog/tools").json() == []                       # nothing lists until a key exists
    assert client.post("/connectors/posthog/authorize").status_code == 400             # keys don't do OAuth
    assert client.put("/connectors/posthog/key", json={"key": "  "}).json()["detail"] == "A key is required"
    assert client.put("/connectors/posthog/key", json={"key": "phx_abc"}).json() == {"ok": True}
    assert asyncio.run(ph.bearer(ws)) == "phx_abc"
    assert [r["name"] for r in client.get("/connectors/posthog/tools").json()] == ["posthog_insight_get"]
    server.tools.assert_awaited_with("phx_abc")
    assert client.get("/connectors").json()[0]["connected_as"] == "user"
    assert client.delete("/connectors/posthog").json() == {"ok": True}
    assert asyncio.run(ph.bearer(ws)) is None


def test_discovery_uses_the_callers_grant_and_skips_a_keyless_key_connector(tmp_path):
    from cycls._app.auth import User
    ws = workspace(User(id="u1"), tmp_path, base=f"file://{tmp_path}")
    ph = c.Key("posthog")
    found = ([{"name": "posthog_s"}], {"posthog_s": 1}, {"posthog_s": "n"})
    server = SimpleNamespace(_connector=ph, label="posthog", _writes=None, tools=AsyncMock(return_value=[]), discover=AsyncMock(return_value=found))
    assert asyncio.run(c.tools_for(server, ws)) == ([], {}, {})                       # no key: nothing, and no error
    server.discover.assert_not_awaited()
    asyncio.run(credentials.put(ws, "posthog", {"key": "phx_1"}))
    assert asyncio.run(c.tools_for(server, ws)) == found
    server.discover.assert_awaited_with(token="phx_1")
    gs = SimpleNamespace(_connector=_google(), discover=AsyncMock(return_value=([], {}, {})))
    asyncio.run(c.tools_for(gs, ws))
    gs.discover.assert_awaited_with(token=None)                                        # OAuth lists anonymously: the card can appear


def test_a_one_tool_server_asks_only_for_the_calls_that_write():
    from cycls._agent.tools import ToolContext
    async def run(inp, ctx): return "ran"
    is_write = lambda tool, args: args.get("command", "").startswith("call flag-")
    g = c.gated(run, "posthog_exec", "posthog · exec", "posthog", is_write)
    assert asyncio.run(g({"command": "info query-trends"}, ToolContext(None, None, auto=False))) == "ran"   # a read passes
    assert asyncio.run(g({"command": "call flag-update {}"}, ToolContext(None, None, auto=False)))["action"] == "confirm"
    assert asyncio.run(g({"command": "call flag-update {}"}, ToolContext(None, None))) == "ran"             # auto: a write runs
    assert asyncio.run(g({"command": "call flag-delete {}"}, ToolContext(None, None)))["action"] == "confirm"   # unless it destroys
    key = c.approval_key("posthog_exec", {"command": "call flag-update {}"})
    assert asyncio.run(g({"command": "call flag-update {}"}, ToolContext(None, None, approvals=frozenset({key}), auto=False))) == "ran"
    t, plain, mixed = SimpleNamespace(name="exec", annotations=None), SimpleNamespace(label="posthog", _writes=None), SimpleNamespace(label="posthog", _writes=is_write)
    assert c.mode(plain, t, {}) == "allow" and c.mode(mixed, t, {}) == "ask"


class _Resp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


class _HTTP:
    """A stand-in for httpx2.AsyncClient that records token requests."""
    calls = []
    def __init__(self, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def post(self, url, data=None, json=None):
        _HTTP.calls.append((url, data or json))
        return _Resp({"access_token": f"at{len(_HTTP.calls)}", "refresh_token": "rt", "expires_in": 100})


def test_an_mcp_server_registers_its_own_client_once_per_org_and_refreshes_without_a_secret(tmp_path):
    salla = c.OAuth2("salla", mcp="https://mcp.x/mcp", scopes=["offline_access"])
    meta = {"issuer": "https://mcp.x", "authorization_endpoint": "https://mcp.x/authorize",
            "token_endpoint": "https://mcp.x/token", "registration_endpoint": "https://mcp.x/register"}
    reg = AsyncMock(return_value={"client_id": "dyn1", "redirect": "http://testserver/connectors/salla/callback", "issuer": "https://mcp.x"})
    _HTTP.calls.clear()
    with patch.object(c, "_auth_server", AsyncMock(return_value=meta)), patch.object(c, "_register", reg), patch("httpx2.AsyncClient", _HTTP):
        client, ws = _app(tmp_path, salla)
        u1, u2 = (urlparse(client.post("/connectors/salla/authorize").json()["url"]) for _ in range(2))
        q = parse_qs(u1.query)
        assert (u1.netloc, u1.path, q["client_id"], q["resource"]) == ("mcp.x", "/authorize", ["dyn1"], ["https://mcp.x/mcp"])
        assert reg.await_count == 1                                                    # registered once, remembered per org
        assert client.get("/connectors/salla/callback", params={"code": "c", "state": parse_qs(u2.query)["state"][0]}).status_code == 200
        grant = asyncio.run(credentials.get(ws, "salla"))
        assert (grant["client_id"], grant["token_endpoint"], grant["access_token"]) == ("dyn1", "https://mcp.x/token", "at1")
        assert _HTTP.calls[0][0] == "https://mcp.x/token" and "client_secret" not in _HTTP.calls[0][1]
        assert _HTTP.calls[0][1]["resource"] == "https://mcp.x/mcp"
        asyncio.run(credentials.put(ws, "salla", {**grant, "expires_at": time.time() - 1}))
        assert asyncio.run(salla.bearer(ws)) == "at2"                                  # refreshed at the grant's own endpoint
        assert _HTTP.calls[-1][0] == "https://mcp.x/token" and "client_secret" not in _HTTP.calls[-1][1]
        assert asyncio.run(credentials.get(ws, "salla"))["client_id"] == "dyn1"        # and the client survives the refresh


def test_oauth2_needs_an_app_or_an_mcp_server():
    with pytest.raises(ValueError):
        c.OAuth2("x")


def test_discovery_is_silent_for_an_unconnected_server_that_only_lists_for_the_signed_in(tmp_path):
    from cycls._app.auth import User
    ws = workspace(User(id="u1"), tmp_path, base=f"file://{tmp_path}")
    g = _google()
    server = SimpleNamespace(_connector=g, discover=AsyncMock(side_effect=RuntimeError("401")))
    assert asyncio.run(c.tools_for(server, ws)) == ([], {}, {})
    asyncio.run(credentials.put(ws, "google", {"access_token": "t", "refresh_token": "r", "expires_at": time.time() + 3600}))
    with pytest.raises(RuntimeError):                                                    # connected and still failing: say so
        asyncio.run(c.tools_for(server, ws))


def test_a_builtin_keeps_its_own_allow_beside_the_connector_ones(tmp_path):
    """The card's *Always allow* on a builtin writes here; the gate reads it once a turn."""
    from cycls._agent.tools import ToolContext, _gate
    client, ws = _app(tmp_path, _google())
    assert client.put("/tools/bash", json={"mode": "sometimes"}).status_code == 400
    assert client.put("/tools/bash", json={"mode": "allow"}).json() == {"ok": True}
    modes = asyncio.run(c.permissions(ws, "_builtin"))
    assert modes == {"bash": "allow"}
    step = {"tool_name": "Bash", "step": "wipe"}
    hard = {"command": "git clean -fdx"}
    assert _gate("bash", hard, ToolContext(None, ws, auto=False), step) is not None              # without it: asks
    assert _gate("bash", hard, ToolContext(None, ws, auto=False, modes=modes), step) is None     # with it: runs
    assert client.get("/tools").json() == {"bash": "allow"}                                      # the panel reads it back
    assert client.delete("/tools/bash").json() == {"ok": True}
    assert client.get("/tools").json() == {}                                                     # and clears it to Auto
    assert _gate("bash", hard, ToolContext(None, ws, auto=False, modes={"bash": "ask"}), step) is not None   # explicit ask


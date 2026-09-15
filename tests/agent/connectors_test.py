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
    assert client.get("/connectors").json() == [{"name": "google", "kind": "oauth", "hint": None, "scope": "user",
                                                 "title": None, "description": None, "category": None,
                                                 "about": None, "story": None, "icon": None, "prompts": [],
                                                 "showcase": "prompts", "gallery": [], "gradient": None, "links": [],
                                                 "use_cases": [], "skills": [],
                                                 "developer": None, "website": None,
                                                 "privacy": None, "terms": None, "docs": None, "team": None,
                                                 "admin": False, "allowed": True, "org_admin": False, "connected": False,
                                                 "on": True, "connected_as": None}]
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
    async def listing(token=None, url=None):
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
    server.tools.assert_awaited_with("phx_abc", None)
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
    server.discover.assert_awaited_with(token="phx_1", url=None)
    gs = SimpleNamespace(_connector=_google(), discover=AsyncMock(return_value=([], {}, {})))
    asyncio.run(c.tools_for(gs, ws))
    gs.discover.assert_awaited_with(token=None, url=None)                                        # OAuth lists anonymously: the card can appear


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
    async def post(self, url, data=None, json=None, headers=None):
        _HTTP.calls.append((url, data or json))
        return _Resp({"access_token": f"at{len(_HTTP.calls)}", "refresh_token": "rt", "expires_in": 100})


def test_an_mcp_server_registers_its_own_client_once_per_org_and_refreshes_without_a_secret(tmp_path):
    salla = c.OAuth2("salla", mcp="https://mcp.x/mcp", scopes=["offline_access"])
    meta = {"issuer": "https://mcp.x", "authorization_endpoint": "https://mcp.x/authorize",
            "token_endpoint": "https://mcp.x/token", "registration_endpoint": "https://mcp.x/register"}
    reg = AsyncMock(return_value={"client_id": "dyn1", "redirect": "http://testserver/connectors/salla/callback",
                                  "issuer": "https://mcp.x", "name": c.CLIENT_NAME})
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



def test_a_person_can_switch_a_connector_off_without_losing_the_grant(tmp_path):
    """Their own switch: the connector stays connected and listed, its tools stay out of every turn,
    and it holds across chats because it is stored on the person, not the conversation."""
    client, ws = _app(tmp_path, _google())
    asyncio.run(credentials.put(ws, "google", {"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600}))
    assert client.patch("/connectors/google", json={"on": False}).json() == {"on": False}
    row = client.get("/connectors").json()[0]
    assert (row["on"], row["connected"], row["allowed"]) == (False, True, True)   # off, but still connected and allowed
    assert asyncio.run(c.off(ws)) == {"google"}
    assert asyncio.run(credentials.get(ws, "google"))["access_token"] == "tok"    # the grant is untouched
    assert client.patch("/connectors/google", json={"on": True}).json() == {"on": True}
    assert asyncio.run(c.off(ws)) == set()


def test_the_cms_fills_the_page_and_the_code_still_wins(tmp_path):
    """Bilingual copy from the CMS, overridden field by field by whatever the agent declared — and a CMS
    that is unreachable leaves the page rendering what the code says."""
    from types import SimpleNamespace as NS
    o = c.OAuth2("salla", mcp="https://mcp.x/mcp", title="Salla")   # title declared in code, the rest is the CMS's
    record = {"name": "salla", "title": {"en": "Salla Store", "ar": "سلة"},
              "description": {"en": "Orders and products", "ar": "الطلبات والمنتجات"},
              "category": {"en": "Commerce", "ar": "تجارة"},
              "story": {"en": "<p>What it does</p>", "ar": "<p>ما تفعله</p>"},
              "prompts": [{"en": "Top products?", "ar": "أفضل المنتجات؟"}],
              "icon": "https://cdn/salla.png", "showcase": "gallery",
              "gallery": [{"image": "https://cdn/1.png"}], "gradient": ["#111", "#222", "#333"],
              "links": "Website: https://salla.sa\nDocs: https://docs.salla.dev\nbroken line",
              "developer": "Salla"}

    async def fake(url, headers=None): return {"salla": record}
    with patch.object(c, "cms_rows", fake):
        client, _ = _app(tmp_path, o)
        row = client.get("/connectors").json()[0]
    assert row["title"] == {"en": "Salla", "ar": "Salla"}                     # code wins, both languages
    assert row["description"]["ar"] == "الطلبات والمنتجات"                    # the CMS fills what code left out
    assert row["story"]["en"] == "<p>What it does</p>" and row["about"] is None
    assert row["prompts"] == [{"en": "Top products?", "ar": "أفضل المنتجات؟"}]
    assert (row["showcase"], row["gradient"], row["icon"]) == ("gallery", ["#111", "#222", "#333"], "https://cdn/salla.png")
    assert row["links"] == [{"label": "Website", "url": "https://salla.sa"},
                            {"label": "Docs", "url": "https://docs.salla.dev"}]   # a line without a url is dropped


class _Reader:
    """Stands in for the CMS read: the calls are counted, and each one answers as told."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    async def __call__(self, url, headers=None):
        self.calls += 1
        ok = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        c._copy["tried"] = time.time()
        if ok:
            c._copy["rows"], c._copy["at"] = {"salla": {"name": "salla"}}, time.time()


@pytest.fixture(autouse=True)
def _fresh_copy():
    """The copy cache is one dict per container, so a test that fills it would leak into the next."""
    c._copy.update({"at": 0.0, "tried": 0.0, "rows": {}, "task": None})
    yield
    c._copy.update({"at": 0.0, "tried": 0.0, "rows": {}, "task": None})


def test_a_read_that_fails_is_retried_rather_than_serving_code_only_copy_for_a_ttl():
    """The bug this guards: stamping the clock on the attempt meant one timeout — a CMS scaled to zero
    is usually woken by this very read — left the directory with no story on it for five minutes, on
    that container only, so the page rendered for some people and not others."""
    read = _Reader(False, True)
    with patch.object(c, "_cms_read", read):
        assert asyncio.run(c.cms_rows("https://cms/connectors")) == {}   # the read did not land
        c._copy["tried"] = 0.0                                          # the retry gate, a moment later
        assert asyncio.run(c.cms_rows("https://cms/connectors")) == {"salla": {"name": "salla"}}
    assert read.calls == 2


def test_a_cms_that_is_down_is_not_read_on_every_request():
    """The other half: retrying at once must not mean every request waits on a dead CMS."""
    read = _Reader(False)
    with patch.object(c, "_cms_read", read):
        for _ in range(5):
            assert asyncio.run(c.cms_rows("https://cms/connectors")) == {}
    assert read.calls == 1   # one attempt, then the gate holds until CMS_RETRY


def test_a_copy_in_hand_is_served_while_it_is_re_read_behind_the_request():
    read = _Reader(True)
    with patch.object(c, "_cms_read", read):
        assert asyncio.run(c.cms_rows("https://cms/connectors")) == {"salla": {"name": "salla"}}

        async def stale():
            c._copy["at"] = c._copy["tried"] = time.time() - c.CMS_TTL - 1
            rows = await c.cms_rows("https://cms/connectors")
            await c._copy["task"]      # held on the dict, so it cannot be collected mid-flight
            return rows

        assert asyncio.run(stale()) == {"salla": {"name": "salla"}}   # served as it stands, never awaited
    assert read.calls == 2


def test_the_model_reads_the_same_copy_the_page_does():
    """catalog.py names a connector and the CMS describes it, so the index the model routes on has to
    come from the CMS row too — not from the code's empty title."""
    o = c.OAuth2("salla", mcp="https://mcp.x/mcp")
    assert c.copy_of(o) == ("", "")                                   # nothing read yet, nothing declared
    assert c.index_line(o, 12) == "- salla: salla (12 tools)"
    c._copy["rows"] = {"salla": {"name": "salla", "title": {"en": "Salla", "ar": "سلة"},
                                 "description": {"en": "Orders, products and customers", "ar": "الطلبات"}}}
    assert c.copy_of(o) == ("Salla", "Orders, products and customers")
    assert c.index_line(o, 12) == "- salla: Salla — Orders, products and customers (12 tools)"
    o.title, o.description = "Salla Store", "What the code says"       # code still wins where it speaks
    assert c.copy_of(o) == ("Salla Store", "What the code says")


def test_bilingual_prefers_what_came_first_and_fills_the_other_language():
    assert c.bilingual("Drive", {"en": "x", "ar": "y"}) == {"en": "Drive", "ar": "Drive"}
    assert c.bilingual(None, {"en": "", "ar": "سلة"}) == {"en": "سلة", "ar": "سلة"}
    assert c.bilingual(None, None) is None


def _relay_ws(tmp_path):
    return workspace("relay", tmp_path, base=f"file://{tmp_path}")


def _fake_httpx(captured):
    """Stands in for httpx.AsyncClient so the relay's request is inspectable."""
    class R:
        status_code, content, headers = 200, b'{"ok":true}', {"content-type": "application/json"}

    class C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, method, url, headers=None, content=None):
            captured.update(method=method, url=url, headers=headers, content=content)
            return R()
    return SimpleNamespace(AsyncClient=lambda **kw: C())


def test_an_app_reaches_a_connector_api_with_the_workspace_grant(key, tmp_path):
    """The app names a connector and a path; the live token is attached here, so a refreshed
    grant is inherited and the page never holds one."""
    import sys
    o, ws, got = c.Key("posthog", api="https://us.posthog.com"), _relay_ws(tmp_path), {}
    asyncio.run(credentials.put(ws, "posthog", {"key": "phx_live"}))
    with patch.dict(sys.modules, {"httpx2": _fake_httpx(got)}):
        status, body, ctype = asyncio.run(c.relay(o, ws, "/api/projects/1/query/", method="POST",
                                                  headers={"content-type": "application/json",
                                                           "authorization": "Bearer attacker",
                                                           "x-forwarded-for": "1.2.3.4"},
                                                  body=b'{"query":"select 1"}'))
    assert (status, body, ctype) == (200, b'{"ok":true}', "application/json")
    assert got["url"] == "https://us.posthog.com/api/projects/1/query/"
    assert got["headers"]["Authorization"] == "Bearer phx_live"      # ours, not the caller's
    assert "x-forwarded-for" not in {k.lower() for k in got["headers"]}


def test_the_relay_will_not_leave_the_connectors_host(key, tmp_path):
    """`api` is the boundary: a path that climbs out, or an absolute url, is refused before
    any request is made — the grant would otherwise be handed to whatever host was named."""
    o, ws = c.Key("posthog", api="https://us.posthog.com"), _relay_ws(tmp_path)
    asyncio.run(credentials.put(ws, "posthog", {"key": "phx_live"}))
    import sys
    with patch.dict(sys.modules, {"httpx2": _fake_httpx({})}):   # a leak would show as 200, never a live call
        for path in ("../../evil", "/api/../../evil", "https://evil.example/x", "//evil.example/x"):
            assert asyncio.run(c.relay(o, ws, path))[0] == 400, path


def test_the_relay_says_not_connected_rather_than_calling_anonymously(key, tmp_path):
    o, ws = c.Key("posthog", api="https://us.posthog.com"), _relay_ws(tmp_path)
    assert asyncio.run(c.relay(o, ws, "/api/x"))[0] == 401
    assert asyncio.run(c.relay(c.Key("nope"), ws, "/api/x"))[0] == 400   # no api base declared


def test_an_api_base_must_be_https():
    with pytest.raises(ValueError):
        c.Key("posthog", api="http://us.posthog.com")


def test_a_connector_can_require_headers_of_every_caller(key, tmp_path):
    """Notion refuses a request without its version header, and an app cannot set one — the
    allowlist drops it. The connector declares it once and the relay sends it every time."""
    import sys
    o = c.OAuth2("notion", mcp="https://mcp.notion.com/mcp", api="https://api.notion.com",
                 api_headers={"Notion-Version": "2022-06-28"})
    ws, got = _relay_ws(tmp_path), {}
    asyncio.run(credentials.put(ws, "notion", {"access_token": "t", "expires_at": 9e12}))
    with patch.dict(sys.modules, {"httpx2": _fake_httpx(got)}):
        asyncio.run(c.relay(o, ws, "/v1/search", method="POST",
                            headers={"notion-version": "1999-01-01"}, body=b"{}"))
    assert got["headers"]["Notion-Version"] == "2022-06-28"   # the connector's, not the app's


def test_a_pasted_link_can_be_the_credential(tmp_path):
    """Zid gives each merchant a private MCP link and calls it a password. It rides the same paste
    field a key uses, but it addresses the server instead of being sent to one."""
    from cycls._app.auth import User
    zid = c.Endpoint("zid", host="zid.sa", hint="https://…zid.sa/…", title="Zid")
    ws = workspace(User(id="u1"), tmp_path, base=f"file://{tmp_path}")
    found = ([{"name": "zid_orders"}], {"zid_orders": 1}, {"zid_orders": "n"})
    server = SimpleNamespace(_connector=zid, label="zid", _writes=None,
                             tools=AsyncMock(return_value=[]), discover=AsyncMock(return_value=found))
    assert zid.kind == "key"                                   # the directory already knows how to draw this
    assert asyncio.run(c.tools_for(server, ws)) == ([], {}, {})   # no link yet: nothing, and no error
    server.discover.assert_not_awaited()

    for bad in ("https://evil.example/mcp", "http://mcp.zid.sa/s/a", "https://evil-zid.sa/s/a",
                "https://zid.sa.evil.com/s/a", "https://u:p@mcp.zid.sa/s/a"):
        assert zid.validate(bad), bad                          # a link from anywhere else is refused
    assert zid.validate("https://mcp.zid.sa/s/abc") is None    # any subdomain of theirs is fine
    asyncio.run(credentials.put(ws, "zid", {"key": "https://mcp.zid.sa/s/abc"}))
    assert asyncio.run(c.tools_for(server, ws)) == found
    server.discover.assert_awaited_with(token=None, url="https://mcp.zid.sa/s/abc")   # addressed, never sent
    assert asyncio.run(zid.bearer(ws)) is None


def test_a_stored_link_that_no_longer_matches_the_prefix_is_ignored(tmp_path):
    """The guard is read at use, not only at save: a prefix tightened in code retires links that
    were stored under the looser one instead of dialling them."""
    from cycls._app.auth import User
    ws = workspace(User(id="u1"), tmp_path, base=f"file://{tmp_path}")
    asyncio.run(credentials.put(ws, "zid", {"key": "https://old.example/s/abc"}))
    assert asyncio.run(c.Endpoint("zid", host="zid.sa").endpoint(ws)) is None


def test_a_link_on_the_right_domain_is_still_refused_over_plain_http():
    assert c.Endpoint("zid", host="zid.sa").validate("http://mcp.zid.sa/s/a")


def test_the_token_exchange_asks_for_json(key):
    """GitHub's token endpoint answers form-encoded unless the request says otherwise, and the
    grant is read with `.json()` — so the header is what makes that provider work at all."""
    import sys
    seen = {}

    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"access_token": "a", "expires_in": 60}

    class C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, data=None):
            seen.update(headers=headers or {}, data=data)
            return R()

    o = c.OAuth2("github", authorize="a", token="https://github.com/login/oauth/access_token",
                 client_id="cid", secret="shh")
    with patch.dict(sys.modules, {"httpx2": SimpleNamespace(AsyncClient=lambda **kw: C())}):
        grant = asyncio.run(o._token({"token": o.token, "client_id": "cid", "resource": None}, code="z"))
    assert seen["headers"].get("Accept") == "application/json"
    assert grant["access_token"] == "a"


def test_a_missing_deployment_secret_says_which_one(monkeypatch):
    """A connector declares `cycls.env("X")` and it resolves when used, so a value nobody set
    surfaces at Connect — naming it beats a bare KeyError in the logs."""
    monkeypatch.delenv("NOPE_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="NOPE_CLIENT_ID is not set"):
        c.env("NOPE_CLIENT_ID").get()


# ---- the connect relay: one registered redirect for every agent ----

def _relay_env(monkeypatch, origins="https://super.cycls.ai,https://haseef.cycls.ai"):
    monkeypatch.setenv("CYCLS_RELAY_SECRET", "shared")
    monkeypatch.setenv("CYCLS_RELAY_ORIGINS", origins)
    monkeypatch.setenv("CYCLS_RELAY_URL", "https://connect.cycls.ai/callback")


def test_the_relay_sends_the_code_back_to_the_agent_that_asked(monkeypatch):
    """The state names the origin, the relay reads it and bounces. Both halves sign and read with
    the same functions, so the format cannot drift into a broken login."""
    _relay_env(monkeypatch)
    state = c.sign({"c": "github", "o": "https://super.cycls.ai", "n": "x"}, key=c.state_key())
    payload = c.verify(state, key=c.state_key())
    assert c.relay_target(payload, c.relay_origins()) == "https://super.cycls.ai/connectors/github/callback"


def test_the_relay_refuses_an_origin_that_is_not_on_the_list(monkeypatch):
    """Anyone can deploy a *.cycls.ai subdomain, so being one of ours is not permission to use our
    registered OAuth apps. Without this the relay is an open redirect with OAuth attached."""
    _relay_env(monkeypatch)
    for origin in ("https://evil.cycls.ai", "https://evil.example", "http://super.cycls.ai",
                   "https://super.cycls.ai.evil.com", ""):
        p = c.verify(c.sign({"c": "github", "o": origin}, key=c.state_key()), key=c.state_key())
        with pytest.raises(ValueError):
            c.relay_target(p, c.relay_origins())


def test_the_relay_refuses_a_state_it_did_not_sign(monkeypatch):
    """A code is only forwarded on our own signature — otherwise anyone could name any origin."""
    _relay_env(monkeypatch)
    good = c.sign({"c": "github", "o": "https://super.cycls.ai"}, key=c.state_key())
    body, _, mac = good.rpartition(".")
    for bad in (f"{body}.{'0' * len(mac)}", f"{body}x.{mac}", "nonsense", body):
        with pytest.raises(ValueError):
            c.verify(bad, key=c.state_key())
    other = c.sign({"c": "github", "o": "https://super.cycls.ai"}, key=b"someone else's key" * 2)
    with pytest.raises(ValueError):
        c.verify(other, key=c.state_key())


def test_a_relayed_state_expires(monkeypatch):
    _relay_env(monkeypatch)
    stale = c.sign({"c": "github", "o": "https://super.cycls.ai"}, ttl=-1, key=c.state_key())
    with pytest.raises(ValueError, match="expired"):
        c.verify(stale, key=c.state_key())


def test_a_connector_name_cannot_escape_the_callback_path(monkeypatch):
    """The name lands in a URL path, so a traversal or a scheme in it would retarget the redirect."""
    _relay_env(monkeypatch)
    for name in ("../../evil", "git hub", "https://evil.example", "a" * 65, ""):
        p = {"c": name, "o": "https://super.cycls.ai"}
        with pytest.raises(ValueError):
            c.relay_target(p, c.relay_origins())


def test_without_a_relay_nothing_changes(monkeypatch):
    """No relay configured: the state never leaves the deployment and its own key signs it."""
    monkeypatch.delenv("CYCLS_RELAY_URL", raising=False)
    monkeypatch.delenv("CYCLS_RELAY_SECRET", raising=False)
    monkeypatch.setenv("CYCLS_SECRET_KEY", "k1")
    assert c.relay_url() is None
    assert c.state_key() == credentials.key()
    assert c.relay_origins() == set()


def test_a_connector_can_stay_off_the_relay(monkeypatch):
    """A fixed app's redirect lives in the provider's console. Routing it through the relay without
    updating that console is a redirect_uri_mismatch at the moment someone presses Connect."""
    _relay_env(monkeypatch)
    assert c.OAuth2("salla", mcp="https://mcp.x/mcp").relay is True
    assert c.OAuth2("google", authorize="a", token="t", client_id="i", relay=False).relay is False
    assert c.Key("posthog").relay is True

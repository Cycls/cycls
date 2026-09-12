"""Connectors — a grant a person makes for themselves or a workspace, and their policy over the tools that use it.

`Key` keeps a pasted key. `OAuth2` runs authorization-code with PKCE against a registered app, or against an
MCP server that publishes its authorization server and registers clients on the fly. `bearer` hands a live
token to a tool and refreshes it when stale. The state that rides through the provider is signed with the
credential store's key and names the user and workspace — the callback carries no JWT. Secrets are
`cycls.env("NAME")` references, resolved when used, never pickled. An org admin can switch a connector off;
each person sets allow / ask / never per tool, and `ask` stops the model with a confirm card.
"""
import base64, hashlib, hmac, json, os, re, time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse
from . import credentials, state
from .logs import log


@dataclass(frozen=True)
class Env:
    name: str

    def get(self):
        return os.environ[self.name]


def env(name):
    """A deployment secret by name; the value is read from the environment when used."""
    return Env(name)


def _val(x):
    return x.get() if isinstance(x, Env) else x


def sign(payload, ttl=600):
    body = base64.urlsafe_b64encode(json.dumps({**payload, "exp": int(time.time()) + ttl}).encode()).decode().rstrip("=")
    return f"{body}.{_mac(body)}"


def verify(state):
    body, _, mac = state.rpartition(".")
    if not hmac.compare_digest(mac, _mac(body)):
        raise ValueError("bad state")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if payload["exp"] < time.time():
        raise ValueError("state expired")
    return payload


def _mac(body):
    return hmac.new(credentials.key(), body.encode(), hashlib.sha256).hexdigest()[:32]


def not_connected(name):
    """What a tool returns when no grant resolves: the connect card for the user, a stop for the model."""
    return {"type": "ui", "action": "connect", "connector": name,
            "ack": f"{name} is not connected. A card is asking the user to connect it — end your turn now."}


def _orgdb(ws):
    return state.org_db(ws.subject.partition(":")[0], ws.volume, ws.base)


async def blocked(ws):
    """Connector names an org admin switched off — one row under the org's `.org` slot."""
    return set(((await _orgdb(ws).get("connectors")) or {}).get("blocked") or [])


async def set_blocked(ws, name, off):
    names = (await blocked(ws) - {name}) | ({name} if off else set())
    await _orgdb(ws).put("connectors", {"blocked": sorted(names)})


# ---- Tool permissions: allow / ask / never, per user, per connector ----
MODES = ("allow", "ask", "never")
_WRITES = re.compile(r"^(create|write|update|delete|remove|send|post|put|patch|upload|copy|move|rename|set|add|insert|share|publish|execute|run|edit|modify|trash|archive|cancel|refund)")


def writes(tool):
    """Does the tool change something? The server's annotation when it gives one, else its name."""
    a = getattr(tool, "annotations", None)
    if a is not None and a.read_only_hint is not None:
        return not a.read_only_hint
    return bool(getattr(a, "destructive_hint", None)) or bool(_WRITES.match(tool.name.lower()))


def mode(server, tool, chosen):
    """What the user picked, else the default: read-only runs, anything that writes asks — a one-tool
    server with a per-call classifier does both, so it asks."""
    return chosen.get(f"{server.label}_{tool.name}") or ("ask" if server._writes or writes(tool) else "allow")


async def permissions(ws, name):
    return ((await credentials.get(ws, f"_permissions/{name}")) or {}).get("tools") or {}


async def set_permissions(ws, name, tools):
    await credentials.put(ws, f"_permissions/{name}", {"tools": tools})


_DESTRUCTIVE = re.compile(r"\b(delete|remove|trash|cancel|refund)")


def destructive(tool):
    """Auto still pauses for these: the server's annotation, else the name."""
    return bool(getattr(getattr(tool, "annotations", None), "destructive_hint", None)) or bool(_DESTRUCTIVE.search(tool.name.lower()))


_NARRATION = ("description", "context", "reason")   # the model's prose about a call, not the call


def approval_key(tool, inp):
    """What one Approve covers: this tool with these arguments. Narration is excluded — the model rewrites
    it on a retry, and an approval that a reworded sentence invalidates is an approval that asks forever."""
    args = {k: v for k, v in (inp or {}).items() if k not in _NARRATION}
    return f"{tool}:{hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:12]}"


def gated(fn, tool, label, connector, classify=None, hard=False):
    """Runs with the person's approval for this exact call, or under Auto unless the call is hard — the person
    set Ask, or it destroys something. With a classifier, a call it deems a read passes. Otherwise the confirm
    card, and the model stops. Every decision but a read is an audit line."""
    async def call(inp, ctx):
        key, args = approval_key(tool, inp), inp or {}
        how = ("approved" if key in ctx.approvals else "read" if classify and not classify(tool, args)
               else "auto" if ctx.auto and not hard and not (classify and _DESTRUCTIVE.search(json.dumps(args).lower())) else "asked")
        if how != "read":
            log("approval", user=ctx.user, chat_id=ctx.chat_id, tool=tool, connector=connector, how=how)
        if how != "asked":
            return await fn(inp, ctx)
        return {"type": "ui", "action": "confirm", "tool": tool, "key": key, "connector": connector, "label": label, "args": inp,
                "ack": f"{label} needs the user's approval — a card is asking them. End your turn now. "
                       "If they approve, make this call again with exactly the same arguments: the approval covers "
                       "this call, so any change to the arguments asks them a second time."}
    return call


async def tools_for(server, ws):
    """One server's tools for the caller: discovered with their grant, then their policy — `never` drops a tool,
    `ask` gates it. A key connector with no key contributes nothing, silently; an OAuth server still lists
    anonymously so the connect card can appear."""
    o = server._connector
    token = await o.bearer(ws) if o else None
    if o and o.kind == "key" and token is None:
        return [], {}, {}
    try:
        schemas, fns, names = await server.discover(token=token)
    except Exception:
        if o and token is None:   # a server that only lists for the signed-in: nothing, until they connect
            return [], {}, {}
        raise
    if not o or not schemas:
        return schemas, fns, names
    chosen = await permissions(ws, o.name)
    found = {f"{server.label}_{t.name}": t for t in await server.tools(token)}
    modes = {k: mode(server, t, chosen) for k, t in found.items()}
    return ([s for s in schemas if modes.get(s["name"]) != "never"],
            {k: gated(f, k, names[k], o.name, server._writes, chosen.get(k) == "ask" or destructive(found[k])) if modes.get(k) == "ask" else f
             for k, f in fns.items() if modes.get(k) != "never"},
            names)


class Connector:
    """What the directory shows and where a grant lands — shared by every kind of connector."""
    kind = hint = None

    def __init__(self, name, *, scope="user", description=None, icon=None, prompts=(), developer=None, category=None,
                 website=None, title=None, about=None, use_cases=(), skills=(), privacy=None, terms=None, docs=None):
        if scope not in ("user", "workspace", "either"):
            raise ValueError(f'scope must be "user", "workspace" or "either"; got {scope!r}')
        self.name, self.scope = name, scope
        self.description, self.icon, self.prompts = description, icon, list(prompts)   # the directory card and detail page
        self.developer, self.category, self.website = developer, category, website
        self.title, self.about, self.use_cases = title, about, [list(u) for u in use_cases]
        self.skills = [list(s) for s in skills]
        self.privacy, self.terms, self.docs = privacy, terms, docs
        self.servers = []   # the MCP servers acting with this grant — registered by MCP.connector()

    def slot(self, scope=None):
        """Where a grant goes: the connector's own scope, or the caller's pick for `either`."""
        if self.scope != "either":
            return self.scope
        if scope not in (None, "user", "workspace"):
            raise ValueError(f'scope must be "user" or "workspace"; got {scope!r}')
        return scope or "user"



class Key(Connector):
    """A connector that authenticates with a key the person pastes — PostHog, and most REST APIs."""
    kind = "key"

    def __init__(self, name, *, hint=None, **kw):
        super().__init__(name, **kw)
        self.hint = hint   # what a key looks like, e.g. "phx_…" — the field's placeholder

    async def bearer(self, ws):
        grant = await credentials.get(ws, self.name)
        return grant["key"] if grant else None


_meta = {}   # mcp url -> its authorization server's metadata


async def _auth_server(mcp_url):
    """RFC 9728, then RFC 8414: the MCP server names its authorization server; that server publishes its endpoints."""
    if mcp_url in _meta:
        return _meta[mcp_url]
    import httpx2
    u = urlparse(mcp_url)
    origin = issuer = f"{u.scheme}://{u.netloc}"
    async with httpx2.AsyncClient(timeout=15) as h:
        for path in (f"/.well-known/oauth-protected-resource{u.path}", "/.well-known/oauth-protected-resource"):
            r = await h.get(origin + path)
            if r.status_code == 200 and r.json().get("authorization_servers"):
                issuer = r.json()["authorization_servers"][0]
                break
        for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
            r = await h.get(issuer.rstrip("/") + path)
            if r.status_code == 200:
                _meta[mcp_url] = r.json()
                return _meta[mcp_url]
    raise RuntimeError(f"{mcp_url}: no authorization server metadata")


async def _register(meta, redirect, name):
    """Dynamic client registration (RFC 7591): a public client with PKCE and one redirect — no app to pre-register."""
    import httpx2
    async with httpx2.AsyncClient(timeout=15) as h:
        r = await h.post(meta["registration_endpoint"], json={
            "client_name": f"Cycls · {name}", "redirect_uris": [redirect], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"})
    r.raise_for_status()
    return {"client_id": r.json()["client_id"], "redirect": redirect, "issuer": meta.get("issuer")}


class OAuth2(Connector):
    kind = "oauth"

    def __init__(self, name, *, authorize=None, token=None, client_id=None, secret=None, scopes=(), extra=None, mcp=None, **kw):
        super().__init__(name, **kw)
        if not mcp and not (authorize and token and client_id):
            raise ValueError("OAuth2 needs authorize, token and client_id — or mcp=<server url> to discover them")
        self.authorize, self.token = authorize, token
        self.client_id, self.secret, self.scopes = client_id, secret, list(scopes)
        self.extra, self.mcp = dict(extra or {}), mcp   # mcp: a server that publishes its auth server and registers clients on the fly

    async def client(self, ws, redirect):
        """The endpoints and client to use: the registered app's, or — for an MCP server — discovered from its
        metadata and registered once per org, the client remembered in the org's `.org` slot."""
        if not self.mcp:
            return {"authorize": self.authorize, "token": self.token, "client_id": _val(self.client_id), "resource": None}
        meta, db = await _auth_server(self.mcp), _orgdb(ws)
        row = await db.get(f"clients/{self.name}")
        if not row or row.get("redirect") != redirect or row.get("issuer") != meta.get("issuer"):
            row = await _register(meta, redirect, self.name)
            await db.put(f"clients/{self.name}", row)
        return {"authorize": meta["authorization_endpoint"], "token": meta["token_endpoint"], "client_id": row["client_id"], "resource": self.mcp}

    def authorize_url(self, client, redirect_uri, state, verifier):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        return client["authorize"] + "?" + urlencode({
            "response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect_uri,
            "scope": " ".join(self.scopes), "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
            **({"resource": client["resource"]} if client["resource"] else {}), **self.extra})

    async def _token(self, client, **form):
        import httpx2
        secret = None if self.mcp else _val(self.secret)   # a discovered client has none
        async with httpx2.AsyncClient(timeout=30) as h:
            r = await h.post(client["token"], data={"client_id": client["client_id"], **({"client_secret": secret} if secret else {}),
                                                    **({"resource": client["resource"]} if client["resource"] else {}), **form})
        r.raise_for_status()
        t = r.json()
        return {"access_token": t["access_token"], "refresh_token": t.get("refresh_token"), "expires_at": time.time() + t.get("expires_in", 3600),
                "token_endpoint": client["token"], "client_id": client["client_id"], "resource": client["resource"]}

    async def exchange(self, client, code, redirect_uri, verifier):
        return await self._token(client, grant_type="authorization_code", code=code, redirect_uri=redirect_uri, code_verifier=verifier)

    async def refresh(self, grant):
        client = {"token": grant.get("token_endpoint") or self.token, "client_id": grant.get("client_id") or _val(self.client_id),
                  "resource": grant.get("resource")}   # a grant from before these were stored: the fixed app's
        new = await self._token(client, grant_type="refresh_token", refresh_token=grant["refresh_token"])
        return {**grant, **new, "refresh_token": new["refresh_token"] or grant["refresh_token"]}

    async def bearer(self, ws):
        """A live access token for this workspace's caller, refreshed if stale; None when not connected."""
        grant, shared = await credentials.find(ws, self.name)
        if not grant:
            return None
        if grant["expires_at"] < time.time() + 60:
            grant = await self.refresh(grant)
            await credentials.put(ws, self.name, grant, shared=shared)
        return grant["access_token"]

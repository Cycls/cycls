"""Connectors — a grant a person makes for themselves or a workspace, and their policy over the tools that use it.

`Key` keeps a pasted key. `OAuth2` runs authorization-code with PKCE against a registered app, or against an
MCP server that publishes its authorization server and registers clients on the fly. `bearer` hands a live
token to a tool and refreshes it when stale. The state that rides through the provider is signed with the
credential store's key and names the user and workspace — the callback carries no JWT. Secrets are
`cycls.env("NAME")` references, resolved when used, never pickled. An org admin can switch a connector off;
each person sets allow / ask / never per tool, and `ask` stops the model with a confirm card.
"""
import asyncio, base64, hashlib, hmac, json, os, re, time
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse
from . import credentials, state
from .logs import log


@dataclass(frozen=True)
class Env:
    name: str

    def get(self):
        try:
            return os.environ[self.name]
        except KeyError:
            raise RuntimeError(f"{self.name} is not set in this deployment's environment") from None


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


async def off(ws):
    """Connector names this person switched off — the grant is kept, the tools stay out of every turn.
    Their own row, so it follows them into every workspace and every chat until they switch it back on."""
    return set(((await credentials.get(ws, "_off")) or {}).get("connectors") or [])


async def set_off(ws, name, value):
    names = (await off(ws) - {name}) | ({name} if value else set())
    await credentials.put(ws, "_off", {"connectors": sorted(names)})


# ---- Directory copy from a CMS: bilingual, and whatever the code declares wins ----
CMS_TTL = 300   # how long a container serves the connector copy it last read
_copy = {"at": 0.0, "rows": {}}


async def _cms_read(url, headers):
    import httpx2
    _copy["at"] = time.time()
    try:
        async with httpx2.AsyncClient(timeout=5) as h:
            r = await h.get(url, headers=headers)
        if r.status_code == 200:
            _copy["rows"] = {c["name"]: c for c in (r.json().get("connectors") or []) if c.get("name")}
    except Exception:
        pass   # a CMS that is down leaves the page rendering what the code declares


async def cms_rows(url, headers=None):
    """The CMS's records by connector name. The first caller waits, so the first directory is already
    right; after that a stale cache is served as it stands and re-read behind the request."""
    if not url:
        return {}
    if not _copy["at"]:
        await _cms_read(url, headers or {})
    elif time.time() - _copy["at"] >= CMS_TTL:
        asyncio.create_task(_cms_read(url, headers or {}))
    return _copy["rows"]


def bilingual(*values):
    """The first value anyone declared, as {en, ar}. A CMS field is already a pair; a string from code is
    the same in both languages, which is what a developer who wrote one means."""
    for v in values:
        if isinstance(v, dict) and (v.get("en") or v.get("ar")):
            return {"en": v.get("en") or v.get("ar") or "", "ar": v.get("ar") or v.get("en") or ""}
        if isinstance(v, str) and v.strip():
            return {"en": v, "ar": v}
    return None


def links_of(row, o):
    """`label: url` lines from the CMS, else the four the connector declared — those keep their own
    translated labels on the page, so they are sent as they always were."""
    out = []
    for line in (row.get("links") or "").splitlines():
        label, _, url = line.partition(":")
        if label.strip() and url.strip():
            out.append({"label": label.strip(), "url": url.strip()})
    return out


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
    url = await o.endpoint(ws) if o and o.addressed else None
    if o and o.kind == "key" and token is None and url is None:
        return [], {}, {}
    try:
        schemas, fns, names = await server.discover(token=token, url=url)
    except Exception:
        if o and token is None:   # a server that only lists for the signed-in: nothing, until they connect
            return [], {}, {}
        raise
    if not o or not schemas:
        return schemas, fns, names
    chosen = await permissions(ws, o.name)
    found = {f"{server.label}_{t.name}": t for t in await server.tools(token, url)}
    modes = {k: mode(server, t, chosen) for k, t in found.items()}
    return ([s for s in schemas if modes.get(s["name"]) != "never"],
            {k: gated(f, k, names[k], o.name, server._writes, chosen.get(k) == "ask" or destructive(found[k])) if modes.get(k) == "ask" else f
             for k, f in fns.items() if modes.get(k) != "never"},
            names)


RELAY_HEADERS = ("content-type", "accept")   # the app sets these; Authorization is ours alone
RELAY_MAX_BYTES = 5_000_000


async def relay(o, ws, path, *, method="GET", headers=None, body=None, timeout=30.0):
    """One call from an app to a connector's REST API. The grant is resolved here, per call, so a
    refreshed token is inherited and the page never holds one; `api` bounds the host."""
    import httpx2
    if not o.api:
        return 400, b'{"error":"this connector has no API base"}', "application/json"
    if not (token := await o.bearer(ws)):
        return 401, b'{"error":"not connected"}', "application/json"
    path = str(path or "")
    if ".." in path or "\\" in path or "\0" in path or "://" in path or path.startswith("//"):
        return 400, b'{"error":"bad path"}', "application/json"
    url = f"{o.api}/{path.lstrip('/')}"
    if not url.startswith(o.api + "/") or urlparse(url).netloc != urlparse(o.api).netloc:
        return 400, b'{"error":"path escapes the connector"}', "application/json"
    if (method := str(method or "GET").upper()) not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        return 405, b'{"error":"method not allowed"}', "application/json"
    send = {k: v for k, v in (headers or {}).items() if str(k).lower() in RELAY_HEADERS}
    send.update(o.api_headers)          # what the API requires of every caller
    send["Authorization"] = f"Bearer {token}"
    async with httpx2.AsyncClient(timeout=timeout, follow_redirects=False) as c:
        r = await c.request(method, url, headers=send, content=body)
    out = r.content[:RELAY_MAX_BYTES]
    return r.status_code, out, r.headers.get("content-type", "application/octet-stream")


FIND_TOOLS = {
    "type": "custom", "name": "find_tools",
    "description": "Load a connector's tools before you can call them. Search by what you want to do "
                   "(\"list orders\", \"read a page\") or by connector name. Matching tools join the "
                   "conversation and stay for the rest of it. The connectors you can search are listed "
                   "in the system prompt.",
    "input_schema": {"type": "object", "required": ["query"],
                     "properties": {"query": {"type": "string", "description": "What you need to do, in a few words."}}},
}


def index_line(o, count):
    """One line per connector — ~15 tokens against ~320 for a schema."""
    d = re.sub(r"\s+", " ", (o.description or "").strip())[:70]
    return f"- {o.name}: {o.title or o.name}{' — ' + d if d else ''} ({count} tools)"


def matches(query, catalog):
    """Connector names whose tools answer *query*, best first. `catalog` is name -> (title, description, [tool text])."""
    q = (query or "").lower()
    words = {w for w in re.findall(r"[a-z0-9]+", q) if len(w) > 2}
    scored = {}
    for name, (title, desc, tools) in catalog.items():
        hay = " ".join([name, title or "", desc or "", *tools]).lower()
        score = sum(1 for w in words if w in hay)
        if name in q or (title and title.lower() in q):
            score += 5
        if score:
            scored[name] = score
    return sorted(scored, key=lambda n: -scored[n])


class Connector:
    """What the directory shows and where a grant lands — shared by every kind of connector."""
    kind = hint = None
    addressed = False   # True when the secret IS the server address, not a token sent to it

    def __init__(self, name, *, scope="user", description=None, icon=None, prompts=(), developer=None, category=None,
                 website=None, title=None, about=None, use_cases=(), skills=(), privacy=None, terms=None, docs=None,
                 api=None, api_headers=None):
        if scope not in ("user", "workspace", "either"):
            raise ValueError(f'scope must be "user", "workspace" or "either"; got {scope!r}')
        if api and not str(api).startswith("https://"):
            raise ValueError(f"api must be an https base url; got {api!r}")
        self.api = str(api).rstrip("/") if api else None   # REST base an app may reach through the relay
        self.api_headers = dict(api_headers or {})          # fixed headers that base requires, e.g. Notion-Version
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

    def validate(self, value):
        """An error to show the person, or None. Runs before anything is stored."""
        return None

    async def bearer(self, ws):
        grant = await credentials.get(ws, self.name)
        return grant["key"] if grant else None


class Endpoint(Key):
    """A connector whose secret IS the address. Zid hands each merchant a private MCP link from
    their dashboard and says to treat it like a password, so there is nothing to send — the link
    is the credential. It reuses the paste field a key already has; `prefix` bounds what counts
    as one, so a typo or a pasted internal address is refused rather than dialled."""
    addressed = True

    def __init__(self, name, *, host, **kw):
        super().__init__(name, **kw)
        self.host = str(host).lower().lstrip("*")   # ".zid.sa" — any subdomain of it, and nothing else

    def _ok(self, url):
        """https, on the declared domain, with no credentials in it. Everything else is someone
        else's server — or an address inside our own network."""
        u = urlparse(str(url or ""))
        h = (u.hostname or "").lower()
        return bool(u.scheme == "https" and not u.username
                    and (h == self.host.lstrip(".") or h.endswith(self.host if self.host.startswith(".") else "." + self.host)))

    def validate(self, value):
        return None if self._ok(value) else f"That should be an https link on {self.host.lstrip('.')}"

    async def bearer(self, ws):
        return None   # nothing to send; the address carries the authority

    async def endpoint(self, ws):
        grant = await credentials.get(ws, self.name)
        url = (grant or {}).get("key")
        return url if self._ok(url) else None


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


CLIENT_NAME = "Cycls"   # what a provider's consent screen calls us; changing it re-registers on next connect


async def _register(meta, redirect, name):
    """Dynamic client registration (RFC 7591): a public client with PKCE and one redirect — no app to pre-register."""
    import httpx2
    async with httpx2.AsyncClient(timeout=15) as h:
        r = await h.post(meta["registration_endpoint"], json={
            "client_name": CLIENT_NAME, "redirect_uris": [redirect], "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none"})
    r.raise_for_status()
    return {"client_id": r.json()["client_id"], "redirect": redirect, "issuer": meta.get("issuer"), "name": CLIENT_NAME}


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
        if not row or row.get("redirect") != redirect or row.get("issuer") != meta.get("issuer") or row.get("name") != CLIENT_NAME:
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
            # GitHub answers form-encoded unless asked otherwise, and `.json()` would throw on it.
            r = await h.post(client["token"], headers={"Accept": "application/json"},
                             data={"client_id": client["client_id"], **({"client_secret": secret} if secret else {}),
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

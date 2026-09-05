"""cycls.OAuth2 — a grant a person makes for themselves or a workspace.

The flow is standard authorization-code with PKCE: `authorize_url` sends the
browser out, the callback route exchanges the code, `bearer` hands a live
token to a tool and refreshes it when it has expired. The state that rides
through the provider is signed with the same key the credential store uses,
and names the user and workspace — the callback carries no JWT. Secrets are
`cycls.env("NAME")` references, resolved when used, never pickled.
"""
import base64, hashlib, hmac, json, os, time
from dataclasses import dataclass
from urllib.parse import urlencode
from . import credentials


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


class OAuth2:
    def __init__(self, name, *, authorize, token, client_id, secret, scopes=(), scope="user", extra=None,
                 description=None, icon=None):
        if scope not in ("user", "workspace"):
            raise ValueError(f'scope must be "user" or "workspace"; got {scope!r}')
        self.name, self.authorize, self.token = name, authorize, token
        self.client_id, self.secret, self.scopes = client_id, secret, list(scopes)
        self.scope, self.extra = scope, dict(extra or {})
        self.description, self.icon = description, icon   # what the directory card shows

    @property
    def shared(self):
        return self.scope == "workspace"

    def authorize_url(self, redirect_uri, state, verifier):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        return self.authorize + "?" + urlencode({
            "response_type": "code", "client_id": _val(self.client_id), "redirect_uri": redirect_uri,
            "scope": " ".join(self.scopes), "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256", **self.extra})

    async def _token(self, **form):
        import httpx2
        async with httpx2.AsyncClient(timeout=30) as c:
            r = await c.post(self.token, data={"client_id": _val(self.client_id),
                                               "client_secret": _val(self.secret), **form})
        r.raise_for_status()
        t = r.json()
        return {"access_token": t["access_token"], "refresh_token": t.get("refresh_token"),
                "expires_at": time.time() + t.get("expires_in", 3600)}

    async def exchange(self, code, redirect_uri, verifier):
        return await self._token(grant_type="authorization_code", code=code,
                                 redirect_uri=redirect_uri, code_verifier=verifier)

    async def refresh(self, grant):
        new = await self._token(grant_type="refresh_token", refresh_token=grant["refresh_token"])
        return {**new, "refresh_token": new["refresh_token"] or grant["refresh_token"]}

    async def bearer(self, ws):
        """A live access token for this workspace's caller, refreshed if stale; None when not connected."""
        grant = await credentials.get(ws, self.name)
        if not grant:
            return None
        if grant["expires_at"] < time.time() + 60:
            grant = await self.refresh(grant)
            await credentials.put(ws, self.name, grant, shared=self.shared)
        return grant["access_token"]

"""Auth — JWT primitives, framework-agnostic verification, FastAPI adapter.

Two layers:
- **Core**: `User`, `JWT`, `Clerk`, `verify_jwt`, `InvalidToken`. No HTTP
  framework imports. Anyone wiring auth into a different ASGI framework
  (Starlette, Litestar, Quart, custom) imports from here.
- **Adapter**: `make_validate` builds a FastAPI `Depends` on top of
  `verify_jwt`. The default cycls App and Agent use this.

Lives at the App layer (not Agent) because auth is a cross-cutting HTTP
protection capability. `@cycls.app` and `@cycls.agent` both pick it up.
"""
from typing import Optional

from pydantic import BaseModel


# =============================================================================
# Core — framework-agnostic JWT primitives
# =============================================================================

class User(BaseModel):
    id: str
    org_id: Optional[str] = None
    org_slug: Optional[str] = None
    org_role: Optional[str] = None
    org_permissions: Optional[list] = None
    plan: Optional[str] = None
    features: Optional[list] = None


class JWT:
    """Generic JWT provider — supports dual-mode (dev/prod) out of the box.

    Every serious OIDC provider (Auth0, WorkOS, Okta, Supabase, Firebase,
    Clerk) expects a dev environment and a prod environment with separate
    JWKS URLs. Cycls picks the right one at serve time based on whether the
    agent is running via `.local()` (dev) or `.deploy()` (prod).

    Dev is optional — falls back to prod when not specified (single-env setups).
    """

    def __init__(
        self,
        jwks_url: str,
        dev_jwks_url: Optional[str] = None,
        issuer: Optional[str] = None,
        dev_issuer: Optional[str] = None,
    ):
        self.jwks_url = jwks_url
        self.dev_jwks_url = dev_jwks_url or jwks_url
        self.issuer = issuer
        self.dev_issuer = dev_issuer or issuer

    def resolve(self, prod: bool) -> dict:
        """Return the config dict Cycls wires into Config at serve time."""
        return {
            "jwks_url": self.jwks_url if prod else self.dev_jwks_url,
            "issuer": self.issuer if prod else self.dev_issuer,
        }


class Clerk(JWT):
    """Clerk JWT provider. Pass a known app name (`Clerk("cycls.ai")`) to
    resolve hosted-Cycls Clerk defaults, or explicit `jwks_url`/`pk` for a
    custom Clerk app. Adds publishable keys (pk) on top of the base JWT for
    the browser SDK."""

    APPS = {
        "cycls.ai": {
            "jwks_url":     "https://clerk.cycls.ai/.well-known/jwks.json",
            "dev_jwks_url": "https://select-sloth-58.clerk.accounts.dev/.well-known/jwks.json",
            "pk":           "pk_live_Y2xlcmsuY3ljbHMuYWkk",
            "dev_pk":       "pk_test_c2VsZWN0LXNsb3RoLTU4LmNsZXJrLmFjY291bnRzLmRldiQ",
        },
    }

    def __init__(
        self,
        app: Optional[str] = "cycls.ai",
        *,
        jwks_url: Optional[str] = None,
        dev_jwks_url: Optional[str] = None,
        pk: Optional[str] = None,
        dev_pk: Optional[str] = None,
        issuer: Optional[str] = None,
        dev_issuer: Optional[str] = None,
    ):
        if app:
            d = self.APPS[app]
            jwks_url     = jwks_url     or d["jwks_url"]
            dev_jwks_url = dev_jwks_url or d["dev_jwks_url"]
            pk           = pk           or d["pk"]
            dev_pk       = dev_pk       or d["dev_pk"]
        if not jwks_url:
            raise ValueError(
                "Clerk requires either a known app name (e.g. Clerk('cycls.ai')) "
                "or an explicit jwks_url for a custom Clerk app."
            )
        super().__init__(jwks_url, dev_jwks_url, issuer, dev_issuer)
        self.pk, self.dev_pk = pk, dev_pk

    def resolve(self, prod: bool) -> dict:
        result = super().resolve(prod)
        result["pk"] = self.pk if prod else self.dev_pk
        return result


class InvalidToken(Exception):
    """Raised by `verify_jwt` when validation fails."""


_jwks_clients: dict = {}


def verify_jwt(token: str, jwks_url: str) -> User:
    """Verify *token* against *jwks_url* and return a `User`. Raises
    `InvalidToken` on signature, expiry, format, or claims errors. Pure —
    no HTTP framework coupling. The PyJWKClient is cached per URL."""
    import jwt as jwtlib
    from jwt import PyJWKClient
    client = _jwks_clients.get(jwks_url)
    if client is None:
        client = PyJWKClient(jwks_url)
        _jwks_clients[jwks_url] = client
    try:
        key = client.get_signing_key_from_jwt(token)
        decoded = jwtlib.decode(token, key.key, algorithms=["RS256"], leeway=10)
    except Exception as e:
        raise InvalidToken(str(e))
    org = decoded.get("o") or {}
    fea = decoded.get("fea")
    if isinstance(fea, str):
        fea = [f.strip() for f in fea.split(",") if f.strip()]
    return User(
        id=decoded.get("sub"),
        org_id=org.get("id"),
        org_slug=org.get("slg"),
        org_role=org.get("rol"),
        org_permissions=org.get("per"),
        plan=decoded.get("pla"),
        features=fea,
    )


# =============================================================================
# Adapter — FastAPI dependency on top of `verify_jwt`
# =============================================================================

def make_validate(get_jwks_url):
    """Build a FastAPI dependency that validates a JWT via `verify_jwt`.

    `get_jwks_url` is a zero-arg callable returning the JWKS URL. Called
    lazily on the first request so agents can create the dependency at
    decoration time before `config.set_prod()` has populated the URL.
    """
    from fastapi import Depends, HTTPException, Request, status
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    def validate(
        request: Request,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    ) -> User:
        token = bearer.credentials if bearer else request.query_params.get("token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        url = get_jwks_url()
        if not url:
            raise HTTPException(500, "Auth not configured (missing JWKS URL)")
        try:
            return verify_jwt(token, url)
        except InvalidToken as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )

    return validate

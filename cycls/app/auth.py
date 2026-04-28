"""Auth — JWT + Clerk + framework-agnostic verify_jwt + FastAPI adapter."""
from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    id: str
    org_id: Optional[str] = None
    org_slug: Optional[str] = None
    org_role: Optional[str] = None
    org_permissions: Optional[list] = None
    plan: Optional[str] = None
    features: Optional[list] = None


class JWT:
    """JWT provider with dev/prod URL pairs. dev falls back to prod when omitted."""

    def __init__(self, jwks_url, dev_jwks_url=None, issuer=None, dev_issuer=None):
        self.jwks_url = jwks_url
        self.dev_jwks_url = dev_jwks_url or jwks_url
        self.issuer = issuer
        self.dev_issuer = dev_issuer or issuer

    def resolve(self, prod):
        return {
            "jwks_url": self.jwks_url if prod else self.dev_jwks_url,
            "issuer": self.issuer if prod else self.dev_issuer,
        }


_CLERK_APPS = {
    "cycls.ai": {
        "jwks_url":     "https://clerk.cycls.ai/.well-known/jwks.json",
        "dev_jwks_url": "https://select-sloth-58.clerk.accounts.dev/.well-known/jwks.json",
        "pk":           "pk_live_Y2xlcmsuY3ljbHMuYWkk",
        "dev_pk":       "pk_test_c2VsZWN0LXNsb3RoLTU4LmNsZXJrLmFjY291bnRzLmRldiQ",
    },
}


class Clerk(JWT):
    """Clerk provider. Adds publishable keys for the browser SDK.
    `Clerk("cycls.ai")` uses hosted defaults; pass explicit URLs for a custom app."""

    def __init__(self, app="cycls.ai", *, jwks_url=None, dev_jwks_url=None,
                 pk=None, dev_pk=None, issuer=None, dev_issuer=None):
        d = _CLERK_APPS.get(app, {})
        super().__init__(
            jwks_url or d.get("jwks_url"),
            dev_jwks_url or d.get("dev_jwks_url"),
            issuer, dev_issuer,
        )
        if not self.jwks_url:
            raise ValueError("Clerk requires app='cycls.ai' or an explicit jwks_url")
        self.pk = pk or d.get("pk")
        self.dev_pk = dev_pk or d.get("dev_pk")

    def resolve(self, prod):
        return {**super().resolve(prod), "pk": self.pk if prod else self.dev_pk}


class InvalidToken(Exception): pass


_jwks_clients: dict = {}


def verify_jwt(token, jwks_url):
    """Verify *token* against *jwks_url*; return a User or raise InvalidToken."""
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


def make_validate(get_jwks_url):
    """FastAPI Depends factory. `get_jwks_url` resolves the URL lazily on first request."""
    from fastapi import Depends, HTTPException, Request
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    def validate(
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    ) -> User:
        # Authorization header only. Native browser loads (img/anchor/window.open)
        # that can't set headers go through HMAC-signed `/shared/...` URLs instead
        # — see `App.signed_url`.
        if not bearer:
            raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
        url = get_jwks_url()
        if not url:
            raise HTTPException(500, "Auth not configured (missing JWKS URL)")
        try:
            return verify_jwt(bearer.credentials, url)
        except InvalidToken as e:
            raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"})

    return validate

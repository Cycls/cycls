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

    def __init__(self, jwks_url, dev_jwks_url=None):
        self.jwks_url = jwks_url
        self.dev_jwks_url = dev_jwks_url or jwks_url

    def resolve(self, prod):
        return {"jwks_url": self.jwks_url if prod else self.dev_jwks_url}


_CLERK_DEFAULTS = {
    "jwks_url":     "https://clerk.cycls.ai/.well-known/jwks.json",
    "dev_jwks_url": "https://select-sloth-58.clerk.accounts.dev/.well-known/jwks.json",
    "pk":           "pk_live_Y2xlcmsuY3ljbHMuYWkk",
    "dev_pk":       "pk_test_c2VsZWN0LXNsb3RoLTU4LmNsZXJrLmFjY291bnRzLmRldiQ",
}


class Clerk(JWT):
    """Clerk provider with hosted defaults; pass explicit URLs to override."""

    def __init__(self, *, jwks_url=None, dev_jwks_url=None, pk=None, dev_pk=None):
        super().__init__(
            jwks_url or _CLERK_DEFAULTS["jwks_url"],
            dev_jwks_url or _CLERK_DEFAULTS["dev_jwks_url"],
        )
        self.pk = pk or _CLERK_DEFAULTS["pk"]
        self.dev_pk = dev_pk or _CLERK_DEFAULTS["dev_pk"]

    def resolve(self, prod):
        return {**super().resolve(prod), "pk": self.pk if prod else self.dev_pk}


class InvalidToken(Exception): pass


_jwks_clients = {}


def verify_jwt(token, jwks_url):
    import jwt as jwtlib
    from jwt import PyJWKClient
    client = _jwks_clients.setdefault(jwks_url, PyJWKClient(jwks_url))
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
        id=decoded.get("sub"), plan=decoded.get("pla"), features=fea,
        org_id=org.get("id"), org_slug=org.get("slg"),
        org_role=org.get("rol"), org_permissions=org.get("per"),
    )


def make_validate(jwks_url):
    from fastapi import Depends, HTTPException
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    def validate(
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    ) -> User:
        # Authorization header only. Native browser loads (img/anchor/window.open)
        # that can't set headers go through HMAC-signed `/shared/...` URLs instead
        # — see `App.signed_url`.
        if not bearer:
            raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
        if not jwks_url:
            raise HTTPException(500, "Auth not configured (missing JWKS URL)")
        try:
            return verify_jwt(bearer.credentials, jwks_url)
        except InvalidToken as e:
            raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"})

    return validate

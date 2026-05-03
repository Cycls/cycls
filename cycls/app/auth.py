"""Auth — JWT/Clerk providers and a FastAPI Depends factory."""
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

    def claims_to_user(self, decoded) -> "User":
        return User(id=decoded.get("sub"))


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

    def claims_to_user(self, decoded) -> "User":
        org = decoded.get("o") or {}
        fea = decoded.get("fea")
        if isinstance(fea, str):
            fea = [f.strip() for f in fea.split(",") if f.strip()]
        return User(
            id=decoded.get("sub"), plan=decoded.get("pla"), features=fea,
            org_id=org.get("id"), org_slug=org.get("slg"),
            org_role=org.get("rol"), org_permissions=org.get("per"),
        )


class GCP(JWT):
    """GCP Identity Platform / Firebase Auth.
    Maps `firebase.tenant` → `org_id` so multi-tenant projects share workspace
    semantics with Clerk orgs (org-shared root, per-user DB)."""

    def __init__(self, project_id, *, jwks_url=None):
        super().__init__(jwks_url or
            "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com")
        self.project_id = project_id

    def claims_to_user(self, decoded) -> "User":
        tenant = (decoded.get("firebase") or {}).get("tenant")
        return User(id=decoded.get("sub"), org_id=tenant)


_jwks_clients = {}


def validator(provider, prod):
    import jwt as jwtlib
    from jwt import PyJWKClient
    from fastapi import Depends, HTTPException
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    jwks_url = provider.resolve(prod)["jwks_url"] if provider else None

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
            client = _jwks_clients.setdefault(jwks_url, PyJWKClient(jwks_url))
            key = client.get_signing_key_from_jwt(bearer.credentials)
            decoded = jwtlib.decode(bearer.credentials, key.key, algorithms=["RS256"], leeway=10)
        except Exception as e:
            raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"})
        return provider.claims_to_user(decoded)

    return validate

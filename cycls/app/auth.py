"""Auth providers — Clerk JWT, generic JWT base, User model, FastAPI validator.

Lives at the App layer (not Agent) because auth is a cross-cutting HTTP
protection capability. `@cycls.app` and `@cycls.agent` both pick it up.
User code references the FastAPI dependency via `Depends(my_agent.auth)`
or `Depends(my_app.auth)`.
"""
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel


# ---- Clerk defaults ----

JWKS_PROD = "https://clerk.cycls.ai/.well-known/jwks.json"
JWKS_TEST = "https://select-sloth-58.clerk.accounts.dev/.well-known/jwks.json"
PK_LIVE = "pk_live_Y2xlcmsuY3ljbHMuYWkk"
PK_TEST = "pk_test_c2VsZWN0LXNsb3RoLTU4LmNsZXJrLmFjY291bnRzLmRldiQ"


# ---- User model ----

class User(BaseModel):
    id: str
    org_id: Optional[str] = None
    org_slug: Optional[str] = None
    org_role: Optional[str] = None
    org_permissions: Optional[list] = None
    plan: Optional[str] = None
    features: Optional[list] = None

    @property
    def workspace(self) -> Path:
        return Path(f"/workspace/{self.org_id}") if self.org_id else Path(f"/workspace/{self.id}")

    @property
    def sessions(self) -> Path:
        return self.workspace / ".sessions" / self.id if self.org_id else self.workspace / ".sessions"


# ---- JWT provider primitives ----

class JWT:
    """Generic JWT provider. Pass to `@cycls.app(auth=...)` or
    `@cycls.agent(auth=...)`. Subclass for named wrappers (Clerk, Auth0, ...)."""
    def __init__(self, jwks_url: str, issuer: Optional[str] = None):
        self.jwks_url = jwks_url
        self.issuer = issuer


class Clerk(JWT):
    """Clerk JWT provider. Defaults to Cycls's Clerk instance; override
    `jwks_url` / `issuer` to point at your own Clerk tenant."""
    def __init__(self, prod: bool = True, jwks_url: Optional[str] = None, issuer: Optional[str] = None):
        super().__init__(
            jwks_url=jwks_url or (JWKS_PROD if prod else JWKS_TEST),
            issuer=issuer,
        )


# ---- FastAPI dependency factory ----

def make_validate(source: Any):
    """Build a FastAPI dependency that validates a Clerk JWT.

    `source` is a JWT/Clerk provider (has `.jwks_url`) or a Config-like
    object (has `.jwks`). Captured by reference so jwks_url can be read
    lazily at first request — lets agents create the dependency at decoration
    time before `config.set_prod()` has populated the real URL.
    """
    from fastapi import Depends, HTTPException, Request, status
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    import jwt as jwtlib
    from jwt import PyJWKClient

    _jwks = [None]

    def _resolve_jwks_url():
        return getattr(source, 'jwks_url', None) or getattr(source, 'jwks', None)

    def validate(
        request: Request,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    ) -> User:
        if _jwks[0] is None:
            url = _resolve_jwks_url()
            if not url:
                raise HTTPException(500, "Auth not configured (missing JWKS URL)")
            _jwks[0] = PyJWKClient(url)
        token = bearer.credentials if bearer else request.query_params.get("token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            key = _jwks[0].get_signing_key_from_jwt(token)
            decoded = jwtlib.decode(token, key.key, algorithms=["RS256"], leeway=10)
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
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )

    return validate

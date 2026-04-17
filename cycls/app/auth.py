"""Auth providers — Clerk JWT, generic JWT base, User model, FastAPI validator.

Lives at the App layer (not Agent) because auth is a cross-cutting HTTP
protection capability. `@cycls.app` and `@cycls.agent` both pick it up.
User code references the FastAPI dependency via `Depends(my_agent.auth)`
or `Depends(my_app.auth)`.
"""
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel


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

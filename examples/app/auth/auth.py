# uv run cycls run examples/app/auth/auth.py
"""Clerkless auth — JWT + scrypt + SlateDB. No external services.

Self-issued HS256 JWTs signed by `app.signing_key` (the bucket-persisted
HMAC the same App uses for signed URLs). User credentials live in a global
SlateDB at `<volume>/_users/.cycls/`. Per-user workspaces work the same as
with Clerk — once `validate()` returns a User, `workspace_for(user, ...)`
gives you the per-tenant fs + db.

Demonstrates that "auth provider" in cycls is really just two functions:
issue a Bearer token, validate one. Clerk is one provider; this is another;
they're interchangeable behind the same User contract.
"""
import hashlib
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import cycls
from cycls.app.auth import User
from cycls.app.db import Workspace, workspace_for

HTML_PATH = str(Path(__file__).parent / "auth.html")


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt.hex() + ":" + h.hex()


def verify_password(pw: str, stored: str) -> bool:
    salt_hex, h_hex = stored.split(":", 1)
    expected = hashlib.scrypt(
        pw.encode(), salt=bytes.fromhex(salt_hex),
        n=2**14, r=8, p=1, dklen=32,
    ).hex()
    return secrets.compare_digest(expected, h_hex)


@cycls.app(image=cycls.Image().copy(HTML_PATH, "auth.html"))
def auth_app():
    import jwt as jwtlib
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from pydantic import BaseModel

    app = FastAPI(title="Local Auth")

    SECRET = auth_app.signing_key  # bucket-persisted; survives restarts
    ISSUER = "cycls-local"
    TTL = 7 * 24 * 3600

    # One global user store for the whole deployment.
    users_ws = Workspace(auth_app.volume, "_users", bucket=auth_app.bucket)
    users = cycls.DB(users_ws).kv("users")

    def issue_token(user_id: str) -> str:
        return jwtlib.encode(
            {"sub": user_id, "iss": ISSUER, "exp": int(time.time()) + TTL},
            SECRET, algorithm="HS256",
        )

    async def validate(
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    ) -> User:
        if not bearer:
            raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
        try:
            decoded = jwtlib.decode(
                bearer.credentials, SECRET, algorithms=["HS256"], issuer=ISSUER,
            )
        except Exception as e:
            raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"})
        return User(id=decoded["sub"])

    auth = Depends(validate)

    def _build_ws(user: User = auth) -> Workspace:
        return workspace_for(user, auth_app.volume, auth_app.bucket)
    workspace = Depends(_build_ws)

    class AuthIn(BaseModel):
        email: str
        password: str

    @app.get("/")
    async def index():
        return HTMLResponse(Path("auth.html").read_text())

    @app.post("/signup")
    async def signup(body: AuthIn):
        if len(body.password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        if await users.get(body.email):
            raise HTTPException(409, "Email already registered")
        uid = "u_" + uuid4().hex[:12]
        await users.put(body.email, {
            "id": uid, "email": body.email,
            "pw": hash_password(body.password),
            "createdAt": datetime.now(timezone.utc).isoformat(),
        })
        return {"token": issue_token(uid), "id": uid, "email": body.email}

    @app.post("/login")
    async def login(body: AuthIn):
        record = await users.get(body.email)
        if not record or not verify_password(body.password, record["pw"]):
            raise HTTPException(401, "Invalid credentials")
        return {"token": issue_token(record["id"]),
                "id": record["id"], "email": body.email}

    @app.get("/me")
    async def me(user: User = auth):
        return user

    # Demo route — exercises the per-tenant workspace to show end-to-end isolation.
    @app.post("/notes")
    async def add_note(request: Request, ws=workspace):
        data = await request.json()
        nid = uuid4().hex[:8]
        note = {"id": nid, "text": data.get("text", ""),
                "at": datetime.now(timezone.utc).isoformat()}
        await cycls.DB(ws).kv("notes").put(nid, note)
        return note

    @app.get("/notes")
    async def list_notes(ws=workspace):
        return [v async for _, v in cycls.DB(ws).kv("notes").items()]

    return app

"""Share tokens — opaque random tokens in the owner's workspace, audience-checked at resolve. See RFC003."""
import secrets
import time

from .workspace import DB

DEFAULT_TTL = 7 * 24 * 3600


async def mint(workspace, path, audience="public", ttl=DEFAULT_TTL):
    token = secrets.token_urlsafe(16)
    row = {"path": path, "audience": audience, "exp": int(time.time()) + ttl}
    await DB(workspace).put(f"share/{token}", row)
    return token, row


async def resolve(workspace, token, requester=None):
    row = await DB(workspace).get(f"share/{token}")
    if not row or row["exp"] < time.time():
        return None
    aud = row.get("audience", "public")
    if aud == "public":
        return row
    if aud.startswith("org:") and getattr(requester, "org_id", None) == aud[4:]:
        return row
    return None


async def revoke(workspace, token):
    await DB(workspace).delete(f"share/{token}")

"""Share tokens — opaque random tokens in the owner's workspace, audience-checked at resolve. See RFC003."""
import secrets
import time
from datetime import datetime, timezone

from cycls.app.workspace import DB


async def mint(workspace, path, audience="public", ttl=None, author=None):
    """ttl in seconds; None (the default) = the share never expires — revoke
    explicitly via `revoke()`. Pass an int for a short-lived link."""
    token = secrets.token_urlsafe(16)
    row = {
        "path": path,
        "audience": audience,
        "shared_at": datetime.now(timezone.utc).isoformat(),
    }
    if ttl is not None:
        row["exp"] = int(time.time()) + int(ttl)
    if author is not None:
        row["author"] = author
    # Durable: a lost share token = silent UX failure (link 404s forever).
    await DB(workspace).put(f"share/{token}", row, durable=True)
    return token, row


async def resolve(workspace, token, requester=None):
    row = await DB(workspace).get(f"share/{token}")
    if not row or ("exp" in row and row["exp"] < time.time()):
        return None
    aud = row.get("audience", "public")
    if aud == "public":
        return row
    if aud.startswith("org:") and getattr(requester, "org_id", None) == aud[4:]:
        return row
    return None


async def revoke(workspace, token):
    # Durable: a lost revoke = stale share remains live (mild security issue).
    await DB(workspace).delete(f"share/{token}", durable=True)

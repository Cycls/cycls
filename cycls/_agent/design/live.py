"""The Cycls side of the live relay (`cycls-design-live`): it only passes bytes, so who may enter a
room is decided here. Needs DESIGN_LIVE_URL and DESIGN_LIVE_SECRET (the relay's LIVE_SECRET)."""
import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

TICKET_TTL = 600        # seconds; the editor asks anew on each connect
WAKE_TIMEOUT = 6.0
NOTIFY_TIMEOUT = 8.0    # the relay offers an edit to editors in turn, up to ~4 s


def _url():
    return (os.environ.get("DESIGN_LIVE_URL") or "").rstrip("/")


def _secret():
    return os.environ.get("DESIGN_LIVE_SECRET") or ""


def configured():
    return bool(_url() and _secret())


def socket_url():
    """The relay as a browser opens it: wss:// for https://, ws:// for http://."""
    url = _url()
    return "ws" + url[4:] if url.startswith("http") else url


def room_of(root, rel):
    """The design's room, keyed with the secret so nobody outside can name it."""
    where = f"{Path(root).resolve().as_posix()}|{Path(rel).as_posix()}"
    return hmac.new(_secret().encode(), where.encode(), hashlib.sha256).hexdigest()[:40]


def ticket(room, user_id, ttl=TICKET_TTL):
    """`<base64url {room, user, exp}>.<hex HMAC-SHA256>` — live/ticket.ts checks it; change both together."""
    body = json.dumps({"room": room, "user": str(user_id), "exp": int(time.time()) + ttl}, separators=(",", ":"))
    body = base64.urlsafe_b64encode(body.encode()).rstrip(b"=").decode()
    return f"{body}.{hmac.new(_secret().encode(), body.encode(), hashlib.sha256).hexdigest()}"


async def wake():
    """Wake a sleeping relay before handing out a room, or the first editor opens alone. Never raises."""
    if not configured():
        return
    import httpx
    try:
        async with httpx.AsyncClient(timeout=WAKE_TIMEOUT) as http:
            await http.get(f"{_url()}/health")
    except Exception:
        pass


async def notify(root, rel, body):
    """Post `body` into the design's room → `{ok, peers, delivered}`, or None. Never raises."""
    if not configured():
        return None
    import httpx
    try:
        async with httpx.AsyncClient(timeout=NOTIFY_TIMEOUT) as http:
            r = await http.post(f"{_url()}/room/{room_of(root, rel)}/notify", json=body,
                                headers={"Authorization": f"Bearer {_secret()}"})
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

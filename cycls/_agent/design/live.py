"""Working in one design together — the Cycls side of the live relay.

The people who have a design open meet in a room of `cycls-design-live` (the service
repo's live/server.ts): their editors keep one shared document in step there, and one
of them saves it. The relay only passes bytes; who may enter is decided here, where
the workspace is known:

- `room_of` names a design's room — the same for everyone the workspace lets in, a
  name nobody outside can work out (it is keyed with the secret).
- `ticket` is one person's pass for one room, for a short while. The relay checks the
  signature (live/ticket.ts is the same few lines in TypeScript — change both
  together); the editor asks for a new one whenever it connects again.
- `wake` rings the relay before a room is handed out (it sleeps when all rooms are empty).
- `notify` is the server speaking into a room: an agent's edit, for ONE editor to make
  so everyone gets it (`delivered` says whether one took it); or "the file was written
  anew, open it again".

Wired by env, like DESIGN_URL: `DESIGN_LIVE_URL` (https://…, the relay) and
`DESIGN_LIVE_SECRET` (the relay's LIVE_SECRET). Without both nothing is live and every
design opens alone, as before.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

TICKET_TTL = 600        # seconds — a pass is shown when connecting, not kept
WAKE_TIMEOUT = 6.0      # how long a sleeping relay is waited for before the room is handed out anyway
NOTIFY_TIMEOUT = 8.0    # a room that can't be told must not hold up an edit (the relay
                        # offers an edit to the editors in turn: up to ~4 s before it answers)


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
    """The room of the design at `rel` in the workspace whose files are at `root`."""
    where = f"{Path(root).resolve().as_posix()}|{Path(rel).as_posix()}"
    return hmac.new(_secret().encode(), where.encode(), hashlib.sha256).hexdigest()[:40]


def ticket(room, user_id, ttl=TICKET_TTL):
    """`<base64url {room, user, exp}>.<hex HMAC-SHA256 of that text>`."""
    body = json.dumps({"room": room, "user": str(user_id), "exp": int(time.time()) + ttl}, separators=(",", ":"))
    body = base64.urlsafe_b64encode(body.encode()).rstrip(b"=").decode()
    return f"{body}.{hmac.new(_secret().encode(), body.encode(), hashlib.sha256).hexdigest()}"


async def wake():
    """Ring the relay. It sleeps when nobody is in any room, and an editor gives it only
    a few seconds to answer before it opens the design alone — which would leave the
    first person of the morning outside the room the second one enters. Never raises."""
    if not configured():
        return
    import httpx
    try:
        async with httpx.AsyncClient(timeout=WAKE_TIMEOUT) as http:
            await http.get(f"{_url()}/health")
    except Exception:
        pass


async def notify(root, rel, body):
    """Say `body` into the design's room → the relay's answer `{ok, peers, delivered}`,
    or None when nothing is live or the relay can't be reached. Never raises: a room
    that can't be told is a room that finds out on its next save."""
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

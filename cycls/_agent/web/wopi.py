"""WOPI host for editable Office on the canvas, via Collabora Online.

A browser can't edit Word/Excel/PowerPoint natively, so the canvas embeds a
Collabora Online editor (LibreOffice, the same engine as office-render). Collabora
renders and edits the document server-side and streams the editor into an iframe;
to reach the actual file it speaks the WOPI protocol back to THIS host:

  GET  /wopi/files/{id}            CheckFileInfo — name, size, version, can-write
  GET  /wopi/files/{id}/contents   GetFile       — the bytes to open
  POST /wopi/files/{id}/contents   PutFile        — the edited bytes to save back
  POST /wopi/files/{id}            Lock/Unlock    — edit-session locks (in-memory)

Those calls come from the Collabora server, not the browser, so they can't carry
the user's JWT. Instead the browser first hits `GET /wopi/editor?path=…` (authed
normally); we mint a short-lived HMAC-signed access_token that encodes the
workspace + file + write permission, hand back the editor URL, and Collabora
echoes the token on every WOPI call. The token IS the credential — unforgeable,
scoped to one file, and expiring.

Config (env):
  COLLABORA_URL           browser-facing base, e.g. http://localhost:9980
  COLLABORA_URL_INTERNAL  how THIS host reaches Collabora for discovery
                          (defaults to COLLABORA_URL)
  WOPI_HOST_URL           how Collabora reaches THIS host (WOPISrc base),
                          e.g. http://host.docker.internal:8080
  WOPI_SECRET             token-signing secret (a per-process random is used if
                          unset — fine for a single instance, set it for a fleet)

Unset COLLABORA_URL and the feature is simply off (`configured()` is False); the
canvas falls back to the read-only PDF preview.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import JSONResponse

from cycls._app.db import workspace

# ext → MS mimetype, the key Collabora's discovery lists actions under. Only
# formats Collabora edits; everything else stays on the PDF/download path.
_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc":  "application/msword",
    "odt":  "application/vnd.oasis.opendocument.text",
    "rtf":  "application/rtf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls":  "application/vnd.ms-excel",
    "ods":  "application/vnd.oasis.opendocument.spreadsheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt":  "application/vnd.ms-powerpoint",
    "odp":  "application/vnd.oasis.opendocument.presentation",
}

_TOKEN_TTL = 24 * 3600     # a generous editing session; token is reused for its life


def _safe(root, rel):
    # Lazy import: routers imports us to register the router, so importing it at
    # module load would be circular.
    from cycls._agent.web.routers import resolve_path
    return resolve_path(root, rel)


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def editable(name):
    return _ext(name) in _MIME


def configured():
    return bool(os.environ.get("COLLABORA_URL"))


def _public_url():
    return (os.environ.get("COLLABORA_URL") or "").rstrip("/")


def _internal_url():
    return (os.environ.get("COLLABORA_URL_INTERNAL") or os.environ.get("COLLABORA_URL") or "").rstrip("/")


def _host_url(request):
    """Base URL Collabora uses to call back to us. Explicit in prod (Collabora
    is cross-origin); falls back to the request's own origin."""
    return (os.environ.get("WOPI_HOST_URL") or str(request.base_url)).rstrip("/")


# --- access token: HMAC-signed, self-contained, single-file scoped ------------

_SECRET = None


def _secret():
    global _SECRET
    if _SECRET is None:
        _SECRET = (os.environ.get("WOPI_SECRET") or secrets.token_hex(32)).encode()
    return _SECRET


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def mint(subject, ws_id, rel, user_id, can_write):
    """A signed token binding one file (subject/ws/path) to a permission + expiry."""
    body = {"s": subject, "w": ws_id, "p": rel, "u": user_id,
            "rw": bool(can_write), "exp": int(time.time()) + _TOKEN_TTL}
    payload = _b64e(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify(token):
    """The token's claims if the signature holds and it hasn't expired, else None."""
    try:
        payload, sig = token.split(".", 1)
    except (ValueError, AttributeError):
        return None
    expect = _b64e(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        body = json.loads(_b64d(payload))
    except Exception:
        return None
    if body.get("exp", 0) < time.time():
        return None
    return body


# --- Collabora discovery: mimetype → editor urlsrc ----------------------------

_discovery = {"at": 0, "map": {}}


async def _editor_src(mime):
    """The browser-facing `cool.html?` URL Collabora advertises for this mimetype.
    Cached — discovery is stable for a running Collabora."""
    if _discovery["map"] and _discovery["at"] > time.time() - 3600:
        return _discovery["map"].get(mime)
    base = _internal_url()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/hosting/discovery")
    root = ET.fromstring(resp.text)
    out = {}
    for app in root.iter("app"):
        name = app.get("name")
        action = app.find("action[@name='edit']") or app.find("action")
        if name and action is not None and action.get("urlsrc"):
            out[name] = action.get("urlsrc")
    _discovery.update(at=time.time(), map=out)
    return out.get(mime)


# In-memory WOPI locks: file_id → lock string. Fine for a single instance; a
# fleet would move this to shared storage.
_LOCKS = {}


def wopi_router(cycls_app, ws_dep, required_auth, volume, base):
    r = APIRouter()

    def _ws_from_token(tok):
        return workspace(tok["s"], volume, base=base, ws=tok["w"])

    def _resolve(file_id, token):
        """Validate the token, decode the file id, and return (Workspace, Path).
        Raises 401/403 on a bad or mismatched token."""
        claims = verify(token or "")
        if not claims:
            raise HTTPException(401, "invalid or expired WOPI token")
        rel = _b64d(file_id).decode("utf-8")
        if claims.get("p") != rel:
            raise HTTPException(403, "token does not match file")
        ws = _ws_from_token(claims)
        try:
            path = _safe(ws.root, rel)
        except ValueError:
            raise HTTPException(403, "path denied")
        return claims, ws, path

    @r.get("/wopi/editor")
    async def editor(path: str, request: Request, ws=ws_dep, user=required_auth):
        """Browser-facing, authed: mint a token for `path` and return the Collabora
        editor URL to drop into an iframe."""
        if not configured():
            raise HTTPException(503, "Collabora not configured")
        if not editable(path):
            raise HTTPException(415, f"not an editable office type: {path}")
        target = _safe(ws.root, path)
        if not Path(target).is_file():
            raise HTTPException(404, "file not found")
        mime = _MIME[_ext(path)]
        src = await _editor_src(mime)
        if not src:
            raise HTTPException(502, f"Collabora advertises no editor for {mime}")
        uid = getattr(user, "id", "user")
        token = mint(ws.subject, ws.ws, path, uid, can_write=True)
        file_id = _b64e(path.encode("utf-8"))
        wopi_src = f"{_host_url(request)}/wopi/files/{file_id}"
        # urlsrc ends with '?' or '&'; append our params.
        sep = "" if src.endswith(("?", "&")) else ("&" if "?" in src else "?")
        editor_url = f"{src}{sep}WOPISrc={wopi_src}&lang=ar"
        return {"editor_url": editor_url, "access_token": token,
                "access_token_ttl": (int(time.time()) + _TOKEN_TTL) * 1000}

    @r.get("/wopi/files/{file_id}")
    async def check_file_info(file_id: str, request: Request):
        """WOPI CheckFileInfo — the metadata Collabora needs to open the file."""
        token = request.query_params.get("access_token", "")
        claims, ws, path = _resolve(file_id, token)
        if not Path(path).is_file():
            raise HTTPException(404, "file not found")
        st = Path(path).stat()
        return JSONResponse({
            "BaseFileName": Path(path).name,
            "Size": st.st_size,
            "Version": str(st.st_mtime_ns),         # changes on every save → cache-busts
            "OwnerId": claims.get("s", "owner"),
            "UserId": claims.get("u", "user"),
            "UserFriendlyName": claims.get("u", "user"),
            "UserCanWrite": bool(claims.get("rw")),
            "UserCanNotWriteRelative": True,        # no "save as" into the workspace
            "SupportsUpdate": True,
            "SupportsLocks": True,
            "SupportsGetLock": True,
        })

    @r.get("/wopi/files/{file_id}/contents")
    async def get_file(file_id: str, request: Request):
        """WOPI GetFile — the bytes Collabora opens."""
        token = request.query_params.get("access_token", "")
        _claims, _ws, path = _resolve(file_id, token)
        if not Path(path).is_file():
            raise HTTPException(404, "file not found")
        return Response(content=Path(path).read_bytes(),
                        media_type="application/octet-stream")

    @r.post("/wopi/files/{file_id}/contents")
    async def put_file(file_id: str, request: Request):
        """WOPI PutFile — persist the edited document back to the workspace."""
        token = request.query_params.get("access_token", "")
        claims, ws, path = _resolve(file_id, token)
        if not claims.get("rw"):
            raise HTTPException(403, "read-only token")
        # Honour the edit lock: reject a save whose lock doesn't match ours.
        held = _LOCKS.get(file_id)
        sent = request.headers.get("x-wopi-lock")
        if held and sent and held != sent:
            return Response(status_code=409, headers={"X-WOPI-Lock": held})
        body = await request.body()
        if body:                                    # Collabora sends empty bodies for some no-ops
            await _atomic_write(Path(path), body)
        return Response(status_code=200)

    @r.post("/wopi/files/{file_id}")
    async def lock_ops(file_id: str, request: Request):
        """WOPI lock lifecycle (LOCK / UNLOCK / REFRESH_LOCK / GET_LOCK). A single
        in-memory lock per file is enough for one editing session."""
        token = request.query_params.get("access_token", "")
        _resolve(file_id, token)                    # auth only
        op = request.headers.get("x-wopi-override", "")
        lock = request.headers.get("x-wopi-lock", "")
        held = _LOCKS.get(file_id)
        if op == "GET_LOCK":
            return Response(status_code=200, headers={"X-WOPI-Lock": held or ""})
        if op in ("LOCK", "PUT"):
            old = request.headers.get("x-wopi-oldlock")
            if held and held != (old or lock):
                return Response(status_code=409, headers={"X-WOPI-Lock": held})
            _LOCKS[file_id] = lock
            return Response(status_code=200)
        if op == "REFRESH_LOCK":
            if held != lock:
                return Response(status_code=409, headers={"X-WOPI-Lock": held or ""})
            return Response(status_code=200)
        if op == "UNLOCK":
            if held != lock:
                return Response(status_code=409, headers={"X-WOPI-Lock": held or ""})
            _LOCKS.pop(file_id, None)
            return Response(status_code=200)
        raise HTTPException(400, f"unsupported X-WOPI-Override: {op}")

    return r


async def _atomic_write(path, data):
    import asyncio

    def _do():
        tmp = path.with_suffix(path.suffix + f".wopi-{secrets.token_hex(4)}.part")
        tmp.write_bytes(data)
        tmp.replace(path)      # atomic swap so a reader never sees a half-written doc

    await asyncio.to_thread(_do)

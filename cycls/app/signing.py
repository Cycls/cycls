"""HMAC-signed URLs — short-lived, copy-pasteable links to per-tenant
resources without requiring the caller to hold a JWT.

A signed URL is a path + user_id + expiry, authenticated by HMAC-SHA256.
The signature IS the proof of authorization — no server-side state, no
auth lookup. Anyone with the URL has the access it grants until `exp`.

Standard pattern (S3 presigned, GCS signed URLs, CloudFront). Use it
for any resource access route where the caller is a browser doing a
native load (`<img>`, `<a href>`, `window.open`) and adding an
Authorization header isn't an option.
"""
import hmac
import hashlib
import secrets
import time


def _digest(secret: bytes, path: str, user_id: str, exp: int) -> str:
    msg = f"{path}\n{user_id}\n{exp}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def sign(path: str, user_id: str, secret: bytes, ttl: int = 3600) -> dict:
    """Sign a (path, user_id) pair with TTL seconds. Returns the URL params."""
    exp = int(time.time()) + ttl
    return {"path": path, "user": user_id, "exp": exp,
            "sig": _digest(secret, path, user_id, exp)}


def verify(path: str, user_id: str, exp: int, sig: str, secret: bytes) -> bool:
    """Constant-time verify. Returns False on bad sig, expired, or any error."""
    try:
        if int(exp) < time.time():
            return False
        expected = _digest(secret, path, str(user_id), int(exp))
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


def new_secret() -> bytes:
    """32 random bytes for use as an HMAC signing secret."""
    return secrets.token_bytes(32)

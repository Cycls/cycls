"""HMAC-signed URLs for browser native loads (img/anchor/window.open) that can't set
Authorization headers. The signature IS the auth — no server-side state."""
import hmac
import hashlib
import secrets
import time


def _digest(secret: bytes, path: str, user_id: str, exp: int) -> str:
    msg = f"{path}\n{user_id}\n{exp}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def sign(path: str, user_id: str, secret: bytes, ttl: int = 3600) -> dict:
    exp = int(time.time()) + ttl
    return {"path": path, "user": user_id, "exp": exp,
            "sig": _digest(secret, path, user_id, exp)}


def verify(path: str, user_id: str, exp: int, sig: str, secret: bytes) -> bool:
    """Constant-time HMAC verify; False on bad sig, expired, or error."""
    try:
        if int(exp) < time.time():
            return False
        return hmac.compare_digest(_digest(secret, path, str(user_id), int(exp)), sig)
    except Exception:
        return False


def new_secret() -> bytes:
    return secrets.token_bytes(32)

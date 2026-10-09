"""The contract: what the model is taught about writing a video, fetched from the service and
verified before it reaches a tool description.

The service serves it signed (Ed25519) with a key kept off Modal; the SDK holds the public keys
and refuses anything that does not verify, so changing the text means signing it, not merely
deploying the service. A contract change ships with the service and needs no agent redeploy.

Fetched with a 10-minute process cache. A turn start waits for it at most 4 s, then carries on
while a background fetch fills the cache; `guide` waits up to 30 s. When none can be had, or none
verifies, the built-in copy of contract v1 (fallback.py) is used and the reply says so.
"""
import asyncio
import base64
import hashlib
import time

from .fallback import FALLBACK

# key id -> raw Ed25519 public key, base64. Add a key here before signing with it.
PUBLIC_KEYS = {
    "cv1": "rfOkWAduGJ5hKuR6QxDFZyL6yn9PzE5JotSIyJO/kUE=",
}
_PREFIX = b"cycls-video-contract"
TTL = 600

_cache = {"at": 0.0, "value": None, "etag": None}
_task = None


def _message(key_id, version, text):
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return b"\n".join([_PREFIX, key_id.encode(), version.encode(), sha.encode()])


def verify(env):
    """Does this envelope carry a text signed with one of our keys?"""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEYS[env["key_id"]]))
        if hashlib.sha256(env["text"].encode("utf-8")).hexdigest() != env["sha256"]:
            return False
        key.verify(base64.b64decode(env["signature"]), _message(env["key_id"], env["version"], env["text"]))
        return True
    except (KeyError, TypeError, ValueError, InvalidSignature):
        return False


def _fallback(reason):
    return {"text": FALLBACK["text"], "version": FALLBACK["version"], "formats": FALLBACK["formats"],
            "fonts": FALLBACK["fonts"], "limits": FALLBACK["limits"], "fallback": reason}


async def _fetch():
    from cycls._agent import video

    try:
        body = await video.get_contract(_cache["etag"])
    except Exception as e:  # noqa: BLE001 - reported as the fallback's reason
        return None, f"the service could not be reached ({type(e).__name__})"
    if body is None:   # 304: what we have is current
        return _cache["value"], None
    env = body.get("envelope") or {}
    if not verify(env):
        return None, "the service's contract did not verify"
    value = {"text": env["text"], "version": env["version"], "formats": body.get("formats") or FALLBACK["formats"],
             "fonts": body.get("fonts") or FALLBACK["fonts"], "limits": body.get("limits") or FALLBACK["limits"],
             "bundle": body.get("bundle")}
    _cache.update(at=time.monotonic(), value=value, etag=body.get("etag"))
    return value, None


def cached():
    """The contract now, without waiting: the cache when fresh, else None."""
    v = _cache["value"]
    return v if v and time.monotonic() - _cache["at"] < TTL else None


async def get(wait):
    """The contract, waiting at most `wait` seconds for the service; the built-in copy when it
    cannot be had in time (a background fetch carries on and fills the cache)."""
    global _task
    if (v := cached()) is not None:
        return v
    if _task is None or _task.done():
        _task = asyncio.ensure_future(_fetch())
    try:
        value, reason = await asyncio.wait_for(asyncio.shield(_task), timeout=wait)
    except asyncio.TimeoutError:
        return _cache["value"] or _fallback("the service did not answer in time")
    return value or _cache["value"] or _fallback(reason)


def reset():
    """Tests: forget what was fetched."""
    global _task
    _cache.update(at=0.0, value=None, etag=None)
    _task = None

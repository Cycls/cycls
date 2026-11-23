"""Web Push from our own server (docs/rfc-notifications.md, Devices): each message encrypted to the browser's keys
(RFC 8291) and signed with our VAPID key (RFC 8292), sent straight to the browser's push service. No provider."""
import asyncio, base64, json, os, struct, time
from urllib.parse import urlsplit

import httpx, jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from cycls._agent.logs import log

_KEY = {}   # our VAPID key pair, once the server has one (VAPID_PRIVATE_KEY)


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _point(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def use(private):
    """Our key pair, from its private number (32 bytes, base64url): browsers subscribe with its public half."""
    key = ec.derive_private_key(int.from_bytes(unb64(private), "big"), ec.SECP256R1())
    _KEY.update(key=key, public=b64(_point(key)))


def public():
    return _KEY.get("public", "")


def _hkdf(salt, info, ikm, size):
    return HKDF(algorithm=hashes.SHA256(), length=size, salt=salt, info=info).derive(ikm)


def encrypt(keys, data, mine=None, salt=None):
    """`data` for one browser (aes128gcm): a fresh key of ours meets its `p256dh`, mixed with its `auth` secret."""
    theirs = unb64(keys["p256dh"])
    mine = mine or ec.generate_private_key(ec.SECP256R1())
    ours, salt = _point(mine), salt or os.urandom(16)
    ikm = _hkdf(unb64(keys["auth"]), b"WebPush: info\x00" + theirs + ours,
                mine.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), theirs)), 32)
    cek, nonce = (_hkdf(salt, f"Content-Encoding: {what}\x00".encode(), ikm, n) for what, n in (("aes128gcm", 16), ("nonce", 12)))
    return salt + struct.pack("!IB", 4096, len(ours)) + ours + AESGCM(cek).encrypt(nonce, data + b"\x02", None)


async def send(subs, message, contact):
    """`message(sub)` to each browser at once, signed as `contact` (where the app is). Returns the addresses its push
    service says are gone, to drop."""
    if not _KEY or not subs:
        return []

    async def one(client, sub):
        to = urlsplit(sub["endpoint"])
        token = jwt.encode({"aud": f"{to.scheme}://{to.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": contact},
                           _KEY["key"], algorithm="ES256")
        try:
            r = await client.post(sub["endpoint"], content=encrypt(sub["keys"], json.dumps(message(sub)).encode()), headers={
                "Content-Encoding": "aes128gcm", "TTL": "86400", "Urgency": "high",
                "Authorization": f"vapid t={token}, k={_KEY['public']}"})
        except Exception as e:
            log("warn", message=f"web push failed: {type(e).__name__}: {e}"[:300])
            return None
        if r.status_code in (404, 410):
            return sub["endpoint"]
        if r.status_code >= 300:
            log("warn", message=f"web push: {r.status_code} {r.text[:200]}")

    async with httpx.AsyncClient(timeout=10) as client:
        return [e for e in await asyncio.gather(*(one(client, s) for s in subs)) if e]

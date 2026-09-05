"""Credentials, encrypted at rest. A user's own live at {org}/.secrets/{user}
and follow the user into every workspace; a workspace's shared ones live at
{workspace.root}/.connectors. Both are masked in the bash sandbox and rejected
by the path guards, like .db. A record the current CYCLS_SECRET_KEY cannot
decrypt reads as absent — rotation means re-auth, never a crash.
"""
import base64, hashlib, json, os
from cryptography.fernet import Fernet, InvalidToken
from cycls._app.db import DB, workspace

USER, SHARED = ".secrets", ".connectors"


def key():
    k = os.environ.get("CYCLS_SECRET_KEY")
    if not k:
        raise RuntimeError("CYCLS_SECRET_KEY is required to store credentials")
    return k.encode()


def _fernet():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key()).digest()))


def _db(ws, shared):
    if shared:
        return DB(workspace(ws.subject.partition(":")[0], ws.volume, base=ws.base, slot=SHARED, ws=ws.ws))
    return DB(workspace(ws.subject, ws.volume, base=ws.base, slot=USER))


async def get(ws, name):
    """The user's record, else the workspace's, else None."""
    for shared in (False, True):
        if (row := await _db(ws, shared).get(name)) is not None:
            try:
                return json.loads(_fernet().decrypt(row["v"].encode()))
            except InvalidToken:
                pass
    return None


async def put(ws, name, value, *, shared=False):
    await _db(ws, shared).put(name, {"v": _fernet().encrypt(json.dumps(value).encode()).decode()})


async def delete(ws, name, *, shared=False):
    await _db(ws, shared).delete(name)

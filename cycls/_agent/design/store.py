"""The one way a `.fig` is written: check the writer's `base` version (`X-Version`; Stale → 412),
keep what it replaces (versions.py), then temp file + rename. Its own short lock, not `deck.lock`
(held for minutes), so an editor save never waits behind the agent.

In production the version a save is checked against is read from the workspace bucket itself
(`load_fig`): each server sees the volume through gcsfuse, whose metadata cache keeps a file as it was
for up to a minute after another server rewrites it, so a check made there refused good saves ("This
design changed elsewhere") after an agent edit landed through another server. The write itself still
goes through the volume, so this server's own view keeps up with it."""
import asyncio
import errno
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from .. import versions


class Stale(Exception):
    """The design changed since the version the writer started from."""

    def __init__(self, current):
        super().__init__(f"the design changed since it was read (now {current})")
        self.current = current


def version_of(data):
    return hashlib.sha256(data).hexdigest()[:16] if data is not None else ""


_locks = {}   # per instance; across instances the check reads the bucket (`load_fig`)
MOUNT = "/workspace"   # the agent's volume; CYCLS_VOLUMES names its bucket in production


def _lock(path):
    key = (id(asyncio.get_running_loop()), str(Path(path).resolve()))   # a lock belongs to one loop
    return _locks.setdefault(key, asyncio.Lock())


def read_fig(root, rel):
    """(bytes, version) of a design file; (None, "") when there is none. Just rewritten by another
    instance, it reads here as a stale handle (Errno 116) until this one's gcsfuse lets go of the
    object it replaced, a second or so: read again, then again."""
    for wait in (1, 2, 0):
        try:
            data = (Path(root) / rel).read_bytes()
        except FileNotFoundError:
            return None, ""
        except OSError as e:
            if e.errno != errno.ESTALE or not wait:
                raise
            time.sleep(wait)
            continue
        return data, version_of(data)


def _object(path):
    """(bucket, object) of a design on the workspace volume in production; None on a local run, where
    the disk is the only copy."""
    bucket = json.loads(os.environ.get("CYCLS_VOLUMES") or "{}").get(MOUNT)
    try:
        return (bucket, Path(path).relative_to(MOUNT).as_posix()) if bucket else None
    except ValueError:
        return None


async def load_fig(root, rel):
    """`read_fig` as the design is now: in production from the bucket, never a server's cached view."""
    if obj := _object(Path(root) / rel):
        from cycls._app.db import object_read
        data, _ = await object_read(*obj)
        return data, version_of(data)
    return await asyncio.to_thread(read_fig, root, rel)


async def write_fig(root, rel, data, *, base=None, by="user", reason="save", intent=None, force=False):
    """Write `data` to design `rel` → its new version. Raises Stale when `base` is no longer
    current, unless `force` ("keep mine"); no `base`: last write wins."""
    root = Path(root)
    async with _lock(root / rel):
        current, now = await load_fig(root, rel)
        return await asyncio.to_thread(_write, root, rel, bytes(data), current, now, base, by, reason, intent, force)


def _write(root, rel, data, current, now, base, by, reason, intent, force):
    path = root / rel
    if base is not None and not force and base != now:
        raise Stale(now)
    if current is not None and current != data:
        versions.snapshot(root, rel, current, by=by, reason=reason, intent=intent,
                          always=force or reason != "save")
    scratch = root / ".tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = scratch / f"{uuid.uuid4().hex}.part"
    tmp.write_bytes(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(path)
    return version_of(data)

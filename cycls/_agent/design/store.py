"""The one way a `.fig` is written: check the writer's `base` version (`X-Version`; Stale → 412),
keep what it replaces (versions.py), then temp file + rename. Its own short lock, not `deck.lock`
(held for minutes), so an editor save never waits behind the agent."""
import asyncio
import hashlib
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


_locks = {}   # per instance: gcsfuse caches metadata per instance; session affinity keeps a person on one


def _lock(path):
    key = (id(asyncio.get_running_loop()), str(Path(path).resolve()))   # a lock belongs to one loop
    return _locks.setdefault(key, asyncio.Lock())


def read_fig(root, rel):
    """(bytes, version) of a design file; (None, "") when there is none."""
    try:
        data = (Path(root) / rel).read_bytes()
    except FileNotFoundError:
        return None, ""
    return data, version_of(data)


async def write_fig(root, rel, data, *, base=None, by="user", reason="save", intent=None, force=False, who=None):
    """Write `data` to design `rel` → its new version. Raises Stale when `base` is no longer
    current, unless `force` ("keep mine"); no `base`: last write wins. `who` ({id, name?}) is the
    person writing, kept on the version it replaces."""
    root = Path(root)
    async with _lock(root / rel):
        return await asyncio.to_thread(_write, root, rel, bytes(data), base, by, reason, intent, force, who)


def _write(root, rel, data, base, by, reason, intent, force, who=None):
    path = root / rel
    current, now = read_fig(root, rel)
    if base is not None and not force and base != now:
        raise Stale(now)
    if current is not None and current != data:
        versions.snapshot(root, rel, current, by=by, reason=reason, intent=intent,
                          always=force or reason != "save", who=who)
    scratch = root / ".tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = scratch / f"{uuid.uuid4().hex}.part"
    tmp.write_bytes(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(path)
    return version_of(data)

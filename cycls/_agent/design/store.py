"""The one way a design file is written: compared, kept, then replaced.

Everything that writes a `.fig` — the editor's saves (`PUT /files`), the agent's
edits and slide actions, a restore — goes through `write_fig`, so none of them
overwrites a change it didn't see:

- A design's version is the first 16 hex of the sha256 of its bytes (the store's
  `_gen_of` precedent, cycls/_app/db.py). It is what `GET /files` serves as
  `X-Version`, and what a write names as its `base`: when the file has changed since,
  the write raises `Stale` instead of landing (412 on the route).
- What a write replaces is kept as a version first (cycls/_agent/versions.py).
- The write itself is a uuid temp file in `.tmp/`, then a rename.

A short per-file lock covers compare → keep → replace. It's not `deck.lock`, which
the agent holds across the whole service call (up to minutes): an editor save must
never wait behind that. The agent compares on its own write instead (a Stale re-reads
and applies once more).

Known limit: each instance's gcsfuse metadata cache is a window between instances no
file-level check closes; session affinity keeps a person on one instance.
"""
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


_locks = {}


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


async def write_fig(root, rel, data, *, base=None, by="user", reason="save", intent=None, force=False):
    """Write `data` to design `rel` → its new version. `base` — the version the writer
    started from — must still be current unless `force` (a "keep mine", which always
    keeps what it replaces). No `base`: last write wins, as before this check."""
    root = Path(root)
    async with _lock(root / rel):
        return await asyncio.to_thread(_write, root, rel, bytes(data), base, by, reason, intent, force)


def _write(root, rel, data, base, by, reason, intent, force):
    path = root / rel
    current, now = read_fig(root, rel)
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

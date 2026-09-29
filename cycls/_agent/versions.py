"""Earlier versions of a design, kept as it's overwritten (docs/notes/design.md).

A snapshot is the bytes a write is about to replace, kept at
`.versions/<path>/<id>`; `.versions/<path>/index.json` lists them —
[{id, at, by, reason, intent?, size}], oldest first — so showing the history is one
read. The editor's autosaves keep one at most every GAP seconds (an editing
session's starting point, then its progress); an agent edit, a restore and a "keep
mine" overwrite always keep one. The newest KEEP per file stay, none older than
TTL_DAYS. Ids are the trash's (`trash.new_id`).

`.versions` is managed by cycls: the files routes and the agent's tools refuse it,
and it is masked in the bash sandbox (as `.trash` is).
"""
import json
import re
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import trash

DIR = ".versions"
KEEP = 50
TTL_DAYS = 30
GAP = 300                     # seconds between two autosave snapshots of one file
_ID = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")
_last = {}                    # (root, rel) -> when its last autosave snapshot was kept


def _dir(root, rel):
    return Path(root) / DIR / rel


def _read_index(d):
    try:
        entries = json.loads((d / "index.json").read_text("utf-8"))
        return [e for e in entries if isinstance(e, dict) and _ID.match(str(e.get("id", "")))]
    except (OSError, ValueError):
        return []


def _write_index(d, entries):
    tmp = d / f".index.{uuid.uuid4().hex}.part"
    tmp.write_text(json.dumps(entries, ensure_ascii=False), "utf-8")
    tmp.replace(d / "index.json")


def _sweep(d, entries):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TTL_DAYS)).isoformat()
    keep = [e for e in entries if e.get("at", "") >= cutoff][-KEEP:]
    ids = {e["id"] for e in keep}
    for e in entries:
        if e["id"] not in ids:
            (d / e["id"]).unlink(missing_ok=True)
    return keep


def snapshot(root, rel, data, *, by, reason, intent=None, always=False):
    """Keep `data` — what's at `rel` before it's overwritten — as a version. An autosave
    (`always` False) keeps one at most every GAP seconds per file. → the id, or None."""
    key = (str(Path(root)), rel)
    now = time.time()
    if not always and now - _last.get(key, 0) < GAP:
        return None
    _last[key] = now
    d = _dir(root, rel)
    d.mkdir(parents=True, exist_ok=True)
    vid = trash.new_id()
    tmp = d / f".{vid}.part"
    tmp.write_bytes(data)
    tmp.replace(d / vid)
    entry = {"id": vid, "at": datetime.now(timezone.utc).isoformat(), "by": by, "reason": reason, "size": len(data)}
    if intent:
        entry["intent"] = str(intent)[:120]
    _write_index(d, _sweep(d, [*_read_index(d), entry]))
    return vid


def listing(root, rel):
    """The versions of `rel`, newest first."""
    return list(reversed(_read_index(_dir(root, rel))))


def read(root, rel, vid):
    """A version's bytes, or None."""
    if not _ID.match(str(vid)):
        return None
    try:
        return (_dir(root, rel) / vid).read_bytes()
    except OSError:
        return None


def move(root, src, dst):
    """A renamed file keeps its history."""
    s, d = _dir(root, src), _dir(root, dst)
    if s.is_dir() and not d.exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        s.replace(d)
        _last.pop((str(Path(root)), src), None)


def forget(root, rel):
    """Drop the history of a path that no longer holds a file (its trash entry went)."""
    if not (Path(root) / rel).exists():
        shutil.rmtree(_dir(root, rel), ignore_errors=True)
        _last.pop((str(Path(root)), rel), None)

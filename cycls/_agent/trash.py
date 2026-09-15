"""Workspace trash — a delete is a move. Bytes land in .trash/<id>/data/<original
path> with a meta.json beside them; restore moves them back; entries expire
TTL_DAYS after deletion on the next sweep (any listing or new deletion — lazy,
so an idle workspace costs nothing). The files route, the edit tool's
overwrite snapshot, and the sandbox `rm` shim (stdlib-only: /app is masked in
there) all write this one layout.
"""
import json, shutil, time, uuid
from datetime import datetime, timezone
from pathlib import Path

DIR = ".trash"
TTL_DAYS = 30


def _root(ws):
    return Path(ws).resolve() / DIR


def _now():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"


def kind_of(rel, is_dir):
    parts = rel.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "apps" and is_dir:
        return "app"
    return "dir" if is_dir else "file"


def trash_path(ws, rel, by="user", reason="delete"):
    """Move *rel* into the trash; returns its meta row."""
    ws = Path(ws).resolve()
    rel = rel.strip("/")
    src = (ws / rel).resolve()
    if not rel or not src.is_relative_to(ws) or src == ws or src.is_relative_to(ws / DIR):
        raise ValueError("not a trashable path")
    if not src.exists():
        raise FileNotFoundError(rel)
    tid = new_id()
    is_dir = src.is_dir()
    entry = _root(ws) / tid
    dest = entry / "data" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    meta = {"id": tid, "path": rel, "kind": kind_of(rel, is_dir), "by": by,
            "reason": reason, "deleted_at": _now()}
    (entry / "meta.json").write_text(json.dumps(meta))
    sweep(ws)
    return meta


def _read(entry):
    try:
        return json.loads((entry / "meta.json").read_text())
    except Exception:
        return None


def list_trash(ws):
    """Every entry, newest first; sweeps expired ones on the way."""
    sweep(ws)
    root = _root(ws)
    if not root.is_dir():
        return []
    rows = [m for e in root.iterdir() if e.is_dir() and (m := _read(e))]
    rows.sort(key=lambda m: m["deleted_at"], reverse=True)
    return rows


def restore(ws, tid):
    """Move the entry back; a path taken since gets `name (restored).ext`."""
    ws = Path(ws).resolve()
    entry = _root(ws) / tid
    meta = _read(entry) if entry.is_dir() else None
    if not meta:
        raise FileNotFoundError(tid)
    src = entry / "data" / meta["path"]
    dest = ws / meta["path"]
    if dest.exists():
        stem, suffix = dest.stem if dest.suffix else dest.name, dest.suffix if not src.is_dir() else ""
        n = 1
        while True:
            tag = " (restored)" if n == 1 else f" (restored {n})"
            candidate = dest.with_name(f"{stem}{tag}{suffix}")
            if not candidate.exists():
                dest = candidate
                break
            n += 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    shutil.rmtree(entry, ignore_errors=True)
    return str(dest.relative_to(ws))


def purge(ws, tid):
    entry = _root(ws) / tid
    if not entry.is_dir():
        raise FileNotFoundError(tid)
    shutil.rmtree(entry, ignore_errors=True)


def empty(ws):
    root = _root(ws)
    if root.is_dir():
        for e in root.iterdir():
            if e.is_dir():
                shutil.rmtree(e, ignore_errors=True)


def sweep(ws, now=None):
    """Drop entries older than TTL_DAYS. Returns how many went."""
    root = _root(ws)
    if not root.is_dir():
        return 0
    now = now or datetime.now(timezone.utc)
    gone = 0
    for e in root.iterdir():
        if not e.is_dir():
            continue
        m = _read(e)
        try:
            at = datetime.fromisoformat(m["deleted_at"]) if m else None
        except Exception:
            at = None
        if at is None or (now - at).days >= TTL_DAYS:
            shutil.rmtree(e, ignore_errors=True)
            gone += 1
    return gone

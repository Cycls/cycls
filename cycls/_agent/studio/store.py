"""The scene on disk: apps/studio/data/scene.json plus its mesh sidecars.

Every write goes through `edit()`, which holds a per-file lock, bumps `rev`,
stamps `by`, and keeps the scene it replaced under data/history/ (the last 20),
so an agent change can be reverted and two writers in this process can't
interleave. The app writes the same file over the bridge; it re-reads `rev`
before saving and merges (docs/notes/studio.md, Sync).
"""
import asyncio
import contextlib
import json
import pathlib
import re
from datetime import datetime, timezone

from . import APP_DIR, SCENE
from . import scene as S

HISTORY_KEEP = 20
MAX_BLOBS = 24_000_000
MESH_TTL = 24 * 3600        # an unreferenced mesh file younger than this may still be an open app's
_MESH = re.compile(r"^meshes/m-[0-9a-f]{12}\.json$")
_locks = {}


def _root(ws):
    return pathlib.Path(ws.root)


def lock(ws):
    key = str(_root(ws).resolve() / SCENE)
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _read(ws):
    path = _root(ws) / SCENE
    if not path.exists():
        return S.new_scene()
    try:
        return S.normalize(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, json.JSONDecodeError) as e:
        raise S.SceneError(f"{SCENE} is not a valid scene ({e}) — revert it from data/history/") from None


async def load(ws):
    return await asyncio.to_thread(_read, ws)


def _write(ws, doc, previous, by):
    root = _root(ws)
    path = root / SCENE
    path.parent.mkdir(parents=True, exist_ok=True)
    if previous is not None and path.exists():
        hist = root / APP_DIR / "data" / "history"
        hist.mkdir(parents=True, exist_ok=True)
        (hist / f"{previous['rev']}.json").write_text(json.dumps(previous), encoding="utf-8")
        old = sorted(hist.glob("*.json"), key=lambda p: int(p.stem) if p.stem.isdigit() else -1)
        for p in old[:-HISTORY_KEEP]:
            with contextlib.suppress(OSError):
                p.unlink()
    doc = dict(doc)
    doc["rev"] = max(doc.get("rev", 0), previous["rev"] if previous else 0) + 1
    doc["by"] = by
    doc["saved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    with contextlib.suppress(Exception):
        _sweep_meshes(root, doc)
    return doc


def _sweep_meshes(root, doc):
    """Mesh files are immutable, so every edit in the app's Edit mode leaves the last
    one behind. Delete those no scene here uses — the current one or any in history —
    once they're a day old: younger ones may be an open app's, written ahead of its
    scene or held by its undo."""
    import time
    data = root / APP_DIR / "data"
    used = {m.get("data") for m in doc.get("meshes", {}).values()}
    for h in (data / "history").glob("*.json"):
        with contextlib.suppress(Exception):
            used |= {m.get("data") for m in json.loads(h.read_text(encoding="utf-8")).get("meshes", {}).values()}
    cutoff = time.time() - MESH_TTL
    for p in (data / "meshes").glob("m-*.json"):
        if f"meshes/{p.name}" not in used and p.stat().st_mtime < cutoff:
            with contextlib.suppress(OSError):
                p.unlink()


async def save(ws, doc, previous, by="agent"):
    return await asyncio.to_thread(_write, ws, S.normalize(doc), previous, by)


def history(ws, rev):
    path = _root(ws) / APP_DIR / "data" / "history" / f"{int(rev)}.json"
    if not path.exists():
        raise S.SceneError(f"no saved scene at rev {rev} (the last {HISTORY_KEEP} agent edits are kept)")
    return S.normalize(json.loads(path.read_text(encoding="utf-8")))


def mesh_path(ws, rel):
    if not _MESH.match(rel):
        raise S.SceneError(f"{rel!r} is not a mesh file")
    return _root(ws) / APP_DIR / "data" / rel


def write_mesh(ws, mesh_id, text):
    path = mesh_path(ws, f"meshes/{mesh_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():                 # content-addressed: the same id is the same geometry
        path.write_text(text if isinstance(text, str) else text.decode(), encoding="utf-8")
    return f"meshes/{mesh_id}.json"


def log_render(ws, entry):
    """Append to data/renders.json (the app's render history), newest last, capped."""
    path = _root(ws) / APP_DIR / "data" / "renders.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
        items = items if isinstance(items, list) else []
    except Exception:
        items = []
    items.append({**entry, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items[-200:], indent=1), encoding="utf-8")


def blobs(ws, doc):
    """The explicit mesh files a scene references — what the engine needs with it."""
    out, total = {}, 0
    for m in doc["meshes"].values():
        rel = m.get("data")
        if not rel or rel in out:
            continue
        path = mesh_path(ws, rel)
        if not path.exists():
            raise S.SceneError(f"the scene references {rel}, which is missing from {APP_DIR}/data/")
        text = path.read_text(encoding="utf-8")
        total += len(text)
        if total > MAX_BLOBS:
            raise S.SceneError("the scene's meshes are over 24 MB together — decimate or remove some")
        out[rel] = text
    return out

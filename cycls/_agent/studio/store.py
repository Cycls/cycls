"""The scene on disk: apps/studio/data/scene.json plus its mesh and texture files.

Every write goes through `edit()`, which holds a per-file lock, bumps `rev`,
stamps `by`, and keeps the scene it replaced under data/history/ (the last 20),
so an agent change can be reverted and two writers in this process can't
interleave. The app writes the same file over the bridge; it re-reads `rev`
before saving and merges (docs/notes/studio.md, Sync).
"""
import asyncio
import base64
import contextlib
import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone

from . import APP_DIR, SCENE
from . import scene as S

HISTORY_KEEP = 20
MAX_BLOBS = 24_000_000
MESH_TTL = 24 * 3600        # an unreferenced mesh/texture file younger than this may still be an open app's
MAX_TEXTURE_BYTES = 8_000_000
_MESH = re.compile(r"^meshes/m-[0-9a-f]{12}\.json$")
_TEXTURE = re.compile(r"^textures/t-[0-9a-f]{12}\.json$")
MEDIA = {"image/png": "png", "image/jpeg": "jpg"}
# The ops that draw (or read materials back) get the images; geometry ops don't need them.
TEXTURE_OPS = {"snapshot", "render", "export", "script"}
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
        _sweep_files(root, doc)
    return doc


def _files_of(doc):
    return {e.get("data") for sec in ("meshes", "textures") for e in doc.get(sec, {}).values()}


def _sweep_files(root, doc):
    """Mesh and texture files are immutable, so every edit in the app's Edit mode (or a
    replaced image) leaves the last one behind. Delete those no scene here uses — the
    current one or any in history — once they're a day old: younger ones may be an open
    app's, written ahead of its scene or held by its undo."""
    import time
    data = root / APP_DIR / "data"
    used = _files_of(doc)
    for h in (data / "history").glob("*.json"):
        with contextlib.suppress(Exception):
            used |= _files_of(json.loads(h.read_text(encoding="utf-8")))
    cutoff = time.time() - MESH_TTL
    for folder, pattern in (("meshes", "m-*.json"), ("textures", "t-*.json")):
        for p in (data / folder).glob(pattern):
            if f"{folder}/{p.name}" not in used and p.stat().st_mtime < cutoff:
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


def texture_path(ws, rel):
    if not _TEXTURE.match(rel):
        raise S.SceneError(f"{rel!r} is not a texture file")
    return _root(ws) / APP_DIR / "data" / rel


def write_texture(ws, data, media_type):
    """An image (PNG/JPEG bytes) as a cycls.texture file, named by its content — the app
    reads it as text over the bridge. Returns its path under data/."""
    if media_type not in MEDIA:
        raise S.SceneError(f"textures are PNG or JPEG, not {media_type}")
    if len(data) > MAX_TEXTURE_BYTES:
        raise S.SceneError(f"that image is over {MAX_TEXTURE_BYTES // 1_000_000} MB")
    w, h = image_size(data)
    rel = f"textures/t-{hashlib.sha256(data).hexdigest()[:12]}.json"
    path = texture_path(ws, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps({"format": "cycls.texture", "version": 1, "media_type": media_type,
                                    "width": w, "height": h, "data": base64.b64encode(data).decode()}),
                        encoding="utf-8")
    return rel


def read_texture(ws, rel):
    """A texture file's image bytes and extension (png/jpg)."""
    path = texture_path(ws, rel)
    if not path.exists():
        raise S.SceneError(f"the scene references {rel}, which is missing from {APP_DIR}/data/")
    side = json.loads(path.read_text(encoding="utf-8"))
    if side.get("format") != "cycls.texture" or side.get("media_type") not in MEDIA:
        raise S.SceneError(f"{rel} is not a cycls.texture file")
    return base64.b64decode(side["data"]), MEDIA[side["media_type"]]


def image_size(data):
    """(width, height) from a PNG or JPEG header — no image library."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker, size = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + size
    raise S.SceneError("not a PNG or JPEG image")


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


def blobs(ws, doc, op=None):
    """What the engine needs with a scene: its explicit mesh files, and — for the ops that
    draw or read materials back — its images as PNG/JPEG bytes (textures/t-<hash>.<ext>)."""
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
        out[rel] = text
    if op in TEXTURE_OPS:
        for t in doc.get("textures", {}).values():
            data, ext = read_texture(ws, t["data"])
            total += len(data)
            out[t["data"][:-5] + "." + ext] = data
    if total > MAX_BLOBS:
        raise S.SceneError("the scene's meshes and images are over 24 MB together — decimate meshes or use "
                           "smaller images")
    return out

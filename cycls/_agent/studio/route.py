"""POST /apps/studio/engine — the Studio app's line to the Blender engine.

The app runs in a sandboxed frame with no network and no token, so it asks the
host (cycls.engine) and the host calls this route with the viewer's JWT. The
route decides what the app may do: only the installed Studio, only app ops,
mesh files only from its own data folder, within a budget. It saves what the
engine makes (renders, meshes, exports) before answering, so a reply lost to a
closed tab loses nothing.
"""
import asyncio
import base64
import json
import pathlib
import re
import time

from fastapi import APIRouter, HTTPException, Request

from . import APP_DIR, SLUG, engine, store
from . import scene as S
from .tool import EXPORT_EXTS, _free, _slug

MAX_BODY = 16_000_000                 # the scene document rides along (~2 MB at 5,000 objects)
CALLS_PER_MINUTE = 60
RENDERS_PER_HOUR = 30
_calls, _renders, _rendering = {}, {}, set()


def _budget(subject, op):
    """Under the caps? In memory, per instance — it bounds a runaway, not a determined caller."""
    now = time.time()
    minute = [t for t in _calls.get(subject, []) if now - t < 60]
    if len(minute) >= CALLS_PER_MINUTE:
        return "too many Studio engine calls — wait a minute"
    minute.append(now)
    _calls[subject] = minute
    if op == "render":
        if subject in _rendering:
            return "a render is already running — wait for it"
        hour = [t for t in _renders.get(subject, []) if now - t < 3600]
        if len(hour) >= RENDERS_PER_HOUR:
            return f"that's {RENDERS_PER_HOUR} renders this hour — try again later"
        hour.append(now)
        _renders[subject] = hour
    if len(_calls) > 10_000:
        _calls.clear()
    return None


def _stamped(ws):
    try:
        return bool(json.loads((pathlib.Path(ws.root) / APP_DIR / "app.json").read_text(encoding="utf-8")).get("studio"))
    except Exception:
        return False


def _data_url(jpg):
    return "data:image/jpeg;base64," + base64.b64encode(jpg).decode()


async def _answer(ws, op, r, body, doc):
    res, files = r["result"], r["files"]
    if op == "evaluate":
        b64 = lambda k: base64.b64encode(files[k]).decode()      # noqa: E731
        return {"ok": True, "tris": res.get("tris", 0), "meshes": {
            oid: {"positions": b64(m["positions"]), "normals": b64(m["normals"]), "index": b64(m["index"]),
                  **({"uv": b64(m["uv"])} if m.get("uv") else {}),
                  **({"material_index": b64(m["material_index"])} if m.get("material_index") else {}),
                  "loops": m["loops"], "tris": m["tris"]}
            for oid, m in res.get("meshes", {}).items()}}
    if op == "snapshot":
        return {"ok": True, "preview": _data_url(files["preview.jpg"]), "resolution": res.get("resolution")}
    if op == "render":
        rel = _free(ws.root, "renders", _slug(body.get("name"), "studio"), "png")
        await asyncio.to_thread((pathlib.Path(ws.root) / rel).write_bytes, files["render.png"])
        await asyncio.to_thread(store.log_render, ws, {"path": rel, "rev": doc["rev"], "resolution": res["resolution"],
                                                       "samples": res["samples"], "seconds": res["render_seconds"],
                                                       "by": "app"})
        return {"ok": True, "path": rel, "preview": _data_url(files["preview.jpg"]),
                "resolution": res["resolution"], "samples": res["samples"], "seconds": res["render_seconds"]}
    if op == "apply":
        rel = await asyncio.to_thread(store.write_mesh, ws, res["mesh_id"], files["mesh.json"])
        return {"ok": True, "mesh_id": res["mesh_id"], "data": rel, "verts": res["verts"], "faces": res["faces"],
                "bbox": res["bbox"], "modifiers": res.get("modifiers"), "removed": res.get("removed", []),
                "selection": res.get("selection"), "materials": res.get("materials")}
    if op == "export":
        fmt = res["format"]
        rel = _free(ws.root, "exports", _slug(body.get("name"), "scene"), EXPORT_EXTS[fmt])
        await asyncio.to_thread((pathlib.Path(ws.root) / rel).write_bytes, files[res["file"]])
        return {"ok": True, "path": rel}
    raise AssertionError(op)


async def _open(ws, body):
    """Ask the host to open a render or export on the canvas — one the Studio made (in its
    render log, or under exports/). No engine call; the bridge does the opening."""
    path = (body.get("params") or {}).get("path")
    ok = isinstance(path, str) and re.match(r"^(renders|exports)/[^/\\]+$", path or "") is not None
    if ok and path.startswith("renders/"):
        ok = path in await asyncio.to_thread(store.render_paths, ws)
    if not ok or not (pathlib.Path(ws.root) / path).is_file():
        raise HTTPException(404, "no such render")
    return {"ok": True, "open": path}


def studio_router(ws_dep, user_dep):
    r = APIRouter()

    @r.post("/apps/{slug}/engine")
    async def engine_op(slug: str, request: Request, ws=ws_dep, user=user_dep):
        if slug != SLUG or not await asyncio.to_thread(_stamped, ws):
            raise HTTPException(404, "Not found")
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "request too large")
        try:
            body = json.loads(raw)
            assert isinstance(body, dict)
        except Exception:
            raise HTTPException(400, "body must be a JSON object")
        op = body.get("op")
        if op == "open":
            return await _open(ws, body)
        if op not in engine.APP_OPS:
            raise HTTPException(400, f"op: one of {', '.join(sorted(engine.APP_OPS))}")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            raise HTTPException(400, "params must be an object")
        try:
            doc = S.normalize(body["scene"]) if body.get("scene") is not None else await store.load(ws)
            blobs = await asyncio.to_thread(store.blobs, ws, doc, op)
        except S.SceneError as e:
            raise HTTPException(400, str(e))
        refusal = _budget(ws.subject, op)
        if refusal:
            raise HTTPException(429, refusal)
        if op == "render":
            _rendering.add(ws.subject)
        try:
            result = await engine.call(op, doc, blobs=blobs, params=params)
        except engine.EngineError as e:
            return {"ok": False, "error": str(e)}
        finally:
            if op == "render":
                _rendering.discard(ws.subject)
        return await _answer(ws, op, result, body, doc)

    return r

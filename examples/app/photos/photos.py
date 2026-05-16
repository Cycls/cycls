# uv run cycls run examples/app/photos/photos.py
"""Photo timeline — per-user gallery, metadata in DB, bytes on the workspace fs.

Metadata at `photos/{id}` (JSON, in the workspace DB). Image bytes at
`<ws.root>/photos/{id}` (filesystem, gcsfuse-backed in prod). Two storage
shapes in one workspace — no S3, no signed URLs, no separate blob store.
"""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cycls

HTML_PATH = str(Path(__file__).parent / "photos.html")
MAX_BYTES = 10 * 1024 * 1024


@cycls.app(image=cycls.Image().copy(HTML_PATH, "photos.html"), auth=cycls.Clerk())
def photos():
    from fastapi import FastAPI, File, HTTPException, Response, UploadFile
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="Photos")

    @app.get("/")
    async def index():
        pk = photos._auth_provider.resolve(photos.prod).get("pk", "")
        html = Path("photos.html").read_text().replace("__CLERK_PK__", pk)
        return HTMLResponse(html)

    @app.get("/me")
    async def me(user=photos.auth):
        return user

    def _img_path(ws, pid):
        d = ws.root / "photos"
        d.mkdir(parents=True, exist_ok=True)
        return d / pid

    @app.post("/photos")
    async def upload(files: list[UploadFile] = File(...), ws=photos.workspace):
        db = cycls.DB(ws)
        results = []
        for f in files:
            data = await f.read()
            if len(data) > MAX_BYTES:
                raise HTTPException(413, f"{f.filename}: exceeds {MAX_BYTES // 1024 // 1024}MB")
            pid = uuid4().hex[:16]
            meta = {
                "id": pid,
                "filename": f.filename or "untitled",
                "mime": f.content_type or "application/octet-stream",
                "size": len(data),
                "uploadedAt": datetime.now(timezone.utc).isoformat(),
            }
            await db.put(f"photos/{pid}", meta)
            _img_path(ws, pid).write_bytes(data)
            results.append(meta)
        return results

    @app.get("/photos")
    async def list_photos(ws=photos.workspace):
        items = [m async for _, m in cycls.DB(ws).items(prefix="photos/")]
        items.sort(key=lambda m: m.get("uploadedAt", ""), reverse=True)
        return items

    @app.get("/photos/{pid}/raw")
    async def get_raw(pid: str, ws=photos.workspace):
        meta = await cycls.DB(ws).get(f"photos/{pid}")
        if not meta:
            raise HTTPException(404, "not found")
        path = _img_path(ws, pid)
        if not path.exists():
            raise HTTPException(404, "not found")
        return Response(content=path.read_bytes(), media_type=meta.get("mime", "application/octet-stream"))

    @app.delete("/photos/{pid}")
    async def delete_photo(pid: str, ws=photos.workspace):
        db = cycls.DB(ws)
        if not await db.get(f"photos/{pid}"):
            raise HTTPException(404, "not found")
        await db.delete(f"photos/{pid}")
        _img_path(ws, pid).unlink(missing_ok=True)
        return {"ok": True}

    return app

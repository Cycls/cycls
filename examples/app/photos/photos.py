# uv run cycls run examples/app/photos/photos.py
"""Photo timeline — per-user gallery using JSON + raw bytes in one DB.

Metadata at `photos/{id}` (JSON). Image bytes at `b"img/{id}"` via
db.raw(). Same workspace, two storage shapes — no S3, no signed URLs,
no separate blob store.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cycls

HTML_PATH = str(Path(__file__).parent / "photos.html")
MAX_BYTES = 10 * 1024 * 1024


@cycls.app(image=cycls.Image().copy(HTML_PATH, "photos.html"), auth=cycls.Clerk("cycls.ai"))
def photos():
    from fastapi import FastAPI, File, HTTPException, Response, UploadFile
    from fastapi.responses import HTMLResponse
    from slatedb.uniffi import PutOptions, Ttl, WriteOptions

    app = FastAPI(title="Photos")

    @app.get("/")
    async def index():
        pk = photos._auth_provider.resolve(photos.prod).get("pk", "")
        html = Path("photos.html").read_text().replace("__CLERK_PK__", pk)
        return HTMLResponse(html)

    @app.get("/me")
    async def me(user=photos.auth):
        return user

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
            async with db.raw() as raw:
                await raw.put_with_options(
                    f"img/{pid}".encode(), data,
                    PutOptions(ttl=Ttl.DEFAULT()),
                    WriteOptions(await_durable=False),
                )
            results.append(meta)
        return results

    @app.get("/photos")
    async def list_photos(ws=photos.workspace):
        items = [m async for _, m in cycls.DB(ws).items(prefix="photos/")]
        items.sort(key=lambda m: m.get("uploadedAt", ""), reverse=True)
        return items

    @app.get("/photos/{pid}/raw")
    async def get_raw(pid: str, ws=photos.workspace):
        db = cycls.DB(ws)
        meta = await db.get(f"photos/{pid}")
        if not meta:
            raise HTTPException(404, "not found")
        async with db.raw() as raw:
            data = await raw.get(f"img/{pid}".encode())
        if data is None:
            raise HTTPException(404, "not found")
        return Response(content=bytes(data), media_type=meta.get("mime", "application/octet-stream"))

    @app.delete("/photos/{pid}")
    async def delete_photo(pid: str, ws=photos.workspace):
        db = cycls.DB(ws)
        async with db.transaction() as t:
            if not await t.get(f"photos/{pid}"):
                raise HTTPException(404, "not found")
            await t.delete(f"photos/{pid}")
        async with db.raw() as raw:
            await raw.delete_with_options(
                f"img/{pid}".encode(),
                WriteOptions(await_durable=False),
            )
        return {"ok": True}

    return app
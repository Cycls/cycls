"""HTTP routers for the agent's state surface — chats, files, share.

Chat metadata + message log live in one KV (`KV("chat", workspace)`) — see
`cycls.agent.chat`. Files and share dirs stay on the workspace filesystem
(they're POSIX-shaped). Path safety guards live here too.
"""
import os, shutil, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from cycls.app.db import Workspace
from cycls.agent import chat, share


# ---- Path safety ----

def resolve_path(workspace, rel):
    """Resolve *rel* inside *workspace*, raising ValueError on traversal or
    access to the reserved `.cycls/` tree (framework-managed)."""
    workspace = Path(workspace)
    rel = unicodedata.normalize("NFC", rel)
    resolved = (workspace / rel).resolve()
    ws = workspace.resolve()
    if not resolved.is_relative_to(ws):
        raise ValueError("Path traversal denied")
    reserved = ws / ".cycls"
    if resolved == reserved or resolved.is_relative_to(reserved):
        raise ValueError("Reserved path: .cycls/ is managed by cycls")
    return resolved


def _ws(user, volume):
    """Build a Workspace from a User + volume, mirroring Context.workspace."""
    if user.org_id:
        return Workspace(volume / user.org_id, user_id=user.id)
    return Workspace(volume / user.id)


# ---- Chats ----

def chats_router(required_auth, volume):
    r = APIRouter()

    @r.get("/chats")
    async def list_chats(user: Any = required_auth):
        ws = _ws(user, volume)
        items = []
        async for cid, data in chat.list_chats(ws):
            items.append({
                "id": data.get("id", cid),
                "title": data.get("title", ""),
                "updatedAt": data.get("updatedAt", ""),
            })
        items.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
        return items

    @r.get("/chats/{chat_id}")
    async def get_chat(chat_id: str, user: Any = required_auth):
        ws = _ws(user, volume)
        meta = await chat.get_meta(ws, chat_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        messages = await chat.load_messages(ws, chat_id)
        return {**meta, "messages": messages}

    @r.put("/chats/{chat_id}")
    async def put_chat(chat_id: str, request: Request, user: Any = required_auth):
        ws = _ws(user, volume)
        data = await request.json()
        data["id"] = chat_id
        data["updatedAt"] = datetime.now(timezone.utc).isoformat()
        existing = (await chat.get_meta(ws, chat_id)) or {}
        if "createdAt" not in data:
            data["createdAt"] = existing.get("createdAt", data["updatedAt"])
        # Drop "messages" if FE accidentally sends it — that's not metadata.
        data.pop("messages", None)
        await chat.put_meta(ws, chat_id, data)
        return data

    @r.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str, user: Any = required_auth):
        ws = _ws(user, volume)
        if (await chat.get_meta(ws, chat_id)) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        await chat.delete_chat(ws, chat_id)
        return {"ok": True}

    return r


# ---- Files ----

def files_router(required_auth, volume):
    r = APIRouter()

    def _safe_path(workspace, rel):
        try:
            return resolve_path(workspace, rel)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path traversal denied")

    @r.get("/files")
    async def list_files(request: Request, user: Any = required_auth):
        target = _safe_path(_ws(user, volume).root, request.query_params.get("path", ""))
        if not target.is_dir():
            return []
        items = []
        for entry in os.scandir(target):
            if entry.name.startswith("."):
                continue
            stat = entry.stat()
            items.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        items.sort(key=lambda f: f["name"])
        return items

    @r.get("/files/{path:path}")
    async def get_file(path: str, request: Request, user: Any = required_auth):
        file_path = _safe_path(_ws(user, volume).root, path)
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if request.query_params.get("download") is not None:
            return FileResponse(file_path, filename=file_path.name)
        return FileResponse(file_path)

    @r.put("/files/{path:path}")
    async def put_file(path: str, request: Request, file: UploadFile = File(...), user: Any = required_auth):
        file_path = _safe_path(_ws(user, volume).root, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(await file.read())
        return {"ok": True}

    @r.patch("/files/{path:path}")
    async def rename(path: str, request: Request, user: Any = required_auth):
        src = _safe_path(_ws(user, volume).root, path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Not found")
        data = await request.json()
        dest = _safe_path(_ws(user, volume).root, data["to"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        return {"ok": True}

    @r.post("/files/{path:path}")
    async def mkdir(path: str, user: Any = required_auth):
        dir_path = _safe_path(_ws(user, volume).root, path)
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"ok": True}

    @r.delete("/files/{path:path}")
    async def delete_path(path: str, user: Any = required_auth):
        target = _safe_path(_ws(user, volume).root, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Not found")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True}

    return r


# ---- Share ----

def share_router(required_auth, volume):
    r = APIRouter()

    @r.post("/share")
    async def create_share(request: Request, user: Any = required_auth):
        data = await request.json()
        messages = data.get("messages")
        if not messages:
            raise HTTPException(status_code=400, detail="messages required")
        share_id, _ = await share.create_share(
            _ws(user, volume),
            volume,
            messages=messages,
            title=data.get("title", ""),
            author=data.get("author"),
        )
        return {"id": share_id, "path": share_id}

    @r.get("/share")
    async def list_shares(user: Any = required_auth):
        items = []
        async for sid, meta in share.list_shares(_ws(user, volume)):
            items.append({
                "id": meta.get("id", sid),
                "title": meta.get("title", ""),
                "sharedAt": meta.get("sharedAt", ""),
                "path": meta.get("id", sid),
            })
        items.sort(key=lambda s: s.get("sharedAt", ""), reverse=True)
        return items

    @r.get("/share/{share_id}")
    async def get_share(share_id: str):
        snap = share.read_snapshot(volume, share_id)
        if snap is None:
            raise HTTPException(status_code=404, detail="Not found")
        return snap

    @r.get("/shared-assets/{share_id}/{filename}")
    async def get_shared_asset(share_id: str, filename: str):
        p = share.asset_path(volume, share_id, filename)
        if p is None:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(p)

    @r.delete("/share/{share_id}")
    async def delete_share(share_id: str, user: Any = required_auth):
        ws = _ws(user, volume)
        if not await share.is_owner(ws, share_id):
            raise HTTPException(status_code=404, detail="Not found")
        await share.delete_share(ws, volume, share_id)
        return {"ok": True}

    return r


# ---- Mount ----

def install_routers(app, required_auth, volume):
    """Mount chats, files, and share routers on a FastAPI app."""
    app.include_router(chats_router(required_auth, volume))
    app.include_router(files_router(required_auth, volume))
    app.include_router(share_router(required_auth, volume))

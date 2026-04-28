"""HTTP routers for the agent's state surface — chats, files, share.

Chat metadata + message log live in one KV (`KV("chat", workspace)`) — see
`cycls.agent.chat`. Files stay on the workspace filesystem (they're POSIX-
shaped). Public shares are stateless HMAC-signed URLs (`/shared?path=&user=
&exp=&sig=`) — the signature *is* the proof of access; no server-side share
record is consulted on read.
"""
import os, shutil, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from cycls.app.db import DB, Workspace, workspace_for
from cycls.agent import chat


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


# ---- Chats ----

def chats_router(ws_dep):
    r = APIRouter()

    @r.get("/chats")
    async def list_chats(ws: Workspace = ws_dep):
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
    async def get_chat(chat_id: str, ws: Workspace = ws_dep):
        meta = await chat.get_meta(ws, chat_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        raw = await chat.load_messages(ws, chat_id)
        return {**meta, "messages": chat.to_ui_messages(raw)}

    @r.put("/chats/{chat_id}")
    async def put_chat(chat_id: str, request: Request, ws: Workspace = ws_dep):
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
    async def delete_chat(chat_id: str, ws: Workspace = ws_dep):
        if (await chat.get_meta(ws, chat_id)) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        await chat.delete_chat(ws, chat_id)
        return {"ok": True}

    return r


# ---- Files ----

def files_router(cycls_app, ws_dep, user_dep):
    r = APIRouter()

    @r.post("/files/sign")
    async def sign_file(request: Request, user: Any = user_dep):
        """Mint a short-lived signed URL for a file in the caller's workspace.
        Used when the FE needs a URL the browser can fetch natively (img src,
        anchor href, window.open) — those don't accept Authorization headers."""
        data = await request.json()
        path = data.get("path")
        if not path:
            raise HTTPException(status_code=400, detail="path required")
        ttl = int(data.get("ttl") or 3600)
        return {"url": cycls_app.signed_url(f"file/{path}", user, ttl=ttl)}

    def _safe_path(workspace, rel):
        try:
            return resolve_path(workspace, rel)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path traversal denied")

    @r.get("/files")
    async def list_files(request: Request, ws: Workspace = ws_dep):
        target = _safe_path(ws.root, request.query_params.get("path", ""))
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
    async def get_file(path: str, request: Request, ws: Workspace = ws_dep):
        file_path = _safe_path(ws.root, path)
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if request.query_params.get("download") is not None:
            return FileResponse(file_path, filename=file_path.name)
        return FileResponse(file_path)

    @r.put("/files/{path:path}")
    async def put_file(path: str, request: Request, file: UploadFile = File(...), ws: Workspace = ws_dep):
        file_path = _safe_path(ws.root, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(await file.read())
        return {"ok": True}

    @r.patch("/files/{path:path}")
    async def rename(path: str, request: Request, ws: Workspace = ws_dep):
        src = _safe_path(ws.root, path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Not found")
        data = await request.json()
        dest = _safe_path(ws.root, data["to"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        return {"ok": True}

    @r.post("/files/{path:path}")
    async def mkdir(path: str, ws: Workspace = ws_dep):
        dir_path = _safe_path(ws.root, path)
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"ok": True}

    @r.delete("/files/{path:path}")
    async def delete_path(path: str, ws: Workspace = ws_dep):
        target = _safe_path(ws.root, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Not found")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True}

    return r


# ---- Share ----

def share_router(cycls_app, ws_dep, user_dep, volume, bucket):
    """Live shares — `POST /share` mints a signed URL bound to (chat_id, owner,
    exp); `/shared/data` and `/shared/file/...` resolve that URL with no auth
    lookup, only HMAC verification. Owner-side `/share` index is kept for the
    "your shared chats" UI but is not consulted on read."""
    r = APIRouter()

    SHARE_TTL = 7 * 24 * 3600

    @r.post("/share")
    async def create_share(request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        data = await request.json()
        chat_id = data.get("chat_id") or data.get("id")
        if not chat_id:
            raise HTTPException(status_code=400, detail="chat_id required")
        if (await chat.get_meta(ws, chat_id)) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        url = cycls_app.signed_url(f"chat/{chat_id}", user, ttl=SHARE_TTL)
        meta = {
            "id": chat_id,
            "title": data.get("title", ""),
            "author": data.get("author"),
            "sharedAt": datetime.now(timezone.utc).isoformat(),
            "url": url,
        }
        await DB(ws).kv("share").put(chat_id, meta)
        return meta

    @r.get("/share")
    async def list_shares(ws: Workspace = ws_dep):
        items = []
        async for _, meta in DB(ws).kv("share").items():
            items.append(meta)
        items.sort(key=lambda s: s.get("sharedAt", ""), reverse=True)
        return items

    @r.delete("/share/{chat_id}")
    async def delete_share(chat_id: str, ws: Workspace = ws_dep):
        """Drop the chat from the owner's share index. Existing signed URLs
        keep working until their `exp` — for instant revocation, delete the
        signing key from the bucket and redeploy (rotates all live shares)."""
        await DB(ws).kv("share").delete(chat_id)
        return {"ok": True}

    @r.get("/shared/data")
    async def shared_data(path: str, user: str, exp: int, sig: str):
        if not cycls_app.verify_signed(path, user, exp, sig):
            raise HTTPException(status_code=403, detail="Invalid or expired link")
        if not path.startswith("chat/"):
            raise HTTPException(status_code=400, detail="Unsupported share path")
        chat_id = path[len("chat/"):]
        ws = Workspace(volume, user, bucket=bucket)
        meta = await chat.get_meta(ws, chat_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        share_meta = await DB(ws).kv("share").get(chat_id) or {}
        raw = await chat.load_messages(ws, chat_id)
        messages = chat.to_ui_messages(raw)
        # Mint per-attachment signed URLs with the same expiry, so the public
        # viewer can load them without re-deriving signatures client-side.
        remaining = max(60, int(exp) - int(time.time()))
        for m in messages:
            for att in m.get("attachments") or []:
                ap = att.get("path")
                if ap:
                    att["url"] = cycls_app.signed_url(f"file/{ap}", user, ttl=remaining)
        return {
            "id": chat_id,
            "title": share_meta.get("title") or meta.get("title", ""),
            "author": share_meta.get("author"),
            "sharedAt": share_meta.get("sharedAt"),
            "messages": messages,
        }

    @r.get("/shared/file/{file_path:path}")
    async def shared_file(file_path: str, user: str, exp: int, sig: str):
        if not cycls_app.verify_signed(f"file/{file_path}", user, exp, sig):
            raise HTTPException(status_code=403, detail="Invalid or expired link")
        ws = Workspace(volume, user, bucket=bucket)
        try:
            target = resolve_path(ws.root, file_path)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path traversal denied")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(target)

    return r


# ---- Mount ----

def install_routers(cycls_app, app, required_auth, volume, bucket):
    """Mount chats, files, and share routers on a FastAPI app. The workspace
    is built once per request via FastAPI's Depends — endpoints don't see
    volume/bucket directly."""
    def _build_ws(user: Any = required_auth):
        return workspace_for(user, volume, bucket)
    ws_dep = Depends(_build_ws)
    app.include_router(chats_router(ws_dep))
    app.include_router(files_router(cycls_app, ws_dep, required_auth))
    app.include_router(share_router(cycls_app, ws_dep, required_auth, volume, bucket))

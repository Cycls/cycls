"""HTTP routers for the agent's state surface — chats, files, share.

Chat metadata + message log live in one KV (`KV("chat", workspace)`) — see
`cycls.agent.chat`. Files stay on the workspace filesystem (POSIX-shaped).
Shares are opaque tokens stored in the owner's workspace at `share/<token>`,
audience-checked at resolve time. See docs/rfc-003.md.
"""
import os, shutil, time, unicodedata, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, Request, Response, HTTPException, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse

from cycls.app.workspace import DB, Workspace, workspace_at, workspace_for
from cycls.agent import share as shares
from cycls.app.auth import User
from cycls.agent import chat


# ---- Path safety ----

def resolve_path(workspace, rel):
    """Resolve *rel* inside *workspace*, raising ValueError on traversal or
    access to the reserved `.db/` tree (framework-managed)."""
    workspace = Path(workspace)
    rel = unicodedata.normalize("NFC", rel)
    resolved = (workspace / rel).resolve()
    ws = workspace.resolve()
    if not resolved.is_relative_to(ws):
        raise ValueError("Path traversal denied")
    reserved = ws / ".db"
    if resolved == reserved or resolved.is_relative_to(reserved):
        raise ValueError("Reserved path: .db/ is managed by cycls")
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
        # 204 (not 404) for a missing chat: the FE auto-restores `?id=` on
        # cold load, and a stale id is normal — 404s clutter the dev console.
        if meta is None:
            return Response(status_code=204)
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

def share_router(cycls_app, ws_dep, user_dep, volume, base):
    r = APIRouter()
    bearer_scheme = HTTPBearer(auto_error=False)

    async def _resolve_or_403(user: str, token: str, bearer):
        from cycls.app.auth import authenticate
        ws_owner = workspace_at(user, volume, base=base)
        requester = None
        if bearer and cycls_app._auth_provider is not None:
            try: requester = authenticate(cycls_app._auth_provider, cycls_app.prod, bearer.credentials)
            except Exception: pass
        row = await shares.resolve(ws_owner, token, requester=requester)
        if row is None:
            raise HTTPException(403, "Invalid, expired, or unauthorized link")
        return ws_owner, row

    # ---- Owner side ----

    @r.post("/share")
    async def create_share(request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        data = await request.json()
        path = data.get("path")
        if not (path and (path.startswith("chat/") or path.startswith("file/"))):
            raise HTTPException(400, "path must be 'chat/<id>' or 'file/<path>'")
        if path.startswith("chat/") and (await chat.get_meta(ws, path[5:])) is None:
            raise HTTPException(404, "Chat not found")
        token, row = await shares.mint(ws, path,
                                       audience=data.get("audience", "public"),
                                       ttl=int(data.get("ttl") or shares.DEFAULT_TTL),
                                       author=data.get("author"))
        return {"token": token, "url": f"/shared/{ws.subject}/{token}", **row}

    @r.get("/share")
    async def list_shares(ws: Workspace = ws_dep):
        out = []
        async for key, row in DB(ws).items(prefix="share/"):
            token = key[6:]
            path = row["path"]
            if path.startswith("chat/"):
                meta = await chat.get_meta(ws, path[5:])
                title = (meta or {}).get("title") or ""
            else:
                title = path[5:]  # file path as the display name
            out.append({"token": token, "url": f"/shared/{ws.subject}/{token}", "title": title, **row})
        out.sort(key=lambda s: s["exp"], reverse=True)
        return out

    @r.delete("/share/{token}")
    async def revoke_share(token: str, ws: Workspace = ws_dep):
        await shares.revoke(ws, token)
        return {"ok": True}

    # ---- Viewer side ----

    @r.get("/share/{user}/{token}/data")
    async def resolve_share(
        user: str, token: str,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        ws_owner, row = await _resolve_or_403(user, token, bearer)
        path = row["path"]
        common = {"author": row.get("author"), "shared_at": row.get("shared_at")}
        if path.startswith("chat/"):
            chat_id = path[5:]
            meta = await chat.get_meta(ws_owner, chat_id)
            if meta is None:
                raise HTTPException(404, "Chat not found")
            messages = chat.to_ui_messages(await chat.load_messages(ws_owner, chat_id))
            for m in messages:
                for att in m.get("attachments") or []:
                    if ap := att.get("path"):
                        att["url"] = f"/share/{user}/{token}/file/{ap}"
            return {"type": "chat", "id": chat_id, "title": meta.get("title", ""),
                    "messages": messages, **common}
        return {"type": "file", "path": path[5:],
                "url": f"/share/{user}/{token}/file/{path[5:]}", **common}

    @r.get("/share/{user}/{token}/file/{file_path:path}")
    async def shared_attachment(
        user: str, token: str, file_path: str,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        ws_owner, row = await _resolve_or_403(user, token, bearer)
        path = row["path"]
        # Authorize: file_path must be the share's file (file share) or an attachment of its chat.
        if path.startswith("file/"):
            if file_path != path[5:]:
                raise HTTPException(403, "Path not in this share")
        else:
            raw = await chat.load_messages(ws_owner, path[5:])
            allowed = {att.get("path") for m in chat.to_ui_messages(raw)
                       for att in (m.get("attachments") or []) if att.get("path")}
            if file_path not in allowed:
                raise HTTPException(403, "Not an attachment of this share")
        return _serve_file(ws_owner.root, file_path)

    @r.post("/share/{user}/{token}/fork")
    async def fork_share(user: str, token: str, forker: Any = user_dep):
        ws_source = workspace_at(user, volume, base=base)
        row = await shares.resolve(ws_source, token, requester=forker)
        if row is None:
            raise HTTPException(403, "Invalid, expired, or unauthorized link")
        if not row["path"].startswith("chat/"):
            raise HTTPException(400, "Only chat shares can be forked")
        source_id = row["path"][5:]
        meta = await chat.get_meta(ws_source, source_id)
        if meta is None:
            raise HTTPException(404, "Chat not found")
        raw = await chat.load_messages(ws_source, source_id)
        ws_fork = workspace_for(forker, volume, base=base)
        new_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        await chat.put_meta(ws_fork, new_id, {
            **{k: v for k, v in meta.items() if k not in ("id", "createdAt", "updatedAt")},
            "id": new_id, "createdAt": now, "updatedAt": now,
            "forked_from": f"{user}/{source_id}",
        })
        await chat.append_messages(ws_fork, new_id, raw, 0)
        for m in chat.to_ui_messages(raw):
            for att in m.get("attachments") or []:
                if ap := att.get("path"):
                    try:
                        src = resolve_path(ws_source.root, ap)
                        dst = resolve_path(ws_fork.root, ap)
                        if src.is_file():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(src, dst)
                    except Exception:
                        pass
        return {"id": new_id}

    return r


def _serve_file(root, file_path):
    try:
        target = resolve_path(root, file_path)
    except ValueError:
        raise HTTPException(403, "Path traversal denied")
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(target)


# ---- Mount ----

def install_routers(cycls_app, app, required_auth, volume, base):
    def _build_ws(user: Any = required_auth):
        return workspace_for(user, volume, base=base)
    ws_dep = Depends(_build_ws)
    app.include_router(chats_router(ws_dep))
    app.include_router(files_router(cycls_app, ws_dep, required_auth))
    app.include_router(share_router(cycls_app, ws_dep, required_auth, volume, base))

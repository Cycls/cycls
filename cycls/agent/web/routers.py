"""HTTP routers for the agent's state surface — chats, files, share.

Chat metadata + message log and shares live in the workspace DB — see
`cycls.agent.state`. Files stay on the workspace filesystem (POSIX-shaped).
"""
import os, secrets, shutil, time, unicodedata, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter, Depends, Request, Response, HTTPException, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse

from cycls.app.db import DB, Workspace, workspace
from cycls.agent import state
from cycls.agent.tools import tool_step

DEFAULT_MAX_UPLOAD_MB = 512   # per-file upload cap when not configured


def to_ui_messages(raw):
    """Stored API messages → FE shape `{role, content: str, parts?, attachments?}`.
    Drops harness scaffolding — messages tagged `internal` (compaction summary,
    output-limit resume prompt) and user messages that are purely tool_result —
    and merges consecutive assistant messages: a model turn is several
    assistant/tool-result round-trips on disk but one bubble in the UI, the same
    shape the live stream produces."""
    out = []
    for msg in raw:
        role, c = msg.get("role"), msg.get("content")
        if msg.get("internal"):
            continue
        if role == "user":
            if isinstance(c, list):
                if all(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                    continue
                text = "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            elif isinstance(c, str):
                text = c
            else:
                continue
            ui = {"role": "user", "content": text}
            if msg.get("attachments"):
                ui["attachments"] = msg["attachments"]
            out.append(ui)
        elif role == "assistant":
            blocks = c if isinstance(c, list) else [{"type": "text", "text": c}] if isinstance(c, str) else []
            parts, texts = [], []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text":
                    parts.append({"type": "text", "text": b.get("text", "")}); texts.append(b.get("text", ""))
                elif t == "thinking":
                    parts.append({"type": "thinking", "thinking": b.get("thinking", "")})
                elif t == "tool_use":
                    parts.append({"type": "step", "id": b.get("id"), **tool_step(b.get("name", ""), b.get("input"))})
                elif t == "server_tool_use":
                    # Server-side tools (web_search etc.) run Anthropic-side. The live
                    # provider stream yields a Step for these at content_block_stop;
                    # mirror it on refetch so search history doesn't vanish on reload.
                    parts.append({"type": "step", **tool_step(b.get("name", ""), b.get("input"))})
            if out and out[-1]["role"] == "assistant":
                out[-1]["content"] += "".join(texts); out[-1]["parts"] += parts
            else:
                out.append({"role": "assistant", "content": "".join(texts), "parts": parts})
    return out


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
        async for cid, data in state.list_chats(ws):
            items.append({
                "id": data.get("id", cid),
                "title": data.get("title", ""),
                "updatedAt": data.get("updatedAt", ""),
                "favoritedAt": data.get("favoritedAt", ""),
                "cost": data.get("cost", "0"),
            })
        items.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
        return items

    @r.get("/chats/{chat_id}")
    async def get_chat(chat_id: str, ws: Workspace = ws_dep):
        meta = await state.get_meta(ws, chat_id)
        # 204 (not 404) for a missing chat: the FE auto-restores `?id=` on
        # cold load, and a stale id is normal — 404s clutter the dev console.
        if meta is None:
            return Response(status_code=204)
        raw = await state.load_messages(ws, chat_id)
        return {**meta, "messages": to_ui_messages(raw)}

    @r.put("/chats/{chat_id}")
    async def put_chat(chat_id: str, request: Request, ws: Workspace = ws_dep):
        """Partial update — merges into existing meta. Send `field: null` to remove a key.
        `updatedAt` is NOT bumped on metadata edits (rename, favorite, …) — it tracks
        message activity only, owned by `touch_meta` on new messages."""
        patch = await request.json()
        patch.pop("messages", None)
        existing = (await state.get_meta(ws, chat_id)) or {}
        merged = {**existing}
        for k, v in patch.items():
            if v is None: merged.pop(k, None)
            else: merged[k] = v
        now = datetime.now(timezone.utc).isoformat()
        merged["id"] = chat_id
        merged.setdefault("createdAt", now)
        merged.setdefault("updatedAt", now)
        await state.put_meta(ws, chat_id, merged)
        return merged

    @r.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str, ws: Workspace = ws_dep):
        if (await state.get_meta(ws, chat_id)) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        await state.delete_chat(ws, chat_id)
        return {"ok": True}

    return r


# ---- Files ----

def files_router(cycls_app, ws_dep, user_dep):
    r = APIRouter()
    max_bytes = (getattr(getattr(cycls_app, "config", None), "max_upload", None) or DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024

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
        # recursive=1 → flat list of every file and folder under `target` with
        # paths relative to the workspace root (for @-mention search and the
        # "Move to…" picker). Skips hidden dirs/files (incl. .db/.database).
        if request.query_params.get("recursive") is not None:
            items = []
            for root, dirs, files in os.walk(target):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for d in dirs:
                    full = Path(root) / d
                    items.append({
                        "name": d,
                        "path": str(full.relative_to(ws.root)),
                        "type": "directory",
                        "size": 0,
                        "modified": datetime.fromtimestamp(full.stat().st_mtime, tz=timezone.utc).isoformat(),
                    })
                    if len(items) >= 2000:
                        return items
                for fn in sorted(files):
                    if fn.startswith("."):
                        continue
                    full = Path(root) / fn
                    items.append({
                        "name": fn,
                        "path": str(full.relative_to(ws.root)),
                        "type": "file",
                        "size": full.stat().st_size,
                        "modified": datetime.fromtimestamp(full.stat().st_mtime, tz=timezone.utc).isoformat(),
                    })
                    if len(items) >= 2000:   # cap response size
                        return items
            return items
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
        if file_path.is_dir():
            return _zip_dir(file_path)   # folders download as <name>.zip
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if request.query_params.get("download") is not None:
            return FileResponse(file_path, filename=file_path.name)
        return FileResponse(file_path)

    @r.put("/files/{path:path}")
    async def put_file(path: str, request: Request, file: UploadFile = File(...), ws: Workspace = ws_dep):
        file_path = _safe_path(ws.root, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # Stream to a .part temp in 1 MB chunks (flat app memory regardless of
        # size), enforce a cap, then rename — so a failed upload can't corrupt an
        # existing file. Works on local FS and the gcsfuse workspace mount.
        tmp = file_path.with_name(file_path.name + ".part")
        size = 0
        try:
            with open(tmp, "wb") as out:
                while chunk := await file.read(1 << 20):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(413, f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
                    out.write(chunk)
            tmp.replace(file_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return {"ok": True}

    @r.patch("/files/{path:path}")
    async def rename(path: str, request: Request, ws: Workspace = ws_dep):
        src = _safe_path(ws.root, path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Not found")
        data = await request.json()
        dest = _safe_path(ws.root, data["to"])
        if dest.exists():
            raise HTTPException(status_code=409, detail="Destination already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        # shutil.move (not rename) so directory moves work on the gcsfuse
        # workspace mount, which doesn't support renaming directories — it falls
        # back to recursive copy + delete.
        shutil.move(str(src), str(dest))
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
        ws_owner = workspace(user, volume, base=base)
        requester = None
        if bearer and cycls_app._auth_provider is not None:
            try: requester = authenticate(cycls_app._auth_provider, cycls_app.prod, bearer.credentials)
            except Exception: pass
        row = await state.resolve(ws_owner, token, requester=requester)
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
        if path.startswith("chat/") and (await state.get_meta(ws, path[5:])) is None:
            raise HTTPException(404, "Chat not found")
        token = secrets.token_urlsafe(16)
        row = {"path": path, "audience": data.get("audience", "public"),
               "shared_at": datetime.now(timezone.utc).isoformat()}
        # Author fields are flat str:str so the row stays meta-eligible (O(1) scan).
        for k in ("author_name", "author_image_url", "author_org_name", "author_org_image_url"):
            if (v := data.get(k)): row[k] = v
        await DB(ws).put(f"share/{token}", row, meta=row)
        return {"token": token, "url": f"/shared/{ws.subject}/{token}", **row}

    @r.get("/share")
    async def list_shares(ws: Workspace = ws_dep):
        # Two LIST calls regardless of N: shares + chat indexes.
        db = DB(ws)
        chat_titles = {k.split("/")[1]: m.get("title", "")
                       async for k, m in db.scan(glob="chat/*/index")}
        out = []
        async for key, meta in db.scan(prefix="share/"):
            token = key[6:]
            path = meta.get("path", "")
            if path.startswith("chat/"):
                title = chat_titles.get(path[5:], "")
            else:
                title = path[5:]
            out.append({"token": token, "url": f"/shared/{ws.subject}/{token}", "title": title, **meta})
        out.sort(key=lambda s: s.get("shared_at", ""), reverse=True)
        return out

    @r.delete("/share/{token}")
    async def revoke_share(token: str, ws: Workspace = ws_dep):
        await DB(ws).delete(f"share/{token}")
        return {"ok": True}

    # ---- Viewer side ----

    @r.get("/share/{user}/{token}/data")
    async def resolve_share(
        user: str, token: str,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        ws_owner, row = await _resolve_or_403(user, token, bearer)
        path = row["path"]
        common = {k: row[k] for k in
                  ("shared_at", "author_name", "author_image_url", "author_org_name", "author_org_image_url")
                  if k in row}
        if path.startswith("chat/"):
            chat_id = path[5:]
            meta = await state.get_meta(ws_owner, chat_id)
            if meta is None:
                raise HTTPException(404, "Chat not found")
            messages = to_ui_messages(await state.load_messages(ws_owner, chat_id))
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
            raw = await state.load_messages(ws_owner, path[5:])
            allowed = {att.get("path") for m in to_ui_messages(raw)
                       for att in (m.get("attachments") or []) if att.get("path")}
            if file_path not in allowed:
                raise HTTPException(403, "Not an attachment of this share")
        return _serve_file(ws_owner.root, file_path)

    @r.post("/share/{user}/{token}/fork")
    async def fork_share(user: str, token: str, forker: Any = user_dep):
        ws_source = workspace(user, volume, base=base)
        row = await state.resolve(ws_source, token, requester=forker)
        if row is None:
            raise HTTPException(403, "Invalid, expired, or unauthorized link")
        if not row["path"].startswith("chat/"):
            raise HTTPException(400, "Only chat shares can be forked")
        source_id = row["path"][5:]
        meta = await state.get_meta(ws_source, source_id)
        if meta is None:
            raise HTTPException(404, "Chat not found")
        raw = await state.load_messages(ws_source, source_id)
        ws_fork = workspace(forker, volume, base=base)
        new_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        await state.put_meta(ws_fork, new_id, {
            **{k: v for k, v in meta.items() if k not in ("id", "createdAt", "updatedAt")},
            "id": new_id, "createdAt": now, "updatedAt": now,
            "forked_from": f"{user}/{source_id}",
        })
        await state.append_messages(ws_fork, new_id, raw, 0)
        for m in to_ui_messages(raw):
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


def _zip_dir(dir_path):
    """Stream a directory back as a .zip (skips hidden/.db entries). Built to a
    temp file, then served and cleaned up — avoids holding it all in memory."""
    import zipfile, tempfile
    from starlette.background import BackgroundTask
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in dir_path.rglob("*"):
            if f.is_file() and not any(p.startswith(".") for p in f.relative_to(dir_path).parts):
                zf.write(f, f.relative_to(dir_path.parent))   # keep the folder as the top dir
    return FileResponse(tmp.name, filename=f"{dir_path.name}.zip", media_type="application/zip",
                        background=BackgroundTask(lambda: os.unlink(tmp.name)))


# ---- Mount ----

def install_routers(cycls_app, app, required_auth, volume, base):
    def _build_ws(user: Any = required_auth):
        return workspace(user, volume, base=base)
    ws_dep = Depends(_build_ws)
    app.include_router(chats_router(ws_dep))
    app.include_router(files_router(cycls_app, ws_dep, required_auth))
    app.include_router(share_router(cycls_app, ws_dep, required_auth, volume, base))

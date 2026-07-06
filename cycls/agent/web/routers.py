"""HTTP routers for the agent's state surface — chats, files, share.

Chat metadata + message log and shares live in the workspace DB — see
`cycls.agent.state`. Files stay on the workspace filesystem (POSIX-shaped).
"""
import asyncio, os, secrets, shutil, time, unicodedata, uuid
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
    # tool_use id → its result errored. Lets the FE downgrade failed canvas
    # calls from a file card back to a plain step.
    errored = set()
    for msg in raw:
        c = msg.get("content")
        if msg.get("role") == "user" and isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    body = b.get("content")
                    if b.get("is_error") or (isinstance(body, str) and body.startswith("Error")):
                        errored.add(b.get("tool_use_id"))

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
                    part = {"type": "step", "id": b.get("id"), **tool_step(b.get("name", ""), b.get("input"))}
                    if b.get("id") in errored:
                        part["ok"] = False
                    parts.append(part)
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


# ---- Workspace selection (multi-workspace mode) ----

async def resolve_ws_id(user, header, mode, volume, base):
    """`X-Workspace` header → workspace id the user may enter, or None in
    legacy mode. Personal (`u-{user.id}`) is the default and needs no lookup;
    team ids are checked against the ACL (member row, or implicit org-admin).
    Everything else — a teammate's personal id, an unknown team, garbage —
    is 404, not 403, so ids don't leak existence (docs/workspaces.md)."""
    if not mode or user is None:
        return None
    await state.ensure_migrated(user, volume, base)   # free after the org's first touch
    ws_id = header or f"u-{user.id}"
    if ws_id == f"u-{user.id}":
        return ws_id
    if ws_id.startswith("t-"):
        orgdb = state.org_db(state.org_of(user), volume, base)
        if await state.resolve_role(user, ws_id, orgdb) is not None:
            return ws_id
    raise HTTPException(404, "Workspace not found")


def personal_ws(subject):
    """Personal workspace id for a `org:user` / `user` subject string."""
    org, _, user = subject.partition(":")
    return f"u-{user or org}"


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
    mode = getattr(getattr(cycls_app, "config", None), "workspaces", None)

    async def _locate(user: str, token: str, requester, ws_q=None):
        """Find the share row in whichever of the owner's workspaces minted it.
        Minted URLs carry `?ws=`; bare legacy links fall back to the owner's
        personal workspace, then General."""
        candidates = [ws_q] if ws_q else ([personal_ws(user), "t-shared"] if mode else [None])
        for ws_id in candidates:
            try:
                ws_owner = workspace(user, volume, base=base, ws=ws_id)
            except ValueError:
                break
            row = await state.resolve(ws_owner, token, requester=requester)
            if row is not None:
                return ws_owner, row
        return None

    async def _resolve_or_403(user: str, token: str, bearer, ws_q=None):
        from cycls.app.auth import authenticate
        requester = None
        if bearer and cycls_app._auth_provider is not None:
            try: requester = authenticate(cycls_app._auth_provider, cycls_app.prod, bearer.credentials)
            except Exception: pass
        found = await _locate(user, token, requester, ws_q)
        if found is None:
            raise HTTPException(403, "Invalid, expired, or unauthorized link")
        return found

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
        return {"token": token, "url": _share_url(ws, token), **row}

    @r.get("/share")
    async def list_shares(ws: Workspace = ws_dep):
        # Two LIST calls regardless of N: shares + chat indexes.
        db = DB(ws)
        chat_titles = {k.split("/")[1]: m.get("title", "")
                       async for k, m in db.scan(glob="chat/*/index")}
        out = []
        async for key, meta in db.scan(prefix="share/"):
            token = key[6:]
            if not meta.get("path"):   # meta channel wiped (gcsfuse move) — body is canonical
                body = await db.get(key)
                if isinstance(body, dict) and body.get("path"):
                    meta = body
                    await db.put(key, body, meta={k: v for k, v in body.items() if isinstance(v, str)})
            path = meta.get("path", "")
            if path.startswith("chat/"):
                title = chat_titles.get(path[5:], "")
            else:
                title = path[5:]
            out.append({"token": token, "url": _share_url(ws, token), "title": title, **meta})
        out.sort(key=lambda s: s.get("shared_at", ""), reverse=True)
        return out

    @r.delete("/share/{token}")
    async def revoke_share(token: str, ws: Workspace = ws_dep):
        await DB(ws).delete(f"share/{token}")
        return {"ok": True}

    # ---- Viewer side ----

    @r.get("/share/{user}/{token}/data")
    async def resolve_share(
        user: str, token: str, ws: Optional[str] = None,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        ws_owner, row = await _resolve_or_403(user, token, bearer, ws)
        path = row["path"]
        common = {k: row[k] for k in
                  ("shared_at", "author_name", "author_image_url", "author_org_name", "author_org_image_url")
                  if k in row}
        suffix = f"?ws={ws_owner.ws}" if ws_owner.ws else ""
        if path.startswith("chat/"):
            chat_id = path[5:]
            meta = await state.get_meta(ws_owner, chat_id)
            if meta is None:
                raise HTTPException(404, "Chat not found")
            messages = to_ui_messages(await state.load_messages(ws_owner, chat_id))
            for m in messages:
                for att in m.get("attachments") or []:
                    if ap := att.get("path"):
                        att["url"] = f"/share/{user}/{token}/file/{ap}{suffix}"
            return {"type": "chat", "id": chat_id, "title": meta.get("title", ""),
                    "messages": messages, **common}
        return {"type": "file", "path": path[5:],
                "url": f"/share/{user}/{token}/file/{path[5:]}{suffix}", **common}

    @r.get("/share/{user}/{token}/file/{file_path:path}")
    async def shared_attachment(
        user: str, token: str, file_path: str, ws: Optional[str] = None,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        ws_owner, row = await _resolve_or_403(user, token, bearer, ws)
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
    async def fork_share(user: str, token: str, ws: Optional[str] = None, forker: Any = user_dep):
        found = await _locate(user, token, forker, ws)
        if found is None:
            raise HTTPException(403, "Invalid, expired, or unauthorized link")
        ws_source, row = found
        if not row["path"].startswith("chat/"):
            raise HTTPException(400, "Only chat shares can be forked")
        source_id = row["path"][5:]
        meta = await state.get_meta(ws_source, source_id)
        if meta is None:
            raise HTTPException(404, "Chat not found")
        raw = await state.load_messages(ws_source, source_id)
        ws_fork = workspace(forker, volume, base=base, ws=f"u-{forker.id}" if mode else None)
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


def _share_url(ws, token):
    """Viewer URL for a share — carries the minting workspace so the viewer
    endpoints can find the row without guessing."""
    return f"/shared/{ws.subject}/{token}" + (f"?ws={ws.ws}" if ws.ws else "")


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


# ---- Workspaces (registry + members — docs/workspaces.md) ----

def workspaces_router(cycls_app, user_dep, volume, base):
    """Workspace lifecycle + member management. Content access control lives in
    `resolve_ws_id`; this router owns create/rename/delete and the ACL rows."""
    r = APIRouter()
    mode = getattr(getattr(cycls_app, "config", None), "workspaces", None)

    def _orgdb(user):
        return state.org_db(state.org_of(user), volume, base)

    def _is_org_admin(user):
        return getattr(user, "org_role", None) == "admin"

    def _name_or_400(data):
        name = (data.get("name") or "").strip()
        if not 1 <= len(name) <= 80:
            raise HTTPException(400, "name must be 1-80 characters")
        return name

    async def _role_or_404(user, ws_id):
        role = await state.resolve_role(user, ws_id, _orgdb(user))
        if role is None:
            raise HTTPException(404, "Workspace not found")
        return role

    async def _manager_or_403(user, ws_id):
        if not ws_id.startswith("t-"):
            raise HTTPException(404, "Workspace not found")
        if await _role_or_404(user, ws_id) not in ("owner", "admin"):
            raise HTTPException(403, "Managing this workspace requires owner or admin")

    @r.get("/workspaces")
    async def list_workspaces(request: Request, user: Any = user_dep):
        await state.ensure_migrated(user, volume, base)
        orgdb = _orgdb(user)
        out = [{"id": f"u-{user.id}", "name": "Personal", "type": "personal", "role": "owner"}]
        if _is_org_admin(user) and request.query_params.get("all") is not None:
            # Lifecycle view (offboarding): every team workspace + every personal
            # dir. Names/ids only — content stays behind the owner-only check.
            async for _, row in orgdb.scan(prefix="workspaces/"):
                out.append({**row, "role": "admin"})
            ws_dir = Path(volume) / state.org_of(user) / "ws"
            dirs = await asyncio.to_thread(
                lambda: [e.name for e in os.scandir(ws_dir) if e.is_dir()] if ws_dir.is_dir() else [])
            out += [{"id": d, "name": d[2:], "type": "personal", "role": None}
                    for d in sorted(dirs) if d.startswith("u-") and d != f"u-{user.id}"]
            return out
        for ws_id in await state.member_of(orgdb, user.id):
            row = await orgdb.get(f"workspaces/{ws_id}")
            member = await orgdb.get(f"members/{ws_id}/{user.id}")
            if row:
                out.append({**row, "role": (member or {}).get("role")})
        # General has no member rows — every org member is an editor via
        # its `builtin: org` registry row.
        if getattr(user, "org_id", None) and not any(w["id"] == "t-shared" for w in out):
            if reg := await orgdb.get("workspaces/t-shared"):
                out.append({**reg, "role": "admin" if _is_org_admin(user) else "editor"})
        return out

    @r.post("/workspaces")
    async def create_workspace(request: Request, user: Any = user_dep):
        if mode == "admin" and not _is_org_admin(user):
            raise HTTPException(403, "Only org admins can create team workspaces")
        if not getattr(user, "org_id", None):
            raise HTTPException(400, "Team workspaces require an organization")
        name = _name_or_400(await request.json())
        return await state.create_team_ws(_orgdb(user), name, user.id)

    @r.patch("/workspaces/{ws_id}")
    async def rename_workspace(ws_id: str, request: Request, user: Any = user_dep):
        await _manager_or_403(user, ws_id)
        name = _name_or_400(await request.json())
        orgdb = _orgdb(user)
        row = {**(await orgdb.get(f"workspaces/{ws_id}") or {}), "name": name}
        await orgdb.put(f"workspaces/{ws_id}", row, meta=row)
        return row

    @r.delete("/workspaces/{ws_id}")
    async def delete_workspace(ws_id: str, user: Any = user_dep):
        if ws_id.startswith("u-"):
            # Personal: the owner themselves, or an org admin (lifecycle —
            # offboarding). Admins never gain content routes on it.
            if ws_id != f"u-{user.id}" and not _is_org_admin(user):
                raise HTTPException(404, "Workspace not found")
        elif await _role_or_404(user, ws_id) != "owner" and not _is_org_admin(user):
            raise HTTPException(403, "Deleting a team workspace requires its owner")
        await state.wipe_workspace(state.org_of(user), ws_id, volume, base)
        return {"ok": True}

    # ---- Members (team workspaces only) ----

    @r.get("/workspaces/{ws_id}/members")
    async def list_members(ws_id: str, user: Any = user_dep):
        if not ws_id.startswith("t-"):
            raise HTTPException(404, "Workspace not found")
        await _role_or_404(user, ws_id)   # any member (or org admin) may look
        return [{"user_id": key.rsplit("/", 1)[1], **row}
                async for key, row in _orgdb(user).scan(prefix=f"members/{ws_id}/")]

    @r.put("/workspaces/{ws_id}/members/{member_id}")
    async def put_member(ws_id: str, member_id: str, request: Request, user: Any = user_dep):
        await _manager_or_403(user, ws_id)
        role = (await request.json()).get("role", "editor")
        if role not in ("admin", "editor"):
            raise HTTPException(400, 'role must be "admin" or "editor"')
        orgdb = _orgdb(user)
        existing = await orgdb.get(f"members/{ws_id}/{member_id}")
        if existing and existing.get("role") == "owner":
            raise HTTPException(403, "The owner's role cannot be changed")
        row = {"role": role, "added_by": user.id,
               "added_at": datetime.now(timezone.utc).isoformat()}
        await orgdb.put(f"members/{ws_id}/{member_id}", row, meta=row)
        return {"user_id": member_id, **row}

    @r.delete("/workspaces/{ws_id}/members/{member_id}")
    async def remove_member(ws_id: str, member_id: str, user: Any = user_dep):
        orgdb = _orgdb(user)
        if member_id == user.id:
            await _role_or_404(user, ws_id)   # leaving requires being in it
        else:
            await _manager_or_403(user, ws_id)
        existing = await orgdb.get(f"members/{ws_id}/{member_id}")
        if existing and existing.get("role") == "owner":
            raise HTTPException(403, "The owner cannot be removed")
        await orgdb.delete(f"members/{ws_id}/{member_id}")
        return {"ok": True}

    return r


# ---- Mount ----

def install_routers(cycls_app, app, required_auth, volume, base):
    mode = getattr(getattr(cycls_app, "config", None), "workspaces", None)

    async def _build_ws(request: Request, user: Any = required_auth):
        ws_id = await resolve_ws_id(user, request.headers.get("x-workspace"), mode, volume, base)
        return workspace(user, volume, base=base, ws=ws_id)
    ws_dep = Depends(_build_ws)
    app.include_router(chats_router(ws_dep))
    app.include_router(files_router(cycls_app, ws_dep, required_auth))
    app.include_router(share_router(cycls_app, ws_dep, required_auth, volume, base))
    if mode:
        app.include_router(workspaces_router(cycls_app, required_auth, volume, base))

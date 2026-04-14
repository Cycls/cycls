import json, os, shutil, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

def resolve_path(workspace, rel):
    """Resolve *rel* inside *workspace*, raising ValueError on traversal."""
    workspace = Path(workspace)
    rel = unicodedata.normalize("NFC", rel)
    resolved = (workspace / rel).resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise ValueError("Path traversal denied")
    return resolved

def ensure_workspace(workspace):
    """Create the workspace directory tree if it doesn't exist."""
    Path(workspace).mkdir(parents=True, exist_ok=True)

def history_path(user, session_id):
    """Validate *session_id* and return the JSONL history file path."""
    if os.sep in session_id or (os.altsep and os.altsep in session_id):
        raise ValueError(f"Invalid session id: {session_id}")
    path = user.sessions / f"{session_id}.history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)

def load_history(path):
    """Read JSONL history, strip stale cache_control, mark last message ephemeral."""
    messages = []
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if line:
                    messages.append(json.loads(line))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except UnicodeDecodeError as e:
        print(f"[DEBUG] UnicodeDecodeError in {path} at line {i}: {e}")
        return messages
    for msg in messages:
        c = msg.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    if messages:
        c = messages[-1].get("content")
        if isinstance(c, str):
            messages[-1]["content"] = [{"type": "text", "text": c, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        elif isinstance(c, list) and c:
            c[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return messages

def save_history(path, messages, mode="a"):
    """Write messages as JSONL."""
    with open(path, mode) as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def sessions_router(required_auth):
    r = APIRouter()

    @r.get("/sessions")
    async def list_sessions(user: Any = required_auth):
        if not user.sessions.is_dir():
            return []
        items = []
        for f in user.sessions.iterdir():
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text())
                items.append({"id": data.get("id", f.stem), "title": data.get("title", ""), "updatedAt": data.get("updatedAt", "")})
            except (json.JSONDecodeError, OSError):
                continue
        items.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
        return items

    @r.get("/sessions/{session_id}")
    async def get_session(session_id: str, user: Any = required_auth):
        session_file = user.sessions / f"{session_id}.json"
        if not session_file.is_file():
            raise HTTPException(status_code=404, detail="Session not found")
        return json.loads(session_file.read_text())

    @r.put("/sessions/{session_id}")
    async def put_session(session_id: str, request: Request, user: Any = required_auth):
        user.sessions.mkdir(parents=True, exist_ok=True)
        data = await request.json()
        data["id"] = session_id
        data["updatedAt"] = datetime.now(timezone.utc).isoformat()
        if "createdAt" not in data:
            data["createdAt"] = data["updatedAt"]
        (user.sessions / f"{session_id}.json").write_text(json.dumps(data))
        return data

    @r.delete("/sessions/{session_id}")
    async def delete_session(session_id: str, user: Any = required_auth):
        session_file = user.sessions / f"{session_id}.json"
        if not session_file.is_file():
            raise HTTPException(status_code=404, detail="Session not found")
        session_file.unlink()
        history_file = user.sessions / f"{session_id}.history.jsonl"
        if history_file.is_file():
            history_file.unlink()
        return {"ok": True}

    return r


def files_router(required_auth):
    r = APIRouter()

    def _safe_path(workspace, rel):
        try:
            return resolve_path(workspace, rel)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path traversal denied")

    @r.get("/files")
    async def list_files(request: Request, user: Any = required_auth):
        target = _safe_path(user.workspace, request.query_params.get("path", ""))
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
        file_path = _safe_path(user.workspace, path)
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if request.query_params.get("download") is not None:
            return FileResponse(file_path, filename=file_path.name)
        return FileResponse(file_path)

    @r.put("/files/{path:path}")
    async def put_file(path: str, request: Request, file: UploadFile = File(...), user: Any = required_auth):
        file_path = _safe_path(user.workspace, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(await file.read())
        return {"ok": True}

    @r.patch("/files/{path:path}")
    async def rename(path: str, request: Request, user: Any = required_auth):
        src = _safe_path(user.workspace, path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Not found")
        data = await request.json()
        dest = _safe_path(user.workspace, data["to"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        return {"ok": True}

    @r.post("/files/{path:path}")
    async def mkdir(path: str, user: Any = required_auth):
        dir_path = _safe_path(user.workspace, path)
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"ok": True}

    @r.delete("/files/{path:path}")
    async def delete_path(path: str, user: Any = required_auth):
        target = _safe_path(user.workspace, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Not found")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True}

    return r


def share_router(required_auth):
    r = APIRouter()
    shared_index = Path("/workspace/shared")

    def _resolve(share_id):
        pointer = shared_index / f"{share_id}.json"
        if not pointer.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        data = json.loads(pointer.read_text())
        share_dir = Path(data["path"])
        if not share_dir.is_dir():
            pointer.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="Not found")
        return share_dir

    @r.post("/share")
    async def create_share(request: Request, user: Any = required_auth):
        data = await request.json()
        messages = data.get("messages")
        if not messages:
            raise HTTPException(status_code=400, detail="messages required")

        share_id = uuid4().hex[:12]
        share_dir = user.sessions / "public" / share_id
        share_dir.mkdir(parents=True, exist_ok=True)

        for msg in messages:
            for att in msg.get("attachments") or []:
                att_path = att.get("path")
                if not att_path:
                    continue
                src = user.workspace / att_path
                if src.is_file():
                    shutil.copy2(src, share_dir / src.name)
                    att["url"] = f"/shared-assets/{share_id}/{src.name}"

        snapshot = {
            "id": share_id,
            "title": data.get("title", ""),
            "author": data.get("author"),
            "sharedAt": datetime.now(timezone.utc).isoformat(),
            "messages": messages,
        }
        (share_dir / "share.json").write_text(json.dumps(snapshot))

        # Write global pointer
        shared_index.mkdir(parents=True, exist_ok=True)
        (shared_index / f"{share_id}.json").write_text(json.dumps({"path": str(share_dir)}))

        return {"id": share_id, "path": share_id}

    @r.get("/share")
    async def list_shares(user: Any = required_auth):
        public_dir = user.sessions / "public"
        if not public_dir.is_dir():
            return []
        items = []
        for d in public_dir.iterdir():
            f = d / "share.json"
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text())
                items.append({"id": data.get("id", d.name), "title": data.get("title", ""), "sharedAt": data.get("sharedAt", ""), "path": data.get("id", d.name)})
            except (json.JSONDecodeError, OSError):
                continue
        items.sort(key=lambda s: s.get("sharedAt", ""), reverse=True)
        return items

    @r.get("/share/{share_id}")
    async def get_share(share_id: str):
        share_dir = _resolve(share_id)
        return json.loads((share_dir / "share.json").read_text())

    @r.get("/shared-assets/{share_id}/{filename}")
    async def get_shared_asset(share_id: str, filename: str):
        share_dir = _resolve(share_id)
        file_path = share_dir / filename
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(file_path)

    @r.delete("/share/{share_id}")
    async def delete_share(share_id: str, user: Any = required_auth):
        share_dir = user.sessions / "public" / share_id
        if not share_dir.is_dir():
            raise HTTPException(status_code=404, detail="Not found")
        shutil.rmtree(share_dir)
        # Remove pointer
        pointer = shared_index / f"{share_id}.json"
        if pointer.is_file():
            pointer.unlink()
        return {"ok": True}

    return r


def install_routers(app, required_auth):
    """Mount sessions, files, and share routers on a FastAPI app."""
    app.include_router(sessions_router(required_auth))
    app.include_router(files_router(required_auth))
    app.include_router(share_router(required_auth))

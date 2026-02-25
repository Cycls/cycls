import json, os, shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

def router(required_auth):
    r = APIRouter()

    # ---- Sessions ----

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
        return {"ok": True}

    # ---- Files ----

    def safe_path(workspace: Path, rel: str) -> Path:
        resolved = (workspace / rel).resolve()
        if not resolved.is_relative_to(workspace.resolve()):
            raise HTTPException(status_code=403, detail="Path traversal denied")
        return resolved

    @r.get("/files")
    async def list_files(request: Request, user: Any = required_auth):
        target = safe_path(user.workspace, request.query_params.get("path", ""))
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="Directory not found")
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
        file_path = safe_path(user.workspace, path)
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if request.query_params.get("download") is not None:
            return FileResponse(file_path, filename=file_path.name)
        return FileResponse(file_path)

    @r.put("/files/{path:path}")
    async def put_file(path: str, request: Request, file: UploadFile = File(...), user: Any = required_auth):
        file_path = safe_path(user.workspace, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(await file.read())
        return {"ok": True}

    @r.patch("/files/{path:path}")
    async def rename(path: str, request: Request, user: Any = required_auth):
        src = safe_path(user.workspace, path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Not found")
        data = await request.json()
        dest = safe_path(user.workspace, data["to"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        return {"ok": True}

    @r.post("/files/{path:path}")
    async def mkdir(path: str, user: Any = required_auth):
        dir_path = safe_path(user.workspace, path)
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"ok": True}

    @r.delete("/files/{path:path}")
    async def delete_path(path: str, user: Any = required_auth):
        target = safe_path(user.workspace, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Not found")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True}

    return r

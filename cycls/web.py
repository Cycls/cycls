import json, inspect, os
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, Any
from .auth import PK_LIVE, PK_TEST, JWKS_PROD, JWKS_TEST

class Config(BaseModel):
    public_path: str = "theme"
    header: Optional[str] = None
    intro: Optional[str] = None
    title: Optional[str] = None
    prod: bool = False
    auth: bool = False
    plan: str = "free"
    analytics: bool = False
    pk: Optional[str] = None
    jwks: Optional[str] = None

    def set_prod(self, prod: bool):
        self.prod = prod
        self.pk = PK_LIVE if prod else PK_TEST
        self.jwks = JWKS_PROD if prod else JWKS_TEST

async def openai_encoder(stream):
    if inspect.isasyncgen(stream):
        async for msg in stream:
            if msg: yield f"data: {json.dumps({'choices': [{'delta': {'content': msg}}]})}\n\n"
    else:
        for msg in stream:
            if msg: yield f"data: {json.dumps({'choices': [{'delta': {'content': msg}}]})}\n\n"
    yield "data: [DONE]\n\n"

def sse(item):
    if not item: return None
    if not isinstance(item, dict): item = {"type": "text", "text": item}
    return f"data: {json.dumps(item)}\n\n"

async def encoder(stream):
    if inspect.isasyncgen(stream):
        async for item in stream:
            if msg := sse(item): yield msg
    else:
        for item in stream:
            if msg := sse(item): yield msg
    yield "data: [DONE]\n\n"

class Messages(list):
    """A list that provides text-only messages by default, with .raw for full data."""
    def __init__(self, raw_messages):
        self._raw = raw_messages
        text_messages = []
        for m in raw_messages:
            text_content = "".join(
                p.get("text", "") for p in m.get("parts", []) if p.get("type") == "text"
            )
            text_messages.append({
                "role": m.get("role"),
                "content": m.get("content") or text_content
            })
        super().__init__(text_messages)

    @property
    def raw(self):
        return self._raw

def web(func, config):
    from fastapi import FastAPI, Request, HTTPException, status, Depends, UploadFile, File
    from fastapi.responses import StreamingResponse, FileResponse
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    import jwt
    from jwt import PyJWKClient
    from pydantic import EmailStr
    from typing import List, Optional, Any
    from fastapi.staticfiles import StaticFiles

    if isinstance(config, dict):
        config = Config(**config)

    jwks = PyJWKClient(config.jwks)

    class User(BaseModel):
        id: str
        name: Optional[str] = None
        email: EmailStr
        org_id: Optional[str] = None
        org_name: Optional[str] = None
        org_slug: Optional[str] = None
        plan_name: Optional[str] = None
        plan_id: Optional[str] = None
        plan_slug: Optional[str] = None

    class Context(BaseModel):
        messages: Any
        user: Optional[User] = None

        model_config = {"arbitrary_types_allowed": True}

        @property
        def last_message(self) -> str:
            if self.messages:
                return self.messages[-1].get("content", "")
            return ""

        @property
        def workspace(self) -> str:
            if not self.user:
                return "/workspace/default"
            return f"/workspace/{self.user.org_id}" if self.user.org_id else f"/workspace/{self.user.id}"

    app = FastAPI()
    bearer_scheme = HTTPBearer()

    def validate(bearer: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
        try:
            key = jwks.get_signing_key_from_jwt(bearer.credentials)
            decoded = jwt.decode(bearer.credentials, key.key, algorithms=["RS256"], leeway=10)
            return {"type": "user",
                    "user": {"id": decoded.get("id"), "name": decoded.get("name"), "email": decoded.get("email"),
                             "org_id": decoded.get("org_id"), "org_name": decoded.get("org_name"), "org_slug": decoded.get("org_slug")}}
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired", headers={"WWW-Authenticate": "Bearer"})
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}", headers={"WWW-Authenticate": "Bearer"})
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Auth error: {e}", headers={"WWW-Authenticate": "Bearer"})

    auth = Depends(validate) if config.auth else None

    @app.post("/")
    @app.post("/chat/cycls")
    @app.post("/chat/completions")
    async def back(request: Request, jwt: Optional[dict] = auth):
        data = await request.json()
        messages = data.get("messages")
        user_data = jwt.get("user") if jwt else None
        if user_data and data.get("plan"):
            user_data.update(data["plan"])
        user = User(**user_data) if user_data else None

        context = Context(messages=Messages(messages), user=user)
        stream = await func(context) if inspect.iscoroutinefunction(func) else func(context)

        if request.url.path == "/chat/completions":
            stream = openai_encoder(stream)
        elif request.url.path == "/chat/cycls":
            stream = encoder(stream)
        return StreamingResponse(stream, media_type="text/event-stream")

    @app.get("/config")
    async def get_config():
        return config

    # ---- Helper ----

    def user_root(jwt):
        user = jwt["user"]
        return Path(f"/workspace/{user['org_id']}") if user.get("org_id") else Path(f"/workspace/{user['id']}")

    # ---- Sessions API ----

    @app.get("/sessions")
    async def list_sessions(jwt: dict = auth):
        sessions_dir = user_root(jwt) / ".sessions" / jwt["user"]["id"]
        if not sessions_dir.is_dir():
            return []
        items = []
        for f in sessions_dir.iterdir():
            if f.suffix != ".json":
                continue
            try:
                data = json.loads(f.read_text())
                items.append({"id": data.get("id", f.stem), "title": data.get("title", ""), "updatedAt": data.get("updatedAt", "")})
            except (json.JSONDecodeError, OSError):
                continue
        items.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
        return items

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str, jwt: dict = auth):
        session_file = user_root(jwt) / ".sessions" / jwt["user"]["id"] / f"{session_id}.json"
        if not session_file.is_file():
            raise HTTPException(status_code=404, detail="Session not found")
        return json.loads(session_file.read_text())

    @app.put("/sessions/{session_id}")
    async def put_session(session_id: str, request: Request, jwt: dict = auth):
        sessions_dir = user_root(jwt) / ".sessions" / jwt["user"]["id"]
        sessions_dir.mkdir(parents=True, exist_ok=True)
        data = await request.json()
        data["id"] = session_id
        data["updatedAt"] = datetime.now(timezone.utc).isoformat()
        if "createdAt" not in data:
            data["createdAt"] = data["updatedAt"]
        session_file = sessions_dir / f"{session_id}.json"
        session_file.write_text(json.dumps(data))
        return data

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: str, jwt: dict = auth):
        session_file = user_root(jwt) / ".sessions" / jwt["user"]["id"] / f"{session_id}.json"
        if not session_file.is_file():
            raise HTTPException(status_code=404, detail="Session not found")
        session_file.unlink()
        return {"ok": True}

    # ---- File API ----

    def safe_path(jwt, rel: str) -> Path:
        root = user_root(jwt)
        resolved = (root / rel).resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise HTTPException(status_code=403, detail="Path traversal denied")
        return resolved

    @app.get("/files")
    async def list_files(request: Request, jwt: dict = auth):
        subpath = request.query_params.get("path", "")
        target = safe_path(jwt, subpath)
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

    @app.get("/files/{path:path}")
    async def get_file(path: str, request: Request, jwt: dict = auth):
        file_path = safe_path(jwt, path)
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        if request.query_params.get("download") is not None:
            return FileResponse(file_path, filename=file_path.name)
        return FileResponse(file_path)

    @app.put("/files/{path:path}")
    async def put_file(path: str, request: Request, file: UploadFile = File(...), jwt: dict = auth):
        file_path = safe_path(jwt, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(await file.read())
        return {"ok": True}

    @app.patch("/files/{path:path}")
    async def rename(path: str, request: Request, jwt: dict = auth):
        src = safe_path(jwt, path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Not found")
        data = await request.json()
        dest = safe_path(jwt, data["to"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        return {"ok": True}

    @app.post("/files/{path:path}")
    async def mkdir(path: str, jwt: dict = auth):
        dir_path = safe_path(jwt, path)
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"ok": True}

    @app.delete("/files/{path:path}")
    async def delete_path(path: str, jwt: dict = auth):
        import shutil
        target = safe_path(jwt, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Not found")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True}

    # ---- Static mounts (must be last) ----

    if Path("public").is_dir():
        app.mount("/public", StaticFiles(directory="public", html=True))
    app.mount("/", StaticFiles(directory=config.public_path, html=True))

    return app

def serve(func, config, name, port):
    import uvicorn, logging
    from dotenv import load_dotenv
    load_dotenv()
    if isinstance(config, dict):
        config = Config(**config)
    logging.getLogger("uvicorn.error").addFilter(lambda r: "0.0.0.0" not in r.getMessage())
    print(f"\n🔨 {name} => http://localhost:{port}\n")
    uvicorn.run(web(func, config), host="0.0.0.0", port=port)

import json, inspect, uuid
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, Any
from .auth import PK_LIVE, PK_TEST, JWKS_PROD, JWKS_TEST

class Config(BaseModel):
    public_path: str = "theme"
    name: Optional[str] = None
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

async def encoder(stream, session_id=None):
    if session_id:
        yield sse({"type": "session_id", "session_id": session_id})
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
    from fastapi import FastAPI, Request, HTTPException, status, Depends
    from fastapi.responses import StreamingResponse, FileResponse
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    import jwt
    from jwt import PyJWKClient
    from typing import Optional, Any
    from fastapi.staticfiles import StaticFiles

    if isinstance(config, dict):
        config = Config(**config)

    jwks = PyJWKClient(config.jwks)

    class User(BaseModel):
        id: str
        org_id: Optional[str] = None
        org_slug: Optional[str] = None
        org_role: Optional[str] = None
        org_permissions: Optional[list] = None
        plan: Optional[str] = None
        features: Optional[list] = None

        @property
        def workspace(self) -> Path:
            return Path(f"/workspace/{self.org_id}") if self.org_id else Path(f"/workspace/{self.id}")

        @property
        def sessions(self) -> Path:
            return self.workspace / ".sessions" / self.id if self.org_id else self.workspace / ".sessions"

    class Context(BaseModel):
        messages: Any
        user: Optional[User] = None
        session_id: Optional[str] = None

        model_config = {"arbitrary_types_allowed": True}

        @property
        def last_message(self) -> str:
            if self.messages:
                return self.messages[-1].get("content", "")
            return ""

        @property
        def workspace(self) -> Path:
            return self.user.workspace if self.user else Path("/workspace/local")

    app = FastAPI()
    
    bearer_scheme = HTTPBearer()

    def validate(request: Request, bearer: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))):
        token = bearer.credentials if bearer else request.query_params.get("token")
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
        try:
            key = jwks.get_signing_key_from_jwt(token)
            decoded = jwt.decode(token, key.key, algorithms=["RS256"], leeway=10)
            org = decoded.get("o") or {}
            return User(id=decoded.get("sub"), org_id=org.get("id"), org_slug=org.get("slg"), org_role=org.get("rol"), org_permissions=org.get("per"),
                        plan=decoded.get("pla"), features=decoded.get("fea"))
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired", headers={"WWW-Authenticate": "Bearer"})
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}", headers={"WWW-Authenticate": "Bearer"})
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Auth error: {e}", headers={"WWW-Authenticate": "Bearer"})

    auth = Depends(validate) if config.auth else Depends(lambda: None)
    required_auth = Depends(validate)

    @app.post("/")
    @app.post("/chat")
    @app.post("/chat/completions")
    async def back(request: Request, user: Optional[User] = auth):
        data = await request.json()
        messages = data.get("messages")
        session_id = data.get("session_id") or str(uuid.uuid4())

        context = Context(messages=Messages(messages), user=user, session_id=session_id)
        stream = await func(context) if inspect.iscoroutinefunction(func) else func(context)

        if request.url.path == "/chat/completions":
            stream = openai_encoder(stream)
        else:
            stream = encoder(stream, session_id=session_id)
        return StreamingResponse(stream, media_type="text/event-stream")

    @app.get("/config")
    async def get_config():
        return config

    from cycls.app.state import sessions_router, files_router, share_router
    app.include_router(sessions_router(required_auth))
    app.include_router(files_router(required_auth))
    app.include_router(share_router(required_auth))

    # ---- Rewrite index.html with OG meta tags ----

    index_path = Path(config.public_path) / "index.html"
    if index_path.is_file() and config.name:
        from html import escape
        html = index_path.read_text()
        og_title = f"Cycls | @{escape(config.name)}"
        html = html.replace('<meta property="og:title" content="Cycls" />', f'<meta property="og:title" content="{og_title}" />')
        html = html.replace('<title>Cycls</title>', f'<title>{og_title}</title>')
        if config.title:
            html = html.replace('<meta property="og:description" content="AI Agent" />', f'<meta property="og:description" content="{escape(config.title)}" />')
        index_path.write_text(html)

    # ---- SPA fallback routes (before static mounts) ----

    @app.get("/sso-callback")
    @app.get("/shared/{path:path}")
    async def spa_fallback(path: str = ""):
        return FileResponse(Path(config.public_path) / "index.html")

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

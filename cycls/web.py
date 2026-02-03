import json, inspect, secrets
from urllib.parse import quote
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
    org: Optional[str] = None
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
        org: Optional[str] = None
        plans: List[str] = []

    class Context(BaseModel):
        messages: Any
        user: Optional[User] = None

        model_config = {"arbitrary_types_allowed": True}

        @property
        def last_message(self) -> str:
            if self.messages:
                return self.messages[-1].get("content", "")
            return ""

    app = FastAPI()
    bearer_scheme = HTTPBearer()

    def validate(bearer: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
        try:
            key = jwks.get_signing_key_from_jwt(bearer.credentials)
            decoded = jwt.decode(bearer.credentials, key.key, algorithms=["RS256"], leeway=10)
            return {"type": "user",
                    "user": {"id": decoded.get("id"), "name": decoded.get("name"), "email": decoded.get("email"), "org": decoded.get("org"),
                             "plans": decoded.get("public", {}).get("plans", [])}}
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

    @app.post("/attachments")
    async def upload_attachment(request: Request, file: UploadFile = File(...), jwt: Optional[dict] = auth):
        token = secrets.token_urlsafe(32)
        token_dir = Path(f"/workspace/attachments/{token}")
        token_dir.mkdir(parents=True, exist_ok=True)

        file_path = token_dir / file.filename
        with open(file_path, "wb") as f:
            f.write(await file.read())

        return {"url": f"/attachments/{token}/{quote(file.filename)}"}

    @app.get("/attachments/{token}/{filename}")
    async def get_attachment(token: str, filename: str):
        file_path = Path(f"/workspace/attachments/{token}") / filename

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(file_path)

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
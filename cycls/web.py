import json, inspect
from pathlib import Path

JWKS_PROD = "https://clerk.cycls.ai/.well-known/jwks.json"
PK_LIVE = "pk_live_Y2xlcmsuY3ljbHMuYWkk"
JWKS_TEST = "https://select-sloth-58.clerk.accounts.dev/.well-known/jwks.json"
PK_TEST = "pk_test_c2VsZWN0LXNsb3RoLTU4LmNsZXJrLmFjY291bnRzLmRldiQ"

async def openai_encoder(stream):
    if inspect.isasyncgen(stream):
        async for msg in stream:
            if msg: yield f"data: {json.dumps({'choices': [{'delta': {'content': msg}}]})}\n\n"
    else:
        for msg in stream:
            if msg: yield f"data: {json.dumps({'choices': [{'delta': {'content': msg}}]})}\n\n"
    yield "data: [DONE]\n\n"

class Encoder:
    def __init__(self): self.cur = None
    def sse(self, d): return f"data: {json.dumps(d)}\n\n"
    def close(self):
        if self.cur: self.cur = None; return self.sse(["-"])

    def process(self, item):
        if not item: return
        if not isinstance(item, dict): item = {"name": "text", "content": item}
        n, done = item.get("name"), item.get("_complete")
        p = {k: v for k, v in item.items() if k not in ("name", "_complete")}
        if done:
            if c := self.close(): yield c
            yield self.sse(["=", {"name": n, **p}])
        elif n != self.cur:
            if c := self.close(): yield c
            self.cur = n
            yield self.sse(["+", n, p])
        else:
            yield self.sse(["~", p])

async def encoder(stream):
    enc = Encoder()
    if inspect.isasyncgen(stream):
        async for item in stream:
            for msg in enc.process(item): yield msg
    else:
        for item in stream:
            for msg in enc.process(item): yield msg
    if close := enc.close(): yield close
    yield "data: [DONE]\n\n"

class Messages(list):
    """A list that provides text-only messages by default, with .raw for full data."""
    def __init__(self, raw_messages):
        self._raw = raw_messages
        text_messages = []
        for m in raw_messages:
            text_content = "".join(
                p.get("content", "") for p in m.get("parts", []) if p.get("name") == "text"
            )
            text_messages.append({
                "role": m.get("role"),
                "content": m.get("content") or text_content
            })
        super().__init__(text_messages)

    @property
    def raw(self):
        return self._raw

def web(func, public_path="", prod=False, org=None, api_token=None, header="", intro="", title="", auth=False, tier="", analytics=False): # API auth
    from fastapi import FastAPI, Request, HTTPException, status, Depends
    from fastapi.responses import StreamingResponse , HTMLResponse
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    import jwt
    from jwt import PyJWKClient
    from pydantic import BaseModel, EmailStr
    from typing import List, Optional, Any
    from fastapi.staticfiles import StaticFiles

    jwks = PyJWKClient(JWKS_PROD if prod else JWKS_TEST)

    class User(BaseModel):
        id: str
        name: Optional[str] = None
        email: EmailStr
        org: Optional[str] = None
        plans: List[str] = []

    class Metadata(BaseModel):
        header: str
        intro: str
        title: str
        prod: bool
        auth: bool
        tier: str
        analytics: bool
        org: Optional[str]
        pk_live: str
        pk_test: str

    class Context(BaseModel):
        messages: Any
        user: Optional[User] = None

    app = FastAPI()
    bearer_scheme = HTTPBearer()

    def validate(bearer: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
        try:
            key = jwks.get_signing_key_from_jwt(bearer.credentials)
            decoded = jwt.decode(bearer.credentials, key.key, algorithms=["RS256"], leeway=10)
            return {"type": "user",
                    "user": {"id": decoded.get("id"), "name": decoded.get("name"), "email": decoded.get("email"), "org": decoded.get("org"),
                             "plans": decoded.get("public", {}).get("plans", [])}}
        except:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    
    @app.post("/")
    @app.post("/chat/cycls")
    @app.post("/chat/completions")
    async def back(request: Request, jwt: Optional[dict] = Depends(validate) if auth else None):
        data = await request.json()
        messages = data.get("messages")
        user_data = jwt.get("user") if jwt else None
        context = Context(messages = Messages(messages), user = User(**user_data) if user_data else None)
        stream = await func(context) if inspect.iscoroutinefunction(func) else func(context)
        if request.url.path == "/chat/completions":
            stream = openai_encoder(stream)
        elif request.url.path == "/chat/cycls":
            stream = encoder(stream)
        return StreamingResponse(stream, media_type="text/event-stream")

    @app.get("/metadata")
    async def metadata():
        return Metadata(
            header=header,
            intro=intro,
            title=title,
            prod=prod,
            auth=auth,
            tier=tier,
            analytics=analytics,
            org=org,
            pk_live=PK_LIVE,
            pk_test=PK_TEST
        )

    if Path("public").is_dir():
        app.mount("/public", StaticFiles(directory="public", html=True))
    app.mount("/", StaticFiles(directory=public_path, html=True))

    return app

def serve(func, config, name, port):
    import uvicorn, logging
    logging.getLogger("uvicorn.error").addFilter(lambda r: "0.0.0.0" not in r.getMessage())
    print(f"\n🔨 {name} => http://localhost:{port}\n")
    uvicorn.run(web(func, *config), host="0.0.0.0", port=port)
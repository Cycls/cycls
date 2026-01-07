import json, inspect
from pathlib import Path

async def async_openai_encoder(stream):
    async for message in stream:
        payload = {"choices": [{"delta": {"content": message}}]}
        if message:
            yield f"data: {json.dumps(payload)}\n\n"
    yield "data: [DONE]\n\n"

class StreamEncoder:
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
    enc = StreamEncoder()
    if inspect.isasyncgen(stream):
        async for item in stream:
            for msg in enc.process(item): yield msg
    else:
        for item in stream:
            for msg in enc.process(item): yield msg
    if close := enc.close(): yield close
    yield "data: [DONE]\n\n"

test_auth_public_key = """
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyDudrDtQ5irw6hPWf2rw
FvNAFWeOouOO3XNWVQrjXCZfegiLYkL4cJdm4eqIuMdFHGnXU+gWT5P0EkLIkbtE
zpqDb5Wp27WpSRb5lqJehpU7FE+oQuovCwR9m5gYXP5rfM+CQ7ZPw/CcOQPtOB5G
0UijBhmYqws3SFp1Rk1uFed1F/esspt6Ifq2uDSHESleylqTKUCQiBa++z4wllcV
PbNiooLRpsF0kGljP2dXXy/ViF7q9Cblgl+FdrqtGfHD+DHJuOSYcPnRa0IHZYS4
r5i9C2lejVrEDqgJk5IbmQgez0wmEG4ynAxiDLvfdtvrd27PyBI75FsyLER/ydBH
WwIDAQAB
-----END PUBLIC KEY-----
"""

live_auth_public_key = """
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAorfL7XyxrLG/X+Kq9ImY
oSQ+Y3PY5qi8t8R4urY9u4ADJ48j9LkmFz8ALbubQkl3IByDDuVbka49m8id9isy
F9ZJErsZzzlYztrgI5Sg4R6OJXcNWLqh/tzutMWJFOrE3LnHXpeyQMo/6qAd59Dx
sNqzGxBTGPV1BZvpfhp/TT/sjgbPQWHS4PMpKD4vZLKXeTNJ913fMTUoFAIaL0sT
EhoeLUwvIuhLx4UYTmjO/sa+fS6mdghjddOkjSS/AWr/K8mN3IXDImGqh83L7/P0
RCru4Hvarm0qPIhfwEFfWhKFXONMj3x2fT4MM1Uw1H7qKTER2MtOjmdchKNX7x9b
XwIDAQAB
-----END PUBLIC KEY-----
"""

def web(func, public_path="", prod=False, org=None, api_token=None, header="", intro="", title="", auth=False, tier="", analytics=False): # API auth
    from fastapi import FastAPI, Request, HTTPException, status, Depends
    from fastapi.responses import StreamingResponse , HTMLResponse
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    import jwt
    from pydantic import BaseModel, EmailStr
    from typing import List, Optional
    from fastapi.staticfiles import StaticFiles

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
        messages: List[dict]
        user: Optional[User] = None

    app = FastAPI()
    bearer_scheme = HTTPBearer()

    def validate(bearer: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
        # if api_token and api_token==""
        try:
            public_key = live_auth_public_key if prod else test_auth_public_key
            decoded = jwt.decode(bearer.credentials, public_key, algorithms=["RS256"], leeway=10)
            # print(decoded)
            return {"type": "user", 
                    "user": {"id": decoded.get("id"), "name": decoded.get("name"), "email": decoded.get("email"), "org": decoded.get("org"),
                             "plans": decoded.get("public").get("plans", [])}}
        except:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    
    @app.post("/")
    @app.post("/chat/cycls")
    @app.post("/chat/completions")
    async def back(request: Request, jwt: Optional[dict] = Depends(validate) if auth else None):
        data = await request.json()
        messages = data.get("messages")
        user_data = jwt.get("user") if jwt else None
        context = Context(messages = messages, user = User(**user_data) if user_data else None)
        stream = await func(context) if inspect.iscoroutinefunction(func) else func(context)
        if request.url.path == "/chat/completions":
            stream = async_openai_encoder(stream)
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
            pk_live="pk_live_Y2xlcmsuY3ljbHMuYWkk",
            pk_test="pk_test_c2VsZWN0LXNsb3RoLTU4LmNsZXJrLmFjY291bnRzLmRldiQ"
        )

    if Path("public").is_dir():
        app.mount("/public", StaticFiles(directory="public", html=True))
    app.mount("/", StaticFiles(directory=public_path, html=True))

    return app
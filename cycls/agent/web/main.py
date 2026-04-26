import json, inspect, uuid, os
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, Any
from cycls.app.auth import User, make_validate
from cycls.app.db import Workspace

class PassMetadata(BaseModel):
    name: str
    description: str = ""
    logo: str = ""

class Config(BaseModel):
    public_path: str = "theme"
    name: Optional[str] = None
    pass_metadata: Optional[dict[str, PassMetadata]] = None
    title: Optional[str] = None
    prod: bool = False
    auth: bool = False
    cms: Optional[str] = None
    analytics: bool = False
    voice: bool = False
    pk: Optional[str] = None
    jwks: Optional[str] = None
    volume: str = "/workspace"

    def set_prod(self, prod: bool):
        self.prod = prod

async def openai_encoder(stream):
    try:
        if inspect.isasyncgen(stream):
            async for msg in stream:
                if msg: yield f"data: {json.dumps({'choices': [{'delta': {'content': msg}}]})}\n\n"
        else:
            for msg in stream:
                if msg: yield f"data: {json.dumps({'choices': [{'delta': {'content': msg}}]})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'choices': [{'delta': {'content': f'\n\n[stream failed: {e}]'}}]})}\n\n"
    yield "data: [DONE]\n\n"

def sse(item):
    if not item: return None
    if not isinstance(item, dict): item = {"type": "text", "text": item}
    return f"data: {json.dumps(item)}\n\n"

async def encoder(stream, session_id=None):
    if session_id:
        yield sse({"type": "session_id", "session_id": session_id})
    try:
        if inspect.isasyncgen(stream):
            async for item in stream:
                if msg := sse(item): yield msg
        else:
            for item in stream:
                if msg := sse(item): yield msg
    except Exception as e:
        yield sse({"type": "callout", "callout": f"Stream failed: {e}", "style": "error"})
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

def web(func, config, extra_routers=None):
    from fastapi import FastAPI, Request, HTTPException, Depends
    from fastapi.responses import StreamingResponse
    from fastapi.staticfiles import StaticFiles

    import httpx

    if isinstance(config, dict):
        config = Config(**config)

    if config.cms == "cycls.ai" and config.name and not config.pass_metadata:
        try:
            resp = httpx.get(f"https://cms.cycls.ai/agents/{config.name}", timeout=5)
            if resp.status_code == 200:
                agent = resp.json()
                config.pass_metadata = {
                    "en": PassMetadata(
                        name=agent.get("title", config.name),
                        description=agent.get("description", ""),
                        logo=agent.get("icon_svg", ""),
                    ),
                    "ar": PassMetadata(
                        name=agent.get("title_ar") or agent.get("title", config.name),
                        description=agent.get("description_ar", ""),
                        logo=agent.get("icon_svg", ""),
                    ),
                }
        except Exception:
            pass

    volume = Path(config.volume)

    class Context(BaseModel):
        messages: Any
        user: Optional[User] = None
        session_id: Optional[str] = None
        prod: bool = False

        model_config = {"arbitrary_types_allowed": True}

        @property
        def last_message(self) -> str:
            if self.messages:
                return self.messages[-1].get("content", "")
            return ""

        def workspace(self) -> Workspace:
            user = self.user
            if user is None:
                return Workspace(volume / "local")
            if user.org_id:
                return Workspace(volume / user.org_id, user_id=user.id)
            return Workspace(volume / user.id)

    app = FastAPI()

    validate = make_validate(config)
    auth = Depends(validate) if config.auth else Depends(lambda: None)
    required_auth = Depends(validate)

    @app.post("/")
    @app.post("/chat")
    @app.post("/chat/completions")
    async def back(request: Request, user: Optional[User] = auth):
        data = await request.json()
        messages = data.get("messages")
        session_id = data.get("session_id") or str(uuid.uuid4())

        context = Context(messages=Messages(messages), user=user, session_id=session_id, prod=config.prod)
        stream = await func(context) if inspect.iscoroutinefunction(func) else func(context)

        if request.url.path == "/chat/completions":
            stream = openai_encoder(stream)
        else:
            stream = encoder(stream, session_id=session_id)
        return StreamingResponse(stream, media_type="text/event-stream")

    @app.get("/config")
    async def get_config():
        return config

    @app.post("/transcribe")
    async def transcribe(request: Request, user: Optional[User] = auth):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=501, detail="Transcription not configured")
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="No audio file")
        audio_bytes = await file.read()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("voice.m4a", audio_bytes, file.content_type or "audio/mp4")},
                data={"model": "gpt-4o-transcribe"},
                timeout=30,
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            return r.json()

    for install in (extra_routers or []):
        install(app, required_auth)

    # ---- SEO helpers ----

    from fastapi.responses import HTMLResponse
    from html import escape
    _base_html = (Path(config.public_path) / "index.html").read_text()

    config.voice = bool(os.environ.get("OPENAI_API_KEY"))
    _config_script = f'<script>window.__CONFIG__={config.model_dump_json()}</script>'

    def _seo_html(title: str = "Cycls", desc: str = "AI Agent"):
        return _base_html.replace("__TITLE__", escape(title)).replace("__DESC__", escape(desc)).replace("</body>", f"{_config_script}</body>")

    app_title = f"{config.name.capitalize()} | Cycls Pass" if config.name else "Cycls"
    _index_html = _seo_html(app_title, config.title or "AI Agent")

    # ---- Dynamic OG images ----

    from fastapi.responses import Response

    og_title = config.name.capitalize() if config.name else "Cycls"

    @app.get("/og.png")
    async def og_image():
        from .og import generate as og_generate
        return Response(await og_generate(og_title, config.title or ""), media_type="image/png")

    @app.get("/og/{share_id}.png")
    async def og_shared_image(share_id: str):
        from .og import generate as og_generate
        try:
            pointer = json.loads((Path("/workspace/shared") / f"{share_id}.json").read_text())
            share = json.loads((Path(pointer["path"]) / "share.json").read_text())
            title = share.get("title") or "Shared conversation"
            author = share.get("author") or {}
            avatars = [u for u in [author.get("org", {}).get("imageUrl"), author.get("imageUrl")] if u]
            return Response(await og_generate(og_title, title, avatars=avatars), media_type="image/png")
        except Exception:
            return Response(await og_generate(og_title, config.title or ""), media_type="image/png")

    # ---- SPA fallback routes (before static mounts) ----

    @app.get("/")
    @app.get("/sso-callback")
    async def index():
        return HTMLResponse(_index_html)

    @app.get("/shared/{share_id:path}")
    async def shared_page(share_id: str):
        try:
            pointer = json.loads((Path("/workspace/shared") / f"{share_id}.json").read_text())
            share = json.loads((Path(pointer["path"]) / "share.json").read_text())
            title = share.get("title") or "Shared conversation"
            return HTMLResponse(_seo_html(app_title, title).replace("/og.png", f"/og/{share_id}.png"))
        except Exception:
            return HTMLResponse(_index_html)

    # ---- Static mounts (must be last) ----

    if Path("public").is_dir():
        app.mount("/public", StaticFiles(directory="public", html=True))
    app.mount("/", StaticFiles(directory=config.public_path))

    return app

def serve(func, config, name, port, extra_routers=None):
    import uvicorn, logging
    from dotenv import load_dotenv
    load_dotenv()
    logging.getLogger("uvicorn.error").addFilter(lambda r: "0.0.0.0" not in r.getMessage())
    print(f"\n🔨 {name} => http://localhost:{port}\n")
    uvicorn.run(web(func, config, extra_routers=extra_routers), host="0.0.0.0", port=port)

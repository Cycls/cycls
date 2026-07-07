import json, inspect, time, uuid, os
from pathlib import Path
from pydantic import BaseModel, PrivateAttr
from typing import Optional, Any
from cycls.app.auth import User, validator
from cycls.app.db import Workspace, workspace
from cycls.agent.logs import log


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
    cms: Optional[dict] = None        # {brand: url, explore: url, token: bearer} — plain GETs, contract JSON
    analytics: bool = False
    suggestions: bool = False
    voice: bool = False
    pk: Optional[str] = None
    affiliate: Optional[str] = None   # affiliate/referral provider key (e.g. Rewardful)
    max_upload: int = 512             # per-file upload cap in MB
    workspaces: Optional[str] = None  # multi-workspace mode: None off, else team-create policy ("member"|"admin")
    volume: str = "/workspace"
    seo: Optional[dict] = None        # {title, description} — page copy overriding the brand
    head: Optional[str] = None        # raw HTML appended to <head> (verification tags etc.)
    favicon: Optional[str] = None     # inline <svg>, data URI, or URL
    og: Optional[str] = None          # og:image URL when external; custom bytes ride _og_image
    explore: Optional[list] = None    # static explore menu (contract-shaped entries)
    explore_enabled: bool = False     # FE shows the agents dropdown
    colors: Optional[dict] = None     # {primary, secondary, primary_dark, secondary_dark}
    _og_image: Optional[bytes] = PrivateAttr(default=None)  # custom og card, served at /og.png

    def set_prod(self, prod: bool):
        self.prod = prod

    @property
    def storage(self) -> str:
        if self.prod and self.name:
            return f"gs://cycls-ws-{self.name}"
        return f"file://{self.volume}"

async def _aiter(stream):
    """Unify sync + async streams as a single async iterator."""
    if inspect.isasyncgen(stream):
        async for x in stream: yield x
    else:
        for x in stream: yield x

async def openai_encoder(stream):
    try:
        async for msg in _aiter(stream):
            if msg: yield f"data: {json.dumps({'choices': [{'delta': {'content': msg}}]})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'choices': [{'delta': {'content': f'\n\n[stream failed: {e}]'}}]})}\n\n"
    yield "data: [DONE]\n\n"

def sse(item):
    if not item: return None
    if not isinstance(item, dict): item = {"type": "text", "text": item}
    return f"data: {json.dumps(item)}\n\n"

async def encoder(stream, *, chat_id=None, user=None):
    if chat_id: yield sse({"type": "chat_id", "chat_id": chat_id})
    try:
        async for item in _aiter(stream):
            if msg := sse(item): yield msg
    except Exception as e:
        import traceback
        error_id = uuid.uuid4().hex[:8]
        log("error", user=user, chat_id=chat_id,
            error_id=error_id, message=str(e), stack=traceback.format_exc())
        yield sse({"type": "callout",
                   "callout": f"Something went wrong. Reference: `{error_id}`",
                   "style": "error"})
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

def web(func, config, extra_routers=None, auth=None):
    from fastapi import FastAPI, Request, HTTPException, Depends
    from fastapi import Response as FastAPIResponse
    from fastapi.responses import StreamingResponse
    from fastapi.staticfiles import StaticFiles

    import httpx

    if isinstance(config, dict):
        config = Config(**config)

    cms = config.cms or {}
    _cms_headers = {"Authorization": f"Bearer {cms['token']}"} if cms.get("token") else {}
    if cms.get("brand") and not config.pass_metadata:
        try:
            resp = httpx.get(cms["brand"], headers=_cms_headers, timeout=5)
            if resp.status_code == 200:
                agent = resp.json()
                config.pass_metadata = {
                    "en": PassMetadata(
                        name=agent.get("title") or config.name or "",
                        description=agent.get("description", ""),
                        logo=agent.get("icon_svg", ""),
                    ),
                    "ar": PassMetadata(
                        name=agent.get("title_ar") or agent.get("title") or config.name or "",
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
        chat_id: Optional[str] = None
        prod: bool = False
        workspace_id: Optional[str] = None

        model_config = {"arbitrary_types_allowed": True}

        @property
        def last_message(self) -> str:
            if self.messages:
                return self.messages[-1].get("content", "")
            return ""

        @property
        def workspace(self) -> Workspace:
            return workspace(self.user, volume, base=config.storage, ws=self.workspace_id)

    app = FastAPI()

    validate = validator(auth, config.prod)
    auth = Depends(validate) if config.auth else Depends(lambda: None)
    required_auth = Depends(validate)

    from .routers import resolve_ws_id

    @app.post("/")
    @app.post("/chat")
    @app.post("/chat/completions")
    async def back(request: Request, user: Optional[User] = auth):
        data = await request.json()
        messages = data.get("messages")
        chat_id = request.query_params.get("id") or str(uuid.uuid4())
        ws_id = await resolve_ws_id(user, request.headers.get("x-workspace"), config.workspaces,
                                    volume, config.storage)

        context = Context(messages=Messages(messages), user=user, chat_id=chat_id, prod=config.prod,
                          workspace_id=ws_id)
        stream = await func(context) if inspect.iscoroutinefunction(func) else func(context)

        if request.url.path == "/chat/completions":
            stream = openai_encoder(stream)
        else:
            stream = encoder(stream, chat_id=chat_id, user=user)
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

    # ---- Explore menu (static list, or proxied + cached CMS) ----

    _explore_cache = {"at": 0.0, "data": None}

    @app.get("/explore")
    async def explore(response: FastAPIResponse):
        response.headers["Cache-Control"] = "public, max-age=300"
        if config.explore is not None:
            return {"agents": config.explore}
        url = cms.get("explore")
        if not url:
            return {"agents": []}
        if _explore_cache["data"] is None or time.time() - _explore_cache["at"] > 300:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.get(url, headers=_cms_headers)
                r.raise_for_status()
                _explore_cache.update(at=time.time(), data=r.json())
            except Exception:
                _explore_cache["at"] = time.time()
        return _explore_cache["data"] or {"agents": []}

    # ---- SEO ----

    from fastapi.responses import HTMLResponse
    from html import escape
    _base_html = (Path(config.public_path) / "index.html").read_text()

    config.voice = bool(os.environ.get("OPENAI_API_KEY"))
    _config_script = f'<script>window.__CONFIG__={config.model_dump_json()}</script>'

    brand_en = (config.pass_metadata or {}).get("en")
    seo = config.seo or {}
    app_title = seo.get("title") or (brand_en.name if brand_en else None) \
        or (f"{config.name.capitalize()} | Cycls Pass" if config.name else "Cycls")
    app_desc = seo.get("description") or (brand_en.description if brand_en else "") \
        or config.title or "AI Agent"

    _jsonld = json.dumps({"@context": "https://schema.org", "@type": "WebApplication",
                          "name": app_title, "description": app_desc,
                          "image": config.og or "/og.png",
                          "inLanguage": list(config.pass_metadata or {"en": None})})
    _extra_head = f'<script type="application/ld+json">{_jsonld}</script>'
    if config.favicon:
        href = config.favicon if config.favicon.startswith(("http", "data:")) else "/favicon.svg"
        _extra_head += f'<link rel="icon" href="{escape(href)}" />'
    if config.colors:
        c = config.colors
        light = "".join(f"--color-{k}:{v};" for k, v in
                        (("accent", c.get("primary")), ("secondary", c.get("secondary"))) if v)
        dark = "".join(f"--color-{k}:{v};" for k, v in
                       (("accent", c.get("primary_dark") or c.get("primary")),
                        ("secondary", c.get("secondary_dark") or c.get("secondary"))) if v)
        _extra_head += f"<style>:root{{{light}}}.dark{{{dark}}}</style>"
    if config.head:
        _extra_head += config.head
    # Crawlable content before JS runs; React replaces it with the same copy.
    _hero = f"<h1>{escape(app_title)}</h1><p>{escape(app_desc)}</p>"

    def _seo_html(title: str = "Cycls", desc: str = "AI Agent"):
        html = _base_html.replace("__TITLE__", escape(title)).replace("__DESC__", escape(desc))
        if config.og:
            html = html.replace('content="/og.png"', f'content="{escape(config.og)}"')
        html = html.replace("</head>", f"{_extra_head}</head>")
        html = html.replace('<div id="root"></div>', f'<div id="root">{_hero}</div>')
        return html.replace("</body>", f"{_config_script}</body>")

    _index_html = _seo_html(app_title, app_desc)

    @app.get("/robots.txt")
    async def robots(request: Request):
        return FastAPIResponse(f"User-agent: *\nAllow: /\nSitemap: {request.base_url}sitemap.xml\n",
                               media_type="text/plain")

    @app.get("/llms.txt")
    async def llms(request: Request):
        return FastAPIResponse(f"# {app_title}\n\n> {app_desc}\n\n- [{app_title}]({request.base_url})\n",
                               media_type="text/plain")

    @app.get("/sitemap.xml")
    async def sitemap(request: Request):
        return FastAPIResponse(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<url><loc>{request.base_url}</loc></url></urlset>',
            media_type="application/xml")

    if config.favicon and not config.favicon.startswith(("http", "data:")):
        @app.get("/favicon.svg")
        async def favicon():
            return FastAPIResponse(config.favicon, media_type="image/svg+xml")

    # ---- Dynamic OG images ----

    from fastapi.responses import Response

    og_title = (brand_en.name if brand_en else None) or (config.name.capitalize() if config.name else "Cycls")
    og_desc = (brand_en.description if brand_en else "") or config.title or ""

    @app.get("/og.png")
    async def og_image():
        if config._og_image:
            return Response(config._og_image, media_type="image/png")
        from .og import generate as og_generate
        return Response(await og_generate(og_title, og_desc), media_type="image/png")

    # ---- SPA fallback routes (before static mounts) ----

    @app.get("/")
    @app.get("/sso-callback")
    async def index():
        return HTMLResponse(_index_html)

    @app.get("/shared/{user}/{token}")
    async def share_index(user: str, token: str):
        return HTMLResponse(_index_html)

    # ---- Static mounts (must be last) ----

    if Path("public").is_dir():
        app.mount("/public", StaticFiles(directory="public", html=True))
    app.mount("/", StaticFiles(directory=config.public_path))

    return app

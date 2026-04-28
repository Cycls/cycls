# uv run cycls run examples/app/bun/bun_app.py
"""A Bun/TypeScript app served via cycls.

The user_func returns a thin Python ASGI proxy that fronts a Bun process.
Bun does the actual request work in TypeScript; cycls handles the
container, multi-tenancy, auth, and workspace mounting.

The proxy stamps `X-Workspace: <user's ws.root>` on every forwarded
request so the TypeScript handler can read/write per-tenant files
without re-implementing auth or tenancy. Same Clerk JWT, same SlateDB-
adjacent gcsfuse workspace, just a different runtime in the middle.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import cycls

SERVER_TS = str(Path(__file__).parent / "server.ts")
HTML_PATH = str(Path(__file__).parent / "bun.html")
BUN_PORT = 3000


image = (cycls.Image()
    .copy(SERVER_TS, "server.ts")
    .copy(HTML_PATH, "bun.html")
    .apt("curl", "unzip")
    # Install Bun and symlink so it's on PATH for our subprocess.
    .run("curl -fsSL https://bun.sh/install | bash "
         "&& ln -sf /root/.bun/bin/bun /usr/local/bin/bun"))


@cycls.app(image=image, auth=cycls.Clerk("cycls.ai"))
def bun_app():
    import httpx
    from fastapi import FastAPI, Request, Response, HTTPException
    from fastapi.responses import HTMLResponse

    @asynccontextmanager
    async def lifespan(app):
        # Spawn Bun as a child process; it serves on BUN_PORT, we proxy to it.
        proc = await asyncio.create_subprocess_exec(
            "bun", "run", "/app/server.ts",
            env={**os.environ, "PORT": str(BUN_PORT)},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )

        async def pump():
            assert proc.stdout is not None
            while line := await proc.stdout.readline():
                print(f"[bun] {line.decode().rstrip()}", flush=True)
        pump_task = asyncio.create_task(pump())

        client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{BUN_PORT}", timeout=30)
        # Wait for Bun to start serving.
        for _ in range(100):
            try:
                await client.get("/info")
                break
            except httpx.RequestError:
                await asyncio.sleep(0.05)
        else:
            raise RuntimeError("bun process didn't start")

        app.state.client = client
        try:
            yield
        finally:
            proc.terminate()
            try: await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError: proc.kill()
            pump_task.cancel()
            await client.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def index():
        pk = bun_app._auth_provider.resolve(bun_app.prod).get("pk", "")
        return HTMLResponse(Path("bun.html").read_text().replace("__CLERK_PK__", pk))

    HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate",
                  "proxy-authorization", "te", "trailers", "transfer-encoding",
                  "upgrade", "host", "content-length"}

    @app.api_route("/api/{path:path}",
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy(path: str, request: Request,
                    user=bun_app.auth, ws=bun_app.workspace):
        # The Python side validates the JWT and mounts the workspace; Bun
        # only sees what we choose to forward (path, body, X-Workspace).
        ws.root.mkdir(parents=True, exist_ok=True)
        client: httpx.AsyncClient = request.app.state.client
        body = await request.body()
        forward_headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP
        }
        forward_headers["X-Workspace"] = str(ws.root)
        try:
            r = await client.request(
                method=request.method, url=f"/{path}",
                content=body, params=request.query_params,
                headers=forward_headers,
            )
        except httpx.RequestError as e:
            raise HTTPException(502, f"bun unreachable: {e}")
        out_headers = {k: v for k, v in r.headers.items()
                       if k.lower() not in HOP_BY_HOP}
        return Response(content=r.content, status_code=r.status_code,
                        headers=out_headers)

    return app

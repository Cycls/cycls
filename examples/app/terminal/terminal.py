# uv run cycls run examples/app/terminal/terminal.py
"""Per-tenant terminal — toy agent with no LLM.

Each user gets their own /workspace (gcsfuse-backed in prod), a bwrap-
sandboxed bash for command execution, and a command history persisted in
cycls.DB. Files written by one command survive into the next; closing the
browser and reopening shows every byte. The whole "agent" is db + workspace
+ sandbox; the framework owns the per-tenant substrate.

Demonstrates:
  - cycls.Sandbox()               immutable builder, augmented per request
  - app.workspace                 per-user fs + db, both gated by Clerk JWT
  - sandbox.bind(...)             route adds the user's mount
  - cycls.DB(ws).put("history/<ts>", entry)  chronological history via ISO-timestamp keys
"""
from datetime import datetime, timezone
from pathlib import Path

import cycls

HTML_PATH = str(Path(__file__).parent / "terminal.html")

sandbox = (
    cycls.Sandbox()
    .setenv(PATH="/workspace/.local/bin:/usr/local/bin:/usr/bin:/bin")
    .network(True)
    .timeout(120)
)


@cycls.app(
    image=cycls.Image().copy(HTML_PATH, "terminal.html"),
    auth=cycls.Clerk(),
)
def terminal():
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel

    app = FastAPI(title="Terminal")

    @app.get("/")
    async def index():
        pk = terminal._auth_provider.resolve(terminal.prod).get("pk", "")
        html = Path("terminal.html").read_text().replace("__CLERK_PK__", pk)
        return HTMLResponse(html)

    @app.get("/me")
    async def me(user=terminal.auth):
        return user

    @app.get("/history")
    async def history(ws=terminal.workspace):
        return [e async for _, e in cycls.DB(ws).items(prefix="history/")]

    @app.delete("/history")
    async def clear_history(ws=terminal.workspace):
        async with cycls.DB(ws).transaction() as t:
            async for k, _ in t.items(prefix="history/"):
                await t.delete(k)
        return {"ok": True}

    class CmdIn(BaseModel):
        cmd: str

    @app.post("/run")
    async def run_cmd(body: CmdIn, ws=terminal.workspace):
        ws.root.mkdir(parents=True, exist_ok=True)
        sb = sandbox.bind(str(ws.root), "/workspace").chdir("/workspace")
        r = await sb.run(["bash", "-c", body.cmd])
        entry = {
            "cmd": body.cmd,
            "output": r.output,
            "code": r.code,
            "timed_out": r.timed_out,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        await cycls.DB(ws).put(f"history/{entry['at']}", entry)
        return entry

    return app

# uv run cycls run examples/app/terminal/terminal.py
"""Per-tenant terminal — toy agent with no LLM.

Each user gets their own /workspace (gcsfuse-backed in prod), a bwrap-
sandboxed bash for command execution, and a command history persisted in
cycls.DB. Files written by one command survive into the next; closing the
browser and reopening shows every byte. The whole "agent" is db + workspace
+ sandbox; the framework owns the per-tenant substrate.

Demonstrates:
  - sandbox=cycls.Sandbox()       configured-once profile, augmented per request
  - app.workspace                 per-user fs + db, both gated by Clerk JWT
  - app.sandbox.bind(...)         immutable builder; route adds the user's mount
  - cycls.DB(ws).kv("history")    chronological history via ISO-timestamp keys
"""
from datetime import datetime, timezone
from pathlib import Path

import cycls

HTML_PATH = str(Path(__file__).parent / "terminal.html")

# Security profile shared by every request. Per-request we only add the user's
# workspace bind on top — the rest (no network, clean env, 10s wall-clock cap)
# is fixed.
sandbox = (
    cycls.Sandbox()
    .ro_bind("/")
    .tmpfs("/tmp").dev("/dev").proc("/proc")
    .clearenv()
    .setenv(
        PATH="/usr/local/bin:/usr/bin:/bin",
        HOME="/workspace",
        TERM="xterm-256color",
        LANG="C.UTF-8",
    )
    .die_with_parent()
    .timeout(10)
)


@cycls.app(
    image=cycls.Image().copy(HTML_PATH, "terminal.html"),
    auth=cycls.Clerk("cycls.ai"),
    sandbox=sandbox,
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
        return [e async for _, e in cycls.DB(ws).kv("history").items()]

    @app.delete("/history")
    async def clear_history(ws=terminal.workspace):
        async with cycls.DB(ws).kv("history").transaction() as t:
            async for k, _ in t.items():
                await t.delete(k)
        return {"ok": True}

    class CmdIn(BaseModel):
        cmd: str

    @app.post("/run")
    async def run_cmd(body: CmdIn, ws=terminal.workspace):
        ws.root.mkdir(parents=True, exist_ok=True)
        sb = terminal.sandbox.bind(str(ws.root), "/workspace").chdir("/workspace")
        r = await sb.run(["bash", "-lc", body.cmd])
        entry = {
            "cmd": body.cmd,
            "output": r.output,
            "code": r.code,
            "timed_out": r.timed_out,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        await cycls.DB(ws).kv("history").put(entry["at"], entry)
        return entry

    return app

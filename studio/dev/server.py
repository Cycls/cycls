"""The Studio dev harness server: a stand-in for the chat host, so the built app can be
driven in any browser (or headless Chrome, see driver.mjs) without signing in.

It serves a host page that runs the REAL shim and bridge (host.ts, bundled here with
the client's esbuild), the built bundle (cycls/_agent/studio/app/index.html), the
workspace's files, and the REAL studio_router — so engine calls reach the deployed
Blender when CYCLS_STUDIO_ENGINE and CYCLS_API_KEY are set.

  python studio/dev/server.py [--port 8094] [--ws studio/dev/ws] [--env path/to/.env]
"""
import argparse
import os
import pathlib
import subprocess
import sys
import types

HERE = pathlib.Path(__file__).resolve().parent
SDK = HERE.parents[1]
sys.path.insert(0, str(SDK))

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8094)
ap.add_argument("--ws", default=str(HERE / "ws"), help="workspace root (seeded with the Studio if empty)")
ap.add_argument("--env", action="append", default=[], help="dotenv file(s) with CYCLS_API_KEY etc.")
args = ap.parse_args()

if args.env:
    from dotenv import load_dotenv
    for f in args.env:
        load_dotenv(f)
os.environ.setdefault("CYCLS_STUDIO_ENGINE", "cycls-render")

import uvicorn  # noqa: E402
from fastapi import Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, PlainTextResponse, Response  # noqa: E402

from cycls._agent.studio import install  # noqa: E402
from cycls._agent.studio.route import studio_router  # noqa: E402

WS = pathlib.Path(args.ws).resolve()
WS.mkdir(parents=True, exist_ok=True)
install._install(str(WS), *install.bundle())          # the stamp, the bundle, a scene if there is none

# The host page's script: the client's shim + bridge, bundled fresh.
esbuild = SDK / "client" / "node_modules" / ".bin" / ("esbuild.cmd" if os.name == "nt" else "esbuild")
subprocess.run([str(esbuild), str(HERE / "host.ts"), "--bundle", "--format=esm", "--log-level=warning",
                f"--alias:@client={SDK / 'client' / 'src'}", f"--outfile={HERE / 'host.js'}"], check=True)

app = FastAPI()
ws = types.SimpleNamespace(root=str(WS), subject="dev")
app.include_router(studio_router(Depends(lambda: ws), Depends(lambda: {"sub": "dev"})))

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Studio dev host</title>
<style>html,body{margin:0;height:100%;background:#111}#app{width:100%;height:100%;border:0;display:block}</style>
</head><body><iframe id="app" sandbox="allow-scripts allow-popups"></iframe>
<script type="module" src="/host.js"></script></body></html>"""


@app.get("/")
def page():
    return HTMLResponse(PAGE)


@app.get("/host.js")
def host():
    return Response((HERE / "host.js").read_bytes(), media_type="text/javascript")


@app.get("/studio.html")
def studio():
    return HTMLResponse((WS / install.APP_DIR / "index.html").read_text(encoding="utf-8"))


def _path(p):
    full = (WS / p).resolve()
    if not full.is_relative_to(WS):
        raise HTTPException(403)
    return full


@app.get("/files/{p:path}")
def read(p: str):
    f = _path(p)
    if not f.is_file():
        raise HTTPException(404)
    return PlainTextResponse(f.read_text(encoding="utf-8"))


@app.put("/files/{p:path}")
async def write(p: str, request: Request):
    f = _path(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(await request.body())
    return {"ok": True}


if __name__ == "__main__":
    print(f"Studio dev host on http://127.0.0.1:{args.port}/ — workspace {WS}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")

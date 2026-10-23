"""The routes behind the office editors in the canvas (Cycls Sheets; Cycls Docs later).

    GET /office/sheets?path=        may this workspace open the file in Cycls Sheets?
                                    → {editor: true, url, name} or {editor: false, reason}
    GET /office/sheets/open?path=   the workbook the editor opens (gzip JSON):
                                    {version, modified, snapshot, notices, activeSheet, stats}

The browser frames the editor from `url`; whether an organisation has Sheets is answered here, per
workspace (SHEETS_ORGS), so the setting never leaks to the page. The service reads the file; what it
read is kept beside the workspace's other caches (.cache/sheets/<version>.json.gz), so opening the
same file again costs nothing. Saving and the agent's edits join this router with patch-back.
"""
import asyncio
import gzip
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

SHEETS_EXTS = (".xlsx", ".xlsm")
SHEETS_CACHE = ".cache/sheets"
MAX_BYTES = 20 * 1024 * 1024     # larger workbooks keep the read-only preview
_KEEP = 24                       # cached reads kept per workspace


def _write_cache(cache_dir, version, body):
    """The read, kept by version; the oldest ones swept. A read-only workspace just isn't cached."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_dir / f".{version}-{uuid.uuid4().hex}.part"
        tmp.write_bytes(body)
        tmp.replace(cache_dir / f"{version}.json.gz")
        kept = sorted(cache_dir.glob("*.json.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in kept[_KEEP:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def office_router(ws_dep):
    from fastapi import APIRouter, HTTPException, Response

    from cycls._agent.design.store import version_of
    from cycls._agent.office import client as office
    from cycls._agent.web.shared import _safe_path
    from cycls._app.db import Workspace

    r = APIRouter()

    def _sheet_file(ws, path):
        if not path or not path.lower().endswith(SHEETS_EXTS):
            raise HTTPException(400, "path: an .xlsx or .xlsm file")
        file_path = _safe_path(ws.root, path)
        if not file_path.is_file():
            raise HTTPException(404, "There is no such file.")
        return file_path

    @r.get("/office/sheets")
    async def sheets(path: str, ws: Workspace = ws_dep):
        file_path = _sheet_file(ws, path)
        if not office.offered(ws, "sheets"):
            return {"editor": False, "reason": "off"}
        if file_path.stat().st_size > MAX_BYTES:
            return {"editor": False, "reason": "too-large"}
        return {"editor": True, "url": f"{office.editor_url()}/sheets/", "name": Path(path).name}

    @r.get("/office/sheets/open")
    async def sheets_open(path: str, ws: Workspace = ws_dep):
        file_path = _sheet_file(ws, path)
        if not office.offered(ws, "sheets"):
            raise HTTPException(403, "Cycls Sheets is not switched on for this workspace.")
        st = file_path.stat()
        if st.st_size > MAX_BYTES:
            raise HTTPException(413, f"The workbook is larger than {MAX_BYTES // (1024 * 1024)} MB.")
        data = await asyncio.to_thread(file_path.read_bytes)
        version = version_of(data)
        cache = Path(ws.root) / SHEETS_CACHE / f"{version}.json.gz"
        body = None
        if cache.is_file():
            try:
                body = await asyncio.to_thread(cache.read_bytes)
            except OSError:
                body = None
        if body is None:
            try:
                read = await office.read_xlsx(data, name=Path(path).stem)
            except office.Unavailable as e:
                raise HTTPException(503, str(e))
            except office.Refused as e:
                raise HTTPException(422, f"This workbook could not be opened: {e}")
            payload = {
                "version": version,
                "snapshot": read.get("workbook"),
                "notices": read.get("notices") or [],
                "activeSheet": read.get("activeSheet"),
                "stats": read.get("stats") or {},
            }
            body = gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6)
            await asyncio.to_thread(_write_cache, Path(ws.root) / SHEETS_CACHE, version, body)
        modified = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
        return Response(body, media_type="application/json", headers={
            "Content-Encoding": "gzip", "Cache-Control": "no-store", "X-Version": version, "X-Modified": modified,
        })

    return r

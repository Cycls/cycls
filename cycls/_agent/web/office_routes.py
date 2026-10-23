"""The routes behind the office editors in the canvas (Cycls Sheets; Cycls Docs later).

    GET /office/sheets?path=   may this workspace open the file in Cycls Sheets?
                               → {editor: true, url} or {editor: false, reason}

The browser frames the editor from `url`; whether an organisation has Sheets is answered here, per
workspace (SHEETS_ORGS), so the setting never leaks to the page. Opening the file's contents, saving
and the agent's edits join this router as the editor learns them.
"""
from pathlib import Path

SHEETS_EXTS = (".xlsx", ".xlsm")


def office_router(ws_dep):
    from fastapi import APIRouter, HTTPException

    from cycls._agent.office import client as office
    from cycls._agent.web.shared import _safe_path
    from cycls._app.db import Workspace

    r = APIRouter()

    @r.get("/office/sheets")
    async def sheets(path: str, ws: Workspace = ws_dep):
        if not path or not path.lower().endswith(SHEETS_EXTS):
            raise HTTPException(400, "path: an .xlsx or .xlsm file")
        file_path = _safe_path(ws.root, path)
        if not file_path.is_file():
            raise HTTPException(404, "There is no such file.")
        if not office.offered(ws, "sheets"):
            return {"editor": False, "reason": "off"}
        return {"editor": True, "url": f"{office.editor_url()}/sheets/", "name": Path(path).name}

    return r

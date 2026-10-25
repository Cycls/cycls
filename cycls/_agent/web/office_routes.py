"""The routes behind the office editors in the canvas (Cycls Sheets and Cycls Docs), the same for both:

    GET /office/<product>?path=        may this workspace open the file in that editor?
                                       → {editor: true, url, name} or {editor: false, reason}
    GET /office/<product>/open?path=   what the editor opens (gzip JSON):
                                       sheets {version, snapshot, notices, activeSheet, stats};
                                       docs {version, snapshot, notices, readonly, stats}
    GET /office/<product>/version?path=  the file's version now → {version, modified}
    PUT /office/<product>/save?path=&base=&force=
                                       the editor's snapshot (JSON, gzip) written back into the file: only
                                       what differs changes (patch-back on the service), the replaced
                                       version is kept → {version, unchanged, summary, modified}; 412
                                       {version} when the file changed since `base`

<product> is sheets (.xlsx, .xlsm) or docs (.docx). The browser frames the editor from `url`; whether an
organisation has it is answered here, per workspace (SHEETS_ORGS / DOCS_ORGS), so the setting never leaks to
the page. The service reads the file; what it read is kept beside the workspace's other caches
(.cache/<product>/<version>.json.gz), so opening the same file again costs nothing. A save goes through the
same versioned write as a design (design/store.py write_fig): the base check, the version history, one write
at a time per file.
"""
import asyncio
import gzip
import json
import uuid
from urllib.parse import unquote
from datetime import datetime, timezone
from pathlib import Path

SHEETS_EXTS = (".xlsx", ".xlsm")
DOCS_EXTS = (".docx",)
MAX_BYTES = 20 * 1024 * 1024     # larger files keep the read-only preview
MAX_SNAPSHOT = 64 * 1024 * 1024  # an editor's snapshot as sent (gzip)
GZIP_MAGIC = bytes([0x1F, 0x8B])
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


def edit_trail(header):
    """The editor's trail sent with a save (X-Edit-Trail: URI-encoded JSON list of short lines) -> at most 64 lines.
    The editor sends the first lines of a burst and the last ones; the start (what was selected) matters most."""
    if not header:
        return None
    try:
        lines = json.loads(unquote(header))
    except ValueError:
        return None
    if not isinstance(lines, list):
        return None
    return [str(line)[:120] for line in lines[:64]]


def office_router(ws_dep, required_auth=None, changed=None):
    from fastapi import APIRouter, Depends, HTTPException, Request, Response
    from fastapi.responses import JSONResponse

    from cycls._agent.design.store import Stale, read_fig, version_of, write_fig
    from cycls._agent.logs import log
    from cycls._agent.office import client as office
    from cycls._agent.web.shared import _safe_path, person
    from cycls._app.db import Workspace

    user_dep = required_auth if required_auth is not None else Depends(lambda: None)

    r = APIRouter()

    async def _read_sheets(data, name):
        read = await office.read_xlsx(data, name=name)
        return {"snapshot": read.get("workbook"), "notices": read.get("notices") or [],
                "activeSheet": read.get("activeSheet"), "stats": read.get("stats") or {}}

    async def _read_docs(data, name):
        read = await office.read_docx(data, name=name)
        out = {"snapshot": read.get("document"), "notices": read.get("notices") or [],
               "readonly": bool(read.get("readonly")), "stats": read.get("stats") or {}}
        # A document with tracked changes opens in review: the changes shown marked, and listed here for the
        # person to accept or reject (each by its Word ids; `other` = those with nothing to show in the text).
        changes = []
        for c in (read.get("changes") or [])[:300]:
            if not isinstance(c, dict) or not isinstance(c.get("ids"), list):
                continue
            item = {"ids": [str(i)[:20] for i in c["ids"][:400]], "author": str(c.get("author") or "")[:60],
                    "color": str(c.get("color") or "")[:9]}
            for k in ("inserted", "deleted"):
                if isinstance(c.get(k), str) and c[k]:
                    item[k] = c[k][:200]
            if isinstance(c.get("date"), str):
                item["date"] = c["date"][:30]
            for k in ("start", "end"):
                if isinstance(c.get(k), int) and not isinstance(c.get(k), bool):
                    item[k] = c[k]
            if c.get("other"):
                item["other"] = True
            changes.append(item)
        if changes:
            out["changes"] = changes
        return out

    products = {
        "sheets": {"exts": SHEETS_EXTS, "title": "Cycls Sheets", "noun": "workbook", "what": "an .xlsx or .xlsm file",
                   "read": _read_sheets, "patch": "patch_xlsx"},
        # docs reads are kept in their own folder since tracked changes open in review (2026-10-25): an older
        # read of such a file has no review in it.
        "docs": {"exts": DOCS_EXTS, "title": "Cycls Docs", "noun": "document", "what": "a .docx file",
                 "read": _read_docs, "patch": "patch_docx", "cache": ".cache/docs-review"},
    }

    def _add(product, p):
        noun, cache_dir = p["noun"], p.get("cache") or f".cache/{product}"

        def _file(ws, path):
            if not path or not path.lower().endswith(p["exts"]):
                raise HTTPException(400, f"path: {p['what']}")
            file_path = _safe_path(ws.root, path)
            if not file_path.is_file():
                raise HTTPException(404, "There is no such file.")
            return file_path

        def _on(ws):
            if not office.offered(ws, product):
                raise HTTPException(403, f"{p['title']} is not switched on for this workspace.")

        async def editor(path: str, ws: Workspace = ws_dep):
            file_path = _file(ws, path)
            if not office.offered(ws, product):
                return {"editor": False, "reason": "off"}
            if file_path.stat().st_size > MAX_BYTES:
                return {"editor": False, "reason": "too-large"}
            return {"editor": True, "url": f"{office.editor_url()}/{product}/", "name": Path(path).name}

        async def open_(path: str, ws: Workspace = ws_dep):
            file_path = _file(ws, path)
            _on(ws)
            st = file_path.stat()
            if st.st_size > MAX_BYTES:
                raise HTTPException(413, f"The {noun} is larger than {MAX_BYTES // (1024 * 1024)} MB.")
            data = await asyncio.to_thread(file_path.read_bytes)
            version = version_of(data)
            cache = Path(ws.root) / cache_dir / f"{version}.json.gz"
            body = None
            if cache.is_file():
                try:
                    body = await asyncio.to_thread(cache.read_bytes)
                except OSError:
                    body = None
            if body is None:
                try:
                    payload = {"version": version, **(await p["read"](data, Path(path).stem))}
                except office.Unavailable as e:
                    raise HTTPException(503, str(e))
                except office.Refused as e:
                    raise HTTPException(422, f"This {noun} could not be opened: {e}")
                body = gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6)
                await asyncio.to_thread(_write_cache, Path(ws.root) / cache_dir, version, body)
            modified = datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()
            return Response(body, media_type="application/json", headers={
                "Content-Encoding": "gzip", "Cache-Control": "no-store", "X-Version": version, "X-Modified": modified,
            })

        async def version_(path: str, ws: Workspace = ws_dep):
            """The file's version now (what a save names as its base): an open editor checks it after the file may
            have changed some other way, and takes the new file in (or asks, with unsaved changes)."""
            file_path = _file(ws, path)
            _on(ws)
            data = await asyncio.to_thread(file_path.read_bytes)
            modified = datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc).isoformat()
            return {"version": version_of(data), "modified": modified}

        async def save(path: str, request: Request, base: str = "", force: bool = False,
                       ws: Workspace = ws_dep, user=user_dep):
            file_path = _file(ws, path)
            _on(ws)
            body = await request.body()
            if not body:
                raise HTTPException(400, f"Send the {noun} (JSON, gzip).")
            if len(body) > MAX_SNAPSHOT:
                raise HTTPException(413, f"The {noun} sent is too large.")
            snapshot_gz = body if body[:2] == GZIP_MAGIC else gzip.compress(body, 6)
            rel = file_path.relative_to(Path(ws.root).resolve()).as_posix()
            trail = edit_trail(request.headers.get("x-edit-trail"))

            def logged(outcome, **fields):
                # Every save, with what it changed and what the editor did before it: a save that changed more
                # than the person meant can be traced (names and offsets only, never the document's text).
                summary = fields.pop("summary", None)
                if isinstance(summary, dict):
                    summary = {k: v for k, v in summary.items() if k != "notices"} | {"notices": len(summary.get("notices") or [])}
                log("office_save", user=user, product=product, path=rel[-160:], outcome=outcome, base=base or None,
                    force=force, bytes=len(body), summary=summary, trail=trail, **fields)
            from cycls._agent.design.deck import lock
            async with lock(file_path):     # one read → patch → write at a time per file
                data, version = await asyncio.to_thread(read_fig, ws.root, rel)
                if data is None:
                    raise HTTPException(404, "There is no such file.")
                if base and base != version and not force:
                    logged("stale", version=version)
                    return JSONResponse(status_code=412, content={
                        "detail": f"This {noun} changed since it was opened.", "version": version})
                try:
                    result = await getattr(office, p["patch"])(data, snapshot_gz)   # looked up per call (tests replace it)
                except office.Unavailable as e:
                    logged("unavailable", error=str(e)[:200])
                    raise HTTPException(503, str(e))
                except office.Refused as e:
                    logged("refused", error=str(e)[:200])
                    raise HTTPException(422, f"The {noun} could not be saved: {e}")
                if result["unchanged"]:
                    logged("unchanged", version=version, summary=result["summary"])
                    return {"version": version, "unchanged": True, "summary": result["summary"]}
                try:
                    new = await write_fig(ws.root, rel, result["bytes"], base=version, by="user",
                                          reason="keep" if force else "save", force=force, who=person(user, ws))
                except Stale as e:
                    logged("stale", version=e.current)
                    return JSONResponse(status_code=412, content={
                        "detail": f"This {noun} changed since it was opened.", "version": e.current})
                logged("written", version=new, replaced=version, summary=result["summary"])
            if changed is not None:
                changed(ws.root)
            # When it was written: the editor's "Last modified" follows its own saves.
            modified = datetime.fromtimestamp(file_path.stat().st_mtime, timezone.utc).isoformat()
            return {"version": new, "unchanged": False, "summary": result["summary"], "modified": modified}

        async def changes_(path: str, request: Request, ws: Workspace = ws_dep, user=user_dep):
            """A document's tracked changes accepted or rejected by the person: {base, action: accept | reject,
            ids?} (ids: some changes, as the review lists them; none: all). Written like a save, the replaced
            version kept; a file changed since it was opened is refused (412)."""
            file_path = _file(ws, path)
            _on(ws)
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                raise HTTPException(400, "Send {base, action: accept | reject, ids?}.")
            action = body.get("action") if isinstance(body, dict) else None
            if action not in ("accept", "reject"):
                raise HTTPException(400, "action is accept or reject.")
            base = str(body.get("base") or "")
            ids = body.get("ids")
            ids = [str(i)[:20] for i in ids[:2000]] if isinstance(ids, list) and ids else None
            rel = file_path.relative_to(Path(ws.root).resolve()).as_posix()
            op = {"op": f"{action}_changes", **({"ids": ids} if ids else {})}
            from cycls._agent.design.deck import lock
            async with lock(file_path):
                data, version = await asyncio.to_thread(read_fig, ws.root, rel)
                if data is None:
                    raise HTTPException(404, "There is no such file.")
                if base and base != version:
                    return JSONResponse(status_code=412, content={
                        "detail": f"This {noun} changed since it was opened.", "version": version})
                try:
                    result = await office.docs_apply(data, file_path.name, [op])
                except office.Unavailable as e:
                    raise HTTPException(503, str(e))
                except office.Refused as e:
                    raise HTTPException(422, str(e))
                if result["unchanged"] or not result["bytes"]:
                    return {"version": version, "unchanged": True}
                try:
                    new = await write_fig(ws.root, rel, result["bytes"], base=version, by="user",
                                          reason=f"{action} changes", who=person(user, ws))
                except Stale as e:
                    return JSONResponse(status_code=412, content={
                        "detail": f"This {noun} changed since it was opened.", "version": e.current})
            log("office_changes", user=user, path=rel[-160:], action=action, some=len(ids) if ids else None,
                version=new, replaced=version)
            if changed is not None:
                changed(ws.root)
            return {"version": new, "unchanged": False}

        r.add_api_route(f"/office/{product}", editor, methods=["GET"], name=f"office_{product}")
        r.add_api_route(f"/office/{product}/open", open_, methods=["GET"], name=f"office_{product}_open")
        r.add_api_route(f"/office/{product}/version", version_, methods=["GET"], name=f"office_{product}_version")
        r.add_api_route(f"/office/{product}/save", save, methods=["PUT"], name=f"office_{product}_save")
        if product == "docs":
            r.add_api_route("/office/docs/changes", changes_, methods=["POST"], name="office_docs_changes")

    for product, p in products.items():
        _add(product, p)
    return r

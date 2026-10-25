"""A thin client to the cycls-office service (Cycls Sheets, Cycls Docs).

Configured by the env an agent sets:
  OFFICE_URL         the service, https://cycls-office.cycls.ai
  OFFICE_SECRET      the key every API request carries (Authorization: Bearer)
  OFFICE_EDITOR_URL  where the browser loads the editors from; the same origin as OFFICE_URL unless set
  SHEETS_ORGS        who gets Cycls Sheets: organisation ids (or a person's id for a personal account),
                     comma separated. Empty means nobody, "*" everybody — setting a URL alone switches
                     nothing on for an agent that admits anyone who signs in.
  DOCS_ORGS          the same for Cycls Docs.

A redirect is never followed: the only host this client talks to is the one in OFFICE_URL.
"""
import os

import httpx

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
PRODUCTS = {"sheets": "SHEETS_ORGS", "docs": "DOCS_ORGS"}


class Unavailable(RuntimeError):
    """The service is not configured, unreachable, or refused the key."""


class Refused(RuntimeError):
    """The service read the request and said no: not an Excel file, too large, broken inside."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def configured():
    return bool(os.environ.get("OFFICE_URL"))


def editor_url():
    """The editors' origin as the browser sees it, without a trailing slash; None when not configured."""
    url = (os.environ.get("OFFICE_EDITOR_URL") or os.environ.get("OFFICE_URL") or "").strip().rstrip("/")
    return url or None


def _allowed(product):
    raw = os.environ.get(PRODUCTS[product], "")
    return {s.strip() for s in raw.replace(";", ",").split(",") if s.strip()}


def offered(workspace, product="sheets"):
    """Is this office product on for the workspace's organisation (or person)? The URL alone does not
    switch it on."""
    if product not in PRODUCTS or not configured() or not editor_url():
        return False
    allowed = _allowed(product)
    if "*" in allowed:
        return True
    subject = str(getattr(workspace, "subject", "") or "")
    org, _, user = subject.partition(":")
    return bool(allowed & {org, user, getattr(workspace, "ws", None)} - {"", None})


def _base():
    url = (os.environ.get("OFFICE_URL") or "").strip().rstrip("/")
    if not url:
        raise Unavailable("Office is not configured (OFFICE_URL)")
    return url


def _headers():
    h = {"Accept": "application/json"}
    if secret := os.environ.get("OFFICE_SECRET"):
        h["Authorization"] = f"Bearer {secret}"
    return h


async def _call(method, path, headers_extra=None, **kw):
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            r = await client.request(method, f"{_base()}{path}", headers={**_headers(), **(headers_extra or {})}, **kw)
    except httpx.HTTPError as e:
        raise Unavailable(f"the office service is unreachable ({type(e).__name__})") from e
    if r.status_code in (401, 403):
        raise Unavailable("the office service refused the key (OFFICE_SECRET)")
    if r.status_code >= 500 or r.is_redirect:
        raise Unavailable(f"the office service answered {r.status_code}")
    return r


async def health():
    """What the service runs: its version, the engine release and patches, the editors it has."""
    r = await _call("GET", "/health")
    return r.json()


async def smoke():
    """The engine's own check, run on the service: a workbook opened, computed, edited and recomputed."""
    r = await _call("POST", "/v1/engine/smoke")
    return r.json()


def _refused(r):
    try:
        message = r.json().get("error") or r.text
    except ValueError:
        message = r.text
    return Refused(str(message)[:300] or f"the office service answered {r.status_code}", r.status_code)


async def patch_xlsx(original, snapshot_gz):
    """The original .xlsx and the editor's workbook (gzip JSON) → {unchanged, bytes, summary}.
    Only what differs is written into the file; `bytes` is None when nothing does."""
    r = await _call("POST", "/v1/xlsx/patch", files={
        "file": ("workbook.xlsx", bytes(original), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "snapshot": ("snapshot.json.gz", bytes(snapshot_gz), "application/gzip"),
    })
    if r.status_code >= 400:
        raise _refused(r)
    if r.headers.get("content-type", "").startswith("application/json"):
        body = r.json()
        return {"unchanged": True, "bytes": None, "summary": body.get("summary") or {}}
    summary = {}
    if raw := r.headers.get("x-patch-summary"):
        import base64
        import json
        try:
            summary = json.loads(base64.b64decode(raw))
        except ValueError:
            summary = {}
    return {"unchanged": False, "bytes": r.content, "summary": summary}


async def read_xlsx(data, name=None):
    """An .xlsx file's bytes → {workbook, notices, activeSheet, stats}: what Cycls Sheets opens."""
    params = {"name": name} if name else None
    r = await _call("POST", "/v1/xlsx/read", content=bytes(data), params=params,
                    headers_extra={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    if r.status_code >= 400:
        raise _refused(r)
    return r.json()


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def sheets_read(data, name, target=None, raw=False, max_chars=None):
    """The agent's read: the workbook outlined and a sheet or range as a grid (formulas → values)."""
    import json
    request = {"name": name, "target": target, "raw": bool(raw)}
    if max_chars:
        request["maxChars"] = int(max_chars)
    r = await _call("POST", "/v1/sheets/read", files={
        "file": (name or "workbook.xlsx", bytes(data), _XLSX),
        "request": ("request.json", json.dumps(request, ensure_ascii=False).encode(), "application/json"),
    })
    if r.status_code >= 400:
        raise _refused(r)
    return r.json()["text"]


async def sheets_apply(data, name, edits, create=None):
    """The agent's edits run through the engine and written into the file →
    {unchanged, bytes, mutations, ops, report}. `create` ({sheet?, rightToLeft?}) starts a new workbook
    and needs no `data`."""
    import base64
    import json
    request = {"name": name, "edits": list(edits or [])}
    if create is not None:
        request["create"] = create
    files = {"request": ("request.json", json.dumps(request, ensure_ascii=False).encode(), "application/json")}
    if data is not None:
        files["file"] = (name or "workbook.xlsx", bytes(data), _XLSX)
    r = await _call("POST", "/v1/sheets/apply", files=files)
    if r.status_code >= 400:
        raise _refused(r)
    body = r.json()
    return {"unchanged": bool(body.get("unchanged")),
            "bytes": base64.b64decode(body["file"]) if body.get("file") else None,
            "mutations": body.get("mutations") or [], "ops": body.get("ops") or [],
            "report": body.get("report") or ""}


_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def docs_read(data, name, start=None, max_chars=None):
    """The agent's read of a Word document: numbered paragraphs (¶7·k3f) and tables as grids."""
    import json
    request = {"name": name}
    if start:
        request["from"] = int(start)
    if max_chars:
        request["maxChars"] = int(max_chars)
    r = await _call("POST", "/v1/docs/read", files={
        "file": (name or "document.docx", bytes(data), _DOCX),
        "request": ("request.json", json.dumps(request, ensure_ascii=False).encode(), "application/json"),
    })
    if r.status_code >= 400:
        raise _refused(r)
    return r.json()["text"]


async def docs_apply(data, name, ops, create=None):
    """The agent's edits made and written into the file (all or none) → {unchanged, bytes, report}.
    `create` ({content, rtl?}) makes a new document from markdown and needs no `data`."""
    import base64
    import json
    request = {"name": name, "ops": list(ops or [])}
    if create is not None:
        request["create"] = create
    files = {"request": ("request.json", json.dumps(request, ensure_ascii=False).encode(), "application/json")}
    if data is not None:
        files["file"] = (name or "document.docx", bytes(data), _DOCX)
    r = await _call("POST", "/v1/docs/apply", files=files)
    if r.status_code >= 400:
        raise _refused(r)
    body = r.json()
    return {"unchanged": bool(body.get("unchanged")),
            "bytes": base64.b64decode(body["file"]) if body.get("file") else None,
            "report": body.get("report") or ""}

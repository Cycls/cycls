"""Thin HTTP client to the shared, stateless design service (cycls-design), like office-render.
DESIGN_URL turns it on (unset: no Design tool); DESIGN_SECRET is the optional Bearer secret."""
import asyncio
import base64
import hashlib
import os
import pathlib
from typing import NamedTuple

import httpx

_TIMEOUT = 240  # seconds — a whole deck (PPTX / PDF) may take a few minutes


# a service deploy drops or 502s in-flight requests; retry those (stateless), never a timeout or a real answer
_RETRY_WAITS = (1, 3)       # seconds before the second and the third try
_GONE = (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


class Unavailable(RuntimeError):
    """The design service is unreachable or not configured; callers degrade instead of failing."""


def configured():
    """Wired when DESIGN_URL is set; DESIGN_SECRET is optional."""
    return bool(os.environ.get("DESIGN_URL"))


def _headers(user_id=None):
    h = {}
    if secret := os.environ.get("DESIGN_SECRET"):
        h["Authorization"] = f"Bearer {secret}"
    if user_id:
        h["X-User-Id"] = str(user_id)   # attribution/quota, not auth
    return h


async def _post(path, body, user_id=None):
    url = os.environ.get("DESIGN_URL")
    if not url:
        raise Unavailable("design not configured (DESIGN_URL)")
    gone = None
    for wait in (0, *_RETRY_WAITS):
        if wait:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(f"{url.rstrip('/')}{path}", headers=_headers(user_id), json=body)
        except _GONE as e:
            gone = e
            continue
        except httpx.HTTPError as e:
            raise Unavailable(f"design service unreachable: {e}") from e
        try:
            data = resp.json()
        except Exception:
            data = None
        if resp.status_code in (502, 503, 504) and not (isinstance(data, dict) and "ok" in data):
            gone = RuntimeError(f"design service {resp.status_code} (no answer from the service itself)")
            continue
        break
    else:
        raise Unavailable(f"design service unreachable after {1 + len(_RETRY_WAITS)} tries: {gone}") from gone
    if resp.status_code == 401:
        raise Unavailable("design service rejected the secret (DESIGN_SECRET)")
    if resp.status_code != 200 or not (isinstance(data, dict) and data.get("ok")):
        # the platform's front end may refuse a request (413/429) before the service sees it: no JSON
        detail = data.get("error") if isinstance(data, dict) else None
        if not detail and resp.status_code == 413:
            detail = "the design request is too large — use smaller or fewer images"
        if not detail and resp.status_code == 429:
            detail = "too many design requests — wait a moment and try again"
        raise RuntimeError(detail or f"design service {resp.status_code}: {resp.text[:200]}")
    return data


_given = {}        # a font file's sha256 → its face as the service named it, or why it can't be used (this process)


async def give_font(path, user_id=None):
    """A font file given to the service — its sha256 first, the file itself only if the service never had it →
    (its face {"family", "style"}, or why it can't be used; new to this process?). Unavailable passes."""
    data = await asyncio.to_thread(pathlib.Path(path).read_bytes)
    if (sha := hashlib.sha256(data).hexdigest()) in _given:
        return _given[sha], False
    try:
        r = await _post("/fonts", {"sha": sha}, user_id)
        if r.get("need"):                               # a file the service has never had: sent once, ever
            r = await _post("/fonts", {"sha": sha, "data": base64.b64encode(data).decode()}, user_id)
        _given[sha] = {"family": r["family"], "style": r["style"]}
    except Unavailable:
        raise
    except RuntimeError as e:                           # the service read it and said no: not asked again
        _given[sha] = str(e)
    return _given[sha], True


async def add_fonts(root, user_id=None):
    """A workspace's brand fonts (brand/fonts/*.ttf|.otf) given to the service: its designs, PDFs and editor draw
    with them from then on → what was newly given, said for the model ('' for nothing)."""
    faces, bad = {}, []
    for p in sorted(pathlib.Path(root, "brand", "fonts").glob("*")):
        if p.suffix.lower() not in (".ttf", ".otf"):
            continue
        try:
            got, new = await give_font(p, user_id)
        except Unavailable:
            continue                                    # given on a later call
        if new and isinstance(got, dict):
            faces.setdefault(got["family"], []).append(got["style"])
        elif new:
            bad.append(f"brand/fonts/{p.name} ({got})")
    ready = "; ".join(f"{f} ({', '.join(s)})" for f, s in faces.items())
    return " ".join(filter(None, [f"The workspace's own fonts are ready for designs: {ready}. Name them by that family." if ready else "",
                                  f"Not usable as fonts: {'; '.join(bad)}." if bad else ""]))


class Rendered(NamedTuple):
    """A render. `image` is the output (pptx/pdf: the whole deck, else the first frame), `fig` the editable
    source, `preview`/`previews` @1x JPEGs for QA, `lint` [{frame, node, issue, fix}], `pages` [{name, frames}].
    `hashes` are frame fingerprints to send back as `known`; `preview_of` is then the differing frames (None: all)."""
    image: bytes
    fig: bytes
    frame_id: object
    fmt: object
    preview: object
    notes: list
    lint: list
    previews: list
    images: list
    slides: list
    dir: object = None
    pages: list = []
    page_images: list = []
    preview_pages: list = []
    size: object = None
    sheets: list = []
    sheet_pages: list = []
    hashes: list = []
    preview_of: object = None


def _b64s(values):
    return [base64.b64decode(v) for v in values or [] if isinstance(v, str)]


def _pages(data):
    """A reply's pages → [{name, frames}]."""
    return [{"name": str(p.get("name") or ""), "frames": int(p.get("frames") or 0)}
            for p in data.get("pages") or [] if isinstance(p, dict)]


def _kept(data):
    """Our record of a design, as the .fig keeps it (render's `keep`) → a dict ({} when it has none)."""
    return data.get("keep") if isinstance(data.get("keep"), dict) else {}


def _paged(body, page):
    """`page` — a page's name, or its place from 0 — onto a request (none: the first)."""
    if page is not None and page != "":
        body["page"] = page
    return body


def _decode(data):
    """Service JSON → a Rendered."""
    return Rendered(
        base64.b64decode(data["image_base64"]),
        base64.b64decode(data["fig_base64"]),
        data.get("frameId"), data.get("format"),
        base64.b64decode(data["preview_base64"]) if data.get("preview_base64") else None,
        [str(n) for n in data.get("notes") or []],
        [dict(i) for i in data.get("lint") or [] if isinstance(i, dict)],
        _b64s(data.get("previews_base64")),
        _b64s(data.get("images_base64")),
        [dict(i) for i in data.get("slides") or [] if isinstance(i, dict)],
        data.get("dir") if data.get("dir") in ("ltr", "rtl") else None,
        _pages(data),
        _b64s(data.get("page_images_base64")),
        [str(p) for p in data.get("preview_pages") or []],
        list(data["size"]) if isinstance(data.get("size"), list) and len(data["size"]) == 2 else None,
        _b64s(data.get("sheets_base64")),
        [[int(p[0]), int(p[1])] for p in data.get("sheet_pages") or [] if isinstance(p, list) and len(p) == 2],
        [str(h) for h in data.get("page_hashes") or []],
        [int(n) for n in data["preview_of"]] if isinstance(data.get("preview_of"), list) else None)


async def render(spec, fmt="png", scale=2, user_id=None, every=False, sheets=False, known=None, lead=None, keep=None):
    """Render a spec (`{size, fill, nodes}`, `{frames}` or `{pages}`) → a Rendered. `every`: every frame
    in a raster `fmt`; `sheets`: contact sheets past twelve frames; `known`: previews of changed frames only;
    `keep`: our record of the design (`kind`, a deck's settings, a document's source), kept in the .fig."""
    body = {"spec": spec, "format": fmt, "scale": scale, "preview": True}
    if keep:
        body["keep"] = keep
    if every:
        body["every"] = True
    if sheets:
        body["sheets"] = True
    if lead:
        body["lead"] = int(lead)      # how many of the first frames to read whole (4 unless said)
    if known:
        body["known"] = list(known)
    return _decode(await _post("/render", body, user_id))


async def apply(fig, script=None, user_id=None, ops=None, preview=False, page=None):
    """Edit a `.fig` headless by `ops` or a raw plugin-API `script` → {fig, lint, script, preview, …};
    `script` is what the live editor replays. A failing edit raises RuntimeError with the service's error."""
    body = _paged({"fig": base64.b64encode(fig).decode()}, page)
    if ops is not None:
        body["ops"] = ops
    else:
        body["script"] = script
    if preview:
        body["preview"] = True
    data = await _post("/apply", body, user_id)
    return {"fig": base64.b64decode(data["fig_base64"]),
            "lint": [dict(i) for i in data.get("lint") or [] if isinstance(i, dict)],
            "script": data.get("script"),
            "preview": base64.b64decode(data["preview_base64"]) if data.get("preview_base64") else None,
            "previews": _b64s(data.get("previews_base64")),
            "touched": [int(i) for i in data.get("touched") or [] if isinstance(i, int)],
            "slides": [dict(s) for s in data.get("slides") or [] if isinstance(s, dict)],
            "pages": _pages(data), "page": str(data.get("page") or ""), "started": str(data.get("started") or ""),
            # resolved: [what was asked, the part it was] for a name that wasn't one
            "changed": [str(n) for n in data.get("changed") or [] if isinstance(n, str)],
            "added": [str(n) for n in data.get("added") or [] if isinstance(n, str)],
            "resolved": [[str(p[0]), str(p[1])] for p in data.get("resolved") or []
                         if isinstance(p, list) and len(p) == 2],
            "notes": [str(n) for n in data.get("notes") or [] if isinstance(n, str)],
            "keep": _kept(data)}


async def outline(fig, user_id=None, page=None, full=False):
    """One page of a `.fig` → {frames: [{slide, name, size, nodes}], pages, page}: nodes by name, measured.
    `full`: every text whole, not its first lines."""
    data = await _post("/inspect", _paged({"fig": base64.b64encode(fig).decode(), **({"full": True} if full else {})}, page), user_id)
    return {"frames": data.get("frames") or [], "pages": _pages(data), "page": str(data.get("page") or ""), "keep": _kept(data)}


async def inspect(fig, user_id=None, page=None):
    """`outline`'s frames alone."""
    return (await outline(fig, user_id=user_id, page=page))["frames"]


async def export(fig, fmt="png", scale=2, width=None, user_id=None, every=False, page=None):
    """Re-export a `.fig` → image bytes (pptx/pdf: the whole deck). `width` (the old image's) keeps its
    resolution; `every` → a list of every frame."""
    data = await _export(fig, fmt, scale, width, user_id, every, page)
    if every:
        return _b64s(data.get("images_base64"))
    return base64.b64decode(data["image_base64"])


async def export_page(fig, page, fmt="png", scale=2, width=None, user_id=None):
    """One page as `fmt` → (bytes, pages, its name); a missing page raises RuntimeError naming the rest."""
    data = await _export(fig, fmt, scale, width, user_id, False, page)
    return base64.b64decode(data["image_base64"]), _pages(data), str(data.get("page") or "")


async def _export(fig, fmt, scale, width, user_id, every, page):
    body = _paged({"fig": base64.b64encode(fig).decode(), "format": fmt, "scale": scale}, page)
    if width:
        body["width"] = width
    if every:
        body["every"] = True
    return await _post("/export", body, user_id)


async def evaluate(script, fmt="png", scale=2, user_id=None, keep=None):
    """Escape hatch: run a raw plugin-API script (it must log `__FRAME__<id>`) → a Rendered."""
    return _decode(await _post("/eval", {"script": script, "format": fmt, "scale": scale, "preview": True,
                                         **({"keep": keep} if keep else {})}, user_id))


async def slides(fig, scale=1, fmt="jpg", user_id=None, page=None, fit=None):
    """One page of a deck, slide by slide → {images, sizes, meta, format, pages, page, keep}, for the deck viewer.
    `fit`: the scale that sets the first slide's long side at that many pixels (at most 2×), instead of `scale`."""
    body = _paged({"fig": base64.b64encode(fig).decode(), "scale": scale, "format": fmt, **({"fit": fit} if fit else {})}, page)
    data = await _post("/slides", body, user_id)
    return {"images": _b64s(data.get("slides")),
            "sizes": [list(s) for s in data.get("sizes") or []],
            "meta": [dict(m) for m in data.get("meta") or [] if isinstance(m, dict)],
            "format": data.get("format") or fmt,
            "pages": _pages(data), "page": str(data.get("page") or ""), "keep": _kept(data)}

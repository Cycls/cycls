"""Design generation for Cycls agents, via a shared headless design service.

Agents produce social-media posts and slides WITHOUT shipping a design engine:
the heavy engine (OpenPencil, headless on Bun/CanvasKit) runs in ONE shared
service — cycls-design — and this module is a thin HTTP client. Same split as
office-render and the browser tool: the SDK ships the client, the service is
deployed once.

Configured by env an agent sets to use the service:
  DESIGN_URL     the service base URL (e.g. https://cycls-design.cycls.ai)
Optional:
  DESIGN_SECRET  shared service secret (Bearer) — set by a deployed service,
                 omitted for a local open dev instance.

If DESIGN_URL is unset the feature is simply off: `configured()` is False and the
`Design` tool is never offered, so the agent degrades to "designing isn't
configured" instead of crashing — exactly the office-render behaviour.

The service is stateless: it takes a spec (or a raw script) and returns the
rendered image plus the editable `.fig` source. State (the saved files) lives in
the calling agent's workspace, so there is nothing to keep in sync here.
"""
import asyncio
import base64
import os
from typing import NamedTuple

import httpx

# A render shells the CanvasKit engine on the service; give it headroom, but
# well under a page-timeout so a hung service surfaces as an error, not a stall.
_TIMEOUT = 240  # seconds — a whole deck (PPTX / PDF) may take a few minutes


# A deploy of the service is not a failed render. For a few minutes after one, its
# instances are swapped under the requests in flight: a connection is dropped with no
# answer, or refused, or the platform's front end answers 502 / 503 for a service that
# isn't there yet. The same request a moment later is served — so it is made again,
# twice at most. (The service keeps no state: a request made twice changes nothing.)
# Not tried again: a timeout — a render that takes too long would take as long again —
# and anything the service itself answered.
_RETRY_WAITS = (1, 3)       # seconds before the second and the third try
_GONE = (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


class Unavailable(RuntimeError):
    """Raised when the design service is unreachable or not configured, so the
    caller degrades gracefully instead of a hard error."""


def configured():
    """Wired when a service URL is set. The secret is optional (a local dev
    instance may run open); a deployed service sets one and rejects calls without
    it, surfaced as `Unavailable` at call time."""
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
        # A well-formed failure carries {ok:false,error}; anything else is raw. A
        # request over the size cap can be refused by the platform's front end
        # before the service sees it (no JSON), so that one is named here too.
        detail = data.get("error") if isinstance(data, dict) else None
        if not detail and resp.status_code == 413:
            detail = "the design request is too large — use smaller or fewer images"
        if not detail and resp.status_code == 429:
            detail = "too many design requests — wait a moment and try again"
        raise RuntimeError(detail or f"design service {resp.status_code}: {resp.text[:200]}")
    return data


class Rendered(NamedTuple):
    """A render. `image` is the output — a deck's whole file for pptx / pdf, else the
    first frame; `images` every frame in the format when asked (a carousel). `fig`
    is the editable source. `preview` / `previews` are small @1x JPEGs of the first /
    every frame — what the agent looks at to QA it (None / [] from a service that
    predates them). `notes` are what the service changed to make it render (a font
    swapped for its open twin, a weight the family lacks, a headline shrunk to fit) —
    lines for the agent's ack. `lint` is the layout check: [{frame, node, issue, fix}].
    `slides` is each frame's deck metadata: [{name, title?, notes?, transition?}].
    `dir` is a deck of layouts' direction ("ltr" / "rtl"), which its bilingual slides
    follow — kept so a later slide op lays out the same way (None for anything else).
    `pages` is the design's pages — its variants — in order: [{name, frames}]; with more
    than one, `page_images` is each page's own image (its first frame) and
    `preview_pages` whose page each of `previews` is. `size` is a document's paper,
    [W, H] in pixels (None for anything else). `sheets` are contact sheets — a long
    document's pages past its previews, twelve to a JPEG — and `sheet_pages` the
    [first, last] page each one holds ([] unless asked for, and past twelve pages)."""
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


def _b64s(values):
    return [base64.b64decode(v) for v in values or [] if isinstance(v, str)]


def _pages(data):
    """A reply's pages → [{name, frames}]."""
    return [{"name": str(p.get("name") or ""), "frames": int(p.get("frames") or 0)}
            for p in data.get("pages") or [] if isinstance(p, dict)]


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
        [[int(p[0]), int(p[1])] for p in data.get("sheet_pages") or [] if isinstance(p, list) and len(p) == 2])


async def render(spec, fmt="png", scale=2, user_id=None, every=False, sheets=False):
    """Render a declarative design spec → a Rendered. `spec` is `{size:[w,h], fill,
    nodes:[...]}`, a deck `{frames:[...]}`, or several pages `{pages:[{name, size, fill,
    nodes}]}` — one design, a variant a page (see the Design tool description);
    `every` asks for every frame in a raster `fmt` (a carousel's slides); `sheets` asks,
    past twelve frames, for previews of the first four and the rest on contact sheets."""
    body = {"spec": spec, "format": fmt, "scale": scale, "preview": True}
    if every:
        body["every"] = True
    if sheets:
        body["sheets"] = True
    return _decode(await _post("/render", body, user_id))


async def apply(fig, script=None, user_id=None, ops=None, preview=False, page=None):
    """Edit a saved `.fig` (bytes) with the editor's own plugin API, headless — by
    `ops` (named operations: set_text, style, move, …) or a raw plugin-API `script` →
    a dict: `fig` (the edited document), `lint` (the layout check of the result),
    `script` (for ops, the compiled script the live editor replays; else None) and
    `preview` (a @1x JPEG of the first frame, when asked). A failing edit raises
    RuntimeError carrying its own error (e.g. 'no node named "cta" — this design
    has: …' or "null is not an object …"). `page` is the page it is made on (a name;
    the first when absent): the dict's `started` names it, `page` the one the edit
    ended on (a page op may have made another) and `pages` all of them."""
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
            # The slides the edit touched (0-based) and their previews; every slide's
            # metadata after it (its count is the deck's).
            "previews": _b64s(data.get("previews_base64")),
            "touched": [int(i) for i in data.get("touched") or [] if isinstance(i, int)],
            "slides": [dict(s) for s in data.get("slides") or [] if isinstance(s, dict)],
            "pages": _pages(data), "page": str(data.get("page") or ""), "started": str(data.get("started") or "")}


async def outline(fig, user_id=None, page=None, full=False):
    """One page of a saved `.fig` → {"frames": [{slide, name, size, fill?, nodes: [{name,
    type, x, y, w, h, text?, font?, size?, color?, fill?, radius?, …}]}], "pages":
    [{name, frames}], "page": its name} — the page's frames and their nodes by name,
    measured, for edits that name nodes which exist. `page` is a name or a place from
    0; the first when absent. `full`: every text whole, not its first lines — to compare
    two saves of a design word for word."""
    data = await _post("/inspect", _paged({"fig": base64.b64encode(fig).decode(), **({"full": True} if full else {})}, page), user_id)
    return {"frames": data.get("frames") or [], "pages": _pages(data), "page": str(data.get("page") or "")}


async def inspect(fig, user_id=None, page=None):
    """`outline`'s frames alone."""
    return (await outline(fig, user_id=user_id, page=page))["frames"]


async def export(fig, fmt="png", scale=2, width=None, user_id=None, every=False, page=None):
    """Re-export an edited `.fig` (bytes) → image bytes (pptx / pdf: the whole deck).
    `width`, the old image's pixel width, keeps its resolution (the service derives
    the scale from it). `every` → a list: every frame in `fmt` (a carousel's slides),
    `width` being the first one's. `page` is the page exported — a name, or a place
    from 0; the first when absent."""
    data = await _export(fig, fmt, scale, width, user_id, every, page)
    if every:
        return _b64s(data.get("images_base64"))
    return base64.b64decode(data["image_base64"])


async def export_page(fig, page, fmt="png", scale=2, width=None, user_id=None):
    """One page of a design as `fmt` → (bytes, the design's pages [{name, frames}], that
    page's name). A page that isn't there is a RuntimeError naming the ones that are."""
    data = await _export(fig, fmt, scale, width, user_id, False, page)
    return base64.b64decode(data["image_base64"]), _pages(data), str(data.get("page") or "")


async def _export(fig, fmt, scale, width, user_id, every, page):
    body = _paged({"fig": base64.b64encode(fig).decode(), "format": fmt, "scale": scale}, page)
    if width:
        body["width"] = width
    if every:
        body["every"] = True
    return await _post("/export", body, user_id)


async def evaluate(script, fmt="png", scale=2, user_id=None):
    """Escape hatch: run a raw OpenPencil/Figma-API script (it must log
    `__FRAME__<id>`) → a Rendered."""
    return _decode(await _post("/eval", {"script": script, "format": fmt, "scale": scale, "preview": True}, user_id))


async def slides(fig, scale=1, fmt="jpg", user_id=None, page=None):
    """A saved deck (`.fig` bytes), slide by slide → {"images": [bytes], "sizes":
    [[w, h]], "meta": [{name, title?, notes?, transition?}], "pages": [{name, frames}],
    "page": its name} — what the deck viewer shows and presents: one page's slides
    (`page`, a name or a place from 0; the first when absent)."""
    body = _paged({"fig": base64.b64encode(fig).decode(), "scale": scale, "format": fmt}, page)
    data = await _post("/slides", body, user_id)
    return {"images": _b64s(data.get("slides")),
            "sizes": [list(s) for s in data.get("sizes") or []],
            "meta": [dict(m) for m in data.get("meta") or [] if isinstance(m, dict)],
            "format": data.get("format") or fmt,
            "pages": _pages(data), "page": str(data.get("page") or "")}

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
import base64
import os
from typing import NamedTuple

import httpx

# A render shells the CanvasKit engine on the service; give it headroom, but
# well under a page-timeout so a hung service surfaces as an error, not a stall.
_TIMEOUT = 240  # seconds — a whole deck (PPTX / PDF) may take a few minutes


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
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{url.rstrip('/')}{path}", headers=_headers(user_id), json=body)
    except httpx.HTTPError as e:
        raise Unavailable(f"design service unreachable: {e}") from e
    if resp.status_code == 401:
        raise Unavailable("design service rejected the secret (DESIGN_SECRET)")
    try:
        data = resp.json()
    except Exception:
        data = None
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
    follow — kept so a later slide op lays out the same way (None for anything else)."""
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


def _b64s(values):
    return [base64.b64decode(v) for v in values or [] if isinstance(v, str)]


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
        data.get("dir") if data.get("dir") in ("ltr", "rtl") else None)


async def render(spec, fmt="png", scale=2, user_id=None, every=False):
    """Render a declarative design spec → a Rendered. `spec` is `{size:[w,h], fill,
    nodes:[...]}` or a deck `{frames:[...]}` (see the Design tool description);
    `every` asks for every frame in a raster `fmt` (a carousel's slides)."""
    body = {"spec": spec, "format": fmt, "scale": scale, "preview": True}
    if every:
        body["every"] = True
    return _decode(await _post("/render", body, user_id))


async def apply(fig, script=None, user_id=None, ops=None, preview=False):
    """Edit a saved `.fig` (bytes) with the editor's own plugin API, headless — by
    `ops` (named operations: set_text, style, move, …) or a raw plugin-API `script` →
    a dict: `fig` (the edited document), `lint` (the layout check of the result),
    `script` (for ops, the compiled script the live editor replays; else None) and
    `preview` (a @1x JPEG of the first frame, when asked). A failing edit raises
    RuntimeError carrying its own error (e.g. 'no node named "cta" — this design
    has: …' or "null is not an object …")."""
    body = {"fig": base64.b64encode(fig).decode()}
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
            "slides": [dict(s) for s in data.get("slides") or [] if isinstance(s, dict)]}


async def inspect(fig, user_id=None):
    """A saved `.fig`'s outline → [{slide, name, size, fill?, nodes: [{name, type, x,
    y, w, h, text?, font?, size?, color?, fill?, radius?, …}]}] — every frame and its
    nodes by name, measured, for edits that name nodes which exist."""
    data = await _post("/inspect", {"fig": base64.b64encode(fig).decode()}, user_id)
    return data.get("frames") or []


async def export(fig, fmt="png", scale=2, width=None, user_id=None, every=False):
    """Re-export an edited `.fig` (bytes) → image bytes (pptx / pdf: the whole deck).
    `width`, the old image's pixel width, keeps its resolution (the service derives
    the scale from it). `every` → a list: every frame in `fmt` (a carousel's slides),
    `width` being the first one's."""
    body = {"fig": base64.b64encode(fig).decode(), "format": fmt, "scale": scale}
    if width:
        body["width"] = width
    if every:
        body["every"] = True
    data = await _post("/export", body, user_id)
    if every:
        return _b64s(data.get("images_base64"))
    return base64.b64decode(data["image_base64"])


async def evaluate(script, fmt="png", scale=2, user_id=None):
    """Escape hatch: run a raw OpenPencil/Figma-API script (it must log
    `__FRAME__<id>`) → a Rendered."""
    return _decode(await _post("/eval", {"script": script, "format": fmt, "scale": scale, "preview": True}, user_id))


async def slides(fig, scale=1, fmt="jpg", user_id=None):
    """A saved deck (`.fig` bytes), slide by slide → {"images": [bytes], "sizes":
    [[w, h]], "meta": [{name, title?, notes?, transition?}]} — what the deck viewer
    shows and presents."""
    data = await _post("/slides", {"fig": base64.b64encode(fig).decode(), "scale": scale, "format": fmt}, user_id)
    return {"images": _b64s(data.get("slides")),
            "sizes": [list(s) for s in data.get("sizes") or []],
            "meta": [dict(m) for m in data.get("meta") or [] if isinstance(m, dict)],
            "format": data.get("format") or fmt}

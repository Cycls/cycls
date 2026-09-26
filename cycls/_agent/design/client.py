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

import httpx

# A render shells the CanvasKit engine on the service; give it headroom, but
# well under a page-timeout so a hung service surfaces as an error, not a stall.
_TIMEOUT = 120  # seconds


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
        # A well-formed failure carries {ok:false,error}; anything else is raw.
        detail = data.get("error") if isinstance(data, dict) else None
        raise RuntimeError(detail or f"design service {resp.status_code}: {resp.text[:200]}")
    return data


def _decode(data):
    """Service JSON → (image_bytes, fig_bytes, frame_id, format, preview_bytes).
    The preview — a small @1x JPEG of the first frame, what the agent looks at to
    QA its render — is None from a service that predates it."""
    return (base64.b64decode(data["image_base64"]),
            base64.b64decode(data["fig_base64"]),
            data.get("frameId"), data.get("format"),
            base64.b64decode(data["preview_base64"]) if data.get("preview_base64") else None)


async def render(spec, fmt="png", scale=2, user_id=None):
    """Render a declarative design spec → (image_bytes, fig_bytes, frame_id, fmt,
    preview_bytes). `spec` is `{size:[w,h], fill, nodes:[...]}` (see the Design
    tool description)."""
    return _decode(await _post("/render", {"spec": spec, "format": fmt, "scale": scale, "preview": True}, user_id))


async def apply(fig, script, user_id=None):
    """Run an `edit` script on a `.fig` (bytes) with the editor's own plugin API →
    the edited `.fig` bytes. A script that throws raises RuntimeError carrying the
    script's error (e.g. "null is not an object …")."""
    data = await _post("/apply", {"fig": base64.b64encode(fig).decode(), "script": script}, user_id)
    return base64.b64decode(data["fig_base64"])


async def export(fig, fmt="png", scale=2, width=None, user_id=None):
    """Re-export an edited `.fig` (bytes) → image bytes. `width`, the old image's
    pixel width, keeps its resolution (the service derives the scale from it)."""
    body = {"fig": base64.b64encode(fig).decode(), "format": fmt, "scale": scale}
    if width:
        body["width"] = width
    return base64.b64decode((await _post("/export", body, user_id))["image_base64"])


async def evaluate(script, fmt="png", scale=2, user_id=None):
    """Escape hatch: run a raw OpenPencil/Figma-API script (it must log
    `__FRAME__<id>`) → (image_bytes, fig_bytes, frame_id, fmt, preview_bytes)."""
    return _decode(await _post("/eval", {"script": script, "format": fmt, "scale": scale, "preview": True}, user_id))

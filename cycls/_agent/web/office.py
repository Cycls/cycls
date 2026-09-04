"""Office → PDF for the canvas, via the shared office-render service.

Word, PowerPoint and Excel files can't render in a browser, but a faithful PDF
can — and the canvas already has a first-class PDF viewer. So the file route
converts an Office document to PDF on demand and serves that; the client shows
it through the viewer it already has.

The conversion itself is LibreOffice, which is ~1GB and used by a minority of
turns — so it lives in ONE shared service (`office-render`, deployed at
https://office-render.cycls.ai), not baked into every agent image. This module
is a thin client of that service's versioned `/v1/convert` contract: multipart
`file` + `to=pdf`, service-secret auth. See the office-render repo for the
service and its decision log.

Configured by two env vars an agent already sets to use the service:
  OFFICE_RENDER_URL     the service base URL (e.g. https://office-render.cycls.ai)
  OFFICE_RENDER_SECRET  the shared service secret (Bearer token)

If either is unset the feature is simply off: `to_pdf` raises `Unavailable`,
the route answers 415, and the client falls back to the download card — exactly
today's behaviour, no regression.
"""
import os

import httpx

# Extensions LibreOffice turns into a faithful PDF, so the canvas offers a
# preview for them. Apple iWork (pages/key/numbers) is absent on purpose —
# LibreOffice can't open it reliably.
CONVERTIBLE = frozenset({
    "doc", "docx", "odt", "rtf", "fodt",          # word processing
    "ppt", "pptx", "odp", "fodp",                 # presentations
    "xls", "xlsx", "xlsm", "ods", "fods",         # spreadsheets
    "epub",                                       # misc office-ish
})

# Conversions run inside a warm container but pay a soffice spawn (~1-2s), and a
# large deck takes longer; give the request real headroom.
_TIMEOUT = 300


class Unavailable(RuntimeError):
    """Raised when the converter is unreachable or can't convert this file, so
    the caller degrades to the download card instead of a hard error."""


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def convertible(name):
    return _ext(name) in CONVERTIBLE


def configured():
    """The service is wired only when both the URL and secret are set."""
    return bool(os.environ.get("OFFICE_RENDER_URL") and os.environ.get("OFFICE_RENDER_SECRET"))


async def to_pdf(data, name, user_id=None):
    """Convert `data` (a .docx/.pptx/.xlsx/… named `name`) to PDF bytes via the
    office-render service. `user_id` rides along as X-User-Id for attribution
    (not auth). Raises `Unavailable` on any miss so the caller can fall back."""
    if not convertible(name):
        raise Unavailable(f"no PDF filter for .{_ext(name) or '?'}")
    url = os.environ.get("OFFICE_RENDER_URL")
    secret = os.environ.get("OFFICE_RENDER_SECRET")
    if not (url and secret):
        raise Unavailable("office-render not configured (OFFICE_RENDER_URL / OFFICE_RENDER_SECRET)")
    headers = {"Authorization": f"Bearer {secret}"}
    if user_id:
        headers["X-User-Id"] = str(user_id)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{url.rstrip('/')}/v1/convert",
                files={"file": (name, data)},
                data={"to": "pdf"},
                headers=headers,
            )
    except httpx.HTTPError as e:
        raise Unavailable(f"office-render unreachable: {e}") from e
    if resp.status_code != 200:
        raise Unavailable(f"office-render {resp.status_code}: {resp.text[:300]}")
    return resp.content

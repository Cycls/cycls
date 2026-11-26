"""Office → PDF and slide pictures for the canvas, through the cycls-office service.

Word, PowerPoint and Excel files can't render in a browser, but a faithful PDF
can — and the canvas already has a first-class PDF viewer. So the file route
converts an Office document to PDF on demand and serves that (`?as=pdf`, also
what the Sheets and Docs editors print), and shows a deck slide by slide
(`?as=slides`).

The conversion is LibreOffice, which is ~1GB and used by a minority of turns,
so it is not baked into every agent image: it runs in cycls-office, the service
behind Cycls Sheets and Cycls Docs (`/v1/convert`, `/v1/render`), with the
fonts Office files ask for (Carlito for Calibri, Caladea for Cambria, …). It
took over from the separate office-render service, on the same contract.

Configured by what an agent already sets for Sheets and Docs:
  OFFICE_URL     the service, https://cycls-office.cycls.ai
  OFFICE_SECRET  the key every request carries

If OFFICE_URL is unset the feature is simply off: `to_pdf` raises
`Unavailable`, the route answers 415, and the client falls back to the download
card, never a dead error.
"""
import base64

from cycls._agent.office import client as _office

# Extensions LibreOffice turns into a faithful PDF, so the canvas offers a
# preview for them. Apple iWork (pages/key/numbers) is absent on purpose —
# LibreOffice can't open it reliably.
CONVERTIBLE = frozenset({
    "doc", "docx", "odt", "rtf", "fodt",          # word processing
    "ppt", "pptx", "odp", "fodp",                 # presentations
    "xls", "xlsx", "xlsm", "ods", "fods",         # spreadsheets
    "epub",                                       # misc office-ish
})

# Presentations render as a slide viewer (per-slide images) rather than a flat
# PDF — via the service's /v1/render. Kept in sync with PRESENTATION_EXTS in
# client/src/components/canvas-utils.ts.
PRESENTATION = frozenset({"ppt", "pptx", "odp", "fodp"})

# Slide-viewer defaults: enough dpi to read a deck on screen without bloating the
# payload, and a page cap so a giant deck can't blow up the response.
_SLIDE_DPI = 110
_SLIDE_MAX_PAGES = 100


class Unavailable(RuntimeError):
    """Raised when the converter is unreachable or can't convert this file, so
    the caller degrades to the download card instead of a hard error."""


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def convertible(name):
    return _ext(name) in CONVERTIBLE


def presentation(name):
    return _ext(name) in PRESENTATION


def configured():
    """The converter is wired when the office service is (OFFICE_URL)."""
    return _office.configured()


async def to_pdf(data, name, user_id=None):
    """Convert `data` (a .docx/.pptx/.xlsx/… named `name`) to PDF bytes on the
    office service. `user_id` rides along as X-User-Id for attribution (not
    auth). Raises `Unavailable` on any miss so the caller can fall back."""
    if not convertible(name):
        raise Unavailable(f"no PDF filter for .{_ext(name) or '?'}")
    if not configured():
        raise Unavailable("the office service is not configured (OFFICE_URL)")
    try:
        return await _office.convert(data, name, "pdf", user_id=user_id)
    except (_office.Unavailable, _office.Refused) as e:
        raise Unavailable(str(e)) from e


async def to_slides(data, name, user_id=None, dpi=_SLIDE_DPI, max_pages=_SLIDE_MAX_PAGES):
    """Render a presentation (`data` named `name`) to per-slide PNGs on the
    office service. Returns a list of PNG byte strings, one per slide, in order.
    Raises `Unavailable` on any miss so the caller can fall back."""
    if not presentation(name):
        raise Unavailable(f"not a presentation: .{_ext(name) or '?'}")
    if not configured():
        raise Unavailable("the office service is not configured (OFFICE_URL)")
    try:
        pages = await _office.render(data, name, dpi=dpi, pages=f"1-{max_pages}", user_id=user_id)
        return [base64.b64decode(p["png_base64"]) for p in pages if p.get("png_base64")]
    except (_office.Unavailable, _office.Refused) as e:
        raise Unavailable(str(e)) from e
    except (ValueError, KeyError, TypeError) as e:
        raise Unavailable(f"the office service sent a bad render: {e}") from e

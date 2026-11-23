"""Any photo a person or the agent brings, made ready for a design: a phone's HEIC, an AVIF, a scan's TIFF or BMP, or a
camera file of any size becomes a picture the renderer takes, the right way up, sized so that many of them fit in one
request. A link the person gave is fetched into the workspace; a picture from anywhere else on the web is not placed.
Pillow does the converting (pillow-heif for HEIC): without them a file the renderer takes as it is still works."""
import asyncio, hashlib, io, pathlib, re
from urllib.parse import urlsplit

MAX_FILE = 64 * 1024 * 1024          # what is read at all
MAX_PIXELS = 110_000_000             # a 108 MP phone photo; past that a file is refused, not decoded
LONG = 3000                          # the longest side kept: an A4 poster at 2x, a full-bleed slide
CAP = 3 * 1024 * 1024                # one photo, when it is the only one
BUDGET = 18 * 1024 * 1024            # all of a design's photos: a request stays under the platform's limit
FLOOR = 350 * 1024                   # one photo, however many there are
AS_IT_IS = 15 * 1024 * 1024          # a picture that can't be converted, sent unchanged
LINK_MAX = 25 * 1024 * 1024
PREVIEW_LONG = 1568                  # what the model is shown
OTHER_EXTS = {"heic", "heif", "avif", "bmp", "tif", "tiff"}

_URL = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)
_SLOTS = ("src", "image", "photo", "picture")
_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "BMP": "bmp", "TIFF": "tiff", "HEIF": "heic", "AVIF": "avif"}


def _pil():
    """Pillow with every format it can read here, or None."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    return Image, ImageOps


def available():
    """Can this service convert pictures?"""
    return _pil() is not None


def cap_for(obj):
    """How large each photo may be, for the number of pictures a spec, deck, document or ops list holds."""
    count = 0

    def walk(v):
        nonlocal count
        if isinstance(v, dict):
            for k, x in v.items():
                if k in (*_SLOTS, "stock", "asset") and (isinstance(x, str) or (isinstance(x, dict) and k != "src")):
                    count += isinstance(x, str)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(obj)
    return max(FLOOR, min(CAP, BUDGET // max(count, 1)))


def _open(data, name):
    pil = _pil()
    if not pil:
        raise ValueError(f"{name} isn't a PNG, JPEG, WebP or GIF, and this service can't convert it: save it as a JPEG")
    Image, ImageOps = pil
    try:
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > MAX_PIXELS:
            raise ValueError(f"{name} is {im.width}×{im.height}, too large to open: save a smaller copy")
        if im.format == "JPEG":
            im.draft("RGB", (LONG, LONG))        # decoded near the size it is kept at
        im.seek(0)
        im.load()
        return ImageOps.exif_transpose(im), Image
    except ValueError:
        raise
    except (OSError, SyntaxError, EOFError, Image.DecompressionBombError) as e:
        raise ValueError(f"{name} can't be read as a picture ({type(e).__name__})") from e


def _encode(im, cap, Image):
    alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    im = im.convert("RGBA" if alpha else "RGB")
    if alpha and im.getchannel("A").getextrema()[0] == 255:
        im, alpha = im.convert("RGB"), False
    long = min(LONG, max(im.size))
    best = None
    for scale in (1, 0.8, 0.64, 0.5, 0.4):
        side = max(800, int(long * scale))
        copy = im.copy()
        copy.thumbnail((side, side), Image.LANCZOS)
        for quality in ((None,) if alpha else (88, 80, 72)):
            out = io.BytesIO()
            if alpha:
                copy.save(out, "PNG", optimize=True)
            else:
                copy.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
            data = out.getvalue()
            if best is None or len(data) < len(best):
                best = data
            if len(data) <= cap:
                return data
        if side == 800:
            break
    return best


def ready(data, dims, cap=CAP, name="the picture"):
    """`data` as bytes the renderer takes: unchanged when it already fits, else converted and sized. Raises ValueError."""
    if dims and all(dims) and len(data) <= cap and max(dims) <= LONG:
        return data
    try:
        im, Image = _open(data, name)
    except ValueError:
        if dims and all(dims):                   # no converter here, or one it can't open: sent as it is, if it fits
            if len(data) <= AS_IT_IS:
                return data
            raise ValueError(f"{name} is {len(data) / 2**20:.1f} MB, over the {AS_IT_IS >> 20} MB a design takes as it is: "
                             f"save a smaller copy") from None
        raise
    return _encode(im, cap, Image)


def preview(data, name="the picture"):
    """(a JPEG small enough to show the model, its media type). Raises ValueError."""
    im, Image = _open(data, name)
    im = im.convert("RGBA")
    ground = Image.new("RGBA", im.size, (255, 255, 255, 255))
    ground.alpha_composite(im)
    im = ground.convert("RGB")
    im.thumbnail((PREVIEW_LONG, PREVIEW_LONG), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue(), "image/jpeg"


def _given(url, heard):
    """Is this link, or a link on the same site, one the person wrote?"""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return False
    for said in _URL.findall(heard or ""):
        theirs = (urlsplit(said).hostname or "").lower().removeprefix("www.")
        if theirs and (host == theirs or host.endswith("." + theirs)):
            return True
    return False


def _kind(data):
    """The file extension for picture bytes, by what they are and not by what a server says, else None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"heif", b"mif1", b"msf1"):
            return "heic"
    return None


async def _download(url):
    """A public picture's bytes, every redirect's host checked. Raises ValueError."""
    import httpx
    from ..tools import _FETCH_HEADERS, _is_public_host
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            for _ in range(5):
                if urlsplit(url).scheme != "https" and urlsplit(url).scheme != "http":
                    raise ValueError("only a web link can be fetched")
                if not await asyncio.to_thread(_is_public_host, httpx.URL(url).host):
                    raise ValueError("it resolves to a private or unreachable address")
                async with client.stream("GET", url, headers=_FETCH_HEADERS) as r:
                    if r.is_redirect:
                        url = str(httpx.URL(url).join(r.headers.get("location", "")))
                        continue
                    r.raise_for_status()
                    chunks, total = [], 0
                    async for chunk in r.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > LINK_MAX:
                            raise ValueError(f"it is over {LINK_MAX >> 20} MB")
                    return b"".join(chunks)
            raise ValueError("too many redirects")
    except httpx.HTTPStatusError as e:
        raise ValueError(f"the site answered {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise ValueError(f"the download failed ({type(e).__name__})") from e


async def links(obj, root, heard):
    """Every picture given as a web link in a spec, deck, slide or ops list → a workspace file, in place. A link must be
    one the person gave, or on the same site. → an error, or None."""
    found = []

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in _SLOTS and isinstance(x, str) and x.lower().startswith(("http://", "https://")):
                    found.append((v, k))
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(obj)
    saved = {}
    for holder, key in found:
        url = holder[key].strip()
        if url not in saved:
            if not _given(url, heard):
                host = urlsplit(url).hostname or url[:40]
                return (f"Error: the picture at {host} didn't come from the person, so it can't be placed: it may be someone "
                        f"else's. Use a file they uploaded, a link they gave, `stock`, or the media library (`asset`).")
            folder = pathlib.Path(root) / "attachments" / "links"
            stem = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            there = next(iter(sorted(folder.glob(f"{stem}.*"))), None) if folder.is_dir() else None
            if there is None:
                try:
                    data = await _download(url)
                except ValueError as e:
                    return f"Error: couldn't fetch the picture at {url[:80]}: {e}."
                ext = _kind(data)
                if not ext:
                    return f"Error: the link {url[:80]} isn't a picture. Give the address of the image file itself."
                folder.mkdir(parents=True, exist_ok=True)
                there = folder / f"{stem}.{ext}"
                part = folder / f".{stem}.part"
                part.write_bytes(data)
                part.replace(there)
            saved[url] = there.relative_to(pathlib.Path(root)).as_posix()
        holder[key] = saved[url]
    return None

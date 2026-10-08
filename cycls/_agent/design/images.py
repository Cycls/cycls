"""The pictures of a design: a workspace image placed in a spec — its size, its turn,
its bytes — an image slot of a layout, and the bounds on what is sent to the service and
shown to the model."""
import base64, struct
from ..paths import _resolve_path


# A render the model sees, to QA before presenting it — bounded like `read`.
_DESIGN_QA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_DESIGN_QA_MAX = 3 * 1024 * 1024
_DESIGN_QA_SLIDES = 12             # a deck's slides the model QAs, in order


# An image node's bytes ride to the stateless service as base64 inside the spec —
# bounded so a request stays under the platform's 32 MiB (base64 adds a third). The
# service fits each photo to its box (cover-crop, at most 2× the box) before it's
# drawn, so the .fig stays light however big the original.
_DESIGN_IMAGE_MAX = 15 * 1024 * 1024
_DESIGN_IMAGES_MAX = 20 * 1024 * 1024
_DESIGN_SVG_MAX = 200 * 1024


def _exif_orientation(tiff):
    """The Orientation tag (0x0112) of an EXIF TIFF block, else 1."""
    try:
        e = {b"II": "<", b"MM": ">"}[tiff[:2]]
        off = struct.unpack(e + "I", tiff[4:8])[0]
        for k in range(struct.unpack(e + "H", tiff[off:off + 2])[0]):
            p = off + 2 + 12 * k
            if struct.unpack(e + "H", tiff[p:p + 2])[0] == 0x0112:
                return struct.unpack(e + "H", tiff[p + 8:p + 10])[0]
    except (KeyError, struct.error):
        pass
    return 1


def _jpeg_size(data):
    i, turned = 2, False
    while i + 9 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xFF:                                  # fill byte
            i += 1
            continue
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            turned = _exif_orientation(data[i + 10:i + 2 + seg]) in (5, 6, 7, 8)
        elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return (h, w) if turned else (w, h)
        i += 2 + seg
    return None


def _image_size(data):
    """(width, height) of a PNG / JPEG / WebP / GIF as the renderer DRAWS it — a
    JPEG's EXIF quarter-turn (orientation 5–8) swaps the two, since the renderer
    honours it — else None (an SVG included)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return (int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1)
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return (w & 0x3FFF, h & 0x3FFF)
        if kind == b"VP8L":
            b = int.from_bytes(data[21:25], "little")
            return ((b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1)
        return None
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    return None


def _no_such_image(src, root):
    """Why an image can't be used: no such file — or not a file's name at all."""
    from cycls._agent.design import stock
    if stock.described(src, root):
        return (f"image {src[:60]!r} describes a picture — `src` is a file in the workspace, and stock photos "
                f"aren't set up here to find one: save a photo into the workspace (e.g. attachments/photo.jpg) and use its path")
    return f"image {src!r} does not exist in the workspace"


def _place_image(n, root):
    """An image node's `src` (a workspace file) → the bytes the service draws, in
    its final box: `fit` "cover" (default) fills w×h, cropping the overflow;
    "contain" shrinks the box to the image's aspect and centres it (the renderer's
    own FIT distorts). Give w, h or both — a missing one follows the image's
    aspect. Rewrites the node in place; returns the byte count. Raises ValueError
    with the fix."""
    src = n.get("src")
    if not isinstance(src, str) or not src.strip():
        raise ValueError("an image node needs `src` — a workspace file, e.g. attachments/photo.jpg — "
                         "or `stock`: a photo to find, e.g. \"stock\": \"coffee beans on wood\"")
    if src.startswith(("http://", "https://", "data:")):
        raise ValueError(f"image src {src[:60]!r} must be a workspace file — save it into the workspace first")
    path = _resolve_path(src, root)
    if not path.is_file():
        raise ValueError(_no_such_image(src, root))
    if (size := path.stat().st_size) > _DESIGN_IMAGE_MAX:
        raise ValueError(f"image {src!r} is {size / 2**20:.1f} MB, over the {_DESIGN_IMAGE_MAX >> 20} MB "
                         f"a design takes — save a smaller copy (longest side ~2000px) and use that")
    data = path.read_bytes()
    if not (dims := _image_size(data)) or not all(dims):
        raise ValueError(f"image {src!r} isn't a PNG, JPEG, WebP or GIF (convert an SVG to PNG first)")
    (iw, ih), w, h = dims, n.get("w"), n.get("h")
    if not w and not h:
        raise ValueError(f"image {src!r} needs `w` and/or `h` (the other follows its {iw}×{ih} aspect)")
    w, h = (w or h * iw / ih), (h or w * ih / iw)
    fit = str(n.pop("fit", "cover")).lower()
    if fit == "contain":
        s = min(w / iw, h / ih)
        n["x"] = (n.get("x") or 0) + (w - iw * s) / 2
        n["y"] = (n.get("y") or 0) + (h - ih * s) / 2
        w, h = iw * s, ih * s
    elif fit != "cover":
        raise ValueError(f"image `fit` is cover or contain, not {fit!r}")
    n["w"], n["h"] = round(w, 2), round(h, 2)
    n["image"] = base64.b64encode(data).decode()
    del n["src"]
    return len(data)
_BRAND_LOGOS = ("logo.svg", "logo.png", "logo.webp", "logo.jpg", "logo.jpeg")


def _image_slot(src, root):
    """A deck's image slot — a workspace path, or {src, focus} — → what the service
    draws: {image: base64, src[, focus]} for a PNG / JPEG / WebP / GIF, or {svg, src}.
    → (slot, bytes read). Raises ValueError with the fix."""
    focus = None
    if isinstance(src, dict):
        focus, src = src.get("focus"), src.get("src")
    if not isinstance(src, str) or not src.strip():
        raise ValueError('an image slot is a workspace file path, e.g. "attachments/photo.jpg"')
    if src.startswith(("http://", "https://", "data:")):
        raise ValueError(f"image {src[:60]!r} must be a workspace file — save it into the workspace first")
    path = _resolve_path(src, root)
    if not path.is_file():
        raise ValueError(_no_such_image(src, root))
    size = path.stat().st_size
    if path.suffix.lower() == ".svg":
        if size > _DESIGN_SVG_MAX:
            raise ValueError(f"{src} is over {_DESIGN_SVG_MAX >> 10} KB — use a simpler SVG (or a PNG)")
        return {"svg": path.read_text(encoding="utf-8", errors="replace"), "src": src}, size
    if size > _DESIGN_IMAGE_MAX:
        raise ValueError(f"image {src!r} is {size / 2**20:.1f} MB, over the {_DESIGN_IMAGE_MAX >> 20} MB a design takes")
    data = path.read_bytes()
    if not _image_size(data):
        raise ValueError(f"image {src!r} isn't a PNG, JPEG, WebP, GIF or SVG")
    slot = {"image": base64.b64encode(data).decode(), "src": src}
    if (natural := _image_size(data)):
        slot["w"], slot["h"] = natural                      # a document sizes a picture from its own shape
    if isinstance(focus, list) and len(focus) == 2:
        slot["focus"] = focus
    return slot, size

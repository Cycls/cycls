"""Colours, and the workspace's brand kit, for a design: a hex read as one, the kit's
colours and fonts, and which ink reads on which ground."""
import pathlib, re


_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}")


def _norm_hex(c):
    """`#abc`/`#AABBCC` → `#aabbcc`; anything else → None."""
    if not isinstance(c, str) or not _HEX.fullmatch(c.strip()):
        return None
    h = c.strip()[1:].lower()
    return "#" + (h if len(h) == 6 else "".join(ch * 2 for ch in h))


def _load_brand(root):
    """The workspace brand kit — `brand/brand.yaml`, written by the brand-kit skill —
    as {primary, accent, heading, body} (any may be None), or None when there is no
    kit or it names neither a hex primary nor a font. Reads the flat keys
    (`primary_color: "#0c2340"`, `font_heading: "Playfair Display"`) and the older
    nested ones (`colors:` / `  primary: …`, `fonts:` / `  heading: …`) with a
    pattern, not a YAML parser — the SDK carries no YAML dependency."""
    try:
        text = (pathlib.Path(root) / "brand" / "brand.yaml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    def pick(flat, nested):
        m = (re.search(rf"^{flat}\s*:\s*['\"]?({_HEX.pattern})\b", text, re.M)
             or re.search(rf"^\s+{nested}\s*:\s*['\"]?({_HEX.pattern})\b", text, re.M))
        return _norm_hex(m.group(1)) if m else None

    def font(flat, nested):
        value = r"""\s*:\s*['"]?([A-Za-z][A-Za-z0-9 \-]*?)['"]?\s*(?:#.*)?$"""
        m = re.search(rf"^{flat}{value}", text, re.M) or re.search(rf"^\s+{nested}{value}", text, re.M)
        return m.group(1).strip() if m and m.group(1).strip().lower() not in ("null", "none", "") else None

    primary = pick("primary_color", "primary")
    brand = {"primary": primary, "accent": pick("accent_color", "accent") or primary,
             "heading": font("font_heading", "heading"), "body": font("font_body", "body")}
    return brand if primary or brand["heading"] or brand["body"] else None


_BRAND_COLOR_KEYS = ("primary", "secondary", "accent", "background", "text", "neutral")


def _brand_palette(root):
    """The brand kit's named colours for the design editor's Brand variables —
    {primary, secondary, accent, background, text, neutral}, each only when
    `brand/brand.yaml` gives it a hex, flat (`secondary_color: "#…"`) or nested under
    `colors:`. Unlike `_load_brand`, nothing is inferred (no accent from primary)."""
    try:
        text = (pathlib.Path(root) / "brand" / "brand.yaml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    palette = {}
    for key in _BRAND_COLOR_KEYS:
        m = (re.search(rf"^{key}_colou?r\s*:\s*['\"]?({_HEX.pattern})\b", text, re.M)
             or re.search(rf"^\s+{key}\s*:\s*['\"]?({_HEX.pattern})\b", text, re.M))
        if m and (value := _norm_hex(m.group(1))):
            palette[key] = value
    return palette


def _first_color(paint):
    """A paint's representative colour: the hex itself, or a gradient's first stop."""
    if isinstance(paint, dict) and isinstance(paint.get("gradient"), list) and paint["gradient"]:
        paint = paint["gradient"][0]
        if isinstance(paint, (list, tuple)) and paint:
            paint = paint[0]
        elif isinstance(paint, dict):
            paint = paint.get("color")
    return _norm_hex(paint)


def _luminance(hex_):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a, b):
    """The WCAG contrast ratio of two #rrggbb colours."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _readable_on(bg):
    """White or near-black — whichever text reads better on `bg` (WCAG luminance)."""
    return "#ffffff" if _luminance(bg) < 0.179 else "#111111"

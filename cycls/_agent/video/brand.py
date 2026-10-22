"""The workspace's brand kit, in every video (not only the templates).

A brand kit is `brand/brand.yaml` (colours, fonts, the brand-kit skill writes it) and `brand/logo.*`,
read as Design reads them (design/brand.py). The guide says what it holds and how a video uses it:
its colours, its fonts when the video catalogue has them (the nearest catalogue family when not, an
Arabic one beside it for Arabic text), and its logo as an image by its workspace path. A save whose
composition uses none of the kit's colours and not its logo is told so, once a reply, the way
Design's replies are. A template is given the kit's colours, fonts and logo for the variables the
model left out (run._with_brand).
"""
import re
from pathlib import Path

from ..design.brand import _brand_palette, _load_brand, _norm_hex

LOGOS = ("logo.svg", "logo.png", "logo.webp", "logo.jpg", "logo.jpeg")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def kit(root, fonts=()):
    """The kit as a video uses it, or None when the workspace has none.
    `fonts` is the contract's catalogue ([{family, scripts}]).
    → {"colours": {role: hex}, "heading", "body": (family, in the catalogue?), "logo": path or None}."""
    b = _load_brand(root) or {}
    palette = _brand_palette(root)
    logo = next((f"brand/{n}" for n in LOGOS if (Path(root) / "brand" / n).is_file()), None)
    colours = {k: v for k, v in palette.items() if v}
    for role in ("primary", "accent"):
        if b.get(role) and role not in colours:
            colours[role] = b[role]
    if not colours and not b.get("heading") and not b.get("body") and not logo:
        return None
    names = {f["family"].lower(): f["family"] for f in fonts or []}

    def font(name):
        if not name:
            return None
        return (names.get(name.lower(), name), name.lower() in names)
    return {"colours": colours, "heading": font(b.get("heading")), "body": font(b.get("body")), "logo": logo}


def note(k, fonts=()):
    """The guide's line for the kit."""
    if not k:
        return ""
    parts = []
    if k["colours"]:
        parts.append("colours " + ", ".join(f"{role} {hex_}" for role, hex_ in k["colours"].items()))
    arabic = [f["family"] for f in fonts or [] if "arabic" in (f.get("scripts") or [])]
    for role, label in (("heading", "headings"), ("body", "body text")):
        f = k.get(role)
        if not f:
            continue
        if f[1]:
            parts.append(f"{label} in {f[0]}")
        else:
            parts.append(f"{label}: the brand's font {f[0]} is not a video font, so use the catalogue family "
                         "closest to it")
    if arabic and (k.get("heading") or k.get("body")):
        parts.append(f"Arabic text in an Arabic family ({', '.join(arabic[:3])}…)")
    if k["logo"]:
        parts.append(f"the logo <img src=\"{k['logo']}\"> (on the opening or the closing scene, or small in a corner)")
    return ("Brand kit (brand/brand.yaml): use it in every video unless the person asks otherwise — "
            + "; ".join(parts) + ".")


def uses(html, k):
    """Does the composition use the kit: one of its colours, or its logo?"""
    if not k:
        return True
    if k["logo"] and k["logo"].lower() in html.lower():
        return True
    used = {_norm_hex(m.group(0)) for m in _HEX.finditer(html)}
    return any(v in used for v in k["colours"].values())


def hint(root, html, fonts=()):
    """A line for a save that leaves the kit out, or ''."""
    k = kit(root, fonts)
    if not k or uses(html, k) or not (k["colours"] or k["logo"]):
        return ""
    what = []
    if k["colours"]:
        what.append("colours (" + ", ".join(list(k["colours"].values())[:4]) + ")")
    if k["logo"]:
        what.append(f"logo ({k['logo']})")
    return (f"Brand: this video uses none of the workspace brand kit's {' or its '.join(what)}. Use them unless the "
            "person asked for another look.")


def template_vars(k, takes, fonts=(), arabic=False):
    """What the kit gives a template for the variables it takes (`takes`: its variable names, or None
    when the catalogue is not at hand: then only those every template takes). For an Arabic template
    (`arabic`) a brand font is given only when it has Arabic letters."""
    if not k:
        return {}
    every = {"accent", "background", "text", "heading_font"}
    ok = (lambda v: v in every) if takes is None else (lambda v: v in takes)
    c = k["colours"]
    out = {}
    accent = c.get("accent") or c.get("primary")
    if accent and ok("accent"):
        out["accent"] = accent
    if c.get("accent") and c.get("primary") and c["primary"] != c["accent"] and ok("accent2"):
        out["accent2"] = c["primary"]
    if c.get("background") and c.get("text") and ok("background") and ok("text"):   # both, or the contrast is a guess
        out["background"], out["text"] = c["background"], c["text"]
    scripts = {f["family"]: f.get("scripts") or [] for f in fonts or []}
    for role, var in (("heading", "heading_font"), ("body", "body_font")):
        f = k.get(role)
        if f and f[1] and ok(var) and (not arabic or "arabic" in scripts.get(f[0], [])):
            out[var] = f[0]
    if k["logo"] and ok("logo"):
        out["logo"] = k["logo"]
    return out

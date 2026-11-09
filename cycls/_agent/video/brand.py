"""The workspace's brand kit, in every video (not only the templates).

A brand kit is `brand/brand.yaml` (colours, fonts, the brand-kit skill writes it) and `brand/logo.*`,
read as Design reads them (design/brand.py). The guide says what it holds and how a video uses it:
its colours, its fonts when the video catalogue has them (the nearest catalogue family when not, an
Arabic one beside it for Arabic text), and its logo as an image by its workspace path. A save whose
composition uses none of the kit's colours and not its logo is told so, once a reply, the way
Design's replies are. A template is given the kit's colours, fonts and logo for the variables the
model left out (run._with_brand). A video with a look carries the kit over the look by itself, and the brand
keeps a look of its own for every video (apply, below).
"""
import re
from pathlib import Path

from ..design.brand import _brand_palette, _load_brand, _norm_hex

LOGOS = ("logo.svg", "logo.png", "logo.webp", "logo.jpg", "logo.jpeg")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def kit(root, fonts=()):
    """The kit as a video uses it, or None when the workspace has none.
    `fonts` is the contract's catalogue ([{family, scripts}]).
    → {"colours": {role: hex}, "heading", "body": (family, in the catalogue?, a font file of the
    kit's?), "files": the kit's own font families (fonts.families), "logo": path or None}."""
    from . import fonts as kit_fonts

    b = _load_brand(root) or {}
    palette = _brand_palette(root)
    logo = next((f"brand/{n}" for n in LOGOS if (Path(root) / "brand" / n).is_file()), None)
    files = kit_fonts.families(root)
    colours = {k: v for k, v in palette.items() if v}
    for role in ("primary", "accent"):
        if b.get(role) and role not in colours:
            colours[role] = b[role]
    if not colours and not b.get("heading") and not b.get("body") and not logo and not files:
        return None
    names = {f["family"].lower(): f["family"] for f in fonts or []}
    own = {f.lower(): f for f in files}

    def font(name):
        if not name:
            return None
        key = name.lower()
        return (names.get(key) or own.get(key) or name, key in names, key in own and key not in names)
    return {"colours": colours, "heading": font(b.get("heading")), "body": font(b.get("body")), "files": files,
            "logo": logo, "look": video_look(root)}


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
        if f[1] or f[2]:
            parts.append(f"{label} in \"{f[0]}\"")
        else:
            parts.append(f"{label}: the brand's font {f[0]} is not a video font and the kit has no file of it, so use "
                         "the catalogue family closest to it")
    files = k.get("files") or {}
    if files:
        own = []
        for fam, info in files.items():
            weights = "/".join(str(w) for w in info["weights"])
            own.append(f"\"{fam}\" ({weights}{', with Arabic' if info['arabic'] else ', Latin only'})")
        parts.append("the brand's own font files (brand/fonts), to name in font-family exactly so, each with a "
                     "catalogue family after it in the stack: " + ", ".join(own))
    if arabic and (k.get("heading") or k.get("body") or files):
        parts.append(f"Arabic text in a family that has Arabic ({', '.join(arabic[:3])}…)")
    if k["logo"]:
        parts.append(f"the logo <img src=\"{k['logo']}\"> (on the opening or the closing scene, or small in a corner)")
    line = ("Brand kit (brand/brand.yaml): use it in every video unless the person asks otherwise — "
            + "; ".join(parts) + ".")
    line += (" Over a look the kit goes by itself: each save adds a <style data-cycls-brand> with its colours and fonts "
             "over the look's (leave it; data-brand=\"none\" on the root leaves the kit out).")
    if k.get("look"):
        line += (f" This brand's look is {k['look']}: write data-look=\"brand\" (or \"{k['look']}\") for every video of "
                 "it, another look only when the person asks for one.")
    else:
        line += " The first look a video uses becomes this brand's look (kept in brand/brand.yaml as video_look)."
    return line


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
    if not k or uses(html, k) or not (k["colours"] or k["logo"]) or BLOCK.search(html):
        return ""
    what = []
    if k["colours"]:
        what.append("colours (" + ", ".join(list(k["colours"].values())[:4]) + ")")
    if k["logo"]:
        what.append(f"logo ({k['logo']})")
    line = (f"Brand: this video uses none of the workspace brand kit's {' or its '.join(what)}. Use them unless the "
            "person asked for another look.")
    if "data-look" in html and k["colours"]:
        # A look is styled through its variables: the kit goes over it in one rule, the look's design kept.
        c = k["colours"]
        sets = [f"--look-{var}: {c[key]}" for var, key in (("accent", "accent"), ("bg", "background"), ("ink", "text"))
                if c.get(key)]
        if not c.get("accent") and c.get("primary"):
            sets.insert(0, f"--look-accent: {c['primary']}")
        for role, var in (("heading", "display"), ("body", "text")):
            f = k.get(role)
            if f and f[1]:
                sets.append(f'--look-{var}: "{f[0]}", sans-serif')
        line += " Over the look, add to your <style>: #root[data-look] { " + "; ".join(sets) + "; }"
    return line


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


# ── the brand's look ────────────────────────────────────────────────────────────────────────────────
# A video with a look in a workspace with a kit carries the kit over the look by itself: a <style data-cycls-brand>
# on the line of <head>, made from the kit at each save (so a changed kit reaches the next save), the look's design
# kept and its variables set — the accent where it reads on the ground in use, the kit's background and text
# together, its fonts with the look's Arabic face after them. The brand's own look (brand/brand.yaml video_look)
# is the one every video for it starts from: the first look a video uses in the workspace is kept there, and
# data-look="brand" names it. data-brand="none" on the root leaves the kit out.
BLOCK = re.compile(r"<style data-cycls-brand>.*?</style>", re.S)
_HEAD = re.compile(r"<head\b[^>]*>", re.I)
_VIDEO_LOOK = re.compile(r"""^video_look\s*:\s*['"]?([a-z][a-z-]*)['"]?""", re.M)


def _lum(hex_):
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def video_look(root):
    """The brand's own look for video (brand/brand.yaml video_look), or None."""
    try:
        m = _VIDEO_LOOK.search((Path(root) / "brand" / "brand.yaml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None
    return m.group(1) if m else None


def keep_look(root, look):
    """`look` kept as the brand's own look: a line added to brand/brand.yaml. → its new text, or None (no kit file,
    or one is kept already)."""
    path = Path(root) / "brand" / "brand.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if _VIDEO_LOOK.search(text):
        return None
    return (text if text.endswith("\n") or not text else text + "\n") + \
        f"video_look: {look}   # the look every video for this brand starts from (Cycls Video)\n"


def _root(html):
    from . import sizes
    m = sizes._ROOT.search(html)
    return (m, sizes._attr(m.group(0), "data-look"), sizes._attr(m.group(0), "data-brand"),
            sizes._attr(m.group(0), "id")) if m else (None, None, None, None)


def layer(k, look, fonts=(), root_id="root"):
    """The CSS that puts kit `k` over look `look` (its catalogue entry: palette, fonts) → (css, notes)."""
    c = k["colours"]
    pal = (look or {}).get("palette") or {}
    lf = (look or {}).get("fonts") or {}
    sets, notes = [], []
    bg = c.get("background") if c.get("background") and c.get("text") else None
    ink = c.get("text") if bg else None
    if bg:
        sets += [f"--look-bg: {bg}", f"--look-ink: {ink}", f"--look-muted: color-mix(in srgb, {ink} 64%, {bg})",
                 f"--look-lt-bg: {bg}", f"--look-lt-ink: {ink}"]
    ground = bg or _norm_hex(pal.get("bg")) or "#ffffff"
    tried = [x for x in (c.get("accent"), c.get("primary")) if x]
    accent = next((x for x in tried if contrast(x, ground) >= 3), None)
    if accent:
        on = "#ffffff" if contrast("#ffffff", accent) >= contrast("#111111", accent) else "#111111"
        sets += [f"--look-accent: {accent}", f"--look-highlight: {accent}", f"--look-lt-accent: {accent}",
                 f"--look-on-accent: {on}", f"--look-on-highlight: {on}"]
        if contrast(accent, "#1a1a1a") >= 3:             # light enough for words over footage under the look's shade
            sets += [f"--look-footage-accent: {accent}", f"--look-caption-accent: {accent}"]
        other = next((x for x in tried if x != accent), None)
        if other:
            sets.append(f"--look-accent2: {other}")
    elif tried:
        notes.append(f"the brand's colour {tried[0]} does not read on this look's ground ({ground}), so the look's own "
                     "accent is kept: for the brand's colours, a look whose ground suits them, or the kit's background "
                     "and text")
    scripts = {f["family"].lower(): f.get("scripts") or [] for f in fonts or []}
    files = k.get("files") or {}

    def has_arabic(name):
        own = files.get(name)
        return bool(own and own.get("arabic")) or "arabic" in scripts.get(name.lower(), [])

    for role, var, fallback, generic in (("heading", "display", lf.get("ar_display"), "serif"),
                                         ("body", "text", lf.get("ar_text"), "sans-serif")):
        f = k.get(role)
        if not f or not (f[1] or f[2]):
            continue
        stack = [f'"{f[0]}"'] + ([f'"{fallback}"'] if fallback and not has_arabic(f[0]) else []) + [generic]
        sets.append(f"--look-{var}: {', '.join(stack)}")
        if role == "body":
            sets.append(f"--look-caption-font: {', '.join(stack)}")
    if not sets:
        return "", notes
    sel = f"#{root_id}[data-look]" if root_id and re.fullmatch(r"[A-Za-z][\w-]*", root_id) else "[data-composition-id][data-look][data-look]"
    return f"{sel} {{ {'; '.join(sets)}; }}", notes


def apply(html, root, fonts=(), looks=()):
    """The composition with the kit over its look (and data-look="brand" made the brand's look) → (html, what the
    reply says, the look to keep as the brand's or None). `looks`: the catalogue's looks (contract data)."""
    m, look_id, opt, root_id = _root(html)
    k = kit(root, fonts)
    said, keep = [], None
    if m and look_id == "brand":
        own = video_look(root)
        if own:
            from . import sizes
            tag = sizes._set(m.group(0), "data-look", own)
            html = html[:m.start()] + tag + html[m.end():]
            look_id = own
            said.append(f'data-look="brand" is {own}, this brand\'s look.')
        else:
            said.append('data-look="brand": this brand has no look yet (brand/brand.yaml video_look) — name one of the '
                        "looks; the first one a video uses becomes the brand's.")
    by_id = {lk.get("id"): lk for lk in looks or []}
    css = ""
    if k and m and look_id in by_id and (opt or "").strip().lower() != "none":
        css, notes = layer(k, by_id[look_id], fonts, root_id=root_id)
        said += [f"Brand: {n}." for n in notes]
        if not video_look(root) and (Path(root) / "brand" / "brand.yaml").is_file():
            keep = look_id
    block = f"<style data-cycls-brand>{css}</style>" if css else ""
    if BLOCK.search(html):
        html = BLOCK.sub(lambda _: block, html, count=1)
    elif block:
        head = _HEAD.search(html)
        if head:
            html = html[:head.end()] + block + html[head.end():]
    return html, " ".join(said), keep

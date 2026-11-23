"""A design held against what the person asked: the language they wrote in and the names as they wrote them. And,
when they named no colours, a ground drawn from every kind of ground, so that no one of them becomes the habit."""
import difflib, hashlib, re

_AR = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")
_LA = re.compile(r"[A-Za-z]")
_ASKED_LANGUAGE = re.compile(r"arabic|english|bilingual|translat|عربي|العربية|إنجليزي|انجليزي|الإنجليزية|ثنائي", re.I)
# Two or more capitalised words in a row: "Bright Smile Dental Clinic" (the 's of a possessive stays out).
_NAME = re.compile(r"\b[A-Z][\w&-]*(?:[ \t]+[A-Z][\w&-]*)+")
# What says how a design looks, not what it says.
_NOT_WORDS = {"type", "id", "font", "color", "fill", "stroke", "src", "asset", "stock", "image", "theme", "look", "layout",
              "style", "size", "align", "valign", "anchor", "dir", "transition", "kind", "icon", "shape", "fit", "columns_style"}
_COLOURS = re.compile(r"#[0-9a-f]{3,8}\b|\b(?:black|white|navy|blue|red|green|yellow|orange|purple|pink|gold|golden|silver|"
                      r"beige|cream|teal|turquoise|grey|gray|brown|maroon|violet|lilac|colou?rs?|palette|theme|same look|"
                      r"like the last|dark|light mode)\b|أسود|أبيض|أزرق|أحمر|أخضر|أصفر|ذهبي|بني|وردي|بنفسجي|رمادي|لون|ألوان",
                      re.I)
_AR_EDGE_L, _AR_EDGE_R = r"(?<![؀-ۿ])", r"(?![؀-ۿ])"
_PLACE = re.compile(r"\b(?:saudi(?: arabia)?|riyadh|jeddah|jiddah|dammam|makkah|mecca|madinah|riyals?|vision 2030)\b|"
                    + _AR_EDGE_L + r"(?:السعودية|السعودي|الرياض|جدة|ريال|مكة|المدينة المنورة)" + _AR_EDGE_R, re.I)
_PLACE_CODE = re.compile(r"\b(?:SAR|SAMA|KSA)\b")     # capitals only: "sar" and "sama" are other words
GROUNDS = ("pure white", "black or a very deep dark", "one full, saturated colour", "a deep colour (forest, navy, oxblood, plum)",
           "a clear pale tint with real colour in it", "a large photo, full bleed")


def words_of(spec):
    """Everything a spec says, as one text."""
    out = []

    def walk(v, key=""):
        if key in _NOT_WORDS:
            return
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, k)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, str) and not v.startswith("#") and not (("/" in v or "." in v) and " " not in v):
            out.append(v)

    walk(spec)
    return " ".join(out)


def language_gap(ask, words):
    """(the language they wrote in, the design's) when the two plainly differ and they didn't ask for that, else None."""
    if not ask or _ASKED_LANGUAGE.search(ask):
        return None
    asked_ar, asked_la = len(_AR.findall(ask)), len(_LA.findall(ask))
    made_ar, made_la = len(_AR.findall(words)), len(_LA.findall(words))
    made = made_ar + made_la
    if made < 12:
        return None
    if asked_ar == 0 and asked_la >= 8 and made_ar / made > 0.5:
        return "English", "Arabic"
    if asked_ar >= 8 and asked_ar > 3 * asked_la and made_la / made > 0.7:
        return "Arabic", "English"
    return None


def name_drift(ask, words):
    """[(the name as they wrote it, as the design has it)] for a name that came out nearly, but not exactly, the same."""
    said = re.sub(r"\s+", " ", words)
    out = []
    for name in dict.fromkeys(_NAME.findall(ask or "")):
        parts = name.split()
        if re.search(rf"(?<!\w){re.escape(' '.join(parts))}(?!\w)", said, re.I):
            continue
        for m in re.finditer(rf"(?<!\w)({re.escape(' '.join(parts[:-1]))}) (\w+)", said, re.I):
            got = m.group(2)
            if got.lower() != parts[-1].lower() and difflib.SequenceMatcher(None, got.lower(), parts[-1].lower()).ratio() >= 0.75:
                out.append((name, f"{m.group(1)} {got}"))
                break
    return out


def place_added(heard, words):
    """The Saudi places, currency or bodies a design names when nothing the person wrote does. No place is the default."""
    if _PLACE.search(heard or "") or _PLACE_CODE.search(heard or ""):
        return []
    found = [m.group(0) for m in _PLACE.finditer(words)] + [m.group(0) for m in _PLACE_CODE.finditer(words)]
    return list(dict.fromkeys(found))


def check(spec, ask, heard=None):
    """What a new design has to put right against the brief, in words for the model, or None."""
    words = words_of(spec)
    faults = []
    gap = language_gap(ask, words)
    if gap:
        faults.append(f"the person wrote in {gap[0]} and this design is in {gap[1]}: write its words in {gap[0]}. A saved preference, "
                      f"a workspace file or an earlier design is not them asking for {gap[1]}")
    faults += [f"they call it \"{name}\" and this design says \"{got}\": use their name exactly" for name, got in name_drift(ask, words)]
    added = place_added(f"{ask or ''}\n{heard or ''}", words)
    if added:
        faults.append(f"it brings in {', '.join(added)}, which they never mentioned: a place, a currency or a regulator comes in only "
                      f"when they name it, so take it out")
    if not faults:
        return None
    return ("Not run: check it against the brief. Nothing was made. " + "; ".join(faults) + ". Put that right and render again. "
            "Only if they asked for it in this chat, render it again as it is: this note comes once a turn.")


def ground_hint(heard, seed, branded=False):
    """With no colours in what the person wrote and no brand kit, the kind of ground to start this piece from."""
    if branded or _COLOURS.search(heard or ""):
        return ""
    at = int(hashlib.sha256(str(seed).encode("utf-8")).hexdigest(), 16) % len(GROUNDS)
    how = ("a `stock` picture at the frame's full size, first in its nodes" if "photo" in GROUNDS[at]
           else "written as the frame's `fill` or the theme's `bg`")
    return (f"They named no colours, so start this piece from this ground: {GROUNDS[at]}, {how}, unless its subject plainly "
            f"calls for another.")

"""One video in several sizes: the composition is the source, its root lists the other sizes.

    <div id="root" data-composition-id="main" ... data-width="1920" data-height="1080"
         data-sizes="vertical square">

The root's own size is the main one (videos/<name>.mp4). Each size listed is made from the same
file for every check and render (videos/<name>.<size>.mp4): the root's size, the viewport and a
`data-shape` on the root changed, nothing else, so the scenes, their timing, the sound and the
captions are the same in every size. What a size needs of its own the file says with rules for it
alone, `#root[data-shape="vertical"] .title { ... }`; the file as written is the main size. Nothing
of this reaches the service: it sees one ordinary composition per size.
"""
import re

# The sizes by the name a person uses, with the format names the service knows as aliases.
SHAPES = {"vertical": (1080, 1920), "portrait": (1080, 1350), "square": (1080, 1080), "wide": (1920, 1080)}
ALIASES = {"reel": "vertical", "story": "vertical", "post-portrait": "portrait", "slide": "wide"}
_BY_SIZE = {v: k for k, v in SHAPES.items()}

_ROOT = re.compile(r"<div\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*\bdata-composition-id\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.I)
_VIEWPORT = re.compile(r"<meta\b(?=(?:[^>\"']|\"[^\"]*\"|'[^']*')*\bname\s*=\s*[\"']?viewport\b)(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.I)


def _attr(tag, name):
    m = re.search(rf"\s{re.escape(name)}\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s>]+))", tag, re.I)
    return None if not m else next(g for g in m.groups()[1:] if g is not None)


def _set(tag, name, value):
    """The tag with attribute `name` set to `value` (added before the tag's end when absent)."""
    pat = re.compile(rf"\s{re.escape(name)}\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
    if pat.search(tag):
        return pat.sub(f' {name}="{value}"', tag, count=1)
    end = len(tag) - (2 if tag.endswith("/>") else 1)
    return f'{tag[:end]} {name}="{value}"{tag[end:]}'


def _drop(tag, name):
    return re.sub(rf"\s{re.escape(name)}\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", tag, count=1, flags=re.I)


def shape_of(size):
    return _BY_SIZE.get(tuple(size))


def main_size(html):
    """The root's own (width, height), or None."""
    m = _ROOT.search(html)
    try:
        return (int(float(_attr(m.group(0), "data-width"))), int(float(_attr(m.group(0), "data-height")))) if m else None
    except (TypeError, ValueError):
        return None


def declared(html):
    """The other sizes the root lists. → ([shape name], [problem]) — the main size, and a size named
    twice, are left out."""
    m = _ROOT.search(html)
    raw = (_attr(m.group(0), "data-sizes") or "") if m else ""
    main = shape_of(main_size(html) or ())
    out, problems = [], []
    for word in re.split(r"[\s,]+", raw.strip().lower()):
        if not word:
            continue
        name = ALIASES.get(word, word)
        if name not in SHAPES and re.fullmatch(r"\d+x\d+", word):
            name = shape_of(tuple(int(x) for x in word.split("x"))) or word
        if name not in SHAPES:
            problems.append(f'data-sizes: "{word}" is not a size; use {", ".join(SHAPES)}.')
        elif name != main and name not in out:
            out.append(name)
    return out, problems


def variant(html, shape):
    """The composition made at size `shape`: the root's data-width/data-height and data-shape, the
    viewport, and the root's box (a rule that wins over the file's own), data-sizes taken off."""
    w, h = SHAPES[shape]
    m = _ROOT.search(html)
    if not m:
        return html
    tag = _drop(_set(_set(_set(m.group(0), "data-width", w), "data-height", h), "data-shape", shape), "data-sizes")
    out = html[:m.start()] + tag + html[m.end():]
    meta = f'<meta name="viewport" content="width={w}, height={h}">'
    out, n = _VIEWPORT.subn(meta, out, count=1)
    box = f"<style data-cycls-size>#root{{width:{w}px !important;height:{h}px !important}}</style>"
    at = out.lower().find("</head>")
    if at < 0:
        at = out.lower().find("<body")
    head = (meta if not n else "") + box
    return out[:at] + head + out[at:] if at >= 0 else head + out


def mp4(name, shape):
    """Where a size's render goes: videos/<name>.<shape>.mp4."""
    return f"videos/{name}.{shape}.mp4"

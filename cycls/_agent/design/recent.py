"""What this workspace's recent designs look like, so the next one is new.

Given the same brief, a model makes the same "free" choices: the same palette, the same faces, the same glow.
Each new design's prepared spec is read for what it really holds (its ground, its accent, its faces, its look,
the stock moves in it) and kept, the last few, in `.cache/design/recent.json`. The tool's skills and guide list
them before a piece is composed, and a render that shares too much with one of them says so: a note, never a
refusal (a resize, a carousel, a campaign and a brand kit's fixed colours and faces are meant to match).
Stdlib only.
"""
import json
import pathlib
import re
import time

_KEEP = 12          # designs remembered
_LISTED = 6         # designs listed before a piece is composed
_FACE_STYLES = re.compile(r"\s+(thin|extra ?light|ultra ?light|light|regular|book|medium|semi ?bold|demi ?bold|bold|"
                          r"extra ?bold|ultra ?bold|black|heavy)(\s+italic)?$|\s+italic$", re.I)
_SOFT = 0.45        # a fill this faint, on a shape this large, is a soft blob
_BIG = 0.25         # … a quarter of the frame's width or more


def _path(root):
    return pathlib.Path(root) / ".cache" / "design" / "recent.json"


def _hex(paint):
    """A paint's first colour as #rrggbb (alpha dropped), and its alpha 0–1 → (hex, alpha), or (None, 1)."""
    if isinstance(paint, dict) and isinstance(paint.get("gradient"), list) and paint["gradient"]:
        stop = paint["gradient"][0]
        paint = stop[0] if isinstance(stop, (list, tuple)) else stop
    if not isinstance(paint, str) or not paint.startswith("#"):
        return None, 1.0
    h = paint[1:]
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    if len(h) not in (6, 8) or not re.fullmatch(r"[0-9a-fA-F]+", h):
        return None, 1.0
    return "#" + h[:6].lower(), (int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)


def _ground(fill):
    if isinstance(fill, dict) and isinstance(fill.get("gradient"), list):
        stops = [_hex(s[0] if isinstance(s, (list, tuple)) else s)[0] for s in fill["gradient"]]
        stops = [s for s in stops if s]
        return f"gradient {stops[0]}→{stops[-1]}" if stops else "gradient"
    return _hex(fill)[0]


def _family(font):
    if isinstance(font, dict):
        font = font.get("family")
    if not isinstance(font, str) or not font.strip():
        return None
    if "/" in font or font.lower().endswith((".ttf", ".otf")):
        return pathlib.PurePath(font).stem
    return _FACE_STYLES.sub("", font.strip()).strip() or None


def _walk(nodes):
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        yield n
        for key in ("children", "nodes"):
            if isinstance(n.get(key), list):
                yield from _walk(n[key])


def _frame(fp, size, fill, nodes):
    """One frame's colours, faces and stock moves, added to `fp`."""
    W = (size[0] if isinstance(size, (list, tuple)) and size else 1080) or 1080
    ground = _ground(fill)
    if ground and not fp.get("ground"):
        fp["ground"] = ground
    texts, accents = [], {}
    for n in _walk(nodes):
        t = n.get("type")
        if t == "text":
            size_ = n.get("size") or 0
            face = _family(n.get("font"))
            color, alpha = _hex(n.get("color"))
            if alpha <= 0.3 and size_ >= 160:
                fp["moves"].add("giant faint word")
            if face:
                texts.append((size_, face))
            for r in n.get("runs") or []:
                if isinstance(r, dict) and _family(r.get("font")):
                    texts.append((size_, _family(r.get("font"))))
        elif t in ("rect", "ellipse"):
            color, alpha = _hex(n.get("fill"))
            fill_ = n.get("fill")
            w = n.get("w") or 0
            radial = isinstance(fill_, dict) and fill_.get("type") == "radial"
            if t == "ellipse" and w >= _BIG * W and (radial or alpha <= _SOFT or (n.get("opacity") or 1) <= _SOFT):
                fp["moves"].add("soft glow or big faint ellipse")
            elif t == "rect" and radial and w >= _BIG * W:
                fp["moves"].add("soft glow or big faint ellipse")
            if n.get("backdropBlur"):
                fp["moves"].add("glass card")
            if t == "rect" and n.get("stroke") and not n.get("fill") and w >= 0.6 * W:
                fp["moves"].add("inset frame")
            if color and alpha > _SOFT and color != ground:
                accents[color] = accents.get(color, 0) + max(1, int(w))
        elif t == "pattern":
            fp["moves"].add("pattern")
        elif t == "image" and n.get("asset") and (n.get("w") or W) <= 0.5 * W:
            fp["moves"].add("one object")
    if texts:
        texts.sort(key=lambda x: -x[0])
        fp.setdefault("faces", [])
        for _, face in texts:
            if face not in fp["faces"]:
                fp["faces"].append(face)
    if accents and not fp.get("accent"):
        fp["accent"] = max(accents, key=accents.get)


def fingerprint(spec):
    """A prepared spec → what it looks like: {kind, ground?, accent?, faces[], look?, theme?, moves[]}."""
    fp = {"moves": set()}
    if isinstance(spec.get("deck"), dict) or isinstance(spec.get("document"), dict):
        kind = "deck" if isinstance(spec.get("deck"), dict) else "document"
        piece = spec[kind]
        fp["kind"], fp["look"] = kind, piece.get("look")
        theme = piece.get("theme")
        if isinstance(theme, str):
            fp["theme"] = theme
        elif isinstance(theme, dict):
            fp["theme"] = theme.get("base") or "minimal-light"
            fp["ground"] = _ground(theme.get("bg")) or _ground(theme.get("hero"))
            fp["accent"] = _hex(theme.get("accent"))[0]
            fp["faces"] = [f for f in (_family(theme.get("heading")), _family(theme.get("body"))) if f]
            if theme.get("decor") in ("glow", "circles"):
                fp["moves"].add("soft glow or big faint ellipse")
        for s in (piece.get("slides") or []) if kind == "deck" else []:
            if isinstance(s, dict) and isinstance(s.get("nodes"), list):
                _frame(fp, piece.get("size"), s.get("fill"), s["nodes"])
    else:
        frames = spec.get("frames") if isinstance(spec.get("frames"), list) else [spec]
        fp["kind"] = "carousel" if len(frames) > 1 else "post"
        for f in frames:
            if isinstance(f, dict):
                _frame(fp, f.get("size") or spec.get("size"), f.get("fill", spec.get("fill")), f.get("nodes"))
    fp["moves"] = sorted(fp["moves"])
    return {k: v for k, v in fp.items() if v not in (None, [], "")}


def _read(root):
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
        return [d for d in data if isinstance(d, dict) and d.get("path")] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def record(root, fig_rel, fp):
    """Keep `fp` as `fig_rel`'s, newest first; a design rendered again replaces its entry."""
    rows = [d for d in _read(root) if d.get("path") != fig_rel]
    rows.insert(0, {**fp, "path": fig_rel, "at": int(time.time())})
    path = _path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows[:_KEEP], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _ago(at, now=None):
    s = max(0, int((now or time.time()) - (at or 0)))
    if s < 3600:
        return "just now" if s < 120 else f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h ago"
    d = s // 86400
    return "yesterday" if d == 1 else f"{d} days ago"


def _line(d):
    bits = [f"{d.get('kind', 'design')}, {_ago(d.get('at'))}"]
    if d.get("ground"):
        bits.append(f"ground {d['ground']}")
    if d.get("accent"):
        bits.append(f"accent {d['accent']}")
    if d.get("faces"):
        bits.append("faces " + " / ".join(d["faces"][:2]))
    if d.get("look"):
        bits.append(f"look {d['look']}" + (f" on {d['theme']}" if d.get("theme") else ""))
    if d.get("moves"):
        bits.append("moves: " + ", ".join(d["moves"]))
    return f"- {d['path']} ({'; '.join(bits)})"


def listing(root):
    """This workspace's recent designs as lines for the model, or "" when it has none."""
    rows = _read(root)[:_LISTED]
    if not rows:
        return ""
    return ("This workspace's most recent designs, made in this chat or earlier ones (the person's own work, newest "
            "first): make the next one different from them in its "
            "concept, composition and palette or faces, unless it is meant to belong with one (design-direction, "
            "\"Never the same twice\").\n" + "\n".join(_line(d) for d in rows))


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _near(a, b, far=40):
    if not a or not b:
        return False
    if a.startswith("gradient") or b.startswith("gradient"):
        return a == b
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b))) ** 0.5 < far


def _group(kind):
    return "deck" if kind == "deck" else "document" if kind == "document" else "visual"


def shared(a, b, brand=False):
    """What design `a` shares with design `b`, as words; a brand kit's colours and faces don't count."""
    out = []
    if not brand:
        if _near(a.get("ground"), b.get("ground")):
            out.append(f"its ground ({a['ground']})")
        if a.get("faces") and b.get("faces") and a["faces"][0] == b["faces"][0]:
            out.append(f"its heading face ({a['faces'][0]})")
        if _near(a.get("accent"), b.get("accent"), 30):
            out.append(f"its accent ({a['accent']})")
    if a.get("look") and a.get("look") == b.get("look") and a.get("theme") == b.get("theme"):
        out.append(f"its look ({a['look']} on {a.get('theme') or 'minimal-light'})")
    moves = sorted(set(a.get("moves") or []) & set(b.get("moves") or []))
    if moves:
        out.append("its " + " and ".join(moves))
    return out


def remember(root, fig_rel, spec, kind, brand=False):
    """A new render's look kept, against what came before → the notes it earns ([] when none). Remembering
    never stops a render: anything that goes wrong is no note."""
    try:
        fp = {**fingerprint(spec), "kind": kind}
        note = alike(root, fig_rel, fp, brand)
        record(root, fig_rel, fp)
        return [note] if note else []
    except Exception:  # noqa: BLE001
        return []


def alike(root, fig_rel, fp, brand=False):
    """A note when `fp` shares two things or more with a recent design of its kind (not itself), and one on
    the stock glow — or None."""
    notes = []
    for d in _read(root):
        if d.get("path") == fig_rel or _group(d.get("kind")) != _group(fp.get("kind")):
            continue
        same = shared(fp, d, brand)
        if len(same) >= 2:
            notes.append(f"It shares {', '.join(same[:-1])} and {same[-1]} with {d['path']} (made {_ago(d.get('at'))}). "
                         f"Unless it is meant to match that one (a resize, a series, \"like the last one\"), change what "
                         f"it shares with one Design edit before you present it: a new design looks new.")
            break
    if "soft glow or big faint ellipse" in (fp.get("moves") or []):
        notes.append("It has a soft glow or a big faint ellipse: the decoration every AI design tool makes. Keep it "
                     "only if this concept needs it; otherwise take it out in that edit.")
    return " ".join(notes) or None

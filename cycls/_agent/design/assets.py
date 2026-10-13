"""The media library for Design.

Anywhere a design takes a picture — an image node's `src`, a deck slide's `image`, a
document's `image`, an edit's `replace_image` — the model may name one the design
service keeps instead of a file: `"asset": "paper texture"` (a few plain words) or
`"asset": "texture/ambientcg/paper006"` (its id, from `{"action": "assets"}`). The SDK
asks the service for it, saves it in the workspace (attachments/assets/…) and puts that
path in as `src`, so the rest of the pipeline sees an ordinary workspace file: the same
caps and fitting as a photo, and the file stays in the workspace for the next edit.

What an asset IS decides the node that holds it: a texture, a 3D emoji or icon, a
museum picture is an image; an illustration is an svg; a pattern — one SVG tile — is a
`pattern` node, which the service repeats over its box. A node written as another of
the three is read as the one its asset is. A licence that asks for a credit gets it in
the ack, and so does a picture that will be drawn larger than it is.

The library lives with the design service (a read-only volume there), so there is
nothing to configure here beyond DESIGN_URL.
"""
import json
import re
from pathlib import Path

from . import client

DIR = "attachments/assets"
_PICTURE_NODES = ("image", "svg", "pattern")
_SOFT = 1.6            # drawn past this many times its own pixels, a picture looks soft


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:80] or "asset"


async def _asset(root, name, kind, pick, user_id):
    """(workspace path, catalogue row) for the asset `name` — an id, or words — fetched
    once and remembered per workspace (attachments/assets/.index.json)."""
    folder = Path(root) / DIR
    index_path = folder / ".index.json"
    key = f"{name.strip().lower()}|{kind or ''}|{pick}"
    try:
        index = json.loads(index_path.read_text("utf-8"))
    except (OSError, ValueError):
        index = {}
    hit = index.get(key)
    if hit and (Path(root) / hit["path"]).is_file():
        return hit["path"], hit["asset"]
    try:
        row, data = await client.asset(name, kind=kind, pick=pick, user_id=user_id)
    except client.Unavailable:
        raise
    except RuntimeError as e:
        # A service from before the library answers its catch-all "not found".
        raise ValueError("this design service has no media library" if str(e) == "not found" else str(e)) from e
    ext = {"jpeg": "jpg"}.get(str(row.get("format") or "").lower(), str(row.get("format") or "png").lower())
    rel = f"{DIR}/{_slug(row.get('id') or name)}.{ext}"
    folder.mkdir(parents=True, exist_ok=True)
    target = Path(root) / rel
    tmp = target.with_name(f".{target.name}.part")
    tmp.write_bytes(data)
    tmp.replace(target)
    index[key] = {"path": rel, "asset": row}
    index_path.write_text(json.dumps(index, indent=1, ensure_ascii=False), "utf-8")
    return rel, row


def _place(d, row, path, node):
    """`d` — a spec node (`node`), a layout's or a document's picture, or an edit op —
    named the asset: it is given the file. → a line for the ack (or None). Raises
    ValueError with the fix."""
    kind, vector = str(row.get("kind") or ""), str(row.get("format") or "").lower() == "svg"
    what = f"{row.get('id')} ({row.get('title')})"
    if "op" in d:
        if vector:
            raise ValueError(f"{what} is {'a pattern' if kind == 'pattern' else 'an SVG'} — replace_image takes a picture; "
                             f"put it in with an `add` op: {{\"op\":\"add\",\"node\":{{\"type\":\"{'pattern' if kind == 'pattern' else 'svg'}\",\"asset\":…}}}}")
        d["src"] = path
        return None
    if not node:                                           # a slide layout's or a document's picture: left as it is
        if kind == "pattern":
            raise ValueError(f"{what} is a pattern — it fills a box as a node, {{\"type\":\"pattern\",\"asset\":…}}, "
                             f"in a design's or a hand-built slide's `nodes`; it isn't a layout's picture")
        d["src"] = path
        return None
    if d.get("type") is not None and d["type"] not in _PICTURE_NODES:
        raise ValueError(f"`asset` goes on an image, svg or pattern node, not a {d['type']} ({json.dumps(d, ensure_ascii=False)[:80]})")
    d["type"] = "pattern" if kind == "pattern" else "svg" if vector else "image"
    d["src"] = path
    if d["type"] != "image":
        d.pop("fit", None)
        return None
    if row.get("transparent"):
        d.setdefault("fit", "contain")                      # a cut-out object is shown whole, never cropped to its box
    try:
        w, h = float(d.get("w") or 0), float(d.get("h") or 0)
        iw, ih = float(row.get("width") or 0), float(row.get("height") or 0)
    except (TypeError, ValueError):
        return None
    ratios = [r for r in (w / iw if iw else 0, h / ih if ih else 0) if r]
    if not ratios:
        return None
    need = min(ratios) if d.get("fit") == "contain" else max(ratios)   # contain fits inside the box, cover fills it
    if need > _SOFT:
        return (f"{row.get('id')} is {round(iw)}×{round(ih)} px and is drawn about {need:.1f}× that — it will look soft; "
                f"draw it smaller (up to about {round(iw * _SOFT)} px wide) or take another")
    return None


async def resolve(obj, root, user_id=None):
    """Every `"asset": "<id or words>"` in a spec, deck, slide or ops list → `"src":
    "<path>"` (and the node its asset is), in place. → (lines for the ack, error or None)."""
    found = []

    def walk(v, node=False):
        """`node`: `v` is a spec node — an item of `nodes` or `children`, an add op's `node`."""
        if isinstance(v, dict):
            if isinstance(v.get("asset"), str) and v["asset"].strip():
                found.append((v, node))
            for k, x in v.items():
                if k in ("nodes", "children") and isinstance(x, list):
                    for item in x:
                        walk(item, True)
                else:
                    walk(x, k == "node" and "op" in v)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(obj)
    if not found:
        return [], None
    said, notes = {}, []
    try:
        for d, node in found:
            name = d["asset"].strip()
            pick = d.get("pick")
            pick = int(pick) if isinstance(pick, (int, float)) and pick >= 0 else 0
            kind = d.get("kind") if isinstance(d.get("kind"), str) else None   # narrows the words: "kind": "texture"
            path, row = await _asset(root, name, kind, pick, user_id)
            note = _place(d, row, path, node)
            for k in ("asset", "pick", "kind"):
                d.pop(k, None)
            rid = str(row.get("id") or "")
            line = "" if name.lower() == rid.lower() else \
                f"{json.dumps(name, ensure_ascii=False)} → the library's {rid} ({row.get('title')}, {row.get('kind')})"
            if row.get("credit"):
                line = f"{line or rid} — credit it: {row['credit']}"
            if line:
                said.setdefault(rid, line)
            if note and note not in notes:
                notes.append(note)
    except client.Unavailable as e:
        return [], f"Error: design unavailable — {e}"
    except ValueError as e:
        return [], f"Error: {e}"
    return [*said.values(), *notes], None


async def named(obj, root, user_id=None):
    """Every picture NAMED in a spec, deck, slide or ops list rather than saved — a stock
    photo to find, an asset of the library — made a workspace file, in place.
    → (lines for the ack, error or None)."""
    from . import stock
    credits, err = await stock.resolve(obj, root)
    if err:
        return [], err
    more, err = await resolve(obj, root, user_id)
    return ([], err) if err else ([*credits, *more], None)


def _row_line(a):
    size = f"{a.get('width')}×{a.get('height')}" if a.get("width") and a.get("height") else ""
    parts = [str(a.get("kind") or ""), f"{str(a.get('format') or '').upper()} {size}".strip(),
             "transparent" if a.get("transparent") else "", " ".join(a.get("colours") or [])]
    tags = ", ".join(str(t) for t in (a.get("tags") or [])[:6])
    return f"  {a.get('id')} — {a.get('title')} · " + " · ".join(p for p in parts if p) + (f" · {tags}" if tags else "")


async def listing(inp, user_id=None):
    """The `assets` action: what the library holds that the words name."""
    query = str(inp.get("query") or inp.get("q") or "").strip()
    kind = str(inp.get("kind") or "").strip().lower() or None
    try:
        data = await client.assets(query, kind=kind, user_id=user_id)
    except client.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except RuntimeError as e:
        return f"Error: {'this design service has no media library' if str(e) == 'not found' else e}."
    rows, total = data["assets"], data["total"]
    kinds = ", ".join(f"{k} ({n})" for k, n in data["kinds"].items())
    asked = (f" for {json.dumps(query, ensure_ascii=False)}" if query else "") + (f" of kind {kind}" if kind else "")
    if not rows:
        return (f"The media library has nothing{asked} — it holds {kinds}. "
                f"Try one or two plain words (paper, marble, rocket, people), or a `kind` alone.")
    head = f"The media library — {total}{asked or ' assets'}" + (f", the first {len(rows)}" if total > len(rows) else "") + ":"
    use = ("Name one where a picture goes: \"asset\": \"<id>\" — on an image node (a texture, a 3D emoji or icon, a museum "
           "picture), an svg node (an illustration) or a pattern node (a pattern); a deck slide's or a document's `image` "
           "takes {\"asset\": \"<id>\"} too. Nothing was made by this call.")
    return "\n".join([head, *(_row_line(a) for a in rows), f"The library holds {kinds}.", use])

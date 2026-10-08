"""What the model wrote, made ready for the service: a spec and its pages, a deck of
layouts, a document, a slide, an edit's ops — sizes named, numbers read, images placed,
the brand applied. Every `_prepare_*` returns what to send, or an error the model can act on."""
import json, pathlib, re
from ..paths import _resolve_path
from .brand import _HEX, _contrast, _first_color, _load_brand, _norm_hex, _readable_on
from .images import _BRAND_LOGOS, _DESIGN_IMAGES_MAX, _DESIGN_SVG_MAX, _image_slot, _place_image


# Named sizes a spec may pass as `size` instead of [W, H], so a common format is
# never guessed or mis-sized. The A4 poster is 150dpi — the default @2x render
# lands it at print-quality 300dpi.
_DESIGN_SIZES = {
    "square": [1080, 1080], "post-portrait": [1080, 1350],
    "story": [1080, 1920], "reel": [1080, 1920],
    "slide": [1920, 1080], "wide": [1920, 1080],
    "x-post": [1600, 900], "a4-poster": [1240, 1754],
}


_NUMERIC = ("x", "y", "w", "h", "size", "radius", "lineHeight", "letterSpacing",
            "opacity", "strokeWeight", "rotation", "gap", "width", "blur", "backdropBlur")


def _num(v):
    """A number the model may have quoted ("1500", "96px") → int/float, else None."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and (m := re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:px)?\s*", v)):
        f = float(m.group(1))
        return int(f) if f.is_integer() else f
    return None


def _frame_size(fr):
    """A frame's [W, H] from whatever shape the model gave it — [W, H], a preset
    name, "1080x1920", {w, h}, or width/height keys on the frame — else the
    renderer's own 1080² default. Raises ValueError for anything else."""
    s = fr.get("size")
    if s is None and "width" in fr and "height" in fr:
        s = [fr.pop("width"), fr.pop("height")]
    if isinstance(s, dict):
        s = [s.get("w", s.get("width")), s.get("h", s.get("height"))]
    if s is None:
        return [1080, 1080]
    if isinstance(s, str):
        key = s.strip().lower()
        if key in _DESIGN_SIZES:
            return list(_DESIGN_SIZES[key])
        if m := re.fullmatch(r"(\d+)\s*[x×]\s*(\d+)", key):
            return [int(m.group(1)), int(m.group(2))]
        raise ValueError(f"unknown size {s!r} — use [W, H] or one of: {', '.join(_DESIGN_SIZES)}")
    if isinstance(s, (list, tuple)) and len(s) == 2 and all((_num(v) or 0) > 0 for v in s):
        return [_num(v) for v in s]
    raise ValueError(f"`size` {s!r} isn't a size — use [W, H] or a preset ({', '.join(_DESIGN_SIZES)})")


def _prepare_spec(spec, brand, root=None):
    """The spec the service renders, made safe to draw: preset sizes resolved to
    [W, H]; a node with `text` but no `type` typed as text (the renderer silently
    drops an untyped node); fonts mapped onto Inter; image `src` files read from the
    workspace under `root` and placed (see _place_image); with a brand kit, a frame
    `fill` left out becomes the brand primary and a shape `fill` the accent; text
    with no colour gets white or near-black against its frame. Never overrides a
    colour the model set. A copy — the model's input stays as written. Returns
    (spec, error, notes), notes being lines for the model's ack."""
    if isinstance(spec.get("deck"), dict):
        return _prepare_deck(spec, brand, root)
    if spec.get("pages") is not None:
        return _prepare_pages(spec, brand, root)
    colors = {_norm_hex(m) for m in _HEX.findall(json.dumps(spec))}
    spec = json.loads(json.dumps(spec))
    frames = spec["frames"] if isinstance(spec.get("frames"), list) and spec["frames"] else [spec]
    filled, branded_fonts, image_bytes = 0, 0, 0
    shapes = []                 # what was written another way and read as what it meant: said, once each
    first_size = None
    for i, fr in enumerate(frames, 1):
        if not isinstance(fr, dict):
            continue
        try:
            fr["size"] = W, H = _frame_size(fr)
        except ValueError as e:
            return None, f"Error: {e}.", []
        # A deck is one size: PowerPoint takes the first slide's size for the whole
        # file and letterboxes the rest.
        if first_size is None:
            first_size = [W, H]
        elif [W, H] != first_size:
            return None, (f"Error: every slide of a deck must be the same size — slide 1 is "
                          f"{first_size[0]}×{first_size[1]}, slide {i} is {W}×{H}. Give every "
                          f"frame the same `size`."), []
        if brand and brand["primary"] and fr.get("fill") is None:
            fr["fill"], filled = brand["primary"], filled + 1
        bg = _first_color(fr.get("fill"))

        def prepare(n, top):
            """One node, made safe (a stack's children too). → an error, or None."""
            nonlocal filled, branded_fonts, image_bytes
            if n.get("type") is None and ("text" in n or "src" in n):
                n["type"] = "text" if "text" in n else "image"
            if n.get("type") in ("radial", "linear", "angular", "diamond") and isinstance(n.get("gradient"), list):
                # A fill, written where a node goes: a glow (or a wash) over the frame.
                fill = {k: n[k] for k in ("gradient", "center", "radius", "angle") if n.get(k) is not None}
                fill["type"] = n["type"]
                keep = {k: n[k] for k in ("id", "opacity") if n.get(k) is not None}
                n.clear()
                n.update({"type": "rect", "x": 0, "y": 0, "w": W, "h": H, "fill": fill, **keep})
                shapes.append(f"A node of type \"{fill['type']}\" was read as a rect over the whole frame with that gradient as "
                              f"its `fill` — a gradient is a fill ({{\"gradient\": […], \"type\": \"{fill['type']}\"}}), not a node.")
            if n.get("type") == "list":
                items = n.get("items") if n.get("items") is not None else n.pop("text", None)
                if isinstance(items, str):
                    items = [line for line in items.splitlines() if line.strip()]
                if isinstance(items, list):
                    # A point is its words: {"text": …} and a marker typed in front are read as that.
                    items = [i["text"] if isinstance(i, dict) and isinstance(i.get("text"), str) and "runs" not in i else i for i in items]
                    n["items"] = [re.sub(r"^\s*(?:[-–—•*·▪●]|\d{1,2}[.)])\s+", "", i).strip() if isinstance(i, str) else i for i in items]
            for k in _NUMERIC:                           # "1500" would reach the renderer as a string —
                if k in n and n[k] is not None and _num(n[k]) is None:     # and a string y sinks the text
                    return f"Error: `{k}` must be a number, not {n[k]!r} ({json.dumps(n)[:80]})."
                if k in n and n[k] is not None:
                    n[k] = _num(n[k])
            if n.get("type") == "text":
                # Fonts go to the service as written — it resolves any Google Font
                # (and says what it swapped). A brand kit's fonts fill in where the spec
                # named none: the heading face for display sizes, the body face below.
                if brand and n.get("font") is None:
                    face = brand["heading"] if (n.get("size") or 32) >= 48 else brand["body"]
                    face = face or brand["heading"] or brand["body"]
                    if face:
                        n["font"], branded_fonts = face, branded_fonts + 1
                if bg and n.get("color") is None and n.get("fill") is None:
                    n["color"] = _readable_on(bg)
            elif n.get("type") in ("rect", "ellipse", "line"):
                if n.get("fill") is None and n.get("color") is not None:
                    n["fill"] = n.pop("color")          # a shape draws `fill` only — as text reads either
                if brand and brand["accent"] and n.get("fill") is None and not n.get("stroke"):
                    n["fill"], filled = brand["accent"], filled + 1
            elif n.get("type") == "image":
                try:
                    image_bytes += _place_image(n, root)
                except ValueError as e:
                    return f"Error: {e}"
                if image_bytes > _DESIGN_IMAGES_MAX:
                    return (f"Error: the design's images total over {_DESIGN_IMAGES_MAX >> 20} MB — "
                            f"use smaller copies (longest side ~2000px).")
            elif n.get("type") in ("icon", "svg", "qr", "list", "chart", "table"):
                kind = n["type"]
                if kind == "icon" and not (isinstance(n.get("name"), str) and ":" in n["name"]):
                    return f"Error: an icon needs `name` — an Iconify name like \"lucide:rocket\" or \"mdi:coffee\" ({json.dumps(n)[:80]})."
                if kind == "svg" and n.get("src") and not n.get("svg"):
                    path = _resolve_path(str(n.pop("src")), root)
                    if not path.is_file() or path.suffix.lower() != ".svg":
                        return f"Error: svg `src` must be an .svg file in the workspace ({json.dumps(n)[:80]})."
                    if path.stat().st_size > _DESIGN_SVG_MAX:
                        return f"Error: {path.name} is over {_DESIGN_SVG_MAX >> 10} KB — use a simpler SVG (or a PNG image)."
                    n["svg"] = path.read_text(encoding="utf-8", errors="replace")
                if kind == "svg" and not (isinstance(n.get("svg"), str) and "<svg" in n["svg"]):
                    return "Error: an svg node needs `svg` (the markup) or `src` (an .svg file in the workspace)."
                if kind == "qr" and not str(n.get("text") or "").strip():
                    return "Error: a qr node needs `text` — the link or text to encode."
                if kind == "list" and not isinstance(n.get("items"), list):
                    return "Error: a list needs `items` — a list of strings."
                if kind == "chart" and not isinstance((n.get("data") or {}).get("series") or n.get("values"), list):
                    return "Error: a chart needs `data`: {labels:[…], series:[{name, values:[…]}]}."
                if kind == "table" and not isinstance(n.get("rows"), list):
                    return "Error: a table needs `rows` (a list of rows, each a list of cells) and usually `columns`."
                # Marks and text-bearing nodes read on their background like text does.
                if bg and n.get("color") is None and kind != "svg":
                    n["color"] = _readable_on(bg)
                if brand and n.get("font") is None and kind in ("list", "chart", "table") and brand["body"]:
                    n["font"], branded_fonts = brand["body"], branded_fonts + 1
            elif n.get("type") == "stack":
                kids = n.get("children")
                if not isinstance(kids, list) or not kids:
                    return f"Error: a stack needs `children` — the nodes it lays out ({json.dumps(n)[:80]})."
                for c in kids:
                    if not isinstance(c, dict):
                        return f"Error: a stack's children are nodes, not {c!r}."
                    if err := prepare(c, False):
                        return err
            else:
                return (f"Error: a node has type {n.get('type')!r} ({json.dumps(n)[:80]}) — "
                        f"every node needs a `type`: text, rect, ellipse, line, image, stack, list, "
                        f"table, chart, icon, svg or qr.")
            # Content placed wholly outside the frame is a layout built for another size:
            # the renderer would clamp every such text box to the edge, piling it up.
            # (A stack places its children itself.)
            if top and n["type"] not in ("rect", "ellipse", "line") and ((n.get("x") or 0) >= W or (n.get("y") or 0) >= H):
                what = repr(n.get("text"))[:40] if n["type"] == "text" else f"a{'n' if n['type'] == 'image' else ''} {n['type']}"
                return (f"Error: {what} starts at ({n.get('x') or 0}, {n.get('y') or 0}), outside the "
                        f"{W}×{H} frame — set the frame's `size` (e.g. \"story\" for 1080×1920) "
                        f"or move it inside.")
            return None

        for n in fr.get("nodes") or []:
            if isinstance(n, dict) and (err := prepare(n, True)):
                return None, err, []
    notes = list(dict.fromkeys(shapes))
    if branded_fonts:
        notes.append(f"Brand fonts applied to {branded_fonts} text node(s) with no font "
                     f"(heading {brand['heading'] or brand['body']}, body {brand['body'] or brand['heading']}).")
    if brand and filled:
        notes.append(f"Brand kit applied to {filled} unset fill(s) "
                     f"(primary {brand['primary']}, accent {brand['accent']}).")
    elif brand and brand["primary"] and not colors & {brand["primary"], brand["accent"]}:
        notes.append(f"Note: the workspace has a brand kit (primary {brand['primary']}, accent "
                     f"{brand['accent']}) and this design uses neither — if it should be on-brand, fix that.")
    return spec, None, notes


def _prepare_pages(spec, brand, root):
    """A design of several pages — its variants — each prepared as a design of its own
    (its own size; a carousel's frames one size). → (spec, error, notes)."""
    pages = spec.get("pages")
    if not isinstance(pages, list) or not pages:
        return None, ('Error: `pages` is a list of pages, each a design with a name: '
                      '[{"name": "Post", "size": "square", "fill": …, "nodes": […]}, …].'), []
    out, notes, seen = [], [], set()
    for n, page in enumerate(pages, 1):
        if not isinstance(page, dict):
            return None, f"Error: page {n} must be an object: {{name, size, fill, nodes}}.", []
        name = str(page.get("name") or "").strip()
        if not name:
            return None, f'Error: page {n} needs a `name` (e.g. "Post", "Story") — edits and downloads name a page.', []
        if name.lower() in seen:
            return None, f"Error: two pages are named {name!r} — every page needs its own name.", []
        seen.add(name.lower())
        if page.get("deck") is not None or page.get("pages") is not None:
            return None, (f"Error: page {name!r} is a design ({{size, fill, nodes}}) or a carousel "
                          f"({{frames}}) — a deck of layouts is a design of its own (render it by itself)."), []
        made, err, more = _prepare_spec({k: v for k, v in page.items() if k != "name"}, brand, root)
        if err:
            return None, err.replace("Error: ", f"Error: page {name!r}: ", 1), []
        out.append({"name": name[:40], **made})
        notes += [m for m in more if m not in notes]
    return {"pages": out}, None, notes


_DECK_THEMES = ("minimal-light", "minimal-dark", "bold-gradient", "editorial", "corporate", "tech-dark", "warm", "mono")


def _brand_theme(brand):
    """The deck theme a brand kit makes, on the minimal-light base: the primary as the
    hero (title, section and closing slides), the accent for highlights — swapped for
    the primary where it wouldn't read as text on white — and the brand's fonts."""
    primary, accent = brand.get("primary"), brand.get("accent") or brand.get("primary")
    theme = {"base": "minimal-light", "name": "brand"}
    hero_text = None
    if primary:
        hero_text = _readable_on(primary)
        theme.update(hero=primary, heroText=hero_text, heroMuted=hero_text + "b3")
    if accent:
        on_white = (accent if _contrast(accent, "#ffffff") >= 4.5
                    else primary if primary and _contrast(primary, "#ffffff") >= 4.5 else "#0f172a")
        theme.update(accent=on_white, accent2=accent, onAccent=_readable_on(on_white),
                     heroAccent=accent if not primary or _contrast(accent, primary) >= 3 else hero_text)
    if brand.get("heading"):
        theme["heading"] = f"{brand['heading']} Bold"
    if brand.get("body"):
        theme["body"] = brand["body"]
    return theme


def _prepare_deck(spec, brand, root):
    """A deck of layouts — {deck: {theme, slides: [{layout, …}]}} — made ready for the
    service, which lays it out (cycls-design layouts.js): the size resolved; image slots
    (a slide's `image`, a team member's `photo`, the deck's `logo` and footer logo) read
    from the workspace; theme "brand" — or no theme, when the workspace has a brand kit —
    built from the brand kit, with brand/logo.* as the deck logo; a custom slide's
    `nodes` prepared like a single design's. → (spec, error, notes)."""
    spec = json.loads(json.dumps(spec))
    deck = spec["deck"]
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        return None, "Error: a deck needs `slides` — a list of {layout, …} (the layouts are in the tool description).", []
    try:
        deck["size"] = size = _frame_size({"size": deck.get("size") or "slide"})
    except ValueError as e:
        return None, f"Error: {e}.", []
    notes, total = [], 0

    def slot(value):
        nonlocal total
        resolved, n = _image_slot(value, root)
        total += n
        if total > _DESIGN_IMAGES_MAX:
            raise ValueError(f"the deck's images total over {_DESIGN_IMAGES_MAX >> 20} MB — use smaller copies "
                             f"(longest side ~2000px)")
        return resolved

    theme = deck.get("theme")
    if theme == "brand" and not brand:
        return None, (f"Error: theme \"brand\" needs a brand kit (brand/brand.yaml) — or pick a theme: "
                      f"{', '.join(_DECK_THEMES)}."), []
    if (theme is None or theme == "brand") and brand:
        deck["theme"] = theme = _brand_theme(brand)
        logo = next((f"brand/{n}" for n in _BRAND_LOGOS if root and (pathlib.Path(root) / "brand" / n).is_file()), None)
        if logo and not deck.get("logo"):
            deck["logo"] = logo
        fonts = " / ".join(f for f in (brand.get("heading"), brand.get("body")) if f)
        notes.append(f"The deck uses the workspace brand kit as its theme (primary {brand['primary']}, accent "
                     f"{brand['accent']}{', fonts ' + fonts if fonts else ''}{', logo ' + logo if logo else ''}).")
    try:
        if deck.get("logo"):
            deck["logo"] = slot(deck["logo"])
        if isinstance(deck.get("footer"), dict) and deck["footer"].get("logo"):
            deck["footer"]["logo"] = slot(deck["footer"]["logo"])
        if isinstance(theme, dict) and theme.get("logo"):
            theme["logo"] = slot(theme["logo"])
        for i, s in enumerate(slides, 1):
            if not isinstance(s, dict):
                return None, f"Error: slide {i} must be an object: {{layout, …}}.", []
            if s.get("image"):
                s["image"] = slot(s["image"])
            for person in s.get("people") or []:
                if isinstance(person, dict) and person.get("photo"):
                    person["photo"] = slot(person["photo"])
            if isinstance(s.get("nodes"), list):
                sub, err, _ = _prepare_spec({"size": size, "fill": s.get("fill"), "nodes": s["nodes"]}, None, root)
                if err:
                    return None, err.replace("Error: ", f"Error: slide {i}: ", 1), []
                s["nodes"] = sub["nodes"]
    except ValueError as e:
        return None, f"Error: {e}.", []
    return spec, None, notes


_PAPER = {"a4": [1240, 1754], "letter": [1275, 1650], "a5": [874, 1240], "a3": [1754, 2480]}   # px at 150 dpi


_SHEET_ROWS = 2000      # rows read from a spreadsheet for a chart or a table


def _number(text):
    """A cell as a number — 1,204.5, 12%, (30) — or None."""
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return text
    s = str(text or "").strip().replace(",", "").replace("\u00a0", "").replace(" ", "")
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").rstrip("%").lstrip("$€£")
    try:
        v = float(s)
    except ValueError:
        return None
    v = -v if negative else v
    return int(v) if v.is_integer() and "." not in s else v


def _sheet(src, root, sheet=None):
    """A workspace spreadsheet — .csv / .tsv, or .xlsx (its first sheet, or `sheet`) —
    → (columns, rows): the first row names the columns. Raises ValueError with the fix."""
    if not isinstance(src, str) or not src.strip():
        raise ValueError('`from` is a workspace spreadsheet, e.g. "data/sales.csv"')
    path = _resolve_path(src, root)
    ext = path.suffix.lower()
    if ext not in (".csv", ".tsv", ".xlsx"):
        raise ValueError(f"{src} isn't a spreadsheet this reads — use a .csv, .tsv or .xlsx file")
    if not path.is_file():
        raise ValueError(f"{src} does not exist in the workspace")
    if ext == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            raise ValueError(f"{src}: reading .xlsx needs openpyxl in this agent's image — save the sheet as .csv instead")
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            if sheet is not None and str(sheet) not in book.sheetnames:
                raise ValueError(f"{src} has no sheet {str(sheet)!r} — its sheets: {', '.join(book.sheetnames)}")
            ws = book[str(sheet)] if sheet is not None else book[book.sheetnames[0]]
            table = [list(r) for _, r in zip(range(_SHEET_ROWS + 1), ws.iter_rows(values_only=True))]
        finally:
            book.close()
    else:
        import csv
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        table = [r for _, r in zip(range(_SHEET_ROWS + 1), csv.reader(text.splitlines(), delimiter="\t" if ext == ".tsv" else ","))]
    table = [r for r in table if any(c not in (None, "") for c in r)]
    if len(table) < 2:
        raise ValueError(f"{src} needs a header row and at least one row of data")
    cell = lambda v: "" if v is None else str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip()
    columns = [cell(c) or f"Column {i + 1}" for i, c in enumerate(table[0])]
    rows = [[r[i] if i < len(r) else None for i in range(len(columns))] for r in table[1:]]
    return columns, rows, cell


def _block_data(b, root):
    """A chart or a table that names its data — {"from": "data/sales.csv", …} — filled
    from that file: a chart's `x` (the column of labels; the first when not said) and `y`
    (the columns of numbers; every one when not said), a table's `columns` (a choice, in
    order) and `limit`. Raises ValueError with the fix."""
    chart, table = b.get("chart"), b.get("table")
    if isinstance(chart, dict) and chart.get("from"):
        columns, rows, cell = _sheet(chart["from"], root, chart.get("sheet"))

        def col(name):
            if str(name) not in columns:
                raise ValueError(f"{chart['from']} has no column {json.dumps(str(name))} — its columns: {', '.join(columns)}")
            return columns.index(str(name))
        x = col(chart["x"]) if chart.get("x") is not None else 0
        given = chart.get("y")
        ys = [col(y) for y in (given if isinstance(given, list) else [given])] if given is not None else [
            i for i in range(len(columns)) if i != x and rows and all(_number(r[i]) is not None for r in rows if r[i] not in (None, ""))
            and any(r[i] not in (None, "") for r in rows)]
        if not ys:
            raise ValueError(f"{chart['from']} has no column of numbers to chart — its columns: {', '.join(columns)}")
        series = []
        for i in ys:
            values = [_number(r[i]) for r in rows]
            if any(v is None for v in values):
                raise ValueError(f"{chart['from']}: column {json.dumps(columns[i])} isn't all numbers")
            series.append({"name": columns[i], "values": values})
        rest = {k: v for k, v in chart.items() if k not in ("from", "sheet", "x", "y")}
        b["chart"] = {**rest, "data": {"labels": [cell(r[x]) for r in rows], "series": series}}
    if isinstance(table, dict) and table.get("from"):
        columns, rows, cell = _sheet(table["from"], root, table.get("sheet"))
        pick = table.get("columns")
        if isinstance(pick, list) and pick:
            missing = [str(c) for c in pick if str(c) not in columns]
            if missing:
                raise ValueError(f"{table['from']} has no column {json.dumps(missing[0])} — its columns: {', '.join(columns)}")
            order = [columns.index(str(c)) for c in pick]
        else:
            order = list(range(len(columns)))
        limit = _num(table.get("limit"))
        if limit and limit > 0:
            rows = rows[:int(limit)]
        rest = {k: v for k, v in table.items() if k not in ("from", "sheet", "columns", "limit")}
        b["table"] = {**rest, "columns": [columns[i] for i in order], "rows": [[cell(r[i]) for i in order] for r in rows]}


def _prepare_document(spec, brand, root):
    """A document — {document: {title, sections: [{title, blocks: […]}]}} — made ready for
    the service, which designs and paginates it (cycls-design document.js / flow.js):
    every image (the cover's, the logo, an `image` block's, wherever it sits) read from
    the workspace; theme "brand" — or no theme, when the workspace has a brand kit —
    built from the kit, with brand/logo.* as the logo; hand-built `nodes` and `pages`
    prepared like a single design's. → (spec, error, notes)."""
    spec = json.loads(json.dumps(spec))
    doc = spec["document"]
    sections = doc.get("sections")
    if not isinstance(sections, list) or not sections:
        return None, ("Error: a document needs `sections` — a list of {title, blocks: […]} "
                      "(the blocks are in the tool description)."), []
    if not str(doc.get("title") or "").strip():
        return None, "Error: a document needs a `title`.", []
    notes, total = [], 0

    def slot(value):
        nonlocal total
        if isinstance(value, dict) and (isinstance(value.get("image"), str) or isinstance(value.get("svg"), str)):
            return value                                      # resolved already
        resolved, n = _image_slot(value, root)
        total += n
        if total > _DESIGN_IMAGES_MAX:
            raise ValueError(f"the document's images total over {_DESIGN_IMAGES_MAX >> 20} MB — use smaller copies "
                             f"(longest side ~2000px)")
        return resolved

    def nodes_of(nodes, size, fill=None):
        sub, err, _ = _prepare_spec({"size": size, "fill": fill, "nodes": nodes}, None, root)
        if err:
            raise ValueError(err.replace("Error: ", "", 1).rstrip("."))
        return sub["nodes"]

    def block(b):
        """One block's images and hand-built nodes, wherever they are nested."""
        if not isinstance(b, dict):
            return b
        for key in ("image", "photo", "picture"):
            if b.get(key):
                b[key] = slot(b[key])
        if str(b.get("type") or "") in ("image", "photo", "picture") and b.get("src") and not b.get("image"):
            b["image"] = slot(b.pop("src"))
        if isinstance(b.get("columns"), list):
            b["columns"] = [[block(x) for x in col] if isinstance(col, list) else block(col) for col in b["columns"]]
        if isinstance(b.get("nodes"), list):
            b["nodes"] = nodes_of(b["nodes"], [100000, 100000])
        _block_data(b, root)                                  # a chart / a table read from a spreadsheet
        return b

    theme = doc.get("theme")
    if theme == "brand" and not brand:
        return None, (f"Error: theme \"brand\" needs a brand kit (brand/brand.yaml) — or pick a theme: "
                      f"{', '.join(_DECK_THEMES)}."), []
    if (theme is None or theme == "brand") and brand:
        doc["theme"] = _brand_theme(brand)
        logo = next((f"brand/{n}" for n in _BRAND_LOGOS if root and (pathlib.Path(root) / "brand" / n).is_file()), None)
        if logo and not doc.get("logo"):
            doc["logo"] = logo
        fonts = " / ".join(f for f in (brand.get("heading"), brand.get("body")) if f)
        notes.append(f"The document uses the workspace brand kit as its theme (primary {brand['primary']}, accent "
                     f"{brand['accent']}{', fonts ' + fonts if fonts else ''}{', logo ' + logo if logo else ''}).")
    size = doc.get("size") or "a4"
    paper = list(_PAPER.get(str(size).lower().replace("-landscape", "").replace(" landscape", ""), _PAPER["a4"])) \
        if isinstance(size, str) else size
    try:
        if doc.get("logo"):
            doc["logo"] = slot(doc["logo"])
        if isinstance(doc.get("cover"), dict) and doc["cover"].get("image"):
            doc["cover"]["image"] = slot(doc["cover"]["image"])
        for i, s in enumerate(sections, 1):
            if not isinstance(s, dict):
                return None, f"Error: section {i} must be an object: {{title, blocks: […]}}.", []
            if isinstance(s.get("blocks"), list):
                s["blocks"] = [block(b) for b in s["blocks"]]
        for i, p in enumerate(doc.get("pages") or [], 1):
            if not isinstance(p, dict) or not isinstance(p.get("nodes"), list):
                return None, f"Error: pages[{i}] must be {{nodes: [spec nodes], fill?}} — a hand-built page.", []
            p["nodes"] = nodes_of(p["nodes"], paper, p.get("fill"))
    except ValueError as e:
        return None, f"Error: {e}.", []
    return spec, None, notes


_OP_NUMERIC = ("x", "y", "dx", "dy", "w", "h", "size", "radius", "opacity", "letterSpacing",
               "lineHeight", "strokeWeight", "frame")


def _prepare_ops(ops, root):
    """Edit ops made safe to send: numbers the model quoted become numbers; a
    replace_image `src` (a workspace file) becomes the image bytes; an `add`ed node
    goes through the render path (types, numbers, image files). → (ops, error)."""
    if not isinstance(ops, list):
        return None, "Error: `ops` must be a list of operations."
    ops = json.loads(json.dumps(ops))
    for k, op in enumerate(ops, 1):
        if not isinstance(op, dict) or not op.get("op"):
            return None, f"Error: op {k} must be an object with an `op` (set_text, style, move, …)."
        for key in _OP_NUMERIC:
            if key in op and op[key] is not None:
                if (v := _num(op[key])) is None:
                    return None, f"Error: op {k}: `{key}` must be a number, not {op[key]!r}."
                op[key] = v
        if op["op"] == "replace_image":
            probe = {"src": op.pop("src", None), "w": 1, "h": 1}
            try:
                _place_image(probe, root)
            except ValueError as e:
                return None, f"Error: op {k}: {e}"
            op["image"] = probe["image"]
        elif op["op"] == "add":
            if not isinstance(op.get("node"), dict):
                return None, f"Error: op {k}: `add` needs a `node` (a spec node, e.g. a text or a stack)."
            spec, err, _ = _prepare_spec({"size": [100000, 100000], "nodes": [op["node"]]}, None, root)
            if err:
                return None, err.replace("Error: ", f"Error: op {k}: ", 1)
            op["node"] = spec["nodes"][0]
        elif op["op"] == "page_add":
            # A new page is a design: prepared as a render's is (sizes, brand, images).
            if not isinstance(op.get("spec"), dict) or op["spec"].get("deck") or op["spec"].get("pages"):
                return None, (f"Error: op {k}: `page_add` needs `spec` — the page's design, "
                              f"{{size, fill, nodes}} (or a carousel's {{frames}}).")
            spec, err, _ = _prepare_spec(op["spec"], _load_brand(root) if root else None, root)
            if err:
                return None, err.replace("Error: ", f"Error: op {k}: ", 1)
            op["spec"] = spec
    return ops, None


def _mend_json_tail(text):
    """JSON text that is right up to its last value and closed with the wrong brackets —
    one too many, one too few, a `]` for a `}` — read as closed where its content ends.
    → the object, or None when that is not what is wrong with it: broken anywhere else,
    cut off inside a string or after a comma, or ending with no closing bracket at all (it
    ran out of room, and more than brackets is missing)."""
    body = text.rstrip()
    tail = len(body)
    while tail and body[tail - 1] in "]} \t\r\n":
        tail -= 1
    if tail == len(body):
        return None                                           # no closing bracket at its end: cut off
    stack, quoted, escaped = [], False, False
    for ch in body[:tail]:
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                return None                                   # wrong before its end
    if quoted or not stack:
        return None
    try:
        return json.loads(body[:tail] + "".join(reversed(stack)))
    except json.JSONDecodeError:
        return None


def _prepare_slide(slide, settings, root):
    """A new or rebuilt slide, made ready the way a deck's slides are (_prepare_deck):
    → (slide, the deck settings with their images resolved, error)."""
    if not isinstance(slide, dict) or not (slide.get("layout") or isinstance(slide.get("nodes"), list)):
        return None, None, ('Error: `slide` is a layout slide ({"layout": "bullets", "title": …, "bullets": […]}) '
                            'or a hand-built one ({"nodes": […], "fill"?}).')
    spec, err, _ = _prepare_deck({"deck": {**settings, "slides": [slide]}}, None, root)
    if err:
        return None, None, err
    deck = spec["deck"]
    return deck.pop("slides")[0], deck, None

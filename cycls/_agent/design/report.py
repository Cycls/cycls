"""What the tool tells the model about a design: its outline (`inspect`), which parts an
edit touched, how two saves of a design differ, and the layout check's findings in words."""
import json
from .prepare import _num


def _outline_text(rel, frames, pages=None, page=None):
    """A design's outline (from the service's inspect) as compact lines for the model:
    each frame, then each node — name, type, box, and its text/font/colour or fill. A
    design of several `pages` says which one this is, and names the others."""
    several = pages and len(pages) > 1
    where = f"{rel} — page {json.dumps(page, ensure_ascii=False)}" if several else rel
    others = ""
    if several:
        listed = ", ".join(json.dumps(p["name"], ensure_ascii=False) for p in pages)
        others = (f" This design has {len(pages)} pages: {listed} — inspect or edit another by "
                  f"passing its name as `page`.")
    if not frames:
        return f"{where} has no frames.{others}"
    out = [f"{where} — {len(frames)} frame{'s' if len(frames) != 1 else ''}. Edit with ops that name these nodes.{others}"]
    for f in frames:
        w, h = (f.get("size") or [0, 0])[:2]
        meta = "".join(f", {k} {json.dumps(f[k], ensure_ascii=False)}" for k in ("title", "transition") if f.get(k))
        out.append(f"slide {f.get('slide')} \"{f.get('name', '')}\" ({w}×{h}"
                   f"{', fill ' + f['fill'] if f.get('fill') else ''}{meta}):")
        if f.get("notes"):
            notes = str(f["notes"])
            out.append(f"  notes: {json.dumps(notes[:300] + ('…' if len(notes) > 300 else ''), ensure_ascii=False)}")
        if f.get("source"):
            # A layout slide as it was asked for — what update_slide re-sends, changed.
            source = str(f["source"])
            out.append(f"  layout source: {source[:1500]}{' …' if len(source) > 1500 else ''}")
        for n in f.get("nodes") or []:
            box = f"({n.get('x')},{n.get('y')} {n.get('w')}×{n.get('h')})"
            bits = [f"  {n.get('name')}", n.get("type", ""), box]
            if n.get("in"):
                bits.append(f"in {n['in']}")
            if "text" in n:
                bits.append(json.dumps(n["text"], ensure_ascii=False))
                bits.append(f"{n.get('font')} {n.get('size')}px {n.get('color', '')}".strip())
                if n.get("align"):
                    bits.append(f"align {n['align']}")
            elif n.get("type") in ("icon", "svg", "qr", "line") and (n.get("icon") or n.get("color")):
                # A mark is one part: which icon it is and its colour (what `style` sets).
                if n.get("icon"):
                    bits.append(n["icon"])
                if n.get("color"):
                    bits.append(f"color {n['color']}")
            else:
                if n.get("fill") and n["fill"] != "none":
                    bits.append(f"fill {n['fill']}")
                if n.get("radius"):
                    bits.append(f"radius {n['radius']}")
                if n.get("stroke"):
                    bits.append(f"stroke {n['stroke']}")
            if n.get("opacity") is not None:
                bits.append(f"opacity {n['opacity']}")
            out.append("  ".join(str(b) for b in bits if b != ""))
        if f.get("more"):
            out.append(f"  … and {f['more']} more parts of this slide are not listed (they are still edited by name).")
    return "\n".join(out)


def _edit_names(r):
    """What an ops edit touched, by name — the parts it changed, the ones it made (a copy
    and an added part get names of their own), and which part a name that wasn't one
    turned out to be. The next edit names them as they are, with no `inspect` between."""
    out = ""
    if r.get("changed"):
        out += f" Changed: {', '.join(r['changed'][:30])}."
    if r.get("added"):
        out += f" Added: {', '.join(r['added'][:30])}."
    for asked, name in (r.get("resolved") or [])[:10]:
        out += f" {json.dumps(asked, ensure_ascii=False)} is named {name} — use that name."
    return out


def _said(text, most=300):
    """A comment's words on one line, in quotes."""
    text = " ".join(str(text or "").split())
    return json.dumps(text[:most] + ("…" if len(text) > most else ""), ensure_ascii=False)


def _thread_said(t, replies=1):
    """`Sara: "…"` and what was answered: the last `replies` of them (0: only how many)."""
    who = lambda a: (a or {}).get("name") or "Someone"
    out = f"{who(t.get('author'))}: {_said(t.get('text'))}"
    answers = t.get("replies") or []
    if answers:
        out += f" · {len(answers)} repl{'y' if len(answers) == 1 else 'ies'}"
        shown = answers[-replies:] if replies else []
        if shown:
            out += (", last " if len(answers) > len(shown) else ": ") + "; ".join(f"{who(r.get('author'))}: {_said(r.get('text'), 200)}" for r in shown)
    return out


def _comments_on_page(threads, frames):
    """The open comments on the page `inspect` shows, each where it is now: the slide —
    by its name, so a slide that was moved keeps its comments — and the part of it the
    pin sits on, read from the same outline. "" when there are none."""
    from .comments import node_at, place
    names = [f.get("name") or "" for f in frames]
    lines = []
    for t in threads:
        at = place(t, names)
        if at is None:
            where = "a slide that is gone"
        else:
            node = node_at(frames[at].get("nodes"), t.get("x", 0), t.get("y", 0))
            where = f"slide {frames[at].get('slide', at + 1)}" + (f" on {node.get('name')}" if node and node.get("name") else "")
        lines.append(f"  #{t.get('n')} {where} — {_thread_said(t)}")
    if not lines:
        return ""
    n = len(lines)
    return (f"{n} open comment{'s' if n != 1 else ''} pinned on this page by the people working on it "
            f"(`comments` lists them whole, answers and resolves them):\n" + "\n".join(lines))


def _comments_listing(rel, threads):
    """Every comment on a design, for the `comments` action: the open ones whole, then
    the resolved ones in a line each."""
    def where(t):
        page = f"page {json.dumps(t['page'], ensure_ascii=False)}, " if t.get("page") else ""
        name = f" {json.dumps(t['frame_name'], ensure_ascii=False)}" if t.get("frame_name") else ""
        return f"{page}slide {int(t.get('frame') or 0) + 1}{name} at ({round(t.get('x', 0))}, {round(t.get('y', 0))})"
    if not threads:
        return f"{rel} has no comments."
    opened = [t for t in threads if not t.get("resolved")]
    closed = [t for t in threads if t.get("resolved")]
    out = [f"{rel} — {len(opened)} open comment{'s' if len(opened) != 1 else ''}, {len(closed)} resolved."]
    for t in opened:
        out.append(f"#{t.get('n')} {where(t)}, {str(t.get('at') or '')[:10]} — {_thread_said(t, replies=20)}")
    if closed:
        out.append("Resolved:")
        out += [f"  #{t.get('n')} {where(t)} — {_thread_said(t, replies=0)}" for t in closed[-20:]]
    if opened:
        out.append("A slide's number is where the comment was pinned; `inspect` shows each open one on the slide and the part it "
                   "sits on now. Answer one with {\"action\": \"comments\", \"name\": …, \"number\": <its #>, \"reply\": \"…\"} and close "
                   "it with \"resolve\": true — after the change it asks for is made.")
    return "\n".join(out)


_OUTLINE_STYLE = ("font", "size", "color", "fill", "radius", "stroke", "rotation", "opacity", "align")


def _page_changes(before, after):
    """Two outlines of a document's pages — as rendered, and as they are now — → what
    was changed, a line a page: a text's new wording, the nodes moved or restyled, the
    ones added and removed."""
    def pair(new, old):
        """A text's wording now and before, each shown from just ahead of where they part
        (a long paragraph changed near its end is not its opening twice)."""
        same = next((i for i, (x, y) in enumerate(zip(new, old)) if x != y), min(len(new), len(old)))
        start = max(0, same - 60) if max(len(new), len(old)) > 300 else 0
        start = new.rfind(" ", 0, start) + 1 if start else 0
        show = lambda t: (("…" if start else "") + t[start:start + 300] + ("…" if len(t) > start + 300 else "")).replace("\n", " ")
        return show(new), show(old)
    count = lambda n, what: f"{n} node{'' if n == 1 else 's'} {what}"
    lines = []
    if len(before) != len(after):
        lines.append(f"it had {len(before)} pages as rendered and has {len(after)} now")
    for i, (a, b) in enumerate(zip(before, after), 1):
        old = {n.get("name"): n for n in reversed(a.get("nodes") or [])}
        new = {n.get("name"): n for n in reversed(b.get("nodes") or [])}
        texts, moved, added = [], [], 0
        for key in (n.get("name") for n in b.get("nodes") or []):
            n, o = new[key], old.get(key)
            if n is None or key in texts or key in moved:
                continue
            if o is None:
                added += 1
            elif str(n.get("text") or "") != str(o.get("text") or ""):
                now, was = pair(str(n.get("text") or ""), str(o.get("text") or ""))
                texts.append(f'"{key}" now reads "{now}" (was "{was}")')
            elif (any(abs((_num(n.get(k)) or 0) - (_num(o.get(k)) or 0)) > 1 for k in ("x", "y", "w", "h"))
                  or any(n.get(k) != o.get(k) for k in _OUTLINE_STYLE)) and key not in moved:
                moved.append(key)
            new[key] = None                                   # a name used twice on a page is told once
        removed = sum(1 for key in old if key not in new)
        parts = [*texts]
        if moved:
            parts.append(", ".join(f'"{k}"' for k in moved[:5]) + (f" and {len(moved) - 5} more" if len(moved) > 5 else "") + " moved, resized or restyled")
        if added:
            parts.append(count(added, "added"))
        if removed:
            parts.append(count(removed, "removed"))
        if parts:
            lines.append(f"page {i}: " + "; ".join(parts))
    return lines[:14]


def _layout_check(lint, fmt):
    """The service's layout check of a render, as one line for the ack: what's
    wrong, where, and the fix — the mechanical backstop to the model's own look."""
    if not lint:
        return " Layout check: clean."
    slide = fmt == "pptx" or any(i.get("frame") for i in lint)

    def line(i):
        where = f"slide {int(i.get('frame') or 0) + 1}: " if slide else ""
        if i.get("page"):
            where = f"page {json.dumps(i['page'], ensure_ascii=False)}: " + where
        return f"{where}{i.get('node', '')} {i.get('issue', '')} — {i.get('fix', '')}"
    items = [line(i) for i in lint[:6]]
    more = f" (+{len(lint) - 6} more)" if len(lint) > 6 else ""
    return (f" Layout check found {len(lint)} issue{'s' if len(lint) != 1 else ''}{more}: "
            + "; ".join(items) + ". Fix these before you present.")

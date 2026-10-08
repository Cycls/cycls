"""A design's files in the workspace: the formats it is saved as, a name not yet taken,
the designs that are there, a document's pages kept as they were rendered, and the pages
of a render written out."""
import asyncio, base64, json, os, pathlib
from .images import _DESIGN_QA_MAX, _DESIGN_QA_SLIDES
from .report import _layout_check


_DESIGN_EXTS = {"png", "jpg", "webp", "svg", "pptx", "pdf"}
# Formats that are the whole deck in one file (every other format is per frame).
_DECK_EXTS = ("pptx", "pdf")


def _dedupe_design_name(designs_dir, name, fmt):
    """A base name whose `<name>.<fmt>` and `<name>.fig` are both free under
    `designs_dir`, so a fresh render never overwrites an existing design:
    `launch`, else `launch-2`, `launch-3`, … The render output and its `.fig`
    stay paired under one base. (`edit` targets an existing design — it does not
    dedupe.)"""
    def taken(base):
        return any((designs_dir / f).exists() for f in
                   (f"{base}.{fmt}", f"{base}.fig", f"{base}-slide-1.{fmt}", f"{base}.deck.json"))
    if not taken(name):
        return name
    n = 2
    while taken(f"{name}-{n}"):
        n += 1
    return f"{name}-{n}"


def _designs_there(root):
    """The designs in a workspace, by name — for "no such design: there are …"."""
    names = sorted(p.stem for p in (pathlib.Path(root) / "designs").glob("*.fig")) if (pathlib.Path(root) / "designs").is_dir() else []
    return ", ".join(names[:30]) + (", …" if len(names) > 30 else "") if names else "none yet"


async def _write_beside(path, data):
    tmp = path.with_name(f".{path.name}.part")
    await asyncio.to_thread(tmp.write_bytes, data)
    await asyncio.to_thread(tmp.replace, path)


def _rendered_copy(root, fig_rel):
    """Where a document's .fig is kept as it was rendered — to tell, later, what was
    changed on its pages by hand."""
    import hashlib
    return pathlib.Path(root) / ".cache" / "design" / f"{hashlib.sha1(fig_rel.encode('utf-8')).hexdigest()[:16]}.rendered.fig"


async def _save_pages(r, name, fmt, workspace, notes):
    """A render of several pages, saved: the one `.fig`, and each page's image —
    `<name>.<fmt>` the first, `<name>-page-<n>.<fmt>` the others (design/refresh.py
    keeps them in step). It opens in the editor on its first page."""
    from cycls._agent.design.refresh import page_file
    requested = name
    root = pathlib.Path(workspace.root)
    name = _dedupe_design_name(root / "designs", name, fmt)
    (root / "designs").mkdir(parents=True, exist_ok=True)
    fig_rel = f"designs/{name}.fig"
    await asyncio.to_thread((root / fig_rel).write_bytes, r.fig)
    images = r.page_images or [r.image]
    listed = []
    for place, (page, data) in enumerate(zip(r.pages, images), 1):
        rel = f"designs/{page_file(name, place, fmt)}"
        if data:
            await asyncio.to_thread((root / rel).write_bytes, data)
        frames = f", {page['frames']} slides" if page["frames"] > 1 else ""
        listed.append(f"{json.dumps(page['name'], ensure_ascii=False)} ({rel if data else 'empty'}{frames})")
    note = f" (named '{name}' so it doesn't overwrite the existing '{requested}')" if name != requested else ""
    editor = bool(os.environ.get("DESIGN_EDITOR_URL"))
    ack = (f"Design saved as ONE file, {fig_rel}{note}, with {len(r.pages)} pages: {'; '.join(listed)}. "
           + (f"It's OPEN in the in-canvas editor on its first page — the user switches pages in the "
              f"editor's Pages panel (top left), and Preview and the downloads (PNG, PDF) act on the "
              f"page in view. " if editor else "Its first page is opened on the canvas. ")
           + f"Change a page with Design edit {{page: \"<its name>\", ops}}; add or copy one with the "
             f"page_add / page_duplicate ops.")
    first = f"designs/{page_file(name, 1, fmt)}"
    ui = {"type": "ui", "action": "open_canvas", **({"path": fig_rel, "name": f"{name}.fig"} if editor
                                                     else {"path": first, "name": first.rsplit("/", 1)[-1]})}
    for line in notes:
        ack += " " + line
    ack += _layout_check(r.lint, fmt)
    blocks, total = [], 0
    labels = r.preview_pages + [""] * (len(r.previews) - len(r.preview_pages))
    for label, jpg in list(zip(labels, r.previews))[:_DESIGN_QA_SLIDES]:
        if blocks and total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        blocks += [{"type": "text", "text": f"Page {json.dumps(label, ensure_ascii=False)}:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if not blocks:
        return {"_model": ack, "_ui": ui}
    shown = len(blocks) // 2
    which = "Every page is attached" if shown == len(r.previews) else f"The first {shown} of {len(r.previews)} frames are attached"
    ack += (f" {which} — QA EACH page before you present, as a design in its own right: its headline "
            "clearly dominant; margins ~8–10%, nothing crammed at an edge or left over from another "
            "size; every text legible on what's behind it; nothing overlapping or cut off; copy exactly "
            "right; and the pages recognisably ONE piece of work (palette, fonts, voice). If anything "
            "is off, fix it now with Design edit on that page (don't re-render), then present.")
    return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}

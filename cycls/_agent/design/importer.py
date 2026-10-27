"""The Design tool's `import` action: a PowerPoint deck brought in as a Design deck — each slide drawn as
PowerPoint draws it (its master and layout, placeholders, pictures, shapes, tables, charts, SmartArt as shapes,
speaker notes), every shape and text named as in the file — so the person can open it in the editor, present it
and download it, and the agent can change it slide by slide. The .pptx itself is never changed. The service does
the reading and drawing (cycls-design src/pptx); a deck over 60 slides comes in parts, each added to the last."""
import asyncio, base64, pathlib, re

PPTX_EXTS = (".pptx", ".ppsx", ".potx", ".pptm", ".ppsm", ".potm")
_PPTX_MAX = 22 * 1024 * 1024          # the service takes 30 MB a request; base64 is a third bigger
_SLIDES_MAX = 150                     # slides brought in, at most
_UPLOAD_ID = re.compile(r"^[0-9a-f]{8}-")   # an upload's name in attachments/ starts with its id


def import_name(src, folder=""):
    """Where an imported deck is saved (its path without `.fig`): beside the .pptx — or, for an upload, in the
    folder the person has open, named as they named the file."""
    from .files import _stem_of
    path = str(src).replace("\\", "/").strip().lstrip("/")
    stem = path.rsplit(".", 1)[0]
    if path.startswith("attachments/"):
        return _stem_of(_UPLOAD_ID.sub("", stem.rsplit("/", 1)[-1]) or "deck", folder)
    return _stem_of(stem)


def _summary(report, limit=10):
    """What changed on the way in, said once each (the service counts repeats: "(3×)")."""
    lines = list(dict.fromkeys(str(r).strip() for r in report if str(r).strip()))
    shown = lines[:limit]
    more = len(lines) - len(shown)
    return shown + ([f"…and {more} more"] if more > 0 else [])


async def import_pptx(inp, workspace, name):
    from cycls._agent import design
    from ..paths import _resolve_path
    from .files import _free_design, _opened
    from .images import _DESIGN_QA_MAX
    src = inp.get("path") or inp.get("src")
    if not isinstance(src, str) or not src.strip():
        return ("Error: `import` needs `path` — the PowerPoint file in the workspace, e.g. attachments/q3-review.pptx. "
                "Nothing was done.")
    if not src.lower().endswith(PPTX_EXTS):
        return (f"Error: `import` brings in a PowerPoint deck (.pptx); {src} isn't one. A PDF is read with `extract`. "
                "Nothing was done.")
    try:
        path = _resolve_path(src, workspace.root)
    except ValueError as e:
        return f"Error: {e}. Nothing was done."
    if not path.is_file():
        return f"Error: {src} doesn't exist. Nothing was done."
    data = await asyncio.to_thread(path.read_bytes)
    if len(data) > _PPTX_MAX:
        return (f"Error: {src} is {len(data) / 1048576:.0f} MB — more than the {_PPTX_MAX // 1048576} MB a deck can be "
                "to come into Design (big videos and photos make it so). Nothing was done.")
    subject = getattr(workspace, "subject", None)
    keep = {"kind": "deck", "imported": {"from": src}}
    fig, first, start, parts = None, None, 0, 0
    try:
        while True:
            r = await design.import_pptx(data, user_id=subject, start=start, fig=fig,
                                         keep=keep if first is None else None, preview=first is None)
            first = first or r
            fig, parts = r["fig"], parts + 1
            if r["next"] is None or r["next"] >= _SLIDES_MAX:
                break
            start = r["next"]
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: {src} couldn't be brought into Design — {e}. Nothing was saved."
    count = first["count"] or len(first["slides"])
    made = len(r["slides"])                         # (a later part's reply lists every slide so far)
    root = pathlib.Path(workspace.root)
    requested, name = name, await asyncio.to_thread(_free_design, root, name)
    fig_rel = f"{name}.fig"
    await asyncio.to_thread((root / fig_rel).parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread((root / fig_rel).write_bytes, fig)
    from cycls._agent.design import refresh
    refresh.schedule(workspace.root, fig_rel, subject)
    note = f", named '{name}' so it doesn't overwrite the existing '{requested}'" if name != requested else ""
    ack, ui = _opened(fig_rel, f"Deck imported from {src} ({count} slide{'s' if count != 1 else ''}{note})")
    ack += f" {src} itself is left as it was."
    if made < count:
        ack += f" Only its first {made} slides came in (a deck is brought in {_SLIDES_MAX} slides at most)."
    changed = _summary(first["report"] + (r["report"] if r is not first else []))
    if changed:
        ack += " Not everything in a PowerPoint file has a Design equivalent — what changed on the way in: " + "; ".join(changed) + "."
    ack += (" Every shape and text keeps its PowerPoint name — Design inspect lists them slide by slide. To change "
            "a slide, Design edit with `frame` (the slide's index from 0) and the node's name; a text with several "
            "paragraphs is a group of '<name> para N' texts. A new slide in the deck's look: duplicate_slide a similar "
            "one, then edit it (update_slide can't rebuild an imported slide — it has no layout). When the person "
            "wants a .pptx back, `export` writes one from the design.")
    blocks, total = [], 0
    for n, jpg in enumerate(first["previews"][:12], 1):
        if blocks and total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        blocks += [{"type": "text", "text": f"Slide {n}:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpg).decode()}}]
    for span, jpg in zip(first["sheet_pages"], first["sheets"]):
        if total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        blocks += [{"type": "text", "text": f"Slides {span[0]}–{span[1]}, small:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpg).decode()}}]
    if blocks:
        ack += (" The slides as they came in are attached — look them over: if a slide looks wrong compared with what "
                "the person expects, tell them plainly rather than redrawing it unasked.")
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    return {"_model": ack, "_ui": ui}

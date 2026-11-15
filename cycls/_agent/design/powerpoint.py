"""The Design tool's `import` action: a PowerPoint deck the person brought, opened as a design to change.

The service (cycls-design `POST /import`) reads the .pptx into a design — every slide a frame, drawn as
PowerPoint draws it, every shape named after its PowerPoint shape — up to 60 slides a call. The parts are
asked for here, not by the model, and the design is written only when the whole deck is in. A file already
brought in points at its design instead of making a second one: an import asked for again is no new work."""
import asyncio, base64, hashlib, json, pathlib
from ..paths import _resolve_path
from .images import _DESIGN_QA_MAX, _DESIGN_QA_SLIDES

_DECK_SUFFIXES = (".pptx", ".pptm", ".ppsx", ".ppsm", ".potx", ".potm")   # PowerPoint's own (OOXML) files
_SERVICE_BODY = 30 << 20     # the service's request limit (cycls-design LIMITS.body)
_IMPORT_MAX = 22 << 20       # a deck, base64 in one request, under that
_IMPORT_PARTS = 8            # requests for one deck: up to 480 slides at 60 a part
_INDEX = (".cache", "design", "imports.json")   # a deck's sha256 → the design it was brought in as


def _index_path(root):
    return pathlib.Path(root, *_INDEX)


def _imported_as(root, sha):
    """The design a file with this sha256 was brought in as, while it is still there; else None."""
    try:
        rel = json.loads(_index_path(root).read_text(encoding="utf-8")).get(sha, {}).get("fig")
    except (OSError, ValueError, AttributeError):
        return None
    return rel if isinstance(rel, str) and (pathlib.Path(root) / rel).is_file() else None


def _remember(root, sha, fig_rel, src):
    path = _index_path(root)
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
        index = index if isinstance(index, dict) else {}
    except (OSError, ValueError):
        index = {}
    index[sha] = {"fig": fig_rel, "source": src}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _mb(n):
    return f"{n / 1048576:.1f}".rstrip("0").rstrip(".")


def _how_to_change(fig_rel, name):
    return (f"It is the person's own deck, drawn as PowerPoint draws it, and every shape on it is named after its "
            f"PowerPoint shape: `inspect {{\"name\": {json.dumps(name, ensure_ascii=False)}}}` lists them, slide by slide, "
            f"with their text. Change what they ask with `edit` — ops by those names, `frame` the slide from 0 — and "
            f"its slides with add_slide (laid out in the deck's own colours and fonts) / move_slide / duplicate_slide / "
            f"delete_slide / update_slide {{number, notes|title}}. update_slide with a `slide` replaces that slide with "
            f"one of Design's layouts: only when they want it redesigned. {fig_rel} is the deck from now on — don't "
            f"import the file again.")


async def _import_deck(inp, workspace, name):
    """`import {path, name?, replace?}` → the deck as `<name>.fig`, open on the canvas, its first slides to look at."""
    from cycls._agent import design
    from .deck import lock
    from .files import _free_design, _opened, _render_again, _replacing
    src = inp.get("path") or inp.get("src")
    if not isinstance(src, str) or not src.strip():
        return 'Error: `import` needs `path` — the PowerPoint file in the workspace, e.g. "attachments/pitch.pptx".'
    src = src.strip()
    try:
        path = _resolve_path(src, workspace.root)
    except ValueError as e:
        return f"Error: {e}"
    if not path.is_file():
        return f"Error: {src} doesn't exist in the workspace."
    suffix = path.suffix.lower()
    if suffix == ".ppt":
        return (f"Error: {src} is an old PowerPoint file (.ppt), which can't be brought in. Nothing was done. "
                f"Ask the person to save it as .pptx (PowerPoint: File › Save As › PowerPoint Presentation) and send that.")
    if suffix not in _DECK_SUFFIXES:
        return f"Error: {src} isn't a PowerPoint file — `import` brings in a .pptx. Nothing was done."
    root, subject = pathlib.Path(workspace.root), getattr(workspace, "subject", None)
    async with lock(path):                                   # the same deck asked for twice at once: once
        data = await asyncio.to_thread(path.read_bytes)
        if len(data) > _IMPORT_MAX:
            return (f"Error: {src} is {_mb(len(data))} MB — a deck comes in at up to {_mb(_IMPORT_MAX)} MB. Nothing was "
                    f"done, and importing it again won't change that. Tell the person: a copy with its pictures "
                    f"compressed (PowerPoint: File › Compress Pictures) comes in.")
        sha = hashlib.sha256(data).hexdigest()
        replacing = _replacing(root, name, inp)
        if not replacing and (there := await asyncio.to_thread(_imported_as, root, sha)):
            stem = there[:-4]
            ack, ui = _opened(there, f"{src} is already in as {there}")
            return {"_model": f"{ack} Nothing new was made. {_how_to_change(there, stem)} (To bring the file in "
                              f"again from scratch, over that design, import it with \"replace\": true and that "
                              f"`name` — its current version is kept in its history.)", "_ui": ui}
        keep = {"kind": "deck", "imported": {"source": src, "sha256": sha}}
        first, fig, start, parts, report = None, None, 0, 0, []
        try:
            while True:
                parts += 1
                if parts > _IMPORT_PARTS:
                    return (f"Error: {src} is too large to bring in — after {parts - 1} parts it still had slides from "
                            f"{start + 1} on. Nothing was saved, and importing it again won't change that. Tell the "
                            f"person: a shorter copy of the deck (the slides to change) comes in.")
                if fig is not None and (len(data) + len(fig)) * 4 // 3 + (1 << 20) > _SERVICE_BODY:
                    return (f"Error: {src} is too large to bring in whole — its pictures fill the request before its "
                            f"slides from {start + 1} on are in. Nothing was saved, and importing it again won't change "
                            f"that. Tell the person: a copy with its pictures compressed (PowerPoint: File › Compress "
                            f"Pictures) comes in.")
                r = await design.import_deck(data, start=start, fig=fig, keep=keep if fig is None else None,
                                             preview=fig is None, user_id=subject)
                first, fig = first or r, r["fig"]
                report += r["report"]
                if r["next"] is None:
                    break
                if r["next"] <= start:                       # a part that brought nothing in
                    return f"Error: {src} couldn't be brought in past slide {start + 1}. Nothing was saved."
                start = r["next"]
        except design.Unavailable as e:
            return f"Error: design unavailable — {e}"
        except Exception as e:
            return (f"Error: {src} couldn't be brought in — {e}. Nothing was saved, and importing it again won't "
                    f"change that: tell the person what is wrong with the file.")
        # Only the whole deck is written: a fresh name (pitch, pitch-2, …), or over its design with `replace`.
        requested = name
        name = name if replacing else await asyncio.to_thread(_free_design, root, name)
        fig_rel = f"{name}.fig"
        if replacing:
            again = await _render_again(workspace, fig_rel, fig, {"intent": f"brought in again from {path.name}"})
        else:
            await asyncio.to_thread((root / fig_rel).parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread((root / fig_rel).write_bytes, fig)
        await asyncio.to_thread(_remember, root, sha, fig_rel, src)
    from cycls._agent.design import refresh
    refresh.schedule(workspace.root, fig_rel, subject)        # its preview, made ready
    count = r["count"] or len(r["slides"]) or len(first["slides"])
    named = f", named '{name}' so it doesn't overwrite the existing '{requested}'" if name != requested else ""
    what = f"{src} brought in as a deck ({count} slide{'s' if count != 1 else ''}{named})"
    ack, ui = (f"{what}, over {fig_rel}: its earlier version is kept in its history.", again) if replacing \
        else _opened(fig_rel, what)
    ack += " " + _how_to_change(fig_rel, name)
    report = [*dict.fromkeys(report)]                         # each part says its own; once each
    if report:
        ack += (" What changed on the way in — tell the person once, in a line, what matters to them (not a list "
                "of it all): " + "; ".join(report) + ".")
    ack += (" When they download it as PowerPoint, the file is written again from this design: it isn't their "
            "original file, and what is listed above stays out. If they need their own file kept exactly as it is, "
            "say so before they rely on the download.")
    # The model looks at the deck it was given: its first slides, the rest small on contact sheets.
    blocks, total = [], 0
    for n, jpg in enumerate(first["previews"][:_DESIGN_QA_SLIDES], 1):
        if blocks and total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        blocks += [{"type": "text", "text": f"Slide {n}:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    for span, jpg in zip(first["sheet_pages"], first["sheets"]):
        if total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        blocks += [{"type": "text", "text": f"Slides {span[0]}–{span[1]}, small:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if not blocks:
        return {"_model": ack, "_ui": ui}
    ack += (" Its slides are attached as they came in (the first to read, any others small): look at them to know "
            "the deck before you change it. They are the person's design — not yours to QA against layout rules.")
    return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}

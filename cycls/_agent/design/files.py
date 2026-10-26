"""A design's file in the workspace — `<stem>.fig`, wherever it is — its name, and a render's pages written out."""
import asyncio, base64, json, os, pathlib
from ..paths import _safe_filename
from .images import _DESIGN_QA_MAX, _DESIGN_QA_SLIDES
from .report import _layout_check


_DESIGN_EXTS = {"png", "jpg", "webp", "svg", "pptx", "pdf"}
# Formats that are the whole deck in one file (every other format is per frame).
_DECK_EXTS = ("pptx", "pdf")


def _stem_of(raw, folder=""):
    """A design's `name` — its path without `.fig`: "pitch", "clients/acme/pitch" — made safe → its stem
    ("clients/acme/pitch"). A bare name is in `folder` (the one the person has open), else the root."""
    raw = str(raw or "").replace("\\", "/").removeprefix("~/").removeprefix("/workspace/").strip().strip("/")
    parts = [p.strip() for p in raw.split("/") if p.strip() not in ("", ".", "..")]
    last = _safe_filename(parts[-1] if parts else "", "design")
    last = last.rsplit(".", 1)[0] if "." in last.lstrip(".") else last
    parts = [*parts[:-1], last.strip() or "design"]
    if len(parts) == 1 and folder:
        parts = [p for p in str(folder).replace("\\", "/").split("/") if p not in ("", ".", "..")] + parts
    return "/".join(parts)


def _find_design(root, raw, folder=""):
    """The stem of an existing design `raw` names: as given, else beside the person (their folder), at the root,
    or in designs/ (where designs used to be) — else the stem as given, which isn't there."""
    stem = _stem_of(raw)
    if "/" in stem:
        return stem
    for cand in (_stem_of(raw, folder), stem, f"designs/{stem}"):
        if (pathlib.Path(root) / f"{cand}.fig").is_file():
            return cand
    return _stem_of(raw, folder)


def _free_design(root, stem):
    """A stem no design has (`launch`, `launch-2`, …), so a fresh render never overwrites one."""
    taken = lambda s: (pathlib.Path(root) / f"{s}.fig").exists()
    if not taken(stem):
        return stem
    n = 2
    while taken(f"{stem}-{n}"):
        n += 1
    return f"{stem}-{n}"


def _replacing(root, stem, inp):
    """`replace`: the render is written over `<stem>.fig` itself, not beside it as `<stem>-2`."""
    return inp.get("replace") is True and (pathlib.Path(root) / f"{stem}.fig").is_file()


async def _render_again(workspace, fig_rel, fig, inp):
    """A render written over its design, the earlier version kept in its history → the event that brings it
    where it is open (an editor reloads, a viewer fetches it again). It opens nothing that isn't."""
    from .actions import _to_the_room
    from .deck import lock
    from .store import write_fig
    async with lock(pathlib.Path(workspace.root) / fig_rel):
        version = await write_fig(workspace.root, fig_rel, fig, by="agent", reason="agent",
                                  intent=str(inp.get("intent") or "rendered again")[:80])
    again = {"type": "ui", "action": "design_command", "path": fig_rel, "script": "", "version": version, "reload": True}
    await _to_the_room(workspace.root, fig_rel, again)
    return again


def _designs_there(root):
    """The workspace's designs, by name — for "no such design: there are …"."""
    root = pathlib.Path(root)
    found = []
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        found += [(pathlib.Path(dirpath) / n).relative_to(root).as_posix()[:-4] for n in sorted(names) if n.lower().endswith(".fig")]
        if len(found) > 30:
            break
    return ", ".join(found[:30]) + (", …" if len(found) > 30 else "") if found else "none yet"


async def _write_beside(path, data):
    tmp = path.with_name(f".{path.name}.part")
    await asyncio.to_thread(tmp.write_bytes, data)
    await asyncio.to_thread(tmp.replace, path)


def _rendered_copy(root, fig_rel, ext="fig"):
    """A document's .fig as rendered, to tell later what was changed by hand (`ext` "json": its pages' hashes)."""
    import hashlib
    return pathlib.Path(root) / ".cache" / "design" / f"{hashlib.sha1(fig_rel.encode('utf-8')).hexdigest()[:16]}.rendered.{ext}"


def _opened(fig_rel, what):
    """The canvas opening design `fig_rel` → (what the model is told, the event). `what`: "Deck saved (…)"."""
    ack = (f"{what}. It is ONE file, {fig_rel}, and it's OPEN on the canvas"
           + (": in the design editor while you work — the person watches each change land — then, when your "
              "turn ends, as a preview" if os.environ.get("DESIGN_EDITOR_URL") else " as a preview")
           + ", where they page through it, present it and download it (PowerPoint, PDF, images or the design file). "
           "Nothing is written beside it: when a file is needed — to send or attach — `export` writes one.")
    return ack, {"type": "ui", "action": "open_canvas", "path": fig_rel, "name": fig_rel.rsplit("/", 1)[-1]}   # .fig and all: the mobile app reads it


async def _save_pages(r, stem, fmt, workspace, notes, inp):
    """Save a multi-page render (a design's variants): its one `.fig`."""
    root = pathlib.Path(workspace.root)
    replacing = _replacing(root, stem, inp)
    requested, stem = stem, stem if replacing else _free_design(root, stem)
    fig_rel = f"{stem}.fig"
    if replacing:
        again = await _render_again(workspace, fig_rel, r.fig, inp)
    else:
        await asyncio.to_thread((root / fig_rel).parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((root / fig_rel).write_bytes, r.fig)
    from cycls._agent.design import refresh
    refresh.schedule(workspace.root, fig_rel, getattr(workspace, "subject", None))
    listed = [json.dumps(p["name"], ensure_ascii=False) + (f" ({p['frames']} slides)" if p["frames"] > 1 else "") for p in r.pages]
    note = f" (named '{stem}' so it doesn't overwrite the existing '{requested}')" if stem != requested else ""
    what = f"Design {'rendered again in place' if replacing else 'saved'}{note}, with {len(r.pages)} pages: {'; '.join(listed)}"
    ack, ui = (f"{what}. Its earlier version is kept in its history.", again) if replacing else _opened(fig_rel, what)
    ack += (" The person switches pages above the design. Change a page with Design edit {page: \"<its name>\", ops}; "
            "add or copy one with the page_add / page_duplicate ops.")
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

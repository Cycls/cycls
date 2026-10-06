"""Keep a design's exported image in step with its editable `.fig`.

A render saves `designs/<name>.<fmt>` beside `designs/<name>.fig`. After that the
`.fig` is the one that changes — the editor auto-saves it on every edit, the
person's or the agent's live `Design(edit)` — and the image beside it would go
stale: a download, a `read`, or a bash `cp` into an email or a deck would all get
the pre-edit design. So a `.fig` saved under `designs/` schedules a re-export of
the images already beside it, through the same headless service that made them.

A deck's `.pptx` / `.pdf` is the whole deck (its notes and transitions ride in the
`.fig`); a carousel's slides (`<name>-slide-1.png`, `-slide-2.png`, …) are
re-exported together, and a slide deleted since loses its old image.

A design of several pages — its variants — keeps its first page as `<name>.<fmt>` and
the others as `<name>-page-2.<fmt>`, `-page-3`, …, by their place: once a design has
any of those images they follow its pages (a page added gets one, a page removed loses
its own), and a page's `.pdf` / `.pptx` — made when someone asked for one — is
re-exported where it is.

A design with no image at all — a copy made in the editor, a version opened as a
copy — is asked for with `ensure`: it gets `<name>.png`, so Files shows what it is
and the agent's "the image beside it" is true. A deck or a carousel already has its
own files beside it and is left as it is.

Debounced per file: the editor saves in bursts while someone drags things around,
and each save restarts the wait, so only the last state is exported. A save that
lands mid-export cancels it — the newer `.fig` wins. Best effort: a failure logs
and leaves the old image; nothing here can fail the save itself.
"""
import asyncio
from pathlib import Path

import re

from ..logs import log
from .client import configured, export, export_page, outline

DELAY = 2.0                                   # seconds of quiet before exporting
FORMATS = ("png", "jpg", "webp", "svg", "pptx", "pdf")
_RASTER = ("png", "jpg", "webp")
_DECK = ("pptx", "pdf")
_pending = {}                                 # (root, rel) -> the waiting/running task
_ensure = set()                               # (root, rel) to leave with an image beside it
_pages = set()                                # (root, rel) to leave with an image of every page


def page_file(stem, place, fmt):
    """The file a page's image is kept in beside `<stem>.fig`: the first page (place 1)
    is the design's own `<stem>.<fmt>`, the others `<stem>-page-<place>.<fmt>`."""
    return f"{stem}.{fmt}" if place <= 1 else f"{stem}-page-{place}.{fmt}"


def managed(root, rel):
    """Whether `rel` is one of the images this keeps beside a design —
    `designs/…/<stem>.<fmt>`, `<stem>-slide-<n>.<fmt>` or `<stem>-page-<n>.<fmt>` next
    to an existing `<stem>.fig` — so a file written there would be replaced by the next
    re-export. (A new file — an export from the editor — takes another name.)"""
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel.startswith("designs/"):
        return False
    path = Path(rel)
    stem, dot, fmt = path.name.rpartition(".")
    if not dot or fmt.lower() not in FORMATS:
        return False
    for tail in ("-slide-", "-page-"):
        base, sep, n = stem.rpartition(tail)
        if sep and n.isdigit() and (Path(root) / path.parent / f"{base}.fig").is_file():
            return True
    return (Path(root) / path.parent / f"{stem}.fig").is_file()


def follow(root, old_rel, new_rel):
    """A design renamed or moved: what is kept beside its .fig goes with it — its image
    in each format, its slides' and pages' images, its deck document (whose paths are
    written anew). A file already at the new name is left as it is. → the files moved."""
    import json, shutil
    root = Path(root)
    old, new = root / old_rel, root / new_rel
    moved = []
    if not old.parent.is_dir():
        return moved
    for f in sorted(old.parent.iterdir()):
        if not f.is_file():
            continue
        tail = None
        if f.name == f"{old.stem}.deck.json":
            tail = ".deck.json"
        else:
            base, dot, fmt = f.name.rpartition(".")
            if dot and fmt.lower() in FORMATS:
                if base == old.stem:
                    tail = f".{fmt}"
                for part in ("-slide-", "-page-"):
                    head, sep, n = base.rpartition(part)
                    if sep and n.isdigit() and head == old.stem:
                        tail = f"{part}{n}.{fmt}"
        dest = new.parent / f"{new.stem}{tail}" if tail else None
        if dest is None or dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest))
        moved.append(dest)
    deck = new.parent / f"{new.stem}.deck.json"
    if deck.is_file():
        before = Path(old_rel).as_posix().rsplit(".", 1)[0]          # designs/launch
        after = Path(new_rel).as_posix().rsplit(".", 1)[0]
        swap = lambda p: after + p[len(before):] if isinstance(p, str) and p.startswith(before) and p[len(before):len(before) + 1] in (".", "-") else p
        try:
            doc = json.loads(deck.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                doc["fig"] = swap(doc.get("fig"))
                if isinstance(doc.get("exports"), list):
                    doc["exports"] = [swap(p) for p in doc["exports"]]
                deck.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            pass
    return moved


def schedule(root, rel, user_id=None, ensure=False, pages=False):
    """Re-export the images beside `rel` (a `designs/*.fig` just written under
    workspace `root`) once its saves go quiet; with `ensure`, a design that has none
    gets `<name>.png`; with `pages`, every page after the first gets its image (an
    agent just made one). A no-op without the service."""
    rel = rel.replace("\\", "/").lstrip("/")
    if not (configured() and rel.startswith("designs/") and rel.endswith(".fig")):
        return
    key = (str(root), rel)
    if ensure:                                 # kept until an export ran: a later plain save restarts the wait
        _ensure.add(key)
    if pages:
        _pages.add(key)
    if (task := _pending.get(key)) and not task.done():
        task.cancel()
    _pending[key] = asyncio.get_running_loop().create_task(_refresh(key, user_id))


async def _refresh(key, user_id):
    root, rel = key
    fig_path = Path(root) / rel
    try:
        await asyncio.sleep(DELAY)
        fig = await asyncio.to_thread(fig_path.read_bytes)
        stem = fig_path.stem
        beside = lambda fmt, tail="": fig_path.with_name(f"{stem}{tail}.{fmt}")
        if key in _ensure and not any(beside(fmt, tail).is_file() for fmt in FORMATS for tail in ("", "-slide-1")):
            await _replace(beside("png"), await export(fig, fmt="png", user_id=user_id))
            _ensure.discard(key)
            return
        _ensure.discard(key)
        for fmt in FORMATS:
            out = beside(fmt)
            if out.is_file():
                image = await export(fig, fmt=fmt, width=await _width(out, fmt), user_id=user_id)
                await _replace(out, image)
            first = beside(fmt, "-slide-1")
            if fmt not in _DECK and first.is_file():
                images = await export(fig, fmt=fmt, width=await _width(first, fmt), user_id=user_id, every=True)
                for n, image in enumerate(images, 1):
                    await _replace(fig_path.with_name(f"{stem}-slide-{n}.{fmt}"), image)
                n = len(images) + 1
                while images and (stale := fig_path.with_name(f"{stem}-slide-{n}.{fmt}")).is_file():
                    await asyncio.to_thread(stale.unlink)      # a slide deleted in the editor
                    n += 1
        await _refresh_pages(fig_path, fig, key in _pages, user_id)
        _pages.discard(key)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        _ensure.discard(key)
        _pages.discard(key)
        log("warn", message=f"design re-export of {rel} failed: {type(e).__name__}: {e}")
    finally:
        if _pending.get(key) is asyncio.current_task():
            del _pending[key]


async def _refresh_pages(fig_path, fig, ensure, user_id):
    """The images of the pages after the first, `<stem>-page-<n>.<fmt>`: in a format
    that has any (or png, with `ensure`), every page's — one added since gets its own;
    a page's .pdf / .pptx only where there is one. A file whose page is gone goes.
    They are drawn at the design's own scale (its `<stem>.<fmt>` against its first
    frame) — a page's place changes, so the file there may have been another page's."""
    stem = fig_path.stem
    held = {}                                                  # fmt -> the places with a file
    pattern = re.compile(re.escape(stem) + r"-page-(\d+)\.(\w+)")
    for f in await asyncio.to_thread(lambda: list(fig_path.parent.glob(f"{stem}-page-*.*"))):
        if (m := pattern.fullmatch(f.name)) and m.group(2) in FORMATS and int(m.group(1)) >= 2:
            held.setdefault(m.group(2), set()).add(int(m.group(1)))
    if ensure:
        held.setdefault("png", set())
    if not held:
        return
    info = await outline(fig, user_id=user_id)
    pages = info["pages"]
    first_width = ((info["frames"] or [{}])[0].get("size") or [0])[0]
    for fmt, places in held.items():
        own = fig_path.with_name(f"{stem}.{fmt}")
        width = await _width(own, fmt) if own.is_file() else None
        scale = round(width / first_width, 3) if width and first_width else 2
        todo = sorted(p for p in places if p <= len(pages)) if fmt in _DECK else range(2, len(pages) + 1)
        for place in todo:
            if not pages[place - 1]["frames"]:
                continue                                       # an empty page has no picture
            if fig_path.with_name(f"{stem}-page-{place}.fig").exists():
                continue                                       # that name is another design's picture
            out = fig_path.with_name(page_file(stem, place, fmt))
            image, _, _ = await export_page(fig, place - 1, fmt=fmt, scale=scale, user_id=user_id)
            await _replace(out, image)
        for place in places:
            if place > len(pages):                             # a page removed in the editor
                await asyncio.to_thread(fig_path.with_name(page_file(stem, place, fmt)).unlink, True)


async def _width(path, fmt):
    """A raster's pixel width — what its re-export keeps — else None."""
    if fmt not in _RASTER:
        return None
    from ..tools import _image_size
    return (_image_size(await asyncio.to_thread(path.read_bytes)) or (None,))[0]


async def _replace(path, data):
    tmp = path.with_name(f".{path.name}.part")
    await asyncio.to_thread(tmp.write_bytes, data)
    await asyncio.to_thread(tmp.replace, path)

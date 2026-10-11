"""Keep the images beside a design's `.fig` in step with it: each save under designs/ schedules a
debounced re-export, and a newer save cancels a running one. Best effort: a failure only logs."""
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
    """A page's image beside `<stem>.fig`: `<stem>.<fmt>` for the first, `<stem>-page-<place>.<fmt>` after."""
    return f"{stem}.{fmt}" if place <= 1 else f"{stem}-page-{place}.{fmt}"


def managed(root, rel):
    """Whether `rel` is an image kept beside a design's `.fig`, which the next re-export replaces."""
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


def beside(root, rel):
    """What is kept beside design `rel` → [(file, its tail after the name: ".png", "-slide-2.png", ".deck.json")]."""
    fig = Path(root) / rel
    found = []
    if not fig.parent.is_dir():
        return found
    for f in sorted(fig.parent.iterdir()):
        if not f.is_file():
            continue
        tail = None
        if f.name == f"{fig.stem}.deck.json":
            tail = ".deck.json"
        else:
            base, dot, fmt = f.name.rpartition(".")
            if dot and fmt.lower() in FORMATS:
                if base == fig.stem:
                    tail = f".{fmt}"
                for part in ("-slide-", "-page-"):
                    head, sep, n = base.rpartition(part)
                    if sep and n.isdigit() and head == fig.stem:
                        tail = f"{part}{n}.{fmt}"
        if tail:
            found.append((f, tail))
    return found


def follow(root, old_rel, new_rel, copy=False):
    """Move (or `copy`) what is kept beside a renamed design, never over an existing file → the files moved."""
    import json, shutil
    root = Path(root)
    old, new = root / old_rel, root / new_rel
    moved = []
    for f, tail in beside(root, old_rel):
        dest = new.parent / f"{new.stem}{tail}"
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copy2 if copy else shutil.move)(str(f), str(dest))
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
    """Re-export the images beside `rel` once its saves go quiet. `ensure`: an imageless design
    gets `<name>.png`; `pages`: every page gets its image."""
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
    """Images of the pages after the first, at the design's own scale; a removed page's file goes."""
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
    from .images import _image_size
    return (_image_size(await asyncio.to_thread(path.read_bytes)) or (None,))[0]


async def _replace(path, data):
    tmp = path.with_name(f".{path.name}.part")
    await asyncio.to_thread(tmp.write_bytes, data)
    await asyncio.to_thread(tmp.replace, path)

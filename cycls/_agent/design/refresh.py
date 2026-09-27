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

Debounced per file: the editor saves in bursts while someone drags things around,
and each save restarts the wait, so only the last state is exported. A save that
lands mid-export cancels it — the newer `.fig` wins. Best effort: a failure logs
and leaves the old image; nothing here can fail the save itself.
"""
import asyncio
from pathlib import Path

from ..logs import log
from .client import configured, export

DELAY = 2.0                                   # seconds of quiet before exporting
FORMATS = ("png", "jpg", "webp", "svg", "pptx", "pdf")
_RASTER = ("png", "jpg", "webp")
_DECK = ("pptx", "pdf")
_pending = {}                                 # (root, rel) -> the waiting/running task


def schedule(root, rel, user_id=None):
    """Re-export the images beside `rel` (a `designs/*.fig` just written under
    workspace `root`) once its saves go quiet. A no-op without the service."""
    rel = rel.replace("\\", "/").lstrip("/")
    if not (configured() and rel.startswith("designs/") and rel.endswith(".fig")):
        return
    key = (str(root), rel)
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
        for fmt in FORMATS:
            out = fig_path.with_name(f"{stem}.{fmt}")
            if out.is_file():
                image = await export(fig, fmt=fmt, width=await _width(out, fmt), user_id=user_id)
                await _replace(out, image)
            first = fig_path.with_name(f"{stem}-slide-1.{fmt}")
            if fmt not in _DECK and first.is_file():
                images = await export(fig, fmt=fmt, width=await _width(first, fmt), user_id=user_id, every=True)
                for n, image in enumerate(images, 1):
                    await _replace(fig_path.with_name(f"{stem}-slide-{n}.{fmt}"), image)
                n = len(images) + 1
                while images and (stale := fig_path.with_name(f"{stem}-slide-{n}.{fmt}")).is_file():
                    await asyncio.to_thread(stale.unlink)      # a slide deleted in the editor
                    n += 1
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log("warn", message=f"design re-export of {rel} failed: {type(e).__name__}: {e}")
    finally:
        if _pending.get(key) is asyncio.current_task():
            del _pending[key]


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

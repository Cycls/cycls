"""Keep a design's exported image in step with its editable `.fig`.

A render saves `designs/<name>.<fmt>` beside `designs/<name>.fig`. After that the
`.fig` is the one that changes — the editor auto-saves it on every edit, the
person's or the agent's live `Design(edit)` — and the image beside it would go
stale: a download, a `read`, or a bash `cp` into an email or a deck would all get
the pre-edit design. So a `.fig` saved under `designs/` schedules a re-export of
the images already beside it, through the same headless service that made them.

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
FORMATS = ("png", "jpg", "webp", "svg", "pptx")
_RASTER = ("png", "jpg", "webp")
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
        for fmt in FORMATS:
            out = fig_path.with_name(f"{fig_path.stem}.{fmt}")
            if not out.is_file():
                continue
            width = None
            if fmt in _RASTER:
                from ..tools import _image_size
                width = (_image_size(await asyncio.to_thread(out.read_bytes)) or (None,))[0]
            image = await export(fig, fmt=fmt, width=width, user_id=user_id)
            tmp = out.with_name(f".{out.name}.part")
            await asyncio.to_thread(tmp.write_bytes, image)
            await asyncio.to_thread(tmp.replace, out)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log("warn", message=f"design re-export of {rel} failed: {type(e).__name__}: {e}")
    finally:
        if _pending.get(key) is asyncio.current_task():
            del _pending[key]

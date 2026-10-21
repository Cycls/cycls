"""A design's preview made ready before anyone opens it: each save of a `.fig` schedules, once saves go
quiet, the slide manifest the canvas shows — so the preview the agent's turn ends on opens at once
instead of drawing every page then. A newer save cancels a waiting one. Best effort: a failure only logs."""
import asyncio
from pathlib import Path

from ..logs import log
from .client import configured

DELAY = 2.0                                   # seconds of quiet before the preview is made
_pending = {}                                 # (root, rel) -> the waiting/running task


def schedule(root, rel, user_id=None):
    """Make design `rel`'s preview once its saves go quiet."""
    rel = rel.replace("\\", "/").lstrip("/")
    if not (configured() and rel.lower().endswith(".fig")):
        return
    key = (str(root), rel)
    if (task := _pending.get(key)) and not task.done():
        task.cancel()
    _pending[key] = asyncio.get_running_loop().create_task(_warm(key, user_id))


async def _warm(key, user_id):
    from cycls._agent.web.design_routes import _design_slides
    root, rel = key
    try:
        await asyncio.sleep(DELAY)
        await _design_slides(root, Path(root) / rel, user_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log("warn", message=f"design preview of {rel} failed: {type(e).__name__}: {e}")
    finally:
        if _pending.get(key) is asyncio.current_task():
            del _pending[key]

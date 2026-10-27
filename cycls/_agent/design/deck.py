"""Slide ops on a deck, shared by the Design tool and the canvas's slide changes. A deck is one `.fig`:
the settings its added slides are laid out with are kept in it (`keep.deck`, written when it is rendered)."""
import asyncio
from pathlib import Path

from . import refresh

SLIDE_OPS = ("slide_add", "slide_update", "slide_move", "slide_duplicate", "slide_delete", "slide_meta")
_locks = {}


def lock(fig_path):
    """One read → apply → write at a time per design file: the model calls tools in parallel."""
    key = (id(asyncio.get_running_loop()), str(Path(fig_path).resolve()))   # a lock belongs to one loop
    return _locks.setdefault(key, asyncio.Lock())


def settings_of(deck):
    """A deck's settings as its file keeps them: image slots back to workspace paths."""
    def strip(v):
        if isinstance(v, dict):
            if (isinstance(v.get("image"), str) or isinstance(v.get("svg"), str)) and "type" not in v:
                return v.get("src")
            return {k: strip(x) for k, x in v.items()}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    return strip({k: deck.get(k) for k in ("theme", "look", "size", "footer", "logo", "transition", "dir") if deck.get(k) is not None})


async def settings(fig, user_id=None):
    """What a slide added to design `fig` (bytes) is laid out with → (settings, the outline's frames): the deck's
    own, else its first slide's size."""
    from cycls._agent import design
    o = await design.outline(fig, user_id=user_id)
    kept = (o.get("keep") or {}).get("deck")
    out = dict(kept) if isinstance(kept, dict) else {}
    size = ((o.get("frames") or [{}])[0] or {}).get("size")
    if "size" not in out and isinstance(size, list) and len(size) == 2:
        out["size"] = size
    return out, o.get("frames") or []


def _intent(ops):
    """What a version history says a slide change was ("move slide 4")."""
    labels = {"slide_add": "add a slide", "slide_update": "change slide {n}", "slide_move": "move slide {n}",
              "slide_duplicate": "duplicate slide {n}", "slide_delete": "delete slide {n}", "slide_meta": "slide {n}'s notes"}
    op = (ops or [{}])[0]
    if len(ops or []) > 1 and all(o.get("op") == "slide_add" for o in ops):
        return f"add {len(ops)} slides"
    n = op.get("index", op.get("from"))
    return labels.get(op.get("op"), "change the slides").format(n=(n + 1) if isinstance(n, int) else "")


async def apply_ops(root, fig_rel, ops, user_id=None, preview=False, by="agent"):
    """Run slide `ops` (service form, 0-based) on design `fig_rel` → the service's result; its preview follows.
    Raises FileNotFoundError, design.Unavailable, RuntimeError."""
    from cycls._agent import design
    from .store import Stale, load_fig, write_fig
    async with lock(Path(root) / fig_rel):
        for attempt in (1, 2):
            data, base = await load_fig(root, fig_rel)
            if data is None:
                raise FileNotFoundError(fig_rel)
            r = await design.apply(data, ops=ops, preview=preview, user_id=user_id)
            try:   # an editor save may land meanwhile: apply to that, once
                r["version"] = await write_fig(root, fig_rel, r["fig"], base=base, by=by,
                                               reason="agent" if by == "agent" else "change", intent=_intent(ops))
                break
            except Stale:
                if attempt == 2:
                    raise RuntimeError("the design changed while the slides were being changed — try again")
    refresh.schedule(root, fig_rel, user_id)
    return r

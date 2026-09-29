"""Slide operations on a design deck — add, update, move, duplicate, delete, notes —
shared by the Design tool's slide actions and the deck viewer's own reorder /
duplicate / delete (the `/deck` route).

A deck is `designs/<name>.fig` (the slides, each with its notes, transition, title
and — for a deck of layouts — its layout source, as plugin data) plus the deck
document `designs/<name>.deck.json` beside it: `{type, version, fig, size, slides,
exports, settings?}`. `settings` — the theme, size, footer and logo a deck of layouts
was made with, image slots kept as their workspace paths — is what a new or updated
slide is laid out with, so it matches the rest.

Every op runs on the saved `.fig` through the service (`/apply`, the same plugin API
the live editor replays), is written back atomically, re-exported beside it
(`refresh`), and the deck document's slide count follows.
"""
import asyncio
import json
from pathlib import Path

from . import refresh

SLIDE_OPS = ("slide_add", "slide_update", "slide_move", "slide_duplicate", "slide_delete", "slide_meta")
_locks = {}


def lock(fig_path):
    """One change at a time per design file. The model calls tools in parallel — a
    move_slide and an update_slide in one turn each read the same .fig, and the later
    write silently dropped the other's change. Every read → apply → write holds this."""
    key = (id(asyncio.get_running_loop()), str(Path(fig_path).resolve()))   # a lock belongs to one loop
    return _locks.setdefault(key, asyncio.Lock())


def settings_of(deck):
    """A deck of layouts' settings as the deck document keeps them: every image slot
    (a resolved {image|svg, src}) back to its workspace path."""
    def strip(v):
        if isinstance(v, dict):
            if (isinstance(v.get("image"), str) or isinstance(v.get("svg"), str)) and "type" not in v:
                return v.get("src")
            return {k: strip(x) for k, x in v.items()}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    return strip({k: deck.get(k) for k in ("theme", "size", "footer", "logo", "transition", "dir") if deck.get(k) is not None})


def paths(root, name):
    """(fig path, fig rel, deck document path, deck rel) for design `name`."""
    root = Path(root)
    return (root / "designs" / f"{name}.fig", f"designs/{name}.fig",
            root / "designs" / f"{name}.deck.json", f"designs/{name}.deck.json")


def _intent(ops):
    """What a version history says a slide change was ("move slide 4")."""
    labels = {"slide_add": "add a slide", "slide_update": "change slide {n}", "slide_move": "move slide {n}",
              "slide_duplicate": "duplicate slide {n}", "slide_delete": "delete slide {n}", "slide_meta": "slide {n}'s notes"}
    op = (ops or [{}])[0]
    n = op.get("index", op.get("from"))
    return labels.get(op.get("op"), "change the slides").format(n=(n + 1) if isinstance(n, int) else "")


def read_doc(deck_path):
    try:
        doc = json.loads(deck_path.read_text("utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


async def apply_ops(root, name, ops, user_id=None, preview=False):
    """Run slide `ops` (service form, 0-based) on design `name` → the service's result
    dict (fig, lint, script, preview, previews, touched, slides). The `.fig` is
    rewritten, its exports refreshed and the deck document's count updated (the
    document is created when a single design becomes a deck). Raises FileNotFoundError
    (no such design), design.Unavailable, RuntimeError (the op's own error)."""
    from cycls._agent import design
    from .store import Stale, read_fig, write_fig
    fig_path, fig_rel, deck_path, _ = paths(root, name)
    async with lock(fig_path):
        for attempt in (1, 2):
            data, base = await asyncio.to_thread(read_fig, root, fig_rel)
            if data is None:
                raise FileNotFoundError(fig_rel)
            r = await design.apply(data, ops=ops, preview=preview, user_id=user_id)
            try:   # the person may have saved in the editor meanwhile: apply to that, once
                r["version"] = await write_fig(root, fig_rel, r["fig"], base=base, by="agent", reason="agent",
                                               intent=_intent(ops))
                break
            except Stale:
                if attempt == 2:
                    raise RuntimeError("the design changed while the slides were being changed — try again")
    refresh.schedule(root, fig_rel, user_id)
    count = len(r.get("slides") or [])
    if count:
        doc = await asyncio.to_thread(read_doc, deck_path)
        if count > 1 or doc:
            doc = {"type": "cycls.deck", "version": 1, "fig": fig_rel, **doc, "slides": count}
            doc.setdefault("exports", [])
            part = deck_path.with_name(f".{deck_path.name}.part")
            await asyncio.to_thread(part.write_text, json.dumps(doc, indent=2), "utf-8")
            await asyncio.to_thread(part.replace, deck_path)
    return r

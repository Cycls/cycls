"""Comment threads pinned on a design's slides (docs/notes/design.md, "Comments"). Kept in the
workspace's shared `.comments` shelf, not the .fig, so a comment is no save; one record per design,
written only if unchanged since read (`gen`) — the server runs on several instances."""
import hashlib, math, secrets
from datetime import datetime, timezone

from cycls._app.db import DB, Conflict, workspace

SLOT = ".comments"
TEXT_MAX = 4000        # characters in one comment
THREADS_MAX = 300      # open threads on one design
REPLIES_MAX = 200      # replies under one thread
KEPT_MAX = 1500        # threads kept in all — past it the oldest resolved go
NAME_MAX = 80
_SPAN = 30000          # a point this far from a slide's corner is not on a slide
_TRIES = 8


class Refused(Exception):
    """A change that isn't made, and the HTTP status that says why."""
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def usable(ws):
    """Whether `ws` can reach a store (a workspace made up for a test may not)."""
    return bool(getattr(ws, "base", None)) and hasattr(ws, "volume")


def db(ws):
    """The workspace's comment shelf, keyed by org (no person in the path) so every member shares it."""
    return DB(workspace(ws.subject.partition(":")[0], ws.volume, base=ws.base, slot=SLOT, ws=ws.ws))


def _key(rel):
    return "d/" + hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16]


def _shelf(tid):
    if not tid or "/" in tid or ".." in tid:
        raise ValueError(f"not a trash entry: {tid!r}")
    return f"trash/{tid}"


def _now():
    return datetime.now(timezone.utc).isoformat()


def version_of(doc):   # `<born>.<rev>`: what a browser sends back to be told nothing changed
    return f"{doc['born']}.{doc['rev']}" if doc else "0"


def shown(doc):
    """A design's threads as they are served, by number."""
    return sorted((doc or {}).get("threads") or [], key=lambda t: t.get("n", 0))


def open_threads(doc):
    return [t for t in shown(doc) if not t.get("resolved")]


def place(thread, names):
    """The index in `names` of the slide a thread is on now, or None if it was deleted. The service
    never renames a slide, so the name finds it after a move; no name or a shared one goes by place."""
    at, name = thread.get("frame", 0), thread.get("frame_name")
    if len(names) == 1:
        return 0
    if name and not (0 <= at < len(names) and names[at] == name):
        named = [i for i, n in enumerate(names) if n == name]
        if len(named) == 1:
            return named[0]
        if not named:
            return None
    return at if 0 <= at < len(names) else None


def on_page(threads, page, pages):
    """Threads on `page`: all for a one-page design, else those naming it (none named = the first)."""
    if len(pages or []) <= 1:
        return list(threads)
    return [t for t in threads if (t.get("page") or pages[0]) == page]


def node_at(nodes, x, y):
    """The topmost outline node under a point (`nodes` are in paint order), or None."""
    for n in reversed(nodes or []):
        try:
            if n["x"] <= x <= n["x"] + n["w"] and n["y"] <= y <= n["y"] + n["h"]:
                return n
        except (KeyError, TypeError):
            continue
    return None


async def read(ws, rel):
    """→ (the record or None, its version)."""
    doc = await db(ws).get(_key(rel))
    doc = doc if isinstance(doc, dict) and isinstance(doc.get("threads"), list) else None
    return doc, version_of(doc)


# ---- what a comment is made of ----

def _text(raw):
    text = raw.replace("\x00", "").strip() if isinstance(raw, str) else ""
    if not text:
        raise Refused("A comment needs some words.")
    if len(text) > TEXT_MAX:
        raise Refused(f"A comment is at most {TEXT_MAX} characters.")
    return text


def _words(raw, most):
    return raw.strip()[:most] if isinstance(raw, str) and raw.strip() else None


def _spot(at):
    """Where a pin is: {page?, frame, frame_name?, x, y}, checked; never a node id (renumbered on save)."""
    at = at if isinstance(at, dict) else {}
    frame = at.get("frame")
    if not isinstance(frame, int) or isinstance(frame, bool) or not 0 <= frame < 1000:
        raise Refused("`frame` is the slide the comment is on: its place on the page, from 0.")
    point = {}
    for axis in ("x", "y"):
        v = at.get(axis)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or abs(v) > _SPAN:
            raise Refused(f"`{axis}` is where on the slide the comment is pinned, in the slide's pixels.")
        point[axis] = round(v, 1)
    spot = {"frame": frame, **point}
    if page := _words(at.get("page"), 80):
        spot["page"] = page
    if name := _words(at.get("frame_name"), 120):
        spot["frame_name"] = name
    return spot


def author(user_id, name=None, image=None, agent=False):
    """Who wrote it: the signed-in person's id (never the request's) and the browser's name for them."""
    who = {"id": str(user_id), "name": _words(name, NAME_MAX) or ("Super" if agent else "Someone")}
    if isinstance(image, str) and image.startswith("https://") and len(image) <= 600:
        who["image"] = image
    if agent:
        who["agent"] = True
    return who


# ---- changing a design's record ----

async def _update(ws, rel, change):
    """Apply `change(doc)`; write back unless someone wrote in between, else retry → (result, version)."""
    store, key = db(ws), _key(rel)
    for _ in range(_TRIES):
        doc, gen = await store.get_gen(key)
        if not (isinstance(doc, dict) and isinstance(doc.get("threads"), list)):
            doc = {"path": rel, "born": secrets.token_hex(4), "rev": 0, "seq": 0, "threads": []}
        out = change(doc)
        doc["rev"] = int(doc.get("rev") or 0) + 1
        try:
            await store.put(key, doc, **({"create": True} if gen == "" else {"gen": gen}))
        except Conflict:
            continue
        return out, version_of(doc)
    raise Refused("Too many people are commenting on this design at once — try again.", 503)


def _thread(doc, tid):
    for t in doc["threads"]:
        if t.get("id") == tid:
            return t
    raise Refused("That comment is gone.", 404)


def _trim(doc):
    """Past KEPT_MAX the oldest resolved threads go; open ones are never dropped."""
    over = len(doc["threads"]) - KEPT_MAX
    if over > 0:
        gone = {t["id"] for t in sorted((t for t in doc["threads"] if t.get("resolved")), key=lambda t: t.get("n", 0))[:over]}
        doc["threads"] = [t for t in doc["threads"] if t["id"] not in gone]


async def add(ws, rel, who, text, at):
    """A new thread pinned at `at`. → (the thread, the version)."""
    text, spot = _text(text), _spot(at)

    def change(doc):
        if len(open_threads(doc)) >= THREADS_MAX:
            raise Refused(f"This design has {THREADS_MAX} open comments — resolve some first.", 409)
        doc["seq"] = int(doc.get("seq") or 0) + 1   # `n` is never reused: comment 3 stays 3
        now = _now()
        thread = {"id": secrets.token_hex(5), "n": doc["seq"], **spot, "author": who, "text": text,
                  "at": now, "updated": now, "resolved": False, "replies": []}
        doc["threads"].append(thread)
        _trim(doc)
        return thread
    return await _update(ws, rel, change)


async def change(ws, rel, tid, op, who, body=None):
    """One op on thread `tid`: reply, resolve, reopen (anyone) or edit, delete, move (author only)
    → (the thread, None once deleted; the version)."""
    body = body if isinstance(body, dict) else {}
    if op not in ("reply", "resolve", "reopen", "edit", "delete", "move"):
        raise Refused("`op` is reply, resolve, reopen, edit, delete or move.")
    text = _text(body.get("text")) if op in ("reply", "edit") else None
    spot = _spot(body) if op == "move" else None
    rid = body.get("reply") if op in ("edit", "delete") else None

    def own(item, what):
        if (item.get("author") or {}).get("id") != who["id"]:
            raise Refused(f"Only its author can {what} a comment.", 403)

    def apply(doc):
        t = _thread(doc, tid)
        now = _now()
        if rid is not None:
            reply = next((r for r in t["replies"] if r.get("id") == rid), None)
            if reply is None:
                raise Refused("That reply is gone.", 404)
            own(reply, "change" if op == "edit" else "remove")
            if op == "edit":
                reply.update(text=text, edited=now)
            else:
                t["replies"].remove(reply)
        elif op == "reply":
            if len(t["replies"]) >= REPLIES_MAX:
                raise Refused(f"A comment takes {REPLIES_MAX} replies — start a new one.", 409)
            t["replies"].append({"id": secrets.token_hex(5), "author": who, "text": text, "at": now})
            _reopen(t)                       # an answer to a resolved comment opens it again
        elif op == "resolve":
            t.update(resolved=True, resolved_by=who, resolved_at=now)
        elif op == "reopen":
            _reopen(t)
        elif op == "edit":
            own(t, "change")
            t.update(text=text, edited=now)
        elif op == "move":
            own(t, "move")
            for k in ("page", "frame_name"):
                t.pop(k, None)
            t.update(spot)
        else:
            own(t, "remove")
            doc["threads"].remove(t)
            return None
        t["updated"] = now
        return t
    return await _update(ws, rel, apply)


def _reopen(thread):
    thread["resolved"] = False
    thread.pop("resolved_by", None)
    thread.pop("resolved_at", None)


# ---- the design renamed, deleted, brought back ----

async def _carry(ws, src, dst, rel=None):
    """Move the record at key `src` to `dst`, clearing any stale record left at `dst`."""
    store = db(ws)
    doc = await store.get(src)
    await store.delete(dst)
    if isinstance(doc, dict):
        if rel:
            doc["path"] = rel
        await store.put(dst, doc)
        await store.delete(src)


async def move(ws, src, dst):
    """A renamed design keeps what was said about it."""
    await _carry(ws, _key(src), _key(dst), dst)


async def shelve(ws, rel, tid):
    """A trashed design's comments go under its trash entry; a new one of that name starts with none."""
    await _carry(ws, _key(rel), _shelf(tid))


async def unshelve(ws, tid, rel):
    """A restored design's comments come back with it."""
    await _carry(ws, _shelf(tid), _key(rel), rel)


async def drop(ws, tids):
    """Trash entries gone for good: so are their comments."""
    store = db(ws)
    for tid in tids:
        try:
            await store.delete(_shelf(tid))
        except ValueError:
            pass

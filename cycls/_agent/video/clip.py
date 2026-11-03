"""A clip the person sent, made into a video they change by hand.

Edit on an MP4 in the canvas (POST /video/clip, web/video_routes.py) and the Video tool's `editor
{path}` both come here. The clip is made ready as `footage` makes it — sent to the service in pieces,
read on the organisation's GPU, what is said in it written beside it — and then a video that is the
clip alone is written: videos/<name>.video.html, the whole clip (its first 90 s when it is longer: a
video runs 3 to 90 s), in the format nearest its shape, fitted on black so nothing is cut off, with
its own sound. The editor opens on that.

Edit again on the same clip opens the same video, with whatever was changed there: the video made
from a clip is remembered (.cache/video/edits.json) and never written over. A rendered MP4 whose
composition is beside it (videos/<name>.mp4, or one of its sizes) opens that composition instead.

    composition_of(root, rel)                   a rendered MP4's own composition, or None
    make_ready(workspace, root, full, rel, …)   → {"state": "ready", "info", "sheet", …}, or where it stopped
    starter(root, rel, info, by)                the clip's video, found or written → (path, made, notice)
    open_clip(workspace, root, rel, …)          all of it, for Edit → {"state": "ready", "path", "notice"?}
"""
import asyncio
import hashlib
import json
import math
import re
import time
from pathlib import Path

from ..design.deck import lock
from ..design.store import write_fig
from . import files, media, sizes

MIN_S, MAX_S = 3, 90            # the service's limits on a video (cycls-video validate.LIMITS)
_STEP_SEND = 5                  # seconds of sending between two words of progress
_STEP_READ = 20                 # and of waiting for the read
_READ_CAP = 20 * 60             # Edit gives up on a read after this long (the agent's call has its own budget)
_ATTACHED = re.compile(r"^[0-9a-f]{8}-")     # the id the chat puts before an attachment's name (use-chat.ts)
_RENDERED = re.compile(rf"^{files.DIR}/(?P<name>[^/]+?)(?:\.(?:{'|'.join(sizes.SHAPES)}))?\.mp4$")
_EDITS = files.SIDECAR / "edits.json"


class NotReady(Exception):
    """The clip was refused, or could not be made ready, or cannot be a video: the message says why."""


async def _tell(progress, event):
    if progress is not None:
        await progress(event)


def composition_of(root, rel):
    """videos/<name>.mp4 (or videos/<name>.<size>.mp4) → videos/<name>.video.html when that is there:
    Edit on a rendered video opens the video it was rendered from."""
    m = _RENDERED.match(rel)
    if not m:
        return None
    comp = files.composition(m.group("name"))
    return comp if (Path(root) / comp).is_file() else None


def _remembered(root):
    try:
        data = json.loads((Path(root) / _EDITS).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(root, rel, comp):
    data = _remembered(root)
    data[rel] = comp
    path = Path(root) / _EDITS
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def video_for(root, rel):
    """The video already made from this clip, while it is still there."""
    comp = _remembered(root).get(rel)
    return comp if isinstance(comp, str) and (Path(root) / comp).is_file() else None


async def make_ready(workspace, root, full, rel, *, chat=None, language=None, send_budget=None, read_budget=None,
                     progress=None, by="agent", again=True):
    """The clip sent (from wherever the service has it up to) and read, its transcript beside it.

    With budgets (the agent's call) it stops when one runs out and says where: {"state": "sending",
    "sent", "size"} or {"state": "reading", "eta_s"}; the next call goes on from there. Without them
    (Edit) it goes on to the end, telling `progress` (an async callable) how far it is.
    → {"state": "ready", "info", "sheet", "reused", "sha", "words_rel"}. NotReady when it cannot be."""
    from cycls._agent import video

    root = Path(root)
    size = full.stat().st_size
    sha = await asyncio.to_thread(files.clip_sha, root, rel, full)
    state = await video.clip_state(workspace, sha, sheet=True)
    info, sheet, reused = None, None, False
    if state.get("state") == "ready":
        info, sheet, reused = state["info"], state.get("sheet"), True
    else:
        if state.get("state") != "uploaded":
            at = int(state.get("at") or 0) if state.get("state") == "partial" else 0
            await _tell(progress, {"state": "sending", "sent": at, "size": size})
            try:
                if send_budget is not None:
                    at, whole = await video.send_clip(workspace, full, sha, budget=send_budget, at=at)
                    if not whole:
                        return {"state": "sending", "sent": at, "size": size}
                else:
                    whole, still = False, 0
                    while not whole:
                        before = at
                        at, whole = await video.send_clip(workspace, full, sha, budget=_STEP_SEND, at=at)
                        await _tell(progress, {"state": "sending", "sent": at, "size": size})
                        still = still + 1 if at <= before and not whole else 0
                        if still >= 3:
                            raise NotReady("the upload to the video service stopped going forward; try again.")
            except video.Refused as e:
                raise NotReady(f"the clip was not taken: {e}") from e
        pending = files.footage_pending(root, chat, sha) if chat else None
        token, eta = (pending["token"] if pending else None), None
        if token is None:
            key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|ingest|{sha}|{language or ''}".encode()).hexdigest()
            try:
                job = await video.ingest(workspace, sha, language=language or None, key=key)
            except video.Refused as e:
                raise NotReady(f"the clip was not made ready: {e}") from e
            if job.get("ready"):
                info, sheet = job["info"], job.get("sheet")
            else:
                token, eta = job["token"], job.get("eta_s")
                if chat:
                    files.footage_started(root, chat, sha, token)
        if info is None:
            await _tell(progress, {"state": "reading", "eta_s": eta})
            if read_budget is not None:
                r = await video.wait(workspace, token, read_budget)
            else:
                deadline = time.monotonic() + _READ_CAP
                while True:
                    r = await video.wait(workspace, token, _STEP_READ)
                    if r.get("state") != "pending" or time.monotonic() > deadline:
                        break
                    await _tell(progress, {"state": "reading", "eta_s": r.get("eta_s")})
            if r.get("state") == "pending":
                return {"state": "reading", "eta_s": r.get("eta_s", 60)}
            if chat:
                files.footage_done(root, chat, sha)
            if r.get("state") in ("gone", "expired") and again:     # the service restarted under the job: once more
                return await make_ready(workspace, root, full, rel, chat=chat, language=language, send_budget=send_budget,
                                        read_budget=read_budget, progress=progress, by=by, again=False)
            if r.get("state") != "done":
                raise NotReady(f"the clip could not be made ready: {r.get('error') or r.get('state')}")
            info, sheet = r["info"], r.get("sheet")
    # What is said, beside the clip. A transcript already there for these same bytes is the one to
    # keep: someone may have corrected it.
    words_rel = None
    if info.get("transcript"):
        words_rel = media.words_path(full).relative_to(root.resolve()).as_posix()
        kept = media.clip_words(full, sha)
        if kept is None:
            said = {**info["transcript"], "sha": sha, "clip": rel}
            async with lock(root / words_rel):
                await write_fig(root, words_rel, json.dumps(said, ensure_ascii=False, indent=1).encode("utf-8"),
                                by=by, reason="video-footage")
        else:
            info = {**info, "transcript": kept}
    return {"state": "ready", "info": info, "sheet": sheet, "reused": reused, "sha": sha, "words_rel": words_rel}


def shape_for(width, height):
    """The format for a clip's shape: (name, width, height). Wide for anything filmed sideways (4:3 too:
    it keeps more of the picture than a square would), square near 1:1, portrait for 3:4 to 4:5, and
    vertical for a phone held upright."""
    ratio = (width or 16) / (height or 9)
    name = "wide" if ratio >= 1.2 else "square" if ratio > 0.9 else "portrait" if ratio >= 0.7 else "vertical"
    return (name, *sizes.SHAPES[name])


def _name_for(root, rel):
    """A new video's name from the clip's: the chat's attachment id taken off, and never one whose
    composition or MP4 is already there (the clip itself may be videos/<name>.mp4)."""
    stem = Path(rel).name.rsplit(".", 1)[0]
    base = files.clean_name(_ATTACHED.sub("", stem)) or "clip"
    name, n = base, 1
    while (Path(root) / files.composition(name)).exists() or (Path(root) / files.mp4(name)).exists():
        n += 1
        name = f"{base}-{n}"
    return name


def _clock(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def starter_html(src, width, height, duration, lang="en"):
    """The clip alone: one piece of it, the whole length, fitted inside the frame on black."""
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={width}, height={height}">
<style>
  body {{ margin: 0; }}
  #root {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; background: #000; }}
  #root > video {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-no-timeline data-start="0" data-duration="{duration:g}" data-width="{width}" data-height="{height}">
  <video id="clip" src="{src}" data-start="0" data-media-start="0" data-duration="{duration:g}" data-track-index="0"></video>
</div>
</body>
</html>
"""


async def starter(root, rel, info, by="user"):
    """The clip's video: the one made from it before, or a new one → (path, made now, notice or None).
    NotReady when the clip cannot be a video (too short, a name the page cannot carry)."""
    root = Path(root)
    found = video_for(root, rel)
    if found:
        return found, False, None
    if any(c in rel for c in '"<>'):
        raise NotReady(f"{rel} has a character in its name a video cannot point at (\" < >); rename the file and try again.")
    whole = float(info.get("duration") or 0)
    if whole < MIN_S:
        raise NotReady(f"{rel} is {whole:.1f} s long; a video runs at least {MIN_S} seconds.")
    duration = math.floor(min(whole, MAX_S) * 100) / 100
    _, width, height = shape_for(info.get("width"), info.get("height"))
    said = (info.get("transcript") or {}).get("language")
    html = starter_html(rel, width, height, duration, "ar" if said == "ar" else "en")
    comp = files.composition(_name_for(root, rel))
    async with lock(root / comp):
        await write_fig(root, comp, html.encode("utf-8"), by=by, reason="video-from-clip")
    await asyncio.to_thread(_remember, root, rel, comp)
    notice = None
    if whole > MAX_S:
        notice = (f"A video runs up to {MAX_S} seconds, so this one holds the first {MAX_S} s of the clip "
                  f"(it runs {_clock(whole)}). Ask Cycls for a different part of it.")
    return comp, True, notice


async def open_clip(workspace, root, rel, *, progress=None, by="user"):
    """Edit on a clip: its video, made ready and written if it must be → {"state": "ready", "path",
    "made", "notice"?}. NotReady says why it cannot be."""
    comp = composition_of(root, rel)
    if comp:
        return {"state": "ready", "path": comp, "made": False}
    full = Path(root) / rel
    r = await make_ready(workspace, root, full, rel, progress=progress, by=by)
    comp, made, notice = await starter(root, rel, r["info"], by=by)
    return {"state": "ready", "path": comp, "made": made, **({"notice": notice} if notice else {})}

"""An animation rendered as a video, in chunks, driven by whoever has the Studio open.

A five-second 720p video is many minutes of Cycles: more than one engine call may take, and
Cloud Run throttles a server's CPU once it has answered, so nothing can render in the
background here. The app drives it instead. `start` snapshots the scene into a job; each
`chunk` renders the next few frames into an mp4 segment (one request, a few minutes);
`finish` joins the segments into renders/<name>.mp4. A job is a file —
apps/studio/data/jobs/<id>.json, its scene and segments in jobs/<id>/ — so a reload, another
tab, or the agent's `render {animation: true}` picks it up where it stands.

Chunks are claimed under a per-job lock; a claim older than CLAIM_TTL is taken again (a tab
closed mid-chunk). Each chunk is sized from the job's measured seconds per frame to take
about CHUNK_TARGET, so no call nears the engine's limit.
"""
import asyncio
import base64
import contextlib
import json
import pathlib
import re
import secrets
import shutil
import time
from datetime import datetime, timezone

from . import APP_DIR, engine_name, renderer_name
from . import engine, store
from . import scene as S

MAX_FRAMES = 240                    # ten seconds at 24 fps
MAX_PIXELS = 1280 * 720
MAX_SAMPLES = 64
FRAMES_PER_HOUR = 600               # per person: two long videos an hour
CHUNK_MAX = 120                     # the engine's cap on frames a call
CHUNK_TARGET = 240                  # seconds of Blender a chunk (the engine stops a call at 600)
FIRST_TARGET = 90                   # the first chunk is short: it measures the rest
CLAIM_TTL = 15 * 60
SLOT_WAIT = 600                     # a chunk waits this long for the engine, then answers "busy"
FAILS = 3                           # failures of one chunk before the job gives up
KEEP_JOBS = 20
PRIOR_RATE = 1.0                    # seconds per (megapixel × sample), before this workspace has renders
_ID = re.compile(r"^v-[0-9a-f]{8}$")

_locks, _frames = {}, {}
_slots = None


class VideoError(Exception):
    """Refused or failed; the message is for the person (or the model)."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jobs_dir(ws):
    return pathlib.Path(ws.root) / APP_DIR / "data" / "jobs"


def _path(ws, jid):
    if not isinstance(jid, str) or not _ID.match(jid):
        raise VideoError("no such video job")
    return _jobs_dir(ws) / f"{jid}.json"


def _lock(ws, jid):
    key = str(_path(ws, jid).resolve())
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


def _slots_now():
    """Chunks rendering at once from this server: one on the shared engine (interactive ops
    keep the rest of it), four on a renderer of its own."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(4 if renderer_name() != engine_name() else 1)
    return _slots


def _read(ws, jid):
    path = _path(ws, jid)
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise VideoError("no such video job") from None
    except (OSError, ValueError):
        raise VideoError(f"video job {jid} is unreadable") from None
    return job


def _write(ws, job):
    job["updated"] = _now()
    path = _path(ws, job["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=1), encoding="utf-8")
    tmp.replace(path)
    return job


def _all(ws):
    out = []
    for p in _jobs_dir(ws).glob("v-*.json"):
        with contextlib.suppress(OSError, ValueError):
            out.append(json.loads(p.read_text(encoding="utf-8")))
    return sorted(out, key=lambda j: j.get("created", ""))


def _rate(ws):
    """Seconds per (megapixel × sample) for a still here: the median of the recent renders
    this workspace logged (videos aside), or a prior."""
    try:
        rows = json.loads((pathlib.Path(ws.root) / APP_DIR / "data" / "renders.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    rates = sorted(r["seconds"] / (r["resolution"][0] * r["resolution"][1] * r["samples"] / 1e6)
                   for r in (rows if isinstance(rows, list) else [])[-12:]
                   if isinstance(r, dict) and not r.get("video") and r.get("seconds") and r.get("samples")
                   and isinstance(r.get("resolution"), list))
    return rates[len(rates) // 2] if rates else PRIOR_RATE


def progress(job):
    """Frames done, the total, and a guess at the seconds left: Blender's measured pace, a few
    seconds a call on top, and the join at the end."""
    a, b = job["frames"]
    total = b - a + 1
    done = sum(c["frames"][1] - c["frames"][0] + 1 for c in job["chunks"] if c["state"] == "done")
    left = total - done
    if job["status"] != "running":
        return {"done": done, "total": total, "seconds_left": 0}
    calls = -(-left // max(1, job["chunk"]))
    return {"done": done, "total": total, "seconds_left": round(left * job["spf"] * 1.05 + 6 * calls + 15)}


def view(job):
    """A job as the app and the model see it."""
    keep = ("id", "name", "status", "by", "rev", "frames", "fps", "resolution", "samples", "created", "updated",
            "path", "error")
    return {**{k: job[k] for k in keep if k in job}, **progress(job)}


def _budget(subject, n):
    now = time.time()
    hour = [(t, k) for t, k in _frames.get(subject, []) if now - t < 3600]
    used = sum(k for _, k in hour)
    if used + n > FRAMES_PER_HOUR:
        return max(60, int(3600 - (now - hour[0][0]))) if hour else 3600
    _frames[subject] = hour + [(now, n)]
    if len(_frames) > 10_000:
        _frames.clear()
    return 0


# ─────────────────────────────── the steps ─────────────────────────────────────

async def start(ws, doc, params=None, by="app"):
    """A new job for `doc`'s animation. One running job a workspace."""
    p = params or {}
    doc = S.normalize(doc)
    if not S.animated(doc):
        raise VideoError("nothing moves in this scene — key something (or add a turntable) first")
    if not doc["render"]["camera"]:
        raise VideoError("the scene has no render camera — add one first")
    a = doc["animation"]
    fr = p.get("frames") or [a["frame_start"], a["frame_end"]]
    if not (isinstance(fr, list) and len(fr) == 2 and all(isinstance(x, int) for x in fr) and 0 <= fr[0] <= fr[1]):
        raise VideoError("frames: [first, last]")
    if fr[1] - fr[0] + 1 > MAX_FRAMES:
        raise VideoError(f"that's {fr[1] - fr[0] + 1} frames — a video is at most {MAX_FRAMES} "
                         f"({MAX_FRAMES / a['fps']:.0f} s at {a['fps']} fps); shorten the timeline or lower the fps")
    res = p.get("resolution") or doc["render"]["resolution"]
    if not (isinstance(res, list) and len(res) == 2 and all(isinstance(x, int) and x >= 16 for x in res)):
        raise VideoError("resolution: [width, height]")
    if res[0] * res[1] > MAX_PIXELS:                      # the render's shape, at most 720p
        k = (MAX_PIXELS / (res[0] * res[1])) ** 0.5
        res = [int(res[0] * k), int(res[1] * k)]
    res = [res[0] // 2 * 2, res[1] // 2 * 2]              # H.264 wants even sides
    samples = min(MAX_SAMPLES, int(p.get("samples") or min(doc["render"]["samples"], 16)))
    running = [j for j in await asyncio.to_thread(_all, ws) if j.get("status") == "running"]
    if running:
        j = running[-1]
        pr = progress(j)
        raise VideoError(f"a video is already rendering ({j['id']}, {pr['done']}/{pr['total']} frames) — "
                         "cancel it or wait for it")
    from .tool import _slug
    jid = "v-" + secrets.token_hex(4)
    spf = _rate(ws) * res[0] * res[1] * samples / 1e6
    job = {"id": jid, "name": _slug(p.get("name"), "animation"), "status": "running", "by": by,
           "rev": doc.get("rev", 0), "frames": fr, "fps": a["fps"], "resolution": res, "samples": samples,
           "chunks": [], "next": fr[0], "spf": round(spf, 3), "measured": False, "created": _now()}
    job["chunk"] = _size(job)

    def write():
        d = _jobs_dir(ws) / jid
        d.mkdir(parents=True, exist_ok=True)
        (d / "scene.json").write_text(json.dumps(doc), encoding="utf-8")
        _write(ws, job)
        _trim(ws)
    await asyncio.to_thread(write)
    return view(job)


def _size(job):
    target = CHUNK_TARGET if job["measured"] else FIRST_TARGET
    return max(1, min(CHUNK_MAX, int(target / max(job["spf"], 0.05))))


def _claim(job):
    """The next frames to render — a stale claim again, or a new chunk — or None."""
    now = time.time()
    for i, c in enumerate(job["chunks"]):
        if c["state"] == "claimed" and now - c["at"] > CLAIM_TTL:
            c["at"] = now
            return i
    a, b = job["next"], job["frames"][1]
    if a > b:
        return None
    job["chunks"].append({"frames": [a, min(b, a + job["chunk"] - 1)], "state": "claimed", "at": now, "fails": 0})
    job["next"] = job["chunks"][-1]["frames"][1] + 1
    return len(job["chunks"]) - 1


async def chunk(ws, jid):
    """Render the next chunk. {job} after it; {job, wait} when there's nothing to take yet,
    the engine is busy, or this hour's frames are spent — the caller comes back later."""
    async with _lock(ws, jid):
        job = await asyncio.to_thread(_read, ws, jid)
        if job["status"] != "running":
            return {"job": view(job)}
        i = _claim(job)
        if i is None:
            return {"job": view(job), "wait": 20 if any(c["state"] != "done" for c in job["chunks"]) else 0}
        fr = job["chunks"][i]["frames"]
        wait = _budget(ws.subject, fr[1] - fr[0] + 1)
        if wait:                                             # the claim isn't saved
            return {"job": view(job), "wait": wait,
                    "reason": f"that's {FRAMES_PER_HOUR} frames this hour — it carries on later"}
        await asyncio.to_thread(_write, ws, job)
    slots = _slots_now()
    try:
        await asyncio.wait_for(slots.acquire(), SLOT_WAIT)
    except asyncio.TimeoutError:
        await _release(ws, jid, i)
        return {"job": view(job), "wait": 30, "reason": "the Studio engine is busy"}
    try:
        doc = await asyncio.to_thread(_scene, ws, jid)
        blobs = await asyncio.to_thread(store.blobs, ws, doc, "video")
        r = await engine.call("video", doc, blobs=blobs, ws=ws,
                              params={"frames": fr, "resolution": job["resolution"], "samples": job["samples"],
                                      "poster": i == 0})
    except (engine.EngineError, S.SceneError, VideoError) as e:
        return await _failed(ws, jid, i, str(e))
    finally:
        slots.release()
    res, files = r["result"], r["files"]
    async with _lock(ws, jid):
        job = await asyncio.to_thread(_read, ws, jid)
        if job["status"] != "running":                        # cancelled meanwhile: drop it
            return {"job": view(job)}
        d = _jobs_dir(ws) / jid

        def save():
            (d / f"s-{i:03d}.mp4").write_bytes(files["segment.mp4"])
            if "poster.jpg" in files:
                (d / "poster.jpg").write_bytes(files["poster.jpg"])
        await asyncio.to_thread(save)
        c = job["chunks"][i]
        c.update(state="done", seconds=res.get("render_seconds"), at=time.time())
        job["spf"] = round(res.get("seconds_per_frame") or job["spf"], 3)
        job["measured"] = True
        job["chunk"] = _size(job)
        await asyncio.to_thread(_write, ws, job)
    return {"job": view(job), "chunk": i}


async def _release(ws, jid, i):
    async with _lock(ws, jid):
        job = await asyncio.to_thread(_read, ws, jid)
        if i < len(job["chunks"]) and job["chunks"][i]["state"] == "claimed":
            job["chunks"][i]["at"] = 0
            await asyncio.to_thread(_write, ws, job)


async def _failed(ws, jid, i, error):
    """A chunk that failed is taken again on the next call; the third failure (busy aside)
    ends the job."""
    busy = "busy" in error
    async with _lock(ws, jid):
        job = await asyncio.to_thread(_read, ws, jid)
        c = job["chunks"][i] if i < len(job["chunks"]) else None
        if c is None or job["status"] != "running":
            return {"job": view(job)}
        c["at"] = 0
        if not busy:
            c["fails"] = c.get("fails", 0) + 1
            if c["fails"] >= FAILS:
                job.update(status="failed", error=error[:500])
        await asyncio.to_thread(_write, ws, job)
    if job["status"] == "failed":
        return {"job": view(job), "error": error}
    return {"job": view(job), "wait": 30 if busy else 10, "reason": error[:300]}


def _scene(ws, jid):
    try:
        return S.normalize(json.loads((_jobs_dir(ws) / jid / "scene.json").read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        raise VideoError(f"the video's scene is gone ({e})") from None


async def finish(ws, jid):
    """Join the segments into renders/<name>.mp4 (logged with the renders) once every chunk
    is in. Answers {job, path, poster, open}."""
    from .tool import _free
    async with _lock(ws, jid):
        job = await asyncio.to_thread(_read, ws, jid)
        if job["status"] == "done":
            return {"job": view(job), "path": job.get("path"), "open": job.get("path")}
        if job["status"] != "running":
            raise VideoError(f"that video was {job['status']}")
        pr = progress(job)
        if pr["done"] < pr["total"]:
            raise VideoError(f"{pr['total'] - pr['done']} frames aren't rendered yet")
        d = _jobs_dir(ws) / jid
        chunks = sorted(job["chunks"], key=lambda c: c["frames"][0])
        order = [job["chunks"].index(c) for c in chunks]

        def read():
            return {f"segments/s-{n:03d}.mp4": (d / f"s-{i:03d}.mp4").read_bytes() for n, i in enumerate(order)}
        try:
            segs = await asyncio.to_thread(read)
        except OSError:
            job.update(status="failed", error="a segment went missing — render it again")
            await asyncio.to_thread(_write, ws, job)
            raise VideoError(job["error"]) from None
        r = await engine.call("encode", {}, blobs=segs,
                              params={"segments": len(segs), "fps": job["fps"], "resolution": job["resolution"]})
        rel = _free(ws.root, "renders", job["name"], "mp4")
        poster = d / "poster.jpg"

        def save():
            (pathlib.Path(ws.root) / rel).write_bytes(r["files"]["video.mp4"])
            store.log_render(ws, {"path": rel, "rev": job["rev"], "resolution": job["resolution"],
                                  "samples": job["samples"], "frames": pr["total"], "fps": job["fps"], "video": True,
                                  "seconds": round(sum(c.get("seconds") or 0 for c in job["chunks"]), 1),
                                  "by": job["by"]})
            for p in d.glob("s-*.mp4"):
                p.unlink()
            with contextlib.suppress(OSError):
                (d / "scene.json").unlink()
            return base64.b64encode(poster.read_bytes()).decode() if poster.exists() else None
        b64 = await asyncio.to_thread(save)
        job.update(status="done", path=rel)
        await asyncio.to_thread(_write, ws, job)
    return {"job": view(job), "path": rel, "open": rel,
            "poster": f"data:image/jpeg;base64,{b64}" if b64 else None}


async def cancel(ws, jid):
    async with _lock(ws, jid):
        job = await asyncio.to_thread(_read, ws, jid)
        if job["status"] == "running":
            job["status"] = "cancelled"
            await asyncio.to_thread(_write, ws, job)
            await asyncio.to_thread(shutil.rmtree, _jobs_dir(ws) / jid, True)
    return {"job": view(job)}


async def jobs(ws):
    """Running jobs first, then the latest others."""
    items = [view(j) for j in await asyncio.to_thread(_all, ws)]
    return [j for j in items if j["status"] == "running"] + [j for j in items if j["status"] != "running"][-5:][::-1]


def poster(ws, jid):
    p = _jobs_dir(ws) / jid / "poster.jpg"
    return f"data:image/jpeg;base64,{base64.b64encode(p.read_bytes()).decode()}" if p.exists() else None


def _trim(ws):
    """Keep the last KEEP_JOBS job files; what's left of older jobs goes too."""
    items = _all(ws)
    for j in items[:-KEEP_JOBS]:
        if j.get("status") == "running":
            continue
        with contextlib.suppress(OSError, VideoError):
            _path(ws, j["id"]).unlink()
        shutil.rmtree(_jobs_dir(ws) / j["id"], ignore_errors=True)


def scenes_in_use(root):
    """The scenes running jobs will render: their mesh and image files must stay."""
    out = []
    for p in (pathlib.Path(root) / APP_DIR / "data" / "jobs").glob("v-*/scene.json"):
        with contextlib.suppress(OSError, ValueError):
            out.append(json.loads(p.read_text(encoding="utf-8")))
    return out

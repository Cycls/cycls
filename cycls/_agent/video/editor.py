"""The video editor: a person changes a video by hand, inside the Cycls canvas.

The editor runs on the cycls-video service (its Editor unit, VIDEO_EDITOR_URL): the SDK opens a session
for one composition with what it names — the same images, audio, words and clips a check sends — and
the canvas embeds the session's page (`/s/<sid>/`). Each change comes back to the page as the clean
source and is saved here like any file, with `PUT /files?base=` (a stale base is a 412 and the
conflict dialog). The workspace stays the truth; the session is a working copy.

    open(workspace, root, path, host_origin) → {url, sid, versions, notice?}
    replace(workspace, root, sid, path)       after an agent edit, the session holds the new file
    close(workspace, sid)
    render(workspace, root, path, quality)    the MP4 beside the composition (started; poll render_state)

An older video (protocol 3) comes back from the service upgraded for the editor (scene-relative
animations, cutaways on their own track); that upgrade is kept here as a version of its own, before
the session opens, so the person can always go back to what the agent made.

Configured by VIDEO_EDITOR_URL beside the service's own VIDEO_URL / VIDEO_SECRET / VIDEO_ORGS.
"""
import asyncio
import hashlib
import json
import os
import posixpath
import time
from pathlib import Path

import httpx

from .. import trash
from ..design.deck import lock
from ..design.store import version_of, write_fig
from ..paths import _resolve_path
from . import client, files, media, sizes

_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
_SUFFIX = ".video.html"


class Unavailable(RuntimeError):
    """The editor is not configured, not offered here, or the service did not answer."""


def configured():
    return bool(os.environ.get("VIDEO_EDITOR_URL")) and client.configured()


def offered(workspace):
    return configured() and client.offered(workspace)


def _url(path):
    return os.environ["VIDEO_EDITOR_URL"].rstrip("/") + path


async def _call(method, path, workspace, **kw):
    headers = {k: v for k, v in client._headers(workspace).items() if k != "X-Video-Proto"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as http:
            resp = await http.request(method, _url(path), headers=headers, **kw)
    except httpx.HTTPError as e:
        raise Unavailable(f"the video editor is unreachable: {type(e).__name__}") from e
    if resp.status_code == 401:
        raise Unavailable("the video editor refused the key (VIDEO_SECRET)")
    if resp.status_code >= 500 or 300 <= resp.status_code < 400:
        raise Unavailable(f"the video editor answered {resp.status_code}")
    return resp


def _words_files(html, root, audio, footage, rel):
    """The words files the video's captions come from, by workspace path: {path: {media, json, shared}}
    — `media` as the composition names it, `shared` when another video in the workspace names it too."""
    out = {}
    named = [(p, "audio") for p in audio] + [(p, "footage") for p in footage]
    others = None
    for written, _kind in named:
        try:
            ws_rel = posixpath.normpath(posixpath.join("videos", written)) if written.startswith("../") else written
            full = _resolve_path(ws_rel, root)
        except ValueError:
            continue
        side = media.words_path(full)
        if not side.is_file():
            continue
        try:
            data = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("words"), list):
            continue
        if others is None:
            others = _other_videos(root, rel)
        name = full.name
        shared = any(name in text for text in others)
        out[side.resolve().relative_to(Path(root).resolve()).as_posix()] = {"media": written, "json": data, "shared": shared}
    return out


def _other_videos(root, rel):
    d = Path(root) / files.DIR
    texts = []
    if d.is_dir():
        for p in d.glob(f"*{_SUFFIX}"):
            if p.name != Path(rel).name:
                try:
                    texts.append(p.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
    return texts


def _parts(meta, sent):
    parts = [("meta", (None, json.dumps(meta)))]
    for name, data in sent.items():
        parts.append((name, (name, data, "application/octet-stream")))
    return parts


def _gather(html, root, rel):
    from . import fonts as kit_fonts

    images, image_files, problems = media.collect(html, root)
    audio, audio_files, _words, more = media.collect_audio(html, root)
    footage, clips = media.collect_footage(html, root)
    problems += more + clips
    words = _words_files(html, root, audio, footage, rel)
    # The brand kit's fonts, every one: the preview draws a video's brand font as its render does, and
    # the editor's font list offers them beside the catalogue's.
    fonts, font_files = kit_fonts.for_html(root, html, every=True)
    lotties, lottie_files, animations = media.collect_lotties(html, root)
    problems += animations
    meta = {"images": images, "audio": audio, "footage": {p: f["sha"] for p, f in footage.items()},
            "words": words, **({"fonts": fonts} if fonts else {}), **({"lotties": lotties} if lotties else {})}
    brand = _brand(root)
    if brand:
        meta["brand"] = brand
        # The logo goes with the session, so Media's "Brand logo" and the Motion menu's logo reveal can use it.
        logo = brand.get("logo")
        if logo and logo not in images:
            try:
                data = (Path(root) / logo).read_bytes()
                if len(data) <= media.MAX_BYTES and logo.rsplit(".", 1)[-1].lower() in media.TYPES:
                    hashed = hashlib.sha256(data).hexdigest()[:32] + "." + logo.rsplit(".", 1)[-1].lower()
                    images[logo] = hashed
                    image_files[hashed] = data
            except OSError:
                pass
    return meta, {**image_files, **audio_files, **font_files, **lottie_files}, problems


def _brand(root):
    """The brand kit as the editor's buttons use it: its colours (the word being said, in a caption) and
    the font a caption or a text can take — the heading's, else the body's, when the video can draw it."""
    from . import brand
    from .run import _catalogue

    try:
        k = brand.kit(root, _catalogue()[0])
    except Exception:  # noqa: BLE001 - a kit that cannot be read is no kit
        return None
    if not k:
        return None
    font = next((f[0] for f in (k.get("heading"), k.get("body")) if f and (f[1] or f[2])), None)
    colours = {role: v for role, v in (k.get("colours") or {}).items() if isinstance(v, str)}
    logo = k.get("logo")
    return ({"colours": colours, "font": font, **({"logo": logo} if logo else {})}
            if colours or font or logo else None)


async def open(workspace, root, rel, host_origin):
    """A session for composition `rel` → {url, sid, versions: {path: version}, notice?}. The versions are
    those of the files the editor may write back: the composition (after any upgrade) and its words."""
    if not offered(workspace):
        raise Unavailable("The video editor is not available here.")
    root = Path(root)
    path = root / rel
    data = await asyncio.to_thread(path.read_bytes)
    html = data.decode("utf-8")
    meta, sent, problems = await asyncio.to_thread(_gather, html, root, rel)
    if problems:
        raise ValueError(problems[0])
    meta.update({"path": rel, "html": html, "host_origin": host_origin})
    resp = await _call("POST", "/v1/sessions", workspace, files=_parts(meta, sent))
    body = client._body(resp) or {}
    if resp.status_code != 200:
        raise ValueError(body.get("error") or f"the editor could not open {rel} ({resp.status_code})")
    version = version_of(data)
    if body.get("upgraded") and isinstance(body.get("html"), str) and body["html"] != html:
        async with lock(path):
            version = await write_fig(root, rel, body["html"].encode("utf-8"), base=version, by="user", reason="upgrade")
    versions = {rel: version}
    for words_rel in meta["words"]:
        try:
            versions[words_rel] = version_of((root / words_rel).read_bytes())
        except OSError:
            pass
    out = {"url": _url(body["url"]), "sid": body["sid"], "versions": versions}
    if body.get("notice"):
        out["notice"] = body["notice"]
    return out


async def replace(workspace, root, sid, rel):
    """The session's copy replaced by the workspace's file and what it names now (an agent edit)."""
    root = Path(root)
    html = (await asyncio.to_thread((root / rel).read_bytes)).decode("utf-8")
    meta, sent, problems = await asyncio.to_thread(_gather, html, root, rel)
    if problems:
        raise ValueError(problems[0])
    meta.update({"path": rel, "html": html})
    resp = await _call("PUT", f"/v1/sessions/{sid}", workspace, files=_parts(meta, sent))
    if resp.status_code == 404:
        raise LookupError("the editor session has ended")
    if resp.status_code != 200:
        raise ValueError((client._body(resp) or {}).get("error") or f"the editor answered {resp.status_code}")


MEDIA_KINDS = ("picture", "logo", "video")


def media_kind(rel):
    """What a workspace file can be in a video: "picture" (an image the video can show), "video" (a clip),
    or None."""
    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    return "picture" if ext in media.TYPES else "video" if ext in media.FOOTAGE_TYPES else None


def media_list(root, limit=400):
    """The workspace's pictures and clips the Add menu offers, newest first: [{path, kind, size, modified}]."""
    root = Path(root)
    out = []
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        if any(part.startswith(".") for part in rel.split("/")) or rel.startswith(("videos/voice/", "videos/.")):
            continue
        kind = media_kind(rel)
        if not kind or not p.is_file():
            continue
        st = p.stat()
        if kind == "picture" and st.st_size > media.MAX_BYTES:
            continue
        out.append({"path": rel, "kind": kind, "size": st.st_size, "modified": st.st_mtime})
    out.sort(key=lambda f: f["modified"], reverse=True)
    return out[:limit]


async def add_media(workspace, root, sid, rel, kind, at=0.0):
    """A picture, the brand logo or a clip of the workspace's, put into editor session `sid` at `at` seconds
    (the Add menu, a file dropped on the timeline): a picture's bytes are sent; a clip is made ready first
    (sent to the service and read there, as `footage` does) and named by its sha. → {id}. ValueError says
    why it cannot be."""
    from . import clip

    root = Path(root)
    full = _resolve_path(rel, root)
    if not full.is_file():
        raise LookupError(f"{rel} is not a file in the workspace.")
    what = media_kind(rel)
    if what is None or (kind == "video") != (what == "video"):
        raise ValueError(f"{rel} is not a {'clip' if kind == 'video' else 'picture'} a video can show.")
    meta = {"path": rel, "kind": kind, "at": max(0.0, float(at or 0))}
    sent = {}
    if kind == "video":
        if full.stat().st_size > media.MAX_FOOTAGE_BYTES:
            raise ValueError(f"{rel} is over {media.MAX_FOOTAGE_BYTES // 1048576} MB; a clip in a video is at most that.")
        try:
            r = await clip.make_ready(workspace, root, full, rel, by="user")
        except clip.NotReady as e:
            raise ValueError(str(e)) from e
        meta["sha"] = r["sha"]
    else:
        data = await asyncio.to_thread(full.read_bytes)
        if len(data) > media.MAX_BYTES:
            raise ValueError(f"{rel} is {len(data) / 1048576:.1f} MB; a picture in a video is at most 2 MB. Export it smaller.")
        name = hashlib.sha256(data).hexdigest()[:32] + "." + rel.rsplit(".", 1)[-1].lower()
        meta["file"] = name
        sent[name] = data
    resp = await _call("POST", f"/v1/sessions/{sid}/media", workspace, files=_parts(meta, sent))
    if resp.status_code == 404:
        raise LookupError("the editor session has ended")
    body = client._body(resp) or {}
    if resp.status_code != 200:
        raise ValueError(body.get("error") or f"the editor answered {resp.status_code}")
    return {"id": body.get("id")}


async def close(workspace, sid):
    try:
        await _call("DELETE", f"/v1/sessions/{sid}", workspace)
    except Unavailable:
        pass


# ── a render the editor asks for ──────────────────────────────────────────────────────────────────
# Started in the background (a render outlives a request); the editor's page polls render_state.
_renders = {}


def _key(root, rel):
    return f"{Path(root).resolve()}|{rel}"


def render_state(root, rel):
    return _renders.get(_key(root, rel)) or {"state": "idle"}


def render(workspace, root, rel, quality="standard"):
    """Start rendering composition `rel` to the MP4 beside it (it replaces the one there). → the state."""
    key = _key(root, rel)
    now = _renders.get(key)
    if now and now["state"] == "rendering":
        return now
    _renders[key] = {"state": "rendering", "progress": 0, "at": time.time()}
    asyncio.get_running_loop().create_task(_render(workspace, Path(root), rel, quality, key))
    return _renders[key]


async def _render(workspace, root, rel, quality, key):
    from cycls._agent import video
    from . import fonts as kit_fonts
    from . import run

    state = _renders[key]
    # The editor's Render asks for "standard"; the service renders "final" or "draft".
    quality = "draft" if quality == "draft" else "final"
    try:
        html = (await asyncio.to_thread((root / rel).read_bytes)).decode("utf-8")
        images, image_files, problems = await asyncio.to_thread(media.collect, html, root)
        audio, audio_files, words, more = await asyncio.to_thread(media.collect_audio, html, root)
        footage, clips = await asyncio.to_thread(media.collect_footage, html, root)
        fonts, font_files = await asyncio.to_thread(kit_fonts.for_html, root, html)
        lotties, lottie_files, animations = await asyncio.to_thread(media.collect_lotties, html, root)
        problems += more + clips + animations
        if problems:
            raise ValueError(problems[0])
        sent = {**image_files, **audio_files, **font_files, **lottie_files}
        # The main size and each other size the root lists (sizes.py), one job each, at once.
        shapes, problems = sizes.declared(html)
        if problems:
            raise ValueError(problems[0])
        jobs = []
        for shape, h in [(None, html)] + [(s, sizes.variant(html, s)) for s in shapes]:
            sha = hashlib.sha256(h.encode("utf-8") + json.dumps(sorted(sent), sort_keys=True).encode()).hexdigest()
            job_key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|editor|{rel}|{sha}|{quality}"
                                     f"{'|' + shape if shape else ''}".encode()).hexdigest()
            try:
                job = await video.submit(workspace, "render", h, images, sent, params={"quality": quality},
                                         key=job_key, audio=audio, words=words, footage=footage,
                                         **({"fonts": fonts} if fonts else {}), **({"lotties": lotties} if lotties else {}))
            except video.Refused as e:
                if shape:
                    e.findings = [{**f, "message": f"At {shape}: {f.get('message')}"} for f in e.findings]
                raise
            jobs.append((shape, job))
        t0 = time.time()
        eta = max(30, max(int(j.get("eta_s") or 90) for _, j in jobs))
        results = {}
        while len(results) < len(jobs):
            left = [i for i in range(len(jobs)) if i not in results]
            polled = await asyncio.gather(*(video.poll(workspace, jobs[i][1]["token"]) for i in left))
            for i, r in zip(left, polled):
                if r.get("state") != "pending":
                    results[i] = r
            state["progress"] = min(0.95, (time.time() - t0) / eta)
        for i, (shape, _) in enumerate(jobs):
            if results[i].get("state") != "done":
                raise RuntimeError((f"at {shape}: " if shape else "")
                                   + (results[i].get("error") or results[i].get("state") or "the render failed"))
        name = Path(rel).name[: -len(_SUFFIX)]
        # The MP4s are replaced, every size, and the subtitle files with them (they were timed to the
        # old cut): the new ones, in each language a translation is kept for, as the agent's render writes.
        olds = [files.mp4(name)] + [sizes.mp4(name, s) for s in sizes.SHAPES] + \
            [files.subtitles(name, e) for e in ("srt", "vtt")] + files.translations(root, name)
        for old in olds:
            if (root / old).exists():
                await asyncio.to_thread(trash.trash_path, root, old, "user", "re-render")
        for shape, job in jobs:
            dest = root / (files.mp4(name) if shape is None else sizes.mp4(name, shape))
            await video.fetch(workspace, job["token"], dest, root / ".tmp" / "video-editor")
        sound = jobs[0][1].get("sound")
        if sound:
            await asyncio.to_thread(files.save_sound, root, name, sound)
            await asyncio.to_thread(run._subtitles, root, name, sound, audio, words, footage)
        _renders[key] = {"state": "done", "path": files.mp4(name), "at": time.time()}
    except video.Refused as e:
        errors = [f.get("message") for f in e.findings if f.get("severity") == "error"]
        _renders[key] = {"state": "failed", "message": (errors[0] if errors else str(e))[:300], "at": time.time()}
    except Exception as e:  # noqa: BLE001 - the editor shows why
        _renders[key] = {"state": "failed", "message": str(e)[:300], "at": time.time()}

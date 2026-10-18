"""A video's composition, as the canvas plays it.

`GET /files/<name>.video.html?as=player` answers, always with 200:

    {"html": <the preview page, or null>, "reason": <why there is none, or null>,
     "version": <the composition's version>, "render": {"path": "videos/<name>.mp4", "exists": bool}}

The page is built by the cycls-video service (its bundler, the pinned player, the catalogue's fonts
and the composition's images inlined, each piece of footage carried as a cut of its small proxy,
nothing loaded from anywhere) and kept under `.cache/video/`, keyed by the composition's bytes, each
image it names (path, time, size), each clip (the hash of its bytes, and what is said in it) and the
service's bundle version — so an edit, a changed image or clip or a new engine is a fresh page, and
an unchanged one is free.
When the service cannot build it (not configured, unreachable, the composition has errors), `html`
is null and `reason` says why; the canvas then shows the MP4 if there is one, else a download card.

A shared composition is never played and never sent through the service: the share route serves it
as a download (routers.py). To share a video, share its MP4.
"""
import asyncio
import hashlib
import json
import re
import types
from pathlib import Path

_VIDEO_CACHE = ".cache/video"
_SUFFIX = ".video.html"
_VIDEO_HTML_LIMIT = 400_000     # the service's own limit on a composition


def _composition(name):
    return str(name).lower().endswith(_SUFFIX)


def _versioned(name):
    """Files written only through design.store.write_fig (a version kept, a stale base refused): a
    design, a video, and a video's words — the files the editors write back."""
    name = str(name).lower()
    return name.endswith((".fig", _SUFFIX, ".words.json"))


def _render_of(rel):
    return rel[: -len(_SUFFIX)] + ".mp4"


def _key(html, images, files_info, bundle):
    h = hashlib.sha256(html.encode("utf-8"))
    for path, info in sorted(files_info.items()):
        h.update(f"\n{path}|{info}".encode())
    h.update(f"\nbundle|{bundle}".encode())
    return h.hexdigest()[:32]


async def _video_response(root, file_path, subject):
    from cycls._agent import video
    from cycls._agent.design.store import version_of
    from cycls._agent.video import media

    # The files route hands over a resolved path; the root may come relative or unresolved
    # (`\workspace\local` on Windows): resolve both before one is cut from the other.
    root = Path(root).resolve()
    file_path = Path(file_path).resolve()
    rel = file_path.relative_to(root).as_posix()
    data = await asyncio.to_thread(file_path.read_bytes)
    html = data.decode("utf-8", "replace")
    mp4 = _render_of(rel)
    out = {"html": None, "reason": None, "version": version_of(data),
           "render": {"path": mp4, "exists": (root / mp4).is_file()}}
    if not video.configured():
        out["reason"] = "Video is not configured here."
        return out
    images, image_files, problems = await asyncio.to_thread(media.collect, html, root)
    audio, audio_files, words, more = await asyncio.to_thread(media.collect_audio, html, root)
    footage, clips = await asyncio.to_thread(media.collect_footage, html, root)
    problems += more + clips
    if problems:
        out["reason"] = problems[0]
        return out
    stat = {}
    # A clip by the hash of its bytes, and what is said in it: a corrected word is a fresh page.
    for path, clip in footage.items():
        said = hashlib.sha256(json.dumps(clip.get("words") or {}, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        stat[f"clip:{path}"] = f"{clip['sha']}-{said}"
    for path in [*images, *audio]:
        try:
            st = (root / path).stat() if not path.startswith("../") else None
            stat[path] = f"{st.st_mtime_ns}-{st.st_size}" if st else (images.get(path) or audio.get(path))
        except OSError:
            stat[path] = images.get(path) or audio.get(path)
    for hashed, w in words.items():
        stat[f"words:{hashed}"] = hashlib.sha256(json.dumps(w, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    from cycls._agent.video import contract
    bundle = (contract.cached() or {}).get("bundle") or ""
    cache = root / _VIDEO_CACHE
    key = _key(html, images, stat, bundle)
    hit = cache / f"{key}.json"
    if hit.is_file():
        try:
            return {**json.loads(hit.read_text(encoding="utf-8")), "version": out["version"], "render": out["render"]}
        except ValueError:
            pass
    ws = types.SimpleNamespace(subject=subject)
    try:
        r = await video.compile(ws, html, images, {**image_files, **audio_files}, preview=True, audio=audio, words=words,
                                footage=footage)
    except video.Unavailable as e:
        out["reason"] = f"The video service is unavailable: {e}"
        return out
    except RuntimeError as e:
        out["reason"] = f"The video service could not build the preview: {e}"
        return out
    if r.get("preview"):
        out["html"] = r["preview"]
    else:
        errors = [f for f in r.get("findings") or [] if f.get("severity") == "error"]
        out["reason"] = (f"The composition has {len(errors)} error{'s' if len(errors) != 1 else ''} to fix first."
                         if errors else (r.get("preview_error") or "No preview was built."))
    if out["html"]:
        await asyncio.to_thread(_store, cache, key, {"html": out["html"], "reason": None})
    return out


_CACHE_PAGES = 40
_CACHE_BYTES = 200 * 1024 * 1024


def _store(cache, key, payload):
    cache.mkdir(parents=True, exist_ok=True)
    tmp = cache / f".{key}.part"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(cache / f"{key}.json")
    # A few dozen pages at most, and no more than 200 MB of them: a page is a few MB, and one that
    # carries footage up to about 30. The oldest go first. Only pages go (a page's name is its key,
    # 32 hex characters): this folder also holds what each chat remembers and the clips' hashes
    # (files.py), which the count used to sweep away with the pages.
    pages = sorted((p for p in cache.glob("*.json") if re.fullmatch(r"[0-9a-f]{32}", p.stem)),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for i, page in enumerate(pages):
        total += page.stat().st_size
        if i >= _CACHE_PAGES or (total > _CACHE_BYTES and i > 0):
            page.unlink(missing_ok=True)


def video_router(ws_dep, changed):
    """The routes the video editor's page uses (video/editor.py). `changed(root)` tells the files
    catalog something was written.

        POST   /video/editor?path=        a session for the composition → {url, sid, versions, notice?}
        PUT    /video/editor?path=&sid=   the session takes the workspace's file again (an agent edit)
        DELETE /video/editor?sid=         the session closes
        POST   /video/render?path=&quality=   the MP4 beside the composition, started → its state
        GET    /video/render?path=        {state: idle | rendering | done | failed, progress?, path?, message?}
    """
    from fastapi import APIRouter, HTTPException, Request

    from cycls._agent.web.shared import _safe_path
    from cycls._app.db import Workspace

    r = APIRouter()

    def _rel(ws, path):
        if not path or not _composition(path):
            raise HTTPException(400, "path: a videos/<name>.video.html")
        file_path = _safe_path(ws.root, path)
        if not file_path.is_file():
            raise HTTPException(404, "There is no such video.")
        return file_path.relative_to(Path(ws.root).resolve()).as_posix()

    @r.post("/video/editor")
    async def open_editor(path: str, request: Request, ws: Workspace = ws_dep):
        from cycls._agent.video import editor
        rel = _rel(ws, path)
        origin = request.headers.get("origin") or f"{request.url.scheme}://{request.url.netloc}"
        try:
            opened = await editor.open(ws, ws.root, rel, origin)
        except editor.Unavailable as e:
            raise HTTPException(503, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        changed(ws.root)
        return opened

    @r.put("/video/editor")
    async def replace_editor(path: str, sid: str, ws: Workspace = ws_dep):
        from cycls._agent.video import editor
        rel = _rel(ws, path)
        try:
            await editor.replace(ws, ws.root, sid, rel)
        except LookupError as e:
            raise HTTPException(410, str(e))
        except editor.Unavailable as e:
            raise HTTPException(503, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True}

    @r.delete("/video/editor")
    async def close_editor(sid: str, ws: Workspace = ws_dep):
        from cycls._agent.video import editor
        await editor.close(ws, sid)
        return {"ok": True}

    @r.post("/video/render")
    async def render(path: str, quality: str = "standard", ws: Workspace = ws_dep):
        from cycls._agent.video import editor
        if quality not in ("draft", "standard", "final"):
            raise HTTPException(400, "quality: draft, standard or final")
        rel = _rel(ws, path)
        if not editor.offered(ws):
            raise HTTPException(503, "Video is not available here.")
        return editor.render(ws, ws.root, rel, quality)

    @r.get("/video/render")
    async def render_state(path: str, ws: Workspace = ws_dep):
        from cycls._agent.video import editor
        return editor.render_state(ws.root, _rel(ws, path))

    return r

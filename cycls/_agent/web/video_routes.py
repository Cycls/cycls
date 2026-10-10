"""A video's composition, as the canvas plays it.

`GET /files/<name>.video.html?as=player` answers, always with 200:

    {"html": <the preview page, or null>, "reason": <why there is none, or null>,
     "version": <the composition's version>, "render": {"path": "videos/<name>.mp4", "exists": bool}}

The page is built by the cycls-video service (its bundler, the pinned player, the catalogue's fonts
and the composition's images inlined, nothing loaded from anywhere) and kept under `.cache/video/`,
keyed by the composition's bytes, each image it names (path, time, size) and the service's bundle
version — so an edit, a changed image or a new engine is a fresh page, and an unchanged one is free.
When the service cannot build it (not configured, unreachable, the composition has errors), `html`
is null and `reason` says why; the canvas then shows the MP4 if there is one, else a download card.

A shared composition is never played and never sent through the service: the share route serves it
as a download (routers.py). To share a video, share its MP4.
"""
import asyncio
import hashlib
import json
import types
from pathlib import Path

_VIDEO_CACHE = ".cache/video"
_SUFFIX = ".video.html"


def _composition(name):
    return str(name).lower().endswith(_SUFFIX)


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
    if problems:
        out["reason"] = problems[0]
        return out
    stat = {}
    for path in images:
        try:
            st = (root / path).stat() if not path.startswith("../") else None
            stat[path] = f"{st.st_mtime_ns}-{st.st_size}" if st else images[path]
        except OSError:
            stat[path] = images[path]
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
        r = await video.compile(ws, html, images, image_files, preview=True)
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


def _store(cache, key, payload):
    cache.mkdir(parents=True, exist_ok=True)
    for old in sorted(cache.glob("*.json"), key=lambda p: p.stat().st_mtime)[:-40]:
        old.unlink(missing_ok=True)   # a few dozen pages at most; each is a few MB
    tmp = cache / f".{key}.part"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(cache / f"{key}.json")

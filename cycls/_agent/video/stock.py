"""Stock footage for Video.

`footage {stock: "waves at sunset"}` searches Pexels for a clip, saves the one picked in the
workspace (videos/footage/…) and hands back its path, so the rest of the tool sees an ordinary
clip of the person's: made ready, described, cut. The other results are listed with it, each by
what its page calls it, so another can be picked without searching again. The filmmaker is
credited in the reply.

Configured by `PEXELS_API_KEY` (the agent process's environment), the key Design's stock photos
use. Without it the reply says to put a clip in the workspace instead.
"""
import json
import os
import re
from pathlib import Path

SEARCH = "https://api.pexels.com/videos/search"
DIR = "videos/footage"
MAX_BYTES = 200 * 1024 * 1024
MAX_SECONDS = 120
RESULTS = 6
FETCH_BUDGET_S = 180      # a clip that is not here by then is given up on: the call says so, and the model picks again


def configured():
    return bool(os.environ.get("PEXELS_API_KEY"))


# Network calls, one place each — tests replace them.
async def _search(query, orientation, per_page):
    import httpx
    params = {"query": query, "per_page": per_page, **({"orientation": orientation} if orientation else {})}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(SEARCH, params=params, headers={"Authorization": os.environ["PEXELS_API_KEY"]})
        r.raise_for_status()
        return r.json()


async def _download(url, dest):
    """Stream a clip to `dest`, refusing a host that is not Pexels', a file past MAX_BYTES, and a
    download still going after FETCH_BUDGET_S (each read has its own timeout, so a slow link would
    otherwise hold the turn for as long as it kept trickling: 4.4 MB took 320 s once, 2026-10-13)."""
    import time

    import httpx
    deadline = time.monotonic() + FETCH_BUDGET_S
    host = httpx.URL(url).host or ""
    if not url.startswith("https://") or not (host == "pexels.com" or host.endswith(".pexels.com")):
        raise ValueError(f"unexpected video host {host!r}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part")
    size = 0
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True) as client:
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 20):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError("that stock clip is too large; pick another")
                        if time.monotonic() > deadline:
                            raise ValueError("that stock clip is taking too long to fetch; try again, or pick another")
                        f.write(chunk)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return size


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "clip"


def _title(video):
    """What the clip's page calls it: the words of its address (…/video/waves-at-sunset-1234/)."""
    m = re.search(r"/video/([^/]+?)-?\d*/?$", str(video.get("url") or ""))
    return m.group(1).replace("-", " ").strip() if m and m.group(1) else "untitled"


def _file(video):
    """The MP4 to fetch: the largest whose long side is at most 1920, else the smallest there is."""
    files = [f for f in video.get("video_files") or [] if f.get("file_type") == "video/mp4" and f.get("link")
             and f.get("width") and f.get("height")]
    if not files:
        return None
    fits = [f for f in files if max(f["width"], f["height"]) <= 1920]
    return max(fits, key=lambda f: f["width"] * f["height"]) if fits else min(files, key=lambda f: f["width"] * f["height"])


def _line(n, video):
    return f"{n}: {_title(video)} ({video.get('duration') or '?'} s, {video.get('width')}x{video.get('height')})"


async def find(root, query, *, orientation=None, pick=0):
    """→ (workspace path of the clip, credit, the other results as lines). ValueError says what to do."""
    query = " ".join(str(query or "").split())[:80]
    if not query:
        raise ValueError("stock needs a few words to search for, e.g. \"waves at sunset\"")
    if not configured():
        raise ValueError("stock footage isn't set up here — put a clip in the workspace and give its path instead")
    if orientation not in (None, "landscape", "portrait", "square"):
        orientation = None
    folder = Path(root) / DIR
    index_path = folder / ".index.json"
    try:
        index = json.loads(index_path.read_text("utf-8"))
    except (OSError, ValueError):
        index = {}
    key = f"{query.lower()}|{orientation or ''}|{pick}"
    hit = index.get(key)
    if hit and (Path(root) / hit["path"]).is_file():
        return hit["path"], hit["credit"], hit.get("others") or []
    data = await _search(query, orientation, RESULTS)
    videos = [v for v in data.get("videos") or [] if _file(v) and (v.get("duration") or 0) <= MAX_SECONDS]
    if not videos:
        raise ValueError(f"no stock clip found for {query!r} — try a simpler query (two or three words)")
    pick = min(max(int(pick), 0), len(videos) - 1)
    v = videos[pick]
    rel = f"{DIR}/{_slug(query)}-{v.get('id')}.mp4"
    await _download(_file(v)["link"], Path(root) / rel)
    by = " ".join(str((v.get("user") or {}).get("name") or "unknown").split())
    credit = f"Video by {by} on Pexels ({v.get('url') or 'pexels.com'})."
    others = [_line(i, x) for i, x in enumerate(videos) if i != pick]
    index[key] = {"path": rel, "credit": credit, "others": others}
    folder.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=1), "utf-8")
    return rel, credit, others

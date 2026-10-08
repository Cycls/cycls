"""Stock photos for Design.

Anywhere a design takes an image — an image node's `src`, a deck slide's `image`, a
team member's `photo`, an edit's `replace_image` — the model may name a photo to
find instead of a file: `"stock": "coffee beans on wood"`. The SDK searches Pexels,
saves the photo in the workspace (attachments/stock/…), and puts that path in as
`src`, so the rest of the pipeline sees an ordinary workspace file: the same size
caps, EXIF handling and fitting, and the photo stays in the workspace for the next
edit. The photographer is credited in the ack.

Configured by `PEXELS_API_KEY` (the agent process's environment). Without it, a
`stock` field is an error telling the model to save a photo into the workspace.
"""
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

SEARCH = "https://api.pexels.com/v1/search"
DIR = "attachments/stock"


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


async def _download(url):
    import httpx
    host = httpx.URL(url).host or ""
    if not url.startswith("https://") or not (host == "pexels.com" or host.endswith(".pexels.com")):
        raise ValueError(f"unexpected photo host {host!r}")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


def _orientation(d):
    o = d.get("orientation")
    if o in ("landscape", "portrait", "square"):
        return o
    try:
        w, h = float(d.get("w") or 0), float(d.get("h") or 0)
    except (TypeError, ValueError):
        return None
    if w and h:
        return "landscape" if w >= h * 1.2 else "portrait" if h >= w * 1.2 else "square"
    return None


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "photo"


async def _photo(root, query, orientation, pick):
    """(workspace path, credit) for the `pick`-th Pexels result for `query` — found
    once and remembered per workspace (attachments/stock/.index.json)."""
    folder = Path(root) / DIR
    index_path = folder / ".index.json"
    key = f"{query.strip().lower()}|{orientation or ''}|{pick}"
    try:
        index = json.loads(index_path.read_text("utf-8"))
    except (OSError, ValueError):
        index = {}
    hit = index.get(key)
    if hit and (Path(root) / hit["path"]).is_file():
        return hit["path"], hit["credit"]
    data = await _search(query, orientation, max(pick + 1, 5))
    photos = data.get("photos") or []
    if not photos:
        raise ValueError(f"no stock photo found for {query!r} — try a simpler query (two or three words)")
    p = photos[min(pick, len(photos) - 1)]
    src = p.get("src") or {}
    url = src.get("large2x") or src.get("original") or src.get("large")
    if not url:
        raise ValueError(f"the stock photo for {query!r} has no downloadable size")
    body = await _download(url)
    rel = f"{DIR}/{_slug(query)}-{p.get('id') or hashlib.sha1(url.encode()).hexdigest()[:10]}.jpg"
    folder.mkdir(parents=True, exist_ok=True)
    target = Path(root) / rel
    tmp = target.with_name(f".{target.name}.part")
    tmp.write_bytes(body)
    tmp.replace(target)
    credit = f"Photo by {p.get('photographer') or 'unknown'} on Pexels ({p.get('url') or 'pexels.com'})"
    index[key] = {"path": rel, "credit": credit}
    index_path.write_text(json.dumps(index, indent=1), "utf-8")
    return rel, credit


_FILE = re.compile(r"\.[A-Za-z0-9]{2,5}$")


def described(src, root):
    """Is `src` a description of a picture rather than a file's name? Several words, no
    extension, no folder — and no such file. (`src`, a slide's `image`, held "modern
    Riyadh skyline at dusk, glass towers": the picture the model wanted, where the name
    of a file goes.)"""
    if not isinstance(src, str):
        return False
    s = src.strip()
    if not (8 <= len(s) <= 300) or " " not in s or "/" in s or "\\" in s or _FILE.search(s) or s.startswith(("http:", "https:", "data:")):
        return False
    try:
        return not (Path(root) / s).is_file()
    except (OSError, ValueError):
        return True


def _query(text):
    """What a photo search can find of a description: its first clause, six words at most."""
    return " ".join(re.split(r"[,.;:—–\n]", text.strip(), maxsplit=1)[0].split()[:6])


async def resolve(obj, root):
    """Every `"stock": "<query>"` in a spec, deck, slide or ops list → `"src": "<path>"`,
    in place. A picture DESCRIBED where a file goes (`described`) is looked for the same
    way, and said. → (credits and notes for the ack, error or None)."""
    found, told = [], []

    def describe(v):
        if isinstance(v, dict):
            for key in ("src", "image", "photo"):
                if described(v.get(key), root) and not v.get("stock"):
                    words = v[key].strip()
                    told.append(words)
                    if key == "src":
                        del v["src"]
                        v["stock"] = _query(words)
                    else:
                        v[key] = {"stock": _query(words)}
            for x in v.values():
                describe(x)
        elif isinstance(v, list):
            for x in v:
                describe(x)

    if configured():
        describe(obj)

    def walk(v):
        if isinstance(v, dict):
            if isinstance(v.get("stock"), str) and v["stock"].strip():
                found.append(v)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(obj)
    if not found:
        return [], None
    if not configured():
        return [], ("Error: stock photos aren't set up here — save a photo into the workspace "
                    "(e.g. attachments/photo.jpg) and use its path as `src` instead of `stock`.")
    credits = []
    try:
        for d in found:
            pick = d.get("pick")
            pick = int(pick) if isinstance(pick, (int, float)) and pick >= 0 else 0
            path, credit = await _photo(root, d["stock"], _orientation(d), pick)
            d["src"] = path
            for k in ("stock", "pick", "orientation"):
                d.pop(k, None)
            if credit not in credits:
                credits.append(credit)
    except ValueError as e:
        return [], f"Error: {e}"
    except Exception as e:
        return [], f"Error: couldn't fetch a stock photo ({e}) — try again, or save a photo into the workspace."
    for words in told:
        short = words if len(words) <= 60 else f"{words[:58]}…"
        credits.append(f"{json.dumps(short, ensure_ascii=False)} is not a file in the workspace, so a stock photo was found for "
                       f"those words (another of them: {{\"stock\": \"…\", \"pick\": 1}}; a file: its path as `src`)")
    return credits, None

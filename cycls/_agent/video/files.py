"""A video's files, and what this chat remembers about them.

videos/<name>.video.html is the composition; videos/<name>.mp4 its render, beside it.

The naming rule: a name this chat made is its own, and writing it again replaces the file (the
old one kept as a version). A name that was already in the workspace before this chat used it
takes a suffix (reel-2), and the reply says so: another chat's video, or the person's, is never
written over. A render replaces only the MP4 this chat rendered for that name, which goes to the
trash first.

What a chat remembers is a small sidecar, .cache/video/<chat id>.json: the names it made, and the
render it started for each, so a render cut off by Stop, a dropped connection or a replaced
instance is collected by the next `render` instead of being paid for twice.
"""
import json
import re
import time
from pathlib import Path

DIR = "videos"
SUFFIX = ".video.html"
SIDECAR = Path(".cache") / "video"
_NAME = re.compile(r"[^a-z0-9؀-ۿ]+")


def clean_name(raw):
    """A file-safe name: lowercase words joined by hyphens; Arabic letters kept. '' when nothing is left."""
    base = str(raw or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    for ext in (SUFFIX, ".html", ".mp4"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
    return _NAME.sub("-", base.lower()).strip("-")[:60]


def composition(name):
    return f"{DIR}/{name}{SUFFIX}"


def mp4(name):
    return f"{DIR}/{name}.mp4"


# A voice-over: videos/voice/<name>.m4a, and its word timings beside it.
VOICE_DIR = f"{DIR}/voice"


def voice_audio(name):
    return f"{VOICE_DIR}/{name}.m4a"


def voice_words(name):
    return f"{VOICE_DIR}/{name}.words.json"


def _sidecar_path(root, chat_id):
    return Path(root) / SIDECAR / f"{re.sub(r'[^A-Za-z0-9_-]', '_', chat_id or 'none')}.json"


def load(root, chat_id):
    try:
        data = json.loads(_sidecar_path(root, chat_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(root, chat_id, data):
    path = _sidecar_path(root, chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def mine(root, chat_id, name):
    return name in load(root, chat_id).get("names", [])


def claim(root, chat_id, name):
    """The name this chat writes under: its own as asked, or the first free `name-N`."""
    root = Path(root)
    if mine(root, chat_id, name) or not (root / composition(name)).exists():
        return name
    n = 2
    while (root / composition(f"{name}-{n}")).exists() and not mine(root, chat_id, f"{name}-{n}"):
        n += 1
    return f"{name}-{n}"


def remember(root, chat_id, name):
    data = load(root, chat_id)
    names = data.setdefault("names", [])
    if name not in names:
        names.append(name)
        save(root, chat_id, data)


def render_started(root, chat_id, name, token, sha, quality):
    data = load(root, chat_id)
    data.setdefault("renders", {})[name] = {"token": token, "sha": sha, "quality": quality, "at": time.time()}
    save(root, chat_id, data)


def render_pending(root, chat_id, name):
    return (load(root, chat_id).get("renders") or {}).get(name)


def render_done(root, chat_id, name, sha):
    data = load(root, chat_id)
    entry = (data.get("renders") or {}).pop(name, None)
    data.setdefault("rendered", {})[name] = {"sha": sha, "at": time.time()}
    save(root, chat_id, data)
    return entry


def voice_started(root, chat_id, name, token, key):
    data = load(root, chat_id)
    data.setdefault("voices", {})[name] = {"token": token, "key": key, "at": time.time()}
    save(root, chat_id, data)


def voice_pending(root, chat_id, name):
    return (load(root, chat_id).get("voices") or {}).get(name)


def voice_done(root, chat_id, name):
    data = load(root, chat_id)
    (data.get("voices") or {}).pop(name, None)
    save(root, chat_id, data)


# Footage: a clip is named to the service by the sha256 of its bytes. Hashing a few hundred
# megabytes on every check would be seconds each time, so a clip's hash is remembered by its
# path, size and time (.cache/video/clips.json), and read again only when one of those changed.
def clip_sha(root, rel, full=None):
    import hashlib

    full = Path(full) if full is not None else Path(root) / rel
    st = full.stat()
    index_path = Path(root) / SIDECAR / "clips.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    hit = index.get(rel)
    if isinstance(hit, dict) and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime_ns and hit.get("sha"):
        return hit["sha"]
    h = hashlib.sha256()
    with open(full, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    index[rel] = {"size": st.st_size, "mtime": st.st_mtime_ns, "sha": h.hexdigest()}
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".part")
    tmp.write_text(json.dumps(index), encoding="utf-8")
    tmp.replace(index_path)
    return index[rel]["sha"]


def footage_started(root, chat_id, sha, token):
    data = load(root, chat_id)
    data.setdefault("footage", {})[sha] = {"token": token, "at": time.time()}
    save(root, chat_id, data)


def footage_pending(root, chat_id, sha):
    return (load(root, chat_id).get("footage") or {}).get(sha)


def footage_done(root, chat_id, sha):
    data = load(root, chat_id)
    (data.get("footage") or {}).pop(sha, None)
    save(root, chat_id, data)


# A stock clip the tool fetched: videos/footage/<name>.mp4.
FOOTAGE_DIR = f"{DIR}/footage"


def rendered_by_me(root, chat_id, name):
    return name in (load(root, chat_id).get("rendered") or {})


def existing(root):
    """The videos in the workspace: [(name, has an mp4)]."""
    d = Path(root) / DIR
    if not d.is_dir():
        return []
    return sorted((p.name[: -len(SUFFIX)], (d / (p.name[: -len(SUFFIX)] + ".mp4")).exists())
                  for p in d.glob(f"*{SUFFIX}"))

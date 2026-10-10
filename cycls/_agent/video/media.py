"""The images a composition names, gathered to send with it.

A composition names an image by its workspace path (designs/logo.png); a path relative to the
composition (../designs/logo.png) is read the same way. Each is sent under a hashed ASCII name,
so no name the model chose reaches a path on the service, with a map from what the document says
to that name. At most 2 MiB each, because that is the most the live preview can inline; a larger
one is refused here with what to do about it. A path that is not a file is left for the service,
which names it in its findings.
"""
import hashlib
import posixpath
import re
from urllib.parse import unquote

from ..paths import _resolve_path

MAX_BYTES = 2 * 1024 * 1024
MAX_IMAGES = 40
TYPES = {"png", "jpg", "jpeg", "webp", "gif", "svg"}
_ATTR = re.compile(r"\s(?:src|href|xlink:href|poster)\s*=\s*([\"'])([^\"']*)\1", re.I)
_URL = re.compile(r"url\(\s*([\"']?)([^\"')]*)\1\s*\)", re.I)
_SKIP_TAGS = ("script", "link", "a")


def _refs(html):
    for m in _ATTR.finditer(html):
        tag = html.rfind("<", 0, m.start())
        name = re.match(r"<([\w-]+)", html[tag:tag + 24] or "")
        if name and name.group(1).lower() in _SKIP_TAGS:
            continue
        yield m.group(2)
    for m in _URL.finditer(html):
        yield m.group(2)


def _local(ref):
    v = ref.strip()
    if not v or v.startswith(("#", "data:", "about:")) or re.match(r"^([a-z][a-z0-9+.-]*:|//)", v, re.I):
        return None
    return unquote(v.removeprefix("./").split("?")[0].split("#")[0])


def collect(html, root, base_dir="videos"):
    """→ (images {path as written: hashed name}, files {hashed name: bytes}, errors [str])."""
    images, files, errors = {}, {}, []
    for ref in dict.fromkeys(_refs(html)):
        path = _local(ref)
        if path is None or path in images:
            continue
        rel = posixpath.normpath(posixpath.join(base_dir, path)) if path.startswith("../") else path
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        if ext not in TYPES:
            continue   # not an image this tool sends; the service reports what it cannot use
        try:
            full = _resolve_path(rel, root)
        except ValueError as e:
            errors.append(f"{path}: {e}")
            continue
        if not full.is_file():
            continue
        data = full.read_bytes()
        if len(data) > MAX_BYTES:
            errors.append(f"{path} is {len(data) / 1048576:.1f} MB; an image in a video is at most 2 MB. Export it "
                          "smaller (a JPEG, or fewer pixels) and name that file instead.")
            continue
        if len(files) >= MAX_IMAGES:
            errors.append(f"A video names at most {MAX_IMAGES} images.")
            break
        hashed = hashlib.sha256(data).hexdigest()[:32] + "." + ext
        images[path] = hashed
        files[hashed] = data
    return images, files, errors


# Sound (protocol 2): the <audio> a composition names by workspace path (a voice-over the tool made,
# or a file of the person's), each with its word timings when it has them (the voice action writes
# <name>.words.json beside <name>.m4a). Library music is named music:<id> and is the service's own.
AUDIO_TYPES = {"m4a", "mp3", "wav"}
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO = 8
_AUDIO_TAG = re.compile(r"<audio\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.I)
_SRC = re.compile(r"\ssrc\s*=\s*([\"'])([^\"']*)\1", re.I)


def collect_audio(html, root, base_dir="videos"):
    """→ (audio {path as written: hashed name}, files {hashed name: bytes}, words {hashed name: words JSON}, errors)."""
    import json

    audio, files, words, errors = {}, {}, {}, []
    for tag in _AUDIO_TAG.finditer(html):
        m = _SRC.search(tag.group(0))
        path = _local(m.group(2)) if m else None
        if path is None or path in audio:
            continue
        rel = posixpath.normpath(posixpath.join(base_dir, path)) if path.startswith("../") else path
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        if ext not in AUDIO_TYPES:
            continue   # the service names what it cannot use
        try:
            full = _resolve_path(rel, root)
        except ValueError as e:
            errors.append(f"{path}: {e}")
            continue
        if not full.is_file():
            continue
        data = full.read_bytes()
        if len(data) > MAX_AUDIO_BYTES:
            errors.append(f"{path} is {len(data) / 1048576:.1f} MB; an audio file in a video is at most 10 MB. Use a "
                          "shorter clip, or AAC or MP3 at 128 kbps.")
            continue
        if len(audio) >= MAX_AUDIO:
            errors.append(f"A video has at most {MAX_AUDIO} audio files.")
            break
        hashed = hashlib.sha256(data).hexdigest()[:32] + "." + ext
        audio[path] = hashed
        files[hashed] = data
        sidecar = full.with_name(full.name.rsplit(".", 1)[0] + ".words.json")
        if sidecar.is_file():
            try:
                w = json.loads(sidecar.read_text(encoding="utf-8"))
                if isinstance(w, dict) and isinstance(w.get("words"), list):
                    words[hashed] = w
            except ValueError:
                errors.append(f"{sidecar.name} is not readable word timings; make the voice-over again.")
    return audio, files, words, errors

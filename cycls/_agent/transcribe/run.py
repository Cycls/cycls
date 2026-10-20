"""The Transcribe tool's executor: a recording in the workspace → what is said in it.

The recording goes to the service once, by the sha256 of its bytes, in pieces (going on from where
an earlier call stopped), and is heard there as a job; the reply waits up to BUDGET["hear"] and
otherwise says to call again, the job's token kept for this chat. The transcript is written beside
the recording:

  <name>.transcript.md   the text, a [mm:ss] mark at each paragraph: what a person reads
  <name>.words.json      every word with its time, and the sha256 of the recording it belongs to

`<name>.words.json` has the shape of a Video footage transcript, so a clip transcribed here is not
heard again when it is cut into a video, and the other way round. A transcript already there for
the same bytes is kept as it is (someone may have corrected it) unless `fresh` asks for a new one.
"""
import asyncio
import hashlib
import json
import time
from pathlib import Path

from ..design.store import write_fig
from ..paths import _resolve_path
from .tool import AUDIO_TYPES, LANGUAGES

BUDGET = {"send": 240, "hear": 300}
MAX_BYTES = 512 * 1024 * 1024
REPLY_CHARS = 20000
SIDECAR = Path(".cache") / "transcribe"
LANGUAGE_NAMES = {"ar": "Arabic", "en": "English", "fr": "French", "ur": "Urdu", "hi": "Hindi", "fa": "Persian",
                  "tr": "Turkish", "es": "Spanish", "de": "German", "zh": "Chinese", "ru": "Russian", "tl": "Tagalog"}
PARAGRAPH_GAP_S = 1.5
PARAGRAPH_WORDS = 80


def _err(text):
    return f"Error: {text}"


def clock(seconds):
    s = int(max(0, seconds))
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def paths_for(full):
    stem = full.name.rsplit(".", 1)[0]
    return full.with_name(stem + ".transcript.md"), full.with_name(stem + ".words.json")


# -- what this chat started, and each recording's hash ---------------------------------------------

def _sidecar(root, name):
    return Path(root) / SIDECAR / name


def _load(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def sha_of(root, rel, full):
    """The recording's sha256, remembered by its path, size and time so a long one is read once."""
    st = full.stat()
    index_path = _sidecar(root, "shas.json")
    index = _load(index_path)
    hit = index.get(rel)
    if isinstance(hit, dict) and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime_ns and hit.get("sha"):
        return hit["sha"]
    h = hashlib.sha256()
    with open(full, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    index[rel] = {"size": st.st_size, "mtime": st.st_mtime_ns, "sha": h.hexdigest()}
    _save(index_path, index)
    return index[rel]["sha"]


def _jobs_path(root, chat_id):
    return _sidecar(root, f"{hashlib.sha256(str(chat_id or '-').encode()).hexdigest()[:16]}.json")


def pending(root, chat_id, sha):
    return _load(_jobs_path(root, chat_id)).get(sha)


def started(root, chat_id, sha, token):
    path = _jobs_path(root, chat_id)
    data = _load(path)
    data[sha] = {"token": token, "at": time.time()}
    _save(path, data)


def finished(root, chat_id, sha):
    path = _jobs_path(root, chat_id)
    data = _load(path)
    if data.pop(sha, None) is not None:
        _save(path, data)


def kept(words_full, sha):
    """The transcript beside a recording, when it is this recording's (its bytes may have changed)."""
    try:
        w = json.loads(words_full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(w, dict) or not isinstance(w.get("words"), list) or w.get("sha") not in (None, sha):
        return None
    return w


# -- the transcript as a person reads it -----------------------------------------------------------

def paragraphs(t):
    """[(start seconds, text)]: sentences joined into paragraphs at long pauses, or every ~80 words."""
    out, cur, start, n, last_end = [], [], None, 0, None
    for s in t.get("sentences") or []:
        if cur and (s["start"] - last_end >= PARAGRAPH_GAP_S or n >= PARAGRAPH_WORDS):
            out.append((start, " ".join(cur)))
            cur, n = [], 0
        if not cur:
            start = s["start"]
        cur.append(s["text"])
        n += len(s["text"].split())
        last_end = s["end"]
    if cur:
        out.append((start, " ".join(cur)))
    if not out and t.get("text"):
        out.append((0.0, t["text"]))
    return out


def _engine(t):
    asr = str((t.get("engine") or {}).get("asr") or "")
    name = asr.split("@")[0].split("/")[-1]
    return {"cohere-transcribe-arabic-07-2026": "Cohere Transcribe Arabic",
            "whisper-large-v3-turbo": "Whisper large-v3-turbo"}.get(name, name or "the service")


def _language(code):
    return LANGUAGE_NAMES.get(code or "", code or "unknown language")


def markdown(rel, t):
    lines = [f"# Transcript: {Path(rel).name}", "",
             f"- Recording: {rel} ({clock(t.get('duration') or 0)})",
             f"- Language: {_language(t.get('language'))}",
             f"- Written down by {_engine(t)}, {time.strftime('%Y-%m-%d', time.gmtime())}. Names, numbers and "
             "dialect words can be misheard.", ""]
    if not t.get("words"):
        lines.append(t.get("note") or "Nobody is heard speaking in it.")
    for at, text in paragraphs(t):
        lines += [f"[{clock(at)}] {text}", ""]
    if t.get("unheard"):
        spans = ", ".join(f"{clock(a)}–{clock(b)}" for a, b in t["unheard"])
        lines += [f"Not written down (loud, but no words could be made out: music, noise or crosstalk): {spans}.", ""]
    return "\n".join(lines).rstrip() + "\n"


def reply(rel, t, md_rel, words_rel, *, reused=False):
    if not t.get("words"):
        return (f"Nobody is heard speaking in {rel} ({clock(t.get('duration') or 0)}): no transcript. "
                + ("(Saved as before.)" if reused else ""))
    head = (f"{'Transcript of' if not reused else 'Transcript of (saved earlier)'} {rel} "
            f"({clock(t.get('duration') or 0)}, {_language(t.get('language'))}, {len(t['words']):,} words; "
            f"written down by {_engine(t)}). Saved as {md_rel} (with times) and {words_rel} (each word timed).")
    body, used = [], 0
    for at, text in paragraphs(t):
        line = f"[{clock(at)}] {text}"
        if used + len(line) > REPLY_CHARS:
            body.append(f"… the rest is in {md_rel}: read it to go on.")
            break
        body.append(line)
        used += len(line) + 1
    tail = ""
    if t.get("unheard"):
        tail = ("\nNot written down (loud, but no words made out — music, noise or crosstalk): "
                + ", ".join(f"{clock(a)}–{clock(b)}" for a, b in t["unheard"]) + ".")
    return head + "\n\n" + "\n".join(body) + tail + ("\nNames, numbers and dialect words can be misheard: check "
                                                     "them where they matter.")


async def _write(root, rel, text):
    await write_fig(root, rel, text.encode("utf-8"), by="agent", reason="transcribe")


async def exec_transcribe(inp, workspace, ctx=None, again=True):
    from cycls._agent import transcribe as service

    root = Path(workspace.root)
    chat = getattr(ctx, "chat_id", None)
    path = inp.get("path")
    if not isinstance(path, str) or not path.strip():
        return _err("transcribe needs path: a recording in the workspace.")
    language = inp.get("language") or "auto"
    if language not in LANGUAGES:
        return _err(f"language: one of {', '.join(LANGUAGES)}.")
    try:
        full = _resolve_path(path.strip(), str(root))
    except ValueError as e:
        return _err(str(e))
    if not full.is_file():
        return _err(f"{path} is not a file in the workspace.")
    rel = full.relative_to(root.resolve()).as_posix()
    if full.suffix.lower().lstrip(".") not in AUDIO_TYPES:
        return _err(f"{rel} is not a recording this tool reads ({', '.join(sorted(AUDIO_TYPES))}).")
    size = full.stat().st_size
    if size > MAX_BYTES:
        return _err(f"{rel} is {size / 1048576:.0f} MB; a recording is at most {MAX_BYTES // 1048576} MB. "
                    "Export it smaller (a compressed m4a or mp3 is plenty for speech).")
    if not service.configured():
        return _err("transcription is not configured for this agent (TRANSCRIBE_URL).")
    md_full, words_full = paths_for(full)
    md_rel, words_rel = (p.relative_to(root.resolve()).as_posix() for p in (md_full, words_full))
    sha = await asyncio.to_thread(sha_of, str(root), rel, full)
    if not inp.get("fresh") and (t := kept(words_full, sha)) is not None:
        if not md_full.is_file():
            await _write(root, md_rel, markdown(rel, t))
        return reply(rel, t, md_rel, words_rel, reused=True)
    try:
        t = await _hear(service, workspace, root, chat, full, rel, sha, language, size, again)
    except service.OverAllowance as e:
        return _err(str(e))
    except service.Refused as e:
        return _err(f"{rel} could not be transcribed: {e}")
    except service.Unavailable as e:
        return _err(f"the transcription service is unavailable: {e}")
    if isinstance(t, str):
        return t
    said = {**t, "sha": sha, "clip": rel}
    await _write(root, words_rel, json.dumps(said, ensure_ascii=False, indent=1))
    await _write(root, md_rel, markdown(rel, t))
    return reply(rel, t, md_rel, words_rel)


async def _hear(service, workspace, root, chat, full, rel, sha, language, size, again):
    """→ the transcript, or a sentence saying to call again."""
    job = pending(root, chat, sha)
    token = job["token"] if job else None
    if token is None:
        st = await service.state(workspace, sha)
        if st.get("state") != "uploaded":
            at = int(st.get("at") or 0) if st.get("state") == "partial" else 0
            at, whole = await service.send(workspace, full, sha, at=at, budget=BUDGET["send"])
            if not whole:
                return (f"Still sending {rel} ({at / 1048576:.0f} of {size / 1048576:.0f} MB so far). Call transcribe "
                        "again with the same path: it goes on from there.")
        key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|transcribe|{sha}|{language}".encode()).hexdigest()
        try:
            started_job = await service.start(workspace, sha, language=language, key=key)
        except service.Refused as e:
            if e.code == "missing" and again:          # the door restarted and lost it: send it again, once
                return await _hear(service, workspace, root, chat, full, rel, sha, language, size, False)
            raise
        token = started_job["token"]
        started(root, chat, sha, token)
    r = await service.wait(workspace, token, BUDGET["hear"])
    if r.get("state") == "pending":
        return (f"Still transcribing {rel} (a long recording takes a minute or two). Call transcribe again with the "
                "same path to collect it.")
    finished(root, chat, sha)
    if r.get("state") == "gone" and again:            # the service restarted under the job: once more
        return await _hear(service, workspace, root, chat, full, rel, sha, language, size, False)
    if r.get("state") != "done":
        raise service.Refused(r.get("error") or r.get("state") or "the job failed", r.get("refused"))
    return r.get("transcript") or {}

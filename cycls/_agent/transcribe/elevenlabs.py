"""ElevenLabs Scribe as a transcription engine: the Transcribe tool and the microphone send audio here when
TRANSCRIBE_ENGINE is `elevenlabs` (or when ELEVENLABS_API_KEY is the only engine an agent has).

Measured on our real-speech clips (cycls-transcribe docs/quirks.md, 2026-10-20): the fewest errors on Gulf
dialect (7.5 % of characters, against 9.0 % for our Cohere service) and on English, 2–3 s a clip, no GPU
of ours to start; $0.22 per audio hour. It names the language itself, labels speakers, takes any format we
do and files up to 3 GB / 10 hours, in one request.

Its reply becomes our transcript's shape (the cycls-transcribe service's and a Video footage
transcript's): `{version, kind, language, duration, text, sentences, words: [{text, start, end, score,
speaker}], engine, speakers}`, so everything downstream reads one shape.
"""
import math
import os
import re

import httpx

from .client import OverAllowance, Refused, Unavailable

URL = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = "scribe_v2"
TIMEOUT = httpx.Timeout(900.0, connect=15.0)     # a long recording is heard in the one request
# ISO 639-3 (what Scribe names) → the two letters the rest of the SDK uses.
LANG = {"ara": "ar", "eng": "en", "fra": "fr", "deu": "de", "spa": "es", "urd": "ur", "hin": "hi", "fas": "fa",
        "per": "fa", "tur": "tr", "rus": "ru", "zho": "zh", "cmn": "zh", "tgl": "tl", "fil": "tl", "ind": "id",
        "msa": "ms", "por": "pt", "ita": "it", "ben": "bn", "mal": "ml", "tam": "ta", "kor": "ko", "jpn": "ja"}
SENTENCE_END = re.compile(r"[.!?؟…]+[\"'»”)]*$")
SENTENCE_GAP_S = 0.9
PHRASE_GAP_S = 0.30
SENTENCE_MAX_WORDS = 20
# Key terms (names, companies, places) Scribe listens for: +20 % on the hour's price; past 100 a request
# is billed at least 20 s, so no more than 100 are sent. Each under 50 characters, at most 5 words, none
# of these characters (Scribe refuses the request); sent as repeated form fields (a JSON list is refused).
MAX_TERMS = 100
_BAD_TERM = frozenset("<>{}[]" + chr(92))      # chr(92) is the backslash


def keyterms(names):
    """The names worth listening for, as Scribe takes them: trimmed, each once, the unusable left out."""
    out, seen = [], set()
    for raw in names or []:
        term = " ".join(str(raw or "").split())
        if not term or len(term) >= 50 or len(term.split()) > 5 or _BAD_TERM & set(term) or term.lower() in seen:
            continue
        seen.add(term.lower())
        out.append(term)
        if len(out) >= MAX_TERMS:
            break
    return out


def configured():
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


def _model():
    return os.environ.get("ELEVENLABS_STT_MODEL") or MODEL


def _detail(resp):
    try:
        d = resp.json().get("detail")
    except Exception:  # noqa: BLE001
        return resp.text[:200]
    if isinstance(d, dict):
        return d.get("message") or d.get("status") or str(d)[:200]
    return str(d or resp.text)[:200]


async def transcribe(*, data=None, path=None, filename="audio", language=None, diarize=True, names=None):
    """One recording (bytes, or a file read as it is sent) → our transcript. Raises Unavailable (no key,
    unreachable, refused, busy), OverAllowance (the account's quota is used) or Refused (not audio)."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise Unavailable("ElevenLabs is not configured (ELEVENLABS_API_KEY)")
    form = {"model_id": _model(), "tag_audio_events": "false", "timestamps_granularity": "word",
            "diarize": "true" if diarize else "false"}
    if language and language != "auto":
        form["language_code"] = language
    if terms := keyterms(names):
        form["keyterms"] = terms          # a list: one form field each
    handle = open(path, "rb") if path is not None else None
    try:
        files = {"file": (filename or "audio", handle if handle is not None else data, "application/octet-stream")}
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            resp = await client.post(URL, headers={"xi-api-key": key}, data=form, files=files)
    except httpx.HTTPError as e:
        raise Unavailable(f"ElevenLabs is unreachable: {type(e).__name__}") from e
    finally:
        if handle is not None:
            handle.close()
    if resp.status_code == 200:
        return to_transcript(resp.json())
    detail = _detail(resp)
    if resp.status_code == 401:
        raise Unavailable(f"ElevenLabs refused the key ({detail})")
    if resp.status_code in (402,) or "quota" in detail.lower():
        raise OverAllowance(f"The ElevenLabs account's transcription quota is used up ({detail})")
    if resp.status_code in (400, 413, 415, 422):
        raise Refused(detail or "the recording was refused", "unreadable")
    raise Unavailable(f"ElevenLabs answered {resp.status_code}: {detail}")


def _speaker(raw):
    """speaker_0 → 1: people count from one."""
    m = re.search(r"(\d+)$", str(raw or ""))
    return int(m.group(1)) + 1 if m else None


def sentences(words):
    """Words grouped as a person reads them: to a full stop, a long pause, a change of speaker, or
    SENTENCE_MAX_WORDS; to each short pause where nothing was punctuated (as the service's listen.py)."""
    gap = SENTENCE_GAP_S if any(SENTENCE_END.search(w["text"]) for w in words) else PHRASE_GAP_S
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if (nxt is None or SENTENCE_END.search(w["text"]) or nxt["start"] - w["end"] > gap
                or nxt.get("speaker") != w.get("speaker") or len(cur) >= SENTENCE_MAX_WORDS):
            s = {"i": len(out), "start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(x["text"] for x in cur)}
            if cur[0].get("speaker") is not None:
                s["speaker"] = cur[0]["speaker"]
            out.append(s)
            cur = []
    return out


def to_transcript(d):
    words = []
    for w in d.get("words") or []:
        text = str(w.get("text") or "").strip()
        if w.get("type", "word") != "word" or not text:
            continue
        lp = w.get("logprob")
        words.append({"text": text, "start": round(float(w.get("start") or 0), 3), "end": round(float(w.get("end") or 0), 3),
                      "score": round(math.exp(lp), 3) if isinstance(lp, (int, float)) else None,
                      **({"speaker": _speaker(w["speaker_id"])} if w.get("speaker_id") is not None else {})})
    code = str(d.get("language_code") or "")
    duration = d.get("audio_duration_secs") or (words[-1]["end"] if words else 0.0)
    out = {"version": 1, "kind": "audio", "language": LANG.get(code, code[:2] or None),
           "duration": round(float(duration), 3), "text": " ".join(w["text"] for w in words),
           "sentences": sentences(words), "words": words, "engine": {"asr": f"elevenlabs/{_model()}"}}
    speakers = sorted({w["speaker"] for w in words if w.get("speaker") is not None})
    if speakers:
        out["speakers"] = len(speakers)
    if not words:
        out["note"] = "Nobody is heard speaking in it."
    return out

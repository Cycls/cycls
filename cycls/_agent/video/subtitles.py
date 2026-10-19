"""Subtitle files beside a rendered video: what is said in it, timed to the MP4, as SRT and WebVTT.

The words are the voice-overs' and the clips' own word timings (what captions are drawn from); where
each sits on the video's clock is the service's sound map: every track's start, end, and where in its
file it begins. So a clip cut into pieces gives only the words of the pieces shown, at the times they
are heard. A cue is a sentence or a part of one: at most two lines of LINE characters and CUE_MAX_S
seconds, broken at a sentence's end, at a pause, or where the next word would not fit.
"""
import re

LINE = 42           # characters a line, the platforms' usual budget
LINES = 2
CUE_MAX_S = 6.0
PAUSE_S = 0.6       # a pause this long starts a new cue
HOLD_S = 0.3        # a cue stays up this long after its last word, unless the next one starts
MIN_S = 0.8         # and at least this long, where there is room
_END = re.compile(r"[.!?؟…]+[\"'»”)]*$")


def placed(sound, words_of):
    """Every word heard in the video, on its clock, sorted. `words_of(src)` → that track's words
    JSON ({"words": [{text, start, end}]}) or None. → [(start, end, text)]."""
    out = []
    for t in (sound or {}).get("tracks") or []:
        said = words_of(t.get("src") or "") if t.get("src") else None
        if not said:
            continue
        start, media = float(t.get("start") or 0), float(t.get("media_start") or 0)
        end = t.get("end")
        end = float(end) if end is not None else float("inf")
        for w in said.get("words") or []:
            text = str(w.get("text") or "").strip()
            if not text or w.get("start") is None or w.get("end") is None:
                continue
            a, b = start + float(w["start"]) - media, start + float(w["end"]) - media
            if start - 1e-6 <= (a + b) / 2 < end:
                out.append((max(a, start), min(b, end), text))
    out.sort()
    return out


def cues(words):
    """[(start, end, text)] words → [(start, end, [lines])] cues."""
    groups, cur = [], []
    for w in words:
        if cur:
            text = " ".join(x[2] for x in cur + [w])
            if (w[0] - cur[-1][1] > PAUSE_S or len(text) > LINE * LINES or w[1] - cur[0][0] > CUE_MAX_S):
                groups.append(cur)
                cur = []
        cur.append(w)
        if _END.search(w[2]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = []
    for i, g in enumerate(groups):
        start, end = g[0][0], g[-1][1] + HOLD_S
        nxt = groups[i + 1][0][0] if i + 1 < len(groups) else None
        end = max(end, start + MIN_S)
        if nxt is not None:
            end = min(end, nxt - 0.04)
        out.append((round(start, 3), round(max(end, start + 0.2), 3), _lines(" ".join(x[2] for x in g))))
    return out


def _lines(text):
    """One line, or two split at the space nearest the middle that keeps both within LINE."""
    if len(text) <= LINE:
        return [text]
    spaces = [i for i, c in enumerate(text) if c == " "]
    fits = [i for i in spaces if i <= LINE and len(text) - i - 1 <= LINE] or spaces
    if not fits:
        return [text]
    cut = min(fits, key=lambda i: abs(i - len(text) / 2))
    return [text[:cut], text[cut + 1:]]


def _stamp(t, sep):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def srt(cs):
    return "".join(f"{i}\n{_stamp(a, ',')} --> {_stamp(b, ',')}\n" + "\n".join(lines) + "\n\n"
                   for i, (a, b, lines) in enumerate(cs, 1))


def vtt(cs):
    return "WEBVTT\n\n" + "".join(f"{_stamp(a, '.')} --> {_stamp(b, '.')}\n" + "\n".join(lines) + "\n\n"
                                  for a, b, lines in cs)

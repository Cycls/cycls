"""A talking clip tidied: its long pauses taken out, every word kept — a jump-cut edit.

From the clip's word timings: the stretches between words longer than PAUSE_S are cut, each side
keeping PAD_S of breath, and so are the silence before the first word and after the last. What is
left are the pieces to put back to back. A filler ("umm") the recogniser left out of the transcript
sits in such a pause and goes with it; a word is never cut, so a piece is never shorter than the words
in it. The reply gives the <video> lines; the person or the agent can lengthen any piece back.

What editors keep (2026-11 survey of open editing skills: vargHQ, social-media-skills, video-use): a beat
before a number (BEAT_S each side), so the figure lands; no cut that saves under MIN_SAVE_S; no piece
under MIN_PIECE_S (a lone word between two cuts flashes by: it is joined to its nearer neighbour); and a
cut is made at a shot change that falls in the breath it keeps, so no sliver of the next shot shows.
"""
import re

PAUSE_S = 0.7
PAD_S = 0.15
BEAT_S = 0.3
MIN_SAVE_S = 0.4
MIN_PIECE_S = 0.4
NUMBER = re.compile(r"[0-9٠-٩۰-۹]")
# Said as fillers but also real words: named in the reply, never cut by themselves.
MAYBE_FILLER = re.compile(r"^(يعني|يعنى|طيب|اه+|ا+م+|إ+م+|um+|uh+|erm?)[.,!?،؟…]*$", re.I)


def plan(said, duration, pause=PAUSE_S, pad=PAD_S, shots=None):
    """`said` is the clip's transcript ({"words": [{text, start, end}]}); `shots` its shots ([[start, end]]).
    → {"pieces": [[media_start, seconds]], "kept", "of", "cuts": [[at, seconds]], "beats": [seconds kept before
    a number]} on the clip's own clock, or None with no words."""
    words = sorted((float(w["start"]), float(w["end"]), str(w.get("text") or "")) for w in (said or {}).get("words") or []
                   if w.get("start") is not None and w.get("end") is not None)
    if not words:
        return None
    duration = float(duration or words[-1][1])
    changes = sorted(float(a) for a, _ in (shots or [])[1:])
    ranges, beats = [], []
    a, last = max(0.0, words[0][0] - pad), words[0][1]
    for s, e, text in words[1:]:
        keep = BEAT_S if NUMBER.search(text) else pad
        if s - last > pause and s - last - 2 * keep >= MIN_SAVE_S:
            end, start = last + keep, max(s - keep, last + keep)
            for c in changes:              # a camera cut inside the breath kept: cut there instead
                if last < c < end:
                    end = c
                if start < c < s:
                    start = c
            ranges.append([a, end])
            a = start
            if keep == BEAT_S:
                beats.append(round(s, 2))
        last = max(last, e)
    ranges.append([a, min(duration, last + pad)])
    while len(ranges) > 1:                 # a piece too short to see is joined to its nearer neighbour
        short = [i for i, (x, y) in enumerate(ranges) if y - x < MIN_PIECE_S]
        if not short:
            break
        i = short[0]
        gap_before = ranges[i][0] - ranges[i - 1][1] if i > 0 else float("inf")
        gap_after = ranges[i + 1][0] - ranges[i][1] if i + 1 < len(ranges) else float("inf")
        j = i - 1 if gap_before <= gap_after else i + 1
        lo, hi = min(i, j), max(i, j)
        ranges[lo:hi + 1] = [[ranges[lo][0], ranges[hi][1]]]
    pieces = [[round(x, 2), round(y - x, 2)] for x, y in ranges if y - x > 0.05]
    cuts, at = [], 0.0
    for x, n in pieces:
        if x - at > 0.05:
            cuts.append([round(at, 2), round(x - at, 2)])
        at = x + n
    if duration - at > 0.05:
        cuts.append([round(at, 2), round(duration - at, 2)])
    return {"pieces": pieces, "kept": round(sum(n for _, n in pieces), 2), "of": round(duration, 2), "cuts": cuts,
            "beats": beats}


def maybe_fillers(said, most=8):
    """Words often said as fillers (يعني, طيب, umm), with their times: for the agent to judge, never cut here."""
    return [(str(w["text"]), round(float(w["start"]), 2)) for w in (said or {}).get("words") or []
            if w.get("start") is not None and MAYBE_FILLER.match(str(w.get("text") or "").strip())][:most]


def lines(rel, p, start=0.0, prefix="t", track=0):
    """The <video> lines for the pieces, back to back from `start` on the video's clock."""
    out, t = [], float(start)
    for i, (m, n) in enumerate(p["pieces"], 1):
        out.append(f'<video id="{prefix}{i}" src="{rel}" data-start="{round(t, 2):g}" data-media-start="{m:g}" '
                   f'data-duration="{n:g}" data-track-index="{track}"></video>')
        t += n
    return out

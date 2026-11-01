"""A talking clip tidied: its long pauses taken out, every word kept — a jump-cut edit.

From the clip's word timings: the stretches between words longer than PAUSE_S are cut, each side
keeping PAD_S of breath, and so are the silence before the first word and after the last. What is
left are the pieces to put back to back. A filler ("umm") the recogniser left out of the transcript
sits in such a pause and goes with it; a word is never cut, so a piece is never shorter than the words
in it. The reply gives the <video> lines; the person or the agent can lengthen any piece back.
"""
PAUSE_S = 0.7
PAD_S = 0.15


def plan(said, duration, pause=PAUSE_S, pad=PAD_S):
    """`said` is the clip's transcript ({"words": [{text, start, end}]}). → {"pieces": [[media_start,
    seconds]], "kept", "of", "cuts": [[at, seconds]]} on the clip's own clock, or None with no words."""
    words = sorted((float(w["start"]), float(w["end"])) for w in (said or {}).get("words") or []
                   if w.get("start") is not None and w.get("end") is not None)
    if not words:
        return None
    duration = float(duration or words[-1][1])
    ranges, a, last = [], max(0.0, words[0][0] - pad), words[0][1]
    for s, e in words[1:]:
        if s - last > pause:
            ranges.append([a, last + pad])
            a = max(s - pad, last + pad)
        last = max(last, e)
    ranges.append([a, min(duration, last + pad)])
    pieces = [[round(x, 2), round(y - x, 2)] for x, y in ranges if y - x > 0.05]
    cuts, at = [], 0.0
    for x, n in pieces:
        if x - at > 0.05:
            cuts.append([round(at, 2), round(x - at, 2)])
        at = x + n
    if duration - at > 0.05:
        cuts.append([round(at, 2), round(duration - at, 2)])
    return {"pieces": pieces, "kept": round(sum(n for _, n in pieces), 2), "of": round(duration, 2), "cuts": cuts}


def lines(rel, p, start=0.0, prefix="t", track=0):
    """The <video> lines for the pieces, back to back from `start` on the video's clock."""
    out, t = [], float(start)
    for i, (m, n) in enumerate(p["pieces"], 1):
        out.append(f'<video id="{prefix}{i}" src="{rel}" data-start="{round(t, 2):g}" data-media-start="{m:g}" '
                   f'data-duration="{n:g}" data-track-index="{track}"></video>')
        t += n
    return out

"""What the model is told after a Video call: one text and at most one sheet of frames.

Bounded on purpose. On Kimi K3 a tool's images arrive unlabelled in a later message, so the times
are burned into the sheet; compaction counts base64 at four characters a token, so there is one
small sheet per reply; and the text stays well under the 20,000 characters past which a result is
filed away and only previewed.
"""
import base64

MAX_FINDINGS = 25
MAX_TEXT = 12_000


def _finding(f):
    where = []
    if f.get("line"):
        where.append(f"line {f['line']}")
    if f.get("time") is not None:
        where.append(f"at {f['time']} s")
    if f.get("selector"):
        where.append(f"on {f['selector']}")
    head = f"{f.get('code', 'issue')}" + (f" ({', '.join(where)})" if where else "")
    text = f"- {head}: {str(f.get('message') or '').strip()}"
    if f.get("fixHint"):
        text += f" Fix: {str(f['fixHint']).strip()}"
    return text[:900]


def findings_text(findings, *, title):
    errors = [f for f in findings if f.get("severity") == "error"]
    rest = [f for f in findings if f.get("severity") != "error"]
    shown = (errors + rest)[:MAX_FINDINGS]
    if not shown:
        return ""
    lines = [f"{title}: {len(errors)} error{'s' if len(errors) != 1 else ''}, "
             f"{len(rest)} warning{'s' if len(rest) != 1 else ''}."]
    lines += [_finding(f) for f in shown]
    if len(findings) > len(shown):
        lines.append(f"(and {len(findings) - len(shown)} more)")
    return "\n".join(lines)


def sheet_blocks(sheet_b64, times, rel):
    """The sheet as the model receives it: a line saying what it is, then the image."""
    if not sheet_b64:
        return []
    when = ", ".join(f"{t:g} s" for t in times or [])
    return [{"type": "text", "text": f"Frames of {rel}" + (f" at {when}" if when else "") +
             " — each cell is labelled with its number and time:"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": sheet_b64}}]


LOOK_AT_IT = ("Look at the sheet before you go on: every word on screen readable and inside the frame, nothing "
              "overlapping, numbers and counters showing their values (not stuck at 0), each scene's end state "
              "reached, Arabic joined and right to left, the frames consistent with each other. If anything is off, "
              "fix it with `edit`, or `look` at the moment more closely.")


def _t(x):
    return f"{x:.2f}".rstrip("0").rstrip(".") if isinstance(x, (int, float)) else "?"


def sound_text(sound):
    """The sound map, as the model reads it in place of hearing: the tracks, when each sentence is
    spoken, and the notes (a scene starting inside a word). '' for a silent video."""
    if not sound or not sound.get("tracks"):
        return ""
    lines = ["Sound map:"]
    for t in sound["tracks"]:
        what = f"music {t['music']}" if t.get("music") else f"{t.get('kind', 'audio')}, {t.get('src')}"
        bits = [f"{_t(t.get('start'))}–{_t(t.get('end'))} s" if t.get("end") is not None else f"from {_t(t.get('start'))} s"]
        if t.get("media_start"):
            bits.append(f"from {_t(t['media_start'])} s into its file")
        if t.get("volume", 1) != 1:
            bits.append(f"level {_t(t['volume'])}")
        if t.get("ducked_by"):
            bits.append(f"dips under {', '.join(t['ducked_by'])}")
        if t.get("fade_out"):
            bits.append(f"fades out over its last {_t(t['fade_out'])} s")
        lines.append(f"- {t.get('id') or '(no id)'} ({what}): {', '.join(bits)}")
    speech = sound.get("speech") or []
    if speech:
        lines.append("Spoken: " + " · ".join(f"{_t(s['start'])}–{_t(s['end'])} \"{s['text'][:80]}\"" for s in speech[:20]))
    for n in sound.get("notes") or []:
        lines.append(f"Note: {n}.")
    return "\n".join(lines)


def voice_text(words, rel, *, warnings=(), reused=False, voice_id="default"):
    """A voice-over's reply: the file, its length, when each sentence and word is spoken, and the
    lines to put in the composition."""
    name = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    head = (f"{'Already made' if reused else 'Made'} {rel} ({_t(words.get('duration'))} s, voice {voice_id}); "
            f"its word timings are in {rel.rsplit('.', 1)[0]}.words.json.")
    lines = [head, "Sentences (seconds into the voice-over):"]
    for s in words.get("sentences") or []:
        lines.append(f"- {_t(s['start'])}–{_t(s['end'])}: {s['text']}")
    w = words.get("words") or []
    if w:
        lines.append("Words: " + " ".join(f"{_t(x['start'])} {x['text']}" for x in w[:160]) + (" …" if len(w) > 160 else ""))
    untimed = [x["text"] for x in w if x.get("untimed")]
    if untimed:
        lines.append(f"Not timed exactly (they share the gap around them): {' '.join(untimed[:12])}.")
    for x in warnings or []:
        lines.append(f"Warning: {x}")
    d = words.get("duration") or 0
    wps = len(w) / d if d else 0
    lines.append(
        f"Put it in the composition once (data-start = when the voice begins in the video; add that to the times above):\n"
        f"  <audio id=\"vo\" src=\"{rel}\" data-start=\"0.5\"></audio>\n"
        f"Captions, at the root: <div class=\"cap\" data-captions=\"vo\" data-cap-style=\"phrase\"></div> "
        f"(or \"word\"). Start scenes between sentences.")
    lines.append(
        f"Length: this take is {_t(d)} s ({wps:.1f} words a second), so the video should end about 1 s after it: "
        f"data-duration {_t(round(d + 1.5, 1))} with the voice at 0.5 s. A longer video needs a longer script — about "
        f"{max(1, round(wps))} more words for each extra second — read again with voice; otherwise the picture runs on "
        f"with nothing to hear, unless music plays under all of it.")
    if name:
        lines.append(f"To change the script, call voice again with name {name}: the old take is kept as a version.")
    return "\n".join(lines)


def audio_facts(a):
    """A render's sound, measured: loudness and peak."""
    if not a:
        return ""
    bits = [f"{a['lufs']:.1f} LUFS" if a.get("lufs") is not None else "", f"peak {a['peak_dbtp']:.1f} dB" if a.get("peak_dbtp") is not None else ""]
    return "Sound: " + ", ".join(b for b in bits if b) + "." if any(bits) else "Sound: present."


def clip(text):
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n…"


def b64(data):
    return base64.b64encode(data).decode() if data else ""

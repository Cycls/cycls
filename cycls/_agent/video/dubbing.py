"""A video said in another language (the `dub` action): what is said in it, timed, and the new
composition that carries the dub.

The sentences come from the translation kept with the words (the `subtitles` action keeps it, a
sentence at a time). Each translated sentence gets a slot: where the original sentence is heard on
the video's clock — placed by the service's sound map, so a clip cut into pieces gives the sentences
of the pieces shown, when they are heard — and until when the next one starts. The service reads
each one in its slot (cycls-video voice.dub) and returns one track on the video's clock.

The new composition is the original with: the voice-overs that were dubbed taken out; the pieces of
footage whose speech was dubbed kept, their sound quietly under the dub (documentary style, chosen
by the user); the dub as one <audio> from the start; the captions boxes pointed at the dub (a box
that showed the translation now shows the original language, from the dub's own translations, so
the layout keeps each language where its styling is); music ducked under the dub; and the page's
language. Everything else — scenes, sizes, reframing — is as it was.
"""
import re

from . import subtitles

UNDER = 0.2            # a dubbed clip's own sound under the dub (about -14 dB)
GAP = 0.08             # a sentence's slot ends this much before the next one starts
RTL = ("ar", "fa", "he", "ur")
ARABIC_FAMILY = "IBM Plex Sans Arabic"

_TAG = re.compile(r"<([a-zA-Z][\w-]*)\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
_ATTR = re.compile(r"([\w:-]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?")


def plan(sound, words_of, to, duration):
    """What is dubbed, from the sound map. `words_of(src)` → that track's words JSON or None.
    → {"slots": [{text, start, end, until}], "missing": sentences heard untranslated, "tracks":
    {track id: kind}, "from": the language heard most, "translations": {lang: {i: text}} for the
    dub's words (the original sentences, and every other translation kept)}."""
    heard = {}
    for t in (sound or {}).get("tracks") or []:
        said = words_of(t.get("src") or "") if t.get("src") else None
        if not said:
            continue
        idx = subtitles.sentence_of(said)
        tr = said.get("translations") if isinstance(said.get("translations"), dict) else {}
        snts = [s for s in (said.get("sentences") or []) if isinstance(s, dict)]
        start, media = float(t.get("start") or 0), float(t.get("media_start") or 0)
        end = float(t["end"]) if t.get("end") is not None else float("inf")
        for j, w in enumerate(said.get("words") or []):
            if idx[j] < 0 or w.get("start") is None or w.get("end") is None:
                continue
            a, b = start + float(w["start"]) - media, start + float(w["end"]) - media
            if not start - 1e-6 <= (a + b) / 2 < end:
                continue
            key = (t["src"], idx[j])
            if key not in heard:
                k = str(idx[j])
                heard[key] = {"stretches": [], "src": t["src"], "k": idx[j], "track": t.get("id") or "",
                              "kind": t.get("kind") or "",
                              "lang": said.get("language") or "",
                              "text": " ".join(str((tr.get(to) or {}).get(k) or "").split()),
                              "orig": str(snts[idx[j]].get("text") or "") if idx[j] < len(snts) else "",
                              "others": {lg: by[k] for lg, by in tr.items()
                                         if lg != to and isinstance(by, dict) and isinstance(by.get(k), str)}}
            heard[key]["stretches"].append((max(a, start), min(b, end)))
            if t.get("id"):
                heard[key].setdefault("ids", set()).add(t["id"])
    rows = []
    for h in heard.values():
        a, b = subtitles._longest(h["stretches"])
        rows.append({**h, "start": round(a, 3), "end": round(b, 3)})
    rows.sort(key=lambda r: (r["start"], r["end"]))
    langs = [r["lang"] for r in rows if r["lang"]]
    src_lang = max(set(langs), key=langs.count) if langs else ""
    tracks = {}
    for r in rows:
        for i in sorted(r.pop("ids", set())):
            tracks[i] = r["kind"]
    out = {"slots": [], "rows": rows, "missing": sum(1 for r in rows if not r["text"]), "heard": len(rows),
           "tracks": tracks, "from": src_lang, "translations": {}}
    if out["missing"]:
        return out
    for i, r in enumerate(rows):
        nxt = rows[i + 1]["start"] if i + 1 < len(rows) else max(float(duration or 0), r["end"])
        until = max(r["end"], round(nxt - (GAP if i + 1 < len(rows) else 0), 3))
        out["slots"].append({"text": r["text"], "start": r["start"], "end": r["end"], "until": until})
        if src_lang and src_lang != to and r["orig"]:
            out["translations"].setdefault(src_lang, {})[str(i)] = r["orig"]
        for lg, text in r["others"].items():
            if lg != src_lang:
                out["translations"].setdefault(lg, {})[str(i)] = text
    return out


def _attrs(raw):
    return [(k, v) for k, v in _ATTR.findall(raw or "")]


def _value(v):
    return v[1:-1] if v[:1] in ("'", '"') and v[-1:] == v[:1] else v


def _get(attrs, key):
    for k, v in attrs:
        if k.lower() == key:
            return _value(v)
    return None


def _set(attrs, key, value):
    """The attribute list with key set (added at the end when absent), or taken out when value is None."""
    out, done = [], False
    for k, v in attrs:
        if k.lower() == key:
            if value is not None and not done:
                out.append((k, f'"{value}"'))
                done = True
            continue
        out.append((k, v))
    if value is not None and not done:
        out.append((key, f'"{value}"'))
    return out


def _tag(name, attrs, self_closing=False):
    body = "".join(f" {k}" if v == "" else f" {k}={v}" for k, v in attrs)
    return f"<{name}{body}{' /' if self_closing else ''}>"


def compose(html, p, *, to, src, dub_id="dub"):
    """The dubbed composition: the original `html` with `p` (plan) applied and the dub `src` (its
    workspace path) as one <audio id=dub_id> from the start. → (html, notes for the reply)."""
    ids = set(p["tracks"])
    voices = {i for i, k in p["tracks"].items() if k == "voice"}
    clips = {i for i, k in p["tracks"].items() if k == "footage"}
    taken = set(re.findall(r"\bid\s*=\s*[\"']([^\"']+)[\"']", html))
    while dub_id in taken:
        dub_id = dub_id + "-2" if not dub_id[-1].isdigit() else dub_id[:-1] + str(int(dub_id[-1]) + 1)
    rtl = to.split("-")[0] in RTL
    src_lang = p.get("from") or ""
    notes = []

    # The voice-overs that were dubbed come out, whole elements.
    def drop_voice(m):
        attrs = _attrs(m.group(2))
        return "" if _get(attrs, "id") in voices else m.group(0)
    html = re.sub(r"[ \t]*<(audio)\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>\s*</audio>[ \t]*\n?", drop_voice, html, flags=re.I)

    boxes = []          # (start, end, attrs) of every captions box

    def sub(m):
        name, raw = m.group(1), m.group(2)
        low = name.lower()
        self_closing = raw.rstrip().endswith("/")
        attrs = _attrs(raw.rstrip().rstrip("/") if self_closing else raw)
        el = _get(attrs, "id")
        if low == "html":
            return _tag(name, _set(attrs, "lang", to))
        if low == "video" and el in clips:
            try:
                level = float(_get(attrs, "data-volume") or 1)
            except ValueError:
                level = 1.0
            attrs = _set(_set(attrs, "data-volume", f"{round(level * UNDER, 3):g}"), "data-dubbed", dub_id)
            return _tag(name, attrs, self_closing)
        duck = _get(attrs, "data-duck")
        if duck is not None:
            kept = [x for x in duck.split() if x not in ids]
            if len(kept) != len(duck.split()):
                attrs = _set(attrs, "data-duck", " ".join(dict.fromkeys([*kept, dub_id])))
        caps = _get(attrs, "data-captions")
        if caps is not None and any(x in ids for x in caps.split()):
            boxes.append(len(boxes))
            return "\x00CAP%d\x00%s\x00%s\x00" % (len(boxes) - 1, name, raw)
        return _tag(name, attrs, self_closing) if duck is not None else m.group(0)

    html = _TAG.sub(sub, html)

    # Captions boxes: those that showed the words follow the dub; one that showed the translation into
    # `to` now shows the original language and the box for the words takes its styling's place.
    found = [(int(m.group(1)), m.group(2), m.group(3)) for m in re.finditer(r"\x00CAP(\d+)\x00([^\x00]*)\x00([^\x00]*)\x00", html)]
    main = [f for f in found if not _get(_attrs(f[2]), "data-cap-lang")]
    into = [f for f in found if _get(_attrs(f[2]), "data-cap-lang") == to]
    main_style = (_get(_attrs(main[0][2]), "data-cap-style") if main else None) or "phrase"
    new = {}
    for n, name, raw in found:
        attrs = _set(_attrs(raw), "data-captions", dub_id)
        lang = _get(attrs, "data-cap-lang")
        if lang == to:               # it was styled for `to`: it shows the dub's own words now
            attrs = _set(_set(attrs, "data-cap-lang", None), "data-cap-style", main_style)
        elif not lang:
            if into and src_lang:    # the translation's box shows the dub: this one shows the original
                attrs = _set(_set(attrs, "data-cap-lang", src_lang), "data-cap-style", "phrase")
                if src_lang.split("-")[0] in RTL:
                    attrs = _set(attrs, "dir", "rtl")
                elif (_get(attrs, "dir") or "").lower() == "rtl":
                    attrs = _set(attrs, "dir", None)
            else:
                attrs = _set(attrs, "dir", "rtl" if rtl else None)
                if rtl:
                    notes.append("arabic_font")
        new[n] = _tag(name, attrs)
    if found:
        notes.append("captions")
    if into and main and src_lang:
        notes.append("swapped")
    html = re.sub(r"\x00CAP(\d+)\x00[^\x00]*\x00[^\x00]*\x00", lambda m: new[int(m.group(1))], html)

    if "arabic_font" in notes:
        # The words' box was styled for the original language: give it an Arabic family first.
        rule = (f'<style data-cycls-dub>[data-captions~="{dub_id}"]:not([data-cap-lang]) '
                f'{{ font-family: "{ARABIC_FAMILY}", sans-serif; line-height: 1.5; }}</style>')
        html = re.sub(r"</head>", rule + "\n</head>", html, count=1, flags=re.I) if re.search(r"</head>", html, re.I) else html

    # The dub, from the video's start, first inside the root.
    line = f'<audio id="{dub_id}" src="{src}" data-start="0"></audio>'
    m = re.search(r"<div\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*\bid\s*=\s*[\"']root[\"'](?:[^>\"']|\"[^\"]*\"|'[^']*')*>", html)
    if m:
        html = html[:m.end()] + "\n  " + line + html[m.end():]
    else:
        notes.append("no_root")
    return html, notes, dub_id


_DUBBED = re.compile(r"<video\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.I)


def dubbed_ids(html):
    """The pieces of footage whose speech a dub says (data-dubbed): heard quietly, not as speech."""
    out = set()
    for m in _DUBBED.finditer(html or ""):
        attrs = _attrs(m.group(0)[6:-1])
        if _get(attrs, "data-dubbed") is not None and _get(attrs, "id"):
            out.add(_get(attrs, "id"))
    return out


def for_words(sound, ids):
    """The sound map without the dubbed pieces' tracks: what subtitles, translations and dubs read."""
    if not sound or not ids:
        return sound
    return {**sound, "tracks": [t for t in sound.get("tracks") or [] if t.get("id") not in ids],
            "speech": [x for x in sound.get("speech") or [] if x.get("track") not in ids]}


def for_reading(sound, ids):
    """The sound map as the model reads it: a dubbed piece is still a track (heard quietly), its words are not speech."""
    if not sound or not ids:
        return sound
    return {**sound, "speech": [x for x in sound.get("speech") or [] if x.get("track") not in ids]}


def listing(rows, to):
    """`dub` before the translation is kept: the sentences to translate, each with how long it is said."""
    out = [f"{i}. ({r['end'] - r['start']:.1f} s) {r['orig']}" + (f"\n   now in {to}: {r['text']}" if r["text"] else "")
           for i, r in enumerate(rows, 1)]
    return "\n".join(out)


def fits_text(sentences, slots):
    """What the reply says of how the dub fits: sped up, run into a pause, too long."""
    fast = [s for s in sentences if (s.get("speed") or 1) > 1.0]
    pause = [s for s in sentences if s.get("fit") == "pause"]
    long = [s for s in sentences if s.get("fit") == "long"]
    parts = []
    if not fast and not pause and not long:
        parts.append("Every sentence fits its place at its natural pace.")
    if fast:
        parts.append("Sped up to fit: " + "; ".join(f"{s['i'] + 1} ({s['speed']:.2f}x)" for s in fast) + ".")
    if pause:
        parts.append("Running into the pause after it: " + ", ".join(str(s["i"] + 1) for s in pause) + ".")
    late = [s for s in sentences if (s.get("late_s") or 0) > 0]
    if late:
        parts.append("Starting later than the original, after the sentence before it: "
                     + "; ".join(f"{s['i'] + 1} (+{s['late_s']:.1f} s)" for s in late) + ".")
    if long:
        rows = []
        for s in long:
            slot = slots[s["i"]] if s["i"] < len(slots) else {}
            room = float(slot.get("until", slot.get("end", 0))) - float(slot.get("start", 0))
            need = (s["end"] - s["start"])
            share = max(10, int(round(100 * (1 - room / need)))) if need > 0 else 30
            rows.append(f"{s['i'] + 1} (\"{s.get('text', '')[:80]}\": {need:.1f} s even sped up, {room:.1f} s before the "
                        f"next sentence; about {share}% shorter)")
        parts.append("TOO LONG for its place, so what follows it is pushed later: " + "; ".join(rows) + ". Shorten those "
                     "sentences (keep the meaning, drop words) and call dub again with all the lines.")
    return " ".join(parts)

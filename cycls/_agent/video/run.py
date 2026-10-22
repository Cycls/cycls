"""The Video tool's executor. `_exec_video(inp, workspace, ctx)` reads a call and makes it:
guide, write, edit, template, look, render, restore, for sound voice and music, and for the
person's clips and stock video footage. Registered in cycls/_agent/tools as the `video` tool.

The SDK owns the schema, the argument checks, every write to the workspace and the report; the
service owns the contract, the checks, the frames, the preview and the render.
"""
import asyncio
import difflib
import hashlib
import json
import re
from pathlib import Path

from .. import trash, versions
from ..design.deck import lock
from ..design.store import Stale, version_of, write_fig
from ..paths import _resolve_path
from . import contract as contract_mod
from . import dubbing, files, media, report
from .tool import ACTIONS, VIDEO_LOADED

# How long a call waits for the service before it answers anyway. The harness has no per-tool
# limit, so the client keeps its own: a save with its frames, a look, a render.
BUDGET = {"check": 300, "look": 180, "render": 900, "voice": 300, "dub": 420, "send": 240, "footage": 420}
MAX_HTML = 400_000

_LOADED_NOTE = ("\n\nVideo's full instructions were not loaded when you made this call; they are now in this tool's "
                "description. Read them before your next change.")


def _err(text):
    return f"Error: {text}"


def _read_changes(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return None
    out = []
    for c in raw:
        if not isinstance(c, dict) or not isinstance(c.get("old"), str) or not isinstance(c.get("new"), str) or not c["old"]:
            return None
        out.append(c)
    return out


def apply_changes(html, changes):
    """Every change or none. → (new html, None) or (None, why)."""
    out = html
    for i, c in enumerate(changes, 1):
        n = out.count(c["old"])
        if n == 0:
            first = c["old"].strip().splitlines()[0] if c["old"].strip() else c["old"]
            lines = out.splitlines()
            near = difflib.get_close_matches(first.strip(), [ln.strip() for ln in lines], n=1, cutoff=0.5)
            hint = ""
            if near:
                at = next(k for k, ln in enumerate(lines, 1) if ln.strip() == near[0])
                hint = f" The closest line is {at}: {near[0][:200]!r}"
            return None, f"change {i}: the old text is not in the composition (nothing was changed).{hint}"
        if n > 1 and not c.get("all"):
            return None, (f"change {i}: the old text occurs {n} times (nothing was changed). Give more of the "
                          "surrounding text so it occurs once, or set all to replace every one.")
        out = out.replace(c["old"], c["new"]) if c.get("all") else out.replace(c["old"], c["new"], 1)
    return out, None


def _sha(html, images_files, words=None, footage=None):
    """What makes two jobs the same: the composition, the files it sends (hashed names carry their
    bytes), the word timings its captions and ducking are made from, and its clips (each by the
    hash of its bytes, with what is said in it)."""
    h = hashlib.sha256(html.encode("utf-8"))
    for name in sorted(images_files):
        h.update(name.encode())
    if words:
        h.update(json.dumps(words, sort_keys=True).encode("utf-8"))
    if footage:
        h.update(json.dumps(footage, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def _media(html, root):
    """The images, audio and footage a composition names, ready to send.
    → (images, audio, files, words, footage, problems)."""
    images, image_files, problems = media.collect(html, root)
    audio, audio_files, words, more = media.collect_audio(html, root)
    footage, clips = media.collect_footage(html, root)
    return images, audio, {**image_files, **audio_files}, words, footage, problems + more + clips


async def _save(root, chat, name, html, reason):
    """Write the composition under this chat's name for it. → (name, rel, note)."""
    asked = name
    name = files.claim(root, chat, name)
    rel = files.composition(name)
    async with lock(root / rel):
        await write_fig(root, rel, html.encode("utf-8"), by="agent", reason=reason)
    files.remember(root, chat, name)
    note = (f" It is named '{name}' because a video called '{asked}' was already here and is not this chat's."
            if name != asked else "")
    return name, rel, note


def _root_text(root_info):
    if not root_info:
        return ""
    d, w, h = root_info.get("duration"), root_info.get("width"), root_info.get("height")
    return f"{d:g} s, {w}x{h}" if d and w and h else ""


async def _check(workspace, root, rel, html, *, kind="review", params=None, budget=None, again=True, label=None,
                 quiet=False):
    """Lint at the door, then (when clean) the browser check and a sheet, or the frames asked for.
    `label` names the sheet (a size of the video); `quiet` leaves out what every size shares (the
    sound map, the reminder to look). → (text, sheet blocks, lint passed)."""
    from cycls._agent import video

    images, audio, sent, words, footage, problems = await asyncio.to_thread(_media, html, root)
    if problems:
        return "The images, sound and clips could not all be sent:\n" + "\n".join(f"- {p}" for p in problems), [], False
    # Keyed, so a retry after a dropped connection is the same job, not a second one.
    key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|{kind}|{_sha(html, sent, words, footage)}|"
                         f"{json.dumps(params or {}, sort_keys=True)}".encode()).hexdigest()
    try:
        job = await video.submit(workspace, kind, html, images, sent, params=params, key=key, audio=audio, words=words,
                                 footage=footage)
    except video.Refused as e:
        text = report.findings_text(e.findings, title="Lint")
        sound = report.sound_text(dubbing.for_reading(e.sound, dubbing.dubbed_ids(html)))
        return ((text or str(e)) + ("\n" + sound if sound else "")
                + "\nFix them with `edit`; the file is saved as it is."), [], False
    except video.OverAllowance as e:
        # Said only after lint passed: the file is good to preview; frames and the MP4 wait.
        return (f"Lint clean. {e} The file is saved and its preview works; the browser check, frames and "
                "the MP4 wait until then — tell the person so."), [], True
    shape = _root_text(job.get("root"))
    head = f"Lint clean ({shape})." if shape else "Lint clean."
    sound = "" if quiet else report.sound_text(dubbing.for_reading(job.get("sound"), dubbing.dubbed_ids(html)))
    if sound:
        head += "\n" + sound
    r = await video.wait(workspace, job["token"], budget or BUDGET["check"])
    state = r.get("state")
    if state == "gone" and again:   # the service restarted under the job: ask once more
        return await _check(workspace, root, rel, html, kind=kind, params=params, budget=budget, again=False,
                            label=label, quiet=quiet)
    if state == "pending":
        what = "the frames" if kind == "look" else "the browser check and the frames"
        return (f"{head} The renderer is still starting or busy, so {what} are not ready yet (about "
                f"{r.get('eta_s', 60)} s more). Call `look` for them."), [], True
    if state != "done":
        return f"{head} The check could not run: {r.get('error') or state}.", [], True
    parts = [head]
    if kind == "review":
        if r.get("browser_skipped") or r.get("not_ready"):
            parts.append("The browser check did not run to the end (the page was not ready in time): treat it as "
                         "not checked, and look at the frames.")
        found = report.findings_text(r.get("findings") or [], title="Browser check")
        parts.append(found or "Browser check: no issues.")
    elif r.get("not_ready"):
        parts.append("The page was not ready in time for these frames: they may show it before it settled.")
    times = job.get("times") or []
    blocks = report.sheet_blocks(r.get("sheet"), times, label or rel)
    if blocks and not quiet:
        parts.append(report.LOOK_AT_IT)
    return "\n".join(parts), blocks, True


async def _checks(workspace, root, rel, html, *, size=None, **kw):
    """`_check` at the main size and, at once, at each other size the root lists (data-sizes,
    sizes.py); `size` checks that one alone. → (text, sheet blocks, lint passed at the main size)."""
    from . import sizes

    shapes, problems = sizes.declared(html)
    main = sizes.shape_of(sizes.main_size(html) or ())
    label = lambda s: f"{rel} at {s} {sizes.SHAPES[s][0]}x{sizes.SHAPES[s][1]}"  # noqa: E731
    if size:
        asked = sizes.ALIASES.get(str(size).lower(), str(size).lower())
        if asked not in sizes.SHAPES:
            return f"size: one of {', '.join(sizes.SHAPES)}.", [], False
        if asked != main and asked not in shapes:
            return (f"{rel} is not made in {asked}: add it to the root's data-sizes first "
                    f"(data-sizes=\"{' '.join(shapes + [asked])}\")."), [], False
        if asked != main:
            return await _check(workspace, root, rel, sizes.variant(html, asked), label=label(asked), **kw)
        shapes = []
    runs = [_check(workspace, root, rel, html, **kw)]
    runs += [_check(workspace, root, rel, sizes.variant(html, s), quiet=True, label=label(s), **kw) for s in shapes]
    results = await asyncio.gather(*runs)
    text, blocks, clean = results[0]
    if problems:
        text = "\n".join(problems) + "\n" + text
    if not clean or not shapes:
        return text, blocks, clean
    name = Path(rel).name[: -len(files.SUFFIX)]
    for s, (t, b, _) in zip(shapes, results[1:]):
        w, h = sizes.SHAPES[s]
        text += (f"\n\nAt {s} {w}x{h} (rendered as {sizes.mp4(name, s)}; rules for this size alone: "
                 f"#root[data-shape=\"{s}\"] ...):\n{t}")
        blocks = blocks + b
    return text, blocks, clean


def _hand_edited(root, rel):
    """When the file was last saved by the person (the editor), a failed match is said to be why."""
    history = versions.listing(root, rel)
    if history and history[0].get("by") == "user":
        return (" The person changed this video in the editor since you last read it, and a save from the editor "
                "writes the file afresh (attribute order, characters): read the file again before you edit it.")
    return ""


def _shown(rel, name, clean, version=None):
    """What the canvas is told after a save: refresh the composition wherever it is open (an open
    editor takes the new `version` in), and open it once it lints clean (with errors it would only
    show why it cannot play)."""
    ui = [{"type": "ui", "action": "refresh_canvas", "path": rel, **({"version": version} if version else {})}]
    if clean:
        ui.insert(0, {"type": "ui", "action": "open_canvas", "path": rel, "name": f"{name}.video.html"})
    return ui


def _catalogue():
    """The contract's fonts and templates as last fetched, or the built-in copy's fonts."""
    from .contract import cached
    from .fallback import FALLBACK

    c = cached() or {}
    return c.get("fonts") or FALLBACK.get("fonts") or [], c.get("templates")


def _with_brand(root, template, given):
    """The workspace brand kit for the colours, fonts and logo the model left out (brand.py): the
    template's own defaults stay where the kit says nothing, or names a font the catalogue lacks."""
    from . import brand

    fonts, templates = _catalogue()
    k = brand.kit(root, fonts)
    if not k:
        return given
    takes = next((t["vars"] for t in templates or [] if t.get("id") == template), None)
    arabic = str(given.get("lang") or "").startswith("ar") or str(given.get("dir") or "").lower() == "rtl"
    return {**brand.template_vars(k, takes, fonts, arabic), **given}


def _brand_hint(root, html):
    """A save that leaves the workspace's brand kit out is told so (brand.hint)."""
    from . import brand

    line = brand.hint(root, html, _catalogue()[0])
    return f"\n{line}" if line else ""


def _result(text, blocks, note="", ui=None):
    text = report.clip(text + note)
    if not blocks and ui is None:
        return text
    out = {"_model": [*blocks, {"type": "text", "text": text}] if blocks else text}
    if ui is not None:
        out["_ui"] = ui
    return out


async def _guide(workspace, root, loaded):
    from cycls._agent import video

    asyncio.ensure_future(video.warm(workspace))
    c = await contract_mod.get(30)
    fonts = ", ".join(f["family"] + (" (Arabic)" if "arabic" in f.get("scripts", []) else "") for f in c["fonts"])
    formats = ", ".join(f"{k} {v[0]}x{v[1]}" for k, v in c["formats"].items())
    have = files.existing(root)
    lines = [f"Video's instructions are loaded (contract {c['version']}); the renderer is starting up.",
             f"Formats: {formats}.", f"Fonts: {fonts}."]
    if c.get("fallback"):
        lines.append(f"(The service's contract could not be used — {c['fallback']} — so the built-in copy is.)")
    lines.append("Videos here: " + (", ".join(f"{n}{' (rendered)' if mp4 else ''}" for n, mp4 in have) if have else "none yet."))
    from . import brand
    kit = brand.note(brand.kit(root, c["fonts"]), c["fonts"])
    if kit:
        lines.append(kit)
    if loaded is None:   # no harness swaps this tool's description: the instructions come in the reply
        lines.append("\n" + c["text"])
    else:
        lines.append("They are in this tool's description now: read them, then `write` the video.")
    return "\n".join(lines)


async def _render(workspace, root, chat, name, quality):
    """The MP4 at the main size and at each other size the root lists, one job each, all at once.
    A job cut off (Stop, a dropped connection) is collected by the next call, never paid twice."""
    from cycls._agent import video
    from . import sizes

    rel = files.composition(name)
    try:
        html = (root / rel).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _err(f"there is no {rel} to render; `write` it first.")
    shapes, problems = sizes.declared(html)
    if problems:
        return _err(" ".join(problems))
    images, audio, sent, words, footage, problems = await asyncio.to_thread(_media, html, root)
    if problems:
        return _err("the images, sound and clips could not all be sent:\n" + "\n".join(f"- {p}" for p in problems))
    jobs = []      # {shape, slot, sha, token, sound, collected}
    for shape, h in [(None, html)] + [(s, sizes.variant(html, s)) for s in shapes]:
        sha = _sha(h, sent, words, footage)
        slot = name if shape is None else f"{name}@{shape}"
        pending = files.render_pending(root, chat, slot)
        if pending and pending.get("sha") == sha and pending.get("quality") == quality:
            jobs.append({"shape": shape, "slot": slot, "sha": sha, "token": pending["token"],
                         "sound": pending.get("sound"), "collected": True})
            continue
        key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|{slot}|{sha}|{quality}".encode()).hexdigest()
        try:
            job = await video.submit(workspace, "render", h, images, sent, params={"quality": quality}, key=key,
                                     audio=audio, words=words, footage=footage)
        except video.Refused as e:
            where = f" at {shape}" if shape else ""
            return (report.findings_text(e.findings, title=f"Not rendered{where} — lint")
                    + "\nFix them with `edit`, then render.")
        files.render_started(root, chat, slot, job["token"], sha, quality, sound=job.get("sound"))
        jobs.append({"shape": shape, "slot": slot, "sha": sha, "token": job["token"], "sound": job.get("sound"),
                     "collected": False})
    results = await asyncio.gather(*(video.wait(workspace, j["token"], BUDGET["render"]) for j in jobs))
    for j, r in zip(jobs, results):
        if r.get("state") in ("gone", "expired") and j["collected"]:
            files.render_done(root, chat, j["slot"], None)   # that job is lost; start it again
            return await _render(workspace, root, chat, name, quality)
    waiting = [(j, r) for j, r in zip(jobs, results) if r.get("state") == "pending"]
    if waiting:
        left = ", ".join(j["shape"] or "the main size" for j, _ in waiting)
        eta = max(r.get("eta_s", 60) for _, r in waiting)
        return (f"Still rendering {rel} ({left}; about {eta} s more). Call `render` again with the same name "
                "to collect it — it keeps running; do not change the composition meanwhile.")
    for j, r in zip(jobs, results):
        if r.get("state") != "done":
            files.render_done(root, chat, j["slot"], None)
            where = f" at {j['shape']}" if j["shape"] else ""
            return _err(f"the render{where} failed: {r.get('error') or r.get('state')}. "
                        + (f"Details: {r['log'][-600:]}" if r.get("log") else ""))
    target = name
    if (root / files.mp4(target)).exists():
        if files.rendered_by_me(root, chat, target):
            # the old MP4s go to the trash, every size, and the subtitle files with them (translations
            # too: timed to the old cut); this render writes its own
            olds = [files.mp4(target)] + [sizes.mp4(target, s) for s in sizes.SHAPES] + \
                [files.subtitles(target, e) for e in ("srt", "vtt")] + files.translations(root, target)
            for old in olds:
                if (root / old).exists():
                    await asyncio.to_thread(trash.trash_path, root, old, "agent", "re-render")
        else:
            n = 2
            while (root / files.mp4(f"{name}-{n}")).exists():
                n += 1
            target = f"{name}-{n}"
    made = []      # (workspace path, the service's facts, bytes)
    for j, r in zip(jobs, results):
        out = files.mp4(target) if j["shape"] is None else sizes.mp4(target, j["shape"])
        size = await video.fetch(workspace, j["token"], root / out, root / ".tmp" / (chat or "video"))
        files.render_done(root, chat, j["slot"], j["sha"])
        made.append((out, r.get("video") or {}, size))
    if target != name:
        files.render_done(root, chat, target, jobs[0]["sha"])
    rel_mp4, v, size = made[0]
    stream = v.get("stream") or {}
    facts = [f"{v['duration']:.1f} s" if v.get("duration") else "",
             f"{stream.get('width')}x{stream.get('height')}" if stream.get("width") else "",
             f"{size / 1048576:.1f} MB", f"rendered in {v['render_s']:.0f} s" if v.get("render_s") else ""]
    text = (f"Rendered {rel_mp4} ({', '.join(f for f in facts if f)}); it is open on the canvas for the user. "
            f"Now make one `canvas` call with path {rel_mp4}, so the video stays in the chat as a file card "
            "(after a reload, and in a shared chat).")
    if made[1:]:
        others = []
        for out, vv, n in made[1:]:
            st = vv.get("stream") or {}
            others.append(f"{out} ({st.get('width')}x{st.get('height')}, {n / 1048576:.1f} MB)" if st.get("width")
                          else f"{out} ({n / 1048576:.1f} MB)")
        text += (f" The other sizes: {', '.join(others)}: the same video, a file each; `canvas` each one the person "
                 "should see, and tell them which is for where (vertical for Reels, TikTok and Shorts; square and "
                 "portrait for feeds; wide for YouTube).")
    if target != name:
        text += f" It is named {target}.mp4 because {name}.mp4 was already here and is not this chat's render."
    if v.get("audio"):
        text += " " + report.audio_facts(v["audio"])
    if v.get("faults"):
        text += f" (The renderer noted: {', '.join(v['faults'])}.)"
    sound = dubbing.for_words(jobs[0]["sound"], dubbing.dubbed_ids(html))
    if sound:
        await asyncio.to_thread(files.save_sound, root, target, sound)
    written, done, short = await asyncio.to_thread(_subtitles, root, target, sound, audio, words, footage)
    if written:
        also = "".join(f", and in {lang}: {files.subtitles(target, 'srt', lang)} and .vtt ({n} cues)"
                       for lang, n in done.items())
        text += (f" Subtitle files beside it, timed to the MP4: {files.subtitles(target, 'srt')} and "
                 f"{files.subtitles(target, 'vtt')} ({written} lines){also}. They are files for platforms that take a "
                 "captions track (YouTube, TikTok, LinkedIn), not text on the video; mention them to the user."
                 + (" They fit every size: the timing is the same." if made[1:] else ""))
        for lang, missing in short.items():
            text += (f" The {lang} subtitle files were not written: {missing} sentences heard have no {lang} "
                     f"translation; `subtitles` {{name: {target}, to: {lang}}} lists them.")
        if not done and not short:
            text += (f" `subtitles` with name {target} translates what is said into another language (Arabic or "
                     "English, say), as subtitle files and as captions on the video.")
    return {"_model": text, "_ui": {"type": "ui", "action": "open_canvas", "path": rel_mp4, "name": f"{target}.mp4"}}


_LANG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_RTL = ("ar", "fa", "he", "ur")
_MEDIA_TAG = re.compile(r"<(audio|video)\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.I)
_TAG_ATTR = re.compile(r"([\w:-]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?")


def _spoken(html, root):
    """The voice-overs and pieces of footage in a composition that have words, in the order they are
    heard: [{"id", "words": the words file's workspace path, "said": its JSON, "heard": [sentence
    index]}]. A sentence is heard when a word of it is inside the piece (the service's rule)."""
    from . import subtitles

    out = []
    for n, m in enumerate(_MEDIA_TAG.finditer(html)):
        attrs = {k.lower(): (v or "").strip("\"'") for k, v in _TAG_ATTR.findall(m.group(2))}
        if "data-dubbed" in attrs:      # its speech is said by a dub: heard quietly, not as words
            continue
        path = media._local(attrs.get("src") or "")
        if not path:
            continue
        try:
            _, full = media.resolve_clip(path, root)
        except ValueError:
            continue
        side = media.words_path(full)
        try:
            said = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(said, dict) or not isinstance(said.get("words"), list):
            continue

        def num(key):
            try:
                return float(attrs[key])
            except (KeyError, ValueError):
                return None
        ms = num("data-playback-start")
        ms = (num("data-media-start") or 0) if ms is None else ms
        dur, video_tag = num("data-duration"), m.group(1).lower() == "video"
        idx, heard = subtitles.sentence_of(said), []
        for j, w in enumerate(said["words"]):
            a, b = w.get("start"), w.get("end")
            if a is None or b is None or idx[j] < 0 or idx[j] in heard:
                continue
            mid = (a + b) / 2
            if (mid >= ms and (dur is None or mid < ms + dur)) if video_tag else (b > ms and (dur is None or a < ms + dur)):
                heard.append(idx[j])
        out.append({"id": attrs.get("id") or "", "words": side.relative_to(Path(root).resolve()).as_posix(),
                    "said": said, "heard": heard, "at": num("data-start") or 0, "n": n})
    return sorted(out, key=lambda x: (x["at"], x["n"]))


def _words_beside(root, src):
    """A track's words JSON as it is now, by the src the sound map names, or None."""
    try:
        _, full = media.resolve_clip(media._local(src) or "", root)
        said = json.loads(media.words_path(full).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return said if isinstance(said, dict) and isinstance(said.get("words"), list) else None


def _write_translated(root, name, lang, sound, words_of):
    """videos/<name>.<lang>.srt and .vtt from the translation kept with the words, timed by the MP4's
    sound map. → (cues written, sentences heard untranslated); nothing is written unless every
    sentence heard has its translation."""
    from . import subtitles

    spans, missing = subtitles.placed_translation(sound, words_of, lang)
    if missing or not spans:
        return 0, missing
    cs = subtitles.translated_cues(spans)
    for ext, body in (("srt", subtitles.srt(cs)), ("vtt", subtitles.vtt(cs))):
        path = Path(root) / files.subtitles(name, ext, lang)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return len(cs), 0


async def _translate(root, name, to, lines):
    """`subtitles {name}`: what is said in the video, sentence by sentence, to translate. `subtitles
    {name, to, lines}`: that translation, kept with the words (each words file's "translations"), so
    captions on the video can show it and subtitle files in that language are made from it — now
    beside the MP4 when it is here, and at every render after. The translation is the model's own."""
    rel = files.composition(name)
    try:
        html = (root / rel).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _err(f"there is no {rel}; `write` it first.")
    spoken = await asyncio.to_thread(_spoken, html, root)
    order, seen = [], set()
    for s in spoken:
        for k in s["heard"]:
            if (s["words"], k) not in seen:
                seen.add((s["words"], k))
                order.append((s["words"], k, s["said"]))
    if not order:
        return _err(f"nothing is said in {rel}: subtitles translate the words of a voice-over or a clip "
                    "(made with `voice` or `footage`).")
    to = str(to or "").strip()
    if to and not _LANG.match(to):
        return _err("to: the language code of the translation, e.g. ar or en.")

    def sentence(said, k):
        snts = said.get("sentences") or []
        return str(snts[k].get("text") or "") if k < len(snts) and isinstance(snts[k], dict) else ""

    def kept(said, k):
        tr = said.get("translations") if isinstance(said.get("translations"), dict) else {}
        return ((tr.get(to) or {}) if to else {}).get(str(k))

    if not lines:
        rows = []
        for i, (_, k, said) in enumerate(order, 1):
            rows.append(f"{i}. {sentence(said, k)}")
            if kept(said, k):
                rows.append(f"   now in {to}: {kept(said, k)}")
        return (f"What is said in {rel}, sentence by sentence ({len(order)}):\n" + "\n".join(rows) + "\n"
                "Translate each sentence as a caption says it (natural and short, the same meaning; numbers and "
                f"names kept), then call subtitles with name {name}, to (the language code: ar, en, fr…) and lines: "
                f"exactly {len(order)} strings, in this order, without the numbers.")
    if not to:
        return _err("to: the language code of the translation, e.g. ar or en.")
    if not isinstance(lines, list) or len(lines) != len(order) or \
            not all(isinstance(x, str) and x.strip() and len(x) <= 600 for x in lines):
        return _err(f"lines: exactly {len(order)} strings (each 600 characters at most), one for each sentence "
                    f"`subtitles` {{name: {name}}} lists, in its order.")
    by_file = {}
    for (wrel, k, _), t in zip(order, lines):
        by_file.setdefault(wrel, {})[str(k)] = " ".join(t.split())
    for wrel, given in by_file.items():
        async with lock(root / wrel):
            said = json.loads((root / wrel).read_text(encoding="utf-8"))     # read again, under the lock
            tr = said.get("translations") if isinstance(said.get("translations"), dict) else {}
            tr[to] = {**(tr.get(to) or {}), **given}
            said["translations"] = tr
            await write_fig(root, wrel, json.dumps(said, ensure_ascii=False, indent=1).encode("utf-8"),
                            by="agent", reason="video-translation")

    text = f"Kept the {to} translation of {len(order)} sentences with the words ({', '.join(by_file)})."
    sound = files.load_sound(root, name) if (root / files.mp4(name)).is_file() else None
    if sound:
        written, missing = await asyncio.to_thread(_write_translated, root, name, to, sound,
                                                   lambda src: _words_beside(root, src))
        if written:
            text += (f" Subtitle files: wrote {files.subtitles(name, 'srt', to)} and {files.subtitles(name, 'vtt', to)} "
                     f"({written} cues), timed to {files.mp4(name)}: files for platforms that take a captions track, "
                     "not text on the video; tell the user where they are.")
        else:
            text += (f" Subtitle files: not written yet, because {missing} sentences heard in {files.mp4(name)} have no "
                     f"translation (it was rendered from another cut); they are written with the next render.")
    else:
        text += (f" Subtitle files in {to} ({files.subtitles(name, 'srt', to)} and .vtt) are written with the next "
                 "render of this video.")
    found = re.search(r"data-captions\s*=\s*\"([^\"]*)\"", html)
    ids = (found.group(1) if found else "") or " ".join(dict.fromkeys(s["id"] for s in spoken if s["heard"] and s["id"])) \
        or "<the ids of the voice or the pieces>"
    if re.search(rf"data-cap-lang\s*=\s*\"{re.escape(to)}\"", html):
        text += f" The captions box in {to} on the video shows this translation from the next check and render."
    else:
        rtl = ' dir="rtl"' if to.split("-")[0] in _RTL else ""
        text += (f" Captions on the video: a captions box in that language shows the translation a sentence at a "
                 f"time, timed to what is said, and follows the cut: <div class=\"cap\" data-captions=\"{ids}\" "
                 f"data-cap-lang=\"{to}\" data-cap-style=\"phrase\"{rtl}></div> at the root, placed and styled by you "
                 "(beside the original captions, or instead of them). "
                 + ("This video shows captions, so the person most likely wants the translation on it too: add the box "
                    "with `edit`, look, then render." if found else
                    "Add it with `edit` when the person wants the translation on the video, then render."))
    return text


def _subtitles(root, name, sound, audio, words, footage):
    """What is said in the render, as SRT and WebVTT beside its MP4 (subtitles.py), and in each language
    a translation is kept for. → (cues written, {lang: cues}, {lang: sentences untranslated})."""
    from . import subtitles

    def words_of(src):
        if src in (audio or {}):
            return (words or {}).get(audio[src])
        clip = (footage or {}).get(src)
        return clip.get("words") if isinstance(clip, dict) else None

    cs = subtitles.cues(subtitles.placed(sound, words_of))
    if not cs:
        return 0, {}, {}
    for ext, body in (("srt", subtitles.srt(cs)), ("vtt", subtitles.vtt(cs))):
        path = Path(root) / files.subtitles(name, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    langs = set()      # the languages a translation is kept in, of what is heard (a dubbed clip is not)
    for t in (sound or {}).get("tracks") or []:
        said = words_of(t.get("src") or "") if t.get("src") else None
        if isinstance(said, dict) and isinstance(said.get("translations"), dict):
            langs.update(k for k in said["translations"]
                         if isinstance(k, str) and _LANG.match(k) and k != said.get("language"))
    done, short = {}, {}
    for lang in sorted(langs):
        n, missing = _write_translated(root, name, lang, sound, words_of)
        if n:
            done[lang] = n
        elif missing:
            short[lang] = missing
    return len(cs), done, short


async def _voice(workspace, root, chat, name, text, voice_id, language):
    """A voice-over: read on the organisation's GPU, saved as videos/voice/<name>.m4a and its word
    timings. The same name, script and voice again is the same take, not a second job."""
    from cycls._agent import video

    if not isinstance(text, str) or not text.strip():
        return _err("voice needs text: the script to read aloud.")
    voice_id = voice_id or "default"
    rel, words_rel = files.voice_audio(name), files.voice_words(name)
    try:
        old = json.loads((root / words_rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if old and old.get("text") == text and old.get("voice") == voice_id and (root / rel).is_file():
        return report.voice_text(old, rel, reused=True, voice_id=voice_id)
    key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|voice|{name}|{voice_id}|{language}|{text}".encode()).hexdigest()
    pending = files.voice_pending(root, chat, name)
    if pending and pending.get("key") == key:
        token = pending["token"]
    else:
        try:
            job = await video.voice(workspace, text, language=language, voice_id=voice_id, key=key)
        except video.Refused as e:
            return _err(f"the voice-over was not made: {e}")
        token = job["token"]
        files.voice_started(root, chat, name, token, key)
    r = await video.wait(workspace, token, BUDGET["voice"])
    if r.get("state") == "pending":
        return (f"Still reading {name} aloud (about {r.get('eta_s', 30)} s more; the first voice-over of a session also "
                "loads the voice). Call voice again with the same name and text to collect it.")
    if r.get("state") != "done":
        files.voice_done(root, chat, name)
        return _err(f"the voice-over failed: {r.get('error') or r.get('state')}.")
    tmp = root / ".tmp" / (chat or "video")
    dest = tmp / f"{name}.m4a.part"
    await video.fetch(workspace, token, dest, tmp, what="audio")
    data = dest.read_bytes()
    dest.unlink(missing_ok=True)
    words = r.get("words") or {}
    async with lock(root / rel):
        await write_fig(root, rel, data, by="agent", reason="video-voice")
        await write_fig(root, words_rel, json.dumps(words, ensure_ascii=False, indent=1).encode("utf-8"),
                        by="agent", reason="video-voice")
    files.voice_done(root, chat, name)
    return report.voice_text(words, rel, warnings=r.get("warnings") or [], voice_id=voice_id)


async def _keep_lines(root, rows, to, lines):
    """A translation sent with `dub`, kept with the words like `subtitles` keeps one: rows are the
    sentences heard (dub.plan), the lines one for each, in their order. → why not, or None."""
    if not isinstance(lines, list) or len(lines) != len(rows) or \
            not all(isinstance(x, str) and x.strip() and len(x) <= 600 for x in lines):
        return (f"lines: exactly {len(rows)} strings (each 600 characters at most), one for each sentence the first "
                "`dub` call lists, in its order.")
    by_file = {}
    for r, t in zip(rows, lines):
        try:
            _, full = media.resolve_clip(media._local(r["src"]) or "", root)
        except ValueError:
            return f"the words of {r['src']} could not be found."
        rel = media.words_path(full).relative_to(Path(root).resolve()).as_posix()
        by_file.setdefault(rel, {})[str(r["k"])] = " ".join(t.split())
    for wrel, given in by_file.items():
        async with lock(root / wrel):
            said = json.loads((root / wrel).read_text(encoding="utf-8"))
            tr = said.get("translations") if isinstance(said.get("translations"), dict) else {}
            tr[to] = {**(tr.get(to) or {}), **given}
            said["translations"] = tr
            await write_fig(root, wrel, json.dumps(said, ensure_ascii=False, indent=1).encode("utf-8"),
                            by="agent", reason="video-translation")
    return None


async def _dub(workspace, root, chat, name, to, voice_id, lines, note=""):
    """`dub`: the video said in another language, as a new video beside it (dub.py)."""
    from cycls._agent import video


    rel = files.composition(name)
    try:
        html = (root / rel).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _err(f"there is no {rel}; `write` it first.")
    to = str(to or "").strip().lower()
    if to not in ("ar", "en"):
        return _err("to: ar or en, the language to dub the video into.")
    voice_id = voice_id or "default"
    if voice_id not in ("default", "saudi"):
        return _err("voice: default or saudi.")
    if voice_id == "saudi" and to != "ar":
        return _err("the saudi voice speaks Arabic: dub into ar, or use the default voice.")

    async def planned():
        images, audio, sent, words, footage, problems = await asyncio.to_thread(_media, html, root)
        if problems:
            return None, "The images, sound and clips could not all be sent:\n" + "\n".join(f"- {p}" for p in problems)
        c = await video.compile(workspace, html, images, sent, audio=audio, words=words, footage=footage)
        if not c.get("ok"):
            return None, (report.findings_text(c.get("findings") or [], title="Lint")
                          + f"\nFix {rel} with `edit` before dubbing it.")

        def words_of(src):
            return _words_beside(root, src)
        sound = dubbing.for_words(c.get("sound"), dubbing.dubbed_ids(html))
        return dubbing.plan(sound, words_of, to, (c.get("root") or {}).get("duration")), None

    p, why = await planned()
    if why:
        return why
    if not p["heard"]:
        return _err(f"nothing is said in {rel}: a dub says again the words of a voice-over or a clip (made with "
                    "`voice` or `footage`).")
    if p["from"] == to:
        return _err(f"{rel} is already in {to}.")
    if lines:
        why = await _keep_lines(root, p["rows"], to, lines)
        if why:
            return _err(why)
        p, why = await planned()
        if why:
            return why
    if p["missing"]:
        return (f"What is said in {rel}, sentence by sentence ({len(p['rows'])}), with how long each is said:\n"
                f"{dubbing.listing(p['rows'], to)}\n"
                f"Translate each into {to} FOR SPEAKING: natural, the same meaning, and about as long to say as the "
                "original (a little shorter is better than longer; numbers and names kept). Then call dub with name "
                f"{name}, to {to} and lines: exactly {len(p['rows'])} strings, in this order, without the numbers. "
                "The same translation is used for subtitles and captions in that language.")

    slots = p["slots"]
    dub_name = files.claim(root, chat, f"{name}-{to}")
    audio_rel, words_rel = files.voice_audio(dub_name), files.voice_words(dub_name)
    key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|dub|{name}|{to}|{voice_id}|"
                         f"{json.dumps(slots, sort_keys=True)}".encode()).hexdigest()
    try:
        old = json.loads((root / words_rel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if old and (old.get("dub") or {}).get("key") == key and (root / audio_rel).is_file():
        words, reused = old, True
    else:
        reused = False
        slot_name = f"dub:{dub_name}"
        pending = files.voice_pending(root, chat, slot_name)
        if pending and pending.get("key") == key:
            token = pending["token"]
        else:
            try:
                job = await video.dub(workspace, slots, language=to, voice_id=voice_id, key=key)
            except video.Refused as e:
                return _err(f"the dub was not made: {e}")
            token = job["token"]
            files.voice_started(root, chat, slot_name, token, key)
        r = await video.wait(workspace, token, BUDGET["dub"])
        if r.get("state") == "pending":
            return (f"Still reading the {to} dub of {name} ({len(slots)} sentences; about {r.get('eta_s', 60)} s more, and "
                    "the first voice of a session also loads the voice). Call dub again with the same name and to to "
                    "collect it.")
        if r.get("state") != "done":
            files.voice_done(root, chat, slot_name)
            return _err(f"the dub failed: {r.get('error') or r.get('state')}.")
        tmp = root / ".tmp" / (chat or "video")
        dest = tmp / f"{dub_name}.m4a.part"
        await video.fetch(workspace, token, dest, tmp, what="audio")
        data = dest.read_bytes()
        dest.unlink(missing_ok=True)
        words = r.get("words") or {}
        if p["translations"]:
            words["translations"] = p["translations"]
        words["dub"] = {"from": rel, "to": to, "key": key}
        async with lock(root / audio_rel):
            await write_fig(root, audio_rel, data, by="agent", reason="video-dub")
            await write_fig(root, words_rel, json.dumps(words, ensure_ascii=False, indent=1).encode("utf-8"),
                            by="agent", reason="video-dub")
        files.voice_done(root, chat, slot_name)

    new_html, notes, dub_id = dubbing.compose(html, p, to=to, src=audio_rel)
    dub_name, drel, named = await _save(root, chat, dub_name, new_html, "video-dub")
    text, blocks, clean = await _checks(workspace, root, drel, new_html)
    head = [f"{'Already made' if reused else 'Made'} the {to} dub of {rel}: {drel}, with its voice {audio_rel} "
            f"({len(slots)} sentences, voice {voice_id}).{named}",
            dubbing.fits_text(words.get("sentences") or [], slots)]
    changed = []
    voices = [i for i, k in p["tracks"].items() if k == "voice"]
    clips = [i for i, k in p["tracks"].items() if k == "footage"]
    if voices:
        changed.append(f"the voice-over ({', '.join(voices)}) is replaced by the dub (<audio id=\"{dub_id}\">)")
    if clips:
        changed.append(f"the clips' own sound ({', '.join(clips)}) plays quietly under it")
    if "captions" in notes:
        changed.append("the captions show the dub's words" + (f", and the box that showed the {to} translation now shows "
                                                               "the original language" if "swapped" in notes else ""))
    if "no_root" in notes:
        changed.append(f"the dub's <audio id=\"{dub_id}\" src=\"{audio_rel}\" data-start=\"0\"> could NOT be placed "
                       "(no root found): add it at the root with `edit`")
    head.append("In the new video: " + "; ".join(changed) + "; everything else is as it was.")
    if "arabic_font" in notes:
        head.append(f"The captions box was styled for the original language: it is now right to left with an Arabic "
                    f"family ({dubbing.ARABIC_FAMILY}, in <style data-cycls-dub>); restyle it if the brand calls for another.")
    head.append(f"On-screen text (titles, labels) is still in the original language: translate it with `edit` on "
                f"{dub_name} when the person wants the whole video in {to} (Arabic text needs dir=\"rtl\" and an Arabic "
                "family), look at the sheet, then render it. Tell the person the voice is a built-in synthetic voice, "
                "not the speaker's own.")
    return _result("\n".join(h for h in head if h) + "\n\n" + text, blocks, note, _shown(drel, dub_name, clean))


async def _footage(workspace, root, chat, inp, again=True):
    """A clip made ready for video: sent to the service once (by the hash of its bytes, in pieces,
    going on from where an earlier call stopped), read there on the organisation's GPU, and
    described back — its shots, a sheet of its frames, what is said in it and when. The transcript
    is written beside the clip, where a misheard word can be corrected. A clip already made ready
    costs nothing to ask after again."""
    from cycls._agent import video

    from . import stock

    credit, others = None, []
    path = inp.get("path")
    if inp.get("stock"):
        try:
            pick = inp.get("pick")
            path, credit, others = await stock.find(root, inp["stock"], orientation=inp.get("orientation"),
                                                    pick=int(pick) if isinstance(pick, (int, float)) and pick >= 0 else 0)
        except ValueError as e:
            return _err(str(e))
        except Exception as e:  # noqa: BLE001 - the network, or the stock service
            return _err(f"the stock clip could not be fetched ({type(e).__name__}); try again, or put a clip in the workspace.")
    if not isinstance(path, str) or not path.strip():
        return _err("footage needs path (a clip in the workspace) or stock (a few words to find one).")
    language = inp.get("language")
    if language not in (None, "", "ar", "en"):
        return _err("language: ar or en, or leave it out to have it found.")
    try:
        full = _resolve_path(path.strip(), root)
    except ValueError as e:
        return _err(str(e))
    if not full.is_file():
        return _err(f"{path} is not a file in the workspace.")
    rel = full.relative_to(Path(root).resolve()).as_posix()
    if full.suffix.lower().lstrip(".") not in media.FOOTAGE_TYPES:
        return _err(f"{rel} is not a video file this tool reads ({', '.join(sorted(media.FOOTAGE_TYPES))}).")
    size = full.stat().st_size
    if size > media.MAX_FOOTAGE_BYTES:
        return _err(f"{rel} is {size / 1048576:.0f} MB; a clip is at most {media.MAX_FOOTAGE_BYTES // 1048576} MB. "
                    "Cut it shorter, or export it smaller.")
    sha = await asyncio.to_thread(files.clip_sha, root, rel, full)
    state = await video.clip_state(workspace, sha, sheet=True)
    info, sheet, reused = None, None, False
    if state.get("state") == "ready":
        info, sheet, reused = state["info"], state.get("sheet"), True
    else:
        if state.get("state") != "uploaded":
            try:
                at, whole = await video.send_clip(workspace, full, sha, budget=BUDGET["send"],
                                                  at=int(state.get("at") or 0) if state.get("state") == "partial" else 0)
            except video.Refused as e:
                return _err(f"the clip was not taken: {e}")
            if not whole:
                return (f"Still sending {rel} ({at / 1048576:.0f} of {size / 1048576:.0f} MB so far). Call footage again "
                        "with the same path: it goes on from there.")
        pending = files.footage_pending(root, chat, sha)
        token = pending["token"] if pending else None
        if token is None:
            key = hashlib.sha256(f"{getattr(workspace, 'subject', '')}|ingest|{sha}|{language or ''}".encode()).hexdigest()
            try:
                job = await video.ingest(workspace, sha, language=language or None, key=key)
            except video.Refused as e:
                return _err(f"the clip was not made ready: {e}")
            if job.get("ready"):
                info, sheet = job["info"], job.get("sheet")
            else:
                token = job["token"]
                files.footage_started(root, chat, sha, token)
        if info is None:
            r = await video.wait(workspace, token, BUDGET["footage"])
            if r.get("state") == "pending":
                return (f"Still reading {rel} (about {r.get('eta_s', 60)} s more: it is being made ready and listened "
                        "to). Call footage again with the same path to collect it.")
            files.footage_done(root, chat, sha)
            if r.get("state") in ("gone", "expired") and again:     # the service restarted under the job: once more
                return await _footage(workspace, root, chat, inp, again=False)
            if r.get("state") != "done":
                return _err(f"the clip could not be made ready: {r.get('error') or r.get('state')}")
            info, sheet = r["info"], r.get("sheet")
    # What is said, beside the clip. A transcript already there for these same bytes is the one to
    # keep: someone may have corrected it.
    words_rel = None
    if info.get("transcript"):
        words_rel = media.words_path(full).relative_to(Path(root).resolve()).as_posix()
        kept = media.clip_words(full, sha)
        if kept is None:
            said = {**info["transcript"], "sha": sha, "clip": rel}
            async with lock(root / words_rel):
                await write_fig(root, words_rel, json.dumps(said, ensure_ascii=False, indent=1).encode("utf-8"),
                                by="agent", reason="video-footage")
        else:
            info = {**info, "transcript": kept}
    text = report.footage_text(rel, info, words_rel=words_rel, reused=reused, credit=credit)
    if inp.get("tidy"):
        text += "\n" + report.tidy_text(rel, info)
    if others:
        text += ("\nOther clips that search found (footage {\"stock\": \"…\", \"pick\": n} fetches one): "
                 + "; ".join(others) + ".")
    return _result(text, report.sheet_blocks(sheet, info.get("sheet_times"), rel))


def _music(query):
    """The library's tracks that fit the words asked for (all of them when none), from the signed
    contract's data."""
    from .fallback import FALLBACK

    c = contract_mod.cached() or {}
    tracks = (c.get("data") or FALLBACK.get("data") or {}).get("music") or []
    if not tracks:
        return "The music library is not available yet: make this video without music, or with an audio file of the person's."
    words = [w for w in str(query or "").lower().replace(",", " ").split() if w]
    def score(t):
        hay = " ".join([t.get("title", ""), t.get("desc", ""), " ".join(t.get("mood") or []), t.get("energy", "")]).lower()
        return sum(1 for w in words if w in hay)
    picked = sorted(tracks, key=lambda t: -score(t)) if words else tracks
    if words and not any(score(t) for t in picked):
        picked = tracks
    lines = [f"Library tracks{' for ' + repr(query) if words else ''} (use one as src=\"music:<id>\"; music only "
             "when the person wants it):"]
    for t in picked[:8]:
        bits = [", ".join(t.get("mood") or []), f"{t['bpm']} bpm" if t.get("bpm") else "", f"{int(t.get('duration', 0)) // 60}:"
                f"{int(t.get('duration', 0)) % 60:02d}" if t.get("duration") else ""]
        line = f"- {t['id']}: {t.get('title', '')} — {'; '.join(b for b in bits if b)}"
        if t.get("desc"):
            line += f". {t['desc']}"
        if t.get("starts") and len(t["starts"]) > 1:
            line += f" Good places to start (data-media-start): {', '.join(str(s) for s in t['starts'])} s."
        lines.append(line)
    return "\n".join(lines)


async def _exec_video(inp, workspace, ctx=None):
    from cycls._agent import video

    inp = inp if isinstance(inp, dict) else {}
    root = Path(workspace.root)
    chat = getattr(ctx, "chat_id", None)
    action = str(inp.get("action") or "").lower().strip()
    loaded = VIDEO_LOADED.get()
    note = _LOADED_NOTE if loaded is False and action != "guide" else ""
    if action not in ACTIONS:
        return _err(f"action must be one of {', '.join(ACTIONS)}.")
    if not video.offered(workspace):
        return _err("Video is not switched on for this organisation.")
    try:
        if action == "guide":
            return await _guide(workspace, root, loaded)
        if action == "music":
            return _music(inp.get("query") or inp.get("mood")) + note
        if action == "footage":
            out = await _footage(workspace, root, chat, inp)
            if isinstance(out, str):
                return out + note
            if note:
                out["_model"][-1]["text"] += note
            return out
        name = files.clean_name(inp.get("name"))
        if not name:
            return _err("name is required: the video's name, e.g. launch-reel.")
        rel = files.composition(name)

        if action == "write":
            html = inp.get("html")
            if not html and inp.get("path"):
                try:
                    src = _resolve_path(str(inp["path"]), root)
                except ValueError as e:
                    return _err(str(e))
                if not src.is_file() or src.suffix.lower() not in (".html", ".htm"):
                    return _err(f"{inp['path']} is not an HTML file in the workspace.")
                html = src.read_text(encoding="utf-8")
            if not isinstance(html, str) or not html.strip():
                return _err("write needs html (the whole composition) or path (a composition to adopt).")
            if len(html.encode("utf-8")) > MAX_HTML:
                return _err(f"the composition is over {MAX_HTML:,} bytes; keep it to the scenes and their animations.")
            name, rel, named = await _save(root, chat, name, html, "video-write")
            text, blocks, clean = await _checks(workspace, root, rel, html)
            kb = len(html.encode("utf-8")) / 1024
            return _result(f"Saved {rel} ({kb:.1f} KB).{named}\n{text}{_brand_hint(root, html)}", blocks, note,
                           _shown(rel, name, clean))

        if action == "voice":
            language = inp.get("language")
            if language not in (None, "", "ar", "en"):
                return _err("language: ar or en, or leave it out to have it found.")
            voice_id = inp.get("voice") or "default"
            out = await _voice(workspace, root, chat, name, inp.get("text"), voice_id, language or None)
            return out + note if isinstance(out, str) else out

        if action == "template":
            which = inp.get("template")
            given = inp.get("vars")
            if isinstance(given, str):
                try:
                    given = json.loads(given)
                except ValueError:
                    return _err("vars must be an object of the template's variables.")
            if not isinstance(which, str) or not which.strip():
                return _err("template needs template (its name) and vars.")
            try:
                html = await video.fill_template(workspace, which.strip(), _with_brand(root, which, given or {}))
            except video.Refused as e:
                return _err(f"the template was not filled: {e}. Nothing was saved.")
            name, rel, named = await _save(root, chat, name, html, "video-template")
            text, blocks, clean = await _checks(workspace, root, rel, html)
            return _result(f"Made {rel} from the {which} template ({len(html) / 1024:.1f} KB).{named} It is an ordinary "
                           f"composition now: change it with `edit`.\n{text}{_brand_hint(root, html)}", blocks, note,
                           _shown(rel, name, clean))

        if action == "edit":
            changes = _read_changes(inp.get("changes"))
            if changes is None:
                return _err("edit needs changes: [{old, new, all?}], each old a non-empty exact text.")
            if not files.mine(root, chat, name) and not (root / rel).exists():
                return _err(f"there is no {rel}; `write` it first.")
            # Against the version read: the person may save from the editor at the same moment (its
            # save takes the store's lock, not this one), so a stale write reads and applies once more.
            async with lock(root / rel):
                for attempt in (1, 2):
                    try:
                        data = (root / rel).read_bytes()
                    except FileNotFoundError:
                        return _err(f"there is no {rel}; `write` it first.")
                    new, why = apply_changes(data.decode("utf-8"), changes)
                    if why:
                        return _err(why + _hand_edited(root, rel))
                    try:
                        version = await write_fig(root, rel, new.encode("utf-8"), base=version_of(data), by="agent",
                                                  reason="video-edit")
                        break
                    except Stale:
                        if attempt == 2:
                            return _err(f"{rel} changed while it was being edited (the person is editing it); read "
                                        "it again, then edit.")
            files.remember(root, chat, name)
            text, blocks, clean = await _checks(workspace, root, rel, new)
            return _result(f"Edited {rel} ({len(changes)} change{'s' if len(changes) != 1 else ''}).\n{text}"
                           f"{_brand_hint(root, new)}", blocks, note, _shown(rel, name, clean, version))

        if action == "look":
            try:
                html = (root / rel).read_text(encoding="utf-8")
            except FileNotFoundError:
                return _err(f"there is no {rel}; `write` it first.")
            at = inp.get("at")
            if isinstance(at, (int, float)):
                at = [at]
            if at:
                if not isinstance(at, list) or not all(isinstance(t, (int, float)) for t in at):
                    return _err("at: a list of times in seconds.")
                params = {"at": [float(t) for t in at][:9], "zoom": str(inp.get("zoom") or "")[:200]}
                text, blocks, _ = await _checks(workspace, root, rel, html, kind="look", params=params,
                                                budget=BUDGET["look"], size=inp.get("size"))
            else:
                text, blocks, _ = await _checks(workspace, root, rel, html, budget=BUDGET["look"], size=inp.get("size"))
            return _result(text, blocks, note)

        if action == "render":
            quality = inp.get("quality") or "final"
            if quality not in ("final", "draft"):
                return _err("quality: final or draft.")
            out = await _render(workspace, root, chat, name, quality)
            if note and isinstance(out, str):
                out += note
            return out

        if action == "subtitles":
            out = await _translate(root, name, inp.get("to"), inp.get("lines"))
            return out + note

        if action == "dub":
            out = await _dub(workspace, root, chat, name, inp.get("to"), inp.get("voice"), inp.get("lines"), note)
            return out + note if isinstance(out, str) else out

        if action == "restore":
            history = versions.listing(root, rel)
            if not history:
                return _err(f"{rel} has no earlier version.")
            data = versions.read(root, rel, history[0]["id"])
            if data is None:
                return _err("that version could not be read.")
            async with lock(root / rel):
                version = await write_fig(root, rel, data, by="agent", reason="restore")
            return _result(f"Restored {rel} to the version from {history[0]['at'][:19]} UTC. Call `look` to see it.", [],
                           note, [{"type": "ui", "action": "refresh_canvas", "path": rel, "version": version}])
    except video.Unavailable as e:
        return _err(f"Video is unavailable: {e}")
    except RuntimeError as e:
        return _err(f"the video service said: {e}")
    return _err("nothing was done.")


def _video_step(inp):
    inp = inp or {}
    return {"tool_name": "Video", "step": f"{inp.get('action', '')} {inp.get('name', '')}".strip()}

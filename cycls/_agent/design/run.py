"""The Design tool's executor: render, script, edit, inspect and extract here; slide, section,
file and comment actions in actions.py; a PowerPoint deck brought in (`import`) in powerpoint.py."""
import asyncio, base64, json, pathlib, re
from ..paths import _resolve_path
from . import skill
from .tool import (DESIGN_ASK, DESIGN_CHECKED, DESIGN_FOLDER, DESIGN_HEARD, DESIGN_LOADED, DESIGN_RESEARCHED,
    DESIGN_SKILLED, _GUIDE_LOADED, _GUIDE_NOT_RUN, _RESEARCH_FIRST, _SEARCH_NOW)
from . import brief
from .brand import _load_brand
from .images import _DESIGN_QA_MAX, _DESIGN_QA_SLIDES, _DESIGN_QA_TYPES
from .prepare import _mend_json_tail, _prepare_ops, _prepare_spec, _quiet_deck
from . import recent
from .extract import _pdf_parts
from .powerpoint import _import_deck
from .report import _edit_names, _fixed_line, _layout_check, _outline_text
from .files import (_DECK_EXTS, _DESIGN_EXTS, _designs_there, _find_design, _free_design, _opened, _render_again,
    _replacing, _save_pages, _stem_of)
from .actions import (_DOCUMENT_ACTIONS, _FILE_ACTIONS, _SLIDE_ACTIONS, _comments_note, _exec_comments,
    _exec_design_file, _exec_document, _exec_slides, _render_document, _sections_text, _to_the_room)


def _skill_for(spec):
    """The skill for what a spec makes: a document, a deck (of layouts, or of slide-sized frames), else a graphic."""
    if not isinstance(spec, dict):
        return "graphic-design"
    if isinstance(spec.get("document"), dict):
        return "document-design"
    frames = spec.get("frames")
    wide = lambda f: isinstance(f, dict) and f.get("size") in ("slide", "wide", [1920, 1080], [1280, 720])
    if isinstance(spec.get("deck"), dict) or (isinstance(frames, list) and frames and all(map(wide, frames))):
        return "deck-design"
    return "graphic-design"


def _nudged(out, line):
    """`out` — a string, or {_model: str | blocks} — with `line` added to what the model reads."""
    if isinstance(out, str):
        return f"{out}\n\n{line}"
    m = out.get("_model")
    if isinstance(m, str):
        return {**out, "_model": f"{m}\n\n{line}"}
    if isinstance(m, list):
        at = max((i for i, b in enumerate(m) if b.get("type") == "text"), default=None)
        blocks = [*m, {"type": "text", "text": line}] if at is None else \
            [*m[:at], {**m[at], "text": f"{m[at]['text']}\n\n{line}"}, *m[at + 1:]]
        return {**out, "_model": blocks}
    return out


def _spec_of(inp):
    """A call's spec as a dict (a large nested argument may arrive as its JSON text)."""
    spec = inp.get("spec")
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except ValueError:
            return {}
    return spec if isinstance(spec, dict) else {}


# A request to MAKE a design (not one that only mentions a report or a PDF): its guide comes with the message.
_MAKE = re.compile(r"\b(design|make|create|build|draft|produce|prepare|put together|turn\b.{0,40}\binto)\b", re.I)
_MAKE_AR = ("صمم", "صمّم", "سو لي", "سوّ لي", "سوي لي", "اعمل", "أنشئ", "انشئ", "جهز", "جهّز", "حضر", "اصنع", "ابغى", "أبغى", "أبي")
_DECK = re.compile(r"\b(slides?|deck|presentation|pitch|powerpoint|pptx|keynote)\b", re.I)
_DECK_AR = ("عرض تقديمي", "شرائح", "شريحة", "بوربوينت", "باوربوينت")
_DOC = re.compile(r"\b(report|proposal|white ?paper|newsletter|cv|resume|résumé|booklet|handbook|guide|document|e-?book)\b", re.I)
_DOC_AR = ("تقرير", "مقترح", "سيرة ذاتية", "السيرة الذاتية", "كتيب", "دليل")


async def design_preload(messages, text, root, subject=None):
    """The person asks for a design and this chat has no Design skill yet → the skills it will load, given with their
    message (with the list of what this workspace made lately, and — when the turn hasn't searched — the note to
    search first), else None. The agent spent its first turn of every design asking for them."""
    from .tool import _DESIGN_WORDS, _DESIGN_WORDS_AR, design_skills_loaded
    text = str(text or "")
    if design_skills_loaded(messages):
        return None
    wants = _DESIGN_WORDS.search(text) or any(w in text for w in _DESIGN_WORDS_AR) or ".fig" in text
    if not wants or not (_MAKE.search(text) or any(w in text for w in _MAKE_AR)):
        return None
    kind = ("deck-design" if _DECK.search(text) or any(w in text for w in _DECK_AR)
            else "document-design" if _DOC.search(text) or any(w in text for w in _DOC_AR) else "graphic-design")
    loaded = skill.load(["design-direction", kind])
    if loaded.startswith("Error"):
        return None
    made = await asyncio.to_thread(recent.listing, root)
    parts = [f"[The Design skills for this request, loaded for you — design-direction and {kind}; no `skill` call "
             f"needed (load another only if the piece turns out to be another kind).]", loaded]
    if made:
        parts.append(made)
    parts.append(_SEARCH_NOW)
    return "\n\n".join(parts)


_NOW_ACTIONS = ("render", "edit", "script", "import", "inspect", "update_slide", "add_slide")
_NOW_MAX = 6_000


def _chat_design(messages):
    """The design this chat last made or changed — the `name` its latest Design call gave — else None."""
    for m in reversed(messages or []):
        content = m.get("content")
        for b in reversed(content) if isinstance(content, list) else []:
            if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "design"):
                continue
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            if str(inp.get("action") or "render").lower() in _NOW_ACTIONS and isinstance(inp.get("name"), str) and inp["name"].strip():
                return inp["name"]
    return None


async def design_now(messages, root, folder="", subject=None):
    """The design this chat is working on, as it is NOW → a line for the person's message, or None. Read from its
    file on every message, so the agent never works on a design it no longer remembers (old tool results are
    cleared after a pause, and the render it saw went with them) or on one changed by hand since: it names the
    parts as they are, and an edit needs no `inspect` first."""
    name = _chat_design(messages)
    if not name:
        return None
    stem = _find_design(root, name, folder)
    fig = pathlib.Path(root) / f"{stem}.fig"
    if not await asyncio.to_thread(fig.is_file):
        return None
    from cycls._agent import design
    o = await asyncio.wait_for(design.outline(await asyncio.to_thread(fig.read_bytes), user_id=subject), 8)
    text = _outline_text(f"{stem}.fig", o["frames"], o["pages"], o["page"])
    if len(text) > _NOW_MAX:
        text = text[:_NOW_MAX] + " …"
    return ("[The design this chat is working on, as it is now (read from its file, with any change made by hand in "
            f"the editor). Change it with ONE `edit` by these names; no `inspect` needed.\n{text}]")


async def _exec_design(inp, workspace):
    """Run one Design call → `_model` (the ack the model reads) and `_ui` (what the canvas opens). The workspace's
    own fonts (brand/fonts) reach the service first, and the call that first gives them says their family; a
    render in a chat that hasn't loaded the tool's skills says which to load (DESIGN_SKILLED, set by the loop)."""
    from cycls._agent import design
    action = str(inp.get("action") or "render").lower()
    if action == "render" and DESIGN_LOADED.get():
        # A new design starts from what is true of its subject. A design made again (its file is there: `replace`,
        # or a variant beside it) was researched when it was first made: an edit's re-render was held as new and
        # sent the agent to search for nothing, then render the same spec again.
        remade = (pathlib.Path(workspace.root) / f"{_stem_of(inp.get('name') or 'design', DESIGN_FOLDER.get())}.fig").is_file()
        if not DESIGN_RESEARCHED.get() and not remade:
            return _RESEARCH_FIRST
        if not DESIGN_CHECKED.get():                          # in their language, with their names as they wrote them
            branded = bool(await asyncio.to_thread(_load_brand, workspace.root))
            held = brief.check(_spec_of(inp), DESIGN_ASK.get(), DESIGN_HEARD.get(), branded)
            if held:
                return held
    said = await design.add_fonts(workspace.root, getattr(workspace, "subject", None))
    out = await _design_call(inp, workspace)
    if action == "render" and not DESIGN_SKILLED.get():
        spec = inp.get("spec") if isinstance(inp.get("spec"), dict) else inp
        want = json.dumps(["design-direction", _skill_for(spec)])
        out = _nudged(out, f"No design skill is loaded in this chat: {{\"action\": \"skill\", \"skill\": {want}}} holds the "
                           f"looks, the layouts and how to change this design in few calls — load it before the next change.")
    if said and isinstance(out, str):
        return f"{said}\n\n{out}"
    if said and isinstance(out, dict) and "_model" in out:
        m = out["_model"]
        return {**out, "_model": [{"type": "text", "text": said}, *m] if isinstance(m, list) else f"{said}\n\n{m}"}
    return out


_FONT_KEYS = ("font", "headerFont", "heading", "body", "arHeading", "arBody")


async def _font_files(v, root, user_id):
    """A font named by its file anywhere in the workspace (a .ttf / .otf path) → given to the service and named by
    the family and weight the file says, so that design draws with it."""
    from cycls._agent import design
    if isinstance(v, list):
        return [await _font_files(x, root, user_id) for x in v]
    if not isinstance(v, dict):
        return v
    out = {}
    for k, x in v.items():
        if k in _FONT_KEYS and isinstance(x, str) and x.lower().endswith((".ttf", ".otf")):
            if not (path := _resolve_path(x, root)).is_file():
                raise RuntimeError(f"there is no font file {x} in the workspace")
            got, _ = await design.give_font(path, user_id)
            if isinstance(got, str):
                raise RuntimeError(f"the font file {x} can't be used: {got}")
            x = f"{got['family']} {got['style']}"
        out[k] = await _font_files(x, root, user_id)
    return out


async def _design_call(inp, workspace):
    from cycls._agent import design
    # the model saw only the short form: this call loads the full one, and runs nothing made blind
    asked = str(inp.get("action") or "render").lower()
    if asked == "skill":                                    # text only: it runs on the short form too, and loads the whole
        text = skill.load(inp.get("skill") if inp.get("skill") is not None else inp.get("name"))
        if text.startswith("Error"):
            return text
        made = await asyncio.to_thread(recent.listing, workspace.root)   # what's new is new against these
        text = f"{text}\n\n{made}" if made else text
        text = text if DESIGN_LOADED.get() else f"{text}\n\n{_GUIDE_LOADED}"
        return text if DESIGN_RESEARCHED.get() else f"{text}\n\n{_SEARCH_NOW}"
    if not DESIGN_LOADED.get():
        if asked == "guide":
            made = await asyncio.to_thread(recent.listing, workspace.root)
            text = f"{_GUIDE_LOADED}\n\n{made}" if made else _GUIDE_LOADED
            return text if DESIGN_RESEARCHED.get() else f"{text}\n\n{_SEARCH_NOW}"
        return _GUIDE_NOT_RUN
    if asked == "guide":
        return ("Design's instructions are already loaded — they are this tool's description. Call it with "
                "what you want made (render, edit, inspect, …). Nothing was made or changed by this call.")
    # a large nested argument may arrive as its JSON text
    inp = dict(inp)
    mended = []
    for key in ("spec", "ops", "slide"):
        v = inp.get(key)
        if isinstance(v, str) and (fenced := re.fullmatch(r"\s*```[a-zA-Z]*\s*(.*?)\s*```\s*", v, re.S)):
            v = fenced.group(1)                              # a code fence around it
        if isinstance(v, str) and v.strip()[:1] in ("{", "["):
            try:
                inp[key] = json.loads(v)
            except json.JSONDecodeError as e:
                fixed = _mend_json_tail(v)
                if fixed is not None:
                    inp[key] = fixed
                    mended.append(f"`{key}` came as text that ended with the wrong closing brackets — it was read as closed "
                                  f"where its content ends (check nothing is missing from its end). Send it as an object.")
                    continue
                # say where it breaks, so the model fixes it rather than rewriting it blind
                at = e.pos
                near = v[max(0, at - 60):at + 40].replace("\n", " ")
                cut = at >= len(v.rstrip()) - 1 or e.msg.startswith("Unterminated string")
                why = ("it is cut off before its end — the call ran out of room" if cut else
                       f"{e.msg} at character {at} of {len(v)}, near: …{near}… (most often a quote left unescaped inside a string, or a line break in one)")
                more = (" A long document need not come in one call: render its first sections, then add_section for each of the rest."
                        if key == "spec" else "")
                return (f"Error: `{key}` came as text that isn't valid JSON — {why}. Nothing was done. "
                        f"Send `{key}` again as an object, with that put right.{more}")
    try:
        inp = await _font_files(inp, workspace.root, getattr(workspace, "subject", None))
    except (RuntimeError, ValueError) as e:
        return f"Error: {e}. Nothing was done."
    action = (inp.get("action") or "render").lower()
    # a design written beside `spec` rather than under it
    if action == "render" and inp.get("spec") is None:
        beside = {k: inp[k] for k in ("document", "deck", "pages", "frames", "nodes", "size", "fill", "theme", "look") if inp.get(k) is not None}
        if any(k in beside for k in ("document", "deck", "pages", "frames", "nodes")):
            inp["spec"] = beside
    fmt = (inp.get("format") or "png").lower()
    if fmt not in _DESIGN_EXTS:
        return f"Error: unknown format {fmt!r} (png, jpg, webp, svg, pptx)."
    # `name` is the design's path without `.fig`; with no folder in it, the folder the person has open
    folder = DESIGN_FOLDER.get()
    if action == "extract" and not inp.get("name") and isinstance(inp.get("path"), str):
        name = _stem_of(inp["path"].rsplit(".", 1)[0])                     # its parts beside the PDF
    elif action == "import" and not inp.get("name") and isinstance(inp.get("path"), str):
        name = _stem_of(inp["path"].replace("\\", "/").rsplit("/", 1)[-1], folder)   # the deck's own name, where the person is
    elif action in ("render", "script", "extract", "import"):
        name = _stem_of(inp.get("name") or "design", folder)
    else:
        name = _find_design(workspace.root, inp.get("name") or "design", folder)
    try:
        _resolve_path(f"{name}.fig", workspace.root)
    except ValueError as e:
        return f"Error: a design can't be saved at {name}.fig — {e}. Nothing was done."
    subject = getattr(workspace, "subject", None)
    if action in _SLIDE_ACTIONS:
        return await _exec_slides(action, inp, workspace, name)
    if action in _DOCUMENT_ACTIONS:
        return await _exec_document(action, inp, workspace, name)
    if action == "extract":
        return await _pdf_parts(inp, workspace, name)
    if action == "import":                                  # a PowerPoint deck, opened as a design to change
        return await _import_deck(inp, workspace, name)
    if action in _FILE_ACTIONS:
        return await _exec_design_file(action, inp, workspace, name)
    if action == "comments":
        return await _exec_comments(inp, workspace, name)
    if action == "assets":                                  # what the media library holds
        from cycls._agent.design import assets
        return await assets.listing(inp, subject)
    if action in ("edit", "inspect"):
        rel = f"{name}.fig"
        fig_path = pathlib.Path(workspace.root) / rel
        if not fig_path.is_file():
            return (f"Error: {rel} doesn't exist — `{action}` works on a design you rendered (`render` creates one). "
                    f"The designs here: {_designs_there(workspace.root)}.")
    page = str(inp.get("page") or "").strip() or None
    if action == "inspect":
        try:   # with every frame of the page small on contact sheets: the whole of it at a glance
            o = await design.outline(await asyncio.to_thread(fig_path.read_bytes), user_id=subject, page=page, sheets=True)
        except design.Unavailable as e:
            return f"Error: design unavailable — {e}"
        except Exception as e:
            return f"Error: couldn't inspect {rel} — {e}"
        text = _outline_text(rel, o["frames"], o["pages"], o["page"])
        if pinned := await _comments_note(workspace, rel, o):
            text += "\n\n" + pinned
        keep = o.get("keep") or {}
        doc = keep.get("document") if keep.get("kind") == "document" and isinstance(keep.get("document"), dict) else None
        text = f"{_sections_text(name, doc)}\n\n{text}" if doc else text
        word, blocks, total = "Pages" if doc else "Slides", [], 0
        for (first, last), jpg in zip(o.get("sheet_pages") or [], o.get("sheets") or []):
            if total + len(jpg) > _DESIGN_QA_MAX:
                break
            total += len(jpg)
            blocks += [{"type": "text", "text": f"{word} {first}–{last}, small:"},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(jpg).decode()}}]
        if not blocks:
            return text
        return {"_model": [{"type": "text", "text": text + f"\n\nEvery {word[:-1].lower()} is on the sheet below, small: "
                                                          "how each is laid out, and how they sit together."}, *blocks]}
    # The service applies an edit to the .fig headless first, so a failure reaches the model and a
    # success is saved with or without an open editor; the UI event then replays it live there.
    if action == "edit":
        script, ops = inp.get("script"), inp.get("ops")
        if not ops and not script:
            return ("Error: `edit` needs `ops` — e.g. [{\"op\":\"set_text\",\"node\":\"headline\",\"text\":\"…\"}] "
                    "(Design inspect lists the node names) — or a raw `script`.")
        credits = []
        if ops:
            from cycls._agent.design import assets
            credits, err = await assets.named(ops, workspace.root, subject)   # {"stock": "…"}, {"asset": "…"} → a saved picture
            if err:
                return err
            ops, err = await asyncio.to_thread(_prepare_ops, ops, workspace.root)
            if err:
                return err
        from cycls._agent.design.deck import lock
        from cycls._agent.design.store import Stale, load_fig, write_fig
        async with lock(fig_path):                          # one change at a time per design
            for attempt in (1, 2):
                data, base = await load_fig(workspace.root, rel)
                try:
                    r = await design.apply(data, script=None if ops else script,
                                           ops=ops or None, preview=True, user_id=subject, page=page, sheets=True)
                except design.Unavailable as e:
                    return f"Error: design unavailable — {e}"
                except Exception as e:
                    # a service error with " has: " already lists the nodes
                    hint = "" if " has: " in str(e) else " (Design inspect lists the nodes)"
                    return (f"Error: the edit failed on {rel} — {e}. Nothing was changed; fix the "
                            f"{'ops' if ops else 'script'}{hint} and try again.")
                try:   # a save in the editor meanwhile: apply to that, once
                    version = await write_fig(workspace.root, rel, r["fig"], base=base, by="agent", reason="agent",
                                              intent=inp.get("intent"))
                    break
                except Stale:
                    if attempt == 2:
                        return (f"Error: {rel} changed while the edit was being made (it's being edited "
                                f"by hand). Nothing was changed; inspect it again, then edit.")
        from cycls._agent.design import refresh
        pages, ended = r.get("pages") or [], r.get("page") or ""
        made_page = any(isinstance(op, dict) and op.get("op") in ("page_add", "page_duplicate") for op in ops or [])
        refresh.schedule(workspace.root, rel, subject)        # its preview, made ready
        ui = {"type": "ui", "action": "design_command", "path": rel, "script": r.get("script") or script,
              "version": version}   # an open editor's later saves base on this version
        if len(pages) > 1 or made_page:
            ui["page"] = r.get("started") or ""   # an open editor shows this page first
        if any(isinstance(op, dict) and str(op.get("op") or "").startswith("page_") for op in ops or []):
            # page ops aren't replayed live: the editor reloads on the page the edit ended on
            ui["reload"], ui["page"] = True, ended
        if intent := inp.get("intent"):
            ui["intent"] = str(intent)[:80]   # shown on the live "Super" cursor
        await _to_the_room(workspace.root, rel, ui)
        on = (f" on page {json.dumps(ended, ensure_ascii=False)} — the design's pages are now "
              + ", ".join(json.dumps(p["name"], ensure_ascii=False) for p in pages)) if len(pages) > 1 else ""
        ack = (f"Edit applied and saved to {rel}{on}. If the design is open in the editor, the Super "
               f"cursor replays the change live there." + _edit_names(r) + _fixed_line(r.get("fixed"), "png")
               + _layout_check(r.get("lint"), "png"))
        for credit in credits:
            ack += f" {credit}."
        # a deck or carousel: show the slides the edit changed, not slide 1 — more than two, small on one sheet
        blocks, total = [], 0
        for numbers, jpg in zip(r.get("sheet_frames") or [], r.get("sheets") or []):
            if total + len(jpg) > _DESIGN_QA_MAX:
                break
            total += len(jpg)
            blocks += [{"type": "text", "text": "Slides " + ", ".join(map(str, numbers)) + ", small:"},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(jpg).decode()}}]
        if blocks:
            ack += (" The slides it changed are attached, small on one sheet. Check the change landed as intended "
                    "and nothing else moved or collides; if not, edit again.")
            return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
        touched, looks = r.get("touched") or [], r.get("previews") or []
        if len(r.get("slides") or []) > 1 and looks and len(looks) == len(touched) and touched != [0]:
            blocks, total = [], 0
            for i, jpg in zip(touched, looks):
                if total + len(jpg) > _DESIGN_QA_MAX:
                    break
                total += len(jpg)
                blocks += [{"type": "text", "text": f"Slide {i + 1}:"},
                           {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": base64.b64encode(jpg).decode()}}]
            if blocks:
                ack += (" The slides it changed are attached — check the change landed as intended and "
                        "nothing else moved or collides; if not, edit again.")
                return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
        if not r.get("preview") or len(r["preview"]) > _DESIGN_QA_MAX:
            return {"_model": ack, "_ui": ui}
        ack += (" The edited design is attached — check the change landed as intended and "
                "nothing else moved or collides; if not, edit again.")
        return {"_model": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": base64.b64encode(r["preview"]).decode()}},
                           {"type": "text", "text": ack}],
                "_ui": ui}
    notes = []
    try:
        if action == "render":
            if not isinstance(inp.get("spec"), dict):
                got = inp.get("spec")
                came = (f"this call has: {', '.join(k for k in inp if inp[k] is not None)} — no design" if got is None
                        else f"`spec` came as text ({json.dumps(got[:60], ensure_ascii=False)}{'…' if len(got) > 60 else ''}), not an object" if isinstance(got, str)
                        else f"`spec` came as a {'list' if isinstance(got, list) else type(got).__name__}, not an object")
                return (f"Error: `render` needs a `spec` object, e.g. {{size:[1080,1080], fill:'#0f172a', nodes:[...]}} — {came}. "
                        f"Put the design under `spec`: {{size, fill, nodes}}, {{deck}}, {{document}} or {{pages}}.")
            if isinstance(inp["spec"].get("document"), dict):
                return await _render_document(inp, workspace, name)
            root = workspace.root   # reads the brand kit + any image files: off the loop
            # {"stock": …}, {"asset": …} pictures are saved first, so the spec sees ordinary files
            from cycls._agent.design import assets
            credits, err = await assets.named(inp["spec"], root, subject)
            if err:
                return err
            # a new deck draws its theme's glow or circles only when it asks for them (an old one's slides keep theirs)
            spec_in, quiet = _quiet_deck(inp["spec"])
            spec, err, notes = await asyncio.to_thread(lambda: _prepare_spec(spec_in, _load_brand(root), root))
            if err:
                return err
            notes = [*mended, *notes, *([quiet] if quiet else []), *(f"{c}." for c in credits)]
            # what it is, kept in the .fig: a deck keeps the settings its added slides are laid out with
            if isinstance(spec.get("deck"), dict):
                from cycls._agent.design.deck import settings_of
                n_frames, keep = len(spec["deck"]["slides"]), {"kind": "deck", "deck": settings_of(spec["deck"])}
            elif isinstance(spec.get("pages"), list):
                n_frames, keep = 1, {"kind": "design"}
            else:
                n_frames = len(spec["frames"]) if isinstance(spec.get("frames"), list) and spec["frames"] else 1
                keep = {"kind": "deck" if fmt in _DECK_EXTS else "carousel" if n_frames > 1 else "post"}
            # the file is the design: its picture is only looked at, so it's drawn small; a long deck's rest on contact sheets
            long = n_frames > _DESIGN_QA_SLIDES and keep["kind"] == "deck"
            r = await design.render(spec, fmt="png", scale=1, user_id=subject, keep=keep,
                                    **({"sheets": True, "lead": _DESIGN_QA_SLIDES} if long else {}))
            notes = [*notes, *r.notes]
        elif action == "script":
            if not inp.get("script"):
                return "Error: `script` needs a `script` string ending in console.log('__FRAME__'+id)."
            keep = {"kind": "deck" if fmt in _DECK_EXTS else "post"}
            r = await design.evaluate(inp["script"], fmt="png", scale=1, user_id=subject, keep=keep)
        else:
            return f"Error: unknown design action {action!r} (render or script)."
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: design {action} failed — {type(e).__name__}: {e}"
    fig, preview, lint = r.fig, r.preview, r.lint
    if len(r.pages) > 1:
        return await _save_pages(r, name, fmt, workspace, notes, inp)
    count = max(len(r.previews), len(r.slides), 1)
    kind = "carousel" if keep["kind"] == "post" and count > 1 else keep["kind"]
    # never clobber an earlier design: launch → launch-2 → …; `replace` renders this one again
    root = pathlib.Path(workspace.root)
    replacing = _replacing(root, name, inp)
    requested, name = name, name if replacing else await asyncio.to_thread(_free_design, root, name)
    fig_rel = f"{name}.fig"
    if replacing:
        again = await _render_again(workspace, fig_rel, fig, inp)
    else:
        await asyncio.to_thread((root / fig_rel).parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread((root / fig_rel).write_bytes, fig)
    from cycls._agent.design import refresh
    refresh.schedule(workspace.root, fig_rel, subject)        # its preview, made ready
    note = (f", named '{name}' so it doesn't overwrite the existing '{requested}'" if name != requested else "")
    saved = "rendered again in place" if replacing else "saved"
    what = (f"{'Deck' if kind == 'deck' else 'Carousel'} {saved} ({count} slide{'s' if count != 1 else ''}{note})" if count > 1 or kind == "deck"
            else f"Design {saved}{f' ({note[2:]})' if note else ''}")
    ack, ui = (f"{what}: {fig_rel}. Its earlier version is kept in its history.", again) if replacing else _opened(fig_rel, what)
    ack += " Change it with Design edit — or, slide by slide, add_slide / update_slide." if count > 1 or kind == "deck" else " Change it with Design edit."
    if action == "render":                                    # what it looks like, against what this workspace made before
        notes = [*notes, *await asyncio.to_thread(_remember, root, fig_rel, spec, kind)]
    for line in notes:
        ack += " " + line
    ack += _fixed_line(r.fixed, fmt if count == 1 else "pptx") + _layout_check(lint, fmt if count == 1 else "pptx")
    # The model QAs its own render: the @1x JPEG previews (a @2x PNG runs MBs; a PPTX isn't
    # an image), else the raster itself within _DESIGN_QA_MAX, else the ack alone.
    fix = "Design edit (the same design — don't re-render)"
    if count > 1 and r.previews:
        blocks, total = [], 0
        for n, jpg in enumerate(r.previews[:_DESIGN_QA_SLIDES], 1):
            if blocks and total + len(jpg) > _DESIGN_QA_MAX:
                break
            total += len(jpg)
            blocks += [{"type": "text", "text": f"Slide {n}:"},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(jpg).decode()}}]
        shown = len(blocks) // 2
        sheets = []
        for span, jpg in zip(r.sheet_pages, r.sheets):
            if total + len(jpg) > _DESIGN_QA_MAX:
                break
            total += len(jpg)
            sheets.append(span)
            blocks += [{"type": "text", "text": f"Slides {span[0]}–{span[1]}, small:"},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(jpg).decode()}}]
        which = (f"All {count} slides are attached" if shown == count else
                 f"Slides 1–{shown} are attached to read, and slides {sheets[0][0]}–{sheets[-1][1]} on {len(sheets)} contact "
                 f"sheet{'' if len(sheets) == 1 else 's'} (small — for how each is laid out, not for its words)" if sheets else
                 f"Slides 1–{shown} of {count} are attached (Design inspect lists the rest)")
        ack += (f" {which} — QA EVERY slide before you present: its headline clearly dominant; "
                "margins ~8–10%, nothing crammed at an edge; every text legible on what's behind it; "
                "nothing overlapping or cut off; copy exactly right; and the slides CONSISTENT with "
                "each other (title position, margins, palette, fonts); the deck made for THIS content, not a "
                "named theme as it stands or a stock look. If anything is off, fix it "
                f"now with {fix} (ops take `frame`, the slide index from 0), then present.")
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    look, media = (preview, "image/jpeg") if preview else (r.image, _DESIGN_QA_TYPES.get("png"))
    if not media or len(look) > _DESIGN_QA_MAX:
        return {"_model": ack, "_ui": ui}
    shown = "The first slide is attached" if count > 1 or kind == "deck" else "The render is attached"
    ack += (f" {shown} — QA it before you present: headline clearly dominant; "
            "margins ~8–10%, nothing crammed at an edge; every text legible on what's behind it; "
            "aligned, nothing overlapping or cut off; copy exactly right (spelling, names, "
            f"numbers); on-brand; made for THIS content, not a stock look or the last design again. "
            f"If anything is off, fix it now with {fix}, then present.")
    return {"_model": [{"type": "image", "source": {"type": "base64", "media_type": media,
                                                    "data": base64.b64encode(look).decode()}},
                       {"type": "text", "text": ack}],
            "_ui": ui}


def _remember(root, fig_rel, spec, kind):
    """A new render's look, kept so the next design can be new against it → the notes it earns: what it shares
    with a recent design, and the stock glow (recent.py). Remembering never stops a render."""
    return recent.remember(root, fig_rel, spec, kind, brand=bool(_load_brand(root)))


def _design_step(inp):
    return {"tool_name": "Design", "step": inp.get("name") or (inp.get("path") if inp.get("action") == "import" else "") or ""}

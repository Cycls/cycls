"""The Design tool's executor. `_exec_design(inp, workspace)` reads a call and makes it:
render, script, edit, inspect, extract — and hands the slide, section and file actions to
actions.py. Registered in cycls/_agent/tools as the `design` tool."""
import asyncio, base64, json, os, pathlib, re
from ..paths import _safe_filename
from .tool import DESIGN_LOADED, _GUIDE_LOADED, _GUIDE_NOT_RUN
from .brand import _load_brand
from .images import _DESIGN_QA_MAX, _DESIGN_QA_SLIDES, _DESIGN_QA_TYPES
from .prepare import _mend_json_tail, _prepare_ops, _prepare_spec
from .extract import _pdf_parts
from .report import _edit_names, _layout_check, _outline_text
from .files import _DECK_EXTS, _DESIGN_EXTS, _dedupe_design_name, _save_pages
from .actions import (_DOCUMENT_ACTIONS, _FILE_ACTIONS, _SLIDE_ACTIONS, _document_source, _exec_design_file,
    _exec_document, _exec_slides, _render_document, _sections_text, _to_the_room)


async def _exec_design(inp, workspace):
    """Render a design via the shared cycls-design service, save the image + the
    editable `.fig` into the workspace, and open the image on the canvas. Two
    channels: the model reads a short ack; the client opens the render (same
    open_canvas event the Canvas tool and browser screenshots use)."""
    from cycls._agent import design
    # The model was shown the short form of the tool (DESIGN_INSTRUCTIONS=on-demand): this
    # call is what loads the whole of it — the guide — and nothing made blind is run.
    asked = str(inp.get("action") or "render").lower()
    if not DESIGN_LOADED.get():
        return _GUIDE_LOADED if asked == "guide" else _GUIDE_NOT_RUN
    if asked == "guide":
        return ("Design's instructions are already loaded — they are this tool's description. Call it with "
                "what you want made (render, edit, inspect, …). Nothing was made or changed by this call.")
    # A model may hand a large nested argument over as its JSON text: read as the object.
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
                # Right to its last value and closed with the wrong brackets — one too many,
                # one too few: read as closed where its content ends, and said.
                fixed = _mend_json_tail(v)
                if fixed is not None:
                    inp[key] = fixed
                    mended.append(f"`{key}` came as text that ended with the wrong closing brackets — it was read as closed "
                                  f"where its content ends (check nothing is missing from its end). Send it as an object.")
                    continue
                # Said where it breaks: "needs a `spec` object" told a model nothing, and a
                # 6,000-token document was written out again, blind.
                at = e.pos
                near = v[max(0, at - 60):at + 40].replace("\n", " ")
                # (Cut short: it stops where more was expected, or inside a string that never closes.)
                cut = at >= len(v.rstrip()) - 1 or e.msg.startswith("Unterminated string")
                why = ("it is cut off before its end — the call ran out of room" if cut else
                       f"{e.msg} at character {at} of {len(v)}, near: …{near}… (most often a quote left unescaped inside a string, or a line break in one)")
                more = (" A long document need not come in one call: render its first sections, then add_section for each of the rest."
                        if key == "spec" else "")
                return (f"Error: `{key}` came as text that isn't valid JSON — {why}. Nothing was done. "
                        f"Send `{key}` again as an object, with that put right.{more}")
    action = (inp.get("action") or "render").lower()
    # A design written beside the action, not under `spec`: it is the spec.
    if action == "render" and inp.get("spec") is None:
        beside = {k: inp[k] for k in ("document", "deck", "pages", "frames", "nodes", "size", "fill") if inp.get(k) is not None}
        if any(k in beside for k in ("document", "deck", "pages", "frames", "nodes")):
            inp["spec"] = beside
    fmt = (inp.get("format") or "png").lower()
    if fmt not in _DESIGN_EXTS:
        return f"Error: unknown format {fmt!r} (png, jpg, webp, svg, pptx)."
    scale = inp.get("scale") or 2
    # Base name only, no extension the model may have tacked on.
    name = _safe_filename(inp.get("name") or "design", "design").rsplit(".", 1)[0] or "design"
    subject = getattr(workspace, "subject", None)
    # `edit` changes a saved design. The service runs the script on the .fig first —
    # the editor's own plugin API, headless — so a script that throws is the model's
    # error now (it used to fail silently inside the browser), and a success is saved
    # and re-exported whether or not an editor is open. Then a UI event replays the
    # same script in the live editor, where the user watches the Super cursor make it.
    if action in _SLIDE_ACTIONS:
        return await _exec_slides(action, inp, workspace, name)
    if action in _DOCUMENT_ACTIONS:
        return await _exec_document(action, inp, workspace, name)
    if action == "extract":
        if not inp.get("name") and isinstance(inp.get("path"), str):
            name = _safe_filename(pathlib.PurePosixPath(inp["path"].replace("\\", "/")).stem or "pdf", "pdf")
        return await _pdf_parts(inp, workspace, name)
    if action in _FILE_ACTIONS:
        return await _exec_design_file(action, inp, workspace, name)
    if action in ("edit", "inspect"):
        rel = f"designs/{name}.fig"
        fig_path = pathlib.Path(workspace.root) / rel
        if not fig_path.is_file():
            return (f"Error: {rel} doesn't exist — `{action}` works on a design you rendered; "
                    f"`render` creates one.")
    # `inspect` lists a design's frames and their named nodes — what `edit` ops name.
    page = str(inp.get("page") or "").strip() or None      # the page an inspect / edit is about
    if action == "inspect":
        try:
            o = await design.outline(await asyncio.to_thread(fig_path.read_bytes), user_id=subject, page=page)
        except design.Unavailable as e:
            return f"Error: design unavailable — {e}"
        except Exception as e:
            return f"Error: couldn't inspect {rel} — {e}"
        text = _outline_text(rel, o["frames"], o["pages"], o["page"])
        doc = await asyncio.to_thread(_document_source, workspace.root, name)
        return f"{_sections_text(name, doc)}\n\n{text}" if doc else text
    # `edit` changes a saved design: named `ops` (the normal way) or a raw `script`.
    # The service applies it to the .fig first — the editor's own plugin API, headless
    # — so an edit that fails is the model's error now (it used to fail silently in
    # the browser), and a success is saved and re-exported whether or not an editor is
    # open. Then a UI event replays the same script in the live editor, where the user
    # watches the Super cursor make it. The model gets the result back to check.
    if action == "edit":
        script, ops = inp.get("script"), inp.get("ops")
        if not ops and not script:
            return ("Error: `edit` needs `ops` — e.g. [{\"op\":\"set_text\",\"node\":\"headline\",\"text\":\"…\"}] "
                    "(Design inspect lists the node names) — or a raw `script`.")
        credits = []
        if ops:
            from cycls._agent.design import stock
            credits, err = await stock.resolve(ops, workspace.root)   # {"stock": "…"} → a saved photo
            if err:
                return err
            ops, err = await asyncio.to_thread(_prepare_ops, ops, workspace.root)
            if err:
                return err
        from cycls._agent.design.deck import lock
        from cycls._agent.design.store import Stale, read_fig, write_fig
        async with lock(fig_path):                          # one change at a time per design
            for attempt in (1, 2):
                data, base = await asyncio.to_thread(read_fig, workspace.root, rel)
                try:
                    r = await design.apply(data, script=None if ops else script,
                                           ops=ops or None, preview=True, user_id=subject, page=page)
                except design.Unavailable as e:
                    return f"Error: design unavailable — {e}"
                except Exception as e:
                    # (An error that lists what the design has needs no "inspect lists the nodes".)
                    hint = "" if " has: " in str(e) else " (Design inspect lists the nodes)"
                    return (f"Error: the edit failed on {rel} — {e}. Nothing was changed; fix the "
                            f"{'ops' if ops else 'script'}{hint} and try again.")
                try:   # the person may have saved in the editor meanwhile: apply to that, once
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
        # The image beside it follows — or is made; a page an edit made gets its own.
        refresh.schedule(workspace.root, rel, subject, ensure=True, pages=made_page)
        ui = {"type": "ui", "action": "design_command", "path": rel, "script": r.get("script") or script,
              "version": version}   # what the file is now — an open editor's saves go on from it
        if len(pages) > 1 or made_page:
            ui["page"] = r.get("started") or ""   # the page it is made on: an open editor shows it first
        if any(isinstance(op, dict) and str(op.get("op") or "").startswith("page_") for op in ops or []):
            # Pages added, copied, renamed or removed: an open editor re-opens the saved
            # file on the page the edit ended on — page surgery isn't replayed live.
            ui["reload"], ui["page"] = True, ended
        if intent := inp.get("intent"):
            ui["intent"] = str(intent)[:80]   # shown on the live "Super" cursor
        await _to_the_room(workspace.root, rel, ui)   # people in the design together get it once, from their room
        if len(pages) > 1:
            place = next((n for n, p in enumerate(pages, 1) if p["name"] == ended), 1)
            image = f"designs/{refresh.page_file(name, place, 'png')}"
            on = (f" on page {json.dumps(ended, ensure_ascii=False)} — the design's pages are now "
                  + ", ".join(json.dumps(p["name"], ensure_ascii=False) for p in pages))
        else:
            image, on = f"designs/{name}.png etc.", ""
        ack = (f"Edit applied and saved to {rel}{on}; the image beside it ({image}) "
               f"re-exports in a few seconds. If the design is open in the editor, the Super "
               f"cursor replays the change live there." + _edit_names(r) + _layout_check(r.get("lint"), "png"))
        for credit in credits:
            ack += f" {credit}."
        # A deck or a carousel: the slides the edit changed, each said — not the first slide.
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
    notes, size = [], None
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
            # Photos named rather than saved — {"stock": "coffee beans"} — are found and
            # saved to the workspace first, so the spec below sees ordinary files.
            from cycls._agent.design import stock
            credits, err = await stock.resolve(inp["spec"], root)
            if err:
                return err
            spec, err, notes = await asyncio.to_thread(lambda: _prepare_spec(inp["spec"], _load_brand(root), root))
            if err:
                return err
            notes = [*mended, *notes, *(f"{c}." for c in credits)]
            if isinstance(spec.get("deck"), dict):
                n_frames, size = len(spec["deck"]["slides"]), spec["deck"]["size"]
            elif isinstance(spec.get("pages"), list):
                # Several pages: one design, each page's own image (never a carousel or a deck file).
                if fmt in _DECK_EXTS:
                    # Not refused for a second call: a page is an image, and that is what is made.
                    notes.append(f"A design of several pages renders to an image a page, so it was rendered as png, not {fmt} — "
                                 f"each page is downloaded as PDF or PowerPoint from the canvas.")
                    fmt = "png"
                n_frames, size = 1, None
            else:
                frames = spec["frames"] if isinstance(spec.get("frames"), list) and spec["frames"] else [spec]
                n_frames, size = len(frames), frames[0].get("size")
            # Several frames in a raster format are a carousel: every slide comes back.
            # Past twelve slides: twelve to read, the rest on contact sheets — all of it seen.
            carousel = n_frames > 1 and fmt not in _DECK_EXTS
            long = n_frames > _DESIGN_QA_SLIDES and not carousel
            r = await design.render(spec, fmt=fmt, scale=scale, user_id=subject, every=carousel,
                                    **({"sheets": True, "lead": _DESIGN_QA_SLIDES} if long else {}))
            notes = [*notes, *r.notes]
        elif action == "script":
            if not inp.get("script"):
                return "Error: `script` needs a `script` string ending in console.log('__FRAME__'+id)."
            r = await design.evaluate(inp["script"], fmt=fmt, scale=scale, user_id=subject)
        else:
            return f"Error: unknown design action {action!r} (render or script)."
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: design {action} failed — {type(e).__name__}: {e}"
    image, fig, preview, lint = r.image, r.fig, r.preview, r.lint
    if len(r.pages) > 1:
        return await _save_pages(r, name, fmt, workspace, notes)
    count = max(len(r.previews), len(r.slides), 1)

    # Never clobber an earlier design: if this base name is taken, bump it
    # (launch → launch-2 → …). To CHANGE an existing design, the model uses `edit`.
    requested = name
    name = _dedupe_design_name(pathlib.Path(workspace.root) / "designs", name, fmt)
    root = pathlib.Path(workspace.root)
    (root / "designs").mkdir(parents=True, exist_ok=True)
    if len(r.images) > 1:
        # A carousel: one image per slide, <name>-slide-N (what gets posted, in order).
        saved = [f"designs/{name}-slide-{n}.{fmt}" for n in range(1, len(r.images) + 1)]
        for rel_n, data in zip(saved, r.images):
            await asyncio.to_thread((root / rel_n).write_bytes, data)
        rel = saved[0]
    else:
        saved = [rel := f"designs/{name}.{fmt}"]
        await asyncio.to_thread((root / rel).write_bytes, image)
    # The .fig is the durable, editable source of truth (opened by a drag-editor
    # later); saved beside the render but not itself shown on the canvas.
    fig_rel = f"designs/{name}.fig"
    await asyncio.to_thread((root / fig_rel).write_bytes, fig)
    if count > 1:
        # A deck (or carousel) gets its deck document: what the canvas opens to show
        # and present it. The slides' titles, notes and transitions live in the .fig.
        deck = {"type": "cycls.deck", "version": 1, "fig": fig_rel, "size": size,
                "slides": count, "exports": saved}
        if action == "render" and isinstance(spec.get("deck"), dict):
            from cycls._agent.design.deck import settings_of
            deck["settings"] = settings_of(spec["deck"])      # what a new slide is laid out with
            if r.dir and "dir" not in deck["settings"]:
                deck["settings"]["dir"] = r.dir                  # its bilingual slides' direction
        await asyncio.to_thread((root / f"designs/{name}.deck.json").write_text,
                                json.dumps(deck, indent=2), "utf-8")
    note = (f" (named '{name}' so it doesn't overwrite the existing '{requested}')"
            if name != requested else "")
    kb = (sum(map(len, r.images)) if len(saved) > 1 else len(image)) // 1024
    if len(saved) > 1:
        what = f"Carousel saved ({count} slides: {saved[0]} … {saved[-1]}, {kb} KB{note})"
    elif count > 1:
        what = f"Deck saved ({rel}, {count} slides, {kb} KB{note})"
    else:
        what = f"Design saved ({rel}, {kb} KB{note})"
    # Open the EDITABLE .fig in the in-canvas editor by default — the user came to
    # DESIGN, so every render lands them in a live editor they can refine, not a flat
    # PNG. The image is still saved (for download/sharing). Fall back to opening the
    # image only where no editor is wired up (DESIGN_EDITOR_URL unset).
    editor = bool(os.environ.get("DESIGN_EDITOR_URL"))
    if count > 1:
        # A deck (or carousel) opens in the deck viewer: its slides, Present, the
        # downloads, and Edit into the editor.
        deck_rel = f"designs/{name}.deck.json"
        # Said plainly, because the reply used to tell the person it was "open in the
        # design editor": a carousel opens here too, and is downloaded as its images.
        downloads = "its images (a .zip), PowerPoint or PDF" if len(saved) > 1 else "PowerPoint, PDF or its images"
        ack = (f"{what}. It's OPEN in the deck viewer ({deck_rel}) — say \"the deck viewer\", not the "
               f"design editor. There the user can page through it, Present it full screen (with the "
               f"speaker notes), and download it as {downloads}"
               f"{'; the viewer has an Edit button that opens the design editor' if editor else ''}. "
               f"Editable source: {fig_rel}; change it with Design edit.")
        ui = {"type": "ui", "action": "open_canvas", "path": deck_rel, "name": f"{name}.deck.json"}
    elif editor:
        ack = (f"{what}; its editable source {fig_rel} is now OPEN in the in-canvas editor — "
               f"the user can edit it live. Tell them they can tweak it directly there, or ask "
               f"you to change it (colors, copy, layout) and you'll apply it with Design edit.")
        ui = {"type": "ui", "action": "open_canvas", "path": fig_rel, "name": f"{name}.fig"}
    else:
        ack = f"{what}, opened on the canvas. Editable source: {fig_rel}."
        ui = {"type": "ui", "action": "open_canvas", "path": saved[0], "name": saved[0].rsplit("/", 1)[-1]}
    for line in notes:
        ack += " " + line
    ack += _layout_check(lint, fmt if count == 1 else "pptx")
    # Show the model its own render, so it QAs what it made before the user judges
    # it — a check the spec alone can't give (hierarchy, overlap, legibility, typos).
    # The service's small @1x JPEG previews when it sent them — one per slide for a
    # deck (a photo-heavy @2x PNG runs several MB; a PPTX isn't an image) — else the
    # render itself if it's a raster within `read`'s bound; otherwise the ack alone.
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
                "each other (title position, margins, palette, fonts). If anything is off, fix it "
                f"now with {fix} (ops take `frame`, the slide index from 0), then present.")
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    look, media = (preview, "image/jpeg") if preview else (image, _DESIGN_QA_TYPES.get(fmt))
    if not media or len(look) > _DESIGN_QA_MAX:
        return {"_model": ack, "_ui": ui}
    shown = "The first slide is attached" if count > 1 or fmt in _DECK_EXTS else "The render is attached"
    ack += (f" {shown} — QA it before you present: headline clearly dominant; "
            "margins ~8–10%, nothing crammed at an edge; every text legible on what's behind it; "
            "aligned, nothing overlapping or cut off; copy exactly right (spelling, names, "
            f"numbers); on-brand. If anything is off, fix it now with {fix}, then present.")
    return {"_model": [{"type": "image", "source": {"type": "base64", "media_type": media,
                                                    "data": base64.b64encode(look).decode()}},
                       {"type": "text", "text": ack}],
            "_ui": ui}


def _design_step(inp):
    return {"tool_name": "Design", "step": f"{inp.get('action', 'render')} {inp.get('name', '')}".strip()}

"""The Design tool's executor: render, script, edit, inspect and extract here; slide, section,
file and comment actions in actions.py."""
import asyncio, base64, json, pathlib, re
from ..paths import _resolve_path
from .tool import DESIGN_FOLDER, DESIGN_LOADED, _GUIDE_LOADED, _GUIDE_NOT_RUN
from .brand import _load_brand
from .images import _DESIGN_QA_MAX, _DESIGN_QA_SLIDES, _DESIGN_QA_TYPES
from .prepare import _mend_json_tail, _prepare_ops, _prepare_spec
from .extract import _pdf_parts
from .report import _edit_names, _layout_check, _outline_text
from .files import _DECK_EXTS, _DESIGN_EXTS, _designs_there, _find_design, _free_design, _opened, _save_pages, _stem_of
from .actions import (_DOCUMENT_ACTIONS, _FILE_ACTIONS, _SLIDE_ACTIONS, _comments_note, _exec_comments,
    _exec_design_file, _exec_document, _exec_slides, _render_document, _sections_text, _to_the_room)


async def _exec_design(inp, workspace):
    """Run one Design call → `_model` (the ack the model reads) and `_ui` (what the canvas opens)."""
    from cycls._agent import design
    # the model saw only the short form: this call loads the full one, and runs nothing made blind
    asked = str(inp.get("action") or "render").lower()
    if not DESIGN_LOADED.get():
        return _GUIDE_LOADED if asked == "guide" else _GUIDE_NOT_RUN
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
    action = (inp.get("action") or "render").lower()
    # a design written beside `spec` rather than under it
    if action == "render" and inp.get("spec") is None:
        beside = {k: inp[k] for k in ("document", "deck", "pages", "frames", "nodes", "size", "fill") if inp.get(k) is not None}
        if any(k in beside for k in ("document", "deck", "pages", "frames", "nodes")):
            inp["spec"] = beside
    fmt = (inp.get("format") or "png").lower()
    if fmt not in _DESIGN_EXTS:
        return f"Error: unknown format {fmt!r} (png, jpg, webp, svg, pptx)."
    # `name` is the design's path without `.fig`; with no folder in it, the folder the person has open
    folder = DESIGN_FOLDER.get()
    if action == "extract" and not inp.get("name") and isinstance(inp.get("path"), str):
        name = _stem_of(inp["path"].rsplit(".", 1)[0])                     # its parts beside the PDF
    elif action in ("render", "script", "extract"):
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
    if action in _FILE_ACTIONS:
        return await _exec_design_file(action, inp, workspace, name)
    if action == "comments":
        return await _exec_comments(inp, workspace, name)
    if action in ("edit", "inspect"):
        rel = f"{name}.fig"
        fig_path = pathlib.Path(workspace.root) / rel
        if not fig_path.is_file():
            return (f"Error: {rel} doesn't exist — `{action}` works on a design you rendered (`render` creates one). "
                    f"The designs here: {_designs_there(workspace.root)}.")
    page = str(inp.get("page") or "").strip() or None
    # `page` is a variant of the design (a post and its story), not a slide: "page 2" of a deck was a miss, twice
    pages_said = (" `page` names one of a design's variants (a post and its story); a deck's slides are its frames — "
                  "`inspect` without `page` lists every slide, and an edit names one with `frame`, from 0.")
    hint = lambda e: pages_said if str(e).startswith("there is no page") and page and page.isdigit() else ""
    if action == "inspect":
        try:
            o = await design.outline(await asyncio.to_thread(fig_path.read_bytes), user_id=subject, page=page)
        except design.Unavailable as e:
            return f"Error: design unavailable — {e}"
        except Exception as e:
            return f"Error: couldn't inspect {rel} — {e}.{hint(e)}"
        text = _outline_text(rel, o["frames"], o["pages"], o["page"])
        if pinned := await _comments_note(workspace, rel, o):
            text += "\n\n" + pinned
        keep = o.get("keep") or {}
        doc = keep.get("document") if keep.get("kind") == "document" and isinstance(keep.get("document"), dict) else None
        return f"{_sections_text(name, doc)}\n\n{text}" if doc else text
    # The service applies an edit to the .fig headless first, so a failure reaches the model and a
    # success is saved with or without an open editor; the UI event then replays it live there.
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
                    # a service error with " has: " already lists the nodes
                    nodes = "" if " has: " in str(e) else " (Design inspect lists the nodes)"
                    return (f"Error: the edit failed on {rel} — {e}. Nothing was changed; fix the "
                            f"{'ops' if ops else 'script'}{nodes} and try again.{hint(e)}")
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
               f"cursor replays the change live there." + _edit_names(r) + _layout_check(r.get("lint"), "png"))
        for credit in credits:
            ack += f" {credit}."
        # a deck or carousel: show the slides the edit changed, not slide 1
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
            # {"stock": …} photos are saved first, so the spec sees ordinary files
            from cycls._agent.design import stock
            credits, err = await stock.resolve(inp["spec"], root)
            if err:
                return err
            spec, err, notes = await asyncio.to_thread(lambda: _prepare_spec(inp["spec"], _load_brand(root), root))
            if err:
                return err
            notes = [*mended, *notes, *(f"{c}." for c in credits)]
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
        return await _save_pages(r, name, fmt, workspace, notes)
    count = max(len(r.previews), len(r.slides), 1)
    kind = "carousel" if keep["kind"] == "post" and count > 1 else keep["kind"]
    # never clobber an earlier design: launch → launch-2 → …
    root = pathlib.Path(workspace.root)
    requested, name = name, await asyncio.to_thread(_free_design, root, name)
    fig_rel = f"{name}.fig"
    await asyncio.to_thread((root / fig_rel).parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread((root / fig_rel).write_bytes, fig)
    from cycls._agent.design import refresh
    refresh.schedule(workspace.root, fig_rel, subject)        # its preview, made ready
    note = (f", named '{name}' so it doesn't overwrite the existing '{requested}'" if name != requested else "")
    what = (f"{'Deck' if kind == 'deck' else 'Carousel'} saved ({count} slide{'s' if count != 1 else ''}{note})" if count > 1 or kind == "deck"
            else f"Design saved{f' ({note[2:]})' if note else ''}")
    ack, ui = _opened(fig_rel, what)
    ack += " Change it with Design edit — or, slide by slide, add_slide / update_slide." if count > 1 or kind == "deck" else " Change it with Design edit."
    for line in notes:
        ack += " " + line
    ack += _layout_check(lint, fmt if count == 1 else "pptx")
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
                "each other (title position, margins, palette, fonts). If anything is off, fix it "
                f"now with {fix} (ops take `frame`, the slide index from 0), then present.")
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    look, media = (preview, "image/jpeg") if preview else (r.image, _DESIGN_QA_TYPES.get("png"))
    if not media or len(look) > _DESIGN_QA_MAX:
        return {"_model": ack, "_ui": ui}
    shown = "The first slide is attached" if count > 1 or kind == "deck" else "The render is attached"
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

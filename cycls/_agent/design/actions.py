"""The tool's actions beyond a plain render: a deck's slides, a document's sections, the
file itself (export, rename, copy, delete, versions), and a document rendered — which is
held when its pages were changed by hand since. `_exec_design` (run.py) hands each the call."""
import asyncio, base64, json, os, pathlib
from .. import trash
from ..paths import _safe_filename
from .brand import _load_brand
from .images import _DESIGN_QA_MAX, _DESIGN_QA_SLIDES
from .prepare import _PAPER, _num, _prepare_document, _prepare_slide
from .report import _layout_check, _page_changes
from .files import _DECK_EXTS, _DESIGN_EXTS, _dedupe_design_name, _designs_there, _rendered_copy, _write_beside


_SLIDE_ACTIONS = ("add_slide", "update_slide", "move_slide", "duplicate_slide", "delete_slide")
_DOCUMENT_ACTIONS = ("add_section", "update_section", "move_section", "delete_section", "update_document")
_BLOCK_KINDS = ("lead", "p", "h2", "h3", "bullets", "numbered", "callout", "quote", "stats", "chart", "table", "image",
                "columns", "cards", "pairs", "note", "nodes", "break")


def _document_source(root, name):
    """The source a document was rendered from (kept in its deck document), or None."""
    try:
        deck = json.loads((pathlib.Path(root) / f"designs/{name}.deck.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    doc = deck.get("document") if isinstance(deck, dict) and deck.get("kind") == "document" else None
    return doc if isinstance(doc, dict) and isinstance(doc.get("sections"), list) else None


def _sections_text(name, doc):
    """A document's sections as `inspect` lists them: what a section action names."""
    kind = lambda b: "p" if isinstance(b, str) else next((k for k in b if k in _BLOCK_KINDS), next(iter(b), "?")) if isinstance(b, dict) else "?"
    lines = [f"A document of {len(doc['sections'])} sections (its source is kept; a section action re-renders it in place):"]
    for i, s in enumerate(doc["sections"], 1):
        s = s if isinstance(s, dict) else {}
        lines.append(f"  {i}. {str(s.get('title') or '(untitled)')[:80]} — {', '.join(kind(b) for b in (s.get('blocks') or [])[:40]) or 'empty'}")
    lines.append(f"Change one with update_section {{name: \"{name}\", number, section: {{title?, blocks?}}}}; also add_section / "
                 f"move_section / delete_section, and update_document for its title, theme or cover.")
    return "\n".join(lines)


async def _exec_document(action, inp, workspace, name):
    """A document's own changes — a section added, rewritten, moved or removed; its title,
    look or cover changed — made on the source kept in its deck document, then rendered
    again in place (the earlier pages kept as a version). The model sends the part that
    changes, not the whole document; nothing is saved unless the render succeeds."""
    doc = await asyncio.to_thread(_document_source, workspace.root, name)
    if doc is None:
        return (f"Error: designs/{name}.deck.json isn't a document — `{action}` works on a document you rendered "
                f"({{document: …}}); a deck's slides have add_slide / update_slide.")
    sections = list(doc["sections"])

    def number(key, upto):
        v = _num(inp.get(key))
        if v is None or v < 1 or int(v) != v:
            raise ValueError(f"`{key}` is a section's number from 1, not {inp.get(key)!r} — the document has {len(sections)} sections")
        if v > upto:
            raise ValueError(f"`{key}` {int(v)}: the document has {len(sections)} sections")
        return int(v) - 1

    section = inp.get("section")
    try:
        if action in ("add_section", "update_section") and not isinstance(section, dict):
            return f"Error: `{action}` needs `section` — {{title, blocks: […]}}" + (" (or just the keys that change)." if action == "update_section" else ".")
        if action == "add_section":
            if not isinstance(section.get("blocks"), list):
                return "Error: a new section needs `blocks` — a list of blocks."
            at = number("at", len(sections) + 1) if inp.get("at") is not None else len(sections)
            sections.insert(at, section)
            intent = f"add section {at + 1}"
        elif action == "update_section":
            n = number("number", len(sections))
            sections[n] = {**(sections[n] if isinstance(sections[n], dict) else {}), **section}
            intent = f"change section {n + 1}"
        elif action == "move_section":
            n, to = number("number", len(sections)), number("to", len(sections))
            sections.insert(to, sections.pop(n))
            intent = f"move section {n + 1}"
        elif action == "delete_section":
            n = number("number", len(sections))
            if len(sections) == 1:
                return "Error: a document keeps at least one section."
            sections.pop(n)
            intent = f"delete section {n + 1}"
        else:
            change = inp.get("document")
            if not isinstance(change, dict) or not change:
                return "Error: `update_document` needs `document` — the keys that change, e.g. {title, theme, cover}."
            if "sections" in change:
                return "Error: `update_document` changes the document's own keys — its `sections` have add_section / update_section / move_section / delete_section."
            doc = {k: v for k, v in {**doc, **change}.items() if v is not None}
            intent = "change the document"
    except ValueError as e:
        return f"Error: {e}."
    return await _render_document({"spec": {"document": {**doc, "sections": sections}}, "replace": True,
                                   "intent": inp.get("intent") or intent, "discard_edits": inp.get("discard_edits")}, workspace, name)


async def _to_the_room(root, rel, ui):
    """An agent's change to a design, for the people who have it open together.

    They keep one shared document in step and one of their editors saves it
    (docs/notes/design.md, "Together"), so the change must reach that document once:
    its script is handed to their room, where the saver's editor makes it for everyone —
    or, when the change wrote the file anew (pages added or removed), the room is told
    to open it again. `ui` is the `design_command` event the chat's own editor gets;
    when the room took the change it is marked `live`, and that editor leaves it to
    the room instead of making it a second time. Nobody in the room, or no relay: the
    event goes as it always did."""
    from cycls._agent.design import live
    if ui.get("reload") or not ui.get("script"):
        body = {"kind": "reload", "version": ui.get("version")}
    else:
        body = {"kind": "command", "script": ui["script"], "version": ui.get("version"),
                **({"intent": ui["intent"]} if ui.get("intent") else {}),
                **({"page": ui["page"]} if ui.get("page") else {})}
    said = await live.notify(root, rel, body)
    if said and said.get("delivered"):
        ui["live"] = True


async def _exec_slides(action, inp, workspace, name):
    """A deck's slide actions — add / update (or its notes, title, transition) / move /
    duplicate / delete — run on the saved .fig through the service, like `edit`
    (design/deck.py). Slides are numbered from 1 here, as the user counts them."""
    from cycls._agent import design
    from cycls._agent.design import deck as decks
    root, subject = workspace.root, getattr(workspace, "subject", None)
    fig_path, fig_rel, deck_path, _ = decks.paths(root, name)
    if not fig_path.is_file():
        return f"Error: {fig_rel} doesn't exist — slide actions work on a deck you rendered."
    doc = await asyncio.to_thread(decks.read_doc, deck_path)
    # A slide's photos may be named, not saved yet: {"stock": "…"} → a workspace file.
    credits = []
    if isinstance(inp.get("slide"), dict):
        from cycls._agent.design import stock
        credits, err = await stock.resolve(inp["slide"], root)
        if err:
            return err

    def number(key):
        v = _num(inp.get(key))
        if v is None or v < 1 or int(v) != v:
            raise ValueError(f"`{key}` is a slide number from 1, not {inp.get(key)!r}")
        return int(v) - 1

    def slide_op(kind, extra):
        settings = doc.get("settings") or ({"size": doc["size"]} if doc.get("size") else {})
        slide = dict(inp.get("slide") or {})
        for k in ("notes", "title", "transition"):
            if inp.get(k) is not None and k not in slide:
                slide[k] = inp[k]
        slide, resolved, err = _prepare_slide(slide, settings, root)
        if err:
            raise ValueError(err.removeprefix("Error: "))
        return {"op": kind, **extra, "slide": slide, "deck": resolved}

    try:
        if action == "add_slide":
            op = slide_op("slide_add", {"at": number("at")} if inp.get("at") is not None else {})
            what = "Slide added" + (f" at position {op['at'] + 1}" if "at" in op else " at the end")
        elif action == "update_slide":
            index = number("number")
            if inp.get("slide") is not None:
                op, what = slide_op("slide_update", {"index": index}), f"Slide {index + 1} rebuilt"
            else:
                meta = {k: inp[k] for k in ("notes", "title", "transition") if inp.get(k) is not None}
                if not meta:
                    return "Error: `update_slide` needs `slide` (the new slide) or `notes` / `title` / `transition`."
                op, what = {"op": "slide_meta", "index": index, **meta}, f"Slide {index + 1}'s {', '.join(meta)} updated"
        elif action == "move_slide":
            op = {"op": "slide_move", "index": number("number"), "to": number("to")}
            what = f"Slide {op['index'] + 1} moved to position {op['to'] + 1}"
        elif action == "duplicate_slide":
            op = {"op": "slide_duplicate", "index": number("number")}
            what = f"Slide {op['index'] + 1} duplicated (the copy is slide {op['index'] + 2})"
        else:
            op = {"op": "slide_delete", "index": number("number")}
            what = f"Slide {op['index'] + 1} deleted"
    except ValueError as e:
        return f"Error: {e}."
    try:
        r = await decks.apply_ops(root, name, [op], user_id=subject, preview=True)
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: {action} failed on {fig_rel} — {e}. Nothing was changed."
    count = len(r.get("slides") or [])
    ack = (f"{what}. {fig_rel} now has {count} slide{'s' if count != 1 else ''}; the deck viewer and "
           f"the exports beside it update in a few seconds." + _layout_check(r.get("lint"), "pptx"))
    for line in r.get("notes") or []:          # what the slide's layout had no room for
        ack += f" Note — {line}"
    for credit in credits:
        ack += f" {credit}."
    command = {"type": "ui", "action": "design_command", "path": fig_rel, "script": r.get("script"),
               "version": r.get("version")}   # what the file is now — an open editor's saves go on from it
    if intent := inp.get("intent"):
        command["intent"] = str(intent)[:80]
    await _to_the_room(root, fig_rel, command)   # people in the deck together get it once, from their room
    # Replayed live in an open editor, and the deck (re)opened in the viewer so the
    # user sees the change even when it wasn't showing.
    ui = [command, {"type": "ui", "action": "open_canvas", "path": f"designs/{name}.deck.json", "name": f"{name}.deck.json"}]
    blocks, total = [], 0
    for i, jpg in zip(r.get("touched") or [], r.get("previews") or []):
        if total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        blocks += [{"type": "text", "text": f"Slide {i + 1}:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if blocks:
        ack += " The changed slide is attached — check it matches the rest of the deck; fix it with update_slide if not."
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    return {"_model": ack, "_ui": ui}


_FILE_ACTIONS = ("export", "rename", "duplicate", "delete", "versions", "restore")


async def _exec_design_file(action, inp, workspace, name):
    """A saved design as another file (`export`), and a design as a file: `rename`,
    `duplicate`, `delete`, `versions`, `restore`. All of them work on designs/<name>.fig
    as it is saved — nothing is rendered again — and what is kept beside it (its images,
    slides, deck document: design/refresh.py `beside`) goes with it."""
    from cycls._agent import design, trash, versions
    from cycls._agent.design import refresh
    root, subject = pathlib.Path(workspace.root), getattr(workspace, "subject", None)
    rel = f"designs/{name}.fig"
    fig_path = root / rel
    if not fig_path.is_file():
        return (f"Error: {rel} doesn't exist — `{action}` works on a design that is saved. "
                f"The designs here: {_designs_there(root)}.")
    deck_path = fig_path.with_name(f"{name}.deck.json")
    shown = lambda r: {"type": "ui", "action": "open_canvas", "path": r, "name": r.rsplit("/", 1)[-1]}

    if action == "export":
        fmt = str(inp.get("format") or "").lower()
        if fmt not in _DESIGN_EXTS:
            return "Error: `export` needs `format` — pdf, pptx, png, jpg, webp or svg."
        fig = await asyncio.to_thread(fig_path.read_bytes)
        scale, page = inp.get("scale") or 2, str(inp.get("page") or "").strip() or None
        try:
            slides = int((json.loads(await asyncio.to_thread(deck_path.read_text, "utf-8")) or {}).get("slides") or 1) if deck_path.is_file() else 1
        except (OSError, ValueError, TypeError):
            slides = 1
        where = ""
        try:
            if page:
                data, pages, page_name = await design.export_page(fig, page, fmt=fmt, scale=scale, user_id=subject)
                place = next((n for n, p in enumerate(pages, 1) if p["name"] == page_name), 1)
                outs = [(f"designs/{refresh.page_file(name, place, fmt)}", data)]
                where = f" (page {json.dumps(page_name, ensure_ascii=False)})"
            elif slides > 1 and fmt not in _DECK_EXTS:
                images = await design.export(fig, fmt=fmt, scale=scale, user_id=subject, every=True)
                outs = [(f"designs/{name}-slide-{n}.{fmt}", d) for n, d in enumerate(images, 1)]
            else:
                outs = [(f"designs/{name}.{fmt}", await design.export(fig, fmt=fmt, scale=scale, user_id=subject))]
        except design.Unavailable as e:
            return f"Error: design unavailable — {e}"
        except Exception as e:
            return f"Error: couldn't export {rel} — {e}"
        if not outs:
            return f"Error: {rel} has nothing to export."
        for out_rel, data in outs:
            await _write_beside(root / out_rel, data)
        kb = sum(len(d) for _, d in outs) // 1024
        what = (f"{outs[0][0]}{where}" if len(outs) == 1 else f"{len(outs)} images, {outs[0][0]} … {outs[-1][0]}")
        return {"_model": (f"Exported {what} ({kb} KB) from the saved design {rel} — as it is now, with everything changed "
                           f"since it was made. Nothing was rendered again. The file is kept in step with the design from here on."),
                "_ui": shown(outs[0][0])}

    if action in ("rename", "duplicate"):
        asked = str(inp.get("new_name") or "").strip()
        if action == "rename" and not asked:
            return "Error: `rename` needs `new_name` — the design's new name."
        to = _safe_filename(asked or f"{name}-copy", "design").rsplit(".", 1)[0] or "design"
        if action == "duplicate":
            to = await asyncio.to_thread(_dedupe_design_name, root / "designs", to, "png")
        new_rel = f"designs/{to}.fig"
        if (root / new_rel).exists():
            return f"Error: {new_rel} is already a design — choose another `new_name`. Nothing was changed."
        if action == "rename":
            await asyncio.to_thread(fig_path.rename, root / new_rel)
            await asyncio.to_thread(versions.move, str(root), rel, new_rel)          # its history goes with it
        else:
            await asyncio.to_thread(lambda: (root / new_rel).write_bytes(fig_path.read_bytes()))
        went = await asyncio.to_thread(refresh.follow, str(root), rel, new_rel, action == "duplicate")
        if action == "duplicate":
            refresh.schedule(str(root), new_rel, subject, ensure=True)            # a copy with no image gets one
        opened = f"designs/{to}.deck.json" if (root / f"designs/{to}.deck.json").is_file() else new_rel
        beside_it = f" with what is kept beside it ({', '.join(p.name for p in went[:6])}{', …' if len(went) > 6 else ''})" if went else ""
        ack = (f"Renamed {rel} to {new_rel}{beside_it}. Its name is now \"{to}\" — use that in the next call."
               if action == "rename" else
               f"Copied {rel} to {new_rel}{beside_it}. The copy is \"{to}\": change it freely with Design edit — \"{name}\" stays as it is.")
        return {"_model": ack, "_ui": shown(opened)}

    if action == "delete":
        files = [fig_path, *(f for f, _ in await asyncio.to_thread(refresh.beside, str(root), rel))]
        gone = []
        for f in files:
            try:
                await asyncio.to_thread(trash.trash_path, str(root), f.relative_to(root).as_posix(), "agent", "delete")
                gone.append(f.name)
            except (OSError, ValueError) as e:
                return f"Error: couldn't delete {f.name} — {e}. Moved to the trash so far: {', '.join(gone) or 'nothing'}."
        return (f"Moved {rel} to the trash{f' with what was kept beside it ({len(gone) - 1} more files)' if len(gone) > 1 else ''}. "
                f"The user can restore it from Files › Trash; tell them so. Nothing else was deleted.")

    listed = await asyncio.to_thread(versions.listing, str(root), rel)             # newest first
    if action == "versions":
        if not listed:
            return f"{rel} has no earlier versions yet — one is kept each time it is edited or saved."
        lines = [f"{rel} — {len(listed)} earlier version{'s' if len(listed) != 1 else ''}, newest first:"]
        for n, v in enumerate(listed[:30], 1):
            why = {"agent": "an edit of yours", "save": "saved in the editor", "keep": "\"Keep mine\" in the editor",
                   "restore": "before a restore"}.get(str(v.get("reason")), str(v.get("reason") or ""))
            intent = f": {json.dumps(str(v['intent'])[:80], ensure_ascii=False)}" if v.get("intent") else ""
            lines.append(f"  {n}. {v.get('id')}  {str(v.get('at') or '')[:16].replace('T', ' ')}  by {v.get('by') or '?'} — {why}{intent}  "
                         f"({int(v.get('size') or 0) // 1024} KB)")
        if len(listed) > 30:
            lines.append(f"  … and {len(listed) - 30} older.")
        lines.append("Each is the design as it was BEFORE that change. Go back to one with "
                     "{\"action\": \"restore\", \"name\": …, \"version\": <its id, or its number here>} — what the design is now is kept first.")
        return "\n".join(lines)

    # restore
    want = inp.get("version")
    vid = None
    if isinstance(want, int) or (isinstance(want, str) and want.strip().isdigit()):
        place = int(want)
        vid = listed[place - 1]["id"] if 1 <= place <= len(listed) else None
    elif isinstance(want, str):
        vid = want.strip()
    data = await asyncio.to_thread(versions.read, str(root), rel, vid) if vid else None
    if data is None:
        return (f"Error: {rel} has no version {want!r} — `versions` lists the {len(listed)} it has "
                f"(an id, or a place from 1 = the newest). Nothing was changed.")
    from cycls._agent.design import live
    from cycls._agent.design.deck import lock
    from cycls._agent.design.store import write_fig
    async with lock(fig_path):
        version = await write_fig(str(root), rel, data, by="agent", reason="restore")
    refresh.schedule(str(root), rel, subject, ensure=True)
    await live.notify(str(root), rel, {"kind": "reload", "version": version})       # people in it open it again
    return {"_model": (f"Restored {rel} to its version {vid}. What it was a moment ago is kept as a version too (`versions`), so this "
                       f"can be undone. Its image re-exports in a few seconds; an open editor opens it again."),
            "_ui": {"type": "ui", "action": "design_command", "path": rel, "script": "", "reload": True, "version": version}}


async def _edits_since_render(workspace, name):
    """What was changed on a document's pages after it was last rendered — by hand in the
    editor, or by an `edit` — and so is not in its source. None: nothing was (or the
    document was rendered before its pages were kept, and it can't be told). A list:
    lines saying what — empty when only that it changed is known."""
    from cycls._agent import design
    from cycls._agent.design.store import version_of
    root = pathlib.Path(workspace.root)
    fig_rel = f"designs/{name}.fig"

    def read():
        try:
            deck = json.loads((root / f"designs/{name}.deck.json").read_text(encoding="utf-8"))
            current = (root / fig_rel).read_bytes()
        except (OSError, ValueError):
            return None, None, None
        rendered = deck.get("rendered") if isinstance(deck, dict) else None
        try:
            base = _rendered_copy(root, fig_rel).read_bytes()
        except OSError:
            base = None
        return rendered, current, base
    rendered, current, base = await asyncio.to_thread(read)
    if not rendered or current is None or version_of(current) == rendered:
        return None
    if base is None or version_of(base) != rendered:
        return []
    subject = getattr(workspace, "subject", None)
    try:
        before = (await design.outline(base, user_id=subject, full=True))["frames"]
        after = (await design.outline(current, user_id=subject, full=True))["frames"]
    except Exception:
        return []
    # (The editor may save a file again without changing a thing: its bytes differ, its pages don't.)
    return _page_changes(before, after) or None


def _edits_hold(name, changes):
    """Why a document was not rendered again, and what to do about it."""
    detail = "".join(f"\n- {line}" for line in changes) if changes else ""
    return (f"Error: not rendered — designs/{name}'s pages were changed after it was last rendered (by hand in the editor, or by an "
            f"`edit`), and those changes are not in its source: rendering it again lays every page out from the source, without them."
            f"{detail}\nDon't drop them silently. Put the wording changes into what you send (the section they are in — or the whole "
            f"document with `render` and \"replace\": true), tell the user which of the others can't be kept (a page laid out again "
            f"keeps no moved or restyled node), and call again with \"discard_edits\": true. The edited pages stay in History either way.")


def _seen_pages(deck_path):
    """The fingerprints of a document's pages as last rendered (kept in its deck document) —
    what the model has looked at — or [] when there are none to go by."""
    try:
        hashes = json.loads(deck_path.read_text(encoding="utf-8")).get("hashes")
    except (OSError, ValueError, AttributeError):
        return []
    return [h for h in hashes if isinstance(h, str)] if isinstance(hashes, list) else []


async def _render_document(inp, workspace, name):
    """A document (a report, a proposal — anything that flows over paper pages): rendered
    by the service to a PDF and its editable pages, saved as designs/<name>.pdf / .fig
    with a deck document (kind "document") that opens the page viewer; every page comes
    back to the model to QA. `replace` re-renders the same document — its earlier .fig
    kept as a version — instead of taking a new name."""
    from cycls._agent import design
    from cycls._agent.design import stock
    from cycls._agent.design.deck import lock
    from cycls._agent.design.store import write_fig
    from cycls._agent.design.store import version_of
    root, subject = pathlib.Path(workspace.root), getattr(workspace, "subject", None)
    designs = root / "designs"
    replacing = inp.get("replace") is True and (designs / f"{name}.fig").is_file() and (designs / f"{name}.deck.json").is_file()
    # Pages edited since the last render aren't in the source: they are not laid out again
    # without a word (the model folds what it can into what it sends, and says so).
    edited = await _edits_since_render(workspace, name) if replacing else None
    if edited is not None and inp.get("discard_edits") is not True:
        return _edits_hold(name, edited)
    credits, err = await stock.resolve(inp["spec"], workspace.root)
    if err:
        return err
    source = json.loads(json.dumps(inp["spec"]["document"]))       # as it was written (a stock photo: the file it became)
    spec, err, notes = await asyncio.to_thread(lambda: _prepare_document(inp["spec"], _load_brand(workspace.root), workspace.root))
    if err:
        return err
    try:
        # Rendered again: the pages the model has seen (their fingerprints, kept with the
        # document) are said, and only the ones that differ come back to be looked at.
        known = await asyncio.to_thread(_seen_pages, designs / f"{name}.deck.json") if replacing else []
        r = await design.render(spec, fmt="pdf", scale=2, user_id=subject, sheets=True, known=known)
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: the document didn't render — {e}"
    notes = [*notes, *(f"{c}." for c in credits), *r.notes]
    if edited is not None:
        notes.append("The pages changed after the last render were laid out again from the source; they are kept in History.")
    await asyncio.to_thread(designs.mkdir, parents=True, exist_ok=True)
    requested = name
    if not replacing:
        name = _dedupe_design_name(designs, name, "pdf")
    fig_rel, pdf_rel, deck_rel = f"designs/{name}.fig", f"designs/{name}.pdf", f"designs/{name}.deck.json"
    version = None
    if replacing:
        async with lock(root / fig_rel):
            version = await write_fig(workspace.root, fig_rel, r.fig, by="agent", reason="agent",
                                      intent=str(inp.get("intent") or "re-rendered")[:80])
    else:
        await asyncio.to_thread((root / fig_rel).write_bytes, r.fig)
    await asyncio.to_thread((root / pdf_rel).write_bytes, r.image)

    def keep_rendered():                                           # its pages as rendered: what a later change is told against
        try:
            copy = _rendered_copy(root, fig_rel)
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(r.fig)
        except OSError:
            pass
    await asyncio.to_thread(keep_rendered)
    count = max(len(r.slides), 1)
    deck = {"type": "cycls.deck", "version": 1, "kind": "document", "fig": fig_rel, "size": r.size or _PAPER["a4"],
            "slides": count, "exports": [pdf_rel], "document": source, "rendered": version_of(r.fig),
            **({"hashes": r.hashes} if r.hashes else {})}
    await asyncio.to_thread((root / deck_rel).write_text, json.dumps(deck, indent=2, ensure_ascii=False), "utf-8")
    note = f" (named '{name}' so it doesn't overwrite the existing '{requested}')" if name != requested else ""
    editor = bool(os.environ.get("DESIGN_EDITOR_URL"))
    ack = (f"Document {'re-rendered' if replacing else 'saved'} ({pdf_rel}, {count} pages, {len(r.image) // 1024} KB{note}). "
           f"It's OPEN in the page viewer ({deck_rel}): the user pages through it and downloads the PDF"
           f"{'; Edit opens the pages in the design editor' if editor else ''}. Its pages were laid out from the "
           f"content — so a small fix on one page (a word, a colour) is Design edit {{name: \"{name}\", ops}} with "
           f"`frame` = the page from 0, and anything that changes the length is made on the document: "
           f"update_section {{name: \"{name}\", number, section}} (or add_section / move_section / delete_section / "
           f"update_document) sends only what changes and renders it again in place — or this render again with "
           f"\"replace\": true. A page edited by hand does not re-flow the pages after it.")
    for line in notes:
        ack += " " + line
    ack += _layout_check(r.lint, "pptx")
    ui = {"type": "ui", "action": "open_canvas", "path": deck_rel, "name": f"{name}.deck.json"}
    if replacing:      # what is open shows the new pages: the viewer fetches them again, an editor re-opens the file
        again = {"type": "ui", "action": "design_command", "path": fig_rel, "script": "", "version": version, "reload": True}
        await _to_the_room(workspace.root, fig_rel, again)   # and so do the people who have it open together
        ui = [again, ui]
    blocks, total, held = [], 0, []
    numbers = r.preview_of if r.preview_of is not None else range(1, len(r.previews) + 1)
    for n, jpg in list(zip(numbers, r.previews))[:_DESIGN_QA_SLIDES]:
        if blocks and total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        held.append(n)
        blocks += [{"type": "text", "text": f"Page {n}:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if r.preview_of is not None:
        # Rendered again: the pages that differ from what the model last saw, and no others.
        if not held:
            return {"_model": ack + " No page changed from the last render: there is nothing to look at again.", "_ui": ui}
        rest = count - len(held)
        named = (f"Page {held[0]}" if len(held) == 1 else
                 "Pages " + ", ".join(map(str, held[:-1])) + f" and {held[-1]}")
        ack += (f" {named} changed and {'is' if len(held) == 1 else 'are'} attached; the other "
                f"{'page is as you last saw it' if rest == 1 else f'{rest} pages are as you last saw them'}. "
                "QA what changed before you present: no page ends in a large hole; nothing overlaps or is cut; "
                "names, numbers and dates are exactly right. If the content needs changing again, change it; then present.")
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    if not blocks:
        return {"_model": ack, "_ui": ui}
    shown = len(blocks) // 2
    # A long document: the pages after those, twelve to a contact sheet — all of it is seen.
    sheets = []
    for pages, jpg in zip(r.sheet_pages, r.sheets):
        if total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        sheets.append(pages)
        blocks += [{"type": "text", "text": f"Pages {pages[0]}–{pages[1]}, small:" if pages[1] > pages[0] else f"Page {pages[0]}, small:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if sheets:
        which = (f"Pages 1–{shown} are attached to read, and pages {sheets[0][0]}–{sheets[-1][1]} on {len(sheets)} contact "
                 f"sheet{'' if len(sheets) == 1 else 's'} (small — for how every page is laid out, not for its words)")
    else:
        which = (f"All {count} pages are attached" if shown >= count else
                 f"Pages 1–{shown} of {count} are attached (Design inspect lists the rest)")
    ack += (f" {which} — QA them before you present: the cover reads at a glance; no page ends in a large "
            "hole that a shorter or reordered block would close; every chart and table has its caption and "
            "says something; nothing overlaps or is cut; names, numbers and dates are exactly right. If the "
            "content needs changing, render again with \"replace\": true; then present.")
    return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}

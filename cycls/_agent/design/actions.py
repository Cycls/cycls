"""Design actions beyond a plain render: a deck's slides, a document's sections and render,
comments, and the file itself (export, rename, duplicate, delete, versions). Called from run.py."""
import asyncio, base64, json, pathlib
from .. import trash
from .brand import _load_brand
from .images import _DESIGN_QA_MAX, _DESIGN_QA_SLIDES
from .prepare import _num, _prepare_document, _prepare_slide, _settle_look
from .report import _layout_check, _page_changes
from .files import _DECK_EXTS, _DESIGN_EXTS, _designs_there, _free_design, _opened, _rendered_copy, _stem_of, _write_beside


_SLIDE_ACTIONS = ("add_slide", "update_slide", "move_slide", "duplicate_slide", "delete_slide")
_DOCUMENT_ACTIONS = ("add_section", "update_section", "move_section", "delete_section", "update_document")
_BLOCK_KINDS = ("lead", "p", "h2", "h3", "bullets", "numbered", "callout", "quote", "stats", "chart", "table", "image",
                "columns", "cards", "pairs", "note", "nodes", "break")


def _document_of(keep):
    """The source a document was rendered from (its file keeps it: `keep`), or None."""
    doc = keep.get("document") if isinstance(keep, dict) and keep.get("kind") == "document" else None
    return doc if isinstance(doc, dict) and isinstance(doc.get("sections"), list) else None


async def _document_source(workspace, fig_rel):
    """The source of document `fig_rel` → (source or None, error or None)."""
    from cycls._agent import design
    path = pathlib.Path(workspace.root) / fig_rel
    if not path.is_file():
        return None, None
    try:
        o = await design.outline(await asyncio.to_thread(path.read_bytes), user_id=getattr(workspace, "subject", None))
    except design.Unavailable as e:
        return None, f"Error: design unavailable — {e}"
    except Exception as e:
        return None, f"Error: couldn't read {fig_rel} — {e}"
    return _document_of(o.get("keep")), None


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
    """A section or document-level change, made on the kept source and re-rendered in place."""
    doc, err = await _document_source(workspace, f"{name}.fig")
    if err:
        return err
    if doc is None:
        return (f"Error: {name}.fig isn't a document — `{action}` works on a document you rendered "
                f"({{document: …}}); a deck's slides have add_slide / update_slide. The designs here: {_designs_there(workspace.root)}.")
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
                                   "intent": inp.get("intent") or intent, "discard_edits": inp.get("discard_edits")}, workspace, name, kept=True)


async def _to_the_room(root, rel, ui):
    """Hand an agent's change to the design's live room (docs/notes/design.md, "Together") so it
    is made once; marks `ui` `live` when delivered, and the chat's own editor then skips it."""
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


async def _comments_follow(workspace, what, *args):
    """Move or shelve a design's comments with it; best-effort, the file has already moved."""
    from . import comments
    if not comments.usable(workspace):
        return
    try:
        await getattr(comments, what)(workspace, *args)
    except Exception as e:
        from ..logs import log
        log("warn", message=f"comments did not {what} {args}: {type(e).__name__}: {e}")


async def _comments_note(workspace, rel, outline):
    """The open comments on the page `inspect` shows; "" when none or unreadable."""
    from . import comments
    from .report import _comments_on_page
    if not comments.usable(workspace):
        return ""
    try:
        doc, _ = await comments.read(workspace, rel)
    except Exception:
        return ""
    pages = [p.get("name") for p in outline.get("pages") or []]
    return _comments_on_page(comments.on_page(comments.open_threads(doc), outline.get("page"), pages), outline.get("frames") or [])


async def _exec_comments(inp, workspace, name):
    """List a design's comments, or reply to / resolve / reopen one by `number`, as the agent."""
    from . import comments
    from .report import _comments_listing
    rel = f"{name}.fig"
    if not (pathlib.Path(workspace.root) / rel).is_file():
        return f"Error: {rel} doesn't exist — `comments` are on a design that is saved. The designs here: {_designs_there(pathlib.Path(workspace.root))}."
    if not comments.usable(workspace):
        return "Error: comments aren't kept in this workspace."
    try:
        doc, _ = await comments.read(workspace, rel)
    except Exception as e:
        return f"Error: couldn't read the comments on {rel} — {e}"
    threads = comments.shown(doc)
    number, reply, resolve = inp.get("number"), inp.get("reply"), inp.get("resolve")
    if number is None:
        if reply is not None or resolve is not None:
            return "Error: `reply` and `resolve` are for one comment — pass its `number` (the # in the list)."
        return _comments_listing(rel, threads)
    thread = next((t for t in threads if t.get("n") == number), None)
    if thread is None:
        have = ", ".join(f"#{t['n']}" for t in threads) or "none"
        return f"Error: {rel} has no comment #{number} — it has {have}. Nothing was changed."
    if not (isinstance(reply, str) and reply.strip()) and not isinstance(resolve, bool):
        return (f"Error: nothing to do to comment #{number} — pass `reply` (your answer) and/or `resolve` "
                f"(true closes it, false opens it again). Without `number`, `comments` lists them.")
    me, did = comments.author("agent", agent=True), []
    try:
        if isinstance(reply, str) and reply.strip():
            await comments.change(workspace, rel, thread["id"], "reply", me, {"text": reply})
            did.append("replied to")
        if isinstance(resolve, bool):
            await comments.change(workspace, rel, thread["id"], "resolve" if resolve else "reopen", me)
            did.append("resolved" if resolve else "reopened")
    except comments.Refused as e:
        return f"Error: {e}" + (f" (Already done: {did[0]} it.)" if did else "")
    left = len([t for t in threads if not t.get("resolved") and t.get("n") != number]) + (0 if resolve else 1)
    said = " and ".join(did)
    return (f"{said[0].upper()}{said[1:]} comment #{number} on {rel}. The people working on it see that in the design. "
            f"{left} comment{'s' if left != 1 else ''} still open.")


async def _exec_slides(action, inp, workspace, name):
    """A deck's slide actions, run on the saved .fig through the service; slides number from 1."""
    from cycls._agent import design
    from cycls._agent.design import deck as decks
    root, subject = workspace.root, getattr(workspace, "subject", None)
    fig_rel = f"{name}.fig"
    fig_path = pathlib.Path(root) / fig_rel
    if not fig_path.is_file():
        return f"Error: {fig_rel} doesn't exist — slide actions work on a deck you rendered. The designs here: {_designs_there(root)}."
    settings = {}
    if action == "add_slide" or (action == "update_slide" and inp.get("slide") is not None):
        try:   # what the deck's added slides are laid out with, as its file keeps it
            settings, _ = await decks.settings(await asyncio.to_thread(fig_path.read_bytes), user_id=subject)
        except design.Unavailable as e:
            return f"Error: design unavailable — {e}"
        except Exception as e:
            return f"Error: couldn't read {fig_rel} — {e}"
    credits = []   # {"stock": "…"}, {"asset": "…"} pictures → saved workspace files
    if isinstance(inp.get("slide"), dict):
        from cycls._agent.design import assets
        credits, err = await assets.named(inp["slide"], root, subject)
        if err:
            return err

    def number(key):
        v = _num(inp.get(key))
        if v is None or v < 1 or int(v) != v:
            raise ValueError(f"`{key}` is a slide number from 1, not {inp.get(key)!r}")
        return int(v) - 1

    def slide_op(kind, extra):
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
        r = await decks.apply_ops(root, fig_rel, [op], user_id=subject, preview=True)
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: {action} failed on {fig_rel} — {e}. Nothing was changed."
    count = len(r.get("slides") or [])
    ack = (f"{what}. {fig_rel} now has {count} slide{'s' if count != 1 else ''}; the canvas shows it." + _layout_check(r.get("lint"), "pptx"))
    for line in r.get("notes") or []:          # what the slide's layout had no room for
        ack += f" Note — {line}"
    for credit in credits:
        ack += f" {credit}."
    command = {"type": "ui", "action": "design_command", "path": fig_rel, "script": r.get("script"),
               "version": r.get("version")}   # an open editor's later saves base on this version
    if intent := inp.get("intent"):
        command["intent"] = str(intent)[:80]
    await _to_the_room(root, fig_rel, command)
    # (re)open the deck so the change shows even when it wasn't open
    ui = [command, _opened(fig_rel, "")[1]]
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
    """File actions on the saved `<name>.fig`, never re-rendered."""
    from cycls._agent import design, trash, versions
    from cycls._agent.design import refresh
    root, subject = pathlib.Path(workspace.root), getattr(workspace, "subject", None)
    rel = f"{name}.fig"
    fig_path = root / rel
    if not fig_path.is_file():
        return (f"Error: {rel} doesn't exist — `{action}` works on a design that is saved. "
                f"The designs here: {_designs_there(root)}.")
    shown = lambda r: {"type": "ui", "action": "open_canvas", "path": r, "name": r.rsplit("/", 1)[-1]}

    if action == "export":
        fmt = str(inp.get("format") or "").lower()
        if fmt not in _DESIGN_EXTS:
            return "Error: `export` needs `format` — pdf, pptx, png, jpg, webp or svg."
        fig = await asyncio.to_thread(fig_path.read_bytes)
        scale, page = inp.get("scale") or 2, str(inp.get("page") or "").strip() or None
        where = ""
        try:
            if page:
                data, pages, page_name = await design.export_page(fig, page, fmt=fmt, scale=scale, user_id=subject)
                outs = [(f"{name}-{page_name}.{fmt}", data)]
                where = f" (page {json.dumps(page_name, ensure_ascii=False)})"
            elif fmt not in _DECK_EXTS and len((await design.outline(fig, user_id=subject))["frames"]) > 1:
                images = await design.export(fig, fmt=fmt, scale=scale, user_id=subject, every=True)
                outs = [(f"{name}-slide-{n}.{fmt}", d) for n, d in enumerate(images, 1)]
            else:
                outs = [(f"{name}.{fmt}", await design.export(fig, fmt=fmt, scale=scale, user_id=subject))]
        except design.Unavailable as e:
            return f"Error: design unavailable — {e}"
        except Exception as e:
            return f"Error: couldn't export {rel} — {e}"
        if not outs:
            return f"Error: {rel} has nothing to export."
        # beside the design; an earlier copy of the same name goes to the trash first (restorable), not to `-2`
        replaced = []
        for out_rel, _ in outs:
            if (root / out_rel).is_file():
                await asyncio.to_thread(trash.trash_path, str(root), out_rel, "agent", "replace")
                replaced.append(out_rel)
        for out_rel, data in outs:
            await _write_beside(root / out_rel, data)
        kb = sum(len(d) for _, d in outs) // 1024
        what = (f"{outs[0][0]}{where}" if len(outs) == 1 else f"{len(outs)} images, {outs[0][0]} … {outs[-1][0]}")
        old = (f" The earlier {'copy' if len(replaced) == 1 else f'{len(replaced)} files'} of that name went to the trash." if replaced else "")
        return {"_model": (f"Exported {what} ({kb} KB) from the saved design {rel} — as it is now, with everything changed "
                           f"since it was made. It is a copy: a later change to the design doesn't change it.{old}"),
                "_ui": shown(outs[0][0])}

    if action in ("rename", "duplicate"):
        asked = str(inp.get("new_name") or "").strip()
        if action == "rename" and not asked:
            return "Error: `rename` needs `new_name` — the design's new name."
        to = _stem_of(asked or f"{name}-copy", rel.rsplit("/", 1)[0] if "/" in rel else "")   # a bare name stays in its folder
        if action == "duplicate":
            to = await asyncio.to_thread(_free_design, root, to)
        new_rel = f"{to}.fig"
        if (root / new_rel).exists():
            return f"Error: {new_rel} is already a design — choose another `new_name`. Nothing was changed."
        await asyncio.to_thread((root / new_rel).parent.mkdir, parents=True, exist_ok=True)
        if action == "rename":
            await asyncio.to_thread(fig_path.rename, root / new_rel)
            await asyncio.to_thread(versions.move, str(root), rel, new_rel)
            await _comments_follow(workspace, "move", rel, new_rel)
        else:
            await asyncio.to_thread(lambda: (root / new_rel).write_bytes(fig_path.read_bytes()))
        ack = (f"Renamed {rel} to {new_rel}. Its name is now \"{to}\" — use that in the next call."
               if action == "rename" else
               f"Copied {rel} to {new_rel}. The copy is \"{to}\": change it freely with Design edit — \"{name}\" stays as it is.")
        return {"_model": ack, "_ui": _opened(new_rel, "")[1]}

    if action == "delete":
        try:
            meta = await asyncio.to_thread(trash.trash_path, str(root), rel, "agent", "delete")
        except (OSError, ValueError) as e:
            return f"Error: couldn't delete {rel} — {e}. Nothing was deleted."
        await _comments_follow(workspace, "shelve", rel, meta["id"])   # so a new design of this name starts with no comments
        return (f"Moved {rel} to the trash. The user can restore it from Files › Trash; tell them so. Nothing else was deleted.")

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
    refresh.schedule(str(root), rel, subject)
    await live.notify(str(root), rel, {"kind": "reload", "version": version})
    return {"_model": (f"Restored {rel} to its version {vid}. What it was a moment ago is kept as a version too (`versions`), so this "
                       f"can be undone. An open editor opens it again."),
            "_ui": {"type": "ui", "action": "design_command", "path": rel, "script": "", "reload": True, "version": version}}


async def _edits_since_render(workspace, fig_rel):
    """Page changes since a document's last render (by hand or `edit`), not in its source: None if
    none or unknowable, else lines saying what — empty when only that it changed is known."""
    from cycls._agent import design
    root = pathlib.Path(workspace.root)

    def read():
        try:
            return (root / fig_rel).read_bytes(), _rendered_copy(root, fig_rel).read_bytes()
        except OSError:
            return None, None
    current, base = await asyncio.to_thread(read)
    if current is None or base is None or current == base:
        return None
    subject = getattr(workspace, "subject", None)
    try:
        before = (await design.outline(base, user_id=subject, full=True))["frames"]
        after = (await design.outline(current, user_id=subject, full=True))["frames"]
    except Exception:
        return []
    # an editor re-save changes the bytes, not the pages
    return _page_changes(before, after) or None


def _edits_hold(name, changes):
    """Why a document was not rendered again, and what to do about it."""
    detail = "".join(f"\n- {line}" for line in changes) if changes else ""
    return (f"Error: not rendered — {name}.fig's pages were changed after it was last rendered (by hand in the editor, or by an "
            f"`edit`), and those changes are not in its source: rendering it again lays every page out from the source, without them."
            f"{detail}\nDon't drop them silently. Put the wording changes into what you send (the section they are in — or the whole "
            f"document with `render` and \"replace\": true), tell the user which of the others can't be kept (a page laid out again "
            f"keeps no moved or restyled node), and call again with \"discard_edits\": true. The edited pages stay in History either way.")


def _seen_pages(root, fig_rel):
    """Hashes of a document's pages as last rendered (what the model has seen), or []."""
    try:
        hashes = json.loads(_rendered_copy(root, fig_rel, "json").read_text(encoding="utf-8")).get("hashes")
    except (OSError, ValueError, AttributeError):
        return []
    return [h for h in hashes if isinstance(h, str)] if isinstance(hashes, list) else []


async def _render_document(inp, workspace, name, kept=False):
    """Render a document to `<name>.fig`, its source kept in it, pages back for QA. `replace` re-renders
    under the same name, keeping the earlier .fig as a version. `kept`: the kept source changed by a
    section action — its look stays what it was (none: classic)."""
    from cycls._agent import design
    from cycls._agent.design import assets, refresh
    from cycls._agent.design.deck import lock
    from cycls._agent.design.store import write_fig
    root, subject = pathlib.Path(workspace.root), getattr(workspace, "subject", None)
    replacing = inp.get("replace") is True and (root / f"{name}.fig").is_file()
    # hand edits since the last render aren't in the source: held until discard_edits
    edited = await _edits_since_render(workspace, f"{name}.fig") if replacing else None
    if edited is not None and inp.get("discard_edits") is not True:
        return _edits_hold(name, edited)
    credits, err = await assets.named(inp["spec"], workspace.root, subject)
    if err:
        return err
    looked = []
    if not kept:
        # a new document without a look takes its theme's, written into the source it keeps (on a copy:
        # the call's own input stays as it came)
        spec_in = dict(inp["spec"])
        doc_in = spec_in["document"] = dict(spec_in["document"])
        if doc_in.get("look") is None and spec_in.get("look") is not None:
            doc_in["look"] = spec_in.pop("look")
        if err := _settle_look(doc_in, "document", looked):
            return err
        inp = {**inp, "spec": spec_in}
    source = json.loads(json.dumps(inp["spec"]["document"]))       # as written, stock photos and assets resolved
    spec, err, notes = await asyncio.to_thread(lambda: _prepare_document(inp["spec"], _load_brand(workspace.root), workspace.root))
    if err:
        return err
    try:
        # a re-render sends the seen page hashes; only changed pages come back
        known = await asyncio.to_thread(_seen_pages, root, f"{name}.fig") if replacing else []
        r = await design.render(spec, fmt="png", scale=1, user_id=subject, sheets=True, known=known,
                                keep={"kind": "document", "document": source})
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: the document didn't render — {e}"
    notes = [*looked, *notes, *(f"{c}." for c in credits), *r.notes]
    if edited is not None:
        notes.append("The pages changed after the last render were laid out again from the source; they are kept in History.")
    requested = name
    if not replacing:
        name = await asyncio.to_thread(_free_design, root, name)
    fig_rel = f"{name}.fig"
    await asyncio.to_thread((root / fig_rel).parent.mkdir, parents=True, exist_ok=True)
    version = None
    if replacing:
        async with lock(root / fig_rel):
            version = await write_fig(workspace.root, fig_rel, r.fig, by="agent", reason="agent",
                                      intent=str(inp.get("intent") or "re-rendered")[:80])
    else:
        await asyncio.to_thread((root / fig_rel).write_bytes, r.fig)
    refresh.schedule(workspace.root, fig_rel, subject)

    def keep_rendered():                                           # what _edits_since_render diffs against, and what was seen
        try:
            copy = _rendered_copy(root, fig_rel)
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(r.fig)
            _rendered_copy(root, fig_rel, "json").write_text(json.dumps({"hashes": r.hashes}), encoding="utf-8")
        except OSError:
            pass
    await asyncio.to_thread(keep_rendered)
    count = max(len(r.slides), 1)
    note = f", named '{name}' so it doesn't overwrite the existing '{requested}'" if name != requested else ""
    ack, ui = _opened(fig_rel, f"Document {'re-rendered' if replacing else 'saved'} ({count} pages{note})")
    ack += (f" Its pages were laid out from the content — so a small fix on one page (a word, a colour) is Design edit "
            f"{{name: \"{name}\", ops}} with `frame` = the page from 0, and anything that changes the length is made on the "
            f"document: update_section {{name: \"{name}\", number, section}} (or add_section / move_section / delete_section / "
            f"update_document) sends only what changes and renders it again in place — or this render again with "
            f"\"replace\": true. A page edited by hand does not re-flow the pages after it.")
    for line in notes:
        ack += " " + line
    ack += _layout_check(r.lint, "pptx")
    if replacing:      # an open viewer refetches, an open editor reloads
        again = {"type": "ui", "action": "design_command", "path": fig_rel, "script": "", "version": version, "reload": True}
        await _to_the_room(workspace.root, fig_rel, again)
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
        # a re-render: only the pages that changed
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
    # the remaining pages on contact sheets, twelve a sheet
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

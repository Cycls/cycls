"""Designs, as the app is served them and as it changes them.

The helpers turn a saved design into what a viewer needs — its slides, its exports, each
cached against the `.fig` it was made from — and `design_router` holds the routes that
act on a design: a deck's slides changed in the viewer (/deck), a new design, an export
written beside it, the live room of a design open together (/design/*), the workspace's
brand kit (/brand) and a design's earlier versions (/versions). A design's own bytes are
read and saved by the files routes (routers.py), which ask these helpers for `?as=…`."""
import asyncio, base64, hashlib, json, re, shutil, tempfile, unicodedata, uuid, zipfile
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from cycls._app.db import Workspace
from cycls._agent.design import refresh as design_refresh
from cycls._agent.web.shared import _NO_CACHE, _free_rel, _safe_path, resolve_path


# Designs as decks. A multi-frame render writes `designs/<name>.deck.json` (the deck
# document) beside its `.fig`; either one previews slide by slide (?as=slides — a
# manifest the deck viewer shows and presents) and exports the whole deck on demand
# (?as=pptx / ?as=pdf, or ?as=images: every slide as a PNG, zipped — what a carousel
# is posted from; ?as=png: the first frame, a single design's picture), through the
# cycls-design service. Cached like the office
# renders, keyed by the .fig's path + mtime + size — so an edit (the editor's
# auto-save, an agent's `edit`) is a fresh render.
#
# A design's PAGES are its variants (a post, a story, a banner of one piece of work),
# and each of these is ONE page: `&page=<its name>`, the first when absent. The slides
# manifest lists them all (`pages: [{name, frames}]`) and says which it is (`page`).
_DESIGN_CACHE = ".cache/design"


_DESIGN_AS = ("slides", "pptx", "pdf", "images", "png")


def _page_param(raw):
    """A request's `page` — a page's name — or None (the first page)."""
    return raw.strip()[:80] if isinstance(raw, str) and raw.strip() else None


def _page_tag(page):
    """What a page adds to a cache file's name (nothing for the first page)."""
    return f"-p{hashlib.sha1(page.encode('utf-8')).hexdigest()[:10]}" if page else ""


def _page_label(page):
    """A page's name as part of a file name."""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", page).strip(" .-") or "page"


def _design_error(e):
    """A design-service failure → the HTTP error: a page that isn't there is the
    caller's (it was renamed or removed), anything else the service's."""
    missing = str(e).startswith("there is no page")
    return HTTPException(404 if missing else 502, str(e) if missing else f"Couldn't render the design: {e}")


def _design_doc(name):
    """A file the deck routes serve: a deck document or a design (.fig)."""
    n = name.lower()
    return n.endswith(".deck.json") or n.endswith(".fig")


def _design_file_name(name):
    """A new design's file name: NFC, no folders or `.fig`, letters (any script),
    digits, spaces, `-_.()` — else `untitled`."""
    name = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"\.fig$", "", name.strip(), flags=re.I)
    name = re.sub(r"[^\w\-. ()]+", "-", name).strip(" .-")[:60].strip(" .-")
    return name or "untitled"


def _deck_fig(root, src):
    """The .fig behind `src` — itself, or the one its deck document names (a
    workspace path that must stay inside the workspace) — and the deck's size when
    the document states it. Raises FileNotFoundError / ValueError."""
    if src.name.lower().endswith(".fig"):
        return src, None
    try:
        doc = json.loads(src.read_text("utf-8"))
    except (OSError, ValueError):
        raise ValueError("not a deck document")
    fig = doc.get("fig") if isinstance(doc, dict) else None
    if not isinstance(fig, str) or not fig.lower().endswith(".fig"):
        raise ValueError("the deck document names no .fig")
    target = resolve_path(root, fig)
    if not target.is_file():
        raise FileNotFoundError(fig)
    size = doc.get("size")
    return target, size if isinstance(size, list) and len(size) == 2 else None


def _design_cache_key(root, fig):
    st = fig.stat()
    stem = hashlib.sha1(fig.relative_to(root).as_posix().encode("utf-8")).hexdigest()[:16]
    return stem, f"{st.st_mtime_ns}-{st.st_size}"


def _poll_of(raw):
    """A slide's poll (the service keeps it as JSON on the frame) → a dict, or None."""
    try:
        poll = json.loads(raw) if isinstance(raw, str) and raw else None
    except ValueError:
        return None
    return poll if isinstance(poll, dict) and poll.get("question") and isinstance(poll.get("options"), list) else None


async def _design_slides(root, src, user_id, page=None):
    """A cached slide render of one page of a design — {count, slides: [data-URI
    JPEGs], sizes, names, titles, notes, transitions, fig, pages, page}. Raises
    design.Unavailable (no service), FileNotFoundError / ValueError (not a deck)."""
    from cycls._agent import design
    root = Path(root).resolve()
    fig, size = await asyncio.to_thread(_deck_fig, root, src)
    stem, key = _design_cache_key(root, fig)
    cache_dir = root / _DESIGN_CACHE
    kind = ""
    if src.name.lower().endswith(".deck.json"):      # a document's deck says so: the viewer offers its PDF first
        try:
            kind = str(json.loads(await asyncio.to_thread(src.read_text, "utf-8")).get("kind") or "")
        except (OSError, ValueError, AttributeError):
            kind = ""
    # (Asked for through its deck document, the manifest carries the kind: cached apart
    # from the same slides asked for through the .fig.)
    dst = cache_dir / f"{stem}-{key}{_page_tag(page)}{'-' + kind if kind in ('document',) else ''}.slides.json"
    if dst.exists():
        return dst
    # ~1920px on the long side: sharp on the stage and in present mode.
    scale = min(2, max(1, 1920 / max(size))) if size and all(isinstance(v, (int, float)) and v > 0 for v in size) else 1
    s = await design.slides(await asyncio.to_thread(fig.read_bytes), scale=scale, user_id=user_id, page=page)
    mime = "image/png" if s["format"] == "png" else "image/jpeg"
    meta = s["meta"] + [{}] * (len(s["images"]) - len(s["meta"]))
    payload = json.dumps({
        "count": len(s["images"]),
        "slides": [f"data:{mime};base64," + base64.b64encode(i).decode("ascii") for i in s["images"]],
        "sizes": s["sizes"],
        "names": [m.get("name") or "" for m in meta],
        "titles": [m.get("title") or "" for m in meta],
        "notes": [m.get("notes") or "" for m in meta],
        "transitions": [m.get("transition") or "" for m in meta],
        "polls": [_poll_of(m.get("poll")) for m in meta],
        "fig": fig.relative_to(root).as_posix(),
        "pages": s.get("pages") or [],
        "page": s.get("page") or "",
        **({"kind": kind} if kind else {}),
    })
    return await asyncio.to_thread(_write_design_cache, cache_dir, stem, key, "slides.json", dst, payload.encode("utf-8"))


def _write_design_cache(cache_dir, stem, key, ext, dst, data):
    """Write one cached render of a design. What an older save of the design left goes;
    the same save's other renders — its other pages — stay."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for old in cache_dir.glob(f"{stem}-*.{ext}"):
            if old.name.startswith(f"{stem}-{key}"):
                continue
            try: old.unlink()
            except OSError: pass
        tmp = cache_dir / f".{stem}-{uuid.uuid4().hex}.part"
        tmp.write_bytes(data)
        tmp.replace(dst)
        return dst
    except OSError:
        tmp = Path(tempfile.gettempdir()) / f"design-{uuid.uuid4().hex}.{ext}"
        tmp.write_bytes(data)
        return tmp


def _zip_slides(stem, pngs):
    """Every slide's PNG as `<stem>-slide-<n>.png` — the names a carousel render writes."""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:       # PNGs don't deflate
        for n, png in enumerate(pngs, 1):
            zf.writestr(f"{stem}-slide-{n}.png", png)
    return buf.getvalue()


async def _design_export(root, src, fmt, user_id, page=None):
    """One page of the design behind `src` as `fmt` (pptx / pdf: its whole deck; images:
    a zip of every slide's PNG; `png`: its first frame) — cached → (path, the download
    name). `page` is the page's name; the first when absent. Same errors as
    _design_slides."""
    from cycls._agent import design
    root = Path(root).resolve()
    fig, _ = await asyncio.to_thread(_deck_fig, root, src)
    stem, key = _design_cache_key(root, fig)
    cache_dir = root / _DESIGN_CACHE
    ext = "zip" if fmt == "images" else fmt
    dst = cache_dir / f"{stem}-{key}{_page_tag(page)}.{ext}"
    base = f"{fig.stem}-{_page_label(page)}" if page else fig.stem   # a named page's download says which
    name = f"{base}.{ext}"
    if dst.exists():
        return dst, name
    data = await asyncio.to_thread(fig.read_bytes)
    if fmt == "images":
        data = _zip_slides(base, await design.export(data, fmt="png", user_id=user_id, every=True, page=page))
    else:
        data = await design.export(data, fmt=fmt, user_id=user_id, page=page)
    return await asyncio.to_thread(_write_design_cache, cache_dir, stem, key, ext, dst, data), name


async def _new_slide_op(root, name, after, title, text, user_id):
    """The deck viewer's "Add slide" as a service op: a slide to start from, after slide
    `after` (from 1; 0: first; None: last). A deck made of layouts gets one laid out as
    its own are — a title and a line of text in the deck's theme; a hand-built deck has
    no theme to follow, so it gets a blank slide the colour of the slide before it, with
    its title in a colour that shows on it. Raises FileNotFoundError, design.Unavailable,
    ValueError (the slide couldn't be prepared)."""
    from cycls._agent import design
    from cycls._agent.design import deck as decks
    from cycls._agent.design.brand import _norm_hex
    from cycls._agent.design.prepare import _prepare_slide
    fig_path, _, deck_path, _ = decks.paths(root, name)
    if not await asyncio.to_thread(fig_path.is_file):
        raise FileNotFoundError(fig_path.name)
    doc = await asyncio.to_thread(decks.read_doc, deck_path)
    title, text = (title or "").strip() or "New slide", (text or "").strip() or "Add your text"
    if isinstance(doc.get("settings"), dict):
        settings = doc["settings"]
        slide = {"layout": "bullets", "title": title, "bullets": [text]}
    else:
        frames = await design.inspect(await asyncio.to_thread(fig_path.read_bytes), user_id=user_id)
        near = frames[min(max((after or len(frames)) - 1, 0), len(frames) - 1)] if frames else {}
        size = near.get("size") or doc.get("size") or [1920, 1080]
        fill = _norm_hex(near.get("fill") or "") or "#ffffff"
        r, g, b = (int(fill[i:i + 2], 16) for i in (1, 3, 5))
        ink = "#ffffff" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 140 else "#111111"
        settings = {"size": size}
        slide = {"fill": fill, "title": title, "nodes": [
            {"type": "text", "id": "title", "x": round(size[0] * 0.08), "y": round(size[1] * 0.12), "w": round(size[0] * 0.84),
             "size": max(24, round(size[1] * 0.07)), "weight": "Bold", "color": ink, "text": title}]}
    slide, resolved, err = _prepare_slide(slide, settings, root)
    if err:
        raise ValueError(err.removeprefix("Error: "))
    return {"op": "slide_add", **({"at": after} if after is not None else {}), "slide": slide, "deck": resolved}


async def _design_response(root, src, as_, user_id, page=None):
    """?as=slides|pptx|pdf|images|png[&page=<name>] on a deck document or a .fig → the
    response."""
    from cycls._agent import design
    page = _page_param(page)
    try:
        if as_ == "slides":
            return FileResponse(await _design_slides(root, src, user_id, page),
                                media_type="application/json", headers=_NO_CACHE)
        path, name = await _design_export(root, src, as_, user_id, page)
        return FileResponse(path, filename=name, headers=_NO_CACHE)
    except design.Unavailable as e:
        raise HTTPException(415, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, f"The deck's design file is missing: {e}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise _design_error(e)


def design_router(ws_dep, user_dep, changed):
    """The routes that act on a design. `changed(root)` tells the files catalog that
    something was written under a workspace root."""
    r = APIRouter()

    @r.post("/deck/{path:path}")
    async def deck_op(path: str, request: Request, ws: Workspace = ws_dep):
        """The deck viewer's own slide changes on a deck under designs/ (its deck document
        or .fig), run on the saved .fig through the design service like the agent's slide
        actions. Slides from 1:
          {op: "move" | "duplicate" | "delete", number, to?}
          {op: "add", number?, title?, text?}   a slide to start from, after slide `number`
                                                (0: first; absent: last) → `added`: its number
          {op: "notes", number, notes}          that slide's speaker notes ("" clears them)"""
        from cycls._agent import design
        from cycls._agent.design import deck as decks
        m = re.fullmatch(r"designs/([^/]+?)(?:\.deck\.json|\.fig)", path)
        if not m:
            raise HTTPException(404, "Not a deck")
        _safe_path(ws.root, path)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Expected {op, number, …}")
        kind, number, to = body.get("op"), body.get("number"), body.get("to")
        whole = lambda v, least: isinstance(v, int) and not isinstance(v, bool) and v >= least
        words = lambda v, most: v is None or (isinstance(v, str) and len(v) <= most)
        added = None
        try:
            if kind == "add":
                if (number is not None and not whole(number, 0)) or not words(body.get("title"), 300) or not words(body.get("text"), 300):
                    raise HTTPException(400, "Expected {op: add, number?, title?, text?} — `number` is the slide it comes after")
                op = await _new_slide_op(ws.root, m.group(1), number, body.get("title"), body.get("text"), ws.subject)
            elif kind == "notes":
                notes = body.get("notes")
                if not whole(number, 1) or not isinstance(notes, str) or len(notes) > 20000:
                    raise HTTPException(400, "Expected {op: notes, number, notes} with slides from 1")
                op = {"op": "slide_meta", "index": number - 1, "notes": notes.strip()}
            elif kind in ("move", "duplicate", "delete") and whole(number, 1) and (kind != "move" or whole(to, 1)):
                op = {"op": f"slide_{kind}", "index": number - 1, **({"to": to - 1} if kind == "move" else {})}
            else:
                raise HTTPException(400, "Expected {op: move|duplicate|delete|add|notes, number, to?} with slides from 1")
            r = await decks.apply_ops(ws.root, m.group(1), [op], user_id=ws.subject, by="user")
            if kind == "add":
                added = op["at"] + 1 if "at" in op else len(r.get("slides") or [])
        except ValueError as e:
            raise HTTPException(422, str(e))
        except FileNotFoundError:
            raise HTTPException(404, "The deck's design file is missing")
        except design.Unavailable as e:
            raise HTTPException(415, str(e))
        except RuntimeError as e:
            raise HTTPException(422, str(e))
        # The slides were changed in the file, beside any editors open on it: the people
        # in the deck together open it again (this one's own editor is re-opened by the app).
        from cycls._agent.design import live
        await live.notify(ws.root, f"designs/{m.group(1)}.fig", {"kind": "reload", "version": r.get("version")})
        return {"ok": True, "slides": len(r.get("slides") or []), **({"added": added} if added else {})}

    @r.post("/design/new")
    async def new_design(request: Request, ws: Workspace = ws_dep):
        """A blank design in the workspace — Cycls's "New design" (the canvas +, the
        Files panel, File › New design in the editor). {name?, size?: a preset
        ("square", "story", …) or [w, h], background?: "#hex"} → one frame, saved as
        designs/<name>.fig with its .png beside it, like a rendered design: the editor
        opens it, the refresh keeps the image current, the agent edits it by name."""
        from cycls._agent import design
        from cycls._agent.design.brand import _norm_hex
        from cycls._agent.design.files import _dedupe_design_name
        from cycls._agent.design.prepare import _DESIGN_SIZES
        if not design.configured():
            raise HTTPException(503, "The design service isn't set up")
        body = await request.json() if int(request.headers.get("content-length") or 0) else {}
        if not isinstance(body, dict):
            raise HTTPException(400, "Expected {name?, size?, background?}")
        size = body.get("size") or "square"
        if isinstance(size, str):
            if size not in _DESIGN_SIZES:
                raise HTTPException(400, f"size is one of {', '.join(_DESIGN_SIZES)} or [w, h]")
            wh = list(_DESIGN_SIZES[size])
        elif (isinstance(size, list) and len(size) == 2
              and all(isinstance(v, int) and not isinstance(v, bool) and 16 <= v <= 4096 for v in size)):
            wh = size
        else:
            raise HTTPException(400, "size is a preset or [w, h] in pixels, 16–4096")
        background = _norm_hex(body.get("background") or "#ffffff")
        if not background:
            raise HTTPException(400, "background is a hex colour")
        try:
            out = await design.render({"size": wh, "fill": background, "nodes": []}, fmt="png", scale=1,
                                      user_id=ws.subject)
        except design.Unavailable as e:
            raise HTTPException(503, str(e))
        except RuntimeError as e:
            raise HTTPException(422, str(e))
        designs = Path(ws.root) / "designs"
        await asyncio.to_thread(designs.mkdir, parents=True, exist_ok=True)
        base = _dedupe_design_name(designs, _design_file_name(body.get("name")), "png")
        for suffix, data in ((".fig", out.fig), (".png", out.image)):
            tmp = designs / f".{base}{suffix}.part"
            await asyncio.to_thread(tmp.write_bytes, data)
            await asyncio.to_thread(tmp.replace, designs / f"{base}{suffix}")
        changed(ws.root)
        return {"path": f"designs/{base}.fig", "name": base, "size": wh}

    @r.post("/design/export")
    async def export_design(request: Request, ws: Workspace = ws_dep):
        """A design as a file beside it — `{path, format: "pdf" | "png", page?}` →
        `{path}`: the editor's File › Export › PDF. Rendered by the design service (the
        export behind `?as=`: every slide of the page, with its own fonts), not in the
        browser, where the editor's PDF embeds no fonts. Under designs/ it is
        `<name>.<format>`, the design's own image — replaced, and kept in step by the
        refresh from then on; anywhere else it takes a free name, never a file that's
        there. `page` names the page exported (the first when absent): a later page is
        `<name>-page-<its place>.<format>`, kept in step the same way."""
        from cycls._agent import design
        body = await request.json()
        fmt = str(body.get("format") or "pdf")
        if fmt not in ("pdf", "png"):
            raise HTTPException(400, "format is pdf or png")
        src = _safe_path(ws.root, str(body.get("path") or ""))
        if src.suffix.lower() != ".fig" or not src.is_file():
            raise HTTPException(404, "No such design")
        page, place, made, data = _page_param(body.get("page")), 1, None, None
        try:
            if page:   # its place names the file, so the service is asked (not the cache)
                data, pages, name = await design.export_page(await asyncio.to_thread(src.read_bytes), page,
                                                             fmt=fmt, user_id=ws.subject)
                place = next((n for n, p in enumerate(pages, 1) if p["name"] == name), 1)
            else:
                made, _ = await _design_export(ws.root, src, fmt, ws.subject)
        except design.Unavailable as e:
            raise HTTPException(415, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except RuntimeError as e:
            raise _design_error(e)
        root = Path(ws.root).resolve()
        rel = src.with_name(design_refresh.page_file(src.stem, place, fmt)).relative_to(root).as_posix()
        if not rel.startswith("designs/"):
            rel = _free_rel(root, rel)
        out = root / rel
        tmp = out.with_name(f".{out.name}.part")
        if data is None:
            await asyncio.to_thread(shutil.copyfile, made, tmp)
        else:
            await asyncio.to_thread(tmp.write_bytes, data)
        await asyncio.to_thread(tmp.replace, out)
        changed(ws.root)
        return {"path": rel}

    @r.get("/design/live")
    async def design_live(path: str, ws: Workspace = ws_dep, user: Any = user_dep):
        """The live room of a design, for someone about to open it in the editor:
        `{live: {room, url, ticket, epoch}}` — the room everyone this workspace lets in
        meets in, the relay's address, this person's pass, and the version of the file
        as it is now — or `{live: null}` where a design opens alone: no relay set up
        (DESIGN_LIVE_URL), or a personal workspace, which has one person in it. Being
        let into the workspace is what `ws_dep` already checked; the editor asks again
        whenever it connects again (a pass lasts minutes)."""
        from cycls._agent.design import live, store
        src = _safe_path(ws.root, path)
        if src.suffix.lower() != ".fig" or not src.is_file():
            raise HTTPException(404, "No such design")
        if not (live.configured() and user is not None and (ws.ws or "").startswith("t-")):
            return {"live": None}
        rel = src.relative_to(Path(ws.root).resolve()).as_posix()
        _, version = await asyncio.to_thread(store.read_fig, ws.root, rel)
        room = live.room_of(ws.root, rel)
        await live.wake()   # asleep with nobody in any room: up by the time the editor connects
        return {"live": {"room": room, "url": live.socket_url(), "ticket": live.ticket(room, user.id),
                         "epoch": version}}

    @r.get("/brand")
    async def brand(ws: Workspace = ws_dep):
        """The workspace brand kit (brand/brand.yaml) for the design editor: its named
        colours (the Brand variables) and fonts, or null when there's no kit."""
        from cycls._agent.design.brand import _brand_palette, _load_brand
        colors = await asyncio.to_thread(_brand_palette, ws.root)
        kit = await asyncio.to_thread(_load_brand, ws.root) or {}
        fonts = {"heading": kit.get("heading"), "body": kit.get("body")}
        if not colors and not any(fonts.values()):
            return {"brand": None}
        return {"brand": {"colors": colors, "fonts": fonts}}

    # ---- A design's earlier versions (cycls/_agent/versions.py) ----

    @r.get("/versions/{path:path}")
    async def list_versions(path: str, request: Request, ws: Workspace = ws_dep):
        """A design's versions, newest first: {versions: [{id, at, by, reason, intent?,
        size}]} — or, with `?id=`, that version's bytes; with `?id=…&as=png`, a picture
        of it (its first slide or page, 640 px wide) to look at before restoring."""
        from cycls._agent import versions
        rel = _safe_path(ws.root, path).relative_to(Path(ws.root).resolve()).as_posix()
        if vid := request.query_params.get("id"):
            data = await asyncio.to_thread(versions.read, ws.root, rel, vid)
            if data is None:
                raise HTTPException(404, "No such version")
            if request.query_params.get("as") == "png":
                from cycls._agent import design
                try:
                    picture = await design.export(data, fmt="png", scale=1, width=640, user_id=ws.subject)
                except design.Unavailable as e:
                    raise HTTPException(415, str(e))
                except RuntimeError as e:
                    raise HTTPException(422, str(e))
                # (A version never changes: the browser may keep its picture.)
                return Response(picture, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})
            return Response(data, media_type="application/octet-stream", headers=_NO_CACHE)
        return {"versions": await asyncio.to_thread(versions.listing, ws.root, rel)}

    @r.post("/versions/{path:path}")
    async def restore_version(path: str, request: Request, ws: Workspace = ws_dep):
        """`?restore=<id>`: the design becomes that version again. What it was is kept
        as a version first, so a restore is undone by restoring. → {ok, version}"""
        from cycls._agent import versions
        from cycls._agent.design.store import write_fig
        rel = _safe_path(ws.root, path).relative_to(Path(ws.root).resolve()).as_posix()
        data = await asyncio.to_thread(versions.read, ws.root, rel, request.query_params.get("restore") or "")
        if data is None:
            raise HTTPException(404, "No such version")
        version = await write_fig(ws.root, rel, data, by="user", reason="restore")
        changed(ws.root)
        design_refresh.schedule(ws.root, rel, ws.subject)
        # People who have it open together hold what it was: their room opens it again.
        from cycls._agent.design import live
        await live.notify(ws.root, rel, {"kind": "reload", "version": version})
        return {"ok": True, "version": version}

    return r

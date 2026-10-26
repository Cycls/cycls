"""Design routes (/deck, /design/*, /brand, /versions, /comments), and the cached slide and export
renders the files routes serve for `?as=…`."""
import asyncio, base64, hashlib, json, re, shutil, tempfile, unicodedata, uuid, zipfile
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from cycls._app.db import Workspace
from cycls._agent.design import comments
from cycls._agent.design import refresh as design_refresh
from cycls._agent.web.shared import _NO_CACHE, _free_rel, _safe_path


# renders of one page (`&page=`, else the first), cached by the .fig's path + mtime + size
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
    """A design-service failure → 404 for a page that isn't there, else 502."""
    missing = str(e).startswith("there is no page")
    return HTTPException(404 if missing else 502, str(e) if missing else f"Couldn't render the design: {e}")


def _design_doc(name):
    """A file the design routes serve: a design (.fig)."""
    return str(name).lower().endswith(".fig")


def _design_file_name(name):
    """A new design's file name: NFC, no folders or `.fig`, word characters and `-_.() `, else `untitled`."""
    name = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"\.fig$", "", name.strip(), flags=re.I)
    name = re.sub(r"[^\w\-. ()]+", "-", name).strip(" .-")[:60].strip(" .-")
    return name or "untitled"


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


_building = {}   # a manifest being made → its task: who asks meanwhile waits for it


async def _give_fonts(root, user_id):
    """The workspace's own fonts (brand/fonts) given to the design service before it draws a preview or the editor
    asks it for them, not only on a Design call: the editor asked first, found nothing and drew stand-ins for the
    whole session. Best effort: a font not given is no reason to fail what was asked."""
    from cycls._agent import design
    from cycls._agent.logs import log
    try:
        await design.add_fonts(root, user_id)
    except Exception as e:
        log("warn", message=f"design fonts not given: {type(e).__name__}: {e}")


async def _design_slides(root, src, user_id, page=None):
    """A cached slide manifest of one page of design `src` (a .fig) → its path. Raises design.Unavailable,
    FileNotFoundError, ValueError."""
    root, fig = Path(root).resolve(), Path(src).resolve()
    if not await asyncio.to_thread(fig.is_file):
        raise FileNotFoundError(fig.name)
    stem, key = _design_cache_key(root, fig)
    cache_dir = root / _DESIGN_CACHE
    dst = cache_dir / f"{stem}-{key}{_page_tag(page)}.slides.json"
    if dst.exists():
        return dst
    if (task := _building.get(dst)) is None:
        task = _building[dst] = asyncio.ensure_future(_make_slides(root, fig, cache_dir, stem, key, dst, user_id, page))
        task.add_done_callback(lambda _: _building.pop(dst, None))
    return await asyncio.shield(task)


async def _make_slides(root, fig, cache_dir, stem, key, dst, user_id, page):
    from cycls._agent import design
    await _give_fonts(root, user_id)
    # ~1920px on the long side: sharp on the stage and in present mode.
    s = await design.slides(await asyncio.to_thread(fig.read_bytes), fit=1920, user_id=user_id, page=page)
    mime = "image/png" if s["format"] == "png" else "image/jpeg"
    meta = s["meta"] + [{}] * (len(s["images"]) - len(s["meta"]))
    keep = s.get("keep") or {}
    kind = str(keep.get("kind") or "")
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
    """Write one cached render; an older save's renders go, this save's other pages stay."""
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
    """One page of the design behind `src` as `fmt` (images: a zip of slide PNGs), cached → (path, download name)."""
    from cycls._agent import design
    root, fig = Path(root).resolve(), Path(src).resolve()
    if not await asyncio.to_thread(fig.is_file):
        raise FileNotFoundError(fig.name)
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


async def _new_slide_op(root, rel, after, title, text, user_id):
    """The deck viewer's "Add slide" as a service op, after slide `after` (from 1; 0: first; None: last):
    themed for a deck of layouts, else a blank in the previous slide's colour."""
    from cycls._agent import design
    from cycls._agent.design.brand import _norm_hex
    from cycls._agent.design.prepare import _prepare_slide
    fig_path = Path(root) / rel
    if not await asyncio.to_thread(fig_path.is_file):
        raise FileNotFoundError(fig_path.name)
    o = await design.outline(await asyncio.to_thread(fig_path.read_bytes), user_id=user_id)
    kept, frames = o["keep"].get("deck"), o["frames"]
    title, text = (title or "").strip() or "New slide", (text or "").strip() or "Add your text"
    if isinstance(kept, dict):
        settings = kept
        slide = {"layout": "bullets", "title": title, "bullets": [text]}
    else:
        near = frames[min(max((after or len(frames)) - 1, 0), len(frames) - 1)] if frames else {}
        size = near.get("size") or [1920, 1080]
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
    """?as=slides|pptx|pdf|images|png[&page=<name>] on a design (.fig) → the response."""
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
    """The routes that act on a design; `changed(root)` tells the files catalog a root was written."""
    r = APIRouter()

    @r.post("/deck/{path:path}")
    async def deck_op(path: str, request: Request, ws: Workspace = ws_dep):
        """The deck viewer's slide changes, run on the saved .fig like the agent's. Slides from 1:
          {op: "move" | "duplicate" | "delete", number, to?}
          {op: "add", number?, title?, text?}   after `number` (0: first; absent: last) → `added`
          {op: "notes", number, notes}"""
        from cycls._agent import design
        from cycls._agent.design import deck as decks
        if not _design_doc(path):
            raise HTTPException(404, "Not a deck")
        rel = _safe_path(ws.root, path).relative_to(Path(ws.root).resolve()).as_posix()
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
                op = await _new_slide_op(ws.root, rel, number, body.get("title"), body.get("text"), ws.subject)
            elif kind == "notes":
                notes = body.get("notes")
                if not whole(number, 1) or not isinstance(notes, str) or len(notes) > 20000:
                    raise HTTPException(400, "Expected {op: notes, number, notes} with slides from 1")
                op = {"op": "slide_meta", "index": number - 1, "notes": notes.strip()}
            elif kind in ("move", "duplicate", "delete") and whole(number, 1) and (kind != "move" or whole(to, 1)):
                op = {"op": f"slide_{kind}", "index": number - 1, **({"to": to - 1} if kind == "move" else {})}
            else:
                raise HTTPException(400, "Expected {op: move|duplicate|delete|add|notes, number, to?} with slides from 1")
            r = await decks.apply_ops(ws.root, rel, [op], user_id=ws.subject, by="user")
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
        # editors open on it reload (this one's own is re-opened by the app)
        from cycls._agent.design import live
        await live.notify(ws.root, rel, {"kind": "reload", "version": r.get("version")})
        return {"ok": True, "slides": len(r.get("slides") or []), **({"added": added} if added else {})}

    @r.post("/design/new")
    async def new_design(request: Request, ws: Workspace = ws_dep):
        """A blank design: {name?, size?: a preset or [w, h], background?, folder?} → <folder>/<name>.fig."""
        from cycls._agent import design
        from cycls._agent.design.brand import _norm_hex
        from cycls._agent.design.files import _free_design
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
        folder = str(body.get("folder") or "").strip("/")
        if folder:
            _safe_path(ws.root, f"{folder}/x.fig")                         # inside the workspace, not a managed slot
        try:
            out = await design.render({"size": wh, "fill": background, "nodes": []}, fmt="png", scale=1,
                                      user_id=ws.subject, keep={"kind": "post"})
        except design.Unavailable as e:
            raise HTTPException(503, str(e))
        except RuntimeError as e:
            raise HTTPException(422, str(e))
        root = Path(ws.root)
        stem = await asyncio.to_thread(_free_design, root, f"{folder}/{_design_file_name(body.get('name'))}".lstrip("/"))
        out_path = root / f"{stem}.fig"
        await asyncio.to_thread(out_path.parent.mkdir, parents=True, exist_ok=True)
        tmp = out_path.with_name(f".{out_path.name}.part")
        await asyncio.to_thread(tmp.write_bytes, out.fig)
        await asyncio.to_thread(tmp.replace, out_path)
        changed(ws.root)
        return {"path": f"{stem}.fig", "name": stem.rsplit("/", 1)[-1], "size": wh}

    @r.post("/design/export")
    async def export_design(request: Request, ws: Workspace = ws_dep):
        """The editor's File › Export: `{path, format: pdf|png, page?}` → `{path}`, rendered by the service
        (the browser's PDF embeds no fonts), written beside the design over nothing."""
        from cycls._agent import design
        body = await request.json()
        fmt = str(body.get("format") or "pdf")
        if fmt not in ("pdf", "png"):
            raise HTTPException(400, "format is pdf or png")
        src = _safe_path(ws.root, str(body.get("path") or ""))
        if src.suffix.lower() != ".fig" or not src.is_file():
            raise HTTPException(404, "No such design")
        page, made, data = _page_param(body.get("page")), None, None
        try:
            if page:   # its name names the file, so the service is asked (not the cache)
                data, _, name = await design.export_page(await asyncio.to_thread(src.read_bytes), page,
                                                         fmt=fmt, user_id=ws.subject)
            else:
                made, _ = await _design_export(ws.root, src, fmt, ws.subject)
        except design.Unavailable as e:
            raise HTTPException(415, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except RuntimeError as e:
            raise _design_error(e)
        root = Path(ws.root).resolve()
        rel = _free_rel(root, src.with_name(f"{src.stem}{f'-{_page_label(name)}' if page else ''}.{fmt}").relative_to(root).as_posix())
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
        """A design's live room: `{live: {room, url, ticket, epoch}}`, or `{live: null}` with no relay
        or in a personal workspace. `ws_dep` is the access check."""
        from cycls._agent.design import live, store
        src = _safe_path(ws.root, path)
        if src.suffix.lower() != ".fig" or not src.is_file():
            raise HTTPException(404, "No such design")
        if not (live.configured() and user is not None and (ws.ws or "").startswith("t-")):
            return {"live": None}
        rel = src.relative_to(Path(ws.root).resolve()).as_posix()
        _, version = await asyncio.to_thread(store.read_fig, ws.root, rel)
        room = live.room_of(ws.root, rel)
        await live.wake()   # up by the time the editor connects
        return {"live": {"room": room, "url": live.socket_url(), "ticket": live.ticket(room, user.id),
                         "epoch": version}}

    @r.get("/brand")
    async def brand(ws: Workspace = ws_dep):
        """The workspace brand kit's colours and fonts for the design editor, or null. The editor asks for it as
        it opens a design, so the workspace's own fonts reach the design service first."""
        from cycls._agent.design.brand import _brand_palette, _load_brand
        await _give_fonts(ws.root, getattr(ws, "subject", None))
        colors = await asyncio.to_thread(_brand_palette, ws.root)
        kit = await asyncio.to_thread(_load_brand, ws.root) or {}
        fonts = {"heading": kit.get("heading"), "body": kit.get("body")}
        if not colors and not any(fonts.values()):
            return {"brand": None}
        return {"brand": {"colors": colors, "fonts": fonts}}

    # ---- A design's earlier versions (cycls/_agent/versions.py) ----

    @r.get("/versions/{path:path}")
    async def list_versions(path: str, request: Request, ws: Workspace = ws_dep):
        """A design's versions, newest first; `?id=` that version's bytes, `&as=png` a 640px picture of it."""
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
                # a version never changes
                return Response(picture, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})
            return Response(data, media_type="application/octet-stream", headers=_NO_CACHE)
        return {"versions": await asyncio.to_thread(versions.listing, ws.root, rel)}

    @r.post("/versions/{path:path}")
    async def restore_version(path: str, request: Request, ws: Workspace = ws_dep):
        """`?restore=<id>`: the design becomes that version again (what it was is kept) → {ok, version}."""
        from cycls._agent import versions
        from cycls._agent.design.store import write_fig
        rel = _safe_path(ws.root, path).relative_to(Path(ws.root).resolve()).as_posix()
        data = await asyncio.to_thread(versions.read, ws.root, rel, request.query_params.get("restore") or "")
        if data is None:
            raise HTTPException(404, "No such version")
        version = await write_fig(ws.root, rel, data, by="user", reason="restore")
        changed(ws.root)
        design_refresh.schedule(ws.root, rel, ws.subject)
        # its live room reloads
        from cycls._agent.design import live
        await live.notify(ws.root, rel, {"kind": "reload", "version": version})
        return {"ok": True, "version": version}

    # ---- Comments on a design (cycls/_agent/design/comments.py) ----

    def _commented(ws, path):
        """The `.fig` a comments request is about."""
        root = Path(ws.root).resolve()
        src = _safe_path(root, path)
        if not _design_doc(src.name) or not src.is_file():
            raise HTTPException(404, "No such design")
        return src.relative_to(root).as_posix()

    def _commenter(ws, user, body):
        """Who is writing: the signed-in person, under the name their browser has for them."""
        from cycls._agent import state
        return comments.author(getattr(user, "id", None) or state.actor_of(ws.subject),
                               body.get("name") or getattr(user, "name", None),
                               getattr(user, "image_url", None) or body.get("image"))

    @r.get("/comments/{path:path}")
    async def list_comments(path: str, request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        """A design's threads: {threads, version, me}; polled with `?v=<version>` → {unchanged, version}."""
        from cycls._agent import state
        rel = await asyncio.to_thread(_commented, ws, path)
        doc, version = await comments.read(ws, rel)
        if request.query_params.get("v") == version:
            return {"unchanged": True, "version": version}
        return {"threads": comments.shown(doc), "version": version,
                "me": getattr(user, "id", None) or state.actor_of(ws.subject)}

    @r.post("/comments/{path:path}")
    async def comment(path: str, request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        """A new thread {text, frame (from 0), x, y (slide pixels), page?, frame_name?, name?}, or with `?id=`
        a change {op: reply|resolve|reopen|edit|delete|move, …} → {thread (null once deleted), version}."""
        rel = await asyncio.to_thread(_commented, ws, path)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise HTTPException(400, "Expected {text, frame, x, y} or {op, …}")
        who = _commenter(ws, user, body)
        try:
            if tid := request.query_params.get("id"):
                thread, version = await comments.change(ws, rel, tid, str(body.get("op") or ""), who, body)
            else:
                thread, version = await comments.add(ws, rel, who, body.get("text"), body)
        except comments.Refused as e:
            raise HTTPException(e.status, str(e))
        return {"thread": thread, "version": version}

    return r

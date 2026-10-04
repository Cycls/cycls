"""HTTP routers for the agent's state surface — chats, files, share.

Chat metadata + message log and shares live in the workspace DB — see
`cycls._agent.state`. Files stay on the workspace filesystem (POSIX-shaped).
"""
import asyncio, base64, hashlib, itertools, json, os, re, secrets, shutil, tempfile, time, unicodedata, uuid, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, parse_qs
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse

from cycls._app.db import DB, Conflict, Workspace, workspace
from cycls._agent import connectors as oauth, credentials, spill, state, trash
from cycls._agent.web import office
from cycls._agent.design import refresh as design_refresh
from cycls._agent.logs import log
from cycls._agent.tools import tool_step, detailed, excerpt

DEFAULT_MAX_UPLOAD_MB = 512   # per-file upload cap when not configured

# FileResponse sets ETag/Last-Modified but no Cache-Control, and heuristic
# freshness (browsers, iOS URLCache) then serves stale bytes after a write.
# no-cache keeps the cache but forces revalidation — 304 when unchanged.
_NO_CACHE = {"Cache-Control": "no-cache"}


def _search_rows(body):
    """Citation rows out of a stored `web_search` tool_result. The tool writes
    its results as JSON, so this reads back exactly what the live stream sent
    as a `sources` event — one format, both paths."""
    if not isinstance(body, str):
        return []
    try:
        data = json.loads(body)
    except Exception:
        return []
    rows = (data or {}).get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("url")]


def to_ui_messages(raw):
    """Stored API messages → FE shape `{role, content: str, parts?, attachments?}`.
    Drops harness scaffolding — messages tagged `internal` (compaction summary,
    output-limit resume prompt) and user messages that are purely tool_result —
    and merges consecutive assistant messages: a model turn is several
    assistant/tool-result round-trips on disk but one bubble in the UI, the same
    shape the live stream produces."""
    # tool_use id → its result errored. Lets the FE downgrade failed canvas
    # calls from a file card back to a plain step.
    errored, results = set(), {}   # tool_use id → its stored result, for a connector step's Response
    search_ids = set()   # client-side `web_search` calls, by tool_use id
    for msg in raw:
        c = msg.get("content")
        if msg.get("role") == "assistant" and isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "web_search":
                    search_ids.add(b.get("id"))
        if msg.get("role") == "user" and isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    body = results[b.get("tool_use_id")] = b.get("content")
                    if b.get("is_error") or (isinstance(body, str) and body.startswith("Error")):
                        errored.add(b.get("tool_use_id"))

    out = []
    for msg in raw:
        role, c = msg.get("role"), msg.get("content")
        if msg.get("internal"):
            continue
        if role == "user":
            if isinstance(c, list):
                if all(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                    # The batch itself stays hidden, but a `web_search` result in
                    # it carries the sources the answer cites — attach them to the
                    # assistant turn that ran the search, where the live stream
                    # put them (after the search step, before the answer).
                    if out and out[-1]["role"] == "assistant":
                        for b in c:
                            if b.get("tool_use_id") not in search_ids or b.get("is_error"):
                                continue
                            if rows := _search_rows(b.get("content")):
                                out[-1]["parts"].append({"type": "sources", "sources": rows, "id": b.get("tool_use_id")})
                    # A run that ended waiting on the person: the card is stored
                    # on the batch, because `ui` events never reach the
                    # transcript. Without this a reload shows a finished-looking
                    # chat with nothing to approve.
                    if msg.get("cards") and out and out[-1]["role"] == "assistant":
                        out[-1]["parts"] += [{"type": "card", "card": card} for card in msg["cards"]]
                    continue
                text = state.user_text(msg)
            elif isinstance(c, str):
                text = c
            else:
                continue
            ui = {"role": "user", "content": text}
            if msg.get("attachments"):
                ui["attachments"] = msg["attachments"]
            if msg.get("selection"):   # the model read it as a line; the person sees a chip
                ui["selection"] = msg["selection"]
            out.append(ui)
        elif role == "assistant":
            blocks = c if isinstance(c, list) else [{"type": "text", "text": c}] if isinstance(c, str) else []
            parts, texts = [], []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text":
                    parts.append({"type": "text", "text": b.get("text", "")}); texts.append(b.get("text", ""))
                elif t == "thinking":
                    parts.append({"type": "thinking", "thinking": b.get("thinking", "")})
                elif t == "tool_use":
                    part = {"type": "step", "id": b.get("id"), **tool_step(b.get("name", ""), b.get("input"))}
                    if b.get("id") in errored:
                        part["ok"] = False
                    if detailed(b.get("name", "")):
                        part["args"] = json.dumps(b.get("input") or {}, ensure_ascii=False)
                        if b.get("id") in results:
                            part["result"] = excerpt(results[b["id"]])
                    parts.append(part)
                elif t == "web_search_tool_result":
                    # Anthropic's server-side search stores its rows right here,
                    # so citations survive a reload for free. No snippet in this
                    # shape — the card degrades to domain + title.
                    # An error comes back as a dict, not a list of results.
                    body = b.get("content")
                    rows = [{"title": (r.get("title") or "").strip(), "url": r["url"], "snippet": ""}
                            for r in (body if isinstance(body, list) else [])
                            if isinstance(r, dict) and r.get("type") == "web_search_result" and r.get("url")]
                    if rows:
                        parts.append({"type": "sources", "sources": rows, "id": b.get("tool_use_id")})
                elif t == "server_tool_use":
                    # Server-side tools (web_search etc.) run Anthropic-side. The live
                    # provider stream yields a Step for these at content_block_stop;
                    # mirror it on refetch so search history doesn't vanish on reload.
                    parts.append({"type": "step", "id": b.get("id"), **tool_step(b.get("name", ""), b.get("input"))})
            if out and out[-1]["role"] == "assistant":
                out[-1]["content"] += "".join(texts); out[-1]["parts"] += parts
            else:
                out.append({"role": "assistant", "content": "".join(texts), "parts": parts})
    return out


def canvas_files(messages):
    """Workspace files produced by the conversation's successful Canvas calls
    (UI shape from `to_ui_messages`), in order of appearance. These are part
    of a chat's shareable surface, same as its attachments: a shared chat
    serves them, a fork copies them."""
    out = []
    for m in messages:
        for p in (m.get("parts") or []):
            if p.get("type") == "step" and p.get("tool_name") == "Canvas" \
                    and p.get("step") and p.get("ok") is not False and p["step"] not in out:
                out.append(p["step"])
    return out


# ---- Workspace selection (multi-workspace mode) ----

async def resolve_ws_id(user, header, mode, volume, base):
    """`X-Workspace` header → workspace id the user may enter, or None in
    legacy mode. Personal (`u-{user.id}`) is the default and needs no lookup;
    team ids are checked against the ACL (member row, or implicit org-admin).
    Everything else — a teammate's personal id, an unknown team, garbage —
    is 404, not 403, so ids don't leak existence (docs/workspaces.md)."""
    if not mode or user is None:
        return None
    await state.ensure_general(user, volume, base)
    ws_id = header or f"u-{user.id}"
    if ws_id == f"u-{user.id}":
        return ws_id
    if ws_id.startswith("t-"):
        orgdb = state.org_db(state.org_of(user), volume, base)
        if await state.resolve_role(user, ws_id, orgdb) is not None:
            return ws_id
    raise HTTPException(404, "Workspace not found")


def personal_ws(subject):
    """Personal workspace id for a `org:user` / `user` subject string."""
    org, _, user = subject.partition(":")
    return f"u-{user or org}"


# ---- Emoji check (workspace icons) ----

_EMOJI_MODIFIERS = {0x200D, 0xFE0E, 0xFE0F, 0x20E3}   # ZWJ, variation selectors, keycap


def _is_emoji(s):
    """True iff `s` is one emoji: a pictograph, flag pair, or keycap, possibly
    a ZWJ sequence (family, professions) with skin tones. Codepoint-range
    check — no emoji dependency; ranges cover Unicode's emoji blocks."""
    cps = [ord(c) for c in s]
    base = [c for c in cps if c not in _EMOJI_MODIFIERS and not 0x1F3FB <= c <= 0x1F3FF]
    if not base or len(base) > 4:   # longest common ZWJ sequence: family of four
        return False
    def ok(c):
        return (0x1F000 <= c <= 0x1FAFF      # emoji, symbols, supplemental
                or 0x2600 <= c <= 0x27BF     # misc symbols, dingbats
                or 0x2B00 <= c <= 0x2BFF     # stars, arrows
                or 0x2190 <= c <= 0x21FF or 0x2300 <= c <= 0x23FF
                or 0x1F1E6 <= c <= 0x1F1FF   # regional indicators (flags)
                or c in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139,
                         0x3030, 0x303D, 0x3297, 0x3299)
                or (0x20E3 in cps and (0x30 <= c <= 0x39 or c in (0x23, 0x2A))))  # keycap digit/#/*
    return all(ok(c) for c in base)


# ---- Path safety ----

def resolve_path(workspace, rel):
    """Resolve *rel* inside *workspace*, raising ValueError on traversal or
    access to the reserved `.db/` and `.database/` trees (framework-managed)."""
    workspace = Path(workspace)
    rel = unicodedata.normalize("NFC", rel)
    resolved = (workspace / rel).resolve()
    ws = workspace.resolve()
    if not resolved.is_relative_to(ws):
        raise ValueError("Path traversal denied")
    for name in (".db", ".database", ".trash", ".versions", ".secrets", ".connectors", ".settings"):
        reserved = ws / name
        if resolved == reserved or resolved.is_relative_to(reserved):
            raise ValueError(f"Reserved path: {name}/ is managed by cycls")
    return resolved


def _free_rel(root, rel):
    """A name for a new file at `rel` that overwrites nothing: `rel` itself, else
    `<stem>-2`, `-3`, … It's free when no file has it and it isn't an image the design
    refresh keeps beside a .fig (that would be overwritten by the next re-export); a
    .fig under designs/ also keeps clear of another design's images and deck, as a
    fresh render does (`_dedupe_design_name`)."""
    from cycls._agent.tools import _dedupe_design_name
    path = Path(rel)
    root = Path(root)
    if rel.startswith("designs/") and path.suffix.lower() == ".fig":
        return (path.parent / f"{_dedupe_design_name(root / path.parent, path.stem, 'png')}.fig").as_posix()
    stem, suffix = (path.name[:-len(path.suffix)], path.suffix) if path.suffix else (path.name, "")
    taken = lambda cand: (root / cand).exists() or design_refresh.managed(root, cand)
    if not taken(rel):
        return rel
    n = 2
    while taken(cand := (path.parent / f"{stem}-{n}{suffix}").as_posix()):
        n += 1
    return cand


def _design_file_name(name):
    """A new design's file name: NFC, no folders or `.fig`, letters (any script),
    digits, spaces, `-_.()` — else `untitled`."""
    name = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"\.fig$", "", name.strip(), flags=re.I)
    name = re.sub(r"[^\w\-. ()]+", "-", name).strip(" .-")[:60].strip(" .-")
    return name or "untitled"


# ---- Chats ----

def chats_router(ws_dep):
    r = APIRouter()

    @r.get("/chats")
    async def list_chats(ws: Workspace = ws_dep):
        items = []
        runs = await state.list_runs(ws)   # one listing for the whole workspace
        async for cid, data in state.list_chats(ws):
            if data.get("deletedAt"):   # in the trash
                continue
            items.append({
                "id": data.get("id", cid),
                "title": data.get("title", ""),
                "updatedAt": data.get("updatedAt", ""),
                "favoritedAt": data.get("favoritedAt", ""),
                "cost": data.get("cost", "0"),
                "run": state.run_status(runs.get(cid)),
            })
        items.sort(key=lambda s: s.get("updatedAt", ""), reverse=True)
        return items

    @r.get("/chats/{chat_id}")
    async def get_chat(chat_id: str, since: Optional[int] = None, ws: Workspace = ws_dep):
        """`since` returns only the turns after that index — the poll runs every
        2s and a whole chat is one object read per turn. `next` is the cursor to
        come back with; `open` is the role of the last projected message, which is
        how a client knows whether to fold the window into its trailing bubble
        (consecutive assistant turns collapse into one)."""
        meta = await state.get_meta(ws, chat_id)
        # 204 (not 404) for a missing chat: the FE auto-restores `?id=` on
        # cold load, and a stale id is normal — 404s clutter the dev console.
        if meta is None:
            return Response(status_code=204)
        # `run` tells the client whether to keep polling: a run outlives the
        # request that started it, so a finished stream is not a finished run.
        row = await state.get_run(ws, chat_id)
        run = state.run_status(row)
        turns, end = (None, None) if since is None else await state.load_tail(ws, chat_id, max(since, 0))
        reset = since is not None and turns is None
        if turns is None:   # full load, or the client is ahead of us
            turns = await state.load_messages(ws, chat_id)
            end = end if end is not None else await state.turn_end(ws, chat_id)
        ui = to_ui_messages(turns)
        return {**meta, "messages": ui, "run": run, "next": end,
                **({"run_started": row.get("started")} if run == "running" and row else {}),
                "open": ui[-1]["role"] if ui else None,
                **({"reset": True} if reset else {})}

    @r.put("/chats/{chat_id}")
    async def put_chat(chat_id: str, request: Request, ws: Workspace = ws_dep):
        """Partial update — merges into existing meta. Send `field: null` to remove a key.
        `updatedAt` is NOT bumped on metadata edits (rename, favorite, …) — it tracks
        message activity only, owned by `touch_meta` on new messages."""
        patch = await request.json()
        patch.pop("messages", None)
        patch.pop("run", None)   # the run record is its own object, not chat meta
        existing = (await state.get_meta(ws, chat_id)) or {}
        merged = {**existing}
        for k, v in patch.items():
            if v is None: merged.pop(k, None)
            else: merged[k] = v
        now = datetime.now(timezone.utc).isoformat()
        merged["id"] = chat_id
        merged.setdefault("createdAt", now)
        merged.setdefault("updatedAt", now)
        await state.put_meta(ws, chat_id, merged)
        return merged

    @r.delete("/chats/{chat_id}/last-exchange")
    async def truncate_last_exchange(chat_id: str, expect: Optional[str] = None, ws: Workspace = ws_dep):
        """Drop the last user turn and everything after it — the persistence
        half of `regenerate`. The FE then re-sends the same message, so the
        run that follows is an ordinary send.

        `?expect=<sha256 of the message's text>` is `retry`'s form: a failed or stopped
        turn is dropped before its message is sent again, so the chat keeps it once. It
        only ever drops that turn — not a turn with other text, and not one that ended
        well (the failed request never arrived; the exchange before it stays) — and
        says `{ok: false}` when it dropped nothing."""
        if (await state.get_meta(ws, chat_id)) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        # This is the one route that still deletes and renumbers every turn file.
        # Under a live run that moves the slots it is appending to — the exact way
        # two production chats lost turns (docs/notes/runs.md).
        status = state.run_status(await state.get_run(ws, chat_id))
        if status == "running":
            raise HTTPException(status_code=409, detail="This chat is still working on your last message.")
        if expect is not None and status == "done":
            return {"ok": False}
        removed = await state.truncate_last_exchange(ws, chat_id, expect)
        return {"ok": removed is not None}

    @r.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str, ws: Workspace = ws_dep):
        """A tombstone, not a wipe — the chat lives on in the trash for
        TTL_DAYS (see files_router's /trash routes for restore and purge)."""
        meta = await state.get_meta(ws, chat_id)
        if meta is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        meta["deletedAt"] = datetime.now(timezone.utc).isoformat()
        await state.put_meta(ws, chat_id, meta)
        return {"ok": True, "trash_id": f"chat:{chat_id}"}

    return r


# ---- Files ----
#
# The file browser reads the one folder it shows. The @-picker, the flat listing
# and "Move to…" need the whole tree, and are served from one cached walk of it;
# matching/ordering/render-class are decided here rather than once per client.

_LIST_CAP = 2000          # flat-listing response cap
_SEARCH_CAP = 12          # @-picker results per query
_CATALOG_MAX = 10000      # entries in one cached walk
_CATALOG_WORKSPACES = 8   # workspaces one instance keeps warm

# Serving is serverless, so this cache is per-instance: `_catalog_drop` marks
# only the instance that handled the write, and agent writes go through the
# sandbox rather than these routes and so never invalidate at all. The TTL is
# what bounds both.
_CATALOG_TTL = 5.0        # how long a walk is reused, from when it ended
_CATALOG_WAIT = 0.5       # how long a reader waits for a re-walk before taking the last one
_CATALOG_SLOW = 2.0       # a walk slower than this is logged, with where its entries are

# str(root) -> {tree: (entries, truncated) | None, began, ended, dropped, walk: Task | None}.
# `began` / `dropped` are ticks of one counter: a tree is current only when its walk
# began after the last write here.
_catalog = {}
_tick = itertools.count(1)


def _norm(text):
    """Casefolded NFC — a typed query and a name off the mount can arrive in
    different normal forms and never compare equal. Routine in Arabic."""
    return unicodedata.normalize("NFC", text).casefold()


def _iso(mtime):
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


# Union of what the web and mobile canvases can each display.
_KINDS = (
    ("image",    {"png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp", "svg", "ico", "avif"}),
    ("pdf",      {"pdf"}),
    ("csv",      {"csv", "tsv"}),          # delimited text: any client can render it
    ("sheet",    {"numbers"}),             # binary spreadsheet a client parses in-browser
    # Office documents render by converting to PDF on demand (LibreOffice, via
    # the office-render service) and showing them in the PDF viewer. The ext
    # set is single-sourced from the converter so labelling and conversion
    # can't disagree. Binary spreadsheets (xls/xlsx/ods) route here too.
    ("office",   set(office.CONVERTIBLE)),
    ("audio",    {"mp3", "wav", "ogg", "oga", "m4a", "aac", "flac", "opus", "weba"}),
    ("video",    {"mp4", "webm", "mov", "m4v", "ogv"}),
    ("model3d",  {"glb", "gltf"}),
    ("markdown", {"md", "markdown"}),
    ("html",     {"html", "htm"}),
    ("code",     {"py", "js", "mjs", "cjs", "ts", "tsx", "jsx", "json", "sh", "bash", "zsh",
                  "rb", "go", "rs", "java", "c", "h", "cc", "cpp", "cs", "php", "swift", "kt",
                  "sql", "yaml", "yml", "toml", "css", "scss", "less", "xml", "ipynb"}),
    ("text",     {"txt", "text", "log", "env", "conf", "cfg", "ini"}),
    ("design",   {"fig"}),                 # an OpenPencil design: the in-canvas editor
)
_KIND_BY_EXT = {ext: kind for kind, exts in _KINDS for ext in exts}
_SORTS = ("name", "size", "modified", "type")
_PUBLIC = ("name", "path", "type", "size", "modified", "kind")


def _kind(name):
    if name.lower().endswith(".deck.json"):
        return "deck"                      # a design deck's document: the deck viewer
    return _KIND_BY_EXT.get(name.rpartition(".")[2].lower() if "." in name else "", "opaque")


def _public(entry):
    return {k: entry[k] for k in _PUBLIC}


# Converted-PDF cache for the Office preview. Hidden (dot-prefixed) so the
# catalog walk skips it, keyed by source path+mtime+size so a rewritten source
# is a fresh entry and prior renders of the same file are swept on the miss.
_OFFICE_CACHE = ".cache/office"


def _write_office_cache(cache_dir, stem, dst, pdf):
    """Persist a rendered PDF into the workspace cache and return the served
    path. On a read-only workspace (e.g. a share) fall back to a temp file so
    the preview still works, just uncached — matching how folder zips serve."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for old in cache_dir.glob(f"{stem}-*.pdf"):   # sweep prior renders of this file
            try: old.unlink()
            except OSError: pass
        tmp = cache_dir / f".{stem}-{uuid.uuid4().hex}.part"
        tmp.write_bytes(pdf)
        tmp.replace(dst)                              # atomic swap into place
        return dst
    except OSError:
        tmp = Path(tempfile.gettempdir()) / f"office-{uuid.uuid4().hex}.pdf"
        tmp.write_bytes(pdf)
        return tmp


async def _office_pdf(root, src, user_id):
    """A cached PDF render of one office file, converting on a miss via the
    office-render service. Raises office.Unavailable so the caller can fall
    back to the download card."""
    root = Path(root).resolve()   # src is already resolved (resolve_path), so match it
    st = src.stat()
    stem = hashlib.sha1(src.relative_to(root).as_posix().encode("utf-8")).hexdigest()[:16]
    cache_dir = root / _OFFICE_CACHE
    dst = cache_dir / f"{stem}-{st.st_mtime_ns}-{st.st_size}.pdf"
    if dst.exists():
        return dst
    data = await asyncio.to_thread(src.read_bytes)
    pdf = await office.to_pdf(data, src.name, user_id)
    return await asyncio.to_thread(_write_office_cache, cache_dir, stem, dst, pdf)


def _write_office_slides(cache_dir, stem, dst, payload):
    """Persist the rendered-slides JSON into the workspace cache; fall back to a
    temp file on a read-only workspace (a share), same as the PDF cache."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for old in cache_dir.glob(f"{stem}-*.slides.json"):
            try: old.unlink()
            except OSError: pass
        tmp = cache_dir / f".{stem}-{uuid.uuid4().hex}.part"
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(dst)
        return dst
    except OSError:
        tmp = Path(tempfile.gettempdir()) / f"office-{uuid.uuid4().hex}.slides.json"
        tmp.write_text(payload, encoding="utf-8")
        return tmp


async def _office_slides(root, src, user_id):
    """A cached slide render of one presentation — a JSON manifest of per-slide
    PNG data-URIs the canvas shows in the slide viewer. Renders on a miss via the
    office-render service. Raises office.Unavailable so the caller can fall back
    to the download card."""
    root = Path(root).resolve()
    st = src.stat()
    stem = hashlib.sha1(src.relative_to(root).as_posix().encode("utf-8")).hexdigest()[:16]
    cache_dir = root / _OFFICE_CACHE
    dst = cache_dir / f"{stem}-{st.st_mtime_ns}-{st.st_size}.slides.json"
    if dst.exists():
        return dst
    data = await asyncio.to_thread(src.read_bytes)
    pngs = await office.to_slides(data, src.name, user_id)
    slides = ["data:image/png;base64," + base64.b64encode(p).decode("ascii") for p in pngs]
    payload = json.dumps({"count": len(slides), "slides": slides})
    return await asyncio.to_thread(_write_office_slides, cache_dir, stem, dst, payload)


# Designs as decks. A multi-frame render writes `designs/<name>.deck.json` (the deck
# document) beside its `.fig`; either one previews slide by slide (?as=slides — a
# manifest the deck viewer shows and presents) and exports the whole deck on demand
# (?as=pptx / ?as=pdf, or ?as=images: every slide as a PNG, zipped — what a carousel
# is posted from; ?as=png: the first frame, a single design's picture), through the
# cycls-design service. Cached like the office
# renders, keyed by the .fig's path + mtime + size — so an edit (the editor's
# auto-save, an agent's `edit`) is a fresh render.
_DESIGN_CACHE = ".cache/design"
_DESIGN_AS = ("slides", "pptx", "pdf", "images", "png")


def _design_doc(name):
    """A file the deck routes serve: a deck document or a design (.fig)."""
    n = name.lower()
    return n.endswith(".deck.json") or n.endswith(".fig")


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


async def _design_slides(root, src, user_id):
    """A cached slide render of a design — {count, slides: [data-URI JPEGs],
    sizes, names, titles, notes, transitions, fig}. Raises design.Unavailable
    (no service), FileNotFoundError / ValueError (not a deck)."""
    from cycls._agent import design
    root = Path(root).resolve()
    fig, size = await asyncio.to_thread(_deck_fig, root, src)
    stem, key = _design_cache_key(root, fig)
    cache_dir = root / _DESIGN_CACHE
    dst = cache_dir / f"{stem}-{key}.slides.json"
    if dst.exists():
        return dst
    # ~1920px on the long side: sharp on the stage and in present mode.
    scale = min(2, max(1, 1920 / max(size))) if size and all(isinstance(v, (int, float)) and v > 0 for v in size) else 1
    s = await design.slides(await asyncio.to_thread(fig.read_bytes), scale=scale, user_id=user_id)
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
    })
    return await asyncio.to_thread(_write_office_slides, cache_dir, stem, dst, payload)


def _write_design_export(cache_dir, stem, fmt, dst, data):
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        for old in cache_dir.glob(f"{stem}-*.{fmt}"):
            try: old.unlink()
            except OSError: pass
        tmp = cache_dir / f".{stem}-{uuid.uuid4().hex}.part"
        tmp.write_bytes(data)
        tmp.replace(dst)
        return dst
    except OSError:
        tmp = Path(tempfile.gettempdir()) / f"design-{uuid.uuid4().hex}.{fmt}"
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


async def _design_export(root, src, fmt, user_id):
    """The whole deck behind `src` as `fmt` (pptx / pdf / images: a zip of every
    slide's PNG) — or `png`, its first frame — cached → (path, the download name).
    Same errors as _design_slides."""
    from cycls._agent import design
    root = Path(root).resolve()
    fig, _ = await asyncio.to_thread(_deck_fig, root, src)
    stem, key = _design_cache_key(root, fig)
    cache_dir = root / _DESIGN_CACHE
    ext = "zip" if fmt == "images" else fmt
    dst = cache_dir / f"{stem}-{key}.{ext}"
    name = f"{fig.stem}.{ext}"
    if dst.exists():
        return dst, name
    data = await asyncio.to_thread(fig.read_bytes)
    if fmt == "images":
        data = _zip_slides(fig.stem, await design.export(data, fmt="png", user_id=user_id, every=True))
    else:
        data = await design.export(data, fmt=fmt, user_id=user_id)
    return await asyncio.to_thread(_write_design_export, cache_dir, stem, ext, dst, data), name


async def _design_response(root, src, as_, user_id):
    """?as=slides|pptx|pdf|images|png on a deck document or a .fig → the response."""
    from cycls._agent import design
    try:
        if as_ == "slides":
            return FileResponse(await _design_slides(root, src, user_id),
                                media_type="application/json", headers=_NO_CACHE)
        path, name = await _design_export(root, src, as_, user_id)
        return FileResponse(path, filename=name, headers=_NO_CACHE)
    except design.Unavailable as e:
        raise HTTPException(415, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, f"The deck's design file is missing: {e}")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise HTTPException(502, f"Couldn't render the deck: {e}")


def _walk_catalog(root):
    """One pass over the tree, a single stat per entry. Folder times come from
    the newest child seen during the same walk — gcsfuse synthesizes directory
    mtimes off its cache-refresh clock, and correcting that per request cost a
    scan of every folder listed."""
    root = Path(root)
    entries, newest, truncated = [], {}, False
    for parent, subdirs, names in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if not d.startswith("."))
        p = Path(parent)
        # POSIX-shaped paths (forward slashes) so scoping/search compare equal on
        # Windows too — str(relative_to()) would emit backslashes there.
        rel_dir = "" if p == root else (p.relative_to(root)).as_posix()
        for d in subdirs:
            entries.append({"name": d, "path": (p / d).relative_to(root).as_posix(),
                            "type": "directory", "size": 0, "modified": "",
                            "kind": "folder", "_dir": rel_dir})
        for fn in sorted(names):
            if fn.startswith(".") or (p == root and fn.lower() == "agent.md"):   # AGENT.md has its own row
                continue
            try:
                st = (p / fn).stat()
            except OSError:      # vanished mid-walk, or unreadable
                continue
            entries.append({"name": fn, "path": (p / fn).relative_to(root).as_posix(),
                            "type": "file", "size": st.st_size,
                            "modified": _iso(st.st_mtime), "kind": _kind(fn),
                            "_dir": rel_dir})
            if st.st_mtime > newest.get(rel_dir, 0):
                newest[rel_dir] = st.st_mtime
        if len(entries) >= _CATALOG_MAX:
            truncated = True
            break
    for e in entries:
        if e["type"] == "directory" and (t := newest.get(e["path"])):
            e["modified"] = _iso(t)
    return entries, truncated


def _catalog_evict(keep):
    """One instance is reused across every workspace it serves, so an unbounded
    dict of walked trees leaks. The tree walked longest ago goes first."""
    while len(_catalog) > _CATALOG_WORKSPACES:
        victim = min((k for k in _catalog if k != keep),
                     key=lambda k: _catalog[k]["ended"], default=None)
        if victim is None:
            return
        del _catalog[victim]


def _catalog_slot(key):
    slot = _catalog.get(key)
    if slot is None:
        slot = _catalog[key] = {"tree": None, "began": 0, "ended": 0.0, "dropped": 0, "walk": None}
        _catalog_evict(key)
    return slot


def _catalog_walk(key, root, slot):
    """Walk `root` off the request → the task. Its tree replaces an older one."""
    began, started = next(_tick), time.monotonic()

    async def walk():
        try:
            tree = await asyncio.to_thread(_walk_catalog, root)
        except BaseException:
            if slot["tree"] is None and _catalog.get(key) is slot:
                del _catalog[key]      # a failed walk leaves nothing to serve
            raise
        finally:
            if slot["walk"] is task:
                slot["walk"] = None
        if began > slot["began"]:
            slot.update(tree=tree, began=began, ended=time.monotonic())
        if (took := time.monotonic() - started) > _CATALOG_SLOW:
            top = {}
            for e in tree[0]:
                head = e["path"].split("/", 1)[0] if "/" in e["path"] else "."
                top[head] = top.get(head, 0) + 1
            log("files", message=f"catalog walk took {took:.1f}s", entries=len(tree[0]), truncated=tree[1],
                largest=dict(sorted(top.items(), key=lambda kv: -kv[1])[:5]))
        return tree

    task = slot["walk"] = asyncio.ensure_future(walk())
    task.add_done_callback(lambda t: t.cancelled() or t.exception())   # nobody may be waiting on it
    return task


async def _catalog_get(root, fresh=False):
    """The workspace tree — every file and folder — from a walk cached per workspace.

    A walk is reused for _CATALOG_TTL after it ends. Past that, or after a write
    here, the tree is walked again: the reader waits _CATALOG_WAIT for it, and if it
    takes longer is handed the last tree while the new one finishes behind it — a
    large workspace on the gcsfuse mount takes 30–40 s to walk, and a search must
    not. `fresh` waits for a walk begun after the call, however long. Readers
    arriving mid-walk join it instead of starting their own."""
    key = str(root)
    slot = _catalog_slot(key)
    last = slot["tree"]
    if (last is not None and not fresh and slot["began"] > slot["dropped"]
            and time.monotonic() - slot["ended"] < _CATALOG_TTL):
        return last
    walk = slot["walk"]
    if fresh or walk is None or walk.done():
        walk = _catalog_walk(key, root, slot)
    if last is None or fresh:
        return await asyncio.shield(walk)
    done, _ = await asyncio.wait({walk}, timeout=_CATALOG_WAIT)
    if done and not walk.cancelled() and walk.exception() is None:
        return walk.result()
    return last


def _catalog_warm(root):
    """A workspace's first walk, begun in the background by its first folder listing —
    so the search that follows finds a tree instead of waiting for one."""
    key = str(root)
    if key not in _catalog:
        _catalog_walk(key, root, _catalog_slot(key))


def _catalog_drop(root):
    """A write happened under `root`: its cached tree is out of date. The tree stays
    (the next reader may be handed it while the re-walk runs). Resolves the root as
    `_catalog_get` does; a mismatched key would silently never invalidate."""
    if slot := _catalog.get(str(Path(root).resolve())):
        slot["dropped"] = next(_tick)


def _search(entries, query, cap=_SEARCH_CAP):
    """Files whose path contains every whitespace-separated token, in any order.
    Tokenized rather than contiguous so a name with spaces doesn't have to be
    reproduced adjacently and in order. A blank query matches everything, so a
    bare "@" browses rather than returning nothing."""
    tokens = _norm(query).split()
    ranked = []
    for e in entries:
        if e["type"] != "file":
            continue
        path_n = _norm(e["path"])
        if not all(t in path_n for t in tokens):
            continue
        name_n = _norm(e["name"])
        ranked.append((
            0 if all(t in name_n for t in tokens) else 1,
            0 if tokens and name_n.startswith(tokens[0]) else 1,
            len(e["path"]),
            name_n,
            e,
        ))
    ranked.sort(key=lambda row: row[:4])
    return [row[4] for row in ranked[:cap]]


def _sorted(entries, key, desc):
    """Folders first, then the requested key. `desc` never reverses the
    grouping."""
    def sort_key(e):
        if key == "size":
            return (e["size"], _norm(e["name"]))
        if key == "modified":
            return (e["modified"], _norm(e["name"]))
        if key == "type":
            return (e["kind"], _norm(e["name"]))
        return (_norm(e["name"]), "")
    groups = ([e for e in entries if e["type"] == "directory"],
              [e for e in entries if e["type"] == "file"])
    return [e for g in groups for e in sorted(g, key=sort_key, reverse=desc)]


def _is_org_admin(user):
    return getattr(user, "org_role", None) == "admin"


async def _admin(cycls_app, user, ws, volume, base):
    """Owner/admin on a team workspace; everyone on their own personal one."""
    mode = getattr(getattr(cycls_app, "config", None), "workspaces", None)
    if not mode or not ws.ws or ws.ws.startswith("u-"):
        return True
    orgdb = state.org_db(state.org_of(user), volume, base)
    return (await state.resolve_role(user, ws.ws, orgdb)) in ("owner", "admin")


def files_router(cycls_app, ws_dep, user_dep, volume, base):
    r = APIRouter()
    max_bytes = (getattr(getattr(cycls_app, "config", None), "max_upload", None) or DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024

    def _safe_path(workspace, rel):
        try:
            return resolve_path(workspace, rel)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path traversal denied")

    def _dir_mtime(path):
        """gcsfuse synthesizes directory mtimes (≈ its cache-refresh clock, so
        every folder 'changes' whenever anything is written) — report the
        newest direct child file instead; empty → ""."""
        try:
            times = [e.stat().st_mtime for e in os.scandir(path)
                     if not e.name.startswith(".") and e.is_file()]
        except OSError:
            times = []
        t = max(times, default=None)
        return datetime.fromtimestamp(t, tz=timezone.utc).isoformat() if t else ""

    def _scandir_slice(target, root):
        """One folder, read from the folder: its files, and its subfolders with their
        times (each a scan of that subfolder — a few at a time, a list call apiece on
        the gcsfuse mount)."""
        out, dirs = [], []
        for entry in os.scandir(target):
            if entry.name.startswith(".") or Path(entry.path).relative_to(root).as_posix().lower() == "agent.md":
                continue
            try:
                st = entry.stat()
            except OSError:      # vanished mid-scan, or unreadable
                continue
            is_dir = entry.is_dir()
            out.append({
                "name": entry.name,
                "path": Path(entry.path).relative_to(root).as_posix(),
                "type": "directory" if is_dir else "file",
                "size": 0 if is_dir else st.st_size,
                "modified": "" if is_dir else _iso(st.st_mtime),
                "kind": "folder" if is_dir else _kind(entry.name),
            })
            if is_dir:
                dirs.append((out[-1], entry.path))
        if len(dirs) > 1:
            with ThreadPoolExecutor(max_workers=8) as pool:
                times = list(pool.map(_dir_mtime, [path for _, path in dirs]))
        else:
            times = [_dir_mtime(path) for _, path in dirs]
        for (row, _), modified in zip(dirs, times):
            row["modified"] = modified
        return out

    @r.get("/files")
    async def list_files(request: Request, response: Response, ws: Workspace = ws_dep):
        """One folder, the whole tree, or a search across it.

        One folder is read from that folder, so it is always current and costs what
        the folder costs — never a walk of the workspace. `search=q` backs the
        @-picker and returns files only; `recursive=1` still returns the flat tree,
        so clients predating `search` keep working. Both come from the cached walk
        (`_catalog_get`), where `fresh=1` waits for a new one — for right after a
        client's own write, which another instance may have handled, and right after
        an agent turn.
        """
        q = request.query_params
        root = Path(ws.root).resolve()
        fresh = q.get("fresh") is not None
        target = _safe_path(ws.root, q.get("path", ""))
        rel = "" if target == root else target.relative_to(root).as_posix()
        under = lambda es: es if not rel else [e for e in es if e["path"].startswith(f"{rel}/")]

        if (search := q.get("search")) is not None:
            entries, _ = await _catalog_get(root, fresh)
            # Lets a client distinguish a filtered result from a server that
            # ignored ?search, rather than guessing from the response shape.
            response.headers["X-Files-Search"] = "1"
            return [_public(e) for e in _search(under(entries), search)]

        if q.get("recursive") is not None:
            entries, _ = await _catalog_get(root, fresh)
            return [_public(e) for e in under(entries)[:_LIST_CAP]]

        if not target.is_dir():
            return []
        sort_key = q.get("sort") if q.get("sort") in _SORTS else "name"
        desc = q.get("desc") is not None
        slice_ = await asyncio.to_thread(_scandir_slice, target, root)
        _catalog_warm(root)
        return [_public(e) for e in _sorted(slice_, sort_key, desc)]

    @r.get("/files/{path:path}")
    async def get_file(path: str, request: Request, ws: Workspace = ws_dep):
        file_path = _safe_path(ws.root, path)
        if file_path.is_dir():
            return _zip_dir(file_path)   # folders download as <name>.zip
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        # A design deck (its deck document or its .fig): ?as=slides is the deck
        # viewer's manifest, ?as=pptx / ?as=pdf the whole deck, exported on demand.
        if request.query_params.get("as") in _DESIGN_AS and _design_doc(file_path.name):
            return await _design_response(ws.root, file_path, request.query_params["as"], ws.subject)
        # ?as=slides previews a presentation as a slide viewer — a JSON manifest
        # of per-slide PNG data-URIs (office-render /v1/render). The canvas shows
        # the deck slide-by-slide rather than as a flat PDF.
        if request.query_params.get("as") == "slides" and office.presentation(file_path.name):
            try:
                slides = await _office_slides(ws.root, file_path, ws.subject)
            except office.Unavailable as e:
                raise HTTPException(status_code=415, detail=str(e))
            return FileResponse(slides, media_type="application/json", headers=_NO_CACHE)
        # ?as=pdf previews an Office document (docx/xlsx/…) by converting it to
        # PDF and serving that inline, so the canvas renders it in the viewer it
        # already has. No filename → inline, not a download.
        if request.query_params.get("as") == "pdf" and office.convertible(file_path.name):
            try:
                pdf = await _office_pdf(ws.root, file_path, ws.subject)
            except office.Unavailable as e:
                raise HTTPException(status_code=415, detail=str(e))
            return FileResponse(pdf, media_type="application/pdf", headers=_NO_CACHE)
        if request.query_params.get("download") is not None:
            return FileResponse(file_path, filename=file_path.name, headers=_NO_CACHE)
        if file_path.suffix.lower() == ".fig":
            # A design comes with its version, from the very bytes served: what a save
            # names as its base (design/store.py) — a save over a newer file is refused.
            from cycls._agent.design.store import version_of
            data = await asyncio.to_thread(file_path.read_bytes)
            return Response(data, media_type="application/octet-stream",
                            headers={**_NO_CACHE, "X-Version": version_of(data)})
        return FileResponse(file_path, headers=_NO_CACHE)

    @r.post("/deck/{path:path}")
    async def deck_op(path: str, request: Request, ws: Workspace = ws_dep):
        """The deck viewer's own slide changes — {op: "move" | "duplicate" | "delete",
        number, to?} (slides from 1) on a deck under designs/ (its deck document or .fig),
        run on the saved .fig through the design service like the agent's slide actions."""
        from cycls._agent import design
        from cycls._agent.design import deck as decks
        m = re.fullmatch(r"designs/([^/]+?)(?:\.deck\.json|\.fig)", path)
        if not m:
            raise HTTPException(404, "Not a deck")
        _safe_path(ws.root, path)
        body = await request.json()
        kind, number, to = body.get("op"), body.get("number"), body.get("to")
        if kind not in ("move", "duplicate", "delete") or not isinstance(number, int) or number < 1 \
                or (kind == "move" and (not isinstance(to, int) or to < 1)):
            raise HTTPException(400, "Expected {op: move|duplicate|delete, number, to?} with slides from 1")
        op = {"op": f"slide_{kind}", "index": number - 1, **({"to": to - 1} if kind == "move" else {})}
        try:
            r = await decks.apply_ops(ws.root, m.group(1), [op], user_id=ws.subject)
        except FileNotFoundError:
            raise HTTPException(404, "The deck's design file is missing")
        except design.Unavailable as e:
            raise HTTPException(415, str(e))
        except RuntimeError as e:
            raise HTTPException(422, str(e))
        return {"ok": True, "slides": len(r.get("slides") or [])}

    @r.post("/design/new")
    async def new_design(request: Request, ws: Workspace = ws_dep):
        """A blank design in the workspace — Cycls's "New design" (the canvas +, the
        Files panel, File › New design in the editor). {name?, size?: a preset
        ("square", "story", …) or [w, h], background?: "#hex"} → one frame, saved as
        designs/<name>.fig with its .png beside it, like a rendered design: the editor
        opens it, the refresh keeps the image current, the agent edits it by name."""
        from cycls._agent import design
        from cycls._agent.tools import _DESIGN_SIZES, _dedupe_design_name, _norm_hex
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
        _catalog_drop(ws.root)
        return {"path": f"designs/{base}.fig", "name": base, "size": wh}

    @r.get("/brand")
    async def brand(ws: Workspace = ws_dep):
        """The workspace brand kit (brand/brand.yaml) for the design editor: its named
        colours (the Brand variables) and fonts, or null when there's no kit."""
        from cycls._agent.tools import _brand_palette, _load_brand
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
        size}]} — or, with `?id=`, that version's bytes."""
        from cycls._agent import versions
        rel = _safe_path(ws.root, path).relative_to(Path(ws.root).resolve()).as_posix()
        if vid := request.query_params.get("id"):
            data = await asyncio.to_thread(versions.read, ws.root, rel, vid)
            if data is None:
                raise HTTPException(404, "No such version")
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
        _catalog_drop(ws.root)
        design_refresh.schedule(ws.root, rel, ws.subject)
        return {"ok": True, "version": version}

    @r.put("/files/{path:path}")
    async def put_file(path: str, request: Request, ws: Workspace = ws_dep):
        """Streams the raw body to a .part temp, then renames. No File(...)
        param — that reads the whole body before auth runs, so uploads longer
        than the JWT lifetime 401 at the end. Multipart kept for old clients.
        `?dedupe=1` writes a new file instead of replacing one — the name, or the
        next free one (`_free_rel`); the reply's `path` says which.

        A design (`.fig`) is written through `design.store.write_fig`: what it replaces
        is kept as a version, and `?base=<version>` (what `GET` served as X-Version)
        must still be current — else 412 {detail, version}, nothing written. `?force=1`
        writes anyway ("keep mine"). The reply carries the new `version`."""
        dedupe = request.query_params.get("dedupe") is not None
        if dedupe:
            _safe_path(ws.root, path)
            path = _free_rel(ws.root, unicodedata.normalize("NFC", path))
        file_path = _safe_path(ws.root, path)
        design_file = file_path.suffix.lower() == ".fig" and not dedupe
        limit_msg = f"File exceeds the {max_bytes // (1024 * 1024)} MB limit"
        if int(request.headers.get("content-length") or 0) > max_bytes:
            raise HTTPException(413, limit_msg)
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            form = await request.form()
            up = form.get("file")
            if up is None or isinstance(up, str):
                raise HTTPException(400, "multipart body missing 'file' field")
            async def _form_chunks(f=up):
                while chunk := await f.read(1 << 20):
                    yield chunk
            source = _form_chunks()
        else:
            source = request.stream()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # unique, and out of the way: a shared name lets two writers interleave into a torn file
        scratch = Path(ws.root) / ".tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        tmp = scratch / f"{uuid.uuid4().hex}.part"
        size = 0
        try:
            with open(tmp, "wb") as out:
                async for chunk in source:
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(413, limit_msg)
                    out.write(chunk)
            if not design_file:
                tmp.replace(file_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        rel = file_path.relative_to(Path(ws.root).resolve()).as_posix()
        reply = {"ok": True, "path": rel}
        if design_file:
            from cycls._agent.design.store import Stale, write_fig
            data = await asyncio.to_thread(tmp.read_bytes)
            tmp.unlink(missing_ok=True)
            force = request.query_params.get("force") is not None
            try:
                reply["version"] = await write_fig(ws.root, rel, data, base=request.query_params.get("base") or None,
                                                   by="user", reason="keep" if force else "save", force=force)
            except Stale as e:
                return JSONResponse(status_code=412, content={
                    "detail": "This design changed since it was opened.", "version": e.current})
        _catalog_drop(ws.root)
        # The design editor saves an edited designs/<name>.fig here; re-export the
        # image beside it so a download (or the agent) never gets the pre-edit one.
        # A new design (a copy, a version opened as one) has none yet: it gets its .png.
        design_refresh.schedule(ws.root, rel, ws.subject, ensure=dedupe)
        return reply

    @r.post("/files-batch/{path:path}")
    async def upload_batch(path: str, request: Request, ws: Workspace = ws_dep):
        """Zip batch from the FE — one request for a whole folder. Member
        paths pass the same traversal checks as any upload, all validated
        before anything is written."""
        _safe_path(ws.root, path)
        limit_msg = f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit"
        if int(request.headers.get("content-length") or 0) > max_bytes:
            raise HTTPException(413, limit_msg)
        size = 0
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, limit_msg)
                tmp.write(chunk)
            tmp.flush()
            tmp.seek(0)
            try:
                # Read from the open handle, not tmp.name — reopening a
                # NamedTemporaryFile by name fails on Windows (the file is still
                # locked by this handle).
                zf = zipfile.ZipFile(tmp)
            except zipfile.BadZipFile:
                raise HTTPException(400, "Body is not a valid zip")
            with zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                # Zip-bomb guard: the uncompressed total obeys the same cap.
                if sum(i.file_size for i in infos) > max_bytes:
                    raise HTTPException(413, limit_msg)
                targets = [(i, _safe_path(ws.root, f"{path}/{i.filename}" if path else i.filename))
                           for i in infos]
                sem = asyncio.Semaphore(8)

                scratch = Path(ws.root) / ".tmp"
                scratch.mkdir(parents=True, exist_ok=True)

                async def _extract(info, dest):
                    def _do():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        tmp = scratch / f"{uuid.uuid4().hex}.part"
                        try:
                            with zf.open(info) as src, open(tmp, "wb") as out:
                                shutil.copyfileobj(src, out, 1 << 20)
                            tmp.replace(dest)
                        finally:
                            tmp.unlink(missing_ok=True)
                    async with sem:
                        await asyncio.to_thread(_do)

                await asyncio.gather(*(_extract(i, d) for i, d in targets))
        _catalog_drop(ws.root)
        return {"ok": True, "files": len(targets)}

    @r.patch("/files/{path:path}")
    async def rename(path: str, request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        src = _safe_path(ws.root, path)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Not found")
        # a move out of apps/ removes an app as surely as a delete, and leaves no trash row
        rel = str(src.relative_to(Path(ws.root).resolve()))
        if trash.owned_by_app(rel) and not await _admin(cycls_app, user, ws, volume, base):
            raise HTTPException(status_code=403, detail="Only workspace admins can move apps")
        data = await request.json()
        dest = _safe_path(ws.root, data["to"])
        if dest.exists():
            raise HTTPException(status_code=409, detail="Destination already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        # shutil.move (not rename) so directory moves work on the gcsfuse
        # workspace mount, which doesn't support renaming directories — it falls
        # back to recursive copy + delete.
        was_app = trash.kind_of(rel, src.is_dir()) == "app"
        was_file = src.is_file()
        shutil.move(str(src), str(dest))
        dst = str(dest.relative_to(Path(ws.root).resolve()))
        if was_file:   # a design's history follows it (directory moves don't carry it)
            from cycls._agent import versions
            try:
                await asyncio.to_thread(versions.move, ws.root, Path(rel).as_posix(), Path(dst).as_posix())
            except OSError as e:   # the file has moved: its history staying behind must not fail the rename
                log("warn", message=f"history of {rel} did not follow it to {dst}: {type(e).__name__}: {e}")
        if was_app and trash.kind_of(dst, True) == "app":
            await _move_app_data(ws, rel.split("/")[1], dst.split("/")[1])
        _catalog_drop(ws.root)
        return {"ok": True}

    @r.post("/files/{path:path}")
    async def mkdir(path: str, ws: Workspace = ws_dep):
        dir_path = _safe_path(ws.root, path)
        dir_path.mkdir(parents=True, exist_ok=True)
        _catalog_drop(ws.root)
        return {"ok": True}

    # ---- Trash: a delete is a move (docs/notes/trash.md) ----

    @r.delete("/files/{path:path}")
    async def delete_path(path: str, ws: Workspace = ws_dep, user: Any = user_dep):
        target = _safe_path(ws.root, path)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Not found")
        rel = str(target.relative_to(Path(ws.root).resolve()))
        # Apps are shared team assets — only admins remove them.
        if trash.owned_by_app(rel) and not await _admin(cycls_app, user, ws, volume, base):
            raise HTTPException(status_code=403, detail="Only workspace admins can delete apps")
        meta = await asyncio.to_thread(trash.trash_path, ws.root, rel, "user")
        _catalog_drop(ws.root)
        return {"ok": True, "trash_id": meta["id"], "kind": meta["kind"]}

    async def _move_app_data(ws, old, new):
        """Renaming an app renames its shelf: the slug is the only thing joining them."""
        db, src = state.apps_db(ws), state.app_shelf(old)
        try:
            dst = state.app_shelf(new)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        await db.delete(dst)   # the folder was free, so rows there are a dead app's
        async for k, v in db.items(prefix=src):
            await db.put(dst + k[len(src):], v)
        await db.delete(src)

    async def _drop_app_data(ws, metas):
        """An app's rows outlive its folder until the trash entry goes for good."""
        db = state.apps_db(ws)
        for m in metas:
            if m and m.get("kind") == "app":
                await db.delete(state.app_shelf(m["path"].split("/")[1]))

    async def _trashed_chats(ws):
        rows = []
        async for cid, data in state.list_chats(ws):
            if at := data.get("deletedAt"):
                rows.append({"id": f"chat:{cid}", "path": data.get("title") or cid, "kind": "chat",
                             "by": "user", "deleted_at": at, "chat_id": cid})
        return rows

    @r.get("/trash")
    async def list_trash(ws: Workspace = ws_dep):
        """Files, apps and chats in one list, newest first. Listing is also the
        sweep: entries past TTL_DAYS go for good."""
        rows = await asyncio.to_thread(trash.list_trash, ws.root)
        cutoff = datetime.now(timezone.utc) - timedelta(days=trash.TTL_DAYS)
        for c in await _trashed_chats(ws):
            try:
                expired = datetime.fromisoformat(c["deleted_at"]) < cutoff
            except Exception:
                expired = True
            if expired:
                await state.delete_chat(ws, c["chat_id"])
            else:
                rows.append(c)
        rows.sort(key=lambda m: m["deleted_at"], reverse=True)
        return rows

    @r.post("/trash/{tid}/restore")
    async def restore_trash(tid: str, ws: Workspace = ws_dep):
        if tid.startswith("chat:"):
            cid = tid[5:]
            meta = await state.get_meta(ws, cid)
            if meta is None:
                raise HTTPException(status_code=404, detail="Not found")
            meta.pop("deletedAt", None)
            await state.put_meta(ws, cid, meta)
            return {"ok": True, "path": cid}
        try:
            path = await asyncio.to_thread(trash.restore, ws.root, tid)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Not found")
        _catalog_drop(ws.root)
        return {"ok": True, "path": path}

    @r.delete("/trash/{tid}")
    async def purge_trash(tid: str, ws: Workspace = ws_dep, user: Any = user_dep):
        if not await _admin(cycls_app, user, ws, volume, base):
            raise HTTPException(status_code=403, detail="Only workspace admins can delete forever")
        if tid.startswith("chat:"):
            await state.delete_chat(ws, tid[5:])
            spill.purge(ws.root, tid[5:])
            return {"ok": True}
        try:
            meta = await asyncio.to_thread(trash.purge, ws.root, tid)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Not found")
        await _drop_app_data(ws, [meta])
        return {"ok": True}

    @r.delete("/trash")
    async def empty_trash(ws: Workspace = ws_dep, user: Any = user_dep):
        if not await _admin(cycls_app, user, ws, volume, base):
            raise HTTPException(status_code=403, detail="Only workspace admins can delete forever")
        await _drop_app_data(ws, await asyncio.to_thread(trash.empty, ws.root))
        for c in await _trashed_chats(ws):
            await state.delete_chat(ws, c["chat_id"])
        return {"ok": True}

    return r


# ---- Share ----

APP_DATA_MAX = 1_000_000   # per row: a list reads every one of them, so a value is not a payload
APP_LIST_MAX = 10_000      # a backstop, not a policy: apps below it are never cut


def apps_router(cycls_app, ws_dep, user_dep, volume, base):
    """App data: the workspace's shelf, the viewer's own, and — for admins — everyone's."""
    r = APIRouter()

    def _manifest(ws, slug):
        try:
            return json.loads((Path(ws.root) / "apps" / slug / "app.json").read_text())
        except Exception:
            return {}

    async def _elevated(user, ws):
        """May this caller read other people's rows? `_admin` answers "is anyone
        above you?", which is yes-by-default where no ACL is configured — right
        for deleting an app, wrong for reading a colleague's. With workspaces off
        an org has no admin to be, and a personal account is alone in there."""
        if not getattr(getattr(cycls_app, "config", None), "workspaces", None):
            return not getattr(user, "org_id", None)
        return await _admin(cycls_app, user, ws, volume, base)

    async def _scope(slug, who, user, ws):
        """`who` -> a key builder for that audience, once the role allows it."""
        if who and who != "me" and not await _elevated(user, ws):
            raise HTTPException(403, "Only workspace admins reach other members' app data")
        kw = ({} if not who else {"user": state.actor_of(ws.subject)} if who == "me"
              else {"everyone": True} if who == "all" else {"user": who})

        def key(k):
            try:
                return state.app_shelf(slug, k, **kw)
            except ValueError as e:
                raise HTTPException(400, str(e))
        return key

    async def _may_write(slug, k, who, user, ws):
        if not k.strip("/"):
            raise HTTPException(400, "key required")
        if who or _manifest(ws, slug).get("write") != "admin":
            return
        if not await _admin(cycls_app, user, ws, volume, base):
            raise HTTPException(403, "Only workspace admins can write this app's shared data")

    @r.get("/apps/{slug}/data")
    async def list_data(slug: str, prefix: str = "", who: str = "", limit: int = APP_LIST_MAX,
                        ws: Workspace = ws_dep, user: Any = user_dep):
        # items() is one GET per row, so an uncapped list is one request fanning
        # out over the whole shelf. Narrow with `prefix`.
        key = await _scope(slug, who, user, ws)
        cap = max(1, min(limit, APP_LIST_MAX))
        root, out, seen = key(""), [], 0
        async for k, v in state.apps_db(ws).items(prefix=key(prefix), limit=cap + 1):
            seen += 1
            if seen > cap:
                break
            rel = k[len(root):]
            if not who and rel.split("/")[0] == state.USER_MARK:
                continue
            owner, _, rest = rel.partition("/")
            out.append({"user": owner, "key": rest, "value": v} if who == "all" else {"key": rel, "value": v})
        # `seen`, not len(out): a shared list drops u/ rows, and reporting on
        # what survived would call a truncated page complete.
        return {"rows": out, "truncated": seen > cap}

    @r.get("/apps/{slug}/data/{k:path}")
    async def get_data(slug: str, k: str, who: str = "",
                       ws: Workspace = ws_dep, user: Any = user_dep):
        key = await _scope(slug, who, user, ws)
        v, version = await state.apps_db(ws).get_gen(key(k))
        if v is None:
            raise HTTPException(404, "Not found")
        return {"value": v, "version": version}

    @r.put("/apps/{slug}/data/{k:path}")
    async def put_data(slug: str, k: str, request: Request, who: str = "",
                       version: Optional[str] = None,
                       ws: Workspace = ws_dep, user: Any = user_dep):
        body = await request.body()
        if len(body) > APP_DATA_MAX:
            raise HTTPException(413, "Value too large")
        key = await _scope(slug, who, user, ws)
        await _may_write(slug, k, who, user, ws)
        try:
            value = json.loads(body)
        except ValueError:
            raise HTTPException(400, "Body must be JSON")
        # No `version` is last-write-wins, which is what `set` means. With one,
        # the write lands only if nothing changed — "" meaning it must be new.
        cond = {} if version is None else ({"create": True} if version == "" else {"gen": version})
        try:
            await state.apps_db(ws).put(key(k), value, **cond)
        except Conflict:
            raise HTTPException(412, "changed since it was read")
        return {"ok": True}

    @r.delete("/apps/{slug}/data/{k:path}")
    async def delete_data(slug: str, k: str, who: str = "",
                          ws: Workspace = ws_dep, user: Any = user_dep):
        key = await _scope(slug, who, user, ws)
        await _may_write(slug, k, who, user, ws)
        await state.apps_db(ws).delete(key(k))
        return {"ok": True}

    return r


# ---- Live polls (a deck's poll slides, run in present mode) ----
#
# The presenter opens a slide's poll; the audience votes on their phones through the
# deck's public share link; the presenter's screen polls the tally. The server runs
# on several instances, so nothing is pushed or held in memory: each vote is its own
# record, written create-only (one per voter per session — a second is a 409), and
# the tally is one listing of a session's votes, cached for a second so a room full
# of phones doesn't list once each. Polls live beside the deck's share row — the
# presenter's own store, which the share route reaches as the link's owner.

POLL_VOTES_PER_MINUTE = 20   # per address, per instance — bounds a runaway, not a determined voter
_poll_hits = {}
_poll_tallies = {}           # (store, deck, session) → (monotonic time, tally)


def _poll_key(deck):
    return "polls/" + hashlib.sha1(deck.encode()).hexdigest()[:16]


def _poll_deck(value):
    deck = str(value or "")
    if not deck.endswith((".deck.json", ".fig")) or ".." in deck.split("/") or deck.startswith("/") or len(deck) > 400:
        raise HTTPException(400, "deck must be a deck document path")
    return deck


def _vote_budget(address):
    now = int(time.time() // 60)
    minute, n = _poll_hits.get(address, (now, 0))
    if minute != now: minute, n = now, 0
    _poll_hits[address] = (minute, n + 1)
    if len(_poll_hits) > 10_000: _poll_hits.clear()
    return n < POLL_VOTES_PER_MINUTE


async def _poll_tally(ws, deck, session, n, fresh=False):
    key = (getattr(ws, "path", ""), deck, session)
    hit = _poll_tallies.get(key)
    if hit and not fresh and time.monotonic() - hit[0] < 1:
        return hit[1]
    counts = [0] * n
    async for _, meta in DB(ws).scan(prefix=f"{_poll_key(deck)}/{session}/v/"):
        try:
            i = int((meta or {}).get("opt"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            counts[i] += 1
    tally = {"session": session, "counts": counts, "total": sum(counts)}
    if len(_poll_tallies) > 2_000: _poll_tallies.clear()
    _poll_tallies[key] = (time.monotonic(), tally)
    return tally


def share_router(cycls_app, ws_dep, user_dep, volume, base):
    r = APIRouter()
    bearer_scheme = HTTPBearer(auto_error=False)
    mode = getattr(getattr(cycls_app, "config", None), "workspaces", None)

    async def _locate(user: str, token: str, ws_q=None):
        """Find the share row in whichever of the owner's workspaces minted it.
        Minted URLs carry `?ws=`; bare legacy links fall back to the owner's
        personal workspace, then General. Audience is NOT checked here."""
        candidates = [ws_q] if ws_q else ([personal_ws(user), "t-shared"] if mode else [None])
        for ws_id in candidates:
            try:
                ws_owner = workspace(user, volume, base=base, ws=ws_id)
            except ValueError:
                break
            row = await state.find_share(ws_owner, token)
            if row is not None:
                return ws_owner, row
        return None

    async def _resolve_or_403(user: str, token: str, bearer, ws_q=None):
        """404 no such share · 401 audience needs a viewer we couldn't identify
        (sign in) · 403 identified but outside the audience. The client needs
        these apart: 401 is recoverable by signing in, 403 never is."""
        from cycls._app.auth import authenticate
        requester = None
        if bearer and cycls_app._auth_provider is not None:
            try:
                requester = authenticate(cycls_app._auth_provider, cycls_app.prod, bearer.credentials)
            except Exception as e:
                # Silently dropping this made every cause look like a dead link.
                log("warn", chat_id=None, message=f"share token rejected: {type(e).__name__}: {e}")
        found = await _locate(user, token, ws_q)
        if found is None:
            raise HTTPException(404, "This link doesn't exist")
        ws_owner, row = found
        if not state.share_allows(row, requester):
            if requester is None:
                raise HTTPException(401, "Sign in to view this")
            raise HTTPException(403, "This link isn't shared with your account")
        return found

    # ---- Owner side ----

    @r.post("/share")
    async def create_share(request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        data = await request.json()
        path = data.get("path")
        if not (path and (path.startswith("chat/") or path.startswith("file/"))):
            raise HTTPException(400, "path must be 'chat/<id>' or 'file/<path>'")
        if path.startswith("chat/") and (await state.get_meta(ws, path[5:])) is None:
            raise HTTPException(404, "Chat not found")
        token = secrets.token_urlsafe(16)
        row = {"path": path, "audience": data.get("audience", "public"),
               "shared_at": datetime.now(timezone.utc).isoformat()}
        # Author fields are flat str:str so the row stays meta-eligible (O(1) scan).
        for k in ("author_name", "author_image_url", "author_org_name", "author_org_image_url"):
            if (v := data.get(k)): row[k] = v
        await DB(ws).put(f"share/{token}", row, meta=row)
        return {"token": token, "url": _share_url(ws, token), **row}

    @r.get("/share")
    async def list_shares(ws: Workspace = ws_dep):
        # Two LIST calls regardless of N: shares + chat indexes.
        db = DB(ws)
        chat_titles = {k.split("/")[1]: m.get("title", "")
                       async for k, m in db.scan(glob="chat/*/index")}
        out = []
        async for key, meta in db.scan(prefix="share/"):
            token = key[6:]
            if not meta.get("path"):   # meta channel wiped (gcsfuse move) — body is canonical
                body = await db.get(key)
                if isinstance(body, dict) and body.get("path"):
                    meta = body
                    await db.put(key, body, meta={k: v for k, v in body.items() if isinstance(v, str)})
            path = meta.get("path", "")
            if path.startswith("chat/"):
                title = chat_titles.get(path[5:], "")
            else:
                title = path[5:]
            out.append({"token": token, "url": _share_url(ws, token), "title": title, **meta})
        out.sort(key=lambda s: s.get("shared_at", ""), reverse=True)
        return out

    @r.delete("/share/{token}")
    async def revoke_share(token: str, ws: Workspace = ws_dep):
        await DB(ws).delete(f"share/{token}")
        return {"ok": True}

    # ---- Viewer side ----

    @r.get("/share/{user}/{token}/data")
    async def resolve_share(
        user: str, token: str, ws: Optional[str] = None,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        ws_owner, row = await _resolve_or_403(user, token, bearer, ws)
        path = row["path"]
        common = {k: row[k] for k in
                  ("shared_at", "author_name", "author_image_url", "author_org_name", "author_org_image_url")
                  if k in row}
        suffix = f"?ws={ws_owner.ws}" if ws_owner.ws else ""
        if path.startswith("chat/"):
            chat_id = path[5:]
            meta = await state.get_meta(ws_owner, chat_id)
            if meta is None:
                raise HTTPException(404, "Chat not found")
            messages = to_ui_messages(await state.load_messages(ws_owner, chat_id))
            for m in messages:
                for att in m.get("attachments") or []:
                    if ap := att.get("path"):
                        att["url"] = f"/share/{user}/{token}/file/{ap}{suffix}"
            return {"type": "chat", "id": chat_id, "title": meta.get("title", ""),
                    "messages": messages, **common}
        return {"type": "file", "path": path[5:],
                "url": f"/share/{user}/{token}/file/{path[5:]}{suffix}", **common}

    @r.get("/share/{user}/{token}/file/{file_path:path}")
    async def shared_attachment(
        user: str, token: str, file_path: str, request: Request, ws: Optional[str] = None,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        ws_owner, row = await _resolve_or_403(user, token, bearer, ws)
        path = row["path"]
        # Authorize: file_path must be the share's file (file share), or part of
        # its chat's shareable surface — an attachment, or a canvas artifact the
        # conversation produced (the shared page shows the chat WITH its output).
        if path.startswith("file/"):
            if file_path != path[5:]:
                raise HTTPException(403, "Path not in this share")
        else:
            ui = to_ui_messages(await state.load_messages(ws_owner, path[5:]))
            allowed = {att.get("path") for m in ui
                       for att in (m.get("attachments") or []) if att.get("path")}
            allowed.update(canvas_files(ui))
            if file_path not in allowed:
                raise HTTPException(403, "Not an attachment of this share")
        # ?as=slides / ?as=pdf preview an Office file (read-only — shares aren't
        # editable). Same convert+cache path as get_file, over the owner's
        # workspace. Presentations get the slide viewer; everything else, PDF.
        as_ = request.query_params.get("as")
        # A shared deck presents and downloads like the owner's (the share covers
        # the deck document; the .fig it names stays inside the owner's workspace).
        if as_ in _DESIGN_AS and _design_doc(file_path):
            try:
                target = resolve_path(ws_owner.root, file_path)
            except ValueError:
                raise HTTPException(403, "Path traversal denied")
            if not target.is_file():
                raise HTTPException(404, "File not found")
            return await _design_response(ws_owner.root, target, as_, ws_owner.subject)
        if as_ in ("slides", "pdf") and office.convertible(file_path):
            try:
                target = resolve_path(ws_owner.root, file_path)
            except ValueError:
                raise HTTPException(403, "Path traversal denied")
            if not target.is_file():
                raise HTTPException(404, "File not found")
            try:
                if as_ == "slides" and office.presentation(file_path):
                    slides = await _office_slides(ws_owner.root, target, ws_owner.subject)
                    return FileResponse(slides, media_type="application/json", headers=_NO_CACHE)
                pdf = await _office_pdf(ws_owner.root, target, ws_owner.subject)
            except office.Unavailable as e:
                raise HTTPException(415, str(e))
            return FileResponse(pdf, media_type="application/pdf", headers=_NO_CACHE)
        return _serve_file(ws_owner.root, file_path)

    # ---- Examples (curated public shares — the empty-screen gallery) ----

    _examples_cache = {"at": 0.0, "data": None}

    async def _example_card(entry):
        """One configured entry → a gallery card, or None (bad URL, dead
        token, non-public, not a chat). A {video, title} entry is a tutorial
        card and needs no resolution — the FE previews the clip and plays it
        in-page. Author fields are deliberately absent: examples read as
        product showcase, not user content."""
        if isinstance(entry, str):
            entry = {"share": entry}
        if entry.get("video"):
            return {"video": entry["video"], "title": entry.get("title", "")}
        url = entry.get("share", "")
        parts = urlsplit(url)
        seg = parts.path.strip("/").split("/")
        if len(seg) != 3 or seg[0] != "shared":
            log("warn", chat_id=None, message=f"examples: not a share URL: {url}")
            return None
        user, token = seg[1], seg[2]
        ws_q = (parse_qs(parts.query).get("ws") or [None])[0]
        found = await _locate(user, token, ws_q)
        if found is None:
            log("warn", chat_id=None, message=f"examples: share not found: {url}")
            return None
        ws_owner, row = found
        if row.get("audience", "public") != "public" or not row.get("path", "").startswith("chat/"):
            log("warn", chat_id=None, message=f"examples: needs a public chat share: {url}")
            return None
        chat_id = row["path"][5:]
        meta = await state.get_meta(ws_owner, chat_id)
        if meta is None:
            return None
        messages = to_ui_messages(await state.load_messages(ws_owner, chat_id))
        prompt = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        suffix = f"?ws={ws_owner.ws}" if ws_owner.ws else ""
        file = None
        if produced := canvas_files(messages):
            fp = produced[-1]   # the conversation's final artifact
            file = {"path": fp, "name": fp.split("/")[-1],
                    "url": f"/share/{user}/{token}/file/{fp}{suffix}"}
        sep = "&" if suffix else "?"
        return {"share": f"/shared/{user}/{token}{suffix}{sep}example=1",
                "title": meta.get("title", ""), "prompt": prompt, "file": file}

    @r.get("/examples")
    async def examples(response: Response):
        """Resolved example cards for the gallery. Public — this is what the
        signed-out empty screen renders. Cached like /explore: the cards only
        move when the operator re-curates or the source chats change."""
        response.headers["Cache-Control"] = "public, max-age=300"
        groups = getattr(getattr(cycls_app, "config", None), "examples", None)
        if not groups:
            return {"categories": []}
        if _examples_cache["data"] is None or time.time() - _examples_cache["at"] > 300:
            cats = []
            for g in groups:
                items = [c for u in g.get("urls", []) if (c := await _example_card(u))]
                if items:
                    cats.append({"label": g.get("label", ""), "label_ar": g.get("label_ar"),
                                 "items": items})
            _examples_cache.update(at=time.time(), data={"categories": cats})
        return _examples_cache["data"]

    @r.post("/share/{user}/{token}/fork")
    async def fork_share(user: str, token: str, ws: Optional[str] = None,
                         forker: Any = user_dep, ws_fork: Workspace = ws_dep):
        # `forker` is already authenticated (user_dep), so it IS the requester.
        found = await _locate(user, token, ws)
        if found is None:
            raise HTTPException(404, "This link doesn't exist")
        ws_source, row = found
        if not state.share_allows(row, forker):
            raise HTTPException(403, "This link isn't shared with your account")
        if not row["path"].startswith("chat/"):
            raise HTTPException(400, "Only chat shares can be forked")
        source_id = row["path"][5:]
        meta = await state.get_meta(ws_source, source_id)
        if meta is None:
            raise HTTPException(404, "Chat not found")
        raw = await state.load_messages(ws_source, source_id)
        new_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        await state.put_meta(ws_fork, new_id, {
            **{k: v for k, v in meta.items() if k not in ("id", "createdAt", "updatedAt")},
            "id": new_id, "createdAt": now, "updatedAt": now,
            "forked_from": f"{user}/{source_id}",
        })
        await state.append_messages(ws_fork, new_id, raw, 0)
        # The fork gets the conversation's whole surface: attachments AND the
        # canvas artifacts it produced, so "continue" lands with the output
        # sitting in the forker's workspace, ready to iterate on.
        ui = to_ui_messages(raw)
        paths = [ap for m in ui for att in (m.get("attachments") or []) if (ap := att.get("path"))]
        paths += canvas_files(ui)
        for ap in dict.fromkeys(paths):
            try:
                src = resolve_path(ws_source.root, ap)
                dst = resolve_path(ws_fork.root, ap)
                # a fork only ADDS: overwriting is an arbitrary write from a public link, and
                # AGENT.md reaches the system prompt, so it is never copied at all
                if not src.is_file() or dst.exists() or Path(ap).name.lower() == "agent.md":
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except Exception:
                pass
        return {"id": new_id}

    # ---- Live polls: the presenter ----

    @r.post("/polls")
    async def open_poll(request: Request, ws: Workspace = ws_dep):
        """Open (or restart) a deck's poll: a fresh session, so earlier votes don't count."""
        data = await request.json()
        deck = _poll_deck(data.get("deck"))
        question = str(data.get("question") or "").strip()[:300]
        options = [str(o).strip()[:120] for o in (data.get("options") or []) if str(o).strip()][:6]
        if not question or len(options) < 2:
            raise HTTPException(400, "a poll needs a question and 2–6 options")
        current = {"deck": deck, "slide": int(data.get("slide") or 0), "question": question, "options": options,
                   "session": secrets.token_hex(8), "open": True, "opened_at": datetime.now(timezone.utc).isoformat()}
        await DB(ws).put(f"{_poll_key(deck)}/current", current)
        return current

    @r.post("/polls/close")
    async def close_poll(request: Request, ws: Workspace = ws_dep):
        deck = _poll_deck((await request.json()).get("deck"))
        current = await DB(ws).get(f"{_poll_key(deck)}/current")
        if current and current.get("open"):
            await DB(ws).put(f"{_poll_key(deck)}/current", {**current, "open": False})
        return {"ok": True}

    @r.get("/polls/results")
    async def poll_results(deck: str, session: str, ws: Workspace = ws_dep):
        deck = _poll_deck(deck)
        current = await DB(ws).get(f"{_poll_key(deck)}/current") or {}
        if current.get("session") != session:
            raise HTTPException(404, "no such poll")
        return await _poll_tally(ws, deck, session, len(current.get("options") or []))

    # ---- Live polls: the audience, through the deck's share link ----

    def _shared_deck(row):
        path = (row or {}).get("path", "")
        if not (path.startswith("file/") and path.endswith((".deck.json", ".fig"))):
            raise HTTPException(404, "This link isn't a deck")
        return path[5:]

    @r.get("/share/{user}/{token}/poll")
    async def shared_poll(
        user: str, token: str, ws: Optional[str] = None,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        """The poll the presenter has open on this deck, if any."""
        ws_owner, row = await _resolve_or_403(user, token, bearer, ws)
        current = await DB(ws_owner).get(f"{_poll_key(_shared_deck(row))}/current")
        if not current or not current.get("open"):
            return {"open": False}
        return {k: current[k] for k in ("open", "session", "question", "options", "slide")}

    @r.post("/share/{user}/{token}/poll/vote")
    async def shared_vote(
        request: Request, user: str, token: str, ws: Optional[str] = None,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        """One vote per voter per session — create-only, so a second is a 409."""
        if not _vote_budget(request.client.host if request.client else "?"):
            raise HTTPException(429, "Too many votes from here — wait a minute")
        raw = await request.body()
        if len(raw) > 2048:
            raise HTTPException(413, "vote too large")
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise HTTPException(400, "not JSON")
        ws_owner, row = await _resolve_or_403(user, token, bearer, ws)
        deck = _shared_deck(row)
        current = await DB(ws_owner).get(f"{_poll_key(deck)}/current")
        if not current or not current.get("open") or data.get("session") != current.get("session"):
            raise HTTPException(409, "This poll has closed")
        option, voter = data.get("option"), str(data.get("voter") or "")
        if not isinstance(option, int) or isinstance(option, bool) or not 0 <= option < len(current["options"]):
            raise HTTPException(400, "pick one of the options")
        if not re.fullmatch(r"[0-9a-f]{32}", voter):
            raise HTTPException(400, "bad voter")
        try:
            await DB(ws_owner).put(f"{_poll_key(deck)}/{current['session']}/v/{voter}", {"opt": option},
                                   meta={"opt": str(option)}, create=True)
        except Conflict:
            raise HTTPException(409, "You've already voted")
        return await _poll_tally(ws_owner, deck, current["session"], len(current["options"]), fresh=True)

    @r.get("/share/{user}/{token}/poll/results")
    async def shared_poll_results(
        user: str, token: str, session: str, ws: Optional[str] = None,
        bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ):
        ws_owner, row = await _resolve_or_403(user, token, bearer, ws)
        deck = _shared_deck(row)
        current = await DB(ws_owner).get(f"{_poll_key(deck)}/current") or {}
        if current.get("session") != session:
            raise HTTPException(404, "no such poll")
        return await _poll_tally(ws_owner, deck, session, len(current.get("options") or []))

    return r


def _share_url(ws, token):
    """Viewer URL for a share — carries the minting workspace so the viewer
    endpoints can find the row without guessing."""
    return f"/shared/{ws.subject}/{token}" + (f"?ws={ws.ws}" if ws.ws else "")


def _serve_file(root, file_path):
    try:
        target = resolve_path(root, file_path)
    except ValueError:
        raise HTTPException(403, "Path traversal denied")
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(target, headers=_NO_CACHE)


def _zip_dir(dir_path):
    """Stream a directory back as a .zip (skips hidden/.db entries). Built to a
    temp file, then served and cleaned up — avoids holding it all in memory."""
    import zipfile, tempfile
    from starlette.background import BackgroundTask
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in dir_path.rglob("*"):
            if f.is_file() and not any(p.startswith(".") for p in f.relative_to(dir_path).parts):
                zf.write(f, f.relative_to(dir_path.parent))   # keep the folder as the top dir
    return FileResponse(tmp.name, filename=f"{dir_path.name}.zip", media_type="application/zip",
                        headers=_NO_CACHE, background=BackgroundTask(lambda: os.unlink(tmp.name)))


# ---- Workspaces (registry + members — docs/workspaces.md) ----

def workspaces_router(cycls_app, user_dep, volume, base):
    """Workspace lifecycle + member management. Content access control lives in
    `resolve_ws_id`; this router owns create/rename/delete and the ACL rows."""
    r = APIRouter()
    mode = getattr(getattr(cycls_app, "config", None), "workspaces", None)

    def _orgdb(user):
        return state.org_db(state.org_of(user), volume, base)

    def _name_or_400(data):
        name = (data.get("name") or "").strip()
        if not 1 <= len(name) <= 80:
            raise HTTPException(400, "name must be 1-80 characters")
        return name

    def _icon_or_400(data):
        """Workspace icon — exactly one emoji (ZWJ sequences, flags, skin
        tones, keycaps included). Validated server-side so every client shares
        one icon vocabulary regardless of its picker UI. Loosen deliberately
        if icons ever grow beyond emoji (e.g. uploaded image URLs)."""
        icon = data.get("icon")
        if icon and (not isinstance(icon, str) or len(icon) > 64 or not _is_emoji(icon)):
            raise HTTPException(400, "icon must be a single emoji")
        return icon

    async def _reserved_name_or_409(orgdb, name, exclude=None):
        """Team names are labels, not addresses: workspaces are id-addressed
        and visibility is membership-scoped, so duplicates are allowed (an
        org-wide check would also leak hidden workspaces' existence). Only
        the two names in everyone's list are reserved — Personal and the
        General workspace's current name. Casefold: Arabic has no case."""
        if name.casefold() == "personal":
            raise HTTPException(409, "A workspace with this name already exists")
        if exclude != "t-shared":
            general = await orgdb.get("workspaces/t-shared")
            if general and (general.get("name") or "").casefold() == name.casefold():
                raise HTTPException(409, "A workspace with this name already exists")

    async def _role_or_404(user, ws_id):
        role = await state.resolve_role(user, ws_id, _orgdb(user))
        if role is None:
            raise HTTPException(404, "Workspace not found")
        return role

    async def _manager_or_403(user, ws_id):
        if not ws_id.startswith("t-"):
            raise HTTPException(404, "Workspace not found")
        if await _role_or_404(user, ws_id) not in ("owner", "admin"):
            raise HTTPException(403, "Managing this workspace requires owner or admin")

    @r.get("/workspaces")
    async def list_workspaces(request: Request, user: Any = user_dep):
        await state.ensure_general(user, volume, base)
        orgdb = _orgdb(user)
        out = [{"id": f"u-{user.id}", "name": "Personal", "type": "personal", "role": "owner"}]
        if _is_org_admin(user) and request.query_params.get("all") is not None:
            # Lifecycle view (offboarding): every team workspace + every personal
            # dir. Names/ids only — content stays behind the owner-only check.
            async for _, row in orgdb.scan(prefix="workspaces/"):
                out.append({**row, "role": "admin"})
            ws_dir = Path(volume) / state.org_of(user) / "ws"
            dirs = await asyncio.to_thread(
                lambda: [e.name for e in os.scandir(ws_dir) if e.is_dir()] if ws_dir.is_dir() else [])
            out += [{"id": d, "name": d[2:], "type": "personal", "role": None}
                    for d in sorted(dirs) if d.startswith("u-") and d != f"u-{user.id}"]
            return out
        # Two LISTs total — my member rows and the registry — joined in
        # memory; per-team gets would be 2K roundtrips on object storage.
        members = {k.split("/")[1]: m async for k, m in orgdb.scan(glob=f"members/*/{user.id}")}
        regs = {k.split("/")[-1]: row async for k, row in orgdb.scan(prefix="workspaces/")}
        for ws_id, member in members.items():
            reg = regs.get(ws_id)
            if reg and not reg.get("builtin") and member.get("role") != "excluded":
                out.append({**reg, "role": member.get("role")})
        # General: every org member by default; admins immune to exclusion.
        if getattr(user, "org_id", None) and (reg := regs.get("t-shared")) and reg.get("builtin"):
            if _is_org_admin(user):
                out.append({**reg, "role": "admin"})
            elif members.get("t-shared", {}).get("role") != "excluded":
                out.append({**reg, "role": "editor"})
        return out

    @r.post("/workspaces")
    async def create_workspace(request: Request, user: Any = user_dep):
        if mode == "admin" and not _is_org_admin(user):
            raise HTTPException(403, "Only org admins can create team workspaces")
        if not getattr(user, "org_id", None):
            raise HTTPException(400, "Team workspaces require an organization")
        data = await request.json()
        name = _name_or_400(data)
        await state.ensure_general(user, volume, base)
        orgdb = _orgdb(user)
        await _reserved_name_or_409(orgdb, name)
        return await state.create_team_ws(orgdb, name, user.id,
                                          icon=_icon_or_400(data))

    @r.patch("/workspaces/{ws_id}")
    async def update_workspace(ws_id: str, request: Request, user: Any = user_dep):
        await _manager_or_403(user, ws_id)
        data = await request.json()
        orgdb = _orgdb(user)
        row = {**(await orgdb.get(f"workspaces/{ws_id}") or {})}
        # On General, manager status derives solely from org membership
        # (resolve_role's builtin branch), so name/icon edits there are
        # org-admin-only without any extra check.
        if "name" in data:
            name = _name_or_400(data)
            await _reserved_name_or_409(orgdb, name, exclude=ws_id)
            row["name"] = name
        if "icon" in data:
            if icon := _icon_or_400(data):
                row["icon"] = icon
            else:
                row.pop("icon", None)   # empty/null clears it, Notion-style
        await orgdb.put(f"workspaces/{ws_id}", row, meta=row)
        return row

    @r.delete("/workspaces/{ws_id}")
    async def delete_workspace(ws_id: str, user: Any = user_dep):
        if ws_id.startswith("u-"):
            # Personal: the owner themselves, or an org admin (lifecycle —
            # offboarding). Admins never gain content routes on it.
            if ws_id != f"u-{user.id}" and not _is_org_admin(user):
                raise HTTPException(404, "Workspace not found")
        elif await _role_or_404(user, ws_id) != "owner" and not _is_org_admin(user):
            raise HTTPException(403, "Deleting a team workspace requires its owner")
        builtin = await _is_builtin(user, ws_id)
        await state.wipe_workspace(state.org_of(user), ws_id, volume, base)
        if builtin:
            # Tombstone: blocks lazy re-provisioning — deleting General is permanent.
            row = {"id": ws_id, "deleted": datetime.now(timezone.utc).isoformat()}
            await _orgdb(user).put(f"workspaces/{ws_id}", row, meta=row)
        return {"ok": True}

    # ---- Members (team workspaces only) ----

    async def _is_builtin(user, ws_id):
        reg = await _orgdb(user).get(f"workspaces/{ws_id}")
        return bool(reg and reg.get("builtin"))

    @r.get("/workspaces/{ws_id}/members")
    async def list_members(ws_id: str, user: Any = user_dep):
        if not ws_id.startswith("t-"):
            raise HTTPException(404, "Workspace not found")
        await _role_or_404(user, ws_id)   # any member (or org admin) may look
        # On General the rows are exclusions — membership is the org minus these.
        return [{"user_id": key.rsplit("/", 1)[1], **row}
                async for key, row in _orgdb(user).scan(prefix=f"members/{ws_id}/")]

    @r.put("/workspaces/{ws_id}/members/{member_id}")
    async def put_member(ws_id: str, member_id: str, request: Request, user: Any = user_dep):
        await _manager_or_403(user, ws_id)
        role = (await request.json()).get("role", "editor")
        if role not in ("admin", "editor"):
            raise HTTPException(400, 'role must be "admin" or "editor"')
        orgdb = _orgdb(user)
        if await _is_builtin(user, ws_id):
            # Everyone is in General by default — "adding" clears an exclusion.
            await orgdb.delete(f"members/{ws_id}/{member_id}")
            return {"user_id": member_id, "role": "editor"}
        existing = await orgdb.get(f"members/{ws_id}/{member_id}")
        if existing and existing.get("role") == "owner":
            raise HTTPException(403, "The owner's role cannot be changed")
        row = {"role": role, "added_by": user.id,
               "added_at": datetime.now(timezone.utc).isoformat()}
        await orgdb.put(f"members/{ws_id}/{member_id}", row, meta=row)
        return {"user_id": member_id, **row}

    @r.delete("/workspaces/{ws_id}/members/{member_id}")
    async def remove_member(ws_id: str, member_id: str, user: Any = user_dep):
        orgdb = _orgdb(user)
        builtin = await _is_builtin(user, ws_id)
        if member_id == user.id and not builtin:
            await _role_or_404(user, ws_id)   # leaving requires being in it
        else:
            await _manager_or_403(user, ws_id)   # on General: org admins only
        if builtin:
            # Membership of General is the org itself — removal writes an
            # exclusion marker instead. Org admins are immune (resolve_role
            # ignores the marker for them; they could reverse it anyway).
            row = {"role": "excluded", "added_by": user.id,
                   "added_at": datetime.now(timezone.utc).isoformat()}
            await orgdb.put(f"members/{ws_id}/{member_id}", row, meta=row)
            return {"ok": True}
        existing = await orgdb.get(f"members/{ws_id}/{member_id}")
        if existing and existing.get("role") == "owner":
            raise HTTPException(403, "The owner cannot be removed")
        await orgdb.delete(f"members/{ws_id}/{member_id}")
        return {"ok": True}

    return r


# ---- Connectors ----

RELAY_PER_MINUTE = 240   # per instance — bounds a runaway, not a determined caller
_relay_hits = {}


def _relay_budget(subject, name):
    """Under the per-minute cap? In memory: a shared counter is a round trip per call."""
    now, key = int(time.time() // 60), (subject, name)
    minute, n = _relay_hits.get(key, (now, 0))
    if minute != now: minute, n = now, 0
    _relay_hits[key] = (minute, n + 1)
    if len(_relay_hits) > 10_000: _relay_hits.clear()
    return n < RELAY_PER_MINUTE


def connectors_router(cycls_app, ws_dep, user_dep, volume, base):
    """Connect, list and disconnect grants. The callback is reached by the
    provider's redirect — no JWT — so it trusts the signed state, which names
    the user and workspace; the PKCE verifier waits in the user's own slot."""
    from fastapi.responses import HTMLResponse
    r = APIRouter()
    reg = {o.name: o for o in cycls_app.connectors}

    def _get(name):
        if name not in reg:
            raise HTTPException(status_code=404, detail="Unknown connector")
        return reg[name]

    def _org_admin(user):
        return bool(getattr(user, "org_id", None)) and _is_org_admin(user)

    def _team(ws):
        return bool(ws.ws) and not ws.ws.startswith("u-")

    cms = getattr(getattr(cycls_app, "config", None), "cms", None) or {}
    cms_headers = {"Authorization": f"Bearer {cms['token']}"} if cms.get("token") else {}

    @r.get("/connectors")
    async def list_connectors(ws: Workspace = ws_dep, user: Any = user_dep):
        admin = any(o.scope != "user" for o in reg.values()) and await _admin(cycls_app, user, ws, volume, base)
        off, org_admin = await oauth.blocked(ws), _org_admin(user)   # members never see what an admin switched off
        mine = await oauth.off(ws)   # what this person switched off: still listed, still connected, just not in a turn
        rows = await oauth.cms_rows(cms.get("connectors"), cms_headers)   # copy the team edits, code still wins
        team = None   # the team workspace's name — the button says where a shared grant lands
        if _team(ws):
            row = await state.org_db(state.org_of(user), volume, base).get(f"workspaces/{ws.ws}")
            team = (row or {}).get("name") or ws.ws
        out = []
        for n, o in reg.items():
            if n in off and not org_admin:
                continue
            grant, shared = await credentials.find(ws, n)
            row = rows.get(n, {})
            out.append({"name": n, "kind": o.kind, "hint": o.hint, "scope": o.scope,
                        "title": oauth.bilingual(o.title, row.get("title")),
                        "description": oauth.bilingual(o.description, row.get("description")),
                        "category": oauth.bilingual(o.category, row.get("category")),
                        "about": o.about, "story": oauth.bilingual(row.get("story")),   # plain from code, html from the CMS
                        "icon": o.icon or row.get("icon") or None,
                        "prompts": [p for p in (oauth.bilingual(x) for x in (o.prompts or row.get("prompts") or [])) if p],
                        "showcase": row.get("showcase") or "prompts", "gallery": row.get("gallery") or [],
                        "gradient": row.get("gradient") or None, "links": oauth.links_of(row, o),
                        "use_cases": o.use_cases, "skills": o.skills,
                        "developer": o.developer or row.get("developer") or None, "website": o.website,
                        "privacy": o.privacy, "terms": o.terms, "docs": o.docs, "team": team,
                        "admin": admin, "allowed": n not in off, "org_admin": org_admin, "connected": grant is not None,
                        "on": n not in mine, "connected_as": ("workspace" if shared else "user") if grant else None})
        return out

    async def _slot_or_4xx(o, scope, user, ws):
        try:
            chosen = o.slot(scope)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if chosen == "workspace" and not _team(ws):
            raise HTTPException(status_code=400, detail="No workspace to share with here")
        if chosen == "workspace" and not await _admin(cycls_app, user, ws, volume, base):
            raise HTTPException(status_code=403, detail="Only workspace admins can manage a team connection")
        return chosen

    async def _connect_slot(o, scope, user, ws):
        if o.name in await oauth.blocked(ws):
            raise HTTPException(status_code=403, detail="Switched off by an org admin")
        return await _slot_or_4xx(o, scope, user, ws)

    @r.patch("/connectors/{name}")
    async def allow(name: str, request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        """Two switches, one route: `allowed` is the org admin's, for everyone; `on` is the person's own,
        which keeps the grant and only keeps the tools out of their turns."""
        _get(name)
        data = await request.json()
        if "on" in data:
            on = bool(data["on"])
            await oauth.set_off(ws, name, not on)
            log("connector", user=user, action="on" if on else "off", connector=name)
            return {"on": on}
        if not _org_admin(user):
            raise HTTPException(status_code=403, detail="Only org admins can switch a connector off")
        allowed = bool(data.get("allowed"))
        await oauth.set_blocked(ws, name, not allowed)
        log("connector", user=user, action="allowed" if allowed else "blocked", connector=name)
        return {"allowed": allowed}

    @r.post("/connectors/{name}/authorize")
    async def authorize(name: str, request: Request, scope: str | None = None, ws: Workspace = ws_dep, user: Any = user_dep):
        o = _get(name)
        if o.kind == "key":
            raise HTTPException(status_code=400, detail="This connector takes a key")
        chosen = await _connect_slot(o, scope, user, ws)
        nonce, verifier = secrets.token_urlsafe(16), secrets.token_urlsafe(48)
        here = f"{request.base_url}connectors/{name}/callback"
        # Through the relay the provider sends the code to one registered host, which reads the origin
        # out of the signed state and bounces it back here. The exchange must reuse whichever it was.
        via = oauth.relay_url() if o.relay else None
        redirect = via or here
        client = await o.client(ws, redirect)
        await credentials.put(ws, f"_pending/{nonce}", {"verifier": verifier, "redirect": redirect, "client": client})
        state_ = oauth.sign({"c": name, "s": ws.subject, "w": ws.ws, "n": nonce, "k": chosen,
                             **({"o": str(request.base_url).rstrip("/")} if via else {})},
                            key=oauth.state_key())
        return {"url": o.authorize_url(client, redirect, state_, verifier)}

    @r.get("/connectors/{name}/callback")
    async def callback(name: str, code: str, state: str):
        try:
            p = oauth.verify(state, key=oauth.state_key())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if p["c"] != name:
            raise HTTPException(status_code=400, detail="bad state")
        o, ws = _get(name), workspace(p["s"], volume, base=base, ws=p["w"])
        pending = await credentials.get(ws, f"_pending/{p['n']}")
        if not pending:
            raise HTTPException(status_code=400, detail="unknown or used state")
        await credentials.delete(ws, f"_pending/{p['n']}")
        grant = await o.exchange(pending["client"], code, pending["redirect"], pending["verifier"])
        await credentials.put(ws, name, grant, shared=p["k"] == "workspace")
        log("connector", action="connected", connector=name, scope=p["k"], subject=p["s"], ws=p["w"])
        return HTMLResponse("<p>Connected — you can close this tab.</p><script>"
                            f"window.opener&&window.opener.postMessage({{type:'cycls:connected',connector:{json.dumps(name)}}},location.origin);"
                            "window.close()</script>")

    @r.delete("/connectors/{name}")
    async def disconnect(name: str, scope: str | None = None, ws: Workspace = ws_dep, user: Any = user_dep):
        chosen = await _slot_or_4xx(_get(name), scope, user, ws)
        await credentials.delete(ws, name, shared=chosen == "workspace")
        log("connector", user=user, action="disconnected", connector=name, scope=chosen)
        return {"ok": True}

    @r.put("/connectors/{name}/key")
    async def set_key(name: str, request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        o, data = _get(name), await request.json()
        key = data.get("key")
        if o.kind != "key":
            raise HTTPException(status_code=400, detail="This connector signs in with OAuth")
        if not isinstance(key, str) or not key.strip():
            raise HTTPException(status_code=400, detail="A key is required")
        if err := o.validate(key.strip()):
            raise HTTPException(status_code=400, detail=err)
        chosen = await _connect_slot(o, data.get("scope"), user, ws)
        await credentials.put(ws, name, {"key": key.strip()}, shared=chosen == "workspace")
        log("connector", user=user, action="connected", connector=name, scope=chosen)
        return {"ok": True}

    @r.get("/connectors/{name}/tools")
    async def tools(name: str, ws: Workspace = ws_dep):
        o, chosen = _get(name), await oauth.permissions(ws, name)
        token, out = await o.bearer(ws), []
        url = await o.endpoint(ws) if o.addressed else None
        for s in o.servers:
            try:
                found = await s.tools(token, url)
            except Exception:
                continue   # a server that wants a key the caller hasn't saved yet lists nothing
            out += [{"name": f"{s.label}_{t.name}", "title": t.title or t.name.replace("_", " "), "description": t.description,
                     "writes": bool(s._writes) or oauth.writes(t), "mode": oauth.mode(s, t, chosen)} for t in found]
        return out

    @r.api_route("/connectors/{name}/fetch/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def fetch(name: str, path: str, request: Request, ws: Workspace = ws_dep):
        """An app's live call to a connector's API. The grant is resolved per call — a refreshed token
        is inherited and never reaches the page — and the same switches that hide a connector's tools
        close this too."""
        o = _get(name)
        if name in (await oauth.blocked(ws) | await oauth.off(ws)):
            raise HTTPException(status_code=403, detail="Connector is switched off")
        # the model's path is gated per tool; an app's is gated by the reserved `_relay` key
        if (await oauth.permissions(ws, name)).get(oauth.RELAY_KEY) == "never":
            raise HTTPException(status_code=403, detail="Apps may not use this connector")
        if not _relay_budget(ws.subject, name):
            raise HTTPException(status_code=429, detail="Too many connector calls from this app")
        status, body, ctype = await oauth.relay(
            o, ws, path, method=request.method, headers=dict(request.headers),
            body=await request.body() if request.method != "GET" else None)
        log("relay", user=getattr(ws, "subject", None), connector=name, method=request.method,
            path=path[:200], status=status, bytes=len(body or b""))
        return Response(content=body, status_code=status, media_type=ctype)

    @r.get("/connectors/{name}/prompts")
    async def prompts(name: str, ws: Workspace = ws_dep):
        o = _get(name)
        token, url = await o.bearer(ws), (await o.endpoint(ws) if o.addressed else None)
        return [{"name": p.name, "title": p.title or p.name.replace("_", " "), "description": p.description}
                for s in o.servers for p in await s.prompts(token, url)]

    @r.put("/connectors/{name}/tools")
    async def set_tools(name: str, request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        _get(name)
        tools = (await request.json()).get("tools") or {}
        if not all(isinstance(k, str) and m in oauth.MODES for k, m in tools.items()):
            raise HTTPException(status_code=400, detail="each tool maps to allow, ask or never")
        await oauth.set_permissions(ws, name, tools)
        log("connector", user=user, action="permissions", connector=name, tools=tools)
        return {"ok": True}

    @r.put("/connectors/{name}/tools/{tool}")
    async def set_tool(name: str, tool: str, request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        _get(name)
        m = (await request.json()).get("mode")
        if m not in oauth.MODES:
            raise HTTPException(status_code=400, detail="mode is allow, ask or never")
        await oauth.set_permissions(ws, name, {**await oauth.permissions(ws, name), tool: m})
        log("connector", user=user, action="permissions", connector=name, tools={tool: m})
        return {"ok": True}

    return r


def tools_router(ws_dep, user_dep):
    """The builtins' own allow / ask / never, per person — what the card's *Always allow* and Settings write.
    Plain rows in the person's `.settings`, so they work on a deployment with no CYCLS_SECRET_KEY."""
    r = APIRouter()

    @r.get("/tools")
    async def builtin_modes(ws: Workspace = ws_dep):
        """Only what the person chose — a tool they never touched follows the composer switch."""
        return await state.settings_db(ws).get("tools", {})

    @r.delete("/tools/{tool}")
    async def clear_builtin(tool: str, ws: Workspace = ws_dep, user: Any = user_dep):
        db = state.settings_db(ws)
        await db.put("tools", {k: v for k, v in (await db.get("tools", {})).items() if k != tool})
        log("connector", user=user, action="permissions", connector="_builtin", tools={tool: None})
        return {"ok": True}

    @r.get("/memory")
    async def memory(ws: Workspace = ws_dep):
        """The person's memory: the `database` tool's own store, never the apps' shelf."""
        return [{"key": k, "value": v} async for k, v in state.memory_db(ws).items(limit=500)]

    @r.put("/memory/{key:path}")
    async def put_memory(key: str, request: Request, ws: Workspace = ws_dep):
        try: state._validate_db_key(key)
        except ValueError as e: raise HTTPException(status_code=400, detail=str(e))
        await state.memory_db(ws).put(key, (await request.json()).get("value"))
        return {"ok": True}

    @r.delete("/memory/{key:path}")
    async def delete_memory(key: str, ws: Workspace = ws_dep):
        await state.memory_db(ws).delete(key)
        return {"ok": True}

    @r.put("/tools/{tool}")
    async def set_builtin(tool: str, request: Request, ws: Workspace = ws_dep, user: Any = user_dep):
        mode = (await request.json()).get("mode")
        if mode not in oauth.MODES:
            raise HTTPException(status_code=400, detail="mode is allow, ask or never")
        db = state.settings_db(ws)
        await db.put("tools", {**await db.get("tools", {}), tool: mode})
        log("connector", user=user, action="permissions", connector="_builtin", tools={tool: mode})
        return {"ok": True}

    return r


# ---- Mount ----

def install_routers(cycls_app, app, required_auth, volume, base):
    mode = getattr(getattr(cycls_app, "config", None), "workspaces", None)

    async def _build_ws(request: Request, user: Any = required_auth):
        ws_id = await resolve_ws_id(user, request.headers.get("x-workspace"), mode, volume, base)
        return workspace(user, volume, base=base, ws=ws_id)
    ws_dep = Depends(_build_ws)
    app.include_router(chats_router(ws_dep))
    app.include_router(tools_router(ws_dep, required_auth))
    app.include_router(files_router(cycls_app, ws_dep, required_auth, volume, base))
    app.include_router(apps_router(cycls_app, ws_dep, required_auth, volume, base))
    app.include_router(share_router(cycls_app, ws_dep, required_auth, volume, base))
    if mode:
        app.include_router(workspaces_router(cycls_app, required_auth, volume, base))
    if getattr(cycls_app, "connectors", None):
        app.include_router(connectors_router(cycls_app, ws_dep, required_auth, volume, base))

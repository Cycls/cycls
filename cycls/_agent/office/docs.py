"""The `docs` tool: the agent reads, edits and makes Word documents (.docx) through Cycls Docs.

The edits run on the cycls-office service: they are made on the document as the editor holds it and written
into the file by patch-back, so only what they change is rewritten — layout, headers, comments, pictures and
everything else in the file are kept as they were. A read names each paragraph with a reference (¶7·k3f) whose
check changes when the paragraph's text does, so an edit made from an old read is refused rather than landing
on the wrong paragraph.
"""
import asyncio

from ..design.deck import lock
from ..design.store import Stale, read_fig, write_fig
from ..paths import _resolve_path
from . import client

ACTIONS = ("read", "edit", "create")
OPS = ("replace", "find_replace", "insert_after", "insert_before", "delete", "style", "list", "link", "cell",
       "insert_row", "delete_row", "insert_column", "delete_column", "insert_table", "picture", "comment", "reply",
       "resolve", "accept_changes", "reject_changes")
_IMAGES = {".png", ".jpg", ".jpeg", ".gif"}
_MAX_IMAGE = 10 * 1024 * 1024
_MAX_OPS = 100

DOCS_TOOL = {
    "name": "docs",
    "description": (
        "Read, edit and create Word documents (.docx) in the workspace with Cycls Docs.\n"
        "- read: each paragraph on a line with its reference (¶7·k3f), its style ([Heading 2]), list marker and "
        "text with **bold**, *italic* and [links](url); tables as grids (T1, rows r1…). For a long document, "
        "`from` starts at a paragraph number.\n"
        "- edit: `ops` run in order on the file at `path`, all of them or none. Only what they change is written; "
        "the rest of the file (layout, headers, comments, pictures) is kept exactly. Name a paragraph by the "
        "reference a read gave (`para`, and `to` for a range) or by words in it (`find`). The reply shows the "
        "changed paragraphs with their new references.\n"
        "- create: a new document at `path` from `content` in markdown: # headings, one paragraph per line, "
        "- bullets and 1. numbers (indent two spaces to nest), | tables |, > quotes, **bold**, *italic*, "
        "[links](url), [page break]. Arabic paragraphs read right to left.\n"
        "Ops: replace (para, text: the paragraph's new text); find_replace (find, replace, all?); insert_after / "
        "insert_before (para, text: lines — \"## Heading\", \"- item\", \"1. item\" or plain); delete (para, to?); "
        "style (para or find, to?; style like \"Heading 2\", align, rtl, bold, italic, underline, strike, color, "
        "highlight, size, font — with find, only those words); list (para, to?, list: bullet | numbered | none, "
        "level?); link (find, url; \"\" removes it); cell (table \"T1\", row, col, text); insert_row (table, after, "
        "cells); delete_row (table, row); insert_column (table, after, cells); delete_column (table, col); "
        "insert_table (para, rows: [[\"Name\", \"Owner\"], [\"…\", \"…\"]], header?) adds a table after the paragraph; "
        "picture (para, path: a PNG/JPEG/GIF in the workspace, width? in pixels, align?) adds a picture after it; "
        "comment (para or find, text) comments on the paragraph or those words; reply (comment: the # in the read's "
        "Comments, text); resolve (comment, done: false opens it again); accept_changes / reject_changes take a "
        "document's tracked changes (a read says when it has them; edits are refused until then). Rows and columns "
        "count from 1. Read before editing a document you have not seen. `ops` and `content` are always sent: "
        "ops [] for read and create, content \"\" for read and edit."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "path": {"type": "string", "description": "The .docx file in the workspace, e.g. reports/q3.docx"},
            "ops": {
                "type": "array",
                "description": "The changes, in order; [] for read and create.",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": list(OPS)},
                        "para": {"type": "string", "description": "A paragraph's reference from the read, e.g. ¶7·k3f"},
                        "to": {"type": "string", "description": "The last paragraph of a range (delete, style, list)"},
                        "find": {"type": "string", "description": "Words in the document: they name the paragraph, or are what find_replace, link and style change"},
                        "text": {"type": "string", "description": "replace / cell: the new text; insert_*: the new lines"},
                        "replace": {"type": "string", "description": "find_replace: the new words (\"\" removes them)"},
                        "all": {"type": "boolean", "description": "find_replace / link: every place the words are"},
                        "style": {"type": "string", "description": "A paragraph style the document has, e.g. Heading 2, Title, Normal"},
                        "list": {"type": "string", "enum": ["bullet", "numbered", "none"]},
                        "level": {"type": "integer", "description": "list: how deep, 0 = top"},
                        "align": {"type": "string", "enum": ["left", "center", "right", "justify"]},
                        "rtl": {"type": "boolean", "description": "style: true right to left, false left to right"},
                        "bold": {"type": "boolean"}, "italic": {"type": "boolean"},
                        "underline": {"type": "boolean"}, "strike": {"type": "boolean"},
                        "color": {"type": "string", "description": "#RRGGBB"},
                        "highlight": {"type": "string", "description": "#RRGGBB, or none"},
                        "size": {"type": "number", "description": "points"},
                        "font": {"type": "string"},
                        "url": {"type": "string", "description": "link: https://…, mailto:…, or \"\" to remove"},
                        "table": {"type": "string", "description": "A table from the read, e.g. T1"},
                        "row": {"type": "integer"}, "col": {"type": "integer"},
                        "after": {"type": "integer", "description": "insert_row / insert_column: after this row or column (0 = first)"},
                        "cells": {"type": "array", "items": {"type": "string"}, "description": "insert_row: the new row's cells; insert_column: one per row"},
                        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}, "description": "insert_table: rows of cells, the first a header"},
                        "header": {"type": "boolean", "description": "insert_table: false when the first row is not a header"},
                        "path": {"type": "string", "description": "picture: the image file in the workspace"},
                        "width": {"type": "integer", "description": "picture: width in pixels (it keeps its proportions)"},
                        "comment": {"type": "integer", "description": "reply / resolve: the comment's # in the read"},
                        "done": {"type": "boolean", "description": "resolve: false opens the comment again"},
                    },
                    "required": ["op"],
                },
            },
            "from": {"type": "integer", "description": "read: start at this paragraph number"},
            "content": {"type": "string", "description": "create: the whole new document in markdown; \"\" for read and edit"},
            "rtl": {"type": "boolean", "description": "create: the whole document reads right to left (Arabic text makes it so anyway)"},
            "intent": {"type": "string", "description": "edit: a few words on what the change does, shown to the person"},
        },
        # `ops` and `content` are required although not every action takes them: models that drop optional fields
        # sent edits without ops and creates without content (DeepSeek, 2026-10-25: 14 creates in a row).
        "required": ["action", "path", "ops", "content"],
    },
}

DOCS_PROMPT = (
    "Word files: read and change any existing .docx with `docs`, never python-docx or a script (even where a skill "
    "describes one): it keeps everything in the file it does not touch (layout, headers, comments, pictures) and the "
    "person sees the change. A new plain Word document (headings, paragraphs, lists, tables, links): `docs` create, "
    "from markdown. Only a Word file that needs pictures, headers and footers, brand colours, a cover or a custom page "
    "layout is built with the docx skill."
)


def docs_step(inp):
    action = str(inp.get("action") or "").lower()
    detail = inp.get("intent") or inp.get("path") or ""
    return {"tool_name": "Docs", "step": f"{action} {detail}".strip()}


def _err(message):
    return f"Error: {message}"


def _check_ops(ops):
    if not isinstance(ops, list):
        return "ops must be a list of {op, …}"
    if len(ops) > _MAX_OPS:
        return f"at most {_MAX_OPS} ops per call; split the change"
    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict) or not op.get("op"):
            return f"op {i} needs an `op` ({', '.join(OPS)})"
        if op["op"] not in OPS:
            return f"op {i}: unknown op {str(op['op'])[:30]!r} (one of {', '.join(OPS)})"
        if op["op"] in ("reply", "comment", "replace", "insert_after", "insert_before", "cell") and not isinstance(op.get("text"), str):
            got = ", ".join(sorted(str(k) for k in op)) or "nothing"
            return f"op {i} ({op['op']}) needs `text`, a string (it came with: {got})"
    return None


def _with_pictures(ops, root):
    """Ops with each picture's image read from the workspace (sent as base64 with its name)."""
    import base64
    out = []
    for i, op in enumerate(ops, 1):
        if op.get("op") != "picture":
            out.append(op)
            continue
        raw = str(op.get("path") or "").strip()
        if not raw:
            raise ValueError(f"op {i} (picture) needs `path`: a PNG, JPEG or GIF in the workspace")
        image = _resolve_path(raw, root)
        if image.suffix.lower() not in _IMAGES:
            raise ValueError(f"op {i} (picture): {raw} is not a PNG, JPEG or GIF")
        if not image.is_file():
            raise ValueError(f"op {i} (picture): {raw} does not exist")
        if image.stat().st_size > _MAX_IMAGE:
            raise ValueError(f"op {i} (picture): {raw} is larger than 10 MB")
        sent = {k: v for k, v in op.items() if k != "path"}
        sent.update(data=base64.b64encode(image.read_bytes()).decode(), name=image.name)
        out.append(sent)
    return out


async def exec_docs(inp, workspace, ctx=None):
    root = workspace.root
    action = str(inp.get("action") or "").lower().strip()
    ops = inp.get("ops") or []
    from ..logs import log
    log("docs_call", chat_id=getattr(ctx, "chat_id", None), action=action[:12],
        keys=sorted(str(k)[:20] for k in inp)[:20],
        ops=[str(o.get("op"))[:16] for o in ops[:30] if isinstance(o, dict)] if isinstance(ops, list) else None,
        # each op's field names: what a model (or a host between us) sent, to see a dropped field
        op_keys=[sorted(str(k)[:16] for k in o)[:12] for o in ops[:12] if isinstance(o, dict)] if isinstance(ops, list) else None)
    if action not in ACTIONS:
        return _err(f"action must be one of {', '.join(ACTIONS)}.")
    if not client.offered(workspace, "docs"):
        return _err("Docs is not switched on for this organisation.")
    raw_path = str(inp.get("path") or "").strip()
    if not raw_path:
        return _err("give the .docx file's `path`.")
    try:
        path = _resolve_path(raw_path, root)
    except ValueError as e:
        return _err(str(e))
    if path.suffix.lower() != ".docx":
        return _err(f"{raw_path} is not a .docx file (Docs edits .docx; convert a .doc first).")
    rel = path.relative_to(root).as_posix()

    try:
        if action == "read":
            if not path.is_file():
                return _err(f"{rel} does not exist.")
            data = await asyncio.to_thread(path.read_bytes)
            start = inp.get("from")
            return await client.docs_read(data, path.name, start=start if isinstance(start, int) and start > 1 else None)

        if bad := _check_ops(ops):
            return _err(bad)
        if action == "create":
            if path.exists():
                return _err(f"{rel} already exists: edit it, or create under another name.")
            content = inp.get("content")
            if not isinstance(content, str) or not content.strip():
                return _err("create needs `content`: the document in markdown (# headings, paragraphs, - bullets, "
                            "1. numbers, | tables |).")
            create = {"content": content}
            if isinstance(inp.get("rtl"), bool):
                create["rtl"] = inp["rtl"]
            result = await client.docs_apply(None, path.name, ops, create=create)
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            try:
                await write_fig(root, rel, result["bytes"], base="", by="agent", reason="agent", intent=inp.get("intent"))
            except Stale:
                return _err(f"{rel} appeared while it was being created: read it, then edit.")
            return {"_model": f"Created {rel}.\n{result['report']}".strip(),
                    "_ui": {"type": "ui", "action": "open_canvas", "path": rel}}

        # edit
        if not ops:
            return _err("edit needs `ops`: [{\"op\": \"replace\", \"para\": \"¶3·k3f\", \"text\": \"…\"}].")
        try:
            ops = await asyncio.to_thread(_with_pictures, ops, root)
        except ValueError as e:
            return _err(f"{e}. Nothing was changed.")
        from ..design import comments as _comments
        author = _comments.author("agent", agent=True)["name"]
        async with lock(path):   # one change at a time per file: the model calls tools in parallel
            for attempt in (1, 2):
                data, base = await asyncio.to_thread(read_fig, root, rel)
                if data is None:
                    return _err(f"{rel} does not exist (use create for a new document).")
                result = await client.docs_apply(data, path.name, ops, author=author)
                if result["unchanged"]:
                    return f"Nothing in {rel} changed.\n{result['report']}".strip()
                try:   # a save meanwhile: apply to that, once (its references may no longer match — then it says so)
                    await write_fig(root, rel, result["bytes"], base=base, by="agent", reason="agent", intent=inp.get("intent"))
                    break
                except Stale:
                    if attempt == 2:
                        return _err(f"{rel} changed while the edit was being made. Nothing was changed; read it "
                                    "again, then edit.")
    except client.Refused as e:
        message = str(e)
        return _err(message if "Nothing was changed" in message else f"{message} — nothing was changed.")
    except client.Unavailable as e:
        return _err(f"Docs is unavailable — {e}")

    # An open preview of the file fetches it again.
    return {"_model": f"Edited {rel}.\n{result['report']}".strip(),
            "_ui": {"type": "ui", "action": "refresh_canvas", "path": rel}}

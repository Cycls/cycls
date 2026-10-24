"""The `sheets` tool: the agent reads and edits .xlsx files through Cycls Sheets.

The edits run on the cycls-office service, in the same engine the person's editor runs, so formulas
recompute and conditional formats, validation, filters, charts and names move with the cells. Only
what changed is written into the file; everything else in it is kept as it was. An editor open on
the file replays the same changes live (`sheets_command`).
"""
import asyncio
import json
import re

from ..design.deck import lock
from ..design.store import Stale, read_fig, write_fig
from ..paths import _resolve_path
from . import client

ACTIONS = ("read", "edit", "create", "comments")
OPS = ("set_values", "set_formulas", "format", "clear", "merge", "unmerge", "insert_rows", "delete_rows",
       "insert_cols", "delete_cols", "add_sheet", "rename_sheet", "delete_sheet", "freeze", "column_width",
       "sort", "set_direction", "note", "define_name")
_MAX_OPS = 200

SHEETS_TOOL = {
    "name": "sheets",
    "description": (
        "Read and edit Excel workbooks (.xlsx) in the workspace with Cycls Sheets.\n"
        "- read: the workbook's sheets outlined, then a sheet or range as a grid showing each formula and "
        "its value (`target`: a sheet name or range like 'المبيعات'!A1:H40; omitted = the first sheet).\n"
        "- edit: `ops` run in order on the file at `path`. Formulas recompute; formats, validation, filters, "
        "charts and named ranges move with inserted or deleted rows and columns; the rest of the file is "
        "kept exactly. The reply shows the changed cells' new values and any formula errors.\n"
        "- create: a new workbook at `path` (`target` names the first sheet, `rtl` for Arabic; an Arabic name or "
        "Arabic values make it right to left unless rtl is false), then `ops`.\n"
        "- note puts a note on a cell (`text`; empty removes it); define_name names a range (`name`, `target`).\n"
        "- comments: what people wrote on the workbook's cells, every thread; with `number` (the # in the list) "
        "answer it (`reply`) and close or reopen it (`resolve`). read lists the open ones too.\n"
        "Targets are A1 ranges (B3, B3:D9, 'Sheet 2'!A1:C4), rows (5 or 5:7), columns (C or C:D) or a "
        "sheet name. Values are rows of cells: [[\"Item\", \"Qty\"], [\"Tea\", 5]]; a value starting with = "
        "is a formula. Read before editing a file you have not seen. `ops` is always sent: [] for read."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS)},
            "path": {"type": "string", "description": "The .xlsx file in the workspace, e.g. reports/budget.xlsx"},
            "target": {"type": "string",
                       "description": "read: a sheet name or range. create: the first sheet's name."},
            "ops": {
                "type": "array",
                "description": "The changes, in order; [] for read.",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": list(OPS)},
                        "target": {"type": "string",
                                   "description": "A1 range, rows (5:7), columns (C:D) or a sheet name; "
                                                  "set_values/set_formulas: the top-left cell"},
                        "values": {"type": "array", "items": {"type": "array", "items": {}},
                                   "description": "set_values: rows of cells"},
                        "formulas": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                                     "description": "set_formulas: rows of formulas, e.g. [[\"=SUM(B2:B9)\"]]"},
                        "count": {"type": "integer", "description": "insert_rows / insert_cols: how many"},
                        "name": {"type": "string", "description": "add_sheet / rename_sheet: the sheet name; define_name: the name (letters, digits, _)"},
                        "text": {"type": "string", "description": "note: the note's text ('' removes the note)"},
                        "rows": {"type": "integer", "description": "freeze: rows frozen at the top"},
                        "cols": {"type": "integer", "description": "freeze: columns frozen at the start"},
                        "width": {"type": "integer", "description": "column_width: pixels"},
                        "column": {"type": "string", "description": "sort: the column to sort by, e.g. C"},
                        "ascending": {"type": "boolean", "description": "sort: false for largest first"},
                        "rtl": {"type": "boolean", "description": "set_direction: true right-to-left, false left-to-right"},
                        "bold": {"type": "boolean"}, "italic": {"type": "boolean"},
                        "color": {"type": "string", "description": "format: text colour, #RRGGBB"},
                        "fill": {"type": "string", "description": "format: background, #RRGGBB"},
                        "font": {"type": "string"}, "size": {"type": "number"},
                        "number_format": {"type": "string", "description": "format: e.g. #,##0.00 or 0% or yyyy-mm-dd"},
                        "align": {"type": "string", "enum": ["left", "center", "right"]},
                        "valign": {"type": "string", "enum": ["top", "middle", "bottom"]},
                        "wrap": {"type": "boolean"},
                    },
                    "required": ["op", "target"],
                },
            },
            "rtl": {"type": "boolean", "description": "create: the first sheet reads right to left (Arabic)"},
            "number": {"type": "integer", "description": "comments: the comment to answer or resolve (its #)"},
            "reply": {"type": "string", "description": "comments: your answer to comment `number`"},
            "resolve": {"type": "boolean", "description": "comments: true closes comment `number`, false reopens it"},
            "raw": {"type": "boolean", "description": "read: stored values instead of formatted ones"},
            "intent": {"type": "string", "description": "edit: a few words on what the change does, shown to the person"},
        },
        # `ops` is required although read takes none: models that drop optional fields sent edits without it.
        "required": ["action", "path", "ops"],
    },
}

SHEETS_PROMPT = (
    "Excel files: read and change .xlsx files with `sheets`, not openpyxl or a script — it keeps "
    "everything in the file it does not touch (charts, pivots, formats) and the person sees the change "
    "live. pandas stays fine for analysing data."
)


_ARABIC = re.compile("[" + chr(0x0600) + "-" + chr(0x06FF) + chr(0x0750) + "-" + chr(0x077F) + "]")


def _arabic(text):
    return bool(text) and bool(_ARABIC.search(str(text)))


def sheets_step(inp):
    action = str(inp.get("action") or "").lower()
    detail = inp.get("intent") or inp.get("path") or ""
    return {"tool_name": "Sheets", "step": f"{action} {detail}".strip()}


def _err(message):
    return f"Error: {message}"


def _clip(text, most):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1] + "…"


_PLAIN_SHEET = re.compile(r"[A-Za-z_\u0600-\u06FF][\w.\u0600-\u06FF]*")


def _where(t):
    sheet = t.get("sheet_name") or t.get("sheet") or "?"
    if not _PLAIN_SHEET.fullmatch(sheet):
        sheet = "'" + sheet.replace("'", "''") + "'"
    return f"{sheet}!{t['cell']}" if t.get("cell") else f"{sheet} (its cell was removed)"


def _thread_line(t, full=False):
    who = (t.get("author") or {}).get("name") or "Someone"
    replies = t.get("replies") or []
    line = f"#{t.get('n')} {_where(t)} — {who}: \"{_clip(t.get('text'), 400 if full else 160)}\""
    if replies and not full:
        line += f" · {len(replies)} repl{'y' if len(replies) == 1 else 'ies'}"
    if t.get("resolved"):
        line += " · resolved"
    if full:
        for r in replies[-5:]:
            line += f"\n    ↳ {(r.get('author') or {}).get('name') or 'Someone'}: \"{_clip(r.get('text'), 300)}\""
        if len(replies) > 5:
            line += f"\n    (and {len(replies) - 5} earlier)"
    return line


async def _open_comments(workspace, rel):
    """The open comments on a workbook, a line each — "" when none (or comments are not kept here)."""
    from ..design import comments
    if not comments.usable(workspace):
        return ""
    try:
        doc, _ = await comments.read(workspace, rel)
    except Exception:
        return ""
    threads = comments.open_threads(doc)
    if not threads:
        return ""
    lines = [_thread_line(t) for t in threads[:12]]
    more = f"\n  … and {len(threads) - 12} more (action comments lists them all)" if len(threads) > 12 else ""
    return "\n\nOpen comments:\n  " + "\n  ".join(lines) + more


async def _exec_comments(inp, workspace, rel):
    """List a workbook's comments, or reply to / resolve / reopen one by `number`, as the agent."""
    from ..design import comments
    if not comments.usable(workspace):
        return _err("comments aren't kept in this workspace.")
    try:
        doc, _ = await comments.read(workspace, rel)
    except Exception as e:
        return _err(f"couldn't read the comments on {rel} — {e}")
    threads = comments.shown(doc)
    number, reply, resolve = inp.get("number"), inp.get("reply"), inp.get("resolve")
    if number is None:
        if (isinstance(reply, str) and reply.strip()) or isinstance(resolve, bool):
            return _err("`reply` and `resolve` are for one comment — pass its `number` (the # in the list).")
        if not threads:
            return f"No one has commented on {rel}."
        opened = [t for t in threads if not t.get("resolved")]
        closed = [t for t in threads if t.get("resolved")]
        out = [f"Comments on {rel}: {len(opened)} open, {len(closed)} resolved."]
        out += [_thread_line(t, full=True) for t in opened[:40]]
        if closed:
            out.append("Resolved:")
            out += [_thread_line(t) for t in closed[-10:]]
        return "\n".join(out)
    thread = next((t for t in threads if t.get("n") == number), None)
    if thread is None:
        have = ", ".join(f"#{t['n']}" for t in threads) or "none"
        return _err(f"{rel} has no comment #{number} — it has {have}. Nothing was changed.")
    if not (isinstance(reply, str) and reply.strip()) and not isinstance(resolve, bool):
        return _err(f"nothing to do to comment #{number} — pass `reply` (your answer) and/or `resolve` "
                    "(true closes it, false opens it again). Without `number`, comments lists them.")
    me, did = comments.author("agent", agent=True), []
    try:
        if isinstance(reply, str) and reply.strip():
            await comments.change(workspace, rel, thread["id"], "reply", me, {"text": reply})
            did.append("replied to")
        if isinstance(resolve, bool):
            await comments.change(workspace, rel, thread["id"], "resolve" if resolve else "reopen", me)
            did.append("resolved" if resolve else "reopened")
    except comments.Refused as e:
        return _err(str(e) + (f" (Already done: {did[0]} it.)" if did else ""))
    left = len([t for t in threads if not t.get("resolved") and t.get("n") != number]) + (0 if resolve else 1)
    said = " and ".join(did)
    return (f"{said[0].upper()}{said[1:]} comment #{number} on {rel}. The people working on it see that in the "
            f"workbook. {left} comment{'s' if left != 1 else ''} still open.")


def _check_ops(ops):
    if not isinstance(ops, list):
        return "ops must be a list of {op, target, …}"
    if len(ops) > _MAX_OPS:
        return f"at most {_MAX_OPS} ops per call; split the change"
    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict) or not op.get("op"):
            return f"op {i} needs an `op` ({', '.join(OPS)})"
        if op["op"] not in OPS:
            return f"op {i}: unknown op {str(op['op'])[:30]!r} (one of {', '.join(OPS)})"
        if op["op"] != "add_sheet" and not op.get("target"):
            return f"op {i} ({op['op']}) needs a `target`"
    return None


async def exec_sheets(inp, workspace, ctx=None):
    root = workspace.root
    action = str(inp.get("action") or "").lower().strip()
    ops = inp.get("ops") or []
    from ..logs import log
    log("sheets_call", chat_id=getattr(ctx, "chat_id", None), action=action[:12],
        keys=sorted(str(k)[:20] for k in inp)[:20],
        ops=[str(o.get("op"))[:16] for o in ops[:30] if isinstance(o, dict)] if isinstance(ops, list) else None)
    if action not in ACTIONS:
        return _err(f"action must be one of {', '.join(ACTIONS)}.")
    if not client.offered(workspace, "sheets"):
        return _err("Sheets is not switched on for this organisation.")
    raw_path = str(inp.get("path") or "").strip()
    if not raw_path:
        return _err("give the .xlsx file's `path`.")
    try:
        path = _resolve_path(raw_path, root)
    except ValueError as e:
        return _err(str(e))
    if path.suffix.lower() != ".xlsx":
        return _err(f"{raw_path} is not an .xlsx file (Sheets edits .xlsx; convert a .xls or .csv first).")
    rel = path.relative_to(root).as_posix()

    try:
        if action == "read":
            if not path.is_file():
                return _err(f"{rel} does not exist.")
            data = await asyncio.to_thread(path.read_bytes)
            text = await client.sheets_read(data, path.name, target=inp.get("target"), raw=bool(inp.get("raw")))
            return text + await _open_comments(workspace, rel)

        if action == "comments":
            if not path.is_file():
                return _err(f"{rel} does not exist.")
            return await _exec_comments(inp, workspace, rel)

        if bad := _check_ops(ops):
            return _err(bad)
        if action == "create":
            if path.exists():
                return _err(f"{rel} already exists: edit it, or create under another name.")
            rtl = inp.get("rtl")
            if rtl is None:   # models drop optional flags: an Arabic workbook reads right to left
                values = [o.get("values") for o in ops[:5] if isinstance(o, dict)]
                rtl = _arabic(inp.get("target")) or _arabic(json.dumps(values, ensure_ascii=False))
            create = {"sheet": str(inp.get("target") or "").strip() or ("ورقة1" if rtl else "Sheet1"),
                      "rightToLeft": bool(rtl)}
            result = await client.sheets_apply(None, path.name, ops, create=create)
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            try:
                await write_fig(root, rel, result["bytes"], base="", by="agent", reason="agent", intent=inp.get("intent"))
            except Stale:
                return _err(f"{rel} appeared while it was being created: read it, then edit.")
            ack = f"Created {rel}.\n{result['report']}".strip()
            return {"_model": ack, "_ui": {"type": "ui", "action": "open_canvas", "path": rel}}

        # edit
        if not ops:
            return _err("edit needs `ops`: [{\"op\": \"set_values\", \"target\": \"B3\", \"values\": [[1]]}].")
        async with lock(path):   # one change at a time per file: the model calls tools in parallel
            for attempt in (1, 2):
                data, base = await asyncio.to_thread(read_fig, root, rel)
                if data is None:
                    return _err(f"{rel} does not exist (use create for a new workbook).")
                result = await client.sheets_apply(data, path.name, ops)
                if result["unchanged"]:
                    return f"Nothing in {rel} changed.\n{result['report']}".strip()
                try:   # a save in the editor meanwhile: apply to that, once
                    version = await write_fig(root, rel, result["bytes"], base=base, by="agent", reason="agent",
                                              intent=inp.get("intent"))
                    break
                except Stale:
                    if attempt == 2:
                        return _err(f"{rel} changed while the edit was being made (it is being edited by hand). "
                                    "Nothing was changed; read it again, then edit.")
    except client.Refused as e:
        return _err(f"{e} — nothing was changed.")
    except client.Unavailable as e:
        return _err(f"Sheets is unavailable — {e}")

    if result.get("ops"):   # comments on the cells follow the rows and columns the edit moved
        from ..design import comments
        if comments.usable(workspace):
            try:
                await comments.shift(workspace, rel, result["ops"])
            except Exception as e:
                log("warn", message=f"comments on {rel} did not follow the edit: {type(e).__name__}: {e}")
    ui = {"type": "ui", "action": "sheets_command", "path": rel, "mutations": result["mutations"],
          "version": version}
    if intent := inp.get("intent"):
        ui["intent"] = str(intent)[:80]
    if len(json.dumps(ui["mutations"], default=str)) > 2_000_000:   # too large to replay: the editor reopens the file
        ui["mutations"], ui["reload"] = [], True
    return {"_model": f"Edited {rel}.\n{result['report']}".strip(), "_ui": ui}

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
from ..design.store import Stale, load_fig, write_fig
from ..paths import _resolve_path
from . import client, fill
from .export import export_pdf

ACTIONS = ("read", "edit", "create", "comments", "export", "print")
OPS = ("set_values", "set_formulas", "format", "clear", "merge", "unmerge", "insert_rows", "delete_rows",
       "insert_cols", "delete_cols", "add_sheet", "rename_sheet", "delete_sheet", "freeze", "column_width",
       "row_height", "page_setup", "print_ready", "sort", "set_direction", "note", "define_name")
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
        "- Printing: every read, and every edit that changes the layout, says how the sheet prints (pages, scale, "
        "how full) and which "
        "cells' text does not fit as it prints (cut by its row, broken inside a word, ### numbers). Fix it here: "
        "page_setup (target the sheet: paper, orientation, scale or fit_width / fit_height, margins, center, "
        "print_area, repeat_rows), row_height and column_width (pixels, or auto: true to fit the text). Read the "
        "reply, not a PDF.\n"
        "- comments: what people wrote on the workbook's cells, every thread; with `number` (the # in the list) "
        "answer it (`reply`) and close or reopen it (`resolve`). read lists the open ones too.\n"
        "- print: the workbook made to print well, in one call, and its PDF written beside it: the title and header "
        "rows found, the table in one font with a coloured header, borders and banded rows (style clean; keep leaves "
        "fonts and colours as they are), columns shared over the page and rows sized to their text, the paper turned "
        "and fitted to one page, pictures kept their size, values untouched. Options: target (the sheet), style, color "
        "(the header, #RRGGBB), font, size, paper, orientation, header (rows such as 2:3, found when left out). The "
        "reply says how it prints; that is the check.\n"
        "- export: the workbook as a PDF beside it (budget.xlsx → budget.pdf), as it prints, for when the person "
        "asks for a PDF to print or send. Once, when the work is done: it is not a way to look at an edit.\n"
        "Targets are A1 ranges (B3, B3:D9, 'Sheet 2'!A1:C4), rows (5 or 5:7), columns (C or C:D) or a "
        "sheet name. Values are rows of cells: [[\"Item\", \"Qty\"], [\"Tea\", 5]]; a value starting with = "
        "is a formula. Rows a query, a tool or a script produced are not typed: set_values `from` fills them from "
        "its .csv or .json file. One formula over a range fills it like Excel's fill handle (target F2:F93, "
        "formulas [[\"=C2/D2\"]]). Read before editing a file you have not seen. `ops` is always sent: [] for "
        "read and export."
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
                                   "description": "set_values: rows of cells, typed (or give `from`)"},
                        "from": {"type": "string",
                                 "description": "set_values: a .csv or .json file in the workspace to fill from "
                                                "instead of `values`, e.g. a query's saved result (.tmp/screen.json). "
                                                "Its column names are the first row; numbers stay numbers, ISO dates "
                                                "become dates, nothing in it runs as a formula"},
                        "header": {"type": "boolean",
                                   "description": "set_values from a file: false leaves out its column names"},
                        "formulas": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                                     "description": "set_formulas: rows of formulas, e.g. [[\"=SUM(B2:B9)\"]]; on a "
                                                    "larger range they fill it, references moving ($ keeps one fixed)"},
                        "count": {"type": "integer", "description": "insert_rows / insert_cols: how many"},
                        "name": {"type": "string", "description": "add_sheet / rename_sheet: the sheet name; define_name: the name (letters, digits, _)"},
                        "text": {"type": "string", "description": "note: the note's text ('' removes the note)"},
                        "rows": {"type": "integer", "description": "freeze: rows frozen at the top"},
                        "cols": {"type": "integer", "description": "freeze: columns frozen at the start"},
                        "width": {"type": "integer", "description": "column_width: pixels"},
                        "height": {"type": "integer", "description": "row_height: pixels (20 is Excel's usual row)"},
                        "auto": {"type": "boolean", "description": "row_height / column_width: fit each to its text instead of a size"},
                        "paper": {"type": "string", "enum": ["A4", "Letter", "Legal", "A3", "A5", "Tabloid"],
                                  "description": "page_setup"},
                        "orientation": {"type": "string", "enum": ["portrait", "landscape"], "description": "page_setup"},
                        "scale": {"type": "integer", "description": "page_setup: percent, 10–400 (turns fitting off)"},
                        "fit_width": {"type": "integer", "description": "page_setup: pages wide (0: as many as it takes); "
                                                                         "with fit_height, fits the sheet to pages"},
                        "fit_height": {"type": "integer", "description": "page_setup: pages tall (0: as many as it takes)"},
                        "margins": {"type": "string", "description": "page_setup: narrow, normal, wide, or one length such as 1cm"},
                        "center": {"type": "string", "enum": ["horizontal", "vertical", "both", "none"], "description": "page_setup"},
                        "gridlines": {"type": "boolean", "description": "page_setup: print the gridlines"},
                        "print_area": {"type": "string", "description": "page_setup: the range that prints, e.g. A1:R16 (\"\" for all)"},
                        "repeat_rows": {"type": "string", "description": "page_setup: rows printed at the top of every page, e.g. 2:3 (\"\" for none)"},
                        "repeat_columns": {"type": "string", "description": "page_setup: columns printed on every page, e.g. A:B"},
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
            "style": {"type": "string", "enum": ["clean", "keep"], "description": "print: clean (one font, a coloured header, borders) or keep"},
            "color": {"type": "string", "description": "print: the header's colour, #RRGGBB"},
            "font": {"type": "string", "description": "print: the table's font (the workbook's when left out)"},
            "size": {"type": "number", "description": "print: the text's size in points (10 when left out)"},
            "paper": {"type": "string", "enum": ["A4", "Letter", "Legal", "A3", "A5", "Tabloid"], "description": "print"},
            "orientation": {"type": "string", "enum": ["portrait", "landscape"], "description": "print: left out, whichever prints larger"},
            "header": {"type": "string", "description": "print: the header rows, e.g. 2:3 (found when left out)"},
        },
        # `ops` is required although read takes none: models that drop optional fields sent edits without it.
        "required": ["action", "path", "ops"],
    },
}

SHEETS_PROMPT = (
    "Excel files: read and change .xlsx files with `sheets`, not openpyxl or a script — it keeps "
    "everything in the file it does not touch (charts, pivots, formats) and the person sees the change "
    "live. pandas stays fine for analysing data. Trust what a `sheets` edit replies: it shows the changed "
    "cells' new values and any formula errors, so tell the person what it says, and `sheets` read to look "
    "again. Never change an existing .xlsx with Bash, a script, zip or XML edits, and don't unzip, render "
    "or convert one to check a `sheets` edit: that goes round the file's lock, its versions and the "
    "person's open editor. A workbook to make print-ready (to print on one page, look professional, be ready to "
    "print) is one `print_sheet` call, made straight away with no read first: it lays the table out, writes the PDF "
    "and its reply is final. Do not inspect the file, open or render the PDF, or make other versions; tell the person "
    "what the reply says, how to change the font and colours included. Only what they ask after that is an edit. "
    "How a workbook prints is in every `sheets` read and layout edit's reply (pages, scale, the "
    "text that does not fit): set it with page_setup, row_height and column_width (auto fits them to the text) "
    "and trust that reply; never export or convert a copy to look at it. Change a layout only when the person asks "
    "about printing or how the sheet looks. A PDF of the workbook, when the person "
    "asks for one, is `sheets` export, once, when the work is done. "
    "Rows a query, a tool or a script produced go in with set_values `from` (their "
    ".csv or .json file), never retyped into `values`: typing is for what exists nowhere else (the person's "
    "own figures, assumptions, labels) or a few cells, and a typed figure from a document or a page says "
    "where it came from beside it. A column of formulas is one formula over its range, not one per row."
)


_ARABIC = re.compile("[" + chr(0x0600) + "-" + chr(0x06FF) + chr(0x0750) + "-" + chr(0x077F) + "]")


def _arabic(text):
    return bool(text) and bool(_ARABIC.search(str(text)))


def sheets_step(inp):
    return {"tool_name": "Sheets", "step": inp.get("intent") or inp.get("path") or ""}


# print_sheet: the one call for "make this print well". A tool of its own, not only an action of `sheets`: a model
# reaches for a tool named for the job, and one asked for a print-ready sheet otherwise formatted it by hand, a
# hundred ops over seven edits checked against PDFs (2.5 minutes, where this is a few seconds).
PRINT_SHEET_TOOL = {
    "name": "print_sheet",
    "description": (
        "Make an Excel workbook (.xlsx) print well, in one call: for a sheet that should print on one page, look "
        "professional or be ready to print. It finds the title and header rows, puts the table in one font with a "
        "coloured header, borders and banded rows (style clean; keep leaves fonts and colours as they are), shares the "
        "page's width over the columns and sizes the rows to their text, turns the paper and fits the sheet to one "
        "page, keeps every picture its size and every value as it is, then writes the PDF beside the workbook and opens "
        "it. Call it straight away, with no read first, and once: its reply is final. Give it only the path and what "
        "the person asked for (a font, a colour, a paper); it finds the rest itself."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The .xlsx file in the workspace, e.g. attachments/register.xlsx"},
            "sheet": {"type": "string", "description": "Only a sheet the person named (the first when left out)"},
            "style": {"type": "string", "enum": ["clean", "keep"], "description": "clean (default), or keep when the person wants their fonts and colours kept"},
            "color": {"type": "string", "description": "Only a colour the person asked for: the header's, #RRGGBB"},
            "font": {"type": "string", "description": "Only a font the person asked for"},
            "size": {"type": "number", "description": "Only a text size the person asked for, in points"},
            "paper": {"type": "string", "enum": ["A4", "Letter", "Legal", "A3", "A5", "Tabloid"], "description": "Only a paper the person named"},
            "orientation": {"type": "string", "enum": ["portrait", "landscape"], "description": "Only when the person asked for one"},
        },
        "required": ["path"],
    },
}

# What print_sheet passes on. The header rows are not among them: the model has not read the workbook, so rows it
# names are a guess, and one guessed rows 3-4 where the header was 2-3, painting the first data row as a header.
_PRINT_SHEET_KEYS = ("path", "style", "color", "font", "size", "paper", "orientation")


def print_step(inp):
    return {"tool_name": "Sheets", "step": "Making it ready to print"}


async def exec_print_sheet(inp, workspace, ctx=None):
    given = {k: inp[k] for k in _PRINT_SHEET_KEYS if inp.get(k) not in (None, "")}
    return await exec_sheets({**given, "action": "print", "target": inp.get("sheet"), "ops": []}, workspace, ctx)


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


async def _exec_comments(inp, workspace, rel, agent=None):
    """List a workbook's comments, or reply to / resolve / reopen one by `number`, as the agent (`agent`: its name
    as the chat shows it)."""
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
    me, did = comments.author("agent", agent, agent=True), []
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


def _typed_hint(typed):
    if typed <= fill.TYPED_HINT_CELLS:
        return ""
    return (f"({typed:,} cells were typed into values. Rows a query, a tool or a script produced fill faster and "
            "exactly from their file: set_values `from`.)\n")


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
        if op["op"] not in ("add_sheet", "print_ready") and not op.get("target"):
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
            return await _exec_comments(inp, workspace, rel, getattr(ctx, "agent", None))

        if action == "print":
            # The layout in one edit (print_ready), then the PDF: one call where a dozen edits checked against PDFs were.
            op = {"op": "print_ready"}
            for k in ("target", "style", "color", "font", "size", "paper", "orientation", "header"):
                if inp.get(k) not in (None, ""):
                    op[k] = inp[k]
            edited = await exec_sheets({"action": "edit", "path": raw_path, "ops": [op],
                                        "intent": inp.get("intent") or "Made ready to print"}, workspace, ctx)
            if not isinstance(edited, dict):
                return edited
            printed = await export_pdf(workspace, path, rel, "workbook")
            if not isinstance(printed, dict):
                return f"{edited['_model']}\n{printed}"
            final = ("This is final; there is nothing to check or redo. The person prints the PDF, or the workbook "
                     "itself (its page is set). To change the font or the colours they select the table in Cycls Sheets "
                     "and pick a font, or the header rows and a fill colour: the table is in one font and the header in "
                     "one colour, so one change is enough.")
            return {"_model": f"{edited['_model']}\n{printed['_model']}\n{final}", "_ui": printed["_ui"]}

        if action == "export":
            return await export_pdf(workspace, path, rel, "workbook")

        if bad := _check_ops(ops):
            return _err(bad)
        try:   # files and formula fills become plain values, formats and formulas before the service sees them
            ops, filled, typed = await asyncio.to_thread(fill.expand, ops, root)
        except fill.Bad as e:
            return _err(f"{e}. Nothing was changed.")
        said = "".join(f"{n}\n" for n in filled) + _typed_hint(typed)
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
            ack = f"Created {rel}.\n{said}{result['report']}".strip()
            return {"_model": ack, "_ui": {"type": "ui", "action": "open_canvas", "path": rel}}

        # edit
        if not ops:
            return _err("edit needs `ops`: [{\"op\": \"set_values\", \"target\": \"B3\", \"values\": [[1]]}].")
        async with lock(path):   # one change at a time per file: the model calls tools in parallel
            for attempt in (1, 2):
                data, base = await load_fig(root, rel)   # as write_fig checks it: the bucket in production
                if data is None:
                    return _err(f"{rel} does not exist (use create for a new workbook).")
                result = await client.sheets_apply(data, path.name, ops)
                if result["unchanged"]:
                    return f"Nothing in {rel} changed.\n{said}{result['report']}".strip()
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
    return {"_model": f"Edited {rel}.\n{said}{result['report']}".strip(), "_ui": ui}

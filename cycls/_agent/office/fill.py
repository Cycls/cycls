"""What `sheets` fills cells with when the model doesn't type them.

- `set_values` with `from`: the rows of a .csv, .tsv or .json file in the workspace (a query's saved result, a
  script's output), header first. Numbers stay numbers, a column of ISO dates becomes real dates with a date
  format, and no value from a file runs as a formula.
- `set_formulas` on a range larger than its formulas: the formulas fill it the way Excel's fill handle does,
  each copy's relative references moved with it (`$` keeps one fixed).

The service gets the plain ops either way (values, formulas, number formats), so it needs no change.
"""
import csv
import io
import json
import math
import re
from datetime import datetime

from ..paths import _resolve_path

MAX_CELLS = 100_000          # one fill: past this the editor chokes, and the rows should be narrowed
MAX_FILE_BYTES = 20_000_000
TYPED_HINT_CELLS = 200       # typed values past this get a reminder that a file fills faster, and exactly
_TEXT_MAX = 32_767           # the most one Excel cell holds
_MAX_COL, _MAX_ROW = 16_384, 1_048_576
_EPOCH = datetime(1899, 12, 30)

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(?:Z|[+-]\d{2}:?\d{2})?$")
_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_CELL = re.compile(r"^(?:(.+)!)?\$?([A-Za-z]{1,3})\$?(\d+)(?::\$?([A-Za-z]{1,3})\$?(\d+))?$")
# A cell reference inside a formula: not part of a name (Table1, LOG10( or Q1!), and string literals and quoted
# sheet names are skipped before this runs.
_REF = re.compile(r"(?<![A-Za-z0-9_.$])(\$?)([A-Za-z]{1,3})(\$?)(\d+)(?![A-Za-z0-9_.(!])")
_LITERAL = re.compile(r"(\"(?:[^\"]|\"\")*\"|'(?:[^']|'')*')")


class Bad(ValueError):
    """A fill that can't be made; its message goes to the model, and nothing is changed."""


def _index(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def _letters(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _where(target):
    """(sheet prefix with its !, first row, first column, last row, last column) of an A1 target; a bare sheet
    name starts at A1 of that sheet."""
    m = _CELL.match(str(target or "").strip())
    if not m:
        name = str(target or "").strip()
        return (name + "!" if name else ""), 1, 1, 1, 1
    sheet, c1, r1, c2, r2 = m.groups()
    r1, c1 = int(r1), _index(c1)
    return (sheet + "!" if sheet else ""), r1, c1, int(r2) if r2 else r1, _index(c2) if c2 else c1


# ---- the rows of a file ---------------------------------------------------------------------------------------

def _text_cell(v):
    """A CSV cell: empty → blank, a plain number → the number (not a code with a leading zero, nor more digits
    than Excel keeps), anything else as written."""
    if v == "":
        return None
    if _NUMBER.match(v) and len(v.lstrip("-").replace(".", "").split("e")[0].split("E")[0]) <= 15:
        n = float(v)
        return int(n) if n.is_integer() and "." not in v and "e" not in v.lower() else n
    return v


def _cell(v):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v if abs(v) < 10 ** 15 else str(v)   # an id longer than Excel's 15 digits stays exact as text
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    v = str(v)[:_TEXT_MAX]
    return " " + v if v.startswith("=") else v   # data never runs as a formula


def _shape_error(name):
    return Bad(f"{name}: a JSON file to fill from is {{\"columns\": [...], \"rows\": [[...]]}}, a list of rows, "
               "or a list of objects")


def load_table(path):
    """(column names or None, rows) of a .csv, .tsv or .json file."""
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".tsv", ".json"):
        raise Bad(f"{path.name}: fill from a .csv, .tsv or .json file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise Bad(f"{path.name} is over {MAX_FILE_BYTES // 1_000_000} MB: narrow the rows first")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise Bad(f"{path.name} is not UTF-8 text")
    if suffix != ".json":
        lines = [r for r in csv.reader(io.StringIO(text), delimiter="\t" if suffix == ".tsv" else ",") if r]
        if not lines:
            raise Bad(f"{path.name} is empty")
        columns, rows = lines[0], [[_text_cell(v) for v in r] for r in lines[1:]]
        # pandas' to_csv writes its index as a first, unnamed column of 0, 1, 2…: not data
        if columns and columns[0] == "" and all(r and r[0] == i for i, r in enumerate(rows)):
            columns, rows = columns[1:], [r[1:] for r in rows]
        return columns, rows
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Bad(f"{path.name} is not valid JSON ({e})")
    if isinstance(data, dict):
        if isinstance(data.get("columns"), list) and isinstance(data.get("rows"), list):
            return [str(c) for c in data["columns"]], data["rows"]
        lists = [v for v in data.values() if isinstance(v, list) and v and all(isinstance(x, (list, dict)) for x in v)]
        if len(lists) != 1:
            raise _shape_error(path.name)
        data = lists[0]
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        columns = list(dict.fromkeys(str(k) for x in data for k in x))
        return columns, [[x.get(c) for c in columns] for x in data]
    if isinstance(data, list) and all(isinstance(x, list) for x in data):
        return None, data
    raise _shape_error(path.name)


def _serial(text):
    """An ISO date or date-time as Excel's day number (time zones dropped: the wall time is kept)."""
    m = _DATETIME.match(text)
    day, clock = (m.group(1), m.group(2)) if m else (text, None)
    when = datetime.fromisoformat(f"{day}T{clock}" if clock else day)
    days = (when - _EPOCH).total_seconds() / 86_400
    return int(days) if clock is None else round(days, 9)


def _dates(rows, c):
    """The number format for column c when every value in it is an ISO date (or date-time), else None."""
    seen = [r[c] for r in rows if c < len(r) and r[c] is not None]
    if not seen or not all(isinstance(v, str) for v in seen):
        return None
    if all(_DATE.match(v) for v in seen):
        return "yyyy-mm-dd"
    if all(_DATE.match(v) or _DATETIME.match(v) for v in seen):
        return "yyyy-mm-dd hh:mm"
    return None


def _from_file(i, op, root):
    raw = str(op["from"]).strip()
    try:
        path = _resolve_path(raw, root)
    except ValueError as e:
        raise Bad(f"op {i}: {e}")
    if not path.is_file():
        raise Bad(f"op {i}: {raw} does not exist")
    columns, rows = load_table(path)
    rows = [r if isinstance(r, list) else [r] for r in rows]
    width = max([len(columns or [])] + [len(r) for r in rows])
    if not width:
        raise Bad(f"op {i}: {raw} has no rows")
    header = columns is not None and op.get("header") is not False
    if (len(rows) + header) * width > MAX_CELLS:
        raise Bad(f"op {i}: {raw} is {len(rows):,} rows × {width} columns, more than the {MAX_CELLS:,} cells one fill "
                  "takes: narrow the rows or columns, or fill it in parts")
    formats = {c: f for c in range(width) if (f := _dates(rows, c))}
    grid = [[_cell(c) for c in columns] + [None] * (width - len(columns))] if header else []
    for r in rows:
        r = [_serial(v) if c in formats and v is not None else v for c, v in enumerate(r)]
        grid.append([_cell(v) for v in r] + [None] * (width - len(r)))
    sheet, r1, c1, _, _ = _where(op.get("target"))
    first, last = r1 + header, r1 + len(grid) - 1
    out = [{"op": "set_values", "target": op.get("target"), "values": grid}]
    for c, fmt in formats.items():
        if rows:
            col = _letters(c1 + c)
            out.append({"op": "format", "target": f"{sheet}{col}{first}:{col}{last}", "number_format": fmt})
    names = columns or [f"column {k + 1}" for k in range(width)]
    shown = ", ".join(f"{_letters(c1 + k)} {names[k] if k < len(names) else ''}".strip() for k in range(min(width, 30)))
    note = (f"op {i}: {len(rows):,} rows from {raw} into {sheet}{_letters(c1)}{r1}:{_letters(c1 + width - 1)}{last}"
            + (f" (header in row {r1}, data from row {first})" if header else "") + f"; columns {shown}"
            + (" …" if width > 30 else "")
            + (f"; dates in {', '.join(_letters(c1 + c) for c in formats)}" if formats and rows else ""))
    return out, note


# ---- one formula over a range ---------------------------------------------------------------------------------

def shift(formula, rows, cols):
    """The formula as it reads `rows` down and `cols` across: relative references move, $ ones stay, and one
    moved off the sheet is #REF!."""
    def moved(m):
        dc, col, dr, row = m.groups()
        c, r = _index(col), int(row)
        if c > _MAX_COL or r > _MAX_ROW:
            return m.group(0)   # a name that looks like a cell, not one
        c, r = c + (0 if dc else cols), r + (0 if dr else rows)
        if c < 1 or r < 1 or c > _MAX_COL or r > _MAX_ROW:
            return "#REF!"
        return f"{dc}{_letters(c)}{dr}{r}"
    parts = _LITERAL.split(formula)
    return "".join(p if k % 2 else _REF.sub(moved, p) for k, p in enumerate(parts))


def _fill_formulas(i, op):
    grid = op.get("formulas")
    m = _CELL.match(str(op.get("target") or "").strip())
    if not (m and m.group(4) and isinstance(grid, list) and grid):
        return op
    _, r1, c1, r2, c2 = _where(op["target"])
    grid = [r if isinstance(r, list) else [r] for r in grid]
    rows, cols = len(grid), max(len(r) for r in grid)
    height, width = r2 - r1 + 1, c2 - c1 + 1
    if height <= rows and width <= cols:
        return op
    if height * width > MAX_CELLS:
        raise Bad(f"op {i}: {op['target']} is more than the {MAX_CELLS:,} cells one fill takes")
    filled = []
    for r in range(max(height, rows)):
        line = []
        for c in range(max(width, cols)):
            src = grid[r % rows]
            f = str(src[c % cols]) if c % cols < len(src) and src[c % cols] is not None else ""
            line.append(shift(f, r - r % rows, c - c % cols) if f else "")
        filled.append(line)
    return {**op, "formulas": filled}


def expand(ops, root):
    """The ops as the service takes them → (ops, what the fills say for the reply, how many cells were typed)."""
    out, notes, typed = [], [], 0
    for i, op in enumerate(ops, 1):
        if op.get("op") == "set_values" and op.get("from"):
            if op.get("values"):
                raise Bad(f"op {i}: give `values` or `from`, not both")
            made, note = _from_file(i, op, root)
            out += made
            notes.append(note)
        elif op.get("op") == "set_formulas":
            out.append(_fill_formulas(i, op))
        else:
            if op.get("op") == "set_values" and isinstance(op.get("values"), list):
                typed += sum(len(r) if isinstance(r, list) else 1 for r in op["values"])
            out.append(op)
    return out, notes, typed

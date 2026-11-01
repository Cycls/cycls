"""Bash kept off the Word and Excel files that `docs` and `sheets` look after.

While Docs (or Sheets) is on, a Bash command that opens an existing .docx (or .xlsx) as a package — unzip, zipfile,
python-docx, openpyxl, pandoc… — is refused before it runs, with a pointer to the tool. Such a command goes round
the file's lock, its versions and the person's open editor; on super-dev the agent "repaired" a document with a zip
script (2026-10-26) and, with the prompt telling it not to, still read the XML with Bash to check a `docs` edit
(2026-10-27). Copying, moving, listing or deleting the file stays Bash's, and so do pandas reads for analysis.

A file a Bash command made this turn (the docx / xlsx skills build new files) may be opened by later commands of the
turn: its validation step runs. Rebuilding a file that already existed is refused like any other change to it.
"""
import re
from pathlib import Path

_KIND = {".docx": "docs", ".xlsx": "sheets", ".xlsm": "sheets"}
_EXT = r"\.(?:docx|xlsx|xlsm)"
# A path in quotes (spaces and Arabic allowed), or a bare one (no spaces or shell punctuation).
_QUOTED = re.compile(r"""(['"])([^'"\n]*?""" + _EXT + r""")\1""", re.I)
_BARE = re.compile(r"""(?<![\w./*?-])([^\s'"`;|&<>()=,\[\]{}]+""" + _EXT + r""")(?![\w.])""", re.I)
_SCRIPT = re.compile(r"""(?:(['"])([^'"\n]+\.py)\1|(?<![\w./-])([^\s'"`;|&<>()=,]+\.py)(?![\w.]))""")
_CD = re.compile(r"""\bcd\s+(?:(['"])([^'"\n]+)\1|([^\s;&|]+))""")
# What opens a Word or Excel file as a package, or writes one.
_OPENS = re.compile(r"\b(?:unzip|zipinfo|zipfile|ZipFile|7za?|bsdtar|import\s+docx|from\s+docx|docx2txt|docx2python|"
                    r"mammoth|pandoc|openpyxl|load_workbook|xlsxwriter|ExcelWriter|to_excel|xlsx2csv|soffice|"
                    r"libreoffice)\b")
# pandas reading with openpyxl named as its engine is still a read for analysis.
_ENGINE = re.compile(r"""engine\s*=\s*['"]openpyxl['"]""")
_MAX_SCRIPT = 256 * 1024
_MAX_GLOB = 50


def _inside(root: Path, rel: str, base: Path = None):
    """`rel` as a path in the workspace `root` (relative ones from `base`, a folder in it), or None outside it."""
    rel = rel.strip()
    if rel.startswith("/workspace"):
        rel, base = rel[len("/workspace"):].lstrip("/"), root
    elif rel.startswith("/") or rel.startswith("~"):
        return None   # outside the workspace (/tmp is not shared with the file tools anyway)
    try:
        path = ((base or root) / rel).resolve()
    except (OSError, ValueError):
        return None
    return path if path == root or root in path.parents else None


def _places(root: Path, command: str):
    """The folders a relative path may be under: the workspace, and each folder the command `cd`s into."""
    out = [root]
    for m in _CD.finditer(command):
        if (d := _inside(root, m.group(2) or m.group(3) or "", out[-1])) and d not in out:
            out.append(d)
    return out


def _named(text: str):
    names = [m.group(2) for m in _QUOTED.finditer(text)]
    names += [m.group(1) for m in _BARE.finditer(_QUOTED.sub(" ", text))]
    return names


def _scripts(root: Path, command: str, places):
    """The text of the workspace's Python scripts the command runs (a script can open the file by name)."""
    texts = []
    for m in _SCRIPT.finditer(command):
        name = m.group(2) or m.group(3)
        for base in places:
            path = _inside(root, name, base)
            if path and path.is_file() and path.stat().st_size <= _MAX_SCRIPT:
                try:
                    texts.append(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
                break
    return texts


def _files(root: Path, command: str):
    """(text the command runs, every Word / Excel path it names, resolved in the workspace — existing or not)."""
    root = Path(root).resolve()
    places = _places(root, command)
    text = "\n".join([command, *_scripts(root, command, places)])
    found = []
    for name in _named(text):
        for base in places:
            if any(c in name for c in "*?["):
                rel, at = (name[len("/workspace/"):], root) if name.startswith("/workspace/") else (name, base)
                if rel.startswith("/") or ".." in rel:
                    continue
                try:
                    found += [p.resolve() for p in list(at.glob(rel))[:_MAX_GLOB] if p.is_file()]
                except (OSError, ValueError, NotImplementedError):
                    pass
            elif path := _inside(root, name, base):
                found.append(path)
    return text, list(dict.fromkeys(found))


def refusal(command: str, root, office, built=()) -> str | None:
    """The error for a command that opens a Word / Excel file the agent's `docs` / `sheets` look after, else None."""
    if not office or not command:
        return None
    text, paths = _files(root, command)
    if not _OPENS.search(_ENGINE.sub(" ", text)):
        return None
    for path in paths:
        tool = _KIND.get(path.suffix.lower())
        if tool in office and path.is_file() and str(path) not in built:
            rel = path.relative_to(Path(root).resolve()).as_posix()
            if tool == "docs":
                return (f"Error: not run — {rel} is a Word document, and Word documents in the workspace are read with "
                        "`docs` read and changed with `docs` edit, never opened with Bash (zip, python-docx, XML). "
                        "`docs` keeps the file's lock, its versions and the person's open editor, and its reply "
                        "already shows the file as it now is. Copying, moving or listing it with Bash is fine; so is a "
                        "new Word file built under a name that is not taken.")
            return (f"Error: not run — {rel} is an Excel workbook, and workbooks in the workspace are read with "
                    "`sheets` read and changed with `sheets` edit, never opened with Bash (zip, openpyxl, XML). "
                    "`sheets` keeps the file's lock, its versions and the person's open editor, and its reply already "
                    "shows the changed cells. pandas.read_excel stays fine for analysing the data; copying, moving or "
                    "listing it is fine; so is a new workbook built under a name that is not taken.")
    return None


def missing(command: str, root) -> list[str]:
    """The Word / Excel paths a command names that do not exist yet (those it makes are the turn's own)."""
    _, paths = _files(root, command)
    return [str(p) for p in paths if p.suffix.lower() in _KIND and not p.exists()]


def made(before: list[str]) -> set[str]:
    return {p for p in before if Path(p).is_file()}

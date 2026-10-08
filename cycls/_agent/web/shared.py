"""What the route modules share: the header that makes a browser ask again, a path kept
inside the workspace (and the 403 a route answers when it is not), and a name for a new
file that overwrites nothing."""
import unicodedata
from pathlib import Path
from fastapi import HTTPException

from cycls._agent.design import refresh as design_refresh


# FileResponse sets ETag/Last-Modified but no Cache-Control, and heuristic
# freshness (browsers, iOS URLCache) then serves stale bytes after a write.
# no-cache keeps the cache but forces revalidation — 304 when unchanged.
_NO_CACHE = {"Cache-Control": "no-cache"}


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


def _safe_path(workspace, rel):
    try:
        return resolve_path(workspace, rel)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path traversal denied")


def _free_rel(root, rel):
    """A name for a new file at `rel` that overwrites nothing: `rel` itself, else
    `<stem>-2`, `-3`, … It's free when no file has it and it isn't an image the design
    refresh keeps beside a .fig (that would be overwritten by the next re-export); a
    .fig under designs/ also keeps clear of another design's images and deck, as a
    fresh render does (`_dedupe_design_name`)."""
    from cycls._agent.design.files import _dedupe_design_name
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

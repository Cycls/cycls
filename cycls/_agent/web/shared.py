"""What the route modules share: no-cache headers, workspace path safety, a free file name."""
import unicodedata
from pathlib import Path
from fastapi import HTTPException
from cycls._agent.paths import MANAGED


# FileResponse sets ETag/Last-Modified but no Cache-Control, and heuristic
# freshness (browsers, iOS URLCache) then serves stale bytes after a write.
# no-cache keeps the cache but forces revalidation — 304 when unchanged.
_NO_CACHE = {"Cache-Control": "no-cache"}


# ---- Path safety ----

def resolve_path(workspace, rel):
    """Resolve *rel* inside *workspace*, raising ValueError on traversal or
    access to a slot cycls manages (MANAGED)."""
    workspace = Path(workspace)
    rel = unicodedata.normalize("NFC", rel)
    resolved = (workspace / rel).resolve()
    ws = workspace.resolve()
    if not resolved.is_relative_to(ws):
        raise ValueError("Path traversal denied")
    for name in MANAGED:
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
    """A name for a new file that overwrites nothing: `rel`, else `<stem>-2`, …"""
    path, root = Path(rel), Path(root)
    stem, suffix = (path.name[:-len(path.suffix)], path.suffix) if path.suffix else (path.name, "")
    if not (root / rel).exists():
        return rel
    n = 2
    while (root / (cand := (path.parent / f"{stem}-{n}{suffix}").as_posix())).exists():
        n += 1
    return cand

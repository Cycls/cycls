"""A path a tool was given, as a path inside the workspace — or the reason it isn't one.
Shared by every tool that reads or writes files (cycls/_agent/tools, cycls/_agent/design)."""
import os, pathlib
from . import credentials


_TMP_ERROR = ("/tmp is not shared — every bash command gets its own, discarded when it "
              "exits, and the file tools cannot see it. Use .tmp/ for scratch and the workspace "
              "root for files the user keeps")


def _resolve_path(raw_path, workspace):
    ws = pathlib.Path(workspace).resolve()
    # Every other absolute path is silently read as workspace-relative, which
    # turns a /tmp write into a confusing "does not exist" one step later.
    if raw_path == "/tmp" or raw_path.startswith("/tmp/"):
        raise ValueError(_TMP_ERROR)
    # HOME is /workspace in the sandbox, so `~/x` names a workspace file.
    rel = raw_path.removeprefix("~/").removeprefix("/workspace/").lstrip("/")
    path = (ws / rel).resolve()
    if not path.is_relative_to(ws): raise ValueError("path escapes workspace")
    for name in (".db", ".database", ".trash", ".versions", ".settings", credentials.USER, credentials.SHARED):
        reserved = ws / name
        if path == reserved or path.is_relative_to(reserved):
            raise ValueError(f"{name}/ is managed by cycls")
    return path


def _safe_filename(name, default="download"):
    """A filename safe to write under the workspace: basename only (no path
    traversal via `/`, `\\`, or `..`), trimmed, with a fallback."""
    base = os.path.basename((name or "").replace("\\", "/")).strip().strip(".")
    return base or default

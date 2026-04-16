"""cycls.Dict + cycls.Workspace — persistent dict scoped to a workspace.

Workspace is a context manager over a Path. Dict is a persistent dict that
reads the active workspace from a ContextVar. JSON-serialized, atomic writes
via temp+rename. __getitem__/get return deep copies so in-place mutation of
nested values can't silently skip _save() (matches Modal's Dict semantics).
"""
import contextvars
import copy
import json
from pathlib import Path


_current_workspace = contextvars.ContextVar("cycls_workspace")


class Workspace:
    def __init__(self, root, user_id=None):
        self.root = Path(root)
        # Personal: .cycls/ directly under root.
        # Org: .cycls/{user_id}/ so members stay isolated in a shared mount.
        self.data = self.root / ".cycls" / user_id if user_id else self.root / ".cycls"

    def __enter__(self):
        self._token = _current_workspace.set(self)
        self.data.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *a):
        _current_workspace.reset(self._token)


class Dict(dict):
    def __init__(self, name):
        try:
            ws = _current_workspace.get()
        except LookupError:
            raise RuntimeError(
                f"cycls.Dict({name!r}) used outside a workspace scope — "
                f"wrap in `with context.workspace():`"
            )
        self._path = ws.data / f"{name}.json"
        if self._path.exists():
            super().update(json.loads(self._path.read_text()))

    def _save(self):
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dict(self)))
        tmp.rename(self._path)

    def __getitem__(self, k):
        return copy.deepcopy(super().__getitem__(k))

    def get(self, k, d=None):
        return copy.deepcopy(super().get(k, d))

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self._save()

    def __delitem__(self, k):
        super().__delitem__(k)
        self._save()

    def update(self, *a, **kw):
        super().update(*a, **kw)
        self._save()

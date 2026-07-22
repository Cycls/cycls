"""cycls.Volume — named, account-scoped persistent storage.

Attach to any deployment via `volumes={"/data": vol}`. Referencing a volume
on deploy creates it if missing; the `cycls volume` CLI manages contents.
Volumes are shared files, not a database: concurrent writers to the same
file are last-write-wins.
"""
import json


class Volume:
    def __init__(self, name, *, read_only=False, sub_path=None):
        self.name = name
        self._read_only = read_only
        self._sub_path = sub_path

    def read_only(self):
        """Mount without write access — e.g. prod data into a dev deployment."""
        return Volume(self.name, read_only=True, sub_path=self._sub_path)

    def sub_path(self, path):
        """Mount only a subdirectory of the volume."""
        return Volume(self.name, read_only=self._read_only, sub_path=path)

    def _wire(self):
        out = {"name": self.name}
        if self._read_only:
            out["read_only"] = True
        if self._sub_path is not None:
            out["sub_path"] = self._sub_path
        return out


def to_wire(volumes):
    """{path: Volume} → the deploy `volumes` form field (JSON string)."""
    out = {}
    for path, v in volumes.items():
        if not isinstance(v, Volume):
            hint = f" — e.g. cycls.Volume({v!r})" if isinstance(v, str) else ""
            raise TypeError(f"volumes[{path!r}] must be a cycls.Volume{hint}")
        out[path] = v._wire()
    return json.dumps(out, sort_keys=True)

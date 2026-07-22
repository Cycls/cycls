"""Workspace + DB — per-tenant JSON KV over object storage.

`file://` (dev) and `gs://` (prod). `db.scan(...)` is the 1-round-trip
listing path: object storage uses LIST + custom-meta; FS uses `pathlib.glob`
+ body reads (no metadata channel locally). `meta=` on `db.put` is an
object-storage-only perf hint — body is canonical on FS.
"""
import asyncio, json, os, re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

# Workspace ids are namespaced: `u-{user_id}` personal, `t-{id}` team (see
# docs/workspaces.md). The prefix split means a team workspace can never
# be named to collide with someone's personal one.
_WS_ID = re.compile(r"^[ut]-[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Workspace:
    root: Path
    path: str
    subject: str
    base: str | None = None
    ws: str | None = None

    @property
    def volume(self) -> Path:
        """The deployment volume this workspace lives under."""
        root = Path(self.root)
        return root.parents[2] if self.ws else root.parent


def workspace(target, volume, base=None, slot=".db", ws=None):
    """Derive a Workspace from a User, a subject string, or None (anonymous).

    `ws` (multi-workspace mode) adds a folder dimension below the org:
    root `{volume}/{org}/ws/{ws}`, DB path `{org}/ws/{ws}/{slot}/{user}`.
    Without it, legacy layout: root `{volume}/{org}`, path `{org}/{slot}/{user}`.
    """
    sub = ("local" if target is None
           else target if isinstance(target, str)
           else f"{target.org_id}:{target.id}" if getattr(target, "org_id", None)
           else target.id)
    org, _, user = sub.partition(":")
    for seg in (org, user):
        if seg and (seg in (".", "..") or "/" in seg or "\\" in seg):
            raise ValueError(f"invalid workspace subject: {sub!r}")
    if ws is not None and not _WS_ID.match(ws):
        raise ValueError(f"invalid workspace id: {ws!r}")
    parts = [org, "ws", ws] if ws else [org]
    path = "/".join([*parts, slot, user] if user else [*parts, slot])
    return Workspace(Path(volume).joinpath(*parts), path, sub, base, ws)


_METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
_gcs_client = None
_gcs_token = None
_gcs_token_expires = 0.0


def _gcs_client_get():
    global _gcs_client
    if _gcs_client is None:
        import httpx
        _gcs_client = httpx.AsyncClient(timeout=30.0)
    return _gcs_client


async def _gcs_auth():
    global _gcs_token, _gcs_token_expires
    import time
    if not _gcs_token or time.time() >= _gcs_token_expires - 60:
        r = await _gcs_client_get().get(_METADATA_URL, headers={"Metadata-Flavor": "Google"})
        r.raise_for_status()
        data = r.json()
        _gcs_token = data["access_token"]
        _gcs_token_expires = time.time() + data.get("expires_in", 3600)
    return {"Authorization": f"Bearer {_gcs_token}"}


class _FileStore:
    def __init__(self, url):
        self.root = Path(url[7:])

    def _path(self, key): return self.root / f"{key}.json"

    async def read(self, key):
        def _do():
            try: return self._path(key).read_bytes()
            except FileNotFoundError: return None
        return await asyncio.to_thread(_do)

    async def write(self, key, data, meta=None):
        def _do():
            p = self._path(key)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp"); tmp.write_bytes(data); tmp.replace(p)
        await asyncio.to_thread(_do)

    async def remove(self, key):
        await asyncio.to_thread(lambda: self._path(key).unlink(missing_ok=True))

    async def remove_prefix(self, prefix):
        if not prefix: raise ValueError("remove_prefix requires non-empty prefix")
        def _do():
            target = self.root / prefix
            if target.is_dir():
                import shutil
                shutil.rmtree(target)
        await asyncio.to_thread(_do)

    def _walk(self, *, prefix=None, glob=None):
        """Yield (key, path) for matching .json files."""
        if not self.root.exists(): return
        if glob is not None:
            paths = self.root.glob(f"{glob}.json")
        else:
            target = self.root / (prefix or "")
            paths = (target if target.is_dir() else self.root).rglob("*.json")
        for p in paths:
            key = str(p.relative_to(self.root).with_suffix("")).replace(os.sep, "/")
            if prefix and not key.startswith(prefix): continue
            yield key, p

    async def list_keys(self, *, prefix=None, glob=None):
        return await asyncio.to_thread(lambda: [k for k, _ in self._walk(prefix=prefix, glob=glob)])

    async def list_metas(self, *, prefix=None, glob=None):
        def _do():
            out = []
            for k, p in self._walk(prefix=prefix, glob=glob):
                try: out.append((k, json.loads(p.read_bytes())))
                except (json.JSONDecodeError, FileNotFoundError): pass
            return out
        return await asyncio.to_thread(_do)


class _GCSStore:
    _STORAGE = "https://storage.googleapis.com"

    def __init__(self, url):
        bucket, _, prefix = url[5:].partition("/")
        self.bucket = bucket
        self.prefix = (prefix.rstrip("/") + "/") if prefix else ""

    def _name(self, key): return f"{self.prefix}{key}.json"
    def _obj(self, key): return quote(self._name(key), safe="")

    async def _req(self, method, url, **kw):
        kw.setdefault("headers", {}).update(await _gcs_auth())
        return await _gcs_client_get().request(method, url, **kw)

    async def read(self, key):
        r = await self._req("GET", f"{self._STORAGE}/storage/v1/b/{self.bucket}/o/{self._obj(key)}?alt=media")
        if r.status_code == 404: return None
        r.raise_for_status()
        return r.content

    async def write(self, key, data, meta=None):
        info = {"name": self._name(key)}
        if meta: info["metadata"] = meta
        body = b"\r\n".join([
            b"--cycls", b"Content-Type: application/json; charset=UTF-8", b"",
            json.dumps(info).encode(),
            b"--cycls", b"Content-Type: application/json", b"",
            data,
            b"--cycls--", b"",
        ])
        r = await self._req("POST",
            f"{self._STORAGE}/upload/storage/v1/b/{self.bucket}/o?uploadType=multipart",
            headers={"Content-Type": "multipart/related; boundary=cycls"}, content=body)
        r.raise_for_status()

    async def remove(self, key):
        r = await self._req("DELETE", f"{self._STORAGE}/storage/v1/b/{self.bucket}/o/{self._obj(key)}")
        if r.status_code not in (200, 204, 404): r.raise_for_status()

    async def remove_prefix(self, prefix):
        if not prefix: raise ValueError("remove_prefix requires non-empty prefix")
        keys = await self.list_keys(prefix=prefix)
        await asyncio.gather(*[self.remove(k) for k in keys])

    async def _list(self, fields, *, prefix=None, glob=None):
        items, page_token = [], None
        while True:
            params = {"fields": fields}
            if glob is not None:
                params["matchGlob"] = f"{self.prefix}{glob}.json"
            else:
                params["prefix"] = f"{self.prefix}{prefix or ''}"
            if page_token: params["pageToken"] = page_token
            r = await self._req("GET", f"{self._STORAGE}/storage/v1/b/{self.bucket}/o", params=params)
            r.raise_for_status()
            data = r.json()
            items.extend(it for it in data.get("items", []) if it["name"].endswith(".json"))
            page_token = data.get("nextPageToken")
            if not page_token: break
        return items

    async def list_keys(self, *, prefix=None, glob=None):
        p, n = len(self.prefix), -len(".json")
        return [it["name"][p:n] for it in await self._list("items(name),nextPageToken", prefix=prefix, glob=glob)]

    async def list_metas(self, *, prefix=None, glob=None):
        p, n = len(self.prefix), -len(".json")
        return [(it["name"][p:n], it.get("metadata") or {})
                for it in await self._list("items(name,metadata),nextPageToken", prefix=prefix, glob=glob)]


def _store(url):
    if url.startswith("file://"): return _FileStore(url)
    if url.startswith("gs://"): return _GCSStore(url)
    raise ValueError(f"Unsupported URL: {url}")


class DB:
    def __init__(self, workspace, base=None):
        self._store = _store(f"{(base or workspace.base).rstrip('/')}/{workspace.path}")

    async def get(self, key, default=None):
        data = await self._store.read(key)
        return json.loads(data) if data is not None else default

    async def put(self, key, value, *, meta=None):
        if meta:
            bad = [(k, type(v).__name__) for k, v in meta.items() if not isinstance(v, str)]
            if bad: raise TypeError(f"meta values must be str; got non-string: {bad}")
        await self._store.write(key, json.dumps(value).encode(), meta=meta)

    async def delete(self, target):
        if not target or target.startswith("/") or ".." in target.split("/"):
            raise ValueError(f"invalid delete target: {target!r}")
        if target.endswith("/"):
            await self._store.remove_prefix(target)
        else:
            await self._store.remove(target)

    async def items(self, *, prefix=None, glob=None, limit=None):
        keys = sorted(await self._store.list_keys(prefix=prefix, glob=glob))
        if limit is not None: keys = keys[:limit]
        async def _fetch(k):
            data = await self._store.read(k)
            return None if data is None else (k, json.loads(data))
        for r in await asyncio.gather(*[_fetch(k) for k in keys]):
            if r is not None: yield r

    async def scan(self, *, prefix=None, glob=None):
        """Yield (key, meta) — `meta` is object-storage custom-meta or, on local
        FS, the body. `glob` uses `*` to match non-`/`."""
        for k, m in sorted(await self._store.list_metas(prefix=prefix, glob=glob)):
            yield k, m

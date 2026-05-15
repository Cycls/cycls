"""Workspace + DB — per-tenant JSON KV over object storage.

`file://` (dev) and `gs://` (prod). `db.put(k, v, meta=...)` carries
per-key metadata; `db.index(prefix)` enumerates names+meta cheaply
(GCS `x-goog-meta-*` headers; local `.meta` sidecars).
"""
import asyncio, json, os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


@dataclass(frozen=True)
class Workspace:
    root: Path
    path: str
    subject: str
    base: str | None = None


def workspace_for(user, volume, base=None):
    sub = ("local" if user is None
           else f"{user.org_id}:{user.id}" if getattr(user, "org_id", None)
           else user.id)
    return workspace_at(sub, volume, base)


def workspace_at(tenant, volume, base=None, slot=".db"):
    org, _, user = tenant.partition(":")
    path = f"{org}/{slot}/{user}" if user else f"{org}/{slot}"
    return Workspace(Path(volume) / org, path, tenant, base)


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


async def shutdown_pool():
    global _gcs_client, _gcs_token
    if _gcs_client: await _gcs_client.aclose()
    _gcs_client = _gcs_token = None


class _FileStore:
    def __init__(self, url):
        self.root = Path(url[7:])

    def _path(self, key, ext=".json"): return self.root / f"{key}{ext}"

    async def read(self, key):
        def _do():
            try: return self._path(key).read_bytes()
            except FileNotFoundError: return None
        return await asyncio.to_thread(_do)

    async def write(self, key, data, meta=None):
        def _do():
            p, mp = self._path(key), self._path(key, ".meta")
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp"); tmp.write_bytes(data); tmp.replace(p)
            if meta is not None:
                mt = mp.with_suffix(".meta.tmp"); mt.write_text(json.dumps(meta)); mt.replace(mp)
            else:
                mp.unlink(missing_ok=True)
        await asyncio.to_thread(_do)

    async def remove(self, key):
        def _do():
            self._path(key).unlink(missing_ok=True)
            self._path(key, ".meta").unlink(missing_ok=True)
        await asyncio.to_thread(_do)

    async def remove_prefix(self, prefix):
        def _do():
            target = self.root / prefix
            if target.is_dir():
                import shutil
                shutil.rmtree(target)
        await asyncio.to_thread(_do)

    async def _walk(self, prefix, with_meta):
        def _do():
            if not self.root.exists(): return []
            target = self.root / prefix
            search = target if target.is_dir() else self.root
            out = []
            for p in search.rglob("*.json"):
                key = str(p.relative_to(self.root).with_suffix("")).replace(os.sep, "/")
                if not key.startswith(prefix): continue
                if with_meta:
                    try: meta = json.loads(p.with_suffix(".meta").read_text())
                    except (FileNotFoundError, json.JSONDecodeError): meta = {}
                    out.append((key, meta))
                else:
                    out.append(key)
            return out
        return await asyncio.to_thread(_do)

    async def list_keys(self, prefix): return await self._walk(prefix, False)
    async def list_metas(self, prefix): return await self._walk(prefix, True)


class _GCSStore:
    _STORAGE = "https://storage.googleapis.com"

    def __init__(self, url):
        bucket, _, prefix = url[5:].partition("/")
        self.bucket = bucket
        self.prefix = (prefix.rstrip("/") + "/") if prefix else ""

    def _obj(self, key): return quote(f"{self.prefix}{key}.json", safe="")

    async def _req(self, method, url, **kw):
        kw.setdefault("headers", {}).update(await _gcs_auth())
        return await _gcs_client_get().request(method, url, **kw)

    async def read(self, key):
        r = await self._req("GET", f"{self._STORAGE}/storage/v1/b/{self.bucket}/o/{self._obj(key)}?alt=media")
        if r.status_code == 404: return None
        r.raise_for_status()
        return r.content

    async def write(self, key, data, meta=None):
        headers = {"Content-Type": "application/json"}
        if meta:
            # Percent-encode values: HTTP headers are ASCII-only, but titles
            # can contain non-ASCII (e.g. Arabic). Without this, the header
            # silently drops or corrupts and the metadata roundtrips empty.
            for k, v in meta.items(): headers[f"x-goog-meta-{k}"] = quote(str(v), safe="")
        r = await self._req("POST",
            f"{self._STORAGE}/upload/storage/v1/b/{self.bucket}/o?uploadType=media&name={self._obj(key)}",
            headers=headers, content=data)
        r.raise_for_status()

    async def remove(self, key):
        r = await self._req("DELETE", f"{self._STORAGE}/storage/v1/b/{self.bucket}/o/{self._obj(key)}")
        if r.status_code not in (200, 204, 404): r.raise_for_status()

    async def remove_prefix(self, prefix):
        keys = await self.list_keys(prefix)
        await asyncio.gather(*[self.remove(k) for k in keys])

    async def _list(self, prefix, fields):
        items, page_token = [], None
        while True:
            params = {"prefix": f"{self.prefix}{prefix}", "fields": fields}
            if page_token: params["pageToken"] = page_token
            r = await self._req("GET", f"{self._STORAGE}/storage/v1/b/{self.bucket}/o", params=params)
            r.raise_for_status()
            data = r.json()
            items.extend(it for it in data.get("items", []) if it["name"].endswith(".json"))
            page_token = data.get("nextPageToken")
            if not page_token: break
        return items

    def _key_of(self, name): return name[len(self.prefix):-len(".json")]

    async def list_keys(self, prefix):
        return [self._key_of(it["name"]) for it in await self._list(prefix, "items(name),nextPageToken")]

    async def list_metas(self, prefix):
        from urllib.parse import unquote
        return [(self._key_of(it["name"]),
                 {k: unquote(v) for k, v in (it.get("metadata") or {}).items()})
                for it in await self._list(prefix, "items(name,metadata),nextPageToken")]


def _store(url):
    if url.startswith("file://"): return _FileStore(url)
    if url.startswith("gs://"): return _GCSStore(url)
    raise ValueError(f"Unsupported URL: {url}")


class DB:
    def __init__(self, workspace, base=None):
        self._url = f"{(base or workspace.base).rstrip('/')}/{workspace.path}"
        self._store = _store(self._url)

    async def get(self, key, default=None):
        data = await self._store.read(key)
        return json.loads(data) if data is not None else default

    async def put(self, key, value, *, meta=None):
        await self._store.write(key, json.dumps(value).encode(), meta=meta)

    async def delete(self, key):
        await self._store.remove(key)

    async def delete_prefix(self, prefix):
        await self._store.remove_prefix(prefix)

    async def items(self, prefix=None):
        keys = await self._store.list_keys(prefix or "")
        async def _fetch(k):
            data = await self._store.read(k)
            return None if data is None else (k, json.loads(data))
        results = await asyncio.gather(*[_fetch(k) for k in keys])
        for k, v in sorted(r for r in results if r is not None):
            yield k, v

    async def index(self, prefix=None):
        for k, m in sorted(await self._store.list_metas(prefix or "")):
            yield k, m

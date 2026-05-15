"""Workspace — per-tenant `(root, path, base)` + JSON KV over a pluggable engine.

The auth ↔ workspace contract: `workspace_for(user, ...)` reads `user.id` and
optionally `user.org_id`, the only `User` fields workspace logic depends on.

`DB` runs JSON KV at `<base>/<path>`. Two engines, selected by
`CYCLS_DB_ENGINE`:

- `jsonl` (default) — local `file://` paths use append-only JSONL for
  `chat/log/{id}/*` (one file per chat, O(1) append via O_APPEND). GCS
  `gs://` paths use one object per key (O(1) PUT, parallel GETs on scan).
  Other keys are always individual JSON objects.
- `slatedb` — LSM over object storage. Preserved as an opt-in.
"""
import asyncio, json, os, uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote


# ---- Debug instrumentation ----

DEBUG = True

_REV = os.environ.get("K_REVISION", "local")[-12:]
_PID = uuid.uuid4().hex[:6]
_INSTANCE = f"{_REV}/{_PID}"

def _log(op, **kv):
    if not DEBUG: return
    extras = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"[WS/{_INSTANCE}] {op} {extras}", flush=True)


# ---- Tenant shape ----

@dataclass(frozen=True)
class Workspace:
    root: Path
    path: str
    subject: str
    base: Optional[str] = None


def workspace_for(user, volume, base=None) -> Workspace:
    if user is None:
        sub = "local"
    elif getattr(user, "org_id", None):
        sub = f"{user.org_id}:{user.id}"
    else:
        sub = user.id
    return workspace_at(sub, volume, base)


def workspace_at(tenant, volume, base=None, slot=".db") -> Workspace:
    volume = Path(volume)
    if ":" in tenant:
        org, user = tenant.split(":", 1)
        return Workspace(root=volume / org, path=f"{org}/{slot}/{user}", subject=tenant, base=base)
    return Workspace(root=volume / tenant, path=f"{tenant}/{slot}", subject=tenant, base=base)


# ---- Engine selection ----

_ENGINE = os.environ.get("CYCLS_DB_ENGINE", "jsonl").lower()


class _Deleted:
    __slots__ = ()
_DELETED = _Deleted()


# ---- JSONL engine: local (file://) ----

def _split_log_key(key):
    parts = key.split("/")
    if len(parts) == 4 and parts[0] == "chat" and parts[1] == "log":
        return parts[2], parts[3]
    return None


def _is_log_prefix(prefix):
    parts = prefix.rstrip("/").split("/")
    return len(parts) == 3 and parts[0] == "chat" and parts[1] == "log"


class _LocalEngine:
    def __init__(self, url):
        self.root = Path(url[7:])
        self.root.mkdir(parents=True, exist_ok=True)

    def _log_path(self, chat_id):
        return self.root / "chat" / "log" / f"{chat_id}.jsonl"

    def _kv_path(self, key):
        return self.root / f"{key}.json"

    async def get(self, key):
        if (lk := _split_log_key(key)):
            chat_id, seq = lk
            path = self._log_path(chat_id)
            if not path.exists(): return None
            def _read():
                latest = None
                with open(path) as f:
                    for line in f:
                        if not line.strip(): continue
                        obj = json.loads(line)
                        if obj["k"] == seq:
                            latest = None if obj.get("d") else obj["v"]
                return latest
            return await asyncio.to_thread(_read)
        path = self._kv_path(key)
        if not path.exists(): return None
        def _read_kv():
            with open(path) as f:
                return json.load(f)
        return await asyncio.to_thread(_read_kv)

    async def put(self, key, value):
        await self.commit({key: value})

    async def delete(self, key):
        await self.commit({key: _DELETED})

    async def scan(self, prefix):
        if _is_log_prefix(prefix):
            parts = prefix.rstrip("/").split("/")
            chat_id = parts[2]
            path = self._log_path(chat_id)
            if not path.exists(): return []
            def _read():
                state = {}
                with open(path) as f:
                    for line in f:
                        if not line.strip(): continue
                        obj = json.loads(line)
                        if obj.get("d"):
                            state.pop(obj["k"], None)
                        else:
                            state[obj["k"]] = obj["v"]
                return state
            state = await asyncio.to_thread(_read)
            return [(f"chat/log/{chat_id}/{k}", state[k]) for k in sorted(state.keys())]
        def _walk():
            results = []
            base = self.root
            if not base.exists(): return results
            target = base / prefix
            search_root = target if target.is_dir() else base
            for p in search_root.rglob("*.json"):
                rel = p.relative_to(base)
                key = str(rel.with_suffix("")).replace(os.sep, "/")
                if key.startswith(prefix):
                    try:
                        with open(p) as f:
                            results.append((key, json.load(f)))
                    except (OSError, json.JSONDecodeError):
                        pass
            return sorted(results)
        return await asyncio.to_thread(_walk)

    async def commit(self, buffer):
        if not buffer: return
        log_lines = {}
        kv_writes = []
        kv_deletes = []
        for key, val in buffer.items():
            if (lk := _split_log_key(key)):
                chat_id, seq = lk
                path = self._log_path(chat_id)
                if val is _DELETED:
                    line = json.dumps({"k": seq, "d": True})
                else:
                    line = json.dumps({"k": seq, "v": val})
                log_lines.setdefault(path, []).append(line)
            else:
                path = self._kv_path(key)
                if val is _DELETED:
                    kv_deletes.append(path)
                else:
                    kv_writes.append((path, val))
        def _flush():
            for path, lines in log_lines.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a") as f:
                    for line in lines:
                        f.write(line + "\n")
            for path, val in kv_writes:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".json.tmp")
                with open(tmp, "w") as f:
                    json.dump(val, f)
                tmp.replace(path)
            for path in kv_deletes:
                try: path.unlink()
                except FileNotFoundError: pass
        await asyncio.to_thread(_flush)

    async def shutdown(self):
        pass


# ---- JSONL engine: GCS (gs://) ----

class _GCSEngine:
    _META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
    _STORAGE = "https://storage.googleapis.com"

    def __init__(self, url):
        import httpx
        rest = url[5:]
        slash = rest.find("/")
        if slash == -1:
            self.bucket, self.prefix = rest, ""
        else:
            self.bucket = rest[:slash]
            self.prefix = rest[slash+1:].rstrip("/") + "/"
        self._client = httpx.AsyncClient(timeout=30.0)
        self._token = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()

    async def _auth(self):
        import time
        if self._token and time.time() < self._token_expires - 60:
            return {"Authorization": f"Bearer {self._token}"}
        async with self._token_lock:
            if self._token and time.time() < self._token_expires - 60:
                return {"Authorization": f"Bearer {self._token}"}
            r = await self._client.get(self._META, headers={"Metadata-Flavor": "Google"})
            r.raise_for_status()
            data = r.json()
            self._token = data["access_token"]
            self._token_expires = time.time() + data.get("expires_in", 3600)
            return {"Authorization": f"Bearer {self._token}"}

    def _object_name(self, key):
        return f"{self.prefix}{key}.json"

    async def get(self, key):
        obj = quote(self._object_name(key), safe="")
        url = f"{self._STORAGE}/storage/v1/b/{self.bucket}/o/{obj}?alt=media"
        r = await self._client.get(url, headers=await self._auth())
        if r.status_code == 404: return None
        r.raise_for_status()
        return r.json()

    async def put(self, key, value):
        await self.commit({key: value})

    async def delete(self, key):
        await self.commit({key: _DELETED})

    async def scan(self, prefix):
        full_prefix = f"{self.prefix}{prefix}"
        names = []
        page_token = None
        while True:
            params = {"prefix": full_prefix, "fields": "items(name),nextPageToken"}
            if page_token: params["pageToken"] = page_token
            url = f"{self._STORAGE}/storage/v1/b/{self.bucket}/o"
            r = await self._client.get(url, headers=await self._auth(), params=params)
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                name = item["name"]
                if name.endswith(".json"):
                    names.append(name)
            page_token = data.get("nextPageToken")
            if not page_token: break
        async def _fetch(name):
            key = name[len(self.prefix):-len(".json")]
            obj = quote(name, safe="")
            url = f"{self._STORAGE}/storage/v1/b/{self.bucket}/o/{obj}?alt=media"
            r = await self._client.get(url, headers=await self._auth())
            if r.status_code == 404: return None
            r.raise_for_status()
            return (key, r.json())
        results = await asyncio.gather(*[_fetch(n) for n in names])
        return sorted([(k, v) for r in results if r is not None for k, v in [r]])

    async def commit(self, buffer):
        if not buffer: return
        async def _apply(key, val):
            obj = quote(self._object_name(key), safe="")
            if val is _DELETED:
                url = f"{self._STORAGE}/storage/v1/b/{self.bucket}/o/{obj}"
                r = await self._client.delete(url, headers=await self._auth())
                if r.status_code not in (200, 204, 404):
                    r.raise_for_status()
                return
            url = f"{self._STORAGE}/upload/storage/v1/b/{self.bucket}/o?uploadType=media&name={obj}"
            body = json.dumps(val).encode()
            headers = {**(await self._auth()), "Content-Type": "application/json"}
            r = await self._client.post(url, headers=headers, content=body)
            r.raise_for_status()
        await asyncio.gather(*[_apply(k, v) for k, v in buffer.items()])

    async def shutdown(self):
        await self._client.aclose()


# ---- SlateDB engine ----

class _SlateEngine:
    def __init__(self, url):
        from slatedb.uniffi import (
            DbBuilder, ObjectStore, Settings, init_logging, LogLevel, LogCallback,
        )
        self._url = url
        if url.startswith("file://"):
            Path(url[7:]).mkdir(parents=True, exist_ok=True)
        self._builder_factory = lambda: DbBuilder("db", ObjectStore.resolve(url))
        self._settings_factory = self._make_settings
        self._db = None

    @staticmethod
    def _make_settings():
        from slatedb.uniffi import Settings
        s = Settings.default()
        s.set("l0_max_ssts", "8")
        s.set("compactor_options.poll_interval", '"1s"')
        s.set("l0_sst_size_bytes", "1048576")
        s.set("max_unflushed_bytes", "67108864")
        return s

    async def _ensure(self):
        if self._db is None:
            from slatedb.uniffi import init_logging, LogLevel, LogCallback
            try:
                class _SlateLog(LogCallback):
                    def log(self, record):
                        if not DEBUG: return
                        target = record.target or ""
                        if not target.startswith("slatedb"): return
                        _log(target, level=record.level.name, msg=record.message)
                init_logging(LogLevel.DEBUG, _SlateLog())
            except Exception:
                pass
            builder = self._builder_factory()
            builder.with_settings(self._settings_factory())
            self._db = await builder.build()
        return self._db

    async def get(self, key):
        from slatedb.uniffi import IsolationLevel
        db = await self._ensure()
        txn = await db.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try:
            v = await txn.get(key.encode())
        finally:
            await txn.rollback()
        return json.loads(v) if v is not None else None

    async def put(self, key, value):
        await self.commit({key: value})

    async def delete(self, key):
        await self.commit({key: _DELETED})

    async def scan(self, prefix):
        from slatedb.uniffi import IsolationLevel
        db = await self._ensure()
        txn = await db.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        results = []
        try:
            it = await txn.scan_prefix((prefix or "").encode())
            while (kv := await it.next()) is not None:
                results.append((kv.key.decode(), json.loads(kv.value)))
        finally:
            await txn.rollback()
        return results

    async def commit(self, buffer):
        if not buffer: return
        from slatedb.uniffi import IsolationLevel, WriteOptions
        db = await self._ensure()
        txn = await db.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try:
            for key, val in buffer.items():
                if val is _DELETED:
                    await txn.delete(key.encode())
                else:
                    await txn.put(key.encode(), json.dumps(val).encode())
            await txn.commit_with_options(WriteOptions(await_durable=False))
        except Exception:
            await txn.rollback()
            raise

    async def shutdown(self):
        if self._db is not None:
            try: await self._db.shutdown()
            except Exception as e: print(f"[WARN] slate shutdown failed: {e}", flush=True)


# ---- Pool ----

_pool: dict = {}
_pool_lock = asyncio.Lock()
_url_locks: dict = {}


def _make_engine(url):
    if _ENGINE == "slatedb":
        return _SlateEngine(url)
    if url.startswith("file://"):
        return _LocalEngine(url)
    if url.startswith("gs://"):
        return _GCSEngine(url)
    raise ValueError(f"Unsupported URL: {url}")


async def _get_engine(url):
    if url in _pool: return _pool[url]
    lock = _url_locks.setdefault(url, asyncio.Lock())
    async with lock:
        if url in _pool: return _pool[url]
        _log("pool-miss", url=url, engine=_ENGINE)
        eng = _make_engine(url)
        _pool[url] = eng
        return eng


async def shutdown_pool():
    async with _pool_lock:
        items = list(_pool.values())
        _pool.clear()
    for e in items:
        try: await e.shutdown()
        except Exception as ex: print(f"[WARN] engine shutdown failed: {ex}", flush=True)


# ---- DB ----

class DB:
    def __init__(self, source, base=None):
        if isinstance(source, str):
            self._url = source if base is None else f"{base.rstrip('/')}/{source}"
        else:
            self._url = f"{(base or source.base).rstrip('/')}/{source.path}"
        self._buffer = None

    async def get(self, key, default=None):
        if self._buffer is not None and key in self._buffer:
            v = self._buffer[key]
            return default if v is _DELETED else v
        eng = await _get_engine(self._url)
        v = await eng.get(key)
        return v if v is not None else default

    async def put(self, key, value, *, durable=False):
        if self._buffer is not None:
            self._buffer[key] = value
            return
        eng = await _get_engine(self._url)
        await eng.put(key, value)

    async def delete(self, key, *, durable=False):
        if self._buffer is not None:
            self._buffer[key] = _DELETED
            return
        eng = await _get_engine(self._url)
        await eng.delete(key)

    async def items(self, prefix=None):
        eng = await _get_engine(self._url)
        disk = await eng.scan(prefix or "")
        if self._buffer is None:
            for k, v in disk: yield k, v
            return
        merged = {}
        for k, v in disk:
            if k in self._buffer:
                bv = self._buffer[k]
                if bv is _DELETED: continue
                merged[k] = bv
            else:
                merged[k] = v
        for k, v in self._buffer.items():
            if v is _DELETED: continue
            if (prefix or "") == "" or k.startswith(prefix):
                merged[k] = v
        for k in sorted(merged.keys()):
            yield k, merged[k]

    @asynccontextmanager
    async def transaction(self):
        if self._buffer is not None:
            raise RuntimeError("nested transactions not supported")
        self._buffer = {}
        try:
            yield self
        except Exception:
            self._buffer = None
            raise
        else:
            buf = self._buffer
            self._buffer = None
            eng = await _get_engine(self._url)
            await eng.commit(buf)

    @asynccontextmanager
    async def raw(self):
        eng = await _get_engine(self._url)
        yield eng

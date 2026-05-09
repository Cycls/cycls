"""Workspace — per-tenant `(root, path, base)` + JSON KV over SlateDB.

The auth ↔ workspace contract: `workspace_for(user, ...)` reads `user.id` and
optionally `user.org_id`, the only `User` fields workspace logic depends on.

`DB` runs JSON KV at `<base>/<path>`. Flat byte-keyed under the hood;
namespacing (if any) is just a prefix in the caller's key. Every op is a
SlateDB transaction (single ops are 1-op txns committed non-durable);
`db.transaction()` shares one txn across many ops; `db.raw()` is the bytes
escape hatch.
"""
import asyncio, json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from slatedb.uniffi import (
    DbBuilder, IsolationLevel, ObjectStore, WriteOptions,
    Error, CloseReason,
)


# ---- Tenant shape ----

@dataclass(frozen=True)
class Workspace:
    root: Path
    path: str
    subject: str
    base: Optional[str] = None


def workspace_for(user, volume, base=None) -> Workspace:
    """User → Workspace. Subject uses `:` as the org/user separator so it's
    URL-path-safe (FastAPI path params reject `/`)."""
    if user is None:
        sub = "local"
    elif getattr(user, "org_id", None):
        sub = f"{user.org_id}:{user.id}"
    else:
        sub = user.id
    return workspace_at(sub, volume, base)


def workspace_at(tenant, volume, base=None, slot=".db") -> Workspace:
    """Tenant → Workspace at a given storage slot. `slot` names the DB tree
    under the tenant's root; default `.db` is the framework chat DB. Callers
    pick other slots for sibling DB trees (e.g. agent-tool storage)."""
    volume = Path(volume)
    if ":" in tenant:
        org, user = tenant.split(":", 1)
        return Workspace(root=volume / org, path=f"{org}/{slot}/{user}", subject=tenant, base=base)
    return Workspace(root=volume / tenant, path=f"{tenant}/{slot}", subject=tenant, base=base)


# ---- KV storage ----

_pool: dict = {}
_pool_lock = asyncio.Lock()
_NON_DURABLE = WriteOptions(await_durable=False)
_DURABLE     = WriteOptions(await_durable=True)


async def _safe_shutdown(db):
    try: await db.shutdown()
    except Exception as e: print(f"[WARN] db shutdown failed: {e}", flush=True)


async def shutdown_pool():
    async with _pool_lock:
        items = list(_pool.values())
        _pool.clear()
    for db in items: await _safe_shutdown(db)


async def _build_db(url):
    if url.startswith("file://"):
        Path(url[7:]).mkdir(parents=True, exist_ok=True)
    return await DbBuilder("db", ObjectStore.resolve(url)).build()


async def _get_pooled(url):
    """Open-once cache. Builds happen outside the lock so different urls
    can build in parallel; same-url racers discard the loser's handle."""
    if url in _pool: return _pool[url]
    db = await _build_db(url)
    async with _pool_lock:
        if url in _pool:
            asyncio.create_task(_safe_shutdown(db))
            return _pool[url]
        _pool[url] = db
        return db


def _fence_retry(method):
    """Retry once on SlateDB writer fence (a newer Cloud Run instance took
    over the writer role). Pool entry is evicted before retry — reopening
    makes us the active writer again. items()/transaction() opt out: scan
    iteration and user-managed txns can't be safely re-run from the middle."""
    async def wrapped(self, *args, **kwargs):
        for attempt in range(2):
            try: return await method(self, *args, **kwargs)
            except Error.Closed as e:
                if attempt == 0 and self._txn is None and e.reason == CloseReason.FENCED:
                    async with _pool_lock: _pool.pop(self._url, None)
                    continue
                raise
    return wrapped


class DB:
    def __init__(self, source, base=None):
        if isinstance(source, str):
            self._url = source if base is None else f"{base.rstrip('/')}/{source}"
            self._txn = None
        elif hasattr(source, "path"):
            self._url = f"{(base or source.base).rstrip('/')}/{source.path}"
            self._txn = None
        else:
            self._url = None
            self._txn = source

    @asynccontextmanager
    async def _handle(self, durable=False):
        if self._txn is not None:
            yield self._txn
            return
        slate = await _get_pooled(self._url)
        txn = await slate.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try: yield txn
        except Exception: await txn.rollback(); raise
        else: await txn.commit_with_options(_DURABLE if durable else _NON_DURABLE)

    @_fence_retry
    async def get(self, key, default=None):
        async with self._handle() as t:
            v = await t.get(key.encode())
            return json.loads(v) if v is not None else default

    @_fence_retry
    async def put(self, key, value, *, durable=False):
        async with self._handle(durable=durable) as t:
            await t.put(key.encode(), json.dumps(value).encode())

    @_fence_retry
    async def delete(self, key, *, durable=False):
        async with self._handle(durable=durable) as t:
            await t.delete(key.encode())

    async def items(self, prefix=None):
        async with self._handle() as t:
            it = await t.scan_prefix((prefix or "").encode())
            while (kv := await it.next()) is not None:
                yield kv.key.decode(), json.loads(kv.value)

    @asynccontextmanager
    async def transaction(self):
        if self._txn is not None:
            raise RuntimeError("nested transactions not supported")
        slate = await _get_pooled(self._url)
        txn = await slate.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try: yield DB(txn)
        except Exception: await txn.rollback(); raise
        else: await txn.commit_with_options(_NON_DURABLE)

    @asynccontextmanager
    async def raw(self):
        if self._url is None:
            raise RuntimeError("raw() not available inside a transaction")
        yield await _get_pooled(self._url)

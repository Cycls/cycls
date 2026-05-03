"""Workspace — per-tenant `(root, path, base)` + JSON KV over SlateDB.

The auth ↔ workspace contract: `subject_for(user)` reads `user.id` and
optionally `user.org_id`, the only `User` fields workspace logic depends on.

`DB` runs JSON KV at `<base>/<path>`. Flat byte-keyed under the hood;
namespacing (if any) is just a prefix in the caller's key. Every op is a
SlateDB transaction (single ops are 1-op txns committed non-durable);
`db.transaction()` shares one txn across many ops; `db.raw()` is the bytes
escape hatch.
"""
import asyncio, json
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from slatedb.uniffi import (
    DbBuilder, IsolationLevel, ObjectStore, WriteOptions,
)


# ---- Tenant shape ----

@dataclass(frozen=True)
class Workspace:
    root: Path
    path: str
    base: Optional[str] = None


def subject_for(user) -> str:
    return f"{user.org_id}/{user.id}" if getattr(user, "org_id", None) else user.id


def workspace_for(user, volume, base=None) -> Workspace:
    return workspace_at("local" if user is None else subject_for(user), volume, base)


def workspace_at(tenant, volume, base=None) -> Workspace:
    volume = Path(volume)
    if "/" in tenant:
        org, user = tenant.split("/", 1)
        return Workspace(root=volume / org, path=f"{org}/.db/{user}", base=base)
    return Workspace(root=volume / tenant, path=f"{tenant}/.db", base=base)


# ---- KV storage ----

_pool: "OrderedDict[str, object]" = OrderedDict()
_pool_lock = asyncio.Lock()
MAX_POOL_SIZE = 100
_NON_DURABLE = WriteOptions(await_durable=False)


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
    """LRU + double-check lock: concurrent misses on the same url may build
    twice; loser discards. Cheaper than serializing all opens."""
    cached = _pool.get(url)
    if cached is not None:
        _pool.move_to_end(url)
        return cached
    db = await _build_db(url)
    discard = None
    async with _pool_lock:
        if url in _pool:
            _pool.move_to_end(url)
            discard, db = db, _pool[url]
        else:
            _pool[url] = db
            if len(_pool) > MAX_POOL_SIZE:
                discard = _pool.popitem(last=False)[1]
    if discard is not None: await _safe_shutdown(discard)
    return db


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
    async def _handle(self):
        if self._txn is not None:
            yield self._txn
            return
        slate = await _get_pooled(self._url)
        txn = await slate.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try: yield txn
        except Exception: await txn.rollback(); raise
        else: await txn.commit_with_options(_NON_DURABLE)

    async def get(self, key, default=None):
        async with self._handle() as t:
            v = await t.get(key.encode())
            return json.loads(v) if v is not None else default

    async def put(self, key, value):
        async with self._handle() as t:
            await t.put(key.encode(), json.dumps(value).encode())

    async def delete(self, key):
        async with self._handle() as t:
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

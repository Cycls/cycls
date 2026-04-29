"""DB — namespaced JSON KV over SlateDB at `<base>/<path>`.

Every op runs inside a SlateDB transaction. Single ops open a 1-op txn
and commit (non-durable) on the way out; multi-op atomic blocks via
`kv.transaction()` join one shared txn. One mechanism, atomicity by
default.
"""
import asyncio, json
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from slatedb.uniffi import (
    DbBuilder, IsolationLevel, ObjectStore, WriteOptions,
)

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
            path = source
        else:
            path = source.path
            base = base or source.base
        self._url = f"{base.rstrip('/')}/{path}"

    def kv(self, name: str) -> "KV":
        return KV(name, self._url)

    @asynccontextmanager
    async def raw(self):
        yield await _get_pooled(self._url)


def _enc(name, key):
    return f"{name}/{key}".encode()


class KV:
    def __init__(self, name, source):
        self._name = name
        self._source = source  # url string OR a live Transaction

    @asynccontextmanager
    async def _txn(self):
        if not isinstance(self._source, str):
            yield self._source
            return
        db = await _get_pooled(self._source)
        txn = await db.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try: yield txn
        except Exception: await txn.rollback(); raise
        else: await txn.commit_with_options(_NON_DURABLE)

    async def get(self, key, default=None):
        async with self._txn() as t:
            v = await t.get(_enc(self._name, key))
            return json.loads(v) if v is not None else default

    async def put(self, key, value):
        async with self._txn() as t:
            await t.put(_enc(self._name, key), json.dumps(value).encode())

    async def delete(self, key):
        async with self._txn() as t:
            await t.delete(_enc(self._name, key))

    async def items(self, prefix=None):
        async with self._txn() as t:
            it = await t.scan_prefix(_enc(self._name, prefix or ""))
            strip = len(self._name) + 1
            while (kv := await it.next()) is not None:
                yield kv.key.decode()[strip:], json.loads(kv.value)

    @asynccontextmanager
    async def transaction(self):
        if not isinstance(self._source, str):
            raise RuntimeError("nested transactions not supported")
        db = await _get_pooled(self._source)
        txn = await db.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try: yield KV(self._name, txn)
        except Exception: await txn.rollback(); raise
        else: await txn.commit_with_options(_NON_DURABLE)

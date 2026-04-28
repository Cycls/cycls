import asyncio, json
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from slatedb.uniffi import (
    DbBuilder, IsolationLevel, ObjectStore,
    PutOptions, Ttl, WriteOptions,
)

_pool: "OrderedDict[str, object]" = OrderedDict()
_pool_lock = asyncio.Lock()
MAX_POOL_SIZE = 100


async def shutdown_pool():
    """Shut down every pooled Db. Use in test teardown or process exit."""
    async with _pool_lock:
        items = list(_pool.items())
        _pool.clear()
    for _, db in items:
        try:
            await db.shutdown()
        except Exception as e:
            print(f"[WARN] db shutdown failed: {e}", flush=True)


class Workspace:
    def __init__(self, root, user_id=None, bucket=None):
        self.root = Path(root)
        self.data = self.root / ".cycls" / user_id if user_id else self.root / ".cycls"
        self._bucket = bucket

    def url(self) -> str:
        if self._bucket:
            rel = self.data.relative_to(self.root.parent)
            return f"{self._bucket.rstrip('/')}/{rel}"
        return f"file://{self.data}"


def workspace_for(user, volume, bucket=None):
    """Build a Workspace for *user* under *volume*. None → /local; org member →
    /<org>/.cycls/<user>; personal → /<user>/.cycls. Duck-types on the user
    object (`.id`, `.org_id`) so any auth model with those attributes works."""
    if user is None:
        return Workspace(volume / "local", bucket=bucket)
    if getattr(user, "org_id", None):
        return Workspace(volume / user.org_id, user_id=user.id, bucket=bucket)
    return Workspace(volume / user.id, bucket=bucket)


def subject_for(user) -> str:
    """The path-safe identifier for *user*'s workspace tenancy. `user_id` for
    personal users, `org_id/user_id` for org members. Used as the bound subject
    of signed URLs — the inverse is `workspace_for_subject`. *user* must be
    authenticated; signed URLs aren't minted for anonymous callers."""
    if getattr(user, "org_id", None):
        return f"{user.org_id}/{user.id}"
    return user.id


def workspace_for_subject(subject, volume, bucket=None):
    """Inverse of `subject_for` — rebuild a Workspace from a signed-URL subject."""
    if "/" in subject:
        org_id, user_id = subject.split("/", 1)
        return Workspace(volume / org_id, user_id=user_id, bucket=bucket)
    return Workspace(volume / subject, bucket=bucket)


async def _build_db(url):
    if url.startswith("file://"):
        Path(url[7:]).mkdir(parents=True, exist_ok=True)
    return await DbBuilder("db", ObjectStore.resolve(url)).build()


async def _get_pooled(url):
    """Pool lookup with LRU. Concurrent misses for the same url may build
    twice — the loser discards. Cheaper than serializing all opens."""
    cached = _pool.get(url)
    if cached is not None:
        _pool.move_to_end(url)
        return cached

    db = await _build_db(url)
    to_shutdown = []
    async with _pool_lock:
        existing = _pool.get(url)
        if existing is not None:
            _pool.move_to_end(url)
            to_shutdown.append(db)
            db = existing
        else:
            _pool[url] = db
            if len(_pool) > MAX_POOL_SIZE:
                _, old = _pool.popitem(last=False)
                to_shutdown.append(old)
    for old in to_shutdown:
        try: await old.shutdown()
        except Exception as e: print(f"[WARN] db shutdown failed: {e}", flush=True)
    return db


class DB:
    """Per-workspace database. `db.kv(name)` for namespaced JSON;
    `async with db.raw() as slate:` for the raw SlateDB handle."""

    def __init__(self, workspace):
        self._workspace = workspace

    def kv(self, name: str) -> "KV":
        return KV(name, self._workspace)

    @asynccontextmanager
    async def raw(self):
        yield await _get_pooled(self._workspace.url())


def _enc(name, key):
    return f"{name}/{key}".encode()


class _BaseKV:
    """Shared get/put/delete/items. Subclasses provide `_handle()` — an async
    context manager yielding a Db or DbTransaction."""

    def __init__(self, name):
        self._name = name

    async def get(self, key, default=None):
        async with self._handle() as h:
            v = await h.get(_enc(self._name, key))
            return json.loads(v) if v is not None else default

    async def put(self, key, value):
        async with self._handle() as h:
            await h.put(_enc(self._name, key), json.dumps(value).encode())

    async def delete(self, key):
        async with self._handle() as h:
            await h.delete(_enc(self._name, key))

    async def items(self, prefix=None):
        async with self._handle() as h:
            it = await h.scan_prefix(_enc(self._name, prefix or ""))
            strip = len(self._name) + 1
            while (kv := await it.next()) is not None:
                yield kv.key.decode()[strip:], json.loads(kv.value)


class KV(_BaseKV):
    def __init__(self, name, workspace):
        super().__init__(name)
        self._workspace = workspace

    @asynccontextmanager
    async def _handle(self):
        yield await _get_pooled(self._workspace.url())

    async def put(self, key, value):
        """Non-durable put — WAL fsync deferred. ~100ms/op savings; small
        risk of losing the write on crash before next flush. Acceptable for
        chat persist, usage counters, share registry."""
        async with self._handle() as h:
            await h.put_with_options(
                _enc(self._name, key),
                json.dumps(value).encode(),
                PutOptions(ttl=Ttl.DEFAULT()),
                WriteOptions(await_durable=False),
            )

    async def delete(self, key):
        async with self._handle() as h:
            await h.delete_with_options(_enc(self._name, key), WriteOptions(await_durable=False))

    @asynccontextmanager
    async def transaction(self):
        """Atomic multi-op transaction (serializable snapshot isolation).
        Commits on clean exit; rolls back on exception. Non-durable commit."""
        db = await _get_pooled(self._workspace.url())
        txn = await db.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try:
            yield _TxKV(self._name, txn)
        except Exception:
            await txn.rollback()
            raise
        else:
            await txn.commit_with_options(WriteOptions(await_durable=False))


class _TxKV(_BaseKV):
    """Transactional view of a KV — same interface, atomic on commit."""

    def __init__(self, name, txn):
        super().__init__(name)
        self._txn = txn

    @asynccontextmanager
    async def _handle(self):
        yield self._txn

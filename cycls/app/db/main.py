"""cycls.db — Workspace + KV.

By default, SlateDB is opened per-operation and shut down on exit. Open is
cheap (one manifest fetch + WAL replay), and the per-op lifecycle keeps
memory flat across tenants, sidesteps stale-handle issues across multi-pod
deploys, and removes pooling entirely.

For a single HTTP request (or any other unit of work), wrap the work in
`request_scope()`: while inside, `_open(url)` returns a Db cached for the
scope. All KV ops in the scope share one open. On scope exit, every Db
opened inside is shut down. Outside any scope, behavior is unchanged.

Substrate selection lives in `Workspace`: pass `bucket="gs://cycls-ws-foo"`
for prod; omit for local `file://`. The container's runtime credentials are
expected to grant access to the bucket — no auth config flows through here.

Set CYCLS_PROFILE=1 to print per-op open/op/shutdown timings to stdout.
The env var is read lazily so user code can flip it on at runtime.
"""
import json, os, time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

_scope: ContextVar = ContextVar("_scope", default=None)


@asynccontextmanager
async def request_scope():
    """Inside this scope, `_open(url)` reuses one Db per URL. All opened
    Dbs are shut down on exit."""
    dbs: dict = {}
    token = _scope.set(dbs)
    try:
        yield
    finally:
        _scope.reset(token)
        for db in dbs.values():
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


async def _build_db(url):
    from slatedb.uniffi import ObjectStore, DbBuilder
    if url.startswith("file://"):
        Path(url[7:]).mkdir(parents=True, exist_ok=True)
    store = ObjectStore.resolve(url)
    return await DbBuilder("db", store).build()


@asynccontextmanager
async def _open(url):
    """Yield a SlateDB at *url*. Inside `request_scope`, the Db is built
    once per URL and reused; the scope owns shutdown. Outside, build and
    shutdown each call."""
    profile = os.environ.get("CYCLS_PROFILE")
    dbs = _scope.get()

    if dbs is not None and url in dbs:
        t0 = time.perf_counter()
        try:
            yield dbs[url]
        finally:
            if profile:
                print(f"[profile] db url={url[-48:]} open=0ms op={(time.perf_counter()-t0)*1000:.0f}ms shutdown=0ms", flush=True)
        return

    t0 = time.perf_counter()
    db = await _build_db(url)
    t_open = time.perf_counter() - t0
    if dbs is not None:
        dbs[url] = db
    try:
        yield db
    finally:
        t1 = time.perf_counter()
        if dbs is None:
            await db.shutdown()
        if profile:
            t_shutdown = time.perf_counter() - t1
            t_op = t1 - t0 - t_open
            tag = "deferred" if dbs is not None else f"{t_shutdown*1000:.0f}ms"
            print(f"[profile] db url={url[-48:]} open={t_open*1000:.0f}ms op={t_op*1000:.0f}ms shutdown={tag}", flush=True)


def _enc(name, key):
    return f"{name}/{key}".encode()


class _BaseKV:
    """Shared get/put/delete/items implementation. Subclasses provide the
    underlying handle (Db or DbTransaction) via async ctx `_handle()`."""

    def __init__(self, name):
        self._name = name

    @asynccontextmanager
    async def _handle(self):
        raise NotImplementedError
        yield  # pragma: no cover — make it a generator

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
        async with _open(self._workspace.url()) as db:
            yield db

    async def put(self, key, value):
        """Non-durable put: WAL fsync is deferred. Trades sync-on-write
        durability (~100ms/op) for a small risk of losing the write on
        process crash before the next flush. Acceptable for chat persist,
        usage counters, share registry — all at-most-once-anyway domains."""
        from slatedb.uniffi import PutOptions, WriteOptions, Ttl
        async with self._handle() as h:
            await h.put_with_options(
                _enc(self._name, key),
                json.dumps(value).encode(),
                PutOptions(ttl=Ttl.DEFAULT()),
                WriteOptions(await_durable=False),
            )

    async def delete(self, key):
        from slatedb.uniffi import WriteOptions
        async with self._handle() as h:
            await h.delete_with_options(_enc(self._name, key), WriteOptions(await_durable=False))

    @asynccontextmanager
    async def transaction(self):
        """Atomic multi-op transaction with serializable snapshot isolation.

            async with kv.transaction() as t:
                await t.delete("a")
                await t.put("b", {...})

        Commit happens at clean exit; rollback on exception. Opens the DB
        once for the lifetime of the block. Commit is non-durable (see
        `KV.put` rationale)."""
        from slatedb.uniffi import IsolationLevel, WriteOptions
        async with _open(self._workspace.url()) as db:
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

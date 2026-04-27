"""cycls.db — Workspace + KV.

SlateDB is opened per-operation and shut down on exit. Open is cheap (one
manifest fetch + WAL replay), and the per-op lifecycle keeps memory flat,
sidesteps stale-handle issues across multi-pod deploys, and removes the
pooling layer entirely. Batches that need fewer opens use `kv.transaction()`,
which opens once and commits once.

Substrate selection lives in `Workspace`: pass `bucket="gs://cycls-ws-foo"`
for prod; omit for local `file://`. The container's runtime credentials are
expected to grant access to the bucket — no auth config flows through here.
"""
import json
from contextlib import asynccontextmanager
from pathlib import Path


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


@asynccontextmanager
async def _open(url):
    """Open a SlateDB at *url* and shutdown on exit."""
    from slatedb.uniffi import ObjectStore, DbBuilder
    if url.startswith("file://"):
        Path(url[7:]).mkdir(parents=True, exist_ok=True)
    store = ObjectStore.resolve(url)
    db = await DbBuilder("db", store).build()
    try:
        yield db
    finally:
        await db.shutdown()


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

    @asynccontextmanager
    async def transaction(self):
        """Atomic multi-op transaction with serializable snapshot isolation.

            async with kv.transaction() as t:
                await t.delete("a")
                await t.put("b", {...})

        Commit happens at clean exit; rollback on exception. Opens the DB
        once for the lifetime of the block."""
        from slatedb.uniffi import IsolationLevel
        async with _open(self._workspace.url()) as db:
            txn = await db.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
            try:
                yield _TxKV(self._name, txn)
            except Exception:
                await txn.rollback()
                raise
            else:
                await txn.commit()


class _TxKV(_BaseKV):
    """Transactional view of a KV — same interface, atomic on commit."""

    def __init__(self, name, txn):
        super().__init__(name)
        self._txn = txn

    @asynccontextmanager
    async def _handle(self):
        yield self._txn

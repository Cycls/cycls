"""cycls.db — Workspace + KV.

SlateDB handles are pooled at the process level. Open is the expensive
operation on object storage (manifest fetch, TLS handshake, HTTP/2
warmup) — once paid, the Db handle is kept alive across requests and
reused. Bounded LRU eviction keeps memory in check.

Multi-container safety: SlateDB's manifest CAS handles concurrent writers
correctly (no corruption). Cross-pod write-write races on the *same*
workspace can lose the latest write within the manifest-poll window;
mitigate with LB session affinity so the same user lands on the same pod.

Substrate selection lives in `Workspace`: pass `bucket="gs://cycls-ws-foo"`
for prod; omit for local `file://`. The container's runtime credentials are
expected to grant access to the bucket — no auth config flows through here.
"""
import asyncio, json
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

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


async def _build_db(url):
    from slatedb.uniffi import ObjectStore, DbBuilder
    if url.startswith("file://"):
        Path(url[7:]).mkdir(parents=True, exist_ok=True)
    store = ObjectStore.resolve(url)
    return await DbBuilder("db", store).build()


async def _get_pooled(url):
    """Pool lookup with LRU semantics. Concurrent misses for the same url
    may build twice — the loser discards its Db. Acceptable: rare, and
    serializing all opens behind a lock would block independent workspaces."""
    cached = _pool.get(url)
    if cached is not None:
        _pool.move_to_end(url)
        return cached

    db = await _build_db(url)
    evict = None
    discard = None
    async with _pool_lock:
        existing = _pool.get(url)
        if existing is not None:
            _pool.move_to_end(url)
            discard = db
            db = existing
        else:
            _pool[url] = db
            if len(_pool) > MAX_POOL_SIZE:
                _, evict = _pool.popitem(last=False)
    if evict is not None:
        try: await evict.shutdown()
        except Exception as e: print(f"[WARN] db shutdown (evict) failed: {e}", flush=True)
    if discard is not None:
        try: await discard.shutdown()
        except Exception as e: print(f"[WARN] db shutdown (discard) failed: {e}", flush=True)
    return db


@asynccontextmanager
async def _open(url):
    """Borrow a pooled SlateDB for *url*. Open cost is paid only on cache
    miss; subsequent ops on the same workspace find the warm handle."""
    yield await _get_pooled(url)


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

"""cycls.db — Workspace + KV."""
import asyncio, json, os
from contextlib import asynccontextmanager
from pathlib import Path


def _fuse_bucket(mount_point):
    try:
        with open("/proc/mounts") as f:
            for line in f:
                src, mnt, fstype, *_ = line.split()
                if mnt == mount_point and "fuse" in fstype:
                    return src
    except OSError:
        pass
    return None


class Workspace:
    def __init__(self, root, user_id=None):
        self.root = Path(root)
        self.data = self.root / ".cycls" / user_id if user_id else self.root / ".cycls"

    def url(self) -> str:
        prefix = os.environ.get("CYCLS_STATE_URL")
        if not prefix:
            bucket = _fuse_bucket(str(self.root.parent))
            if bucket:
                prefix = f"gs://{bucket}"
        if not prefix:
            return f"file://{self.data}"
        rel = self.data.relative_to(self.root.parent)
        return f"{prefix.rstrip('/')}/{rel}"


_pool: dict[str, object] = {}
_pool_lock = asyncio.Lock()


async def _db(url):
    cached = _pool.get(url)
    if cached is not None:
        return cached
    async with _pool_lock:
        cached = _pool.get(url)
        if cached is not None:
            return cached
        from slatedb.uniffi import ObjectStore, DbBuilder
        if url.startswith("file://"):
            Path(url[7:]).mkdir(parents=True, exist_ok=True)
        store = ObjectStore.resolve(url)
        db = await DbBuilder("db", store).build()
        _pool[url] = db
        return db


class _BaseKV:
    """Shared get/put/delete/items implementation. Subclasses provide the
    underlying handle (Db or DbTransaction) via `_handle()`."""

    def __init__(self, name):
        self._name = name

    def _key(self, k):
        return f"{self._name}/{k}".encode()

    async def _handle(self):
        raise NotImplementedError

    async def get(self, key, default=None):
        h = await self._handle()
        v = await h.get(self._key(key))
        return json.loads(v) if v is not None else default

    async def put(self, key, value):
        h = await self._handle()
        await h.put(self._key(key), json.dumps(value).encode())

    async def delete(self, key):
        h = await self._handle()
        await h.delete(self._key(key))

    async def items(self, prefix=None):
        h = await self._handle()
        it = await h.scan_prefix(self._key(prefix or ""))
        strip = len(self._name) + 1
        while (kv := await it.next()) is not None:
            yield kv.key.decode()[strip:], json.loads(kv.value)


class KV(_BaseKV):
    def __init__(self, name, workspace):
        super().__init__(name)
        self._workspace = workspace

    async def _handle(self):
        return await _db(self._workspace.url())

    @asynccontextmanager
    async def transaction(self):
        """Atomic multi-op transaction with serializable snapshot isolation.

            async with kv.transaction() as t:
                await t.delete("a")
                await t.put("b", {...})

        Commit happens at clean exit; rollback on exception."""
        from slatedb.uniffi import IsolationLevel
        db = await self._handle()
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

    async def _handle(self):
        return self._txn

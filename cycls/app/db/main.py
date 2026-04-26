"""cycls.db — Workspace + KV."""
import asyncio, json, os
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


class KV:
    def __init__(self, name, workspace):
        self._name = name
        self._workspace = workspace

    async def _open(self):
        return await _db(self._workspace.url())

    def _key(self, k):
        return f"{self._name}/{k}".encode()

    async def get(self, key, default=None):
        db = await self._open()
        v = await db.get(self._key(key))
        return json.loads(v) if v is not None else default

    async def put(self, key, value):
        db = await self._open()
        await db.put(self._key(key), json.dumps(value).encode())

    async def delete(self, key):
        db = await self._open()
        await db.delete(self._key(key))

    async def items(self, prefix=None):
        db = await self._open()
        it = await db.scan_prefix(self._key(prefix or ""))
        strip = len(self._name) + 1
        while (kv := await it.next()) is not None:
            yield kv.key.decode()[strip:], json.loads(kv.value)

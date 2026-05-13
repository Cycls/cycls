"""Workspace — per-tenant `(root, path, base)` + JSON KV over SlateDB.

The auth ↔ workspace contract: `workspace_for(user, ...)` reads `user.id` and
optionally `user.org_id`, the only `User` fields workspace logic depends on.

`DB` runs JSON KV at `<base>/<path>`. Flat byte-keyed under the hood;
namespacing (if any) is just a prefix in the caller's key. Every op is a
SlateDB transaction (single ops are 1-op txns committed non-durable);
`db.transaction()` shares one txn across many ops; `db.raw()` is the bytes
escape hatch.
"""
import asyncio, json, os, uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from slatedb.uniffi import (
    DbBuilder, IsolationLevel, ObjectStore, WriteOptions,
    Error, CloseReason,
)


# ---- Debug instrumentation (fence-war forensics) ----

DEBUG = True  # flip True to dump every pool/begin/commit/fence event

_REV = os.environ.get("K_REVISION", "local")[-12:]
_PID = uuid.uuid4().hex[:6]
_INSTANCE = f"{_REV}/{_PID}"

def _log(op, **kv):
    if not DEBUG: return
    extras = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"[SLATE/{_INSTANCE}] {op} {extras}", flush=True)


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
_url_locks: dict = {}


async def _safe_shutdown(db):
    try: await db.shutdown()
    except Exception as e: print(f"[WARN] db shutdown failed: {e}", flush=True)


async def shutdown_pool():
    async with _pool_lock:
        items = list(_pool.values())
        _pool.clear()
    for db in items: await _safe_shutdown(db)


async def _build_db(url):
    _log("build-start", url=url)
    if url.startswith("file://"):
        Path(url[7:]).mkdir(parents=True, exist_ok=True)
    db = await DbBuilder("db", ObjectStore.resolve(url)).build()
    _log("build-done", url=url)
    return db


async def _get_pooled(url):
    if url in _pool:
        _log("pool-hit", url=url)
        return _pool[url]
    _log("pool-miss", url=url)
    lock = _url_locks.setdefault(url, asyncio.Lock())
    async with lock:
        if url in _pool:
            _log("pool-wait-resolved", url=url)
            return _pool[url]
        db = await _build_db(url)
        _pool[url] = db
        _log("pool-insert", url=url, size=len(_pool))
        return db


async def _evict_on_fence(url, e):
    """Pool eviction without retry — for paths that can't be safely re-run
    (scan iterators, user-managed transactions). One stuck-fenced handle in
    the pool poisons every subsequent request until eviction."""
    if e.reason == CloseReason.FENCED:
        async with _pool_lock:
            popped = _pool.pop(url, None)
        _log("fence-evict", url=url, had_entry=bool(popped), via="opt-out-path")


def _fence_retry(method):
    """Retry once on SlateDB writer fence (a newer Cloud Run instance took
    over the writer role). Pool entry is evicted before retry — reopening
    makes us the active writer again. items()/transaction() opt out: scan
    iteration and user-managed txns can't be safely re-run from the middle."""
    async def wrapped(self, *args, **kwargs):
        for attempt in range(2):
            try: return await method(self, *args, **kwargs)
            except Error.Closed as e:
                _log("closed", method=method.__name__, url=self._url, reason=str(e.reason), attempt=attempt)
                if attempt == 0 and self._txn is None and e.reason == CloseReason.FENCED:
                    async with _pool_lock:
                        popped = _pool.pop(self._url, None)
                    _log("fence-evict", url=self._url, had_entry=bool(popped))
                    continue
                _log("closed-giveup", method=method.__name__, url=self._url)
                raise
    return wrapped


class DB:
    def __init__(self, source, base=None):
        if isinstance(source, str):
            self._url = source if base is None else f"{base.rstrip('/')}/{source}"
        else:
            self._url = f"{(base or source.base).rstrip('/')}/{source.path}"
        self._txn = None

    @classmethod
    def _in_txn(cls, txn):
        self = cls.__new__(cls)
        self._url = None
        self._txn = txn
        return self

    @asynccontextmanager
    async def _handle(self, durable=False):
        if self._txn is not None:
            yield self._txn
            return
        slate = await _get_pooled(self._url)
        _log("begin", url=self._url, durable=durable)
        txn = await slate.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        try: yield txn
        except Exception:
            _log("rollback", url=self._url)
            await txn.rollback(); raise
        else:
            await txn.commit_with_options(WriteOptions(await_durable=durable))
            _log("commit", url=self._url, durable=durable)

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
        _log("scan-start", url=self._url, prefix=prefix)
        try:
            async with self._handle() as t:
                it = await t.scan_prefix((prefix or "").encode())
                while (kv := await it.next()) is not None:
                    yield kv.key.decode(), json.loads(kv.value)
        except Error.Closed as e:
            _log("scan-closed", url=self._url, reason=str(e.reason))
            await _evict_on_fence(self._url, e)
            raise

    @asynccontextmanager
    async def transaction(self):
        if self._txn is not None:
            raise RuntimeError("nested transactions not supported")
        slate = await _get_pooled(self._url)
        _log("txn-begin", url=self._url)
        try:
            txn = await slate.begin(IsolationLevel.SERIALIZABLE_SNAPSHOT)
        except Error.Closed as e:
            _log("txn-begin-closed", url=self._url, reason=str(e.reason))
            await _evict_on_fence(self._url, e)
            raise
        try: yield DB._in_txn(txn)
        except Exception as e:
            _log("txn-rollback", url=self._url)
            await txn.rollback()
            if isinstance(e, Error.Closed):
                await _evict_on_fence(self._url, e)
            raise
        else:
            try:
                await txn.commit_with_options(WriteOptions(await_durable=False))
                _log("txn-commit", url=self._url)
            except Error.Closed as e:
                _log("txn-commit-closed", url=self._url, reason=str(e.reason))
                await _evict_on_fence(self._url, e)
                raise

    @asynccontextmanager
    async def raw(self):
        if self._url is None:
            raise RuntimeError("raw() not available inside a transaction")
        yield await _get_pooled(self._url)

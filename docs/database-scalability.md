# Database scalability

How cycls's per-tenant SlateDB layer scales, what the ceilings are, what we ruled out, and when you'd need to graduate the architecture.

## Architecture

```
agent process (Cloud Run instance)
   │
   ├── tenant A: DB(workspace_A) ─────► SlateDB at gs://cycls-ws-<agent>/<tenant_A>/.db/
   ├── tenant B: DB(workspace_B) ─────► SlateDB at gs://cycls-ws-<agent>/<tenant_B>/.db/
   └── ...                              (LSM tree on object storage; one DB per tenant)
```

Each agent's data is partitioned **per tenant**: every Workspace gets its own SlateDB instance at a tenant-scoped GCS prefix. Inside a single tenant DB, keys are flat — namespacing is just a key prefix (`chat/log/<id>/<turn>`, `chat/meta/<id>`, `share/<token>`).

`cycls/app/workspace.py` owns the layer: `Workspace` (root + path + base), `DB` (the KV API), and `_pool` (SlateDB handle cache).

## The pool

### Why it exists

A cold `DbBuilder("db", ObjectStore.resolve(url)).build()` takes **~4 seconds** — it has to read the manifest from GCS, materialize LSM state in memory, and start background compaction tasks. Doing that per-request per-tenant would be unusable.

The pool keeps SlateDB handles alive for the process's lifetime, keyed by URL. First request for a tenant pays the 4s cold open; every subsequent request is hot.

### Shape

```python
_pool: dict = {}          # url → Db handle
_pool_lock = asyncio.Lock()

async def _get_pooled(url):
    if url in _pool: return _pool[url]
    db = await _build_db(url)              # ← outside the lock
    async with _pool_lock:
        if url in _pool:                   # lost the race
            asyncio.create_task(_safe_shutdown(db))
            return _pool[url]
        _pool[url] = db
        return db
```

Builds happen **outside the lock** so concurrent first-opens for *different* tenants build in parallel. Same-URL racers (rare) discard the loser's handle. There is **no LRU eviction** — the pool grows monotonically over the instance's lifetime. See "Scale ceilings" for when that becomes a problem.

## Single-writer constraint

**SlateDB enforces single-writer via epoch fencing.** This is per the docs: *"SlateDB only needs to support one writer process at a time, and SlateDB should enforce this property. Applications that need multiple writers should use multiple SlateDB databases as partitions."*

When a second writer opens the same DB, it bumps the manifest epoch. The original writer becomes a "zombie" — its next operation raises `Error.Closed` with `reason=CloseReason.FENCED`.

### What this means for Cloud Run autoscaling

Cloud Run can run multiple instances of the same service. Without affinity, requests for the same tenant can land on different instances:

```
Instance A: opens tenant Alice's DB → becomes writer @ epoch N
Instance B: opens tenant Alice's DB → becomes writer @ epoch N+1, A is fenced
A: next request → Error.Closed/FENCED on the pooled handle
```

### Fence retry (what we ship)

`@_fence_retry` wraps `get`/`put`/`delete`. On `Error.Closed` with `FENCED`, evict the pool entry, reopen (we become the active writer again, fencing whoever fenced us), retry once. `items()` and `transaction()` opt out — scan iteration and user-managed txns can't be safely re-run from the middle.

Recovery is **not free**: each fence cycle is a 4s SlateDB reopen. Under sustained multi-instance same-tenant traffic, instances livelock fencing each other (~4s per cycle each direction). Below ~5 RPS for one tenant cross-instance, this is fine. Above that, performance collapses.

`tests/app/workspace_test.py::test_db_recovers_from_writer_fence` is the live regression catcher.

## Durability

```python
_NON_DURABLE = WriteOptions(await_durable=False)   # default
_DURABLE     = WriteOptions(await_durable=True)    # opt-in
```

By default, commits return as soon as the write is enqueued — they don't wait for SlateDB to flush WAL to GCS. Saves ~10-50ms per write. **The cost**: if the writer is fenced or crashes between enqueue and flush, the write is lost.

| Write | Default | Why |
|---|---|---|
| `chat/log/{id}/{turn}` (messages) | non-durable | Losing one message = annoying, recoverable; the user re-asks |
| `chat/meta/{id}` (chat title etc.) | non-durable | Cosmetic |
| `share/{token}` (mint) | **durable** | A lost share token = silent UX failure. Link 404s forever, user thinks it worked. |
| `share/{token}` (revoke) | **durable** | A lost revoke = stale share stays live (mild security issue) |

API: `db.put(key, value, durable=True)` — same shape for `delete`. Keep the default for hot paths; opt in where data loss has user-visible cost.

## Scale ceilings

Per agent deployment, single Cloud Run instance (we're locked here by the single-writer constraint — see "What we ruled out" below):

| Cloud Run size | Active users (mid-LLM-call) | Connected, mostly idle | Active tenants in pool |
|---|---|---|---|
| 1GB / 1 vCPU | ~15-25 | ~100-200 | ~10-20 |
| 2GB / 2 vCPU | ~30-50 | ~200-400 | ~25-40 |
| 4GB / 2 vCPU | ~60-100 | ~400-800 | ~50-80 |
| 8GB / 4 vCPU | ~150-300 | ~1500+ | ~150 |

Math: ~50MB per pooled SlateDB handle, ~20-30MB per active request, ~500MB Python+FastAPI+slatedb baseline.

### What hits first (in order)

1. **LLM provider rate limits** (Anthropic/OpenAI per-minute token quotas) — usually the binding constraint in practice, before any infra ceiling
2. **Pool memory** — the unbounded pool OOMs at ~50 active tenants on 2GB
3. **Per-tenant write throughput** — single-writer caps a single tenant at ~10-30 writes/sec. Chat workloads sit far under this.
4. **GCS request rate** — 5000 ops/sec per bucket prefix; per-tenant prefixes keep us safely under

Translating to users: a 50-concurrent-active-user instance comfortably serves **thousands of DAU** assuming ~5min/day active engagement. The architecture has plenty of headroom for typical cycls deployments.

## What we ruled out

| Approach | Why not |
|---|---|
| Multi-writer SlateDB | Not supported. Fencing is enforced; livelock under sustained cross-instance traffic. |
| Tenant→instance routing affinity | Needs an L7 router that hashes tenant ID. Significant infra; defeats Cloud Run's auto-scaling simplicity. |
| `max_instances=1` on the cycls service | Limits scaling. Acceptable as a stopgap but caps growth. |
| Restoring LRU eviction at the pool | Doesn't help — the active set is what's in use; eviction would just thrash. Better fix is per-tenant deploys when pool size becomes a real problem. |

## When you graduate

When **one agent's user base** approaches ~200 concurrent active users on max Cloud Run sizing (or the pool consistently OOMs an 8GB instance), single-instance has been outgrown. The architectural answer is **per-tenant Cloud Run services**:

- Each tenant gets their own Cloud Run service deployment
- Each service runs `max_instances=N` (autoscales within a tenant)
- Different tenants are different services → no shared SlateDB → no fence ping-pong, no shared pool
- Cycls platform-level autoscaling stays alive (more tenants → more services)

This also solves the [metadata-bypass cross-tenant breach](sandbox-security.md) at the same time — a stolen SA only reaches one tenant's data because the SA is scoped to one tenant's project/bucket.

Per-tenant deploys is **weeks of cycls control-plane work** (provisioning, routing, lifecycle). Not preemptive — wait until measurement shows you need it.

## Migration

See [migration-rfc002-kv.md](migration-rfc002-kv.md) for the JSONL-on-FUSE → SlateDB cutover script and runbook.

## Testing

`tests/app/workspace_test.py`:

- Live SlateDB at `tmp_path` for every test; the `_isolate_db_pool` autouse fixture in `tests/conftest.py` calls `shutdown_pool()` between tests so handles don't carry over.
- URL composition tests (personal vs org tenant)
- DB API tests (get/put/delete/items/transaction)
- `test_db_recovers_from_writer_fence` — the multi-writer regression catcher described above

When touching the workspace layer, run the suite and verify the pool/fence/durability invariants hold.

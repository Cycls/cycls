# cycls.db

The data layer. One primitive (`cycls.KV`) backed by SlateDB, scoped per tenant via `Workspace`.

## Substrate selection

`Workspace.url()` decides where SlateDB writes, in this order:

1. `CYCLS_STATE_URL` env var — explicit override, e.g. `gs://other-bucket`
2. gcsfuse mount auto-detected from `/proc/mounts` — same bucket the deploy attached for FUSE, talked to **directly via SlateDB** (bypasses FUSE for state, gets native conditional writes for writer fencing)
3. `file://{workspace.data}` — local dev / no FUSE

Cross-cloud portable: same shape works against S3 + Mountpoint or Azure Blob + BlobFuse2.

## On-disk layout

```
{workspace.data}/                          # i.e. .cycls/ (personal) or .cycls/{user_id}/ (org member)
└── db/
    ├── manifest/
    │   └── 00000000000000000NNN.manifest
    ├── wal/
    │   └── 00000000000000000NNN.sst
    ├── compacted/
    └── compactions/
```

The `db/` subfolder is `DbBuilder("db", store)` — leaves room for siblings (logs, lock files, future framework state) under `.cycls/{whatever}/` without colliding.

## KV — the primitive

```python
kv = cycls.KV("name", workspace)
await kv.put("key", {"any": "json"})
v = await kv.get("key", default=None)
await kv.delete("key")
async for k, v in kv.items(prefix=None):
    ...
```

One SlateDB instance per workspace; multiple KVs (`KV("chats")`, `KV("usage")`, ...) share the underlying handle, namespaced by `{name}/` key prefix. Pool keyed by `workspace.url()` in `cycls/app/db/main.py:_pool`.

## Lifecycle

- **Process-wide**, lazy on first touch. Module-level `_pool` dict; opened once per tenant URL, lives until the Python process dies.
- **No per-request init.** Subsequent `KV(...)` calls for the same tenant reuse the cached handle.
- **First-hit cold-start**: ~1–2ms in dev (file://), few hundred ms in prod (manifest fetch over GCS).

## Memory profile (measured)

Linux container, slatedb 0.12.1, defaults, file:// backend. The actual cost model:

| Component | Cost |
|---|---|
| slatedb library import | ~5 MB fixed |
| First DB opened (Tokio runtime, schedulers) | ~7 MB fixed |
| Each *additional* DB (idle) | **~0.1–0.2 MB** marginal |
| Active write data | proportional to in-memtable bytes |

Raw measurements:

```
baseline (Python only):          22.6 MB
after slatedb import:            27.0 MB   (+4.4 — runtime + lib)
1st DB opened:                   34.4 MB   (+7.4 — infra)
5 DBs:                           35.1 MB   (+0.7  for 4 more  = ~0.18 MB/db marginal)
10 DBs:                          35.6 MB   (+0.5  for 5 more  = ~0.10 MB/db marginal)
25 DBs:                          36.9 MB   (+1.3  for 15 more = ~0.09 MB/db marginal)
50 DBs:                          52.0 MB   (~0.17 MB/db avg)
50 DBs + 10×1KB puts each:       52.5 MB
50 DBs + 50×8KB puts each:       71.6 MB   (~20 MB of data sitting in memtables)
```

**SlateDB shares its Tokio runtime across instances** — incremental DBs are nearly free. There is no memory wall at any reasonable per-pod tenant count.

## Scaling implications

| Active tenants/pod | Approx RAM overhead |
|---|---|
| 10 | ~10 MB above first-DB cost |
| 50 | ~10 MB |
| 500 | ~85 MB |
| 5000 | ~850 MB |

LRU eviction on the pool was once planned as a scale knob — measurement says it's basically unnecessary. The thing that scales linearly is in-memtable data, which would exist on any storage substrate.

## Operations

### Verify the integration

Drop into the deployed container's shell:

```bash
uv run python - <<'EOF'
import asyncio
from cycls.db import KV, Workspace

async def check():
    ws = Workspace("/workspace/_smoketest")
    print(f"substrate: {ws.url()}")
    kv = KV("smoketest", ws)
    await kv.put("ping", {"hello": "world"})
    assert await kv.get("ping") == {"hello": "world"}
    for i in range(3): await kv.put(f"scan/{i}", {"i": i})
    rows = [(k, v) async for k, v in kv.items(prefix="scan/")]
    assert [r[1]["i"] for r in rows] == [0, 1, 2]
    await kv.delete("ping")
    for k, _ in rows: await kv.delete(k)
    print("KV healthy")

asyncio.run(check())
EOF
```

Expected:
- Dev: `substrate: file://...` → write/read in ~ms
- Prod: `substrate: gs://{bucket}/...` → first put ~150–400 ms (real GCS), subsequent ms

### Bypass the FUSE auto-detect

Set `CYCLS_STATE_URL=gs://separate-bucket` in the deploy environment to point state at a different bucket from user files. Useful if you want hard separation (state bucket has different IAM, retention, region than user-files bucket).

## What's still file-based

| Concern | Why |
|---|---|
| User files (the agent's bwrap surface) | POSIX needed for bash/editor; FUSE/object-storage-as-filesystem is the right shape |
| Chat log JSONL | Hot path, current shape isn't biting; KV migration is mechanical (~30–50 LOC) when needed |
| Shares (pointer + dir + assets) | Cross-tenant public read is its own design concern; deferred |

See [rfc-002-data-primitives.md](rfc-002-data-primitives.md) for the design and forward-compat audit.

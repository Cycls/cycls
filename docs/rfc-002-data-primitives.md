# RFC 002: Data Primitives

**Status**: Draft — depends on RFC 001 landing
**Target**: After `cycls 1.0`
**Scope**: `cycls.Volume` as a first-class named primitive, backed by gfuse-mounted cloud buckets

---

## Summary

Introduce `cycls.Volume("name")` as a fourth primitive sibling to `Image`/`Web`/`LLM`. Volumes are named, lifecycle-independent cloud buckets that multiple apps can mount. Modal-style ergonomics, gfuse under the hood. `Dict`, `Queue`, and `Secret` follow as higher-level primitives built on the same foundation — deferred to a later RFC.

## Decisions locked

- `cycls.Volume("name")` is a named resource, independent of any app's lifecycle
- Volumes mount into apps via `@cycls.agent(..., volumes={"/path": vol, ...})`
- Multiple apps can mount the same volume
- Volumes persist across deployments; created on first use (`create_if_missing=True` by default)
- Backed by gfuse-mounted cloud buckets (GCS)
- CLI: `cycls volume create / ls / rm / info`
- `Image.volume("/path")` shortcut (from RFC 001) stays for the anonymous single-volume case

## Decisions deferred

- `cycls.Dict`, `cycls.Queue`, `cycls.Secret` — later RFCs, each with its own GCP substrate (see *Future primitives roadmap* below)
- Volume versioning / snapshots — TBD, GCS object versioning is the likely substrate
- Multi-writer coordination primitives (locks, leases) — TBD when needed

---

## Why

Today's state (post-RFC-001):

- Each `@agent` can create one cloud bucket via `Image.volume("/workspace")`
- The bucket is implicitly named after the app and tied to its lifecycle
- No way to share state between apps
- No way to reference a volume from outside the app that created it
- No CLI to inspect, back up, or migrate volume state

Modal's Volume solves all of this by making the volume a **named, first-class resource**:

- Create once, reference by name, outlives the apps that use it
- Multiple functions/apps can mount the same volume
- Can be listed, inspected, deleted via CLI
- Lifecycle is independent — delete an app, volume survives

This unlocks genuinely useful patterns:

- **Cross-app shared state**: one app writes, another reads
- **Long-lived persistence**: a volume stores your agent's accumulated memory / knowledge base / user data across deployments
- **Data migration**: back up a volume, restore to a new region
- **Team-shared data**: multiple agents in an org mount the same knowledge base

---

## Design

### The primitive

```python
# Create (or reference) a named volume
notes = cycls.Volume("user-notes")
shared = cycls.Volume("team-knowledge-base")

# Mount in an agent — multiple volumes at different paths
@cycls.agent(
    image=image, web=web, llm=llm,
    volumes={
        "/workspace": notes,
        "/shared":    shared,
    },
)
async def super(context):
    async for call in context:
        ...
```

### Naming semantics

- `cycls.Volume("name")` → looks up the volume by name in the current Cycls account
- If it doesn't exist, it's created on first deployment (`create_if_missing=True` is the default)
- Names are account-scoped and unique
- Names are slug-like: `[a-z0-9-]+`

### Mounting

- Volumes are attached to apps via the `volumes={}` kwarg on `@function`, `@app`, and `@agent`
- Key is the mount path inside the container, value is a `cycls.Volume` reference
- Multiple volumes per app, mounted at different paths
- The same volume can be mounted by multiple apps

### Under the hood

- **One project-wide GCS bucket** per environment (e.g. `cycls-volumes-prod`). All accounts share it.
- **Each volume is a prefix** within that bucket: `gs://cycls-volumes-prod/<account_id>/<volume_name>/`.
- **Isolation** is enforced via SDK path scoping (layer 1) and IAM conditions on the bucket that restrict read/write by prefix (layer 2). See *Credentials & trust model* below.
- **Mounting**: at deploy time, Cycls configures the container to `gcsfuse --only-dir=<account_id>/<volume_name> cycls-volumes-prod <mount_path>`.
- **Volume metadata** (creation time, size, last access, mounting apps) lives in Cycls's control plane, not in GCS.

### Shortcut: the `Image.volume()` method from RFC 001

Stays as a convenience for single-volume apps that don't need naming. It's sugar for an anonymous volume — Cycls creates a volume with a system-generated name (e.g. `<app_id>__anon`), tied to the app's lifecycle, deleted when the app is deleted.

```python
image = cycls.Image().pip("anthropic").volume("/workspace")

@cycls.agent(image=image, web=web, llm=llm)
async def my_agent(context):
    ...
```

Use the named primitive (`cycls.Volume("name")`) when you want persistence or sharing beyond a single app.

### `Volume` API

```python
vol = cycls.Volume("my-notes")

# Properties
vol.name          # "my-notes"
vol.created_at    # datetime
vol.size_bytes    # int

# Modifiers (return a new reference, don't mutate)
vol.read_only()   # mounts as read-only; attempts to write raise
```

In-app reads/writes go through the mounted filesystem — users never call methods on the `Volume` object for data access. The object is a **reference**; actual I/O happens against the mount point. Control-plane operations (create, delete, copy, inspect) live on the CLI, not the Python object.

**When is the volume created?** On first `cycls deploy` that references it. The Python call `cycls.Volume("name")` is just a reference — it does not make control-plane calls. Deploying an app that mounts an unknown volume triggers creation with `create_if_missing=True`.

---

## CLI

```bash
cycls volume create <name>        # create a named volume
cycls volume ls                    # list all volumes in the account
cycls volume info <name>           # size, created_at, mounted by which apps
cycls volume rm <name>             # delete (with confirmation)
cycls volume cp <src> <dest>       # copy files between local and volume paths
```

**`cp` path convention**: local paths are plain (`./docs/`, `/tmp/foo.txt`), volume paths use `<volume_name>:<path>` (`team-kb:/`, `team-kb:/articles/x.md`). The colon separates the volume name from the path within it. Direction is inferred from which side has the colon.

Examples:

```bash
# Create a knowledge base volume
cycls volume create team-kb

# Populate it
cycls volume cp ./docs/ team-kb:/

# Check what's using it
cycls volume info team-kb
# → Used by: agent-research, agent-support

# Delete (refuses if in use)
cycls volume rm team-kb
```

---

## Full example

```python
# examples/agent/research.py
import cycls

image = cycls.Image().pip("anthropic", "httpx")
web = cycls.Web().auth(True).title("Research Agent")
llm = cycls.LLM().model("claude-sonnet-4-6").system("You are a research assistant.")

# Named volumes
kb = cycls.Volume("team-knowledge-base")       # shared across agents
sessions = cycls.Volume("research-sessions")   # per-app history

@cycls.agent(
    image=image, web=web, llm=llm,
    volumes={
        "/kb":         kb,
        "/workspace":  sessions,
    },
)
async def research(context):
    async for call in context:
        if call.name == "save_to_kb":
            path = f"/kb/{call.input['topic']}.md"
            with open(path, "w") as f:
                f.write(call.input["content"])
            call.result = f"Saved to {path}"
```

Another agent can mount the same `kb` and read what `research` wrote:

```python
# examples/agent/support.py
import cycls

kb = cycls.Volume("team-knowledge-base")  # same volume

@cycls.agent(
    image=image, web=web, llm=llm,
    volumes={"/kb": kb},
)
async def support(context):
    async for call in context:
        if call.name == "lookup":
            # Read from the shared KB
            ...
```

Two apps, same persistent shared state. No coordination code, just mount the same named volume.

**Note on sync I/O in async bodies**: gfuse-mounted paths are regular filesystem paths — sync `open()`, `read_text()`, `write_text()` work and are usually fast enough. Use `aiofiles` if you need explicit async (long writes, many concurrent handlers). Don't block the event loop on huge files.

---

## gfuse: what it can and can't do

Honest assessment of the backing substrate. gfuse-mounted GCS is great for most things and problematic for a few specific patterns.

### ✅ Works well

- **Single-writer**: one app at a time writes to a path, others read. This is ~80% of agent use cases.
- **Append-only / new-file-per-write**: writing a new file per operation. Safe, scales, no conflicts.
- **Large files**: gfuse is good at whole-file reads and writes.
- **Read-heavy**: mounting a shared knowledge base read-only across many agents — fast, cheap, correct.
- **Persistence**: GCS is durable, replicated, multi-region if configured.
- **Workspace state**: the current Cycls workspace pattern (agent writes files, user browses them later) works perfectly.

### ⚠️ Works with caveats

- **Multi-writer**: concurrent writes to the same file are not safely ordered. Last-writer-wins with no conflict detection. Solve at the app level (use different file names, or use a real KV store).
- **Small files with high frequency**: every file write is a GCS PUT (~50-100ms latency). Writing 10,000 tiny files in a loop is slow. Batch into larger files.
- **File renames**: gcsfuse emulates renames with copy+delete. Not atomic, slower than native filesystems.
- **Directory listings on huge directories**: listing a folder with 100K files is slow. Partition your data.

### ❌ Doesn't work

- **True locking**: fcntl-style file locks don't work across gfuse mounts. Need application-level coordination.
- **Named pipes / sockets / special files**: no.
- **Strict POSIX semantics**: partial writes, atomic renames, exclusive create — not reliable.

---

## Migration from RFC 001's `Image.volume()`

`Image.volume("/workspace")` (RFC 001) and `cycls.Volume("name")` (RFC 002) coexist. They're different features for different needs:

| | `Image.volume(path)` | `cycls.Volume("name")` |
|---|---|---|
| Named | No (anonymous) | Yes |
| Shared across apps | No | Yes |
| Lifecycle | Tied to the app | Independent |
| Referenced from CLI | No | Yes (`cycls volume ls`) |
| Use case | Single-app workspace | Shared / long-lived state |

`Image.volume("/workspace")` is the simple case and stays as-is. The named form adds an upgrade path when you need sharing or persistence beyond a single app. The internal implementation is identical — an anonymous volume is a named volume with a system-generated name.

---

## Credentials & trust model

**Devs never see GCP credentials.** Same pattern as today's gfuse-mounted workspaces: Cycls runtime has the creds, user containers inherit them via the metadata server, the Python primitives use default credentials automatically. No env vars, no JSON key files, no `GOOGLE_APPLICATION_CREDENTIALS`, no GCP account required on the user side.

**Multi-tenancy via two layers of defense**:

- **Layer 1 — SDK path scoping**. Every primitive is resolved under the current account's namespace. A `cycls.Volume("prefs")` call from account A resolves to `gs://cycls-volumes-prod/<A>/prefs/`; from account B, `gs://cycls-volumes-prod/<B>/prefs/`. User code has no way to address another account's resources.
- **Layer 2 — GCS IAM conditions**. The service account can only read/write under the current account's prefix. Even if the SDK is bypassed, GCS refuses cross-account access.

Same defense-in-depth pattern that already works for gfuse Volumes today.

### Local development

`cycls run my_agent.py` needs to reach the backing service without creating real GCP resources. For Volume: mount a local directory (`~/.cycls/local/volumes/<name>/`) in place of the gfuse mount. Zero setup. State survives between runs and can be wiped with `cycls clean`.

When Dict/Queue/Secret arrive, they use the same pattern with emulators:

| Primitive | Local backend |
|---|---|
| `Volume` | Local directory in place of gfuse mount |
| `Dict` (future) | Firestore emulator (`gcloud emulators firestore start`) |
| `Queue` (future) | Pub/Sub emulator (`gcloud emulators pubsub start`) |
| `Secret` (future) | Values from a local `.env` file |

The Cycls CLI spawns the relevant emulator(s) transparently on `cycls run` and sets the standard env vars (`FIRESTORE_EMULATOR_HOST`, `PUBSUB_EMULATOR_HOST`). The google-cloud-* client libraries automatically use them.

---

## Open questions

1. **Volume quota** — default size/count limits per account? Probably yes, with overage billing.
2. **Volume versioning** — expose GCS object versioning as `cycls volume snapshot` / `restore`? Nice-to-have, not v1.
3. **Multi-region volumes** — GCS dual-region and multi-region support. Expose as `cycls.Volume("name", region="us")`? Deferred.
4. **Access control between apps in the same account** — v1 is account-wide (any app in the account can mount any volume). Per-volume ACLs deferred.

---

## Rejected alternatives

**Bake Volume into Image (RFC 001's method-only approach)** — fine for single-volume apps but can't express named, shareable, lifecycle-independent volumes. Both forms coexist.

**Make Volume implicit (every app gets one automatically)** — too magical, hides the lifecycle question. Explicit `cycls.Volume("name")` forces the user to think about persistence.

**Skip Volume, use a separate storage service API** — requires users to learn a parallel API (boto3-style). Loses the composability of "mount it, read/write files, done."

**Build Dict/Queue on Volume** — filesystem semantics don't match KV atomicity or queue ordering requirements. Each data primitive gets its own purpose-built substrate (see *Future primitives roadmap*).

---

## Future primitives roadmap

The four-primitive vision. Each follows the same pattern: named GCP-native resource with a Pythonic facade. Each gets its own RFC as it's scoped.

| Primitive | GCP substrate | Facade | Status |
|---|---|---|---|
| `cycls.Volume("name")` | GCS bucket (prefix-scoped) | gfuse mount → POSIX filesystem | **This RFC** |
| `cycls.Dict("name")` | Firestore collection | Python async dict (`get`/`set`/`items`/`transaction`) | Future |
| `cycls.Queue("name")` | Pub/Sub topic + auto-managed subscription | async `put` / `async for msg in q` / `ack` | Future |
| `cycls.Secret("name")` | Secret Manager | Injected as env vars at container start | Future |

**Rejected substrates** (for the record):

- **Memorystore Redis** for Dict/Queue — breaks the zero-to-pay model (~$40/month minimum instance).
- **Firestore as queue backend** — poll-based, inefficient; Pub/Sub is the right fit.
- **gfuse as KV backend** — filesystem semantics don't match KV atomicity requirements.
- **BigTable** — overkill for Cycls's scale, expensive minimum.

**Why these substrates** (as of 2026 pricing): Firestore has a generous free tier (50K reads + 20K writes/day, 1GB), Pub/Sub has 10GB/month free, Secret Manager has 10K accesses/month free. At Cycls's scale, most users stay in free tier across all primitives. Beyond that, pricing is per-operation — matches Cycls's own usage-based model.

---

## Status tracker

- [ ] RFC 001 shipped (prerequisite)
- [ ] `cycls.Volume` primitive implemented
- [ ] `volumes={}` kwarg on `@function`, `@app`, `@agent`
- [ ] Control plane for named volumes (create, list, info, delete)
- [ ] CLI: `cycls volume create / ls / info / rm / cp`
- [ ] gfuse mounting at deploy time based on `volumes={}`
- [ ] Quota + billing integration
- [ ] Local development story for volumes
- [ ] Migration guide (how to upgrade from `Image.volume()` to `cycls.Volume()`)

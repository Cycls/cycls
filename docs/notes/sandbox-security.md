# Sandbox security

How the bash tool is isolated from the host agent process, what's currently covered, what's known to leak, and the fix plan.

## Threat model

- **Agent developer** (`@cycls.agent` author, deploys via `cycls deploy`) — **trusted**. They configured the image, they wrote the handler, they own the workspace.
- **End user** (talks to the agent via web/API, submits prompts) — **untrusted**. Prompt injection is the primary concern. An adversarial prompt should not be able to exfiltrate data belonging to the developer, their other users, or any other tenant.

Every control below is designed against prompt injection, not against a malicious developer.

## Layers

A deployed agent runs inside a per-deploy Docker container. The `bash` tool (`cycls/agent/harness/tools.py::_exec_bash`) adds a second layer inside that container using `bwrap`. So the chain is:

```
host → docker container (agent runtime) → bwrap sandbox (bash tool)
```

The agent's Python process holds secrets as env vars (`ANTHROPIC_API_KEY`, `CYCLS_API_KEY`, `OPENAI_API_KEY`, the user's own `.env`, etc.). The goal of the bwrap layer is to make sure a prompt-injected bash command cannot reach any of those.

## Current invocation

```sh
bwrap --ro-bind / /
      --tmpfs /tmp --dev /dev --proc /proc
      --unshare-user
      --clearenv --die-with-parent
      --setenv PATH ... --setenv HOME /workspace
      --setenv TERM xterm --setenv LANG ...
      --ro-bind <pkg>/_blockmeta.so /tmp/.blockmeta.so   # LD_PRELOAD shim
      --setenv LD_PRELOAD /tmp/.blockmeta.so
      --bind <cwd> /workspace
      --tmpfs /workspace/.db                              # hide SlateDB internals
      --tmpfs /app                                        # mask provider .env file
      --chdir /workspace
      [--unshare-net]                                     # only when network=False
      -- bash -c <command>
```

Launched via `asyncio.create_subprocess_exec(..., env={"PATH": ..., "LANG": ...})`.

Key properties:

- **Network**: the LLM bash tool defaults to `network=True` (curl/pip/git for the model). When `network=False`, `--unshare-net` + `--unshare-user` gives a fresh netns owned by a fresh userns, so bwrap has caps to bring up `lo` even though Docker drops `CAP_NET_ADMIN` on the outer container. Without `--unshare-user`, loopback setup fails with `RTM_NEWADDR: No child processes`.
- **Workspace is the only writable path** (`<cwd>` bound at `/workspace`). Root is read-only; `/app` and `/tmp` are ephemeral tmpfs.
- **`.db/` is hidden** (`--tmpfs /workspace/.db`) so the sandboxed shell can't read SlateDB internals from the workspace volume. Editor tools (`read`, `edit`) also reject `.db/` paths via `_resolve_path`; tmpfs is defense in depth.
- **Metadata server is blocked** via the LD_PRELOAD shim (`_blockmeta.so`), which intercepts libc `connect()` and rejects `169.254.0.0/16` + IPv6 link-local. See "Cloud credential exposure" below for the threat boundary.

### Why not `--unshare-all`?

We tried. `--unshare-all` adds PID/IPC/UTS/cgroup unsharing and triggers `--proc /proc` to mount a fresh procfs in the new PID namespace. That fails with `bwrap: Can't mount proc on /newroot/proc: Operation not permitted` in our nested-container runtime — even with `cap_add=SYS_ADMIN`, `seccomp=unconfined`, `apparmor=unconfined` on the outer container. The nested Docker + user namespace chain blocks the procfs mount.

Dropping `--unshare-all` means `/proc` inside the sandbox shows the full container PID tree. That *sounds* bad — bash can see bwrap, Python, every process. But the actual protection is one layer down: `--unshare-user` puts bash in a child user namespace. Every `/proc/<pid>/environ`, `/proc/<pid>/mem`, `/proc/<pid>/root` access requires `PTRACE_MODE_READ_FSCREDS` across the user-namespace boundary, which the kernel denies. See the attack probes below — `cat /proc/*/environ` returns "Permission denied" for every PID except bash's own.

## Threat model — attack probes (filesystem & /proc)

We ran a battery of attacker-perspective bash commands from inside the sandbox. Findings:

| Attack | Result | Why |
|---|---|---|
| `cat /proc/$PPID/environ` (read bwrap/Python env) | Permission denied | Cross-user-NS ptrace blocked |
| Grep `/proc/*/environ` for planted API-key sentinel | No match — every PID blocked except bash's own | Same |
| `ls /proc/<other_pid>/root/workspace/` (cross-tenant FS via magic symlink) | Permission denied | Same |
| `cat /proc/<other_pid>/root/<other_tenant>/secret` | Permission denied | Same |
| `ls /workspace/` | Only current tenant's dir visible | `--bind <cwd> /workspace` masks sibling tenants |
| `mount \| grep workspace` | Shows only the bound current-tenant dir | Mount namespace unshared by bwrap default |
| `cat /etc/shadow` | Permission denied | File mode 0400 root-only; bash is non-root |
| `cat /app/.env` | Empty dir | `/app` is `--tmpfs` — masks the provider-keys file baked into the image |
| Read container's `/proc/1/environ` (docker-init) | Permission denied | Same cross-user-NS rule |
| `getent hosts example.com` with `network=False` | Fails | `--unshare-net` — no egress |
| `curl http://evil` with `network=True` | Works | Explicit opt-in — but see "Cloud credential exposure" below |

## Cloud credential exposure (mitigated, with documented threat boundary)

The filesystem and `/proc` isolation holds, but the cloud-credential layer needs its own answer because bwrap doesn't touch it by default.

### The mechanism

Cloud Run (and any GCP compute) exposes a **metadata server** at `169.254.169.254` that any process in the instance can reach with no credentials of its own:

```sh
curl -H "Metadata-Flavor: Google" \
  http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token
```

It returns a short-lived (~1h) access token for the Cloud Run service account. That token is **bucket-wide** — the SA has read + write across the agent's whole workspace bucket, including other tenants' prefixes. Stealing it from a sandboxed shell = cross-tenant breach.

### What we tried (and why they don't work on Cloud Run)

| Approach | Verdict |
|---|---|
| `--unshare-net` (kill network entirely) | Closes the vector but breaks `curl`/`pip`/`git` — most agents need internet |
| `slirp4netns` / `pasta` (user-space TCP/IP into a fresh netns + IP filter) | **Dead path**: both require `/dev/net/tun`. Cloud Run V2 user containers (verified live: kernel 6.9.12, Gen2 microVM) **don't expose `/dev/net/`**. No TUN, no filtered netns. |
| `iptables` blackhole at container entrypoint | Requires `CAP_NET_ADMIN`. Cloud Run drops it. |
| Cloud Run VPC egress controls | Don't apply to link-local IPs (169.254/16 routes outside VPC) |
| Disable metadata server at the platform | No such Cloud Run knob. GKE Workload Identity has metadata hardening; Cloud Run doesn't. |

The `/dev/net/tun` wall is the load-bearing constraint — it kills every "fresh netns + user-space net stack" approach simultaneously.

### What we shipped: LD_PRELOAD shim

`cycls/app/sandbox/_blockmeta.c` (~30 LOC C) intercepts libc `connect()` and returns `ECONNREFUSED` for:

- `169.254.0.0/16` (IPv4 link-local — covers GCP/AWS/Azure metadata)
- `fe80::/10` (IPv6 link-local)
- `fd00:ec2::/32` (AWS-style IPv6 metadata, defensive)

The compiled `.so` ships in the cycls Python package (`importlib.resources.files("cycls.app.sandbox") / "_blockmeta.so"`), gets ro-bind-mounted into the bwrap sandbox at `/tmp/.blockmeta.so`, and is loaded via `LD_PRELOAD` env. Every libc-using program (curl, wget, python's socket/requests/urllib, node's http, etc.) gets metadata blocked.

### Threat boundary (read this carefully)

LD_PRELOAD is a **seatbelt, not a vault**. It covers the realistic threats and is bypassable in narrow ways. We accept the bypass cost because every alternative on Cloud Run is either ineffective or requires architectural rework (per-tenant deploys).

**Covers** (≥95% of what an LLM-issued shell does):
- Any program that uses libc `connect()` — curl, wget, python, node, ruby, php
- DNS-resolved access (`metadata.google.internal` → 169.254.169.254 → libc → blocked)
- Process exec chains (the shim survives `exec()`)
- Casual prompt injection asking the LLM to "fetch this URL"

**Does NOT cover** (documented bypasses):
- **Static binaries** — Go's default build, `musl-static` curl, anything compiled `-static`. They don't use libc, so `LD_PRELOAD` doesn't load.
- **Direct `syscall(SYS_connect, ...)`** — `python -c "import ctypes; ctypes.CDLL('libc.so.6').syscall(42, ...)"` calls libc's syscall wrapper, not libc's `connect` symbol.
- **Inline assembly** — `asm volatile("syscall" : : "a"(42), ...)`.
- **`unset LD_PRELOAD; curl ...`** — using env-var injection, the sandbox's LD_PRELOAD can be stripped from a child process's env. (Mitigation: `/etc/ld.so.preload` is harder to bypass but requires the file to pre-exist on the host, which our `--ro-bind / /` doesn't allow without extra image-build setup. Future hardening.)

All four bypasses require **deliberate adversarial intent** — the LLM, naturally generating code, will not pick them. They matter only if the threat model includes "user actively reads cycls source and crafts bypass code."

For the realistic cycls product shape (developer ships an agent for their customers, who use it normally with occasional prompt injection attempts), this shim closes the practical metadata vector. For "deliberately adversarial users with shell access," no SDK-level fix is sufficient — the architectural answer is per-tenant Cloud Run deploys (each tenant's bash steals only their own SA, no cross-tenant leak).

### What this does NOT change

- The developer's Python handler runs outside bwrap and keeps full ADC by design — they need it for `slatedb`/GCS calls, future `ws.object()` primitive, etc. Developer trust boundary is unchanged.
- Framework state writes (share tokens, chat metadata, usage counters) happen via trusted Python code with the full-scope token. Scoping is only applied at the bash-tool boundary where untrusted input reaches.

## What's provably safe in prod

- **Process env / provider keys** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) — live in Python's env, unreadable via `/proc/<python_pid>/environ` due to user-NS boundary. `/app/.env` is masked by tmpfs. ✅
- **CLI/publish secrets** (`CYCLS_API_KEY`, `UV_PUBLISH_TOKEN`) — not shipped into the runtime container at all, thanks to the `.providers.env` split (`Image.copy(".providers.env", ".env")`). Can't leak from a place they never existed. ✅
- **SlateDB internals** — `--tmpfs /workspace/.db` masks the workspace's `.db/` so the sandboxed shell can't read the LSM/WAL files. Editor tools also reject `.db/` paths. ✅
- **Cross-tenant filesystem access via `/proc` or mount tricks** — blocked at both layers (user-NS + bind mount). ✅
- **Cross-tenant GCS access via metadata-minted tokens** — mitigated for libc-using code via the LD_PRELOAD shim. ⚠️ Bypassable by static binaries / direct syscall / `unset LD_PRELOAD`; see threat boundary above. Fully closing requires per-tenant deploys.

### Dev-only caveat

`bwrap --ro-bind / /` exposes the *entire* host root read-only inside the sandbox. In prod that's just the runtime container's filesystem (clean, no host secrets). But if you run `._local()` (no Docker) during development on a machine that has `/workspaces/<project>/.env`, `~/.claude/.credentials.json`, or similar *local* secrets, those are readable from the sandbox.

Mitigation: during dev, use `.local()` (Docker-wrapped) instead of `._local()` when exercising agents that accept untrusted input and have `sandbox(network=True)`. Or keep `network=False` so even if a dev-host secret is read, there's no exfil path.

## Gotcha — bwrap's own environ

`--clearenv` only clears the *child's* environment (bash). `bwrap` itself is visible as PID 1 inside the sandbox's `/proc`. Its own environ is inherited from the parent Python process.

Without passing `env=` to `subprocess_exec`, a sandboxed bash can run:

```sh
cat /proc/1/environ | tr '\0' '\n'
```

and read every secret the parent Python had. We hit this in practice — a live probe dumped `ANTHROPIC_API_KEY`, `CYCLS_API_KEY`, `GITHUB_TOKEN`, `UV_PUBLISH_TOKEN`, and the user's `.env` contents.

The fix is to sanitize bwrap's *own* env via `subprocess_exec`'s `env=` kwarg, not rely on `--clearenv`:

```python
bwrap_env = {"PATH": ..., "LANG": ...}
await asyncio.create_subprocess_exec("bwrap", ..., env=bwrap_env, ...)
```

When auditing new sandbox changes, test `/proc/1/environ` specifically, not just a sentinel grep across all `/proc/*/environ`. A sentinel-based test will catch the leak, but the root cause (PID 1 = bwrap, not bash) is easy to miss when reading the code.

## Testing

Tests split across `tests/app/sandbox_test.py` (sandbox-level) and `tests/agent/harness_test.py` (tool-level):

- **Argv-level (always run, in `sandbox_test.py`):** assert the flags we depend on are present — `--unshare-user`, `--unshare-net` when `network=False`, `--clearenv`, `--die-with-parent`, only safe env via `--setenv` (PATH/HOME/TERM/LANG/LD_PRELOAD), explicit `env=` on `subprocess_exec`, `_blockmeta.so` ro-bind + LD_PRELOAD set.
- **Live — bwrap environ leak (skipped off-container):** plant a sentinel env var, verify *bwrap's own* `/proc/<pid>/environ` is clean. Skipped on hosts where `--ro-bind / /` blocks creating `/workspace`.
- **Live — metadata block:** with `network=True`, assert `curl http://169.254.169.254/...` fails fast with "Couldn't connect" (libc connect → ECONNREFUSED via shim). Prevents future regressions where someone edits `_blockmeta.c` and forgets to rebuild — stale `.so` would still bind-mount fine but stop blocking.

When touching the sandbox layer, run all three and — if the live tests skip on your dev host — bring up a deployed container (`docker exec` into the running cycls agent) and verify there.

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

```python
bwrap --ro-bind / /
      --bind <cwd> /workspace
      --ro-bind-try <cwd>/.cycls /workspace/.cycls
      --tmpfs /app --tmpfs /tmp --dev /dev --proc /proc
      [--unshare-net]
      --chdir /workspace --die-with-parent --clearenv
      --setenv PATH ...  --setenv HOME /workspace
      --setenv TERM xterm --setenv LANG ...
      -- bash -c <command>
```

Launched via `asyncio.create_subprocess_exec(..., env={"PATH": ..., "LANG": ...})`.

Key properties:

- **Network is isolated by default** via `--unshare-net`. Opt in per-agent with `cycls.LLM().sandbox(network=True)` if bash needs `curl` / `pip install` / `git clone`. With network off, even a compromised bash has no egress.
- **Workspace is the only writable path** (`<cwd>` bound at `/workspace`). The root is read-only; `/app` and `/tmp` are ephemeral tmpfs.
- **`.cycls/` is read-only** (`--ro-bind-try`) so managed state (usage counters, session metadata) can be read by user commands but not tampered with at the filesystem layer.

### Why not `--unshare-all`?

We tried. `--unshare-all` adds PID/IPC/UTS/cgroup unsharing and triggers `--proc /proc` to mount a fresh procfs in the new PID namespace. That fails with `bwrap: Can't mount proc on /newroot/proc: Operation not permitted` in our nested-container runtime — even with `cap_add=SYS_ADMIN`, `seccomp=unconfined`, `apparmor=unconfined` on the outer container. The nested Docker + user namespace chain blocks the procfs mount.

Dropping `--unshare-all` means `/proc` inside the sandbox shows the full container PID tree. That *sounds* bad — bash can see bwrap, Python, every process. But the actual protection is one layer down: bwrap still implicitly `--unshare-user`s, so bash runs in a child user namespace. Every `/proc/<pid>/environ`, `/proc/<pid>/mem`, `/proc/<pid>/root` access requires `PTRACE_MODE_READ_FSCREDS` across the user-namespace boundary, which the kernel denies. See the attack probes below — `cat /proc/*/environ` returns "Permission denied" for every PID except bash's own.

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

## Cloud credential exposure (OPEN — planned fix)

Discovered 2026-04-20. The filesystem and `/proc` isolation above holds, but there's a separate exposure at the cloud-credential layer that bwrap doesn't touch by default.

### The mechanism

Cloud Run (and any GCP compute) exposes a **metadata server** at `169.254.169.254` that any process in the instance can reach with no credentials of its own:

```sh
curl -H "Metadata-Flavor: Google" \
  http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token
```

The metadata server returns a short-lived (~1h) access token for the Cloud Run service account. That token is **bucket-wide** — the SA has read + write on the entire shared workspace bucket, not just the calling tenant's prefix.

### The exposure

A networked bash (`sandbox(network=True)`) can mint this token and hit the GCS REST API directly, bypassing the filesystem isolation:

- **Read** every other tenant's files via `GET /storage/v1/b/{bucket}/o?prefix=<other_user>/`
- **Write** into any tenant's prefix via `POST /upload/storage/v1/b/{bucket}/o?name=<other_user>/whatever`
- **Bypass `.cycls/` guard** — the ro-bind and `resolve_path` checks are filesystem-layer; the GCS API doesn't care about them. A malicious prompt could reset its own quota or plant files in other tenants' `.cycls/`.

This affects **any tenant with `sandbox(network=True)` enabled**. Networked bash is intentionally enabled for many legitimate agents (web scraping, pip installs, API calls) — so this is a real prod exposure, not theoretical.

### Why current bwrap controls don't cover it

- `--unshare-net` would close it — but also kills all network, including legitimate `curl` / `pip install`. Not acceptable for agents that need internet.
- Filesystem isolation (`--bind`, `--ro-bind`, `/proc` ptrace) is irrelevant — the attack goes over TCP to a metadata IP, not through the filesystem.
- `--clearenv` + `env=` on `subprocess_exec` removes ADC-style env-var credentials, but the metadata server doesn't use env vars — it's a network endpoint.

### Fix direction

**Selective egress filter via user-space networking.** Keep network enabled in bash, block `169.254.169.254` and `metadata.google.internal` specifically. Two viable paths:

1. **bwrap + `pasta`** — `pasta` is unprivileged user-space networking (shipped in Debian/Fedora/Alpine). bwrap `--unshare-net` creates a fresh netns, pasta provides filtered connectivity to it with `--deny-out 169.254.169.254`. Bash gets full internet minus metadata. ~10 lines in `harness/tools.py`.

2. **iptables at container entrypoint** — blackhole `169.254.169.254` for the whole container before the framework starts. Requires `CAP_NET_ADMIN` on Cloud Run gen 2. Also blocks the framework's own ADC access, so the framework must cache or proxy tokens before the rule takes effect.

**Pasta path is cleaner** — smaller blast radius, no capability requirement, no framework behavior change. Preferred.

### Application-level defenses (ship alongside)

- **URL validators in every network-capable tool** — WebSearch, custom fetch tools, anything taking a user-influenced URL. Block hostnames and IPs matching `169.254.*`, `metadata.google.internal`, `*.internal`. One helper function, reused across tools.
- **Detect and log** — any outbound attempt to `169.254.169.254` from inside a sandbox should surface in audit logs, not just fail silently.

### What this does NOT change

- The developer's Python handler runs outside bwrap and keeps full ADC by design — they need it for `google-cloud-storage` usage, future `ws.object()` primitive, etc. Developer trust boundary is unchanged.
- The `.cycls/_migrated` marker, quota writes, and other framework state are still written by trusted framework code with the full-scope token. The scoping is only applied at the boundary where untrusted input reaches.

## What's provably safe in prod (updated)

- **Process env / provider keys** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) — live in Python's env, unreadable via `/proc/<python_pid>/environ` due to user-NS boundary. `/app/.env` is masked by tmpfs. ✅
- **CLI/publish secrets** (`CYCLS_API_KEY`, `UV_PUBLISH_TOKEN`) — not shipped into the runtime container at all, thanks to the `.providers.env` split (`Image.copy(".providers.env", ".env")`). They can't leak from a place they never existed. ✅
- **Cross-tenant filesystem access via `/proc` or mount tricks** — blocked at both layers. ✅
- **Cross-tenant GCS access via metadata-minted tokens** — **currently exposed for `sandbox(network=True)` agents.** Pasta-based fix planned. ❌

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

Three classes of test in `tests/guard_test.py`:

- **Argv-level (always run):** assert the flags we depend on are present (`--unshare-net` when `network=False`, `--clearenv`, `--die-with-parent`, only safe env via `--setenv`, explicit `env=` on `subprocess_exec`).
- **Live — process/env (skipped off-container):** actually run bwrap with a planted sentinel env var and verify *bwrap's own* `/proc/<pid>/environ` is clean. Skipped on dev hosts that lack `/workspace` and `/app` mount points.
- **Live — metadata egress (once pasta ships):** with `sandbox(network=True)`, assert `curl http://169.254.169.254/...` fails (connection refused / timeout) while `curl https://example.com` succeeds. Prevents regression.

When touching `_exec_bash`, run all three and — if the live tests skip — bring up a deployed container and verify there.

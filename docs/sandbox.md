# Sandbox

How the bash tool is isolated from the host agent process, and which gotchas we've hit.

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
- **`.cycls/` is read-only** (`--ro-bind-try`) so managed state (usage counters, session metadata) can be read by user commands but not tampered with.

### Why not `--unshare-all`?

We tried. `--unshare-all` adds PID/IPC/UTS/cgroup unsharing and triggers `--proc /proc` to mount a fresh procfs in the new PID namespace. That fails with `bwrap: Can't mount proc on /newroot/proc: Operation not permitted` in our nested-container runtime — even with `cap_add=SYS_ADMIN`, `seccomp=unconfined`, `apparmor=unconfined` on the outer container. The nested Docker + user namespace chain blocks the procfs mount.

Consequence: `/proc` inside the sandbox shows the full container PID tree, including the parent Python process. Bash can read `/proc/<ppid>/environ` and see whatever env vars the agent runtime was launched with. Mitigations in place:

- `cycls.Image().copy(".providers.env", ".env")` — keep `CYCLS_API_KEY`, `UV_PUBLISH_TOKEN`, and other tool-level secrets out of the shipped image. Only provider keys the agent actually needs end up in the container's environ.
- `--unshare-net` when `network=False` — even if a secret is read, no egress.
- bwrap's own environ is sanitized (see next section) so *bwrap itself* doesn't add to the leak surface.

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

Two classes of test in `tests/guard_test.py`:

- **Argv-level (always run):** assert the flags we depend on are present (`--unshare-net` when `network=False`, `--clearenv`, `--die-with-parent`, only safe env via `--setenv`, explicit `env=` on `subprocess_exec`).
- **Live (skipped off-container):** actually run bwrap with a planted sentinel env var and verify *bwrap's own* `/proc/<pid>/environ` is clean. Skipped on dev hosts that lack `/workspace` and `/app` mount points.

When touching `_exec_bash`, run both and — if the live tests skip — bring up a deployed container and verify there.

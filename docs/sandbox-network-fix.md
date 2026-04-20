# Sandbox network fix — close the metadata exposure

**Companion to**: [sandbox-security.md](sandbox-security.md)
**Goal**: close the cross-tenant GCS exposure documented in the "Cloud credential exposure" section while keeping networked Bash (`sandbox(network=True)`) fully functional for legitimate use.

---

## Scope

| Step | What changes | Lines |
|---|---|---|
| 1 | Add `pasta` (or `slirp4netns`) to the runtime Docker image | ~1 (Image.apt) |
| 2 | Rewrite `_exec_bash` to use `--unshare-net` + pasta with metadata egress denied | ~15 |
| 3 | Central URL validator helper; wire into WebSearch + any fetch tool | ~15 |
| 4 | CI tests: metadata IP/hostname blocked, other network works | ~30 |

**Out of scope:** metadata proxy / token downscoping (not needed under the current threat model — trusted developer, untrusted end user). The dev's Python handler keeps full ADC. We're only closing the prompt-injection → Bash path.

---

## Step 1 — Bundle `pasta` into the runtime image

`pasta` is part of the `passt` package on Debian/Ubuntu and shipped in Alpine. Unprivileged user-space networking — no `CAP_NET_ADMIN` required.

Update the runtime base image Dockerfile (or the framework's default `Image.apt()` call):

```python
# cycls/function/main.py — adjust the base image layer
image = image.apt("passt")   # provides the `pasta` binary
```

Adds ~1 MB to the runtime image. No other dependencies.

**Tests:** `docker run <image> which pasta` returns a path.

---

## Step 2 — Wire pasta into `_exec_bash`

Current shape (`cycls/agent/harness/tools.py::_exec_bash`):

```python
# Network is all-or-nothing today:
net_flags = () if network else ("--unshare-net",)
```

New shape: **always** `--unshare-net`, then pasta provides filtered connectivity when `network=True`.

```python
async def _exec_bash(command, cwd, timeout=600, network=False):
    # ... existing setup ...

    # Always unshare net — bwrap starts with no network.
    # If network is requested, pasta attaches a filtered stack after bwrap starts.

    bwrap_args = [
        "bwrap",
        "--unshare-net",
        "--ro-bind", "/", "/",
        "--bind", cwd, "/workspace",
        "--ro-bind-try", str(Path(cwd) / ".cycls"), "/workspace/.cycls",
        "--tmpfs", "/app", "--tmpfs", "/tmp",
        "--dev", "/dev", "--proc", "/proc",
        "--chdir", "/workspace", "--die-with-parent", "--clearenv",
        "--setenv", "PATH", path,
        "--setenv", "HOME", "/workspace",
        "--setenv", "TERM", "xterm",
        "--setenv", "LANG", lang,
        "--", "bash", "-c", command,
    ]

    if not network:
        proc = await asyncio.create_subprocess_exec(
            *bwrap_args, env=bwrap_env,
            stdout=..., stderr=...,
        )
    else:
        # Start bwrap, then attach pasta to its netns with metadata egress blocked.
        proc = await asyncio.create_subprocess_exec(
            *bwrap_args, env=bwrap_env,
            stdout=..., stderr=...,
        )
        pasta_proc = await asyncio.create_subprocess_exec(
            "pasta",
            "--config-net",                         # give the netns an IP + default route
            "--netns", f"/proc/{proc.pid}/ns/net",  # attach to bwrap's netns
            "--deny-out", "169.254.169.254",        # block GCP metadata IP
            "--deny-out", "metadata.google.internal",
            "--deny-out", "169.254.0.0/16",         # block all link-local just in case
            env={"PATH": path},
        )

    # ... existing wait/timeout/output handling ...
```

Key points:
- `--unshare-net` creates a fresh, empty netns for bwrap
- pasta attaches to that netns via `/proc/<pid>/ns/net` and provides a TAP device with external connectivity
- `--deny-out` rules filter egress at pasta's user-space TCP stack
- `bash` inside bwrap sees a normal-looking network (can resolve DNS, reach the internet), except metadata endpoints return `EHOSTUNREACH` or equivalent

**Tests:**
- `curl -m 3 https://example.com` succeeds from inside sandbox when `network=True`
- `curl -m 3 http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token -H "Metadata-Flavor: Google"` fails (connection refused / timeout)
- Same curl to `http://metadata.google.internal` fails
- Same curl with `network=False` fails for both (existing behavior preserved)

---

## Step 3 — URL validator for other network-capable tools

Bash isn't the only path that makes HTTP requests with user-influenced input. Audit:

- **WebSearch** — takes a user query; the search provider URL is hardcoded, safe
- **Custom fetch tools** — any developer-defined tool that accepts a URL from prompt context
- **Future tools** — image loaders, webhook callers, etc.

Add a helper in `cycls/agent/harness/net.py` (new file):

```python
"""Network destination safety — reject metadata servers and link-local IPs."""
import ipaddress
from urllib.parse import urlparse

_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
}

def ensure_safe_url(url: str) -> None:
    """Raise ValueError if the URL targets a cloud metadata endpoint or
    link-local range. Called by every tool that makes outbound HTTP from
    user-supplied URLs."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"Blocked destination: {host}")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_link_local or ip.is_private or ip.is_loopback:
            raise ValueError(f"Blocked destination: {host} (link-local/private)")
    except ValueError:
        pass  # not an IP literal; hostname check above is what matters
```

Call sites to wire in:
- Any existing tool that makes a URL-based request from user input
- `cycls.LLM().on(name, handler)` — document that custom handlers should use `ensure_safe_url` when they take URL args from the model

**Tests:**
- `ensure_safe_url("http://example.com")` passes
- `ensure_safe_url("http://169.254.169.254/...")` raises
- `ensure_safe_url("http://metadata.google.internal/...")` raises
- `ensure_safe_url("http://127.0.0.1")` raises
- `ensure_safe_url("http://10.0.0.1")` raises (private range)

---

## Step 4 — Tests

Three new test files / test classes:

1. **`tests/guard_test.py`** — add a `TestBashMetadataEgress` class with the live curl tests from Step 2. Gated on the container environment where bwrap + pasta actually work (skip on macOS dev hosts without the setup).

2. **`tests/net_test.py`** (new) — unit tests for `ensure_safe_url`. Covers all the blocked cases and allowed cases.

3. **`tests/agent_test.py`** — integration test: run the agent with `.sandbox(network=True)`, prompt-inject an attempted `curl metadata.google.internal`, verify the exfiltration attempt returns a connection error.

---

## Shipping order

1. **PR 1** — Steps 1 + 2 + 4 together. The pasta wiring and the tests that prove it works belong in one change. Merging the Dockerfile update without the wiring is a no-op; merging the wiring without pasta in the image breaks bash.
2. **PR 2** — Step 3. URL validator is orthogonal, can ship independently.
3. Deploy new SDK + rebuild runtime image.
4. Audit GCS access logs in the week after — verify no unexpected cross-prefix reads post-deploy (would indicate a bypass).

**Total engineering:** half a day to one day including tests.

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| pasta unavailable in some base image we deploy to | Low | Verify Debian/Alpine have it; fall back to `slirp4netns` which has the same interface |
| pasta's `--deny-out` syntax/behavior changes between versions | Low | Pin pasta version in the image; test on CI |
| Bypass via raw TCP to 169.254.169.254 even with denied pasta rules | Low — pasta denies at L3 | Confirm with live test; if bypassed, add L7 proxy as defense-in-depth |
| Performance overhead from pasta's user-space stack | Low | Measured latency is microseconds for local ops; remote latency is dominated by the network |
| Developer's agent relies on `curl 169.254.169.254` for a legitimate reason | Very low | None known — no legitimate use case. Document the block in tool docs |

---

## Forward-compat guarantees

- **Developer DX unchanged** — `sandbox(network=True)` still works, bash still has internet, custom fetch tools still work with safe URLs.
- **Developer's Python handler** keeps full ADC access. `from google.cloud import storage` still works, `ws.object()` primitive (future) still works.
- **No breaking changes** for agents currently running. The block is purely a new restriction on outbound destinations, visible only to prompt-injected exploit attempts.

---

## What this doesn't fix

- **Malicious developer writes their own exfiltration code** — explicitly out of scope (developer is trusted under the threat model).
- **Vulnerable SSRF in custom tools not using `ensure_safe_url`** — developer responsibility; cycls provides the helper but can't audit every custom tool.
- **Metadata access from inside the Python handler process** — by design. The handler is trusted code with full ADC.

If the threat model ever widens to "untrusted developer," the metadata proxy approach (token downscoping via `iamcredentials.generateAccessToken`) becomes necessary. That's a separate, larger piece of work — and not needed today.

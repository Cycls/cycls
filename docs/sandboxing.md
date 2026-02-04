# Sandboxing

Per-user isolation for running untrusted code on Cloud Run.

---

## Cloud Run + gVisor

Cloud Run runs containers inside gVisor. This isolates your container from the host, but **not** users from each other within the container. Per-user isolation must happen inside your container using proot.

---

## What Doesn't Work on Cloud Run

gVisor restricts namespace syscalls:

| Tool | Why it fails |
|------|--------------|
| Bubblewrap | `clone(CLONE_NEWUSER)` blocked |
| User namespaces | `unshare()` not permitted |
| Landlock | gVisor doesn't implement Landlock syscalls |
| Codex native sandbox | Uses Landlock or bubblewrap on Linux |

---

## Codex CLI Sandbox

Codex CLI sandboxing per platform:

| OS | Sandbox |
|----|---------|
| macOS | `sandbox-exec` (Seatbelt) |
| Linux | Landlock + seccomp, fallback to bubblewrap |

Neither Linux option works on Cloud Run. Use `--yolo` to bypass Codex's sandbox and rely on proot:

```python
codex_cmd = ["codex", "--yolo", "exec", "--json", prompt]
cmd = ["proot", "-b", f"{user_workspace}:/workspace", "-w", "/workspace"] + codex_cmd
```

> also codex default global reads. 
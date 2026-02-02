# Claude Agent SDK: Production Deployment Analysis

**Date:** February 2, 2026
**Status:** Assessment Complete

---

## Executive Summary

We investigated deploying the Claude Agent SDK in a production server environment (Cloud Run). The SDK has fundamental architectural limitations that result in **~5 second startup overhead per request**. This is a known issue with no current solution from Anthropic.

**Bottom line:** The SDK works, but with significant latency. Accept the 5s tax for now, or build a native agent loop later.

---

## Background

We are using the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) to serve an AI agent via FastAPI on Cloud Run. The SDK provides access to Claude Code's capabilities (file operations, bash execution, web search, etc.) through a Python interface.

---

## Problem

Initial deployment showed:
- **SIGTERM errors** (exit code -15) appearing in logs
- **Occasional requests not responding**
- **High latency** to first token (~10-15 seconds)

---

## Investigation Findings

### 1. SIGTERM Errors (-15)

**Cause:** Client disconnection (browser close, network timeout) leaves subprocess orphaned. Garbage collection eventually kills it with SIGTERM.

**Impact:** None. The error is cleanup noise - the user is already gone.

**Verdict:** Harmless, can ignore.

### 2. Architecture Analysis

The Claude Agent SDK is a **subprocess wrapper** around the Claude Code CLI:

```
Python App → spawns → Claude CLI (Node.js/Bun) → calls → Anthropic API
```

Each request:
1. Spawns a new CLI subprocess (~5s)
2. CLI initializes, loads config
3. Sends query to Anthropic API (~1.5s)
4. Streams response back
5. Subprocess terminates

**The 5s is subprocess spawn overhead, not API latency.**

### 3. Optimization Attempts

| Optimization | Result |
|-------------|--------|
| Skip version check | No improvement |
| 2 CPU + CPU boost | Reduced 10s → 5s |
| Warm subprocess pool | Doesn't work - SDK doesn't support multiple queries per connection |
| Streaming input mode | Only works on single persistent server, not serverless |
| Per-user warm clients | Same scaling issues |
| Session resume | Works for history, still 5s spawn per request |

### 4. SDK Version

- **SDK:** 0.1.27 (latest)
- **Bundled CLI:** 2.1.29 (Bun-based single-file executable)

The CLI already uses Bun (faster than Node.js). The 5s startup is as optimized as it gets.

### 5. Known Issues

Anthropic is aware of these limitations:

- **[Issue #333](https://github.com/anthropics/claude-agent-sdk-python/issues/333)** (Python): "Performance Issues with Server-side Multi-instance Deployment"
  - 20-30s startup times reported
  - No official response from Anthropic

- **[Issue #33](https://github.com/anthropics/claude-agent-sdk-typescript/issues/33)** (TypeScript): "Daemon Mode for Hot Process Reuse"
  - Closed with recommendation to use "streaming input"
  - Streaming input doesn't solve serverless use case

**Key quote from Issue #333:**
> "The SDK's architecture seems optimized for single-user CLI usage rather than multi-tenant server deployments."

---

## Root Cause

Claude Code was designed as an **interactive CLI tool**:
- Single user, single session
- Owns the terminal
- Long-running, stateful process

The SDK exposes this via subprocess, inheriting all limitations:
- Heavy memory footprint per instance
- Slow startup (Bun/Node.js runtime initialization)
- No connection reuse
- No multi-tenant support

**This is an architectural mismatch**, not a bug we can fix.

---

## Current Production Configuration

```python
@cycls.app(pip=["claude-agent-sdk"], copy=[".env"], memory="2Gi")
async def anthropic_agent(context):
    # Skip version check
    os.environ["CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK"] = "true"

    # Per-user persistent workspace
    user_workspace = f"/workspace/{user_id}"
    os.environ["CLAUDE_CONFIG_DIR"] = f"{user_workspace}/.claude"

    # Session resume for conversation history
    client = ClaudeSDKClient(
        options=ClaudeAgentOptions(
            cwd=user_workspace,
            resume=session_id,  # From previous response
            ...
        )
    )
```

**Performance (Cloud Run, 2 CPU + boost):**
- First request (cold container): ~25-30s
- Subsequent requests (warm container): ~6s to first token
- API response time: ~1.5s (the rest is subprocess overhead)

---

## Recommendations

### Short Term (Now)
1. **Accept the 5s latency** - It's the cost of using the SDK
2. **Use session resume** - Maintains conversation history across requests
3. **Set `min_instances=1`** - Eliminates cold container start (~25s → ~6s)
4. **Ignore SIGTERM errors** - They're harmless cleanup

### Medium Term (When Bandwidth Allows)
1. **Build native agent loop** - Use Anthropic API directly with custom tools
   - Reference: [baby-code](https://github.com/sidbharath/baby-code) (~200 lines)
   - Eliminates subprocess, ~1.5s latency
   - Trade-off: Must implement tools ourselves

### Long Term (Wait and See)
1. **Monitor Anthropic's SDK updates** - They may address this
2. **Watch for daemon mode** - Requested but not implemented
3. **Evaluate alternatives** - As ecosystem matures

---

## Alternatives Considered

| Option | Latency | Effort | Trade-off |
|--------|---------|--------|-----------|
| Claude SDK (current) | ~6s | Low | High latency |
| Native agent loop | ~1.5s | High | Build tools ourselves |
| Different compute (VM) | ~3-4s | Medium | Manage infrastructure |
| Wait for Anthropic | Unknown | None | Uncertain timeline |

---

## Conclusion

The Claude Agent SDK is functional but not optimized for server-side deployment. The ~5s subprocess overhead is architectural and cannot be eliminated without changes from Anthropic or building our own solution.

**Recommendation:** Ship with current implementation. The 6s first-token latency is acceptable for MVP. Plan to build native agent loop when we have bandwidth and clearer requirements.

---

## References

- [Claude Agent SDK (Python)](https://github.com/anthropics/claude-agent-sdk-python)
- [Issue #333: Server Performance](https://github.com/anthropics/claude-agent-sdk-python/issues/333)
- [Issue #33: Daemon Mode Request](https://github.com/anthropics/claude-agent-sdk-typescript/issues/33)
- [Bun joins Anthropic](https://bun.com/blog/bun-joins-anthropic)
- [Baby Code (DIY reference)](https://github.com/sidbharath/baby-code)

"""Loop events — dict factories in the FE's render shape.

The loop yields these directly; the agent body just passes them through
(`cycls.to_ui` is identity, kept for backwards compat). Match on `ev["type"]`:

    async for ev in llm.run(context=context):
        if isinstance(ev, dict) and ev.get("type") == "callout" and ev.get("style") == "error":
            page_ops(ev["callout"])
        yield ev

Bare strings (text deltas, the usage footer) pass through as-is — the SSE
encoder handles both strings and dicts.

A `Turn` is loop-internal — content + stop_reason + usage. Tagged so the
loop can distinguish it from forward-bound events; never reaches the body.
"""
from dataclasses import dataclass


# ---- Forward-bound events (the body sees these) ----

def text(s: str) -> str:
    """Plain text delta — passed through as a bare string."""
    return s


def thinking(s: str) -> dict:
    return {"type": "thinking", "thinking": s}


def step(label: str, *, tool: str | None = None, id: str | None = None) -> dict:
    out = {"type": "step", "step": label}
    if tool: out["tool_name"] = tool
    if id: out["id"] = id
    return out


def tool_args(id: str, delta: str) -> dict:
    """Live preview chunk for a tool call's input as it streams."""
    return {"type": "step_arg", "id": id, "delta": delta}


def callout(message: str, style: str = "info") -> dict:
    """info | warning | error | success."""
    return {"type": "callout", "callout": message, "style": style}


def tool_call(name: str, inp: dict) -> dict:
    """Unrecognized tool — the FE renders it generically."""
    return {"type": "tool_call", "tool": name, "args": inp}


def usage(input: int, output: int, cached: int, cache_create: int,
          cost: float | None, elapsed: float) -> str:
    parts = [f"in: {input:,}", f"out: {output:,}",
             f"cached: {cached:,}", f"cache-create: {cache_create:,}"]
    if cost is not None:
        parts.append(f"cost: ${cost:.4f}")
    m, s = divmod(int(elapsed), 60)
    parts.append(f"time: {f'{m}m {s}s' if m else f'{s}s'}")
    return "\n\n*" + " · ".join(parts) + "*"


# ---- Loop-internal: the assistant turn ----

@dataclass(frozen=True)
class Turn:
    """A completed assistant turn — last event a provider stream emits.
    Loop-internal: never forwarded. `content` is assistant content blocks in
    storage shape; the rest is this turn's token usage."""
    content: list
    stop_reason: str
    input: int = 0
    output: int = 0
    cached: int = 0
    cache_create: int = 0


# ---- Back-compat ----

def to_ui(ev):
    """Identity — events are already in UI shape. Kept so examples
    `yield cycls.to_ui(ev)` still work after the dict-event migration."""
    return ev

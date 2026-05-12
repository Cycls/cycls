"""Typed loop events.

`LLM.run` (and any `.loop(fn)`) yields these; `to_ui(event)` projects each one
to the shape the FE renders. The agent body pattern-matches to hook the loop, or
just `to_ui`s them through:

    async for ev in llm.run(context=context):
        match ev:
            case Step(query, "Web Search"): log_search(query)
            case Failed(msg):               page_ops(msg)
            case _:                         pass
        yield to_ui(ev)

`Callout` and `ToolCall` aren't emitted by the built-in loop but `to_ui` knows
them, so a custom `.loop(fn)` can yield them too.
"""
from dataclasses import dataclass
from typing import Optional


# ---- Streamed content ----

@dataclass(frozen=True)
class TextDelta:
    text: str

@dataclass(frozen=True)
class Thinking:
    text: str

@dataclass(frozen=True)
class Step:
    """A progress line. `tool` is set when the step is a recognized tool call."""
    label: str
    tool: Optional[str] = None

@dataclass(frozen=True)
class ToolStart:
    """The model has committed to a tool call — emitted the moment its block
    opens, before the (possibly large) arguments stream in. `id` threads the
    later `ToolArgs` chunks and the post-execution step to the same UI element;
    `tool` is the display name."""
    id: str
    tool: str

@dataclass(frozen=True)
class ToolArgs:
    """A chunk of a tool call's input as it streams (partial JSON). The FE
    appends `delta` to the call identified by `id` — a live preview of, e.g.,
    a file being written."""
    id: str
    delta: str

@dataclass(frozen=True)
class Callout:
    text: str
    style: str = "info"  # info | warning | error | success

@dataclass(frozen=True)
class ToolCall:
    """An unrecognized tool the harness can't run itself — the FE renders it
    generically and (today) the model is told it 'executed'."""
    name: str
    input: dict

@dataclass(frozen=True)
class Raw:
    """A payload already in FE shape — e.g. a custom tool handler's return value.
    Passed through `to_ui` untouched."""
    payload: object


# ---- Loop lifecycle (rendered as steps/callouts by default; hookable) ----

@dataclass(frozen=True)
class Compacting: ...

@dataclass(frozen=True)
class CompactionFailed:
    error: str

@dataclass(frozen=True)
class Retrying:
    attempt: int
    of: int
    delay: float

@dataclass(frozen=True)
class OutputLimitHit:
    attempt: int
    of: int

@dataclass(frozen=True)
class StoppedUnexpectedly:
    reason: str

@dataclass(frozen=True)
class TimedOut:
    message: str

@dataclass(frozen=True)
class Failed:
    error: str

@dataclass(frozen=True)
class Usage:
    input: int
    output: int
    cached: int
    cache_create: int
    cost: Optional[float]
    elapsed: float

@dataclass(frozen=True)
class Turn:
    """A completed assistant turn — the last event a provider stream emits.
    Loop-internal: the loop consumes it to advance state and never forwards it
    (to_ui raises on it). `content` is assistant content blocks in storage shape;
    `stop_reason` is the API stop reason; the rest is this turn's token usage."""
    content: list
    stop_reason: str
    input: int = 0
    output: int = 0
    cached: int = 0
    cache_create: int = 0


Event = (
    TextDelta | Thinking | Step | ToolStart | ToolArgs | Callout | ToolCall | Raw
    | Compacting | CompactionFailed | Retrying | OutputLimitHit
    | StoppedUnexpectedly | TimedOut | Failed | Usage | Turn
)


def to_ui(ev: Event):
    """Project a loop event to the dict/string shape the FE renders. Bare
    strings (text deltas, the usage footer) pass through as-is — the SSE
    encoder handles both strings and dicts."""
    match ev:
        case TextDelta(text):              return text
        case Thinking(text):               return {"type": "thinking", "thinking": text}
        case Step(label, tool):            return {"type": "step", "step": label, **({"tool_name": tool} if tool else {})}
        case ToolStart(id, tool):          return {"type": "step", "id": id, "tool_name": tool, "step": ""}
        case ToolArgs(id, delta):          return {"type": "step_arg", "id": id, "delta": delta}
        case Callout(text, style):         return {"type": "callout", "callout": text, "style": style}
        case ToolCall(name, inp):          return {"type": "tool_call", "tool": name, "args": inp}
        case Raw(payload):                 return payload
        case Compacting():                 return {"type": "step", "step": "Compacting context..."}
        case CompactionFailed(error):      return {"type": "callout", "callout": f"Compaction failed: {error}", "style": "warning"}
        case Retrying(attempt, of, delay): return {"type": "step", "step": f"Rate limited, retrying in {delay:.1f}s... (attempt {attempt}/{of})"}
        case OutputLimitHit(attempt, of):  return {"type": "step", "step": f"Output limit hit, continuing... ({attempt}/{of})"}
        case StoppedUnexpectedly(reason):  return {"type": "callout", "callout": f"Stopped: {reason}", "style": "warning"}
        case TimedOut(message):            return {"type": "callout", "callout": message, "style": "warning"}
        case Failed(error):                return {"type": "callout", "callout": error, "style": "error"}
        case Usage(inp, out, cached, cc, cost, elapsed):
            parts = [f"in: {inp:,}", f"out: {out:,}", f"cached: {cached:,}", f"cache-create: {cc:,}"]
            if cost is not None:
                parts.append(f"cost: ${cost:.4f}")
            m, s = divmod(int(elapsed), 60)
            parts.append(f"time: {f'{m}m {s}s' if m else f'{s}s'}")
            return "\n\n*" + " · ".join(parts) + "*"
    raise TypeError(f"unhandled event: {ev!r}")

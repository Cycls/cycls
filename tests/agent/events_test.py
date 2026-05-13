"""to_ui must reproduce the exact wire shapes the FE renders — a refactor of
the loop emitting typed events instead of dicts must not change the wire format."""
from cycls.agent.harness.events import (
    TextDelta, Thinking, Step, ToolStart, ToolArgs, Callout, ToolCall, Raw,
    Compacting, CompactionFailed, Retrying,
    StoppedUnexpectedly, TimedOut, Failed, Usage, to_ui,
)


def test_to_ui_content_shapes():
    assert to_ui(TextDelta("hi")) == "hi"
    assert to_ui(Thinking("hmm")) == {"type": "thinking", "thinking": "hmm"}
    assert to_ui(Step("Compacting context...")) == {"type": "step", "step": "Compacting context..."}
    assert to_ui(Step("ls", tool="Bash")) == {"type": "step", "step": "ls", "tool_name": "Bash"}
    assert to_ui(ToolStart("toolu_1", "Editing")) == {"type": "step", "id": "toolu_1", "tool_name": "Editing", "step": ""}
    assert to_ui(ToolArgs("toolu_1", '{"path":"a')) == {"type": "step_arg", "id": "toolu_1", "delta": '{"path":"a'}
    assert to_ui(Callout("oops", "error")) == {"type": "callout", "callout": "oops", "style": "error"}
    assert to_ui(ToolCall("render_image", {"src": "x"})) == {"type": "tool_call", "tool": "render_image", "args": {"src": "x"}}
    assert to_ui(Raw({"type": "text", "text": "from handler"})) == {"type": "text", "text": "from handler"}


def test_to_ui_lifecycle_shapes():
    assert to_ui(Compacting()) == {"type": "step", "step": "Compacting context..."}
    assert to_ui(CompactionFailed("boom")) == {"type": "callout", "callout": "Compaction failed: boom", "style": "warning"}
    assert to_ui(Retrying(3, 10, 1.5)) == {"type": "step", "step": "Rate limited, retrying in 1.5s... (attempt 3/10)"}
    assert to_ui(StoppedUnexpectedly("refusal")) == {"type": "callout", "callout": "Stopped: refusal", "style": "warning"}
    assert to_ui(TimedOut("Error: Command timed out after 600s")) == {"type": "callout", "callout": "Error: Command timed out after 600s", "style": "warning"}
    assert to_ui(Failed("connection reset")) == {"type": "callout", "callout": "connection reset", "style": "error"}


def test_to_ui_usage_footer():
    assert to_ui(Usage(1000, 200, 5000, 800, 0.0123, 65)) == "\n\n*in: 1,000 · out: 200 · cached: 5,000 · cache-create: 800 · cost: $0.0123 · time: 1m 5s*"
    assert to_ui(Usage(10, 20, 0, 0, None, 9)) == "\n\n*in: 10 · out: 20 · cached: 0 · cache-create: 0 · time: 9s*"

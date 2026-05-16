"""Event factories produce the exact wire shapes the FE renders."""
from cycls.agent.harness import events


def test_content_shapes():
    assert events.text("hi") == "hi"
    assert events.thinking("hmm") == {"type": "thinking", "thinking": "hmm"}
    assert events.step("Compacting context...") == {"type": "step", "step": "Compacting context..."}
    assert events.step("ls", tool="Bash") == {"type": "step", "step": "ls", "tool_name": "Bash"}
    assert events.step("", tool="Editing", id="toolu_1") == {"type": "step", "step": "", "tool_name": "Editing", "id": "toolu_1"}
    assert events.tool_args("toolu_1", '{"path":"a') == {"type": "step_arg", "id": "toolu_1", "delta": '{"path":"a'}
    assert events.callout("oops", "error") == {"type": "callout", "callout": "oops", "style": "error"}
    assert events.tool_call("render_image", {"src": "x"}) == {"type": "tool_call", "tool": "render_image", "args": {"src": "x"}}


def test_lifecycle_messages():
    """Loop-internal status events were collapsed into plain callouts/steps."""
    assert events.callout("Compaction failed: boom", "warning") == {"type": "callout", "callout": "Compaction failed: boom", "style": "warning"}
    assert events.step("Rate limited, retrying in 1.5s... (attempt 3/10)") == {"type": "step", "step": "Rate limited, retrying in 1.5s... (attempt 3/10)"}
    assert events.callout("Stopped: refusal", "warning") == {"type": "callout", "callout": "Stopped: refusal", "style": "warning"}
    assert events.callout("connection reset", "error") == {"type": "callout", "callout": "connection reset", "style": "error"}


def test_usage_footer():
    assert events.usage(1000, 200, 5000, 800, 0.0123, 65) == "\n\n*in: 1,000 · out: 200 · cached: 5,000 · cache-create: 800 · cost: $0.0123 · time: 1m 5s*"
    assert events.usage(10, 20, 0, 0, None, 9) == "\n\n*in: 10 · out: 20 · cached: 0 · cache-create: 0 · time: 9s*"


def test_to_ui_is_identity():
    """`to_ui` is back-compat shim — events are already in UI shape."""
    ev = events.callout("hello")
    assert events.to_ui(ev) is ev
    assert events.to_ui("plain text") == "plain text"

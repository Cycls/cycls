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


def test_to_ui_is_identity():
    """`to_ui` is back-compat shim — events are already in UI shape."""
    ev = events.callout("hello")
    assert events.to_ui(ev) is ev
    assert events.to_ui("plain text") == "plain text"

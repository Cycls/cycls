"""Tests for cycls.agent.chat.to_ui_messages — raw API → FE shape converter."""
from cycls.agent.chat import to_ui_messages


def test_passes_through_string_user_content():
    assert to_ui_messages([{"role": "user", "content": "hi"}]) == [
        {"role": "user", "content": "hi"}
    ]


def test_string_assistant_content_gets_text_part():
    out = to_ui_messages([{"role": "assistant", "content": "hello"}])
    assert out == [{"role": "assistant", "content": "hello",
                    "parts": [{"type": "text", "text": "hello"}]}]


def test_drops_user_tool_result_messages():
    """A user message that's purely tool_result blocks is harness scaffolding —
    it must not appear as a chat bubble (would crash React #31 too)."""
    raw = [
        {"role": "user", "content": "do thing"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x", "content": "ok"},
        ]},
        {"role": "assistant", "content": "done"},
    ]
    out = to_ui_messages(raw)
    assert [m["role"] for m in out] == ["user", "assistant"]


def test_assistant_blocks_become_parts():
    raw = [{"role": "assistant", "content": [
        {"type": "thinking", "thinking": "hmm..."},
        {"type": "text", "text": "Here you go"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}, "id": "1"},
    ]}]
    out = to_ui_messages(raw)
    assert len(out) == 1
    msg = out[0]
    assert msg["role"] == "assistant"
    assert msg["content"] == "Here you go"
    types = [p["type"] for p in msg["parts"]]
    assert types == ["thinking", "text", "step"]
    assert msg["parts"][2]["tool_name"] == "Bash"


def test_web_search_tool_use_includes_query():
    raw = [{"role": "assistant", "content": [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "rust async"}, "id": "1"},
    ]}]
    # server_tool_use isn't tool_use — currently dropped. This is desired:
    # web_search results render as steps via the streaming path; on reload
    # they'd need their own handling. For now ensure no crash.
    out = to_ui_messages(raw)
    assert out == [{"role": "assistant", "content": "", "parts": []}]


def test_user_message_with_text_blocks_only_keeps_text():
    """A user message with content as list-of-text-blocks (e.g. from _ingest)
    flattens to a string for display."""
    raw = [{"role": "user", "content": [
        {"type": "text", "text": "Look at "},
        {"type": "text", "text": "this image"},
    ]}]
    assert to_ui_messages(raw) == [{"role": "user", "content": "Look at this image"}]


# =============================================================================
# Load-time repair (_valid_prefix) — trim trailing corrupted state
# =============================================================================

from cycls.agent.chat import _valid_prefix


def test_valid_prefix_empty():
    assert _valid_prefix([]) == 0


def test_valid_prefix_clean_text_pair():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]
    assert _valid_prefix(msgs) == 2


def test_valid_prefix_dangling_assistant_tool_use():
    """Most common corruption: assistant emits tool_use, crash before
    tool_result is persisted. Anthropic rejects the next request — repair
    by trimming the dangling assistant message."""
    msgs = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {"command": "ls"}}
        ]},
    ]
    assert _valid_prefix(msgs) == 1  # trim the dangling assistant


def test_valid_prefix_complete_tool_pair():
    msgs = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "A", "name": "bash", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "A", "content": "ok"}]},
    ]
    assert _valid_prefix(msgs) == 3  # complete pair, all valid


def test_valid_prefix_orphaned_tool_result():
    """User message with tool_result but no preceding assistant tool_use."""
    msgs = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "X", "content": "ghost"}
    ]}]
    assert _valid_prefix(msgs) == 0


def test_valid_prefix_partial_tool_result_set():
    """Assistant emits two tool_uses, only one tool_result was persisted —
    Anthropic rejects (all tool_uses must be paired). Trim back."""
    msgs = [
        {"role": "user", "content": "do X and Y"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {}},
            {"type": "tool_use", "id": "B", "name": "read", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "A", "content": "ok"},
            # missing id="B"
        ]},
    ]
    # The user tool_result message has uses != rids, so it's orphaned;
    # then the assistant has dangling tool_uses; trim both.
    assert _valid_prefix(msgs) == 1


def test_valid_prefix_assistant_with_text_and_tool_use():
    """Assistant message that mixes text + tool_use is still dangling if no
    tool_result follows — the tool_use needs pairing regardless of text."""
    msgs = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Let me check"},
            {"type": "tool_use", "id": "A", "name": "bash", "input": {}},
        ]},
    ]
    assert _valid_prefix(msgs) == 1


def test_valid_prefix_clean_chain_then_dangling():
    """Long chat with valid history, recent turn corrupted. Repair preserves
    the prefix, drops only the bad tail."""
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "X", "name": "bash", "input": {}}]},
        # crash — no tool_result for X
    ]
    assert _valid_prefix(msgs) == 3  # keep first three, drop dangling

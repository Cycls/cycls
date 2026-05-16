"""Tests for to_ui_messages — stored API messages → FE shape converter."""
from cycls.agent.web.routers import to_ui_messages


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


def test_web_search_tool_use_renders_as_step():
    """`server_tool_use` blocks render as steps on refetch with the same
    {tool_name: "Web Search", step: query} shape the live provider yields."""
    raw = [{"role": "assistant", "content": [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "rust async"}, "id": "1"},
    ]}]
    out = to_ui_messages(raw)
    assert out == [{"role": "assistant", "content": "",
                    "parts": [{"type": "step", "tool_name": "Web Search", "step": "rust async"}]}]


def test_bash_tool_use_preserves_command_on_refetch():
    """Regression: live dispatch yields step={"tool_name":"Bash","step":<command>};
    on refetch, to_ui_messages must produce the same shape so the FE shows
    the command, not an empty step. Both paths route through tool_step()."""
    raw = [{"role": "assistant", "content": [
        {"type": "tool_use", "name": "bash", "input": {"command": "ls /workspace"}, "id": "X"},
    ]}]
    out = to_ui_messages(raw)
    assert out == [{"role": "assistant", "content": "",
                    "parts": [{"type": "step", "id": "X", "tool_name": "Bash", "step": "ls /workspace"}]}]


def test_bash_tool_use_prefers_description_over_command():
    raw = [{"role": "assistant", "content": [
        {"type": "tool_use", "name": "bash",
         "input": {"command": "rg foo", "description": "Search for foo"}, "id": "X"},
    ]}]
    out = to_ui_messages(raw)
    assert out[0]["parts"][0]["step"] == "Search for foo"


def test_editor_tool_uses_preserve_path_on_refetch():
    raw = [{"role": "assistant", "content": [
        {"type": "tool_use", "name": "read", "input": {"path": "src/main.py"}, "id": "A"},
        {"type": "tool_use", "name": "edit", "input": {"path": "src/main.py", "command": "create"}, "id": "B"},
    ]}]
    out = to_ui_messages(raw)
    parts = out[0]["parts"]
    assert parts[0] == {"type": "step", "id": "A", "tool_name": "Reading", "step": "src/main.py"}
    assert parts[1] == {"type": "step", "id": "B", "tool_name": "Editing", "step": "src/main.py"}


def test_database_tool_use_renders_command_and_key():
    """Database tool_use renders as 'cmd key' so the FE shows what
    happened (e.g. 'put tasks/42', 'scan notes/')."""
    raw = [{"role": "assistant", "content": [
        {"type": "tool_use", "name": "database",
         "input": {"command": "put", "key": "tasks/42", "value": {"done": True}}, "id": "X"},
    ]}]
    out = to_ui_messages(raw)
    assert out[0]["parts"][0] == {"type": "step", "id": "X", "tool_name": "Database", "step": "put tasks/42"}


def test_database_scan_renders_with_prefix():
    raw = [{"role": "assistant", "content": [
        {"type": "tool_use", "name": "database",
         "input": {"command": "scan", "prefix": "notes/"}, "id": "X"},
    ]}]
    out = to_ui_messages(raw)
    assert out[0]["parts"][0]["step"] == "scan notes/"


def test_user_message_with_text_blocks_only_keeps_text():
    """A user message with content as list-of-text-blocks (e.g. from _ingest)
    flattens to a string for display."""
    raw = [{"role": "user", "content": [
        {"type": "text", "text": "Look at "},
        {"type": "text", "text": "this image"},
    ]}]
    assert to_ui_messages(raw) == [{"role": "user", "content": "Look at this image"}]


def test_consecutive_assistant_messages_merge_into_one_turn():
    """A turn is several assistant/tool-result round-trips on disk; the UI shows
    one bubble — same as the live stream — so steps don't split across bubbles."""
    raw = [
        {"role": "user", "content": "do stuff"},
        {"role": "assistant", "content": [{"type": "tool_use", "name": "bash", "input": {"command": "ls"}, "id": "1"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "ok"}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "name": "read", "input": {"path": "a.py"}, "id": "2"},
            {"type": "tool_use", "name": "read", "input": {"path": "b.py"}, "id": "3"},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "2", "content": "..."},
                                     {"type": "tool_result", "tool_use_id": "3", "content": "..."}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
    ]
    out = to_ui_messages(raw)
    assert [m["role"] for m in out] == ["user", "assistant"]
    assert [p["type"] for p in out[1]["parts"]] == ["step", "step", "step", "text"]
    assert out[1]["content"] == "Done."
    # A real user message between assistants is NOT merged — that's a new turn.
    out2 = to_ui_messages(raw + [{"role": "user", "content": "more"},
                                 {"role": "assistant", "content": [{"type": "text", "text": "Sure."}]}])
    assert [m["role"] for m in out2] == ["user", "assistant", "user", "assistant"]


def test_internal_messages_are_dropped():
    """Compaction summaries and the output-limit resume prompt are tagged
    `internal` — model scaffolding, never shown to the user."""
    raw = [
        {"role": "user", "internal": True, "content": "This session continues from a previous conversation. ..."},
        {"role": "assistant", "internal": True, "content": "Understood. I have the full context."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "cut off"}]},
        {"role": "user", "internal": True, "content": "Cut off by output limit. Resume — ..."},
        {"role": "assistant", "content": [{"type": "text", "text": "...continued."}]},
    ]
    out = to_ui_messages(raw)
    assert [m["role"] for m in out] == ["user", "assistant"]
    assert out[1]["content"] == "cut off...continued."  # the two halves merged across the dropped resume prompt


# =============================================================================
# Load-time repair (_valid_prefix) — trim trailing corrupted state
# =============================================================================

from cycls.agent.state import _valid_prefix


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

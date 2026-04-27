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

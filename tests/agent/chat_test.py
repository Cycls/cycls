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


def test_errored_tool_use_flagged_for_fe():
    """A tool call whose result errored gets ok=False on its step part — the
    FE uses this to downgrade failed canvas calls from file cards to steps."""
    raw = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "c1", "name": "canvas", "input": {"path": "nope.md"}},
            {"type": "tool_use", "id": "c2", "name": "canvas", "input": {"path": "report.md"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": "Error: nope.md does not exist"},
            {"type": "tool_result", "tool_use_id": "c2", "content": "Opened report.md for the user."},
        ]},
    ]
    parts = to_ui_messages(raw)[0]["parts"]
    assert parts[0]["ok"] is False
    assert "ok" not in parts[1]


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
# normalize — single safety net enforcing provider API pairing invariants
# =============================================================================

from cycls.agent.state import normalize


def test_normalize_empty():
    assert normalize([]) == []


def test_normalize_clean_text_pair_unchanged():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]
    assert normalize(msgs) == msgs


def test_normalize_drops_dangling_assistant_tool_use():
    """Most common corruption: assistant emits tool_use, crash before
    tool_result is persisted. Strip the dangling block — drops the
    assistant message entirely if nothing else remains."""
    msgs = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {"command": "ls"}}
        ]},
    ]
    assert normalize(msgs) == [{"role": "user", "content": "do X"}]


def test_normalize_preserves_complete_tool_pair():
    msgs = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "A", "name": "bash", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "A", "content": "ok"}]},
    ]
    assert normalize(msgs) == msgs


def test_normalize_drops_orphaned_tool_result():
    """User message with tool_result but no preceding assistant tool_use → drop."""
    msgs = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "X", "content": "ghost"}
    ]}]
    assert normalize(msgs) == []


def test_normalize_strips_partial_tool_result_set():
    """Assistant emits two tool_uses, only one tool_result persisted. Drop
    the unpaired tool_use from the assistant; keep the paired one with its
    result."""
    msgs = [
        {"role": "user", "content": "do X and Y"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {}},
            {"type": "tool_use", "id": "B", "name": "read", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "A", "content": "ok"},
        ]},
    ]
    out = normalize(msgs)
    assert len(out) == 3
    assert out[1]["content"] == [{"type": "tool_use", "id": "A", "name": "bash", "input": {}}]
    assert out[2]["content"] == [{"type": "tool_result", "tool_use_id": "A", "content": "ok"}]


def test_normalize_keeps_text_when_tool_use_stripped():
    """Assistant message with text + dangling tool_use → keep the text,
    drop the tool_use. Don't lose the assistant's prose just because
    one block was unpaired."""
    msgs = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Let me check"},
            {"type": "tool_use", "id": "A", "name": "bash", "input": {}},
        ]},
    ]
    assert normalize(msgs) == [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [{"type": "text", "text": "Let me check"}]},
    ]


def test_normalize_preserves_history_drops_dangling_tail():
    """Long chat with valid history, recent turn corrupted. Preserve the
    prefix, drop only the bad tail."""
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "X", "name": "bash", "input": {}}]},
    ]
    assert normalize(msgs) == msgs[:3]


def test_normalize_strips_orphaned_server_tool_use():
    """The exact reproduction of error 7f6bc577: assistant message has a
    web_search server_tool_use without its paired web_search_tool_result
    in the same content list. Anthropic 400s on the next replay. Strip
    the orphaned server_tool_use."""
    msgs = [
        {"role": "user", "content": "search the web"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Searching."},
            {"type": "server_tool_use", "id": "srvtoolu_01",
             "name": "web_search", "input": {"query": "cats"}},
            # missing the web_search_tool_result that Anthropic would have emitted
        ]},
    ]
    out = normalize(msgs)
    assert out == [
        {"role": "user", "content": "search the web"},
        {"role": "assistant", "content": [{"type": "text", "text": "Searching."}]},
    ]


def test_normalize_preserves_paired_server_tool_use():
    msgs = [
        {"role": "user", "content": "search"},
        {"role": "assistant", "content": [
            {"type": "server_tool_use", "id": "srvtoolu_01",
             "name": "web_search", "input": {"query": "cats"}},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_01",
             "content": [{"type": "web_search_result", "url": "...", "title": "..."}]},
            {"type": "text", "text": "Done."},
        ]},
    ]
    assert normalize(msgs) == msgs


def test_normalize_strips_orphaned_server_result():
    """Server-side result block without a matching server_tool_use → drop."""
    msgs = [
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "hi"},
            {"type": "web_search_tool_result", "tool_use_id": "nothing",
             "content": []},
        ]},
    ]
    assert normalize(msgs) == [
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]


def test_normalize_strips_mid_history_corruption():
    """Crucially, normalize is not trailing-only — corruption in the middle
    of a long chat gets caught too. Otherwise it lives forever."""
    msgs = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": [
            {"type": "server_tool_use", "id": "srv_a",
             "name": "web_search", "input": {}},
            # orphan — no result block in same message
            {"type": "text", "text": "first answer"},
        ]},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": [{"type": "text", "text": "second answer"}]},
    ]
    out = normalize(msgs)
    assert out == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": [{"type": "text", "text": "first answer"}]},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": [{"type": "text", "text": "second answer"}]},
    ]


def test_normalize_cascading_drop_takes_user_result_with_it():
    """If stripping leaves the assistant empty (so the assistant message is
    dropped), the next user's tool_result becomes orphaned too — cascade."""
    msgs = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "WRONG", "content": "mismatched"},
        ]},
    ]
    # tool_use A isn't paired (next message's tool_result points to WRONG).
    # Assistant becomes empty → dropped. User's tool_result now has no prior
    # tool_use anywhere → orphaned → dropped.
    assert normalize(msgs) == [{"role": "user", "content": "do X"}]


def test_normalize_mixed_client_and_server_in_one_message():
    """Both kinds of tool blocks in one assistant message: keep paired,
    drop unpaired, independently."""
    msgs = [
        {"role": "user", "content": "do many things"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Working."},
            {"type": "server_tool_use", "id": "srv_a",
             "name": "web_search", "input": {}},
            {"type": "web_search_tool_result", "tool_use_id": "srv_a", "content": []},
            {"type": "server_tool_use", "id": "srv_b",
             "name": "web_search", "input": {}},
            # srv_b has no result → orphan
            {"type": "tool_use", "id": "cli_a", "name": "bash", "input": {}},
            {"type": "tool_use", "id": "cli_b", "name": "bash", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "cli_a", "content": "ok"},
            # cli_b has no result → orphan
        ]},
    ]
    out = normalize(msgs)
    assert out[1]["content"] == [
        {"type": "text", "text": "Working."},
        {"type": "server_tool_use", "id": "srv_a", "name": "web_search", "input": {}},
        {"type": "web_search_tool_result", "tool_use_id": "srv_a", "content": []},
        {"type": "tool_use", "id": "cli_a", "name": "bash", "input": {}},
    ]
    assert out[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "cli_a", "content": "ok"},
    ]


def test_normalize_string_content_passes_through():
    """Plain string user content (no blocks to validate) is untouched."""
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        {"role": "user", "content": "thanks"},
    ]
    assert normalize(msgs) == msgs


def test_normalize_is_idempotent():
    """normalize(normalize(x)) == normalize(x) — the safety net is stable
    under repeated application (matters for the on-load + on-send model)."""
    msgs = [
        {"role": "user", "content": "search"},
        {"role": "assistant", "content": [
            {"type": "server_tool_use", "id": "srv_orphan",
             "name": "web_search", "input": {}},
            {"type": "text", "text": "ans"},
            {"type": "tool_use", "id": "cli_orphan", "name": "bash", "input": {}},
        ]},
    ]
    once = normalize(msgs)
    twice = normalize(once)
    assert once == twice

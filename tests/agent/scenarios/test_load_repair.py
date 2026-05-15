"""End-to-end scenarios for load-time repair (rfc-004 b44248c).

These plant state directly via chat.append_messages, then verify that
chat.load_messages trims trailing corruption AND persists the cleanup.
The conftest.py at tests/ resets the engine pool between tests so each
scenario starts fresh."""
import asyncio
from pathlib import Path

from cycls.agent import sessions as chat
from cycls.app.workspace import workspace_at


def _ws(tmp_path):
    return workspace_at("tenant", tmp_path, base=f"file://{tmp_path}")


def _run(coro):
    return asyncio.run(coro)


def test_orphan_assistant_tool_use_trimmed_and_persisted(tmp_path):
    """The headline reliability win: a chat with a dangling assistant
    tool_use (the typical mid-turn-crash corruption) loads as the clean
    prefix. Second load sees disk-clean state — repair was persisted."""
    ws = _ws(tmp_path)
    cid = "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {"command": "ls"}}
        ]},
    ], 0))

    first = _run(chat.load_messages(ws, cid))
    assert len(first) == 1, f"orphan not trimmed: {first}"
    assert first[0]["content"] == "do X"

    # Second load: disk now matches; repair is a no-op.
    second = _run(chat.load_messages(ws, cid))
    assert second == first, "disk wasn't persisted clean"


def test_clean_history_passes_through_unchanged(tmp_path):
    ws = _ws(tmp_path)
    cid = "test"
    clean = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        {"role": "user", "content": "again"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
    ]
    _run(chat.append_messages(ws, cid, clean, 0))
    loaded = _run(chat.load_messages(ws, cid))
    assert loaded == clean


def test_complete_tool_pair_preserved(tmp_path):
    """(assistant tool_use, user tool_result) is a valid trailing state —
    Anthropic accepts it; repair must NOT trim it."""
    ws = _ws(tmp_path)
    cid = "test"
    msgs = [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "A", "content": "ok"}
        ]},
    ]
    _run(chat.append_messages(ws, cid, msgs, 0))
    loaded = _run(chat.load_messages(ws, cid))
    assert len(loaded) == 3


def test_long_chat_preserves_clean_prefix_drops_corrupted_tail(tmp_path):
    """Long valid history with one corrupted final turn — repair keeps
    the prefix, only trims the dangling assistant. Users keep most of
    their chat instead of nuking the whole thing."""
    ws = _ws(tmp_path)
    cid = "test"
    valid = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": [{"type": "text", "text": "got it"}]},
        {"role": "user", "content": "third"},
    ]
    corrupted_tail = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "X", "name": "bash", "input": {}}
        ]},
    ]
    _run(chat.append_messages(ws, cid, valid + corrupted_tail, 0))
    loaded = _run(chat.load_messages(ws, cid))
    assert len(loaded) == 5  # valid prefix preserved, corrupted tail trimmed
    assert loaded[-1]["content"] == "third"


def test_partial_tool_result_set_trimmed_to_clean(tmp_path):
    """Two tool_uses, one tool_result missing — Anthropic rejects the
    pair (must be complete). Repair drops the partial pair entirely,
    trimming back to the user message that triggered the turn."""
    ws = _ws(tmp_path)
    cid = "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "do X and Y"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {}},
            {"type": "tool_use", "id": "B", "name": "read", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "A", "content": "ok"},
            # missing tool_use_id="B"
        ]},
    ], 0))
    loaded = _run(chat.load_messages(ws, cid))
    assert len(loaded) == 1
    assert loaded[0]["content"] == "do X and Y"


def test_empty_chat_no_crash(tmp_path):
    ws = _ws(tmp_path)
    loaded = _run(chat.load_messages(ws, "nonexistent"))
    assert loaded == []


def test_attachment_sidecar_survives_repair(tmp_path):
    """Attachments are stored as a sidecar on user messages. Repair
    operates on content shape, must not strip the sidecar from clean
    user messages — that's the live/refetch divergence we just fixed."""
    ws = _ws(tmp_path)
    cid = "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": [{"type": "text", "text": "look"}],
         "attachments": [{"name": "pic.jpg", "path": "attachments/pic.jpg",
                          "type": "image/jpeg", "size": 1234}]},
        {"role": "assistant", "content": [{"type": "text", "text": "I see"}]},
    ], 0))
    loaded = _run(chat.load_messages(ws, cid))
    assert len(loaded) == 2
    assert loaded[0].get("attachments") == [
        {"name": "pic.jpg", "path": "attachments/pic.jpg",
         "type": "image/jpeg", "size": 1234}
    ]

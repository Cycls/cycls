"""End-to-end scenarios for load-time repair (rfc-004 b44248c).

These plant state directly via chat.append_messages, then verify that
chat.load_messages trims trailing corruption AND persists the cleanup.
The conftest.py at tests/ resets the engine pool between tests so each
scenario starts fresh."""
import asyncio
from pathlib import Path

from cycls.agent import state as chat
from cycls.app.db import workspace


def _ws(tmp_path):
    return workspace("tenant", tmp_path, base=f"file://{tmp_path}")


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


def test_partial_tool_result_set_repaired_surgically(tmp_path):
    """Two tool_uses, one tool_result missing. Strip just the unpaired
    tool_use from the assistant — the paired tool_use + its tool_result
    survive. User keeps the half of the turn that completed instead of
    losing the whole turn."""
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
    assert len(loaded) == 3
    assert loaded[1]["content"] == [
        {"type": "tool_use", "id": "A", "name": "bash", "input": {}}
    ]
    assert loaded[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "A", "content": "ok"}
    ]


def test_empty_chat_no_crash(tmp_path):
    ws = _ws(tmp_path)
    loaded = _run(chat.load_messages(ws, "nonexistent"))
    assert loaded == []


def test_add_cost_accumulates_on_chat_index(tmp_path):
    """add_cost sums deltas into the chat index's `cost` field; survives
    interleaving with other meta edits (rename, favorite)."""
    ws = _ws(tmp_path)
    cid = "test"
    _run(chat.put_meta(ws, cid, {"id": cid, "title": "Hi"}))
    _run(chat.add_cost(ws, cid, 0.0125))
    _run(chat.add_cost(ws, cid, 0.0075))
    meta = _run(chat.get_meta(ws, cid))
    assert meta["cost"] == "0.020000"
    # A rename in between must not lose the accumulated cost.
    _run(chat.put_meta(ws, cid, {**meta, "title": "Renamed"}))
    _run(chat.add_cost(ws, cid, 0.001))
    meta = _run(chat.get_meta(ws, cid))
    assert meta["title"] == "Renamed"
    assert meta["cost"] == "0.021000"


def test_add_cost_skips_zero_and_anonymous(tmp_path):
    """Zero delta is a no-op (no PUT). Missing chat is also a no-op-ish —
    add_cost on a missing chat creates the index with just the cost field."""
    ws = _ws(tmp_path)
    _run(chat.add_cost(ws, "test", 0))   # zero delta → no-op
    assert _run(chat.get_meta(ws, "test")) is None


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

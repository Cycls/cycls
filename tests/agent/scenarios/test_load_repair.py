"""End-to-end scenarios for load-time repair (rfc-004 b44248c).

These plant state directly via chat.append_messages, then verify that
chat.load_messages trims trailing corruption. The repair is in memory for
readers and persisted only for `persist=True`, the session's own load — see
the "Readers do not repair" section of docs/notes/runs.md.

The conftest.py at tests/ resets the engine pool between tests so each
scenario starts fresh."""
import asyncio
from pathlib import Path

from cycls._agent import state as chat
from cycls._app.db import workspace


def _ws(tmp_path):
    return workspace("tenant", tmp_path, base=f"file://{tmp_path}")


def _run(coro):
    return asyncio.run(coro)


def test_orphan_assistant_tool_use_trimmed_and_persisted(tmp_path):
    """The headline reliability win: a chat with a dangling assistant
    tool_use (the typical mid-turn-crash corruption) loads as the clean
    prefix. With `persist`, disk catches up too."""
    ws = _ws(tmp_path)
    cid = "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {"command": "ls"}}
        ]},
    ], 0))

    first = _run(chat.load_messages(ws, cid, persist=True))
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


# ---- readers do not repair (docs/notes/runs.md) ----

def _dangling(ws, cid):
    """A chat whose last turn is an assistant tool_use with no result yet —
    what disk looks like while a run is mid-tool-batch."""
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {"command": "ls"}}
        ]},
    ], 0))


def test_a_reader_normalizes_in_memory_and_leaves_disk_alone(tmp_path):
    ws, cid = _ws(tmp_path), "test"
    _dangling(ws, cid)
    before = _turn_keys(ws, cid)

    loaded = _run(chat.load_messages(ws, cid))
    assert len(loaded) == 1, "the caller still gets a provider-valid view"
    assert _turn_keys(ws, cid) == before, "a reader rewrote the turn files"


def test_the_writer_repairs_so_its_index_matches_disk(tmp_path):
    """`Session.__init__` sets `_saved = len(messages)` and appends at it, so the
    one caller that repairs must be the one whose indices have to agree."""
    ws, cid = _ws(tmp_path), "test"
    _dangling(ws, cid)

    messages = _run(chat.load_messages(ws, cid, persist=True))
    keys = _turn_keys(ws, cid)
    assert [k.split("/")[-1] for k in keys] == ["000000"], keys
    assert chat.Session(ws, cid, messages)._saved == len(keys)


def test_a_reader_cannot_move_a_live_sessions_slots(tmp_path):
    """The production failure, in miniature (super a95500f1, haseef 48b79700):
    a run holds turn 2 as its next index while its tool_use is unpaired on disk;
    a reader normalizes that turn away and renumbers; the run's next append then
    lands in a slot that means something else, leaving a hole."""
    ws, cid = _ws(tmp_path), "test"
    _dangling(ws, cid)
    # The run as it stands mid-batch: both turns written, so its next index is 2.
    live = chat.Session(ws, cid, [
        {"role": "user", "content": "do X"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {"command": "ls"}}]},
    ])
    assert live._saved == 2 == len(_turn_keys(ws, cid))

    _run(chat.load_messages(ws, cid))          # a poll lands mid-batch

    live.messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "A", "content": "ok"}]})
    _run(live.checkpoint())

    assert [k.split("/")[-1] for k in _turn_keys(ws, cid)] == \
        ["000000", "000001", "000002"], "the reader moved the run's slots"
    assert len(_run(chat.load_messages(ws, cid))) == 3


# ---- truncate_last_exchange (backs `regenerate`) ----

def _turn_keys(ws, cid):
    from cycls._app.db import DB
    async def go():
        return sorted([k async for k, _ in DB(ws).scan(glob=f"chat/{cid}/[0-9]*")])
    return _run(go())


def test_truncate_drops_last_user_turn_and_everything_after(tmp_path):
    ws, cid = _ws(tmp_path), "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "one"}]},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": [{"type": "text", "text": "two"}]},
    ], 0))
    removed = _run(chat.truncate_last_exchange(ws, cid))
    assert removed == "second"
    left = _run(chat.load_messages(ws, cid))
    assert [m["content"] for m in left] == ["first", [{"type": "text", "text": "one"}]]


def test_truncate_renumbers_so_the_next_append_cannot_collide(tmp_path):
    """The corruption this guards: turn files are `{turn:06d}` and the session
    appends at `len(messages)`. A delete that left a numbering gap would make
    the next append overwrite a live turn — so the rewrite must be contiguous."""
    ws, cid = _ws(tmp_path), "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": [{"type": "text", "text": "1"}]},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": [{"type": "text", "text": "2"}]},
    ], 0))
    _run(chat.truncate_last_exchange(ws, cid))

    keys = _turn_keys(ws, cid)
    assert [k.split("/")[-1] for k in keys] == ["000000", "000001"], keys

    # Replay what the session does next: append at len(messages).
    left = _run(chat.load_messages(ws, cid))
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "b again"},
        {"role": "assistant", "content": [{"type": "text", "text": "3"}]},
    ], len(left)))
    final = _run(chat.load_messages(ws, cid))
    assert [m["content"] for m in final] == [
        "a", [{"type": "text", "text": "1"}],
        "b again", [{"type": "text", "text": "3"}],
    ], "a stale turn survived the truncate"


def test_truncate_shrinks_a_stale_compaction_marker(tmp_path):
    """`first_kept` is an index. Session clamps on load, but the marker on disk
    has to shrink too — a value left past the new length would re-clamp beyond
    the turns appended afterwards and hide them from the model's context."""
    ws, cid = _ws(tmp_path), "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": [{"type": "text", "text": "1"}]},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": [{"type": "text", "text": "2"}]},
    ], 0))
    _run(chat.put_compaction(ws, cid, {"summary": "earlier work", "first_kept": 3}))
    _run(chat.truncate_last_exchange(ws, cid))
    marker = _run(chat.get_compaction(ws, cid))
    assert marker["first_kept"] == 2, marker
    assert marker["summary"] == "earlier work"

    # And the model's view still contains the turn sent after the truncate.
    left = _run(chat.load_messages(ws, cid))
    _run(chat.append_messages(ws, cid, [{"role": "user", "content": "b again"}], len(left)))
    reloaded = _run(chat.load_messages(ws, cid))
    session = chat.Session(ws, cid, reloaded, summary=marker["summary"],
                           first_kept=int(marker["first_kept"]))
    assert {"role": "user", "content": "b again"} in session.context()


def test_truncate_keeps_a_marker_that_still_fits(tmp_path):
    ws, cid = _ws(tmp_path), "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": [{"type": "text", "text": "1"}]},
        {"role": "user", "content": "b"},
    ], 0))
    _run(chat.put_compaction(ws, cid, {"summary": "s", "first_kept": 1}))
    _run(chat.truncate_last_exchange(ws, cid))
    assert _run(chat.get_compaction(ws, cid))["first_kept"] == 1


def test_truncate_cuts_at_a_plain_user_turn_not_a_tool_result(tmp_path):
    """A tool-result batch is a user-role message. Cutting there would strand
    the assistant `tool_use` it answers; the cut has to land on a real turn."""
    ws, cid = _ws(tmp_path), "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "run it"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "A", "name": "bash", "input": {"command": "ls"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "A", "content": "out"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
    ], 0))
    removed = _run(chat.truncate_last_exchange(ws, cid))
    assert removed == "run it"
    assert _run(chat.load_messages(ws, cid)) == []


def test_truncate_on_a_chat_with_no_user_turn_is_a_noop(tmp_path):
    ws, cid = _ws(tmp_path), "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ], 0))
    assert _run(chat.truncate_last_exchange(ws, cid)) is None
    assert len(_run(chat.load_messages(ws, cid))) == 1


def test_truncate_ignores_internal_scaffolding_turns(tmp_path):
    """The output-limit resume prompt is a user-role message the harness wrote.
    Regenerate must rewind to the user's own last turn, not to that."""
    ws, cid = _ws(tmp_path), "test"
    _run(chat.append_messages(ws, cid, [
        {"role": "user", "content": "write it"},
        {"role": "assistant", "content": [{"type": "text", "text": "part one"}]},
        {"role": "user", "internal": True, "content": "Continue."},
        {"role": "assistant", "content": [{"type": "text", "text": "part two"}]},
    ], 0))
    assert _run(chat.truncate_last_exchange(ws, cid)) == "write it"
    assert _run(chat.load_messages(ws, cid)) == []

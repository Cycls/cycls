"""End-to-end scenarios for the DataBase tool — real engine roundtrip,
isolated from the framework chat DB.

`_exec_database` always returns a string (Anthropic's tool_result.content
rejects raw dicts/lists), so get/scan results come back JSON-encoded.

The conftest.py at tests/ resets the engine pool between tests so each
scenario starts fresh.
"""
import asyncio, json

from cycls.agent.tools import _exec_database
from cycls.app.workspace import workspace, DB


def _ws(tmp_path):
    return workspace("tenant", tmp_path, base=f"file://{tmp_path}")


def _run(coro):
    return asyncio.run(coro)


def test_put_then_get_roundtrips_value(tmp_path):
    ws = _ws(tmp_path)
    _run(_exec_database({"command": "put", "key": "k1", "value": {"x": 42}}, ws))
    out = _run(_exec_database({"command": "get", "key": "k1"}, ws))
    assert json.loads(out) == {"x": 42}


def test_get_missing_key_returns_error_string(tmp_path):
    ws = _ws(tmp_path)
    out = _run(_exec_database({"command": "get", "key": "nope"}, ws))
    assert isinstance(out, str) and "not found" in out


def test_delete_removes_key(tmp_path):
    ws = _ws(tmp_path)
    _run(_exec_database({"command": "put", "key": "k1", "value": "v1"}, ws))
    _run(_exec_database({"command": "delete", "key": "k1"}, ws))
    out = _run(_exec_database({"command": "get", "key": "k1"}, ws))
    assert isinstance(out, str) and "not found" in out


def test_scan_returns_pairs_under_prefix(tmp_path):
    ws = _ws(tmp_path)
    _run(_exec_database({"command": "put", "key": "tasks/1", "value": "a"}, ws))
    _run(_exec_database({"command": "put", "key": "tasks/2", "value": "b"}, ws))
    _run(_exec_database({"command": "put", "key": "notes/x", "value": "c"}, ws))
    out = _run(_exec_database({"command": "scan", "prefix": "tasks/"}, ws))
    pairs = json.loads(out)
    keys = {p["key"]: p["value"] for p in pairs}
    assert keys == {"tasks/1": "a", "tasks/2": "b"}


def test_scan_empty_prefix_lists_all(tmp_path):
    ws = _ws(tmp_path)
    _run(_exec_database({"command": "put", "key": "a", "value": 1}, ws))
    _run(_exec_database({"command": "put", "key": "b", "value": 2}, ws))
    out = _run(_exec_database({"command": "scan", "prefix": ""}, ws))
    pairs = json.loads(out)
    assert {p["key"] for p in pairs} == {"a", "b"}


def test_scan_no_matches_returns_message(tmp_path):
    ws = _ws(tmp_path)
    out = _run(_exec_database({"command": "scan", "prefix": "missing/"}, ws))
    assert isinstance(out, str) and "missing/" in out


def test_unknown_command_returns_error(tmp_path):
    ws = _ws(tmp_path)
    out = _run(_exec_database({"command": "explode"}, ws))
    assert isinstance(out, str) and "unknown" in out.lower()


def test_database_isolated_from_chat_db(tmp_path):
    """Hard isolation: writing to the agent DB must not affect the chat DB
    (different storage tree at .database/ vs .db/)."""
    ws = _ws(tmp_path)
    # Write via agent tool
    _run(_exec_database({"command": "put", "key": "shared", "value": "agent-only"}, ws))

    # Check the chat DB doesn't see it (chat DB uses default slot ".db")
    chat_db = DB(ws)
    val = _run(chat_db.get("shared"))
    assert val is None, "agent write leaked into chat DB"

    # Conversely: write to chat DB, agent shouldn't see it
    _run(chat_db.put("private", "chat-only"))
    out = _run(_exec_database({"command": "get", "key": "private"}, ws))
    assert isinstance(out, str) and "not found" in out


def test_database_value_can_be_complex_json(tmp_path):
    ws = _ws(tmp_path)
    val = {"list": [1, 2, 3], "nested": {"a": True}, "s": "string"}
    _run(_exec_database({"command": "put", "key": "k", "value": val}, ws))
    out = _run(_exec_database({"command": "get", "key": "k"}, ws))
    assert json.loads(out) == val


def test_database_rejects_path_traversal_keys(tmp_path):
    ws = _ws(tmp_path)
    for bad in ("../escape", "foo/../bar", "/abs", "a//b", ""):
        out = _run(_exec_database({"command": "put", "key": bad, "value": "x"}, ws))
        assert "Error:" in out, f"expected rejection for key={bad!r}, got {out!r}"


def test_database_scan_truncates_at_limit(tmp_path):
    ws = _ws(tmp_path)
    for i in range(5):
        _run(_exec_database({"command": "put", "key": f"item/{i}", "value": i}, ws))
    out = _run(_exec_database({"command": "scan", "prefix": "item/", "limit": 2}, ws))
    head, _, tail = out.partition("\n")
    assert len(json.loads(head)) == 2
    assert "truncated" in tail


def test_db_delete_rejects_dangerous_targets(tmp_path):
    """DB.delete is polymorphic (trailing slash = subtree). The agent tool's
    key validator already blocks dangerous shapes, but DB.delete is also
    used from framework code (sessions.py) and must defend itself."""
    from cycls.app.workspace import DB
    ws = _ws(tmp_path)
    async def t():
        db = DB(ws)
        for bad in ("", "/", "/abs", "../escape", "foo/../bar"):
            try:
                await db.delete(bad)
                assert False, f"expected ValueError for {bad!r}"
            except ValueError: pass
    _run(t())


def test_db_delete_subtree_via_trailing_slash(tmp_path):
    """db.delete('prefix/') wipes the subtree; db.delete('key') deletes the leaf."""
    from cycls.app.workspace import DB
    ws = _ws(tmp_path)
    async def t():
        db = DB(ws)
        for k in ("notes/a", "notes/b", "notes/sub/c", "tasks/keep"):
            await db.put(k, k)
        await db.delete("notes/")
        remaining = sorted([k async for k, _ in db.items()])
        assert remaining == ["tasks/keep"]
    _run(t())

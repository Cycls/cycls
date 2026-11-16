"""End-to-end scenarios for the DataBase tool — real engine roundtrip,
isolated from the framework chat DB.

`_exec_database` returns a string (Anthropic's tool_result.content
rejects raw dicts/lists), so get/scan results come back JSON-encoded. A write
to an app's data is the one exception: `{"_model": <the string>, "_ui": …}`,
the harness's two channels, so an app open on it hears at once.

The conftest.py at tests/ resets the engine pool between tests so each
scenario starts fresh.
"""
import asyncio, json

from cycls._agent.tools import _exec_database
from cycls._app.db import workspace, DB


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
    from cycls._app.db import DB
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
    from cycls._app.db import DB
    ws = _ws(tmp_path)
    async def t():
        db = DB(ws)
        for k in ("notes/a", "notes/b", "notes/sub/c", "tasks/keep"):
            await db.put(k, k)
        await db.delete("notes/")
        remaining = sorted([k async for k, _ in db.items()])
        assert remaining == ["tasks/keep"]
    _run(t())


def test_ws_mode_kv_lands_inside_workspace(tmp_path):
    """Multi-workspace mode: the agent KV re-derivation keeps the ws segment,
    so the `.database` slot sits inside the workspace subtree, per-user."""
    ws = workspace("org:u1", tmp_path, base=f"file://{tmp_path}", ws="u-u1")
    _run(_exec_database({"command": "put", "key": "k1", "value": 1}, ws))
    assert (tmp_path / "org" / "ws" / "u-u1" / ".database" / "u1" / "k1.json").exists()
    out = _run(_exec_database({"command": "get", "key": "k1"}, ws))
    assert json.loads(out) == 1


# ---- apps/ routes to the workspace app shelf (docs/notes/apps.md) ----

def _ws_user(tmp_path):
    return workspace("tenant:alice", tmp_path, base=f"file://{tmp_path}", ws="t-eng")


def test_app_key_lands_in_the_apps_slot_not_the_agent_db(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_exec_database({"command": "put", "key": "apps/standup/config", "value": {"days": "mon"}}, ws))
    shelf = DB(workspace("tenant", tmp_path, base=f"file://{tmp_path}", slot=".apps", ws="t-eng"))
    assert _run(shelf.get("standup/config")) == {"days": "mon"}


def test_app_shelf_is_shared_across_members(tmp_path):
    a = workspace("tenant:alice", tmp_path, base=f"file://{tmp_path}", ws="t-eng")
    b = workspace("tenant:bob", tmp_path, base=f"file://{tmp_path}", ws="t-eng")
    _run(_exec_database({"command": "put", "key": "apps/standup/entries/1", "value": "hi"}, a))
    out = _run(_exec_database({"command": "get", "key": "apps/standup/entries/1"}, b))
    assert json.loads(out) == "hi"


def test_agent_db_stays_per_user(tmp_path):
    a = workspace("tenant:alice", tmp_path, base=f"file://{tmp_path}", ws="t-eng")
    b = workspace("tenant:bob", tmp_path, base=f"file://{tmp_path}", ws="t-eng")
    _run(_exec_database({"command": "put", "key": "note", "value": "mine"}, a))
    assert "not found" in _run(_exec_database({"command": "get", "key": "note"}, b))


def test_u_is_reserved_under_a_slug(tmp_path):
    ws = _ws_user(tmp_path)
    for key in ("apps/standup/u/bob/draft", "apps/standup/u"):
        out = _run(_exec_database({"command": "put", "key": key, "value": "x"}, ws))
        assert out.startswith("Error:") and "reserved" in out


def test_u_is_only_reserved_directly_under_the_slug(tmp_path):
    ws = _ws_user(tmp_path)
    out = _run(_exec_database({"command": "put", "key": "apps/standup/notes/u/x", "value": 1}, ws))
    assert out["_model"].startswith("Stored")


def test_scan_hides_members_private_rows_and_reprefixes(tmp_path):
    ws = _ws_user(tmp_path)
    shelf = DB(workspace("tenant", tmp_path, base=f"file://{tmp_path}", slot=".apps", ws="t-eng"))
    _run(shelf.put("standup/entries/1", "shared"))
    _run(shelf.put("standup/u/bob/draft", "private"))
    out = _run(_exec_database({"command": "scan", "prefix": "apps/standup/"}, ws))
    assert json.loads(out) == [{"key": "apps/standup/entries/1", "value": "shared"}]


def test_a_bare_slug_cannot_be_deleted_from_the_tool(tmp_path):
    ws = _ws_user(tmp_path)
    out = _run(_exec_database({"command": "delete", "key": "apps/standup/"}, ws))
    assert out.startswith("Error:")


def test_app_key_needs_a_slug(tmp_path):
    ws = _ws_user(tmp_path)
    assert _run(_exec_database({"command": "get", "key": "apps/"}, ws)).startswith("Error:")


def test_an_admin_only_app_takes_the_tools_writes_from_admins_only(tmp_path):
    """The /apps route's `write: admin` rule holds for the tool too, now that it is the only way in."""
    from types import SimpleNamespace
    from cycls._agent import state
    orgdb = state.org_db("tenant", tmp_path, f"file://{tmp_path}")
    _run(orgdb.put("workspaces/t-eng", {"id": "t-eng", "type": "team"}))
    _run(orgdb.put("members/t-eng/alice", {"role": "editor"}))
    _run(orgdb.put("members/t-eng/bob", {"role": "admin"}))
    ws = _ws_user(tmp_path)
    (ws.root / "apps" / "standup").mkdir(parents=True)
    (ws.root / "apps" / "standup" / "app.json").write_text('{"write": "admin"}')
    alice, bob = (SimpleNamespace(id=u, org_id="tenant", org_role="member") for u in ("alice", "bob"))
    put = {"command": "put", "key": "apps/standup/config", "value": 1}
    assert "only workspace admins" in _run(_exec_database(put, ws, alice))
    assert "only workspace admins" in _run(_exec_database({"command": "delete", "key": "apps/standup/config"}, ws, alice))
    assert "only workspace admins" in _run(_exec_database(put, ws))   # no person, no admin
    assert _run(_exec_database(put, ws, bob))["_model"].startswith("Stored")
    assert json.loads(_run(_exec_database({"command": "get", "key": "apps/standup/config"}, ws, alice))) == 1
    assert _run(_exec_database({"command": "put", "key": "note", "value": 1}, ws, alice)).startswith("Stored")



# ---- an open app hears the agent's writes (docs/notes/apps.md, "Keeping an open app in step") ----

def test_an_app_write_tells_the_open_app_which_key_and_its_new_version(tmp_path):
    ws = _ws_user(tmp_path)
    out = _run(_exec_database({"command": "put", "key": "apps/standup/entries/1", "value": "hi"}, ws))
    assert out["_model"] == "Stored 'apps/standup/entries/1'"
    ui = out["_ui"]
    assert ui["type"] == "ui" and ui["action"] == "app_data"
    assert (ui["slug"], ui["key"]) == ("standup", "entries/1")
    shelf = DB(workspace("tenant", tmp_path, base=f"file://{tmp_path}", slot=".apps", ws="t-eng"))
    # the version the app's own check will read, so it does not count this change twice
    assert ui["version"] == _run(shelf.get_gen("standup/entries/1"))[1]
    assert "deleted" not in ui


def test_an_app_delete_says_it_was_a_delete(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_exec_database({"command": "put", "key": "apps/standup/entries/1", "value": "hi"}, ws))
    out = _run(_exec_database({"command": "delete", "key": "apps/standup/entries/1"}, ws))
    assert out["_model"] == "Deleted 'apps/standup/entries/1'"
    assert out["_ui"]["deleted"] is True and out["_ui"]["key"] == "entries/1"


def test_a_subtree_delete_names_no_key_so_the_app_reads_everything(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_exec_database({"command": "put", "key": "apps/standup/entries/1", "value": "hi"}, ws))
    out = _run(_exec_database({"command": "delete", "key": "apps/standup/entries/"}, ws))
    assert out["_ui"] == {"type": "ui", "action": "app_data", "slug": "standup"}


def test_the_agents_own_keys_and_reads_stay_plain_strings(tmp_path):
    ws = _ws_user(tmp_path)
    assert _run(_exec_database({"command": "put", "key": "note", "value": 1}, ws)) == "Stored 'note'"
    assert _run(_exec_database({"command": "delete", "key": "note"}, ws)) == "Deleted 'note'"
    _run(_exec_database({"command": "put", "key": "apps/standup/a", "value": 1}, ws))
    assert isinstance(_run(_exec_database({"command": "get", "key": "apps/standup/a"}, ws)), str)
    assert isinstance(_run(_exec_database({"command": "scan", "prefix": "apps/standup/"}, ws)), str)


def test_a_put_returns_the_version_a_read_and_a_listing_see(tmp_path):
    db = DB(workspace("tenant", tmp_path, base=f"file://{tmp_path}", slot=".apps"))
    v1 = _run(db.put("app/a", {"n": 1}))
    assert v1 and _run(db.get_gen("app/a"))[1] == v1
    v2 = _run(db.put("app/a", {"n": 2}))
    assert v2 != v1
    _run(db.put("app/b", 1))
    _run(db.put("other/c", 1))
    assert _run(db.versions(prefix="app/")) == {"app/a": v2, "app/b": _run(db.get_gen("app/b"))[1]}


# ---- the agent cannot write over what someone changed in the app (docs/notes/apps.md) ----

def _shelf(tmp_path):
    return DB(workspace("tenant", tmp_path, base=f"file://{tmp_path}", slot=".apps", ws="t-eng"))


def test_a_put_after_a_get_lands_and_a_second_put_needs_no_second_get(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_shelf(tmp_path).put("tasks/list", [1]))
    assert json.loads(_run(_exec_database({"command": "get", "key": "apps/tasks/list"}, ws, chat="c1"))) == [1]
    assert _run(_exec_database({"command": "put", "key": "apps/tasks/list", "value": [1, 2]}, ws, chat="c1"))["_model"].startswith("Stored")
    assert _run(_exec_database({"command": "put", "key": "apps/tasks/list", "value": [1, 2, 3]}, ws, chat="c1"))["_model"].startswith("Stored")
    assert _run(_shelf(tmp_path).get("tasks/list")) == [1, 2, 3]


def test_a_put_over_a_change_made_in_the_app_since_the_get_is_refused(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_shelf(tmp_path).put("tasks/list", [1]))
    _run(_exec_database({"command": "get", "key": "apps/tasks/list"}, ws, chat="c1"))
    _run(_shelf(tmp_path).put("tasks/list", [1, "added in the app"]))   # a teammate, meanwhile
    out = _run(_exec_database({"command": "put", "key": "apps/tasks/list", "value": [1, "from the agent"]}, ws, chat="c1"))
    assert isinstance(out, str) and out.startswith("Error:") and "changed since you read it" in out
    assert _run(_shelf(tmp_path).get("tasks/list")) == [1, "added in the app"]   # nothing lost
    # read again, apply the change to what is there: it lands
    cur = json.loads(_run(_exec_database({"command": "get", "key": "apps/tasks/list"}, ws, chat="c1")))
    _run(_exec_database({"command": "put", "key": "apps/tasks/list", "value": cur + ["from the agent"]}, ws, chat="c1"))
    assert _run(_shelf(tmp_path).get("tasks/list")) == [1, "added in the app", "from the agent"]


def test_a_put_of_data_never_read_in_this_conversation_is_refused(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_shelf(tmp_path).put("tasks/list", ["theirs"]))
    out = _run(_exec_database({"command": "put", "key": "apps/tasks/list", "value": ["from memory"]}, ws, chat="c1"))
    assert out.startswith("Error:") and "not read in this conversation" in out
    # a read in another conversation does not count for this one
    _run(_exec_database({"command": "get", "key": "apps/tasks/list"}, ws, chat="other"))
    assert _run(_exec_database({"command": "put", "key": "apps/tasks/list", "value": ["x"]}, ws, chat="c1")).startswith("Error:")
    assert _run(_shelf(tmp_path).get("tasks/list")) == ["theirs"]


def test_a_new_key_needs_no_read_but_is_not_created_twice(tmp_path):
    ws = _ws_user(tmp_path)
    assert _run(_exec_database({"command": "put", "key": "apps/tasks/new", "value": 1}, ws, chat="c1"))["_model"].startswith("Stored")
    # read as absent, then someone creates it first: the create is refused
    _run(_exec_database({"command": "get", "key": "apps/tasks/other"}, ws, chat="c1"))
    _run(_shelf(tmp_path).put("tasks/other", "theirs"))
    out = _run(_exec_database({"command": "put", "key": "apps/tasks/other", "value": "mine"}, ws, chat="c1"))
    assert out.startswith("Error:") and _run(_shelf(tmp_path).get("tasks/other")) == "theirs"


def test_a_scan_counts_as_reading_what_it_returned(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_shelf(tmp_path).put("tasks/a", 1))
    _run(_shelf(tmp_path).put("tasks/b", 2))
    _run(_exec_database({"command": "scan", "prefix": "apps/tasks/"}, ws, chat="c1"))
    assert _run(_exec_database({"command": "put", "key": "apps/tasks/a", "value": 10}, ws, chat="c1"))["_model"].startswith("Stored")
    _run(_shelf(tmp_path).put("tasks/b", 20))   # changed after the scan
    assert _run(_exec_database({"command": "put", "key": "apps/tasks/b", "value": 3}, ws, chat="c1")).startswith("Error:")


def test_a_delete_needs_the_value_read_and_unchanged(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_shelf(tmp_path).put("tasks/a", 1))
    out = _run(_exec_database({"command": "delete", "key": "apps/tasks/a"}, ws, chat="c1"))
    assert out.startswith("Error:") and "Nothing was deleted" in out
    _run(_exec_database({"command": "get", "key": "apps/tasks/a"}, ws, chat="c1"))
    _run(_shelf(tmp_path).put("tasks/a", 2))
    assert _run(_exec_database({"command": "delete", "key": "apps/tasks/a"}, ws, chat="c1")).startswith("Error:")
    _run(_exec_database({"command": "get", "key": "apps/tasks/a"}, ws, chat="c1"))
    assert _run(_exec_database({"command": "delete", "key": "apps/tasks/a"}, ws, chat="c1"))["_model"].startswith("Deleted")
    assert _run(_shelf(tmp_path).get("tasks/a")) is None


def test_the_agents_own_memory_is_not_checked(tmp_path):
    ws = _ws_user(tmp_path)
    _run(_exec_database({"command": "put", "key": "note", "value": 1}, ws, chat="c1"))
    assert _run(_exec_database({"command": "put", "key": "note", "value": 2}, ws, chat="c2")) == "Stored 'note'"


def test_the_agents_write_to_an_app_carries_its_person_and_name_and_reaches_the_teams_record(tmp_path):
    from cycls._agent import activity, state
    activity._app_seen.clear()
    ws = _ws_user(tmp_path)
    activity.ORIGIN.set({"agent": "super", "chat": "c1"})
    try:
        _run(_exec_database({"command": "put", "key": "apps/tasks/a", "value": 1}, ws, chat="c1"))
    finally:
        activity.ORIGIN.set({})
    [(_, meta)] = _run(_shelf(tmp_path).versions(prefix="tasks/", meta=True)).values()
    assert (meta["by"], meta["agent"]) == ("alice", "super") and meta["at"]
    assert _run(_shelf(tmp_path).get("tasks/a")) == 1   # the value is what was written, nothing added
    [row] = _run(activity.audit_page(state.org_db("tenant", tmp_path, f"file://{tmp_path}"), ws))[0]
    assert (row["action"], row["target"], row["agent"], row["by"]["id"]) == ("app_data", "apps/tasks", "super", "alice")


def test_a_list_sent_as_text_is_stored_as_the_list(tmp_path):
    """Seen on super-dev 2026-11-11: the model sent the tasks as a JSON string, the app got text and stopped."""
    ws = _ws_user(tmp_path)
    _run(_exec_database({"command": "put", "key": "apps/tasks/tasks", "value": '[{"id": 1}]'}, ws, chat="c1"))
    assert _run(_shelf(tmp_path).get("tasks/tasks")) == [{"id": 1}]
    _run(_exec_database({"command": "put", "key": "note", "value": '{"a": 1}'}, ws))
    _run(_exec_database({"command": "put", "key": "plain", "value": "[not json"}, ws))
    assert json.loads(_run(_exec_database({"command": "get", "key": "note"}, ws))) == {"a": 1}
    assert json.loads(_run(_exec_database({"command": "get", "key": "plain"}, ws))) == "[not json"

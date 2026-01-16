"""Tests for the state module."""

import os
import tempfile
import pytest
from cycls.state import State, KV, SQL, FS, connect


@pytest.fixture
def db_conn():
    """Create a temporary SQLite connection."""
    import sqlite3
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    conn = sqlite3.connect(db_path, check_same_thread=False)
    yield conn
    conn.close()
    os.unlink(db_path)


@pytest.fixture
def state(db_conn):
    """Create a State instance."""
    return State(db_conn, user_id="test_user")


class TestKV:
    def test_set_get(self, state):
        state.kv.set("key1", "value1")
        assert state.kv.get("key1") == "value1"

    def test_get_default(self, state):
        assert state.kv.get("nonexistent") is None
        assert state.kv.get("nonexistent", "default") == "default"

    def test_set_complex_value(self, state):
        data = {"name": "test", "count": 42, "items": [1, 2, 3]}
        state.kv.set("complex", data)
        assert state.kv.get("complex") == data

    def test_delete(self, state):
        state.kv.set("to_delete", "value")
        assert state.kv.exists("to_delete")
        result = state.kv.delete("to_delete")
        assert result is True
        assert not state.kv.exists("to_delete")

    def test_delete_nonexistent(self, state):
        result = state.kv.delete("nonexistent")
        assert result is False

    def test_list_prefix(self, state):
        state.kv.set("user:1", "alice")
        state.kv.set("user:2", "bob")
        state.kv.set("item:1", "widget")

        users = state.kv.list("user:")
        assert set(users) == {"user:1", "user:2"}

    def test_incr(self, state):
        assert state.kv.incr("counter") == 1
        assert state.kv.incr("counter") == 2
        assert state.kv.incr("counter", 5) == 7

    def test_incr_float(self, state):
        state.kv.set("float_val", 1.5)
        assert state.kv.incr("float_val", 0.5) == 2.0

    def test_exists(self, state):
        assert not state.kv.exists("key")
        state.kv.set("key", "value")
        assert state.kv.exists("key")

    def test_keys(self, state):
        state.kv.set("a", 1)
        state.kv.set("b", 2)
        keys = state.kv.keys()
        assert set(keys) == {"a", "b"}

    def test_clear(self, state):
        state.kv.set("a", 1)
        state.kv.set("b", 2)
        count = state.kv.clear()
        assert count == 2
        assert state.kv.keys() == []

    def test_namespace_isolation(self, db_conn):
        state1 = State(db_conn, user_id="user1")
        state2 = State(db_conn, user_id="user2")

        state1.kv.set("key", "value1")
        state2.kv.set("key", "value2")

        assert state1.kv.get("key") == "value1"
        assert state2.kv.get("key") == "value2"


class TestSQL:
    def test_execute(self, state):
        state.sql.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        state.sql.execute("INSERT INTO test (name) VALUES (?)", ["alice"])
        state.sql.execute("INSERT INTO test (name) VALUES (?)", ["bob"])

    def test_query(self, state):
        state.sql.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        state.sql.execute("INSERT INTO users (name) VALUES (?)", ["alice"])
        state.sql.execute("INSERT INTO users (name) VALUES (?)", ["bob"])

        results = state.sql.query("SELECT * FROM users ORDER BY id")
        assert len(results) == 2
        assert results[0]["name"] == "alice"
        assert results[1]["name"] == "bob"

    def test_one(self, state):
        state.sql.execute("CREATE TABLE counts (val INTEGER)")
        state.sql.execute("INSERT INTO counts VALUES (1), (2), (3)")

        total = state.sql.one("SELECT SUM(val) FROM counts")
        assert total == 6

    def test_one_empty(self, state):
        state.sql.execute("CREATE TABLE empty (val INTEGER)")
        result = state.sql.one("SELECT val FROM empty")
        assert result is None

    def test_row(self, state):
        state.sql.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        state.sql.execute("INSERT INTO items (name) VALUES (?)", ["widget"])

        row = state.sql.row("SELECT * FROM items WHERE id = 1")
        assert row["id"] == 1
        assert row["name"] == "widget"

    def test_row_empty(self, state):
        state.sql.execute("CREATE TABLE empty (val INTEGER)")
        result = state.sql.row("SELECT * FROM empty")
        assert result is None


class TestFS:
    def test_write_read_text(self, state):
        state.fs.write("/test.txt", "Hello, World!")
        content = state.fs.read("/test.txt")
        assert content == "Hello, World!"

    def test_write_read_binary(self, state):
        data = b"\x00\x01\x02\x03"
        state.fs.write("/test.bin", data)
        content = state.fs.read("/test.bin", as_bytes=True)
        assert content == data

    def test_read_not_found(self, state):
        with pytest.raises(FileNotFoundError):
            state.fs.read("/nonexistent.txt")

    def test_exists(self, state):
        assert not state.fs.exists("/test.txt")
        state.fs.write("/test.txt", "content")
        assert state.fs.exists("/test.txt")

    def test_delete(self, state):
        state.fs.write("/test.txt", "content")
        result = state.fs.delete("/test.txt")
        assert result is True
        assert not state.fs.exists("/test.txt")

    def test_delete_nonexistent(self, state):
        result = state.fs.delete("/nonexistent.txt")
        assert result is False

    def test_list(self, state):
        state.fs.write("/docs/a.txt", "a")
        state.fs.write("/docs/b.txt", "b")
        state.fs.write("/docs/sub/c.txt", "c")

        files = state.fs.list("/docs/")
        assert set(files) == {"a.txt", "b.txt", "sub/"}

    def test_stat(self, state):
        state.fs.write("/test.txt", "Hello!")
        info = state.fs.stat("/test.txt")

        assert info["size"] == 6
        assert info["is_binary"] is False
        assert "created" in info
        assert "modified" in info

    def test_stat_not_found(self, state):
        with pytest.raises(FileNotFoundError):
            state.fs.stat("/nonexistent.txt")

    def test_copy(self, state):
        state.fs.write("/src.txt", "content")
        state.fs.copy("/src.txt", "/dst.txt")

        assert state.fs.read("/src.txt") == "content"
        assert state.fs.read("/dst.txt") == "content"

    def test_move(self, state):
        state.fs.write("/src.txt", "content")
        state.fs.move("/src.txt", "/dst.txt")

        assert not state.fs.exists("/src.txt")
        assert state.fs.read("/dst.txt") == "content"

    def test_clear(self, state):
        state.fs.write("/a.txt", "a")
        state.fs.write("/b.txt", "b")
        count = state.fs.clear()
        assert count == 2
        assert state.fs.list("/") == []

    def test_namespace_isolation(self, db_conn):
        state1 = State(db_conn, user_id="user1")
        state2 = State(db_conn, user_id="user2")

        state1.fs.write("/file.txt", "user1 content")
        state2.fs.write("/file.txt", "user2 content")

        assert state1.fs.read("/file.txt") == "user1 content"
        assert state2.fs.read("/file.txt") == "user2 content"


class TestConnect:
    def test_connect_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CYCLS_DATA_DIR"] = tmpdir
            conn = connect(True, app_name="test_app")
            conn.close()

            db_path = os.path.join(tmpdir, "test_app.db")
            assert os.path.exists(db_path)
            del os.environ["CYCLS_DATA_DIR"]

    def test_connect_file_path(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()
            assert os.path.exists(db_path)
        finally:
            os.unlink(db_path)

    def test_connect_file_uri(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = connect(f"file:{db_path}")
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.close()
            assert os.path.exists(db_path)
        finally:
            os.unlink(db_path)


class TestState:
    def test_user_id(self, state):
        assert state.user_id == "test_user"

    def test_global_namespace(self, db_conn):
        state = State(db_conn)
        assert state.user_id is None

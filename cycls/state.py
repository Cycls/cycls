"""
State management for Cycls apps.

Provides three interfaces for persistent state:
- KV: Simple key-value store with JSON serialization
- SQL: Direct SQL access for relational data
- FS: POSIX-like filesystem backed by SQLite

All data is stored in a single SQLite/libSQL database file.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional, List, Dict, Union


class KV:
    """Key-value store backed by SQLite table."""

    def __init__(self, conn, namespace: str = "global"):
        self._conn = conn
        self._ns = namespace
        self._ensure_table()

    def _ensure_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS _kv (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self._conn.commit()

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    def set(self, key: str, value: Any) -> None:
        """Set a key to a JSON-serializable value."""
        self._conn.execute(
            """INSERT OR REPLACE INTO _kv (key, value, updated_at)
               VALUES (?, ?, datetime('now'))""",
            [self._key(key), json.dumps(value)]
        )
        self._conn.commit()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by key, returns default if not found."""
        cursor = self._conn.execute(
            "SELECT value FROM _kv WHERE key = ?",
            [self._key(key)]
        )
        row = cursor.fetchone()
        return json.loads(row[0]) if row else default

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if key existed."""
        cursor = self._conn.execute(
            "DELETE FROM _kv WHERE key = ?",
            [self._key(key)]
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def list(self, prefix: str = "") -> List[str]:
        """List keys matching a prefix."""
        full_prefix = self._key(prefix)
        cursor = self._conn.execute(
            "SELECT key FROM _kv WHERE key LIKE ? ORDER BY key",
            [f"{full_prefix}%"]
        )
        ns_prefix = f"{self._ns}:"
        return [row[0].removeprefix(ns_prefix) for row in cursor.fetchall()]

    def incr(self, key: str, amount: Union[int, float] = 1) -> Union[int, float]:
        """Increment a numeric value. Initializes to 0 if not exists."""
        val = self.get(key, 0)
        if not isinstance(val, (int, float)):
            raise TypeError(f"Value at '{key}' is not numeric")
        new_val = val + amount
        self.set(key, new_val)
        return new_val

    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        cursor = self._conn.execute(
            "SELECT 1 FROM _kv WHERE key = ?",
            [self._key(key)]
        )
        return cursor.fetchone() is not None

    def keys(self) -> List[str]:
        """List all keys in this namespace."""
        return self.list("")

    def clear(self) -> int:
        """Delete all keys in this namespace. Returns count deleted."""
        cursor = self._conn.execute(
            "DELETE FROM _kv WHERE key LIKE ?",
            [f"{self._ns}:%"]
        )
        self._conn.commit()
        return cursor.rowcount


class SQL:
    """Direct SQL access to the database."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query: str, params: Optional[List] = None):
        """Execute a SQL statement. Returns cursor for chaining."""
        cursor = self._conn.execute(query, params or [])
        self._conn.commit()
        return cursor

    def query(self, query: str, params: Optional[List] = None) -> List[Dict]:
        """Execute a SELECT and return results as list of dicts."""
        cursor = self._conn.execute(query, params or [])
        if not cursor.description:
            return []
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def one(self, query: str, params: Optional[List] = None) -> Any:
        """Execute a SELECT and return the first column of the first row."""
        cursor = self._conn.execute(query, params or [])
        row = cursor.fetchone()
        return row[0] if row else None

    def row(self, query: str, params: Optional[List] = None) -> Optional[Dict]:
        """Execute a SELECT and return the first row as a dict."""
        cursor = self._conn.execute(query, params or [])
        if not cursor.description:
            return None
        row = cursor.fetchone()
        if not row:
            return None
        columns = [d[0] for d in cursor.description]
        return dict(zip(columns, row))


class FS:
    """Filesystem backed by SQLite table."""

    def __init__(self, conn, namespace: str = "global"):
        self._conn = conn
        self._ns = namespace
        self._ensure_table()

    def _ensure_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS _fs (
                path TEXT PRIMARY KEY,
                content BLOB,
                is_binary INTEGER DEFAULT 0,
                size INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self._conn.commit()

    def _path(self, path: str) -> str:
        # Normalize path and add namespace
        path = path.lstrip("/")
        return f"{self._ns}/{path}"

    def write(self, path: str, content: Union[str, bytes]) -> None:
        """Write content to a file. Creates parent dirs implicitly."""
        is_binary = isinstance(content, bytes)
        data = content if is_binary else content.encode("utf-8")
        self._conn.execute(
            """INSERT OR REPLACE INTO _fs (path, content, is_binary, size, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            [self._path(path), data, int(is_binary), len(data)]
        )
        self._conn.commit()

    def read(self, path: str, as_bytes: bool = False) -> Union[str, bytes]:
        """Read file content. Raises FileNotFoundError if not found."""
        cursor = self._conn.execute(
            "SELECT content, is_binary FROM _fs WHERE path = ?",
            [self._path(path)]
        )
        row = cursor.fetchone()
        if not row:
            raise FileNotFoundError(f"File not found: {path}")
        content, is_binary = row
        if as_bytes or is_binary:
            return bytes(content) if content else b""
        return content.decode("utf-8") if content else ""

    def exists(self, path: str) -> bool:
        """Check if a file exists."""
        cursor = self._conn.execute(
            "SELECT 1 FROM _fs WHERE path = ?",
            [self._path(path)]
        )
        return cursor.fetchone() is not None

    def delete(self, path: str) -> bool:
        """Delete a file. Returns True if file existed."""
        cursor = self._conn.execute(
            "DELETE FROM _fs WHERE path = ?",
            [self._path(path)]
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def list(self, prefix: str = "/") -> List[str]:
        """List files/directories under a path. Returns immediate children only."""
        prefix = prefix.rstrip("/") + "/"
        full_prefix = self._path(prefix.lstrip("/"))

        cursor = self._conn.execute(
            "SELECT path FROM _fs WHERE path LIKE ? ORDER BY path",
            [f"{full_prefix}%"]
        )

        results = set()
        prefix_len = len(full_prefix)
        for (path,) in cursor.fetchall():
            relative = path[prefix_len:]
            if "/" in relative:
                # It's in a subdirectory - return dir name with trailing /
                results.add(relative.split("/")[0] + "/")
            else:
                results.add(relative)
        return sorted(results)

    def stat(self, path: str) -> Dict[str, Any]:
        """Get file metadata. Raises FileNotFoundError if not found."""
        cursor = self._conn.execute(
            "SELECT size, is_binary, created_at, updated_at FROM _fs WHERE path = ?",
            [self._path(path)]
        )
        row = cursor.fetchone()
        if not row:
            raise FileNotFoundError(f"File not found: {path}")
        return {
            "size": row[0],
            "is_binary": bool(row[1]),
            "created": row[2],
            "modified": row[3],
        }

    def copy(self, src: str, dst: str) -> None:
        """Copy a file from src to dst."""
        content = self.read(src, as_bytes=True)
        stat = self.stat(src)
        is_binary = stat["is_binary"]
        self._conn.execute(
            """INSERT OR REPLACE INTO _fs (path, content, is_binary, size, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            [self._path(dst), content, int(is_binary), len(content)]
        )
        self._conn.commit()

    def move(self, src: str, dst: str) -> None:
        """Move a file from src to dst."""
        self.copy(src, dst)
        self.delete(src)

    def clear(self) -> int:
        """Delete all files in this namespace. Returns count deleted."""
        cursor = self._conn.execute(
            "DELETE FROM _fs WHERE path LIKE ?",
            [f"{self._ns}/%"]
        )
        self._conn.commit()
        return cursor.rowcount


class State:
    """
    Unified state container providing KV, SQL, and FS interfaces.

    All data is stored in a single SQLite database file, making it
    portable and easy to debug.
    """

    def __init__(self, conn, user_id: Optional[str] = None):
        """
        Initialize state with a database connection.

        Args:
            conn: A database connection (sqlite3 or libsql)
            user_id: Optional user ID for namespace isolation
        """
        self._conn = conn
        self._user_id = user_id
        namespace = user_id or "global"

        self.kv = KV(conn, namespace)
        self.sql = SQL(conn)
        self.fs = FS(conn, namespace)

    @property
    def user_id(self) -> Optional[str]:
        """The user ID this state is namespaced to."""
        return self._user_id

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()


def _get_db_path(app_name: str) -> Path:
    """Get the default database path for an app."""
    data_dir = Path(os.environ.get("CYCLS_DATA_DIR", ".cycls"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / f"{app_name}.db"


def connect(source: Union[str, bool] = True, app_name: str = "app") -> Any:
    """
    Connect to a state database.

    Args:
        source: Database source. Can be:
            - True: Use default local SQLite file
            - str starting with "file:": Local SQLite file path
            - str starting with "libsql://": Turso database URL
            - str: Treated as file path
        app_name: App name for default database naming

    Returns:
        Database connection
    """
    if source is True:
        # Default: local SQLite file
        db_path = _get_db_path(app_name)
        return _connect_sqlite(str(db_path))

    if isinstance(source, str):
        if source.startswith("libsql://") or source.startswith("https://"):
            return _connect_libsql(source)
        elif source.startswith("file:"):
            path = source[5:]  # Remove "file:" prefix
            return _connect_sqlite(path)
        else:
            # Treat as file path
            return _connect_sqlite(source)

    raise ValueError(f"Invalid state source: {source}")


def _connect_sqlite(path: str) -> Any:
    """Connect to a local SQLite database."""
    import sqlite3
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _connect_libsql(url: str) -> Any:
    """Connect to a Turso/libSQL database."""
    try:
        import libsql_experimental as libsql
    except ImportError:
        try:
            import libsql
        except ImportError:
            raise ImportError(
                "libsql package required for Turso connections. "
                "Install with: pip install libsql-experimental"
            )

    # Parse auth token from environment if not in URL
    auth_token = os.environ.get("TURSO_AUTH_TOKEN") or os.environ.get("LIBSQL_AUTH_TOKEN")

    if auth_token:
        return libsql.connect(url, auth_token=auth_token)
    return libsql.connect(url)

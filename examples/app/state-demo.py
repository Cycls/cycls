"""
State Demo - Demonstrates the Cycls state API (KV, SQL, FS).

Run with: uv run examples/app/state-demo.py
"""

import cycls

@cycls.app(state=True)
async def state_demo(context):
    """Demonstrates KV, SQL, and FS state interfaces."""

    msg = context.last_message.lower()

    # ─────────────────────────────────────────────────────────
    # KV Store Examples
    # ─────────────────────────────────────────────────────────
    if "counter" in msg or "count" in msg:
        count = context.state.kv.incr("visit_count")
        yield f"Visit count: {count}"
        return

    if "remember" in msg:
        # Extract what to remember (everything after "remember")
        parts = msg.split("remember", 1)
        if len(parts) > 1 and parts[1].strip():
            memory = parts[1].strip()
            context.state.kv.set("memory", memory)
            yield f"I'll remember: {memory}"
        else:
            yield "Remember what? Say 'remember <something>'"
        return

    if "recall" in msg or "what do you remember" in msg:
        memory = context.state.kv.get("memory")
        if memory:
            yield f"I remember: {memory}"
        else:
            yield "I don't remember anything yet. Say 'remember <something>'"
        return

    # ─────────────────────────────────────────────────────────
    # SQL Examples
    # ─────────────────────────────────────────────────────────
    if "init" in msg or "setup" in msg:
        context.state.sql.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        yield "Database initialized with notes table."
        return

    if msg.startswith("note ") or msg.startswith("add note"):
        # Ensure table exists
        context.state.sql.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        content = msg.replace("add note", "").replace("note ", "").strip()
        if content:
            context.state.sql.execute(
                "INSERT INTO notes (content) VALUES (?)",
                [content]
            )
            count = context.state.sql.one("SELECT COUNT(*) FROM notes")
            yield f"Note saved. You have {count} note(s)."
        else:
            yield "What should I note? Say 'note <content>'"
        return

    if "notes" in msg or "list notes" in msg:
        # Ensure table exists
        context.state.sql.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        notes = context.state.sql.query("SELECT id, content, created_at FROM notes ORDER BY id DESC LIMIT 10")
        if notes:
            yield "Your notes:\n"
            for note in notes:
                yield f"- [{note['id']}] {note['content']}\n"
        else:
            yield "No notes yet. Say 'note <content>' to add one."
        return

    # ─────────────────────────────────────────────────────────
    # File System Examples
    # ─────────────────────────────────────────────────────────
    if msg.startswith("save "):
        # save filename: content
        parts = msg[5:].split(":", 1)
        if len(parts) == 2:
            filename, content = parts[0].strip(), parts[1].strip()
            context.state.fs.write(f"/files/{filename}", content)
            yield f"Saved to /files/{filename}"
        else:
            yield "Usage: save filename: content"
        return

    if msg.startswith("read "):
        filename = msg[5:].strip()
        try:
            content = context.state.fs.read(f"/files/{filename}")
            yield f"Contents of {filename}:\n{content}"
        except FileNotFoundError:
            yield f"File not found: {filename}"
        return

    if "files" in msg or "list files" in msg:
        files = context.state.fs.list("/files/")
        if files:
            yield "Your files:\n"
            for f in files:
                yield f"- {f}\n"
        else:
            yield "No files yet. Say 'save filename: content' to create one."
        return

    # ─────────────────────────────────────────────────────────
    # Help / Default
    # ─────────────────────────────────────────────────────────
    yield "State Demo Commands:\n\n"
    yield "**KV Store:**\n"
    yield "- `counter` - Increment and show visit count\n"
    yield "- `remember <text>` - Store something\n"
    yield "- `recall` - Retrieve what you stored\n\n"
    yield "**SQL Database:**\n"
    yield "- `note <content>` - Save a note\n"
    yield "- `notes` - List all notes\n\n"
    yield "**File System:**\n"
    yield "- `save <name>: <content>` - Save a file\n"
    yield "- `read <name>` - Read a file\n"
    yield "- `files` - List all files\n"


state_demo._local()  # Use _local() for non-Docker testing

"""Per-session history persistence — append-only JSONL on the workspace.

Lives next to the harness because it's harness-internal: the chat loop reads
on entry, writes after each turn, and rewrites on compaction. Sessions
metadata (titles, updatedAt) lives separately in `KV("sessions", ws)` —
this file owns just the message log.

History migration to KV is deferred — this is the one piece RFC 002 doesn't
move yet because it's hot-path and the JSONL shape isn't broken at our scale.
"""
import json, os
from pathlib import Path


def ensure_workspace(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def history_path(user, session_id):
    """Validate *session_id* and return the JSONL history file path."""
    if os.sep in session_id or (os.altsep and os.altsep in session_id):
        raise ValueError(f"Invalid session id: {session_id}")
    path = user.sessions / f"{session_id}.history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def load_history(path):
    """Read JSONL history, strip stale cache_control, mark last message ephemeral.
    Malformed lines are logged and skipped — never silently truncates the history."""
    messages = []
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line: continue
                try: messages.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"[WARN] skipping malformed line {i} in {path}: {e}")
    except FileNotFoundError:
        return []
    except UnicodeDecodeError as e:
        print(f"[DEBUG] UnicodeDecodeError in {path} at line {i}: {e}")
        return messages
    for msg in messages:
        c = msg.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    if messages:
        c = messages[-1].get("content")
        if isinstance(c, str):
            messages[-1]["content"] = [{"type": "text", "text": c, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        elif isinstance(c, list) and c:
            c[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    return messages


def save_history(path, messages, mode="a"):
    """Write messages as JSONL."""
    with open(path, mode) as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

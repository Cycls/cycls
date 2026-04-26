"""Per-chat message log persistence — append-only JSONL on the workspace.

Lives next to the harness because it's harness-internal: the loop reads on
entry, writes after each turn, and rewrites on compaction. Chat metadata
(title, updatedAt) lives separately in `KV("chats", ws)` — this file owns
just the message log.

Log migration to KV is deferred — hot path; current shape isn't biting at
our scale. JSONL filename pattern stays `.history.jsonl` until that ships.
"""
import json, os
from pathlib import Path


def ensure_workspace(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def chat_path(user, chat_id):
    """Validate *chat_id* and return the JSONL message-log file path."""
    if os.sep in chat_id or (os.altsep and os.altsep in chat_id):
        raise ValueError(f"Invalid chat id: {chat_id}")
    path = user.sessions / f"{chat_id}.history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def load_chat(path):
    """Read JSONL message log, strip stale cache_control, mark last message ephemeral.
    Malformed lines are logged and skipped — never silently truncates."""
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


def save_chat(path, messages, mode="a"):
    """Write messages as JSONL."""
    with open(path, mode) as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

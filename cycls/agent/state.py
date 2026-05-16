"""Agent state primitives — chat (meta + log + Session), shares, and the
LLM-facing database tool. All built on cycls.app.workspace.DB.

Keys:
    chat/meta/{id}           — chat metadata (title, updatedAt, createdAt)
    chat/log/{id}/{turn:06d} — each message, ordered
    share/{token}            — opaque share tokens (RFC003)
    <.database/ slot>        — agent-controlled KV exposed to the LLM
"""
import asyncio, json
from datetime import datetime, timezone

from cycls.app.workspace import DB, workspace


# ---- Chat metadata ----

def _validate(chat_id):
    if "/" in chat_id:
        raise ValueError(f"Invalid chat id (contains slash): {chat_id}")


async def get_meta(workspace, chat_id):
    _validate(chat_id)
    return await DB(workspace).get(f"chat/meta/{chat_id}")


async def put_meta(workspace, chat_id, data):
    _validate(chat_id)
    list_meta = {"title": data.get("title", ""), "updatedAt": data.get("updatedAt", "")}
    await DB(workspace).put(f"chat/meta/{chat_id}", data, meta=list_meta)


async def list_chats(workspace):
    """Yield (chat_id, {title, updatedAt}) for every chat — backed by GCS
    custom-metadata so this is 1 LIST regardless of chat count."""
    async for key, meta in DB(workspace).index(prefix="chat/meta/"):
        yield key[len("chat/meta/"):], meta


async def touch_meta(workspace, chat_id, content):
    """Stamp `updatedAt` for chat-list ordering; on the first turn also derive
    title from the user message and set createdAt. Sole writer of chat meta —
    the FE shouldn't PUT this back."""
    existing = (await get_meta(workspace, chat_id)) or {}
    now = datetime.now(timezone.utc).isoformat()
    meta = {**existing, "id": chat_id, "updatedAt": now}
    if "createdAt" not in meta:
        meta["createdAt"] = now
    if not meta.get("title"):
        text = content if isinstance(content, str) else next(
            (b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"), "")
        if (title := text.strip()[:80]):
            meta["title"] = title
    await put_meta(workspace, chat_id, meta)


# ---- Chat message log ----

def _valid_prefix(messages):
    """Length of the longest valid prefix of *messages*, per Anthropic's
    pairing rules. Trims trailing corruption (most often a dangling
    assistant tool_use whose tool_result never persisted — typical after
    a mid-turn crash or retry). Repairs in-place rather than nuking
    the whole chat.

    Anthropic rejects:
      - assistant message with tool_use blocks but no following user
        message containing matching tool_result blocks
      - user tool_result blocks without preceding assistant tool_use
    """
    n = len(messages)
    while n > 0:
        last = messages[n-1]
        role, content = last.get("role"), last.get("content", [])
        if role == "user":
            if isinstance(content, list):
                results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                if results:
                    if n >= 2 and messages[n-2].get("role") == "assistant":
                        prev = messages[n-2].get("content", [])
                        if isinstance(prev, list):
                            uses = {b.get("id") for b in prev if isinstance(b, dict) and b.get("type") == "tool_use"}
                            rids = {b.get("tool_use_id") for b in results}
                            if uses and uses == rids:
                                return n  # complete pair
                    n -= 1; continue  # orphaned tool_result
            return n  # regular user message
        if role == "assistant":
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content
            ):
                n -= 1; continue  # dangling tool_use
            return n  # final response (text only)
        n -= 1  # unknown role
    return 0


async def load_messages(workspace, chat_id):
    """All messages for *chat_id* in turn order. Trims trailing corrupted
    state if any, persisting the repair so the disk catches up."""
    _validate(chat_id)
    db = DB(workspace)
    messages = [msg async for _, msg in db.items(prefix=f"chat/log/{chat_id}/")]
    valid = _valid_prefix(messages)
    if valid < len(messages):
        await asyncio.gather(*[
            db.delete(f"chat/log/{chat_id}/{i:06d}")
            for i in range(valid, len(messages))
        ])
        messages = messages[:valid]
    return messages


async def append_messages(workspace, chat_id, messages, start_idx):
    """Append *messages* starting at turn index *start_idx*."""
    _validate(chat_id)
    if not messages:
        return
    db = DB(workspace)
    await asyncio.gather(*[
        db.put(f"chat/log/{chat_id}/{(start_idx + i):06d}", msg)
        for i, msg in enumerate(messages)
    ])


async def replace_messages(workspace, chat_id, messages):
    """Wipe and rewrite all messages for *chat_id* (used by compaction)."""
    _validate(chat_id)
    db = DB(workspace)
    await db.delete(f"chat/log/{chat_id}/")
    await asyncio.gather(*[
        db.put(f"chat/log/{chat_id}/{i:06d}", msg)
        for i, msg in enumerate(messages)
    ])


async def delete_chat(workspace, chat_id):
    """Delete metadata + all messages for *chat_id*."""
    _validate(chat_id)
    db = DB(workspace)
    await asyncio.gather(
        db.delete(f"chat/meta/{chat_id}"),
        db.delete(f"chat/log/{chat_id}/"),
    )


# ---- Session ----

def _ephemeralize(messages):
    """Strip stale cache_control markers; tag the last message ephemeral so
    prompt caching keeps the prior context warm and the new turn is fresh."""
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


class Session:
    """The working message list plus its persistence. The loop appends to
    `.messages` and calls `.checkpoint()` whenever the list is consistent (a
    complete turn or tool-result batch) and `.rollback()` after an error that
    may have left a half-written turn. An anonymous request — no chat_id or no
    signed-in user — gets a pure in-memory session: checkpoint/rollback are
    no-ops and nothing touches disk."""

    @classmethod
    async def open(cls, context):
        persist = bool(context.chat_id and context.user)
        messages = _ephemeralize(await load_messages(context.workspace, context.chat_id)) if persist else []
        return cls(context.workspace, context.chat_id if persist else None, messages)

    def __init__(self, workspace, chat_id, messages):
        self.workspace, self.chat_id, self.messages = workspace, chat_id, messages
        self._saved = len(messages)

    async def add_user(self, content, *, attachments=None):
        msg = {"role": "user", "content": content}
        if attachments:
            msg["attachments"] = attachments
        self.messages.append(msg)
        if self.chat_id:
            try: await touch_meta(self.workspace, self.chat_id, content)
            except Exception as e: print(f"[WARN] meta touch failed: {e}")

    async def checkpoint(self):
        """Flush the unsaved tail of `.messages` to disk."""
        if self.chat_id and len(self.messages) > self._saved:
            await append_messages(self.workspace, self.chat_id, self.messages[self._saved:], self._saved)
        self._saved = len(self.messages)

    async def rewrite(self, messages):
        """Replace `.messages` wholesale (compaction) and persist the rewrite."""
        self.messages[:] = messages
        if self.chat_id:
            await replace_messages(self.workspace, self.chat_id, self.messages)
        self._saved = len(self.messages)

    def rollback(self):
        """Drop any tail not yet flushed by `checkpoint()`."""
        del self.messages[self._saved:]


# ---- Share tokens (RFC003) ----

async def resolve(workspace, token, requester=None):
    row = await DB(workspace).get(f"share/{token}")
    if not row:
        return None
    aud = row.get("audience", "public")
    if aud == "public":
        return row
    if aud.startswith("org:") and getattr(requester, "org_id", None) == aud[4:]:
        return row
    return None


# ---- Agent KV (LLM-facing tool) ----

def _validate_db_key(key):
    """Allow trailing slash (= subtree marker for delete); reject empty,
    leading '/', '..' segments, and empty middle segments."""
    if not key: raise ValueError("key required")
    parts = key.split("/")
    if key.startswith("/") or ".." in parts or "" in parts[:-1]:
        raise ValueError(f"invalid key: {key!r}")


async def _exec_database(inp, ws):
    """All returns are strings — Anthropic tool_result.content accepts
    str or content-blocks (each with a `type`); raw dicts/lists from JSON
    values would 400. JSON-encode the data ones."""
    agent_ws = workspace(ws.subject, ws.root.parent, base=ws.base, slot=".database")
    db = DB(agent_ws)
    cmd, key = inp.get("command"), inp.get("key", "")
    try:
        if cmd == "get":
            _validate_db_key(key)
            v = await db.get(key)
            return json.dumps(v) if v is not None else f"Error: key {key!r} not found"
        if cmd == "put":
            _validate_db_key(key)
            await db.put(key, inp.get("value"))
            return f"Stored {key!r}"
        if cmd == "delete":
            _validate_db_key(key)
            await db.delete(key)
            return f"Deleted {key!r}"
        if cmd == "scan":
            prefix = inp.get("prefix", "")
            limit = max(1, int(inp.get("limit", 100)))
            pairs = [{"key": k, "value": v} async for k, v in db.items(prefix=prefix, limit=limit + 1)]
            truncated = len(pairs) > limit
            if truncated: pairs = pairs[:limit]
            if not pairs: return f"No keys with prefix {prefix!r}"
            result = json.dumps(pairs)
            return f"{result}\n[truncated at {limit}; use a narrower prefix or higher limit]" if truncated else result
        return f"Error: unknown command {cmd!r}"
    except ValueError as e:
        return f"Error: {e}"

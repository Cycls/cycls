"""Agent state primitives — chat (index + turns + Session), shares, and the
LLM-facing database tool. All built on cycls.app.db.DB.

Chat layout — one folder per chat:
    chat/{id}/index           — chat metadata (title, updatedAt, createdAt)
    chat/{id}/{turn:06d}      — one file per message, ordered

The `index` file is the sidebar's enumeration target: `db.scan(glob=
"chat/*/index")` returns one entry per chat in a single LIST round-trip.
Delete is a single subtree wipe of `chat/{id}/` — catches the index AND
every turn in one operation.

Keys:
    chat/{id}/index           — chat metadata (sidebar target)
    chat/{id}/{turn:06d}      — turns (append-only; the full transcript)
    chat/{id}/compaction      — compaction marker (summary + first_kept)
    share/{token}             — opaque share tokens (RFC003)
    <.database/ slot>         — agent-controlled KV exposed to the LLM
"""
import asyncio, json, re
from datetime import datetime, timezone

from cycls.app.db import DB, workspace


# ---- Chat metadata ----

# Whitelist: alphanumeric + `_` / `-`. Rejects path separators, glob metachars
# (`*?[]{}`), dot-prefixed names, unicode tricks. UUIDs fit comfortably.
_CHAT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate(chat_id):
    if not _CHAT_ID.match(chat_id or ""):
        raise ValueError(f"Invalid chat id: {chat_id!r}")


async def get_meta(workspace, chat_id):
    _validate(chat_id)
    return await DB(workspace).get(f"chat/{chat_id}/index")


async def put_meta(workspace, chat_id, data):
    _validate(chat_id)
    await DB(workspace).put(f"chat/{chat_id}/index", data, meta=data)


async def list_chats(workspace):
    """Yield (chat_id, {title, updatedAt}) for every chat. One LIST via
    object storage; one glob+read on local FS."""
    async for key, meta in DB(workspace).scan(glob="chat/*/index"):
        yield key.split("/")[1], meta


async def add_cost(workspace, chat_id, delta):
    """Increment the chat's running cost total (USD). Stored as a stringified
    decimal in the index so it rides on the str:str meta contract."""
    if delta <= 0: return
    _validate(chat_id)
    existing = (await get_meta(workspace, chat_id)) or {}
    current = float(existing.get("cost") or 0)
    existing["cost"] = f"{current + delta:.6f}"
    await put_meta(workspace, chat_id, existing)


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

def normalize(messages):
    """Return a copy of *messages* that satisfies all provider API pairing
    invariants. Strips blocks/messages that can't be repaired in place.
    The single safety net — runs at load time and before every provider
    send, so the API never sees a half-written turn regardless of how
    persistence got there.

    Invariants enforced:
      1. Assistant `tool_use` (client-side) blocks must be paired with a
         matching `tool_result` in the next user message.
      2. User `tool_result` blocks must point to a `tool_use` in the prior
         assistant message.
      3. Assistant `server_tool_use` blocks must have a matching
         `*_tool_result` block in the same content list (server-side
         tools like web_search return both blocks within one turn).

    Messages that become empty after stripping are dropped entirely.
    """
    out = []
    n = len(messages)
    for i, m in enumerate(messages):
        role = m.get("role")
        content = m.get("content")

        if role == "assistant":
            if not isinstance(content, list):
                out.append(m); continue
            next_msg = messages[i+1] if i+1 < n else None
            new_content = _normalize_assistant_blocks(content, next_msg)
            if new_content:
                out.append({**m, "content": new_content})
            continue

        if role == "user":
            if not isinstance(content, list):
                out.append(m); continue
            prior = out[-1] if out else None
            new_content = _normalize_user_blocks(content, prior)
            if new_content:
                out.append({**m, "content": new_content})
            continue

        # Unknown role: drop
    return out


def _normalize_assistant_blocks(blocks, next_msg):
    # Server-side pairing (intra-message): server_tool_use ↔ *_tool_result
    server_uses = {b["id"] for b in blocks
                   if isinstance(b, dict) and b.get("type") == "server_tool_use" and "id" in b}
    server_results = {b.get("tool_use_id") for b in blocks
                      if isinstance(b, dict)
                      and isinstance(b.get("type"), str)
                      and b["type"].endswith("_tool_result")
                      and b["type"] != "tool_result"}
    paired_server = server_uses & server_results

    # Client-side pairing: assistant tool_use ↔ tool_result in NEXT user message
    next_result_ids = set()
    if next_msg and next_msg.get("role") == "user":
        nc = next_msg.get("content")
        if isinstance(nc, list):
            next_result_ids = {b.get("tool_use_id") for b in nc
                               if isinstance(b, dict) and b.get("type") == "tool_result"}
    client_uses = {b["id"] for b in blocks
                   if isinstance(b, dict) and b.get("type") == "tool_use" and "id" in b}
    paired_client = client_uses & next_result_ids

    def keep(b):
        if not isinstance(b, dict): return True
        t = b.get("type")
        if t == "tool_use": return b.get("id") in paired_client
        if t == "server_tool_use": return b.get("id") in paired_server
        if isinstance(t, str) and t.endswith("_tool_result") and t != "tool_result":
            return b.get("tool_use_id") in paired_server
        return True

    return [b for b in blocks if keep(b)]


def _normalize_user_blocks(blocks, prior):
    prior_use_ids = set()
    if prior and prior.get("role") == "assistant":
        pc = prior.get("content")
        if isinstance(pc, list):
            prior_use_ids = {b["id"] for b in pc
                             if isinstance(b, dict) and b.get("type") == "tool_use" and "id" in b}

    def keep(b):
        if not isinstance(b, dict): return True
        if b.get("type") == "tool_result":
            return b.get("tool_use_id") in prior_use_ids
        return True

    return [b for b in blocks if keep(b)]


async def load_messages(workspace, chat_id):
    """All messages for *chat_id* in turn order, normalized to satisfy provider
    pairing invariants. Persists the repair via full rewrite so disk catches
    up with whatever `normalize` produced."""
    _validate(chat_id)
    db = DB(workspace)
    # Glob `[0-9]*` selects turn files (000000, 000001, ...) — index excluded.
    messages = [msg async for _, msg in db.items(glob=f"chat/{chat_id}/[0-9]*")]
    normalized = normalize(messages)
    if normalized != messages:
        await replace_messages(workspace, chat_id, normalized)
    return normalized


async def append_messages(workspace, chat_id, messages, start_idx):
    """Append *messages* starting at turn index *start_idx*."""
    _validate(chat_id)
    if not messages:
        return
    db = DB(workspace)
    await asyncio.gather(*[
        db.put(f"chat/{chat_id}/{(start_idx + i):06d}", msg)
        for i, msg in enumerate(messages)
    ])


async def replace_messages(workspace, chat_id, messages):
    """Wipe and rewrite all messages for *chat_id* (used by compaction).
    Preserves the index file — only turns are rewritten."""
    _validate(chat_id)
    db = DB(workspace)
    turn_keys = [k async for k, _ in db.scan(glob=f"chat/{chat_id}/[0-9]*")]
    await asyncio.gather(*(db.delete(k) for k in turn_keys))
    await asyncio.gather(*[
        db.put(f"chat/{chat_id}/{i:06d}", msg)
        for i, msg in enumerate(messages)
    ])


async def get_compaction(workspace, chat_id):
    """The chat's compaction marker `{summary, first_kept}`, or None. Raw turns
    stay on disk; this marker projects the model's context over them."""
    _validate(chat_id)
    return await DB(workspace).get(f"chat/{chat_id}/compaction")


async def put_compaction(workspace, chat_id, data):
    _validate(chat_id)
    await DB(workspace).put(f"chat/{chat_id}/compaction", data)


async def delete_chat(workspace, chat_id):
    """Delete the chat — index and all turns in one subtree wipe."""
    _validate(chat_id)
    await DB(workspace).delete(f"chat/{chat_id}/")


# ---- Session ----

def _ephemeralize(messages):
    """Strip any persisted `cache_control` markers from history. The provider
    re-applies cache breakpoints fresh each turn (system + last tool + last
    user message); persisted markers would risk exceeding Anthropic's 4-
    breakpoint cap."""
    for msg in messages:
        c = msg.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
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
        if not persist:
            return cls(context.workspace, None, [])
        messages = _ephemeralize(await load_messages(context.workspace, context.chat_id))
        marker = await get_compaction(context.workspace, context.chat_id) or {}
        return cls(context.workspace, context.chat_id, messages,
                   summary=marker.get("summary"), first_kept=int(marker.get("first_kept", 0)))

    def __init__(self, workspace, chat_id, messages, summary=None, first_kept=0):
        self.workspace, self.chat_id, self.messages = workspace, chat_id, messages
        self.summary, self.first_kept = summary, min(first_kept, len(messages))
        self._saved = len(messages)

    def context(self):
        """The model's view: raw turns whole, or (once compacted) the summary
        standing in for the folded prefix + the recent raw turns verbatim."""
        if self.summary is None:
            return self.messages
        from .harness.compact import prefix
        return [*prefix(self.summary), *self.messages[self.first_kept:]]

    async def compact(self, provider):
        """Fold the projected context into a summary marker — raw turns on disk
        are never touched, so the full transcript survives for the UI."""
        from .harness.compact import compact
        result = await compact(provider, self.context())
        self.summary = result[0]["content"]
        self.first_kept = len(self.messages) - (len(result) - 2)
        if self.chat_id:
            await put_compaction(self.workspace, self.chat_id,
                                 {"summary": self.summary, "first_kept": self.first_kept})

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
    agent_ws = workspace(ws.subject, ws.volume, base=ws.base, slot=".database", ws=ws.ws)
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

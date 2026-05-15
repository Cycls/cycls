"""Per-chat persistence — metadata + message log under one workspace DB,
plus `Session`, the stateful handle the loop writes through.

Keys:
    chat/meta/{chat_id}           — chat metadata (title, updatedAt, createdAt)
    chat/log/{chat_id}/{turn:06d} — each message, ordered
"""
from datetime import datetime, timezone

from cycls.app.workspace import DB


def _validate(chat_id):
    if "/" in chat_id:
        raise ValueError(f"Invalid chat id (contains slash): {chat_id}")


# ---- Metadata ----

async def get_meta(workspace, chat_id):
    _validate(chat_id)
    return await DB(workspace).get(f"chat/meta/{chat_id}")


async def put_meta(workspace, chat_id, data):
    _validate(chat_id)
    # Stash list-view fields as object custom-metadata so `list_chats` can
    # enumerate (title, updatedAt) via a single GCS LIST — no per-chat GETs.
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


# ---- Message log ----

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
                    # Must be paired with preceding assistant tool_use
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
    state if any, persisting the repair so the disk catches up. The harness
    applies prompt-cache markers itself; this is storage, not LLM-shaping."""
    _validate(chat_id)
    messages, keys = [], []
    async for k, msg in DB(workspace).items(prefix=f"chat/log/{chat_id}/"):
        keys.append(k); messages.append(msg)
    valid = _valid_prefix(messages)
    if valid < len(messages):
        # Persist the repair so subsequent loads stay clean.
        async with DB(workspace).transaction() as t:
            for k in keys[valid:]:
                await t.delete(k)
        messages = messages[:valid]
    return messages


async def append_messages(workspace, chat_id, messages, start_idx):
    """Append *messages* starting at turn index *start_idx*. Single open
    via transaction so a 3-message turn doesn't pay 3× the open cost."""
    _validate(chat_id)
    if not messages:
        return
    async with DB(workspace).transaction() as t:
        for offset, msg in enumerate(messages):
            await t.put(f"chat/log/{chat_id}/{(start_idx + offset):06d}", msg)


async def replace_messages(workspace, chat_id, messages):
    """Wipe and rewrite all messages for *chat_id* atomically (used by
    compaction)."""
    _validate(chat_id)
    async with DB(workspace).transaction() as t:
        async for key, _ in t.items(prefix=f"chat/log/{chat_id}/"):
            await t.delete(key)
        for i, msg in enumerate(messages):
            await t.put(f"chat/log/{chat_id}/{i:06d}", msg)


async def delete_chat(workspace, chat_id):
    """Atomically delete metadata + all messages for *chat_id*."""
    _validate(chat_id)
    async with DB(workspace).transaction() as t:
        await t.delete(f"chat/meta/{chat_id}")
        async for key, _ in t.items(prefix=f"chat/log/{chat_id}/"):
            await t.delete(key)


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
            # FE attachment metadata, stored as a sidecar: the model sees inlined
            # base64 in `content`, the FE renders thumbnails from `attachments[]`.
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

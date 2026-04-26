"""Per-chat state — metadata + message log, unified in one KV.

A chat is metadata + messages. They live in `KV("chat", workspace)` with two
sub-prefixes:

    meta/{chat_id}           — chat metadata (title, updatedAt, createdAt)
    log/{chat_id}/{turn:06d} — each message, ordered

list_chats scans `meta/`. load_messages scans `log/{id}/`. delete_chat removes
both. One KV, one logical concept, prefix-scan ergonomics throughout.
"""
from cycls.app.db import KV


def _kv(workspace):
    return KV("chat", workspace)


def _validate(chat_id):
    if "/" in chat_id:
        raise ValueError(f"Invalid chat id (contains slash): {chat_id}")


# ---- Metadata ----

async def get_meta(workspace, chat_id):
    _validate(chat_id)
    return await _kv(workspace).get(f"meta/{chat_id}")


async def put_meta(workspace, chat_id, data):
    _validate(chat_id)
    await _kv(workspace).put(f"meta/{chat_id}", data)


async def list_chats(workspace):
    """Yield (chat_id, metadata) for every chat in this workspace."""
    async for key, data in _kv(workspace).items(prefix="meta/"):
        yield key[len("meta/"):], data


# ---- Message log ----

async def load_messages(workspace, chat_id):
    """All messages for *chat_id* in turn order. Returns raw messages — the
    harness applies prompt-cache `cache_control` markers itself; this is
    storage, not LLM-shaping."""
    _validate(chat_id)
    messages = []
    async for _, msg in _kv(workspace).items(prefix=f"log/{chat_id}/"):
        messages.append(msg)
    return messages


async def append_messages(workspace, chat_id, messages, start_idx):
    """Append *messages* starting at turn index *start_idx*."""
    _validate(chat_id)
    kv = _kv(workspace)
    for offset, msg in enumerate(messages):
        await kv.put(f"log/{chat_id}/{(start_idx + offset):06d}", msg)


async def replace_messages(workspace, chat_id, messages):
    """Wipe and rewrite all messages for *chat_id* (used by compaction)."""
    _validate(chat_id)
    kv = _kv(workspace)
    async for key, _ in kv.items(prefix=f"log/{chat_id}/"):
        await kv.delete(key)
    for i, msg in enumerate(messages):
        await kv.put(f"log/{chat_id}/{i:06d}", msg)


# ---- Combined ----

async def delete_chat(workspace, chat_id):
    """Delete metadata + all messages for *chat_id*."""
    _validate(chat_id)
    kv = _kv(workspace)
    await kv.delete(f"meta/{chat_id}")
    async for key, _ in kv.items(prefix=f"log/{chat_id}/"):
        await kv.delete(key)

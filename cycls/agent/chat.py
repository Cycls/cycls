"""Per-chat state — metadata + message log under one workspace DB.

Keys:
    chat/meta/{chat_id}           — chat metadata (title, updatedAt, createdAt)
    chat/log/{chat_id}/{turn:06d} — each message, ordered
"""
from cycls.app.workspace import DB
from cycls.agent.tools import tool_step


def _validate(chat_id):
    if "/" in chat_id:
        raise ValueError(f"Invalid chat id (contains slash): {chat_id}")


# ---- Metadata ----

async def get_meta(workspace, chat_id):
    _validate(chat_id)
    return await DB(workspace).get(f"chat/meta/{chat_id}")


async def put_meta(workspace, chat_id, data):
    _validate(chat_id)
    await DB(workspace).put(f"chat/meta/{chat_id}", data)


async def list_chats(workspace):
    """Yield (chat_id, metadata) for every chat in this workspace."""
    async for key, data in DB(workspace).items(prefix="chat/meta/"):
        yield key[len("chat/meta/"):], data


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
    messages = []
    keys = []
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


# ---- Display view ----

def to_ui_messages(raw):
    """API-format messages → FE shape `{role, content: str, parts?, attachments?}`.
    Store keeps Anthropic blocks; FE wants a string content (+ parts for
    assistant). Drops user messages whose content is purely tool_result
    blocks — harness scaffolding, not user-visible."""
    out = []
    for msg in raw:
        role, c = msg.get("role"), msg.get("content")
        if role == "user":
            if isinstance(c, list):
                if all(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                    continue
                text = "".join(b.get("text", "") for b in c
                               if isinstance(b, dict) and b.get("type") == "text")
            elif isinstance(c, str):
                text = c
            else:
                continue
            ui = {"role": "user", "content": text}
            if msg.get("attachments"):
                ui["attachments"] = msg["attachments"]
            out.append(ui)
        elif role == "assistant":
            if isinstance(c, str):
                out.append({"role": "assistant", "content": c,
                            "parts": [{"type": "text", "text": c}]}); continue
            if not isinstance(c, list): continue
            parts, texts = [], []
            for b in c:
                if not isinstance(b, dict): continue
                t = b.get("type")
                if t == "text":
                    parts.append({"type": "text", "text": b.get("text", "")})
                    texts.append(b.get("text", ""))
                elif t == "thinking":
                    parts.append({"type": "thinking", "thinking": b.get("thinking", "")})
                elif t == "tool_use":
                    parts.append({"type": "step", **tool_step(b.get("name", ""), b.get("input"))})
            out.append({"role": "assistant", "content": "".join(texts), "parts": parts})
    return out


# ---- Combined ----

async def delete_chat(workspace, chat_id):
    """Atomically delete metadata + all messages for *chat_id*."""
    _validate(chat_id)
    async with DB(workspace).transaction() as t:
        await t.delete(f"chat/meta/{chat_id}")
        async for key, _ in t.items(prefix=f"chat/log/{chat_id}/"):
            await t.delete(key)

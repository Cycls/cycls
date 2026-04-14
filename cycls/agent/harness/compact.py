"""Context compaction — microcompact + partial compaction."""
import re
from .prompts import COMPACT_SYSTEM

COMPACT_BUFFER = 30_000   # compact when within this many tokens of context window
KEEP_RECENT = 10          # keep last N messages verbatim during partial compaction

def context_window(model):
    windows = {
        "claude-sonnet-4-6": 1_000_000,
        "claude-opus-4-6": 1_000_000,
        "claude-sonnet": 200_000,   # earlier 4.x versions
        "claude-opus": 200_000,     # earlier 4.x versions
        "claude-haiku": 200_000,
    }
    if model in windows: return windows[model]
    return next((v for k, v in windows.items() if k in model), 200_000)

def microcompact(messages):
    """Strip old tool results from messages older than KEEP_RECENT. Mutates in place."""
    keep = min(len(messages), KEEP_RECENT)
    for msg in messages[:-keep] if keep else []:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list): continue
        for block in msg["content"]:
            if block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                block["content"] = "[Old tool result cleared]"

async def compact(client, model, messages):
    """Partial compaction: summarize old messages, keep recent verbatim. Returns new messages list."""
    microcompact(messages)
    keep = min(len(messages), KEEP_RECENT)
    old = messages[:-keep] if keep else messages
    recent = messages[-keep:] if keep else []
    r = await client.messages.create(model=model, max_tokens=16384,
        system=[{"type": "text", "text": COMPACT_SYSTEM}],
        messages=old + [{"role": "user", "content":
            "Summarize the conversation above following the structured format. "
            "Use <analysis> to think through everything, then <summary> for the final output. "
            "Recent messages will be preserved separately — focus on the older context."}])
    raw = r.content[0].text
    raw = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw)
    m = re.search(r"<summary>([\s\S]*?)</summary>", raw)
    summary = m.group(1).strip() if m else raw.strip()
    return [
        {"role": "user", "content": "This session continues from a previous conversation. Summary of earlier work:\n\n" + summary},
        {"role": "assistant", "content": "Understood. I have the full context. Recent messages follow."},
        *recent]

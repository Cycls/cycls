"""Context compaction — microcompact + partial compaction."""
import re
from .prompts import COMPACT_SYSTEM

COMPACT_BUFFER = 30_000   # compact when within this many tokens of the context window
KEEP_RECENT = 10          # keep last N messages verbatim during partial compaction

_SUMMARY_REQUEST = (
    "Summarize the conversation above following the structured format. "
    "Use <analysis> to think through everything, then <summary> for the final output. "
    "Recent messages will be preserved separately — focus on the older context."
)


def microcompact(messages):
    """Strip old tool results from messages older than KEEP_RECENT. Mutates in place."""
    keep = min(len(messages), KEEP_RECENT)
    for msg in messages[:-keep] if keep else []:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                block["content"] = "[Old tool result cleared]"


async def compact(complete, messages):
    """Partial compaction: summarize the old messages, keep the recent ones
    verbatim. `complete(messages=, system=, max_tokens=) -> str` is the
    provider's non-streaming one-shot. Returns the new messages list."""
    microcompact(messages)
    keep = min(len(messages), KEEP_RECENT)
    old = messages[:-keep] if keep else messages
    recent = messages[-keep:] if keep else []
    raw = await complete(
        messages=old + [{"role": "user", "content": _SUMMARY_REQUEST}],
        system=COMPACT_SYSTEM, max_tokens=16384)
    raw = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw)
    m = re.search(r"<summary>([\s\S]*?)</summary>", raw)
    summary = m.group(1).strip() if m else raw.strip()
    return [
        {"role": "user", "content": "This session continues from a previous conversation. Summary of earlier work:\n\n" + summary},
        {"role": "assistant", "content": "Understood. I have the full context. Recent messages follow."},
        *recent]

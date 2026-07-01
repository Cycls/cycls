"""Context compaction — summarize old turns, keep recent ones verbatim."""
import json, re
from .prompts import COMPACT_SYSTEM

COMPACT_BUFFER = 30_000        # compact within this many tokens of the window
KEEP_RECENT_TOKENS = 20_000    # keep this many recent tokens verbatim

_SUMMARY_REQUEST = (
    "Summarize the conversation above following the structured format. "
    "Use <analysis> to think through everything, then <summary> for the final output. "
    "Recent messages will be preserved separately — focus on the older context."
)
_LEDGER = "Files touched so far: "
_LEDGER_RE = re.compile(re.escape(_LEDGER) + r"(.+)")
_ACK = "Understood. I have the full context. Recent messages follow."


def prefix(summary):
    """The two internal messages that stand in for the folded-away turns."""
    return [
        {"role": "user", "internal": True, "content": summary},
        {"role": "assistant", "internal": True, "content": _ACK},
    ]


def _tokens(content):
    """~4 chars/token estimate over the JSON form — picks the cut point only."""
    return len(content if isinstance(content, str) else json.dumps(content, default=str)) // 4


def _is_tool_result(m):
    c = m.get("content")
    return isinstance(c, list) and bool(c) and all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def _cut(messages):
    """Index where the recent window starts: walk back to KEEP_RECENT_TOKENS,
    then snap forward to a real user turn — never inside a tool_use/tool_result
    pair, and roles alternate after our ack."""
    total, cut = 0, len(messages)
    for i in range(len(messages) - 1, 0, -1):
        total += _tokens(messages[i].get("content"))
        cut = i
        if total >= KEEP_RECENT_TOKENS: break
    while cut < len(messages) and (messages[cut].get("role") != "user" or _is_tool_result(messages[cut])):
        cut += 1
    return cut


def _ledger(messages):
    """Files read/edited so far, accumulated from tool calls + any prior line."""
    files = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            if hit := _LEDGER_RE.search(c):
                files += [f.strip() for f in hit.group(1).split(",") if f.strip()]
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("read", "edit"):
                    if p := (b.get("input") or {}).get("path"): files.append(p)
    return list(dict.fromkeys(files))


def microcompact(messages):
    """Blank string tool results in place — the summary keeps what mattered."""
    for msg in messages:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                block["content"] = "[Old tool result cleared]"


async def _summarize(provider, old):
    from ..state import normalize
    raw = await provider.complete(
        messages=normalize(old) + [{"role": "user", "content": _SUMMARY_REQUEST}],
        system=COMPACT_SYSTEM, max_tokens=min(provider.max_output, 16384))
    raw = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw)
    m = re.search(r"<summary>([\s\S]*?)</summary>", raw)
    return m.group(1).strip() if m else raw.strip()


async def compact(provider, messages):
    """Old turns → one summary; recent turns kept verbatim. Always shrinks —
    a failed summary drops the old turns instead, so the next request fits."""
    cut = _cut(messages)
    files = _ledger(messages)
    old, recent = messages[:cut], messages[cut:]
    microcompact(old)
    try:
        summary = await _summarize(provider, old)
    except Exception:
        summary = "(Earlier conversation could not be summarized; it was dropped to free up context.)"
    head = "This session continues from a previous conversation. Summary of earlier work:\n\n" + summary
    if files:
        head += "\n\n" + _LEDGER + ", ".join(files)
    return [*prefix(head), *recent]

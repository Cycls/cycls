"""Context compaction — stub old tool results first, summarize old turns when that frees too little."""
import json, re
from .prompts import COMPACT_SYSTEM

COMPACT_AT = 0.7          # compact past this share of the window
KEEP_RECENT = 0.3         # keep this share of the window verbatim
CLEAR_AT_LEAST = 0.1      # stubbing must free this share, or the summary runs instead
COMPACT_BUFFER = 30_000   # headroom past input + max_tokens

_SUMMARY_REQUEST = (
    "Summarize the conversation above following the structured format. "
    "Use <analysis> to think through everything, then <summary> for the final output. "
    "Recent messages will be preserved separately — focus on the older context."
)
_LEDGER = "Files touched so far: "
_LEDGER_RE = re.compile(re.escape(_LEDGER) + r"(.+)")
_ACK = "Understood. I have the full context. Recent messages follow."
_CLEARED = "[Old tool result cleared]"


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


def _cut(messages, keep):
    """Index where the recent window starts: walk back `keep` tokens,
    then snap forward to a real user turn — never inside a tool_use/tool_result
    pair, and roles alternate after our ack."""
    total, cut = 0, len(messages)
    for i in range(len(messages) - 1, 0, -1):
        total += _tokens(messages[i].get("content"))
        cut = i
        if total >= keep: break
    start = cut
    while cut < len(messages) and (messages[cut].get("role") != "user" or _is_tool_result(messages[cut])):
        cut += 1
    if cut == len(messages):
        # No plain user turn after the cut (one request, many tool rounds) —
        # fall back to an assistant boundary so the recent window survives.
        cut = start
        while cut < len(messages) and messages[cut].get("role") != "assistant":
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


def clear(messages):
    """Copies with every tool result stubbed — the transcript keeps the originals."""
    return [{**m, "content": [{**b, "content": _CLEARED} if b.get("type") == "tool_result" else b
                              for b in m["content"]]} if _is_tool_result(m) else m for m in messages]


def clear_to(messages, start, keep):
    """Where stubbing stops short of the recent `keep` tokens, and ~the tokens it frees from `start`."""
    cut = _cut(messages, keep)
    return cut, sum(_tokens(m["content"]) for m in messages[start:cut] if _is_tool_result(m))


async def _summarize(provider, old):
    from ..state import normalize
    raw = await provider.complete(
        messages=normalize(old) + [{"role": "user", "content": _SUMMARY_REQUEST}],
        system=COMPACT_SYSTEM, max_tokens=8_192)
    raw = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw)
    m = re.search(r"<summary>([\s\S]*?)</summary>", raw)
    return m.group(1).strip() if m else raw.strip()


async def compact(provider, messages, keep):
    """Old turns → one summary; recent turns kept verbatim. Always shrinks —
    a failed summary drops the old turns instead, so the next request fits."""
    cut = _cut(messages, keep)
    files = _ledger(messages)
    old, recent = messages[:cut], messages[cut:]
    try:
        summary = await _summarize(provider, old)
    except Exception:
        summary = "(Earlier conversation could not be summarized; it was dropped to free up context.)"
    head = "This session continues from a previous conversation. Summary of earlier work:\n\n" + summary
    if files:
        head += "\n\n" + _LEDGER + ", ".join(files)
    return [*prefix(head), *recent]

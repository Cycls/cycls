"""Context compaction — stub old tool results first, summarize old turns when that frees too little."""
import asyncio, json, re
from .prompts import COMPACT_SYSTEM

COMPACT_AT = 0.7          # compact past this share of the window
KEEP_RECENT = 0.3         # keep this share of the window verbatim
CLEAR_AT_LEAST = 0.25     # stubbing a warm cache must free this share, or the summary runs instead
CLEAR_COLD = 0.1          # ... and this share after a pause, when the provider cache is gone anyway
COLD_AFTER = 1_200        # idle seconds until the cache is mostly gone (K3: 94% cached at 5–10 min, 19% at 20–40)
COMPACT_BUFFER = 30_000   # headroom past input + max_tokens
SUMMARY_MAX = 16_384      # summary output cap, reasoning included; more needs streaming on Anthropic
SUMMARY_TIMEOUT = 300     # seconds before the summary counts as failed

_SUMMARY_REQUEST = (
    "Summarize the conversation above following the structured format. "
    "Use <analysis> to think through everything, then <summary> for the final output. "
    "Recent messages will be preserved separately — focus on the older context."
)
_LEDGER = "Files touched so far: "
_LEDGER_RE = re.compile(re.escape(_LEDGER) + r"(.+)")
_ACK = "Understood. I have the full context. Recent messages follow."
DROPPED = "(Earlier conversation could not be summarized; it was dropped to free up context.)"


def prefix(summary):
    """The two internal messages that stand in for the folded-away turns."""
    return [
        {"role": "user", "internal": True, "content": summary},
        {"role": "assistant", "internal": True, "content": _ACK},
    ]


def _tokens(content):
    """~4 chars/token estimate over the JSON form — sizes cuts, never bills."""
    return len(content if isinstance(content, str) else json.dumps(content, default=str, ensure_ascii=False)) // 4


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


def _stub(b):
    t = isinstance(b, dict) and b.get("type")
    if t == "tool_result": return {**b, "content": "[Old tool result cleared]"}
    if t == "tool_use":   # long arguments (an app's code, an edit's text) go too; paths and commands stay
        return {**b, "input": {k: "[Old input cleared]" if isinstance(v, str) and len(v) > 1_000 else v
                               for k, v in (b.get("input") or {}).items()}}
    return b


def clear(messages):
    """Copies with tool results and long tool arguments stubbed — the transcript keeps the originals.
    A loaded skill is instructions, not history, so its result stays."""
    skills = {b.get("id") for m in messages if isinstance(m.get("content"), list) for b in m["content"]
              if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "skill"}
    return [{**m, "content": [b if isinstance(b, dict) and b.get("tool_use_id") in skills else _stub(b)
                              for b in m["content"]]} if isinstance(m.get("content"), list) else m
            for m in messages]


def clear_to(messages, start, keep):
    """Where stubbing stops short of the recent `keep` tokens, and ~the tokens it frees from `start`."""
    cut = _cut(messages, keep)
    old = messages[start:cut]
    return cut, sum(_tokens(m.get("content")) for m in old) - sum(_tokens(m.get("content")) for m in clear(old))


async def _summarize(provider, old, max_tokens):
    from ..state import normalize
    raw = await asyncio.wait_for(provider.complete(
        messages=normalize(old) + [{"role": "user", "content": _SUMMARY_REQUEST}],
        system=COMPACT_SYSTEM, max_tokens=max_tokens), SUMMARY_TIMEOUT)
    raw = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw)
    m = re.search(r"<summary>([\s\S]*?)</summary>", raw)
    if not (summary := (m.group(1) if m else raw).strip()):
        raise ValueError("empty summary")   # a reasoning model can spend the whole budget thinking
    return summary


async def compact(provider, messages, keep, max_tokens):
    """Old turns → one summary; recent turns kept verbatim. Always shrinks —
    a failed summary drops the old turns instead, so the next request fits."""
    cut = _cut(messages, keep)
    files = _ledger(messages)
    old, recent = messages[:cut], messages[cut:]
    try:
        summary = await _summarize(provider, old, min(max_tokens, SUMMARY_MAX))
    except Exception:
        summary = DROPPED
    head = "This session continues from a previous conversation. Summary of earlier work:\n\n" + summary
    if files:
        head += "\n\n" + _LEDGER + ", ".join(files)
    return [*prefix(head), *recent]

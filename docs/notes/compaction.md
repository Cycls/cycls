# Compaction and context management

**Status**: built (2026-09-23).

The context window is a budget. A fixed part (system prompt, tool schemas, skills and
app catalogs, `AGENT.md`) is paid on every call; connectors cost ~15 tokens each until
the model loads one (decisions 21–22 in [plugins-connectors.md](plugins-connectors.md)).
The rest is the conversation, and it only grows. Three layers keep it bounded:

| layer | when | model call | code |
| --- | --- | --- | --- |
| cap at ingest | as a tool result or attachment arrives | no | `_exec_read`, `spill.spill` |
| clear (tier 1) | past the trigger, or when a run starts after a pause | no | `Session.clear`, `compact.clear` |
| summarize (tier 2) | past the trigger when clearing frees too little, or on overflow | yes | `Session.compact`, `compact.compact` |

The transcript on disk is never rewritten. Clearing and summaries are a projection over
it, so the UI always shows the full chat.

## Caps at ingest

- **`read`** returns at most 50,000 characters (~25k tokens), cuts lines at 2,000, and
  ends with `[Stopped at line N of M. Continue with offset=N+1.]`. Attachments are
  inlined through `read`, so the same cap bounds them. Files over 3 MB are refused (use
  bash); large PDFs need `pages`, 20 per read. Images and PDFs go as base64 blocks.
- **Every other string result** of 20,000 characters or more spills to
  `.tmp/{chat_id}/` and the model gets a preview (`spill.py`, 48h TTL). `read` and
  `skill` never spill; list-shaped results (MCP multi-part, images) don't either.
- **`web_fetch`** returns `max_chars` (default 20k, at most 100k), then spills like the rest.

Why the `read` cap exists: one user's 2.19M-character HTML deck was inlined whole —
1.48M tokens against a 1,048,576 window — and overflowed before the model ran, seven
times across four chats. Compaction cannot rescue a single turn bigger than the window,
so the only defence is not letting it in.

## When the loop looks

`fold()` in `_run` (`harness/main.py`) runs before every model call and once more after
the loop ends. It reads the last call's measured input (`input + cached + cache_create`)
and does nothing unless that is past the trigger and more than two messages follow
`first_kept`. Before the first call, a chat whose last call was over 20 minutes ago also
gets a tier-1 clear at a lower bar — see [what it costs](#what-it-costs).

| | formula | super (1M, `max_tokens` 131k) | 128k window, 8k out |
| --- | --- | --- | --- |
| trigger | `min(70% of window, window − max_tokens − 30k)` | 700k | 89.6k |
| kept verbatim | 30% of window | 300k | 38.4k |
| clearing must free, cache warm | 25% of window | 250k | 32k |
| clearing must free, after a 20-minute pause | 10% of window | 100k | 12.8k |

The `max_tokens` term matters when the reply budget is large: the request needs room for
input *and* output. Constants live at the top of `compact.py`.

`.context()` sets the window. Unset, it is 1M — set it for smaller models, or chats
overflow before the trigger is reached.

## Tier 1 — clear

Everything between `first_kept` and the cut that leaves the recent 30% is shown to the
model with:

- tool results → `[Old tool result cleared]`
- string tool arguments over 1,000 characters (an app's code, an edit's text) →
  `[Old input cleared]`

Paths, commands and short arguments stay, so the model still knows what it did and the
file ledger still finds files. The index is persisted as `cleared` in the marker, and
`Session.context()` applies the stubs on every request.

There is no model call, no UI and no wait. This is the approach of Anthropic's
tool-result clearing (`clear_at_least`, keep the recent uses) and OpenHands' observation
masking.

### What it costs

A clear changes the prompt from the first stubbed message on, so the next request misses
the provider cache from there, and the one after is cached again. Measured 2026-09-23 on a
15k-token chat, cached tokens for full → cleared → cleared again: Modal K3 15,360 → 0 →
1,536 of 2,233; OpenAI 14,976 → 0 → 1,664 of 1,711; GLM 15,872 → 0 → 1,856 of 2,007.

The miss is real money, because production's cache is warm almost all the time:

| idle before the call (super + haseef, 30 days) | calls | cached |
| --- | --- | --- |
| under 5 min | 35,531 | 97% |
| 5–10 min | 642 | 94% |
| 10–20 min | 376 | 65% |
| 20–40 min | 250 | 19% |
| over 40 min | 632 | 5–7% |

So the bar follows the cache:

- **Warm** — within a run, or back within 20 minutes: clear only past the trigger, and only
  if it frees 25% of the window. At super's prices ($3 in, $0.30 cached per 1M), a clear at
  700k that frees 25–30% pays back its miss in about 7–9 calls; at a 10% bar it took ~33.
- **Cold** — 20+ minutes idle: before the first call, clear if it frees 10%. The cache is
  mostly gone, so the miss costs nothing and the smaller prompt is cheaper from that call on.

## Tier 2 — summarize

Runs when clearing frees too little, or when the window has already overflowed (then
clearing is skipped). The part before the recent 30% — what the model currently sees,
stubs included — goes to `provider.complete()` with `COMPACT_SYSTEM`, a nine-section
prompt modelled on Claude Code's. `<analysis>` is stripped, `<summary>` kept.

- **Budget**: `max_tokens`, capped at 16,384. A reasoning model needs room to think
  before it writes; the Anthropic SDK refuses much more without streaming.
- **Timeout**: 300s.
- **Failure** (error, timeout, or an empty summary) drops the old turns with a sentence
  saying so. Compaction always shrinks, so the next request fits.
- **Result**: two internal messages stand in for the folded turns — the summary plus
  `Files touched so far: …` (read/edit paths, carried across summaries), and an
  acknowledgement.

What the user sees: the step "Summarizing earlier messages to keep this chat going...",
which the web client shows in the UI's language (`stepText` in
`client/src/lib/i18n.ts`). The loop pings every 15s while it waits, like a tool batch,
so proxies don't cut the silent call. A failure is a warning callout with a reference id.

**End of run.** A run that ends past the trigger summarizes before its stream closes,
while the answer is being read, so the next message starts from a ready context. The run
stays active until it finishes; a message sent meanwhile queues. If the stream is cut,
the task keeps running and writes the marker if the instance lets it finish.

The summarizer call is billed and logged as a `usage` row with `compact=true`, and added
to the chat's cost.

## Overflow recovery

The provider can still say the context is full — an estimate was off, or one turn grew
past the trigger in a single step. Two detectors:

- `stop_reason == "model_context_window_exceeded"`, or `max_tokens` with zero output
- an error whose text matches `_OVERFLOW_RE` — one phrasing per provider (Anthropic,
  OpenAI, SGLang, …). SGLang's was missing until `29301a9`: 10 errors across 4 chats on
  super since 2026-09-01 reached users as raw 400s.

Either way, once per run: drop any partial turn, summarize, replay.

## The marker

`chat/{id}/compaction` in the workspace DB — on the volume,
`<workspace>/.db/chat/<chat_id>/compaction.json`:

```json
{"summary": "This session continues…", "first_kept": 120, "cleared": 380}
```

`first_kept` and `cleared` index `Session.messages` (the normalized list, not turn
files). The model sees:

```
[summary, ack]  +  stubbed(messages[first_kept:max(first_kept, cleared)])  +  messages[max(first_kept, cleared):]
```

`Session` clamps both on load. `truncate_last_exchange` clamps them on disk too — a stale
index past the new length would stub or hide the turns appended after it.

## Checking it in production

Summaries, with their size and cost:

```sql
SELECT timestamp, JSON_VALUE(json_payload.chat_id) AS chat,
       JSON_VALUE(json_payload.input) AS input, JSON_VALUE(json_payload.output) AS output
FROM logs
WHERE JSON_VALUE(json_payload.level) = 'usage' AND JSON_VALUE(json_payload.compact) = 'true'
ORDER BY timestamp DESC LIMIT 50
```

Every compaction, either tier, is a `compaction` row (`tier`, `reason` = `trigger` /
`cold` / `overflow`, `tokens`, `ok`) and, when a client is watching, the analytics event
`context_compacted` ([analytics.md](analytics.md)):

```sql
SELECT timestamp, JSON_VALUE(json_payload.chat_id) AS chat, JSON_VALUE(json_payload.tier) AS tier,
       JSON_VALUE(json_payload.reason) AS reason, JSON_VALUE(json_payload.tokens) AS tokens,
       JSON_VALUE(json_payload.ok) AS ok
FROM logs
WHERE JSON_VALUE(json_payload.level) = 'compaction'
ORDER BY timestamp DESC LIMIT 50
```

`ok` is false when the summary failed and the old turns were dropped. A compaction that
raised is also a `level=warn` row whose `message` starts with `compaction failed:`; its
`error_id` is the reference the user saw. A chat's current state is its
`compaction.json` (`cycls volume get`).

## Provider compatibility

Tested 2026-09-23: the loop's full, cleared and summary views of one chat, sent through
cycls' own provider classes. Accepted by Modal K3 (production), OpenAI gpt-4o-mini, Z.ai
GLM-5.2, Gemini 2.5 Flash, and Baseten Kimi-K3, GLM-5.2 and DeepSeek-V4-Flash — and every
model still named the file it edited after clearing. Baseten's gpt-oss-120b rejects our tool
history cleared or not: it refuses an assistant message carrying both text and a tool call.
Not tested, for lack of credit: Anthropic native (the open question is extended thinking
with edited tool inputs in old turns), OpenRouter, Moonshot, Fireworks.

## Tests

- `tests/agent/agent_test.py`, compaction section — trigger and threshold, tier 1 (stubs,
  no summary call, marker, transcript intact), the cold-start clear, end-of-run summary,
  failed and empty summaries, the `compacted` events, cut invariants, ledger, both
  overflow paths, the `read` cap.
- `tests/agent/scenarios/test_load_repair.py` — the marker clamps on truncate.
- `tests/agent/scenarios/test_live.py::test_compaction_real_roundtrip` — real Anthropic,
  text-only history.

## Open

- **The summary call is uncached.** It has its own system prompt and no tools, so it
  pays full price for the whole prefix. Reusing the main system prompt, tools and
  message prefix (Claude Code's approach) makes it a cache hit — and settles whether
  Anthropic accepts tool history without `tools`, which is unverified: the live test
  avoids tool calls.
- **A failed summary is logged without its cause** — `ok=false`, but not why.
- **The estimate is `chars / 4`.** Good enough to place cuts; base64 images are
  overcounted badly (a 1 MB image estimates ~330k tokens and bills ~1.5k). Each
  assistant turn stores its measured `usage`, which could replace it.
- **Only string arguments are stubbed**; long nested arguments stay.
- **The end-of-run summary holds the stream open.** A fully detached one needs CPU
  after the response ends, which Cloud Run throttles — see [runs.md](runs.md).
- **The mobile app** shows the step label in English.
- **Public docs** (`cycls-docs`) still say compaction happens "when the window fills".

## Related

- [plugins-connectors.md](plugins-connectors.md) — the tool-block budget and the spill design.
- [runs.md](runs.md) — stream cuts and the 1200s request cap.

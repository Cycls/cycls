# RFC004 — Provider parity (Anthropic + OpenAI, no gap-filling)

## Summary

Make the harness kernel provider-agnostic and lift `OpenAIProvider` to a first-class peer of `AnthropicProvider`. Where the two providers diverge in capability (Anthropic's native `document` rendering, server-side `web_search`, MCP connector, image content inside `tool_result`), **declare the gap honestly and warn — don't simulate**. Anthropic's behavior is byte-for-byte unchanged. OpenAI does the things it natively does; users hit a clear warning when they reach for something only Anthropic supports.

## Motivation

Today the harness was built Anthropic-shape-first, with `OpenAIProvider` doing a one-way adapter into Chat Completions. Three capability gaps silently break on OpenAI:

- **Small PDF reads** → `_exec_read` emits `{type:"document", source:base64}` blocks; OpenAI Chat Completions has no `document`; `_to_messages` joins `.text` of child blocks → empty string.
- **Image content inside `tool_result.content`** → Anthropic accepts it natively; OpenAI `role:"tool"` messages are text-only (`string | Array<{type:"text",…}>`); `_to_messages` drops the visual content.
- **Web search** (`web_search_20250305`) → Anthropic server-side built-in; OpenAI has no equivalent; `_to_tools` filters it out.

The natural-but-wrong fix is to write translation gymnastics: rasterize PDFs each turn on the OpenAI path; emit a tool-stub plus follow-up `user` message carrying the image; replace `web_search` with a third-party search API. All three add real risk surface (wire-shape divergence, rasterization cost, third-party dependency) for the same outcome we could get by being honest: **OpenAI doesn't do these things; tell the user that clearly when they ask for them**.

## Principle

> Translate between *supported* features. Don't simulate *unsupported* ones.

Translating a base64 user-message image into OpenAI's `image_url` data URI: fine — both providers support that capability with different wire shapes. Translating an Anthropic `document` block into a synthetic follow-up `user` message of rasterized images: gap-filling. The first is wiring; the second is pretending. Cycls does the first; cycls does **not** do the second.

The benefit: kernel stays portable, risk near-zero, Anthropic's golden bits unchanged, OpenAI is a real first-class provider rather than an adapter pretending to be Anthropic.

## Goals

- The kernel (`harness/main.py`, `Session`, events, compact, `to_ui`) is provider-agnostic — uses a canonical message/content shape, doesn't enforce or assume any one provider's wire format.
- `AnthropicProvider` and `OpenAIProvider` are peers — each does its own provider-side translation from canonical to wire.
- Anthropic behavior is byte-for-byte unchanged: native `document` rendering, server-side `web_search`, MCP, image-in-tool_result.
- OpenAI does the things it does natively: chat, tool calls, user-message `image_url` attachments, text-only tool results.
- Capability gaps surface as clear warnings, not silent breaks.

## Non-goals

- **Rasterize-on-translate for PDFs.** Anthropic's native `document` rendering is "golden" — rasterizing would degrade Anthropic users. For OpenAI: warn, don't simulate.
- **Tool-stub + follow-up `user` message trick for images in tool_result.** Pi ships this; we're explicitly choosing not to. Adds a wire-shape divergence and a synthetic user message into the transcript for marginal gain. Warn instead.
- **Replace server-side `web_search` with a third-party search API.** Anthropic's bundled search is a real product gift; OpenAI users who want search BYO via `.tools([…]).on("web_search", fn)` — already supported.
- **Provider-neutral canonical storage shape (pi's approach).** We're Anthropic-aligned in storage because it's the most expressive option (has thinking, document, image-in-tool_result, server-tool-use). One translator (OpenAI) is cheaper than two; the "Anthropic-aligned canonical" is a design choice, not architectural Anthropic special-treatment.
- **Per-API-variant compat flags** (pi's `requiresAssistantAfterToolResult`, `requiresThinkingAsText`, …). Only useful once we onboard a third provider class. Add then.

## Design

### Canonical shape

Stored messages, `Session.messages`, and the inputs/outputs of `dispatch`/`_exec_read`/`_ingest` all use Anthropic's message and content-block shape as the **canonical** form. It's the most expressive option, so it can represent everything any provider supports. Providers translate canonical → wire on their boundary; kernel never knows the wire shape.

### Per-capability behavior

| capability | Anthropic | OpenAI | code |
|---|---|---|---|
| basic chat / text deltas / thinking | native | native (`reasoning` / `reasoning_content` → `Thinking` event) | unchanged |
| tool calls | native | native (Chat Completions function calls) | unchanged |
| user-message image attachments | native (`image` block) | translated (`image_url` data URI) — wiring between supported features | unchanged |
| custom tools | `{type:"custom", name, description, input_schema}` | translated via `_to_tools` to `{type:"function", function:{…}}` | unchanged |
| **PDF reads** (`document` block in `tool_result.content`) | native rendering — golden | **warning + text stub** `"[document content not viewable on this provider]"`. No rasterization. | `OpenAIProvider._to_messages` |
| **Image in `tool_result.content`** | native | **warning + text stub** `"[image content not viewable on this provider]"`. No follow-up-user trick. | `OpenAIProvider._to_messages` |
| **Server-side `web_search`** | registered when `"WebSearch"` ∈ allowed_tools — golden, free | **vendor-gated:** `build_tools` skips it; logs a one-shot warning when filtering. Users wanting search BYO custom tool. | `tools/__init__.py` + `harness/main.py` |
| **MCP servers (`cycls.MCP`)** | Anthropic connector | **warning** when `mcp_servers` is non-empty; drops them (already silently dropped today; just makes it loud) | `OpenAIProvider.stream` |

### Warning surface

A one-shot warning per (chat_id, gap) pair. Either:
- Yielded as a `Callout(text, "warning")` event so it shows in the UI as a callout (visible, not noise on stdout), OR
- A `logging.warning(...)` call (server logs only).

Pick UI: warnings are user-facing decisions ("you enabled web search but switched to GPT-5; it's not available"). Surfacing as a Callout matches the user's mental model.

## Honest gotchas

- **Lossy PDF/image on OpenAI.** A `read` of a PDF or an image, when the model is OpenAI, gives the model a text stub instead of the visual content. Documented; the warning fires the first time it happens in a session. Users who need visual on OpenAI use `bash` to extract text from PDFs, or upload images in user messages (which *does* work on both providers).
- **No `web_search` on OpenAI** by default. Users who want it register a custom tool; the warning when they try `.allowed_tools(["WebSearch"])` on a non-Anthropic model tells them so.
- **Storage shape is Anthropic-aligned.** If we ever change canonical (e.g., add a third provider whose features don't translate down), this becomes a refactor. Not in scope.

## What this does *not* change

- The Anthropic side of the harness — at all. Behavior is byte-for-byte preserved.
- `Session.messages` / on-disk storage / `_valid_prefix` / `to_ui_messages`.
- The loop (`_run`), events, compact, prompts.
- Public API: `cycls.LLM().model("anthropic/…")` / `model("openai/…")`, `.allowed_tools([…])`, agent bodies, `to_ui`, FE.

## Implementation order

Each a separate green commit.

1. **Web search vendor gate** in `build_tools`. `build_tools` takes a `vendor` arg; skips `WebSearch` entries when vendor ≠ anthropic; the loop emits a `Callout` warning if it filtered something the user asked for. (~+10 LOC)
2. **OpenAIProvider degrades visual content in tool_result** — `_to_messages` detects `document`/`image` blocks inside `tool_result.content`, replaces with a `"[<kind> content not viewable on this provider]"` text stub, yields a one-shot `Callout` warning. (~+10 LOC)
3. **MCP gate** — `OpenAIProvider.stream` emits a `Callout` warning when `mcp_servers` is non-empty and the call drops them. (~+3 LOC)
4. **Live test** — `test_openai_basic_real`: simple chat + one `bash` tool call on `openai/gpt-…`. Pins that the OpenAI path actually works end-to-end against the real API. (~+15 LOC, ~$0.02/run)

**Total: ~+25–35 LOC** for a portable kernel, OpenAI as a first-class provider, Anthropic untouched, capability gaps honest. Zero rasterization, zero synthetic-message tricks, zero third-party search dependency.

## Where pi confirms / diverges

| concern | pi does | we do | why we diverge |
|---|---|---|---|
| canonical shape | their own neutral type (`TextContent` / `ImageContent` / `ToolResultMessage`) | Anthropic-aligned | one translator vs two; our scope is 2 providers |
| native PDF support in canonical | none — rasterize upstream | native on Anthropic side (`document` block); warn on OpenAI | we keep an Anthropic gift instead of dropping it |
| image-in-tool_result on OpenAI | tool-stub + follow-up user message workaround | **warning + text stub, no workaround** | we choose honesty over simulation |
| server-side web_search | not shipped | native on Anthropic; warn on OpenAI | we keep an Anthropic gift |
| per-API-variant quirks | compat flag set | none yet (only 2 providers) | future-proof; add when we add a 3rd |

We end up with strictly **more** capability than pi (we ship native `document` blocks and server-side `web_search` on Anthropic), at strictly **less** translation complexity (no rasterizer-in-the-loop, no synthetic-message trick).

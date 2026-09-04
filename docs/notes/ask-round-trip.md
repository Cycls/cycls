# Making `ask` a true in-turn round-trip

The `ask` tool ends the turn. It yields a `{type: ui, action: ask, questions}`
event, the loop **breaks**, and the user's next message carries their answers.
That covers "ask, then act on the reply". It does not cover "ask mid-task and
keep working in the same turn" — the model can't call `ask` while holding
half-finished work.

**Status**: deliberate. This note records how to lift it if we want to.

## How it ends the turn today

Not by trusting the model to stop. `ask` is a `Tool` row with `terminal=True`
(see [tool-rows.md](tool-rows.md)), and the loop enforces it:

```python
# harness/main.py — after the batch's tool_results are appended
results.append({"type": "tool_result", "tool_use_id": block["id"], "content": content})
if ok and is_terminal(block["name"]) and not str(content).startswith("Error"):
    terminal = True
messages.append({"role": "user", "content": results})
await session.checkpoint()
if terminal:
    break
```

Two properties of that ordering matter for anything built on top:

- The `tool_result` is written **before** the break, so the assistant
  `tool_use` is never left unpaired. History on disk is always API-valid.
- Only a call that actually reached the user is terminal. A malformed `ask`
  returns `Error: …` and the model gets another turn to fix itself, rather
  than the turn dying on a typo.

The card carries up to 3 questions (`_ASK_MAX_QUESTIONS`), batched into one
call precisely because each call costs a full round-trip. `once=True` means a
second `ask` in the same batch is refused with an error telling the model to
send everything together.

## Why it isn't a round-trip

SSE is one-directional. Once `_run` is streaming there is no channel for the
client to hand an answer back into the running loop, so a blocking `ask` would
need a second POST route plus a pending-future registry, a timeout policy, and
an answer for what happens when the tab closes mid-await.

## How Claude Code solves the same bind

Claude Code's `AskUserQuestion` is a normal tool — no dedicated hook, matched
by `PreToolUse`/`PostToolUse` by name. In an interactive terminal it genuinely
blocks and returns the answer as the `tool_result`.

Headless (`claude -p`) has no terminal, which is structurally our problem.
Their answer is a **defer/resume protocol** rather than a held connection:

1. Claude calls `AskUserQuestion`; `PreToolUse` fires.
2. The hook returns `permissionDecision: "defer"`. The tool does **not** run.
   The process exits with `stop_reason: "tool_deferred"` and the pending
   `tool_use` preserved in the transcript.
3. The caller reads `deferred_tool_use` (`id`, `name`, `input`), renders the
   question in its own UI, and waits. No timeout, no retry limit — the session
   sits on disk until resumed.
4. It resumes with `--resume <session-id>`; the same tool call fires
   `PreToolUse` again.
5. The hook returns `"allow"` with the answer in `updatedInput`. The tool
   executes and the model continues **inside the same turn**.

The turn is suspended and resumed with the answer injected as tool input — no
connection is held open. That shape ports to us.

## What the port would cost here

Less than it used to. An earlier draft of this note claimed `state.normalize()`
was the blocker, on the assumption that a suspended turn would leave an
unpaired `tool_use` on disk — the exact shape `_normalize_assistant_blocks`
strips as mid-turn corruption. **That is no longer true**, because the loop
writes the ack `tool_result` before breaking. History after a terminal `ask` is
already well-formed:

```
user      "build me a report"
assistant [tool_use  id=a1 name=ask …]
user      [tool_result tool_use_id=a1 "Asked the user 1 question. End your turn…"]
```

`normalize()` keeps all three. So the port is a **rewrite**, not a carve-out:

- `POST /chats/{id}/answer` replaces that last `tool_result`'s content with the
  user's answers and re-enters `_run` without appending a new user turn.
- Rewriting a stored message means `state.replace_messages` (wipe + contiguous
  rewrite) — the same primitive `truncate_last_exchange` uses, for the same
  reason: turn files are `{turn:06d}` and `Session._saved` is
  `len(messages)`, so an in-place edit that changed the count would let the
  next append clobber a live turn.
- `ask` loses `terminal=True`, or gains a "resumable" variant of it. Everything
  else in the loop stays as-is.

What still needs deciding, and is the real cost:

- **The transcript shows an answered question twice** — once as the rewritten
  tool_result, once as whatever the user sees. Today the answer is a visible
  user message; after the port it is tool input, so `to_ui_messages` needs to
  project it or the conversation reads as though nobody replied.
- **Abandonment.** Today a dismissed card costs nothing: the turn already
  ended. A suspended turn that is never answered is a chat stuck mid-tool-call,
  and needs an expiry or an explicit "never mind" that writes a cancellation
  tool_result.
- **The answer stops being editable.** As a user message it can be regenerated
  from; as tool input it can't, without teaching `truncate_last_exchange`
  about pending asks.

## Related

The FE card is per-device dismissable (`askEnabled()` in `client/src/lib/utils.ts`,
toggled in Settings → General). Off hides the card, not the question: the step
line still names it and typing a reply still answers. Any round-trip design has
to keep that true, or the toggle becomes a way to deadlock a turn.

# Runs — the loop outlives the request

**Status**: proposed (2026-09-09). Investigation of super and haseef, 14 days of
production logs and transcripts.

Today one HTTP request does two jobs: it *is* the agent run, and it carries
the stream. `POST /chat` starts the loop inside the response generator and the
events go back on that response. When the browser's connection ends for any
reason, Starlette sends `http.disconnect`, cancels the generator, and the loop
dies mid-tool or mid-model-call. The client shows nothing. The user reloads,
sees the agent stopped, and types "كمل".

This note separates the two jobs. The run becomes a server-side task that the
connection only watches. Nothing about how often connections drop changes;
it stops mattering.

## What the logs say

| 14 days, super + haseef | count |
| --- | --- |
| streams closed from the client side while the loop was mid-work (hypercorn `- POST /chat`) | ~245 |
| of those, runs longer than 60s | ~100 |
| runs killed by the Cloud Run 1200s request timeout | 4 |
| runs killed by container OOM at 1Gi (3 events) | 7 |
| user messages lost because the cut came before the first checkpoint | 44 |
| `Stopped: max_tokens` callouts, provider errors, loop-initiated stops | 0 |

The loop never stops on its own in these cases. Every cut is the request
ending under it. Desktop cuts are mostly the tab being parked (Edge sleeping
tabs, Chrome freezing) or the user navigating; mobile cuts are backgrounding
and screen lock. Durations are irregular, so no timer on our side, Google's
side, or the browser's is involved. Cloud Run's own guidance for long requests
is to "design request handlers in such a way that they can resume from the
point where they left off".

Why the damage is total today, in code:

- `web/server.py` `back()` returns `StreamingResponse(encoder(func(context)))`.
  hypercorn reports ASGI 2.1, so Starlette uses the task-group path and
  cancels the generator on disconnect.
- `harness/main.py` catches the cancel only around the model stream (saves
  partial text with `[…]`). A cancel during tool execution drops the
  assistant `tool_use` turn entirely; `normalize` strips it on next load.
- `state.py` `Session.add_user` appends to memory only; the first checkpoint
  is after the first tool batch. A cut before that loses the user's message.
- `client/src/hooks/use-chat.ts` retries only pre-stream failures. A stream
  that dies after first bytes ends silently; `loadChat` aborts the running
  stream, so clicking any chat in the panel kills the run.

## Non-goals

- No Redis, no new service, no event-log files on GCS. The turn files and
  `index.json` we already write are the durable state.
- No token-level re-attach after a drop. That needs the watcher to reach the
  container holding the run, and Cloud Run has no way to address an instance.
  Session affinity is best effort and we will not build on it.
- No WebSocket. Same connection underneath, same causes.
- No change to the 1200s request timeout. Once the request only carries the
  stream, its limit no longer bounds the run.

## Design

Three parts. Each maps to one failure.

### 1. The run is a task; the response only forwards

In `back()`, the body stream `func(context)` is consumed by a task that puts
events on a queue; the `StreamingResponse` generator reads the queue. A
disconnect cancels the reader, never the task. The task runs to the loop's
own end or to the run budget (45 minutes, then a clean interrupt).

A registry `{chat_id: Run}` per process holds the task and its status. One
run per chat: a second `POST /chat?id=` while a run is active answers
`409 {run: {...}}` and the client falls into the polling view below. This
also removes the duplicate-run case seen on Android (five identical POSTs in
12 ms, five copies of a 400-turn chat, then OOM).

`POST /chats/{chat_id}/stop` cancels the task. Stop is the only thing that
cancels; a dropped connection is not a stop.

Per-instance cap on active runs (tied to memory; 6 at 2Gi). Beyond it, `503`
with `Retry-After`; the client retries on the next poll tick.

### 2. Run state lives on `index.json`

`touch_meta` already owns the chat meta. Add one key:

```json
"run": {"status": "running", "started": "…", "heartbeat": "…", "owner": "<instance id>"}
```

- `status`: `running` | `done` | `interrupted` | `stopped`.
- `heartbeat`: refreshed every 10s by the owning task. Readers treat a
  heartbeat older than 30s as `interrupted` regardless of the stored status,
  so a container that died mid-run never leaves a chat "running" forever.
- `owner`: the instance id, for logs only. Nothing routes on it.

Writes use the GCS `ifGenerationMatch` precondition (one header in
`_app/db.py` `_GCSStore.write`) so a heartbeat can never clobber a rename or
a favorite written from `PUT /chats/{id}` in the same second.

Durability rules in the loop:

- `add_user` checkpoints immediately. No message is ever lost.
- The assistant turn is checkpointed before its tools run, not after.
- On cancel (stop, SIGTERM, budget), the loop writes a `tool_result` for
  every in-flight `tool_use` with `"Interrupted: <reason>"`, `is_error: true`,
  checkpoints, and sets `run.status`. History on disk stays API-valid and
  the next user message resumes from the exact step. A SIGTERM handler in
  `_app/main.py` `_serve` cancels all runs and waits up to 8s for their
  checkpoints (Cloud Run gives 10s).

### 3. The client watches, and polls when it cannot

`use-chat.ts`:

- Stream the `POST /chat` response as today. Track whether the terminal
  event arrived.
- If the stream ends without it, or a `409` comes back, poll
  `GET /chats/{id}` every 2s while `run.status == "running"`, replacing the
  tail of the conversation with the projected turns. Progress shows per
  completed turn. When status leaves `running`, render the final state; if
  it is `interrupted`, show "The connection dropped while the agent was
  working" with a Continue button that sends an internal continue message.
- Do the same check on page load with `?id=`, on `visibilitychange` back to
  visible, and on `online`.
- Stop calls `POST /chats/{id}/stop`. Clicking a chat in the panel and New
  Chat detach the view; they never call `abort()` on a running stream.
- Hold a Web Lock for the duration of a run. Edge does not sleep and Chrome
  does not freeze a tab that holds one; that removes most desktop drops at
  the source. On mobile also hold a Screen Wake Lock.
- One analytics event, `stream_broken`, with the error name,
  `visibilityState`, `navigator.onLine`, seconds since the last byte, and run
  duration. It tells us the cause per user instead of guessing.

`GET /chats/{id}` gains an optional `since=<raw turn index>` so a poll returns
only new turns plus meta. v1 may refetch the whole chat; a 600-turn chat is
under 150 KB.

### 4. Cloud

In `Cycls/cloud` `gcp.py` `_deploy_to_cloud_run`, for agent deployments:

- `ResourceRequirements(cpu_idle=False)`: CPU stays allocated when no request
  is open, which is what lets the task keep working after the browser drops.
  Instance-based billing; idle instances live up to 15 minutes, which covers
  every reconnect and most mobile returns. Price it from the cost view before
  flipping: agents already run mostly one request per instance.
- Default memory `2Gi` and concurrency `10` for agents (today 1Gi and 80).
  Removes the OOM class and bounds how many detached runs share an instance.

Exposed as deploy fields; `@cycls.agent` sends them.

## Failure table

| Event | Today | After |
| --- | --- | --- |
| browser connection drops (tab parked, phone locked, reload, network) | run dies, user retypes | run continues; client polls or reloads into the result |
| user presses Stop | stream aborted, run dies | `stop` endpoint, clean interrupt, history valid |
| container OOM or replaced mid-run | run dies, every run on the instance | heartbeat goes stale, chat shows `interrupted`, Continue resumes from the last checkpointed step |
| deploy | in-flight requests drained | same; SIGTERM checkpoints detached runs as `interrupted` |
| run longer than 1200s | killed | request ends, run continues, client polls |
| Cloud Run scales the instance in while a detached run is active | n/a | rare within the 15-minute idle window; ends as `interrupted`, resumable |

Bounded loss in every case: the in-flight model turn or tool batch. Never a
user message, never a completed turn.

## What the user sees

They close the laptop, come back, open the chat, and see the run still
working (per-turn updates) or the finished document. Token-level streaming
returns on their next message. "كمل" becomes a button, and mostly unnecessary.

## Order of work

1. SDK: `add_user` checkpoint, assistant turn checkpoint before tools,
   interrupted `tool_result`s on cancel, one run per chat. No infra change,
   ships alone, stops message loss and duplicate runs.
2. SDK: run as a task, registry, `run` on `index.json` with heartbeat, `stop`
   endpoint, SIGTERM handler, run budget and instance cap.
3. Client: polling fallback, visibility and page-load checks, stop endpoint,
   no aborts on navigation, Web Lock, `stream_broken` event.
4. Cloud: `cpu_idle`, memory, concurrency as deploy fields. Enable on
   super-dev, watch `stream_broken` and the cut count for a few days, then
   super and haseef.

Steps 1 to 3 without 4 already help: a detached run keeps CPU for as long as
any other request is active on the instance, and otherwise ends as
`interrupted` with precise state. Step 4 makes it complete.

## Later, if the data asks for it

- Token-level re-attach: a hot `GET /chats/{id}/stream?since=N` served from the
  owner's memory, with an owner check and `409` fallback to polling. Only
  worth it if users notice per-turn granularity after a drop.
- Lease takeover: a stale heartbeat lets another container resume the run
  without the user pressing Continue. Same state, one more code path.
- Push on completion via the existing OneSignal plugin, for runs that finish
  while nobody is attached.

## Related

- Side findings from the same investigation, filed separately: `_OVERFLOW_RE`
  in `harness/main.py` does not match SGLang's "longer than the model's
  context length" wording, so an overflowing chat errors instead of
  compacting; the OpenAI provider stubs every attached document on Modal K3.
- [ask-round-trip.md](ask-round-trip.md) for how terminal tools end a turn.
- [tool-rows.md](tool-rows.md) for the `Tool` row the loop reads.

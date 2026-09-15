# Runs — the loop outlives the request

**Status**: proposed (2026-09-09), revised 2026-09-15 against HEAD — an audit of
everything that landed since, plus an invariant scan of every chat on super and
haseef. The revision did not change the design's shape. It found that two of its
parts corrupt chats when combined, and that the corruption is already happening
at a low rate for a different reason.

Today one HTTP request does two jobs: it *is* the agent run, and it carries the
stream. `POST /chat` starts the loop inside the response generator and the events
go back on that response. When the browser's connection ends for any reason,
Starlette sends `http.disconnect`, cancels the generator, and the loop dies
mid-tool or mid-model-call. The client shows nothing. The user reloads, sees the
agent stopped, and types "كمل".

This note separates the two jobs. The run becomes a server-side task; the
connection only watches it. Nothing about how often connections drop changes; it
stops mattering.

## What the logs say

| super + haseef, 14 days | at 2026-09-07 | at 2026-09-15 |
| --- | --- | --- |
| streams closed from the client side mid-work (hypercorn `- POST /chat`) | ~245 | **388** (super 209, haseef 179) |
| of those, runs longer than 60s | ~100 | not re-measured |
| runs killed by the Cloud Run 1200s request timeout | 4 | not re-measured |
| container OOM kills at 1Gi | 7 (3 events) | **73** (super 70) |
| user messages lost because the cut came before the first checkpoint | 44 | 42 still on disk (see below) |

The loop never stops itself in these cases. Every cut is the request ending under
it. Desktop cuts are mostly the tab being parked (Edge sleeping tabs, Chrome
freezing) or the user navigating; mobile cuts are backgrounding and screen lock.
Durations are irregular, so no timer on our side, Google's, or the browser's is
involved. Cloud Run's own guidance for long requests is to "design request
handlers in such a way that they can resume from the point where they left off".

Two caveats on this table. The OOM jump is two crash-loops on one revision
(`super-00026-xld`, Sep 10 and Sep 13), not a steady rate — but during the Sep 10
window seven users sent 36 POSTs across seven chats, retrying into a service whose
containers kept dying, so container death is no longer the rare event the failure
table below once assumed. And super moved from `anthropic/claude-sonnet-4-6` to
Modal-hosted K3 through the OpenAI provider (5a21709) *after* the first window, so
the "loop never stops itself" row describes a configuration no longer deployed:
on the SGLang path an overflow error falls through `_OVERFLOW_RE` and kills the
turn. That makes the two items under Related prerequisites for the rollout, not
footnotes.

## What the chats say

An invariant scan of all 2,499 chats on the two volumes (101,160 objects), looking
for turn indices that are not contiguous and for chats whose stored history cannot
be read back as valid:

- **Two chats have holes.** super `a95500f1` lost turns 4–5 on Sep 10 — a whole
  user message and its reply. haseef `48b79700` lost turns 9–16 on Sep 14. Both
  times two runs were writing one chat: the super chat has two POSTs two seconds
  apart on one instance; the haseef chat's file timestamps are interleaved out of
  order (0–2 at 14:28:37, 17–19 at :40, 3–4 at :44), one session appending at its
  own `_saved` while another renumbered the chat underneath it.
- **The trigger is almost never armed today: 0 of 500 sampled chats** end on an
  unpaired `tool_use`. The loop writes the assistant turn and its `tool_result`s
  in one checkpoint, so disk is paired within microseconds and the repair path
  below effectively never fires.
- **42 chats hold a title and no turns at all** (30 super, 12 haseef) — the title
  is derived from the user's first message, so the message reached the server and
  never reached disk. They sit in the user's chat list, named, empty.

The mechanism behind the holes is that our read path writes. It takes three facts
to see it.

**One: the filename is the position.** A chat is one file per turn, and nothing
inside a file records where it belongs. Order is the numbering and nothing else.

```
000000.json   user: "fix my document"
000001.json   assistant: [tool_use: bash]
000002.json   user: [tool_result]
000003.json   assistant: "done"
```

**Two: reading repairs, and the repair is a delete-and-renumber.**
`load_messages` (`state.py:206`) reads the files, runs `normalize` — which strips
an assistant `tool_use` that has no matching `tool_result`, because the provider
API rejects it, and drops the message if that empties it — and then, if anything
changed, writes the repaired list back through `replace_messages` (`state.py:232`):
`delete` every turn file, then `put` the list renumbered from zero. The docstring
says it plainly: "Persists the repair via full rewrite so disk catches up."
`GET /chats/{id}` goes through this path. So do share, fork, and `/examples`,
which is unauthenticated.

**Three: a live run addresses turns by a counter it holds in memory.** `Session`
keeps `_saved`, the number of turns it has already written, and appends at it
(`append_messages(..., start_idx=self._saved)`). Renumber the files underneath it
and that counter is stale.

Put together, on the haseef chat:

1. 17 turns on disk, `000000`–`000016`. A run opens it: `_saved = 17`.
2. The run works and checkpoints → `000017`, `000018`, `000019`.
3. A GET arrives while the run is mid-batch, so a `tool_use` is unpaired.
   `normalize` drops it and the list comes back 9 long instead of 17.
4. `replace_messages` deletes `000000`–`000019` and writes `000000`–`000008`.
5. The run is still alive and still believes `_saved` is 19. Its next checkpoint
   writes `000020`, `000021`.

Disk now holds `000000`–`000008` and `000017`–`000025`. Turns 9–16 are gone, and
the out-of-order file timestamps are the fingerprint of steps 2–5 overlapping.

This matters more for what it predicts than for what it cost. Today step 3 almost
never happens — the loop writes the assistant turn and its `tool_result`s in one
checkpoint, so disk is unpaired for microseconds and `normalize` finds nothing to
change (0 of 500 chats). §2 below checkpoints the assistant turn *before* its
tools run, which leaves it unpaired for the whole length of a tool batch — seconds
to minutes — and §4 polls `GET /chats/{id}` every 2s, which walks into that window
on purpose. Written naively, the two parts together take a trigger that is armed
0% of the time and arm it for most of every run. The fix is in §2: reads stop
repairing.

Why the damage is total today, in code:

- `web/server.py` `back()` returns `StreamingResponse(encoder(func(context)))`.
  hypercorn reports ASGI 2.1, so Starlette uses the task-group path and cancels
  the generator on disconnect.
- `harness/main.py` catches the cancel only around the model stream (saving
  partial text with `[…]`). A cancel during tool execution drops the assistant
  `tool_use` turn entirely; `normalize` strips it on next load.
- the tool batch is bare `create_task` under `asyncio.wait` (`harness/main.py`),
  which cancels nothing when the waiter is cancelled: the tools of a dead run keep
  driving the browser and keep writing to the workspace.
- `state.py` `Session.add_user` appends to memory only; the first checkpoint is
  after the first tool batch. A cut before that loses the user's message — the 42.
- `client/src/hooks/use-chat.ts` retries only pre-stream failures. A stream that
  dies after first bytes ends silently; `loadChat` aborts the running stream, so
  clicking any chat in the panel kills the run.

## Non-goals

- No Redis, no new service, no event-log files. The turn files are the durable
  state; the run record is one small object beside them.
- No token-level re-attach after a drop. That needs the watcher to reach the
  container holding the run, and Cloud Run has no way to address an instance.
  Session affinity is best effort and we will not build on it. After a drop,
  progress is per completed turn; token streaming returns on the next message.
- No WebSocket. Same connection underneath, same causes.
- No change to the 1200s request timeout. Once the request only carries the
  stream, its limit no longer bounds the run.

## Design

### 1. The run is a task; the response only forwards

In `back()`, the body stream `func(context)` is consumed by a task that puts
events on a queue; the `StreamingResponse` generator reads the queue. A disconnect
cancels the reader, never the task. The task runs to the loop's own end or to the
run budget (45 minutes, then a clean interrupt).

A registry `{chat_id: Run}` per process holds the task and its status. One run per
chat, and the check is not only the registry — that is per-process, and two
containers can each open a session on one chat. The run record in §3 is the
cross-container guard: a fresh heartbeat means refuse. A second `POST /chat?id=`
against a live run answers `409 {run: {...}}` and the client falls into the
polling view. This is what the two corrupted chats needed and did not have.

`POST /chats/{chat_id}/stop` cancels the task. Stop is the only thing that
cancels; a dropped connection is not a stop.

**Only the chat routes get runs.** `back()` is registered on `/`, `/chat` and
`/chat/completions` (`web/server.py`), and the OpenAI-compatible encoder emits no
`chat_id` — so under this design an API client's disconnect would leave a detached
run nobody can stop, poll or find, holding an instance slot to the 45-minute
budget. `/chat/completions` stays request-bound and out of the registry. Its
disconnect keeps cancelling, as today.

**Detached runs are opt-in per client.** The client declares that it will poll and
will call `stop`; a client that does not is served the old behaviour, where its
disconnect cancels. Without this, the Expo app's Stop button (a local `abort()`,
`~/Desktop/code/mobile-app`) silently stops stopping the day this ships — on
exactly the platform the logs blame for the cuts. Mobile adopts the endpoint on
its own schedule and nothing breaks in between.

**The browser tool is keyed per chat, not per user.** Its remote page, cookies and
`data-cy-ref` numbering are cached per workspace subject (`browser/client.py`,
`tools/__init__.py`), so two of one user's runs share one page and one run's `open`
navigates the other's out from under it. One run per chat bounds the loop, not the
browser; key the cache by subject and chat id.

Per-instance cap on active runs (tied to memory). Beyond it, `503` with
`Retry-After`; the client retries on the next poll tick. The cap and the memory
figure in §5 decide whether this makes the OOM class better or worse, so measure
them on super-dev rather than picking them.

### 2. Writing: one writer, append-only

The turn log becomes append-only and single-writer. Four rules, in the order they
should land — the first two fix bugs that exist today and are prerequisites for
everything else, not consequences of it.

- **Readers do not repair.** `load_messages` grows `persist=False` and every HTTP
  reader uses it; normalization stays, in memory, so what the model sees is still
  valid. Only `Session.open` and the explicit truncate/regenerate path may write a
  repair back. This removes `replace_messages` from the poll, share, fork and
  `/examples`, and with it the renumbering that ate turns 4–5 and 9–16.
- **Turn writes are create-only.** Every turn file is written with a
  "must not already exist" precondition, so an append can never silently overwrite
  a slot that moved. A failure means this run's index is stale: re-read and
  continue. Silent corruption becomes a loud, recoverable error. This is one
  parameter on the turn write path, not the compare-and-swap a shared object would
  need.
- **`add_user` checkpoints immediately.** Closes the 42 lost messages.
- **The assistant turn is checkpointed before its tools run** — safe only once the
  first rule is in, because until then it is precisely the state that makes every
  reader destructive.

Then the cancel path:

- On cancel (stop, SIGTERM, budget) the loop **takes the batch back before it
  writes anything**. The tools run as tasks and `asyncio.wait` does not cancel
  them, so a bare cancel leaves them running and their side effects land
  unrecorded — the browser keeps clicking, the converter keeps writing, a
  connector keeps posting. Cancel them, wait ~2s, then write each finished tool's
  real result and `"Interrupted: <reason>"` with `is_error: true` only for the
  ones actually cancelled. Writing `Interrupted:` for a tool that completed is
  worse than losing it: the resume replays a side effect that already happened.
  Each connector call also holds its own HTTP session inside that task, so the
  cancel is what closes them. History on disk stays API-valid and the next user
  message resumes from the exact step — except for remote tool state: the browser
  page lives in the service's session, whose id is in this process's memory, so an
  interrupted `browser` result reads "the browser session ended; re-open the page"
  and the model re-opens rather than clicking a ref that no longer resolves.
- On SIGTERM, hypercorn installs its own handler and then drives the ASGI lifespan
  shutdown, so the drain is a FastAPI shutdown hook registered in `web()`, next to
  the registry — not a signal handler in `_app/main.py` `_serve`, which sees only
  a wrapped ASGI app and which the `--remote` dev services never reach (they boot
  through `_function/remote.py`). It cancels all runs and waits up to 8s for their
  checkpoints; Cloud Run gives 10s and hypercorn's `shutdown_timeout` is 60s, so
  no config change.

### 3. Run state is its own object

`chat/{id}/run`, beside the turn files — not a key on `index.json`:

```json
{"status": "running", "started": "…", "heartbeat": "…", "owner": "<instance id>"}
```

- `status`: `running` | `done` | `interrupted` | `stopped`.
- `heartbeat`: refreshed every 10s by the owning task. Readers treat a heartbeat
  older than 30s as `interrupted` whatever the stored status says, so a container
  that died mid-run never leaves a chat "running" forever.
- `owner`: for logs only. Nothing routes on it.
- `finished`, `turns`: stamped when the status leaves `running`. That transition
  is the only place that knows a run ended, so it is where the **run-finished
  event** fires — `on_run(chat_id, user, status, turns, ms)`, a plain hook on the
  agent with no opinion about what happens next. Push, email, a webhook, a row in
  a table, nothing: the deployment decides. The loop also logs it for the fleet
  view. Fires on every terminal status, not just `done` — "it finished" and "it
  stopped early" are both things a deployment may want to act on.

Its own object because `index.json` is the wrong home three times over:
`put_meta` hands the whole meta dict to the object store's custom-metadata
channel and `DB.put` rejects non-string values, so a nested `run` raises
`TypeError` as written; the meta already has six writers on an existing chat
(`add_cost`, `touch_meta`, the `list_chats` self-heal, `PUT /chats/{id}`, the
delete tombstone, trash restore), each a full read-modify-write, and a 10s
heartbeat would race all of them — most often `add_cost`, whose lost increment is
lost billing; and making that safe needs a compare-and-swap the store does not
have (`ifGenerationMatch` is a query parameter, `read` discards the generation,
`_FileStore` has no version concept, five call sites would need retry). A separate
object has one writer and needs none of it. It also stops `fork_share` inheriting
a live run record along with the rest of the meta.

### 4. Reading: the client watches, and polls when it cannot

`use-chat.ts`:

- Stream the `POST /chat` response as today. Track whether the terminal event
  arrived.
- If the stream ends without it, or a `409` comes back, poll `GET /chats/{id}`
  every 2s while `run.status == "running"`, appending new turns. When status
  leaves `running`, render the final state; if it is `interrupted`, show "The
  connection dropped while the agent was working" with a Continue button.
- Do the same on page load with `?id=`, on `visibilitychange` back to visible, and
  on `online`.
- **A detached run is visible as itself.** Once a run outlives its stream the UI
  has to say so, or a returning person cannot tell "still working" from "stopped
  and said nothing" — the complaint this note exists to fix. In the open chat, the
  composer's working state comes from `run.status`, not from a live stream, and
  reads "working in the background" when nothing is attached. In the chat list, a
  chat whose run record is `running` carries the same mark, so a person who
  switches away can see it finish. `GET /chats` already enumerates the chats;
  it returns each one's run status with them.
- **`since=<turn index>` is required, not an optimization.** `load_messages` reads
  one object per turn file, so refetching a 600-turn chat is ~600 reads every 2s
  per attached client, on instances §5 caps at concurrency 10. Payload size was
  never the constraint. The tail slice must not run the repair path: normalization
  of a slice would strip a `tool_use` whose result sits outside it.
- **A run can end waiting for the person, and the card has to come back.** `ask`,
  `confirm` and `connect` yield a `ui` event and end the turn; only the model's ack
  is stored, and the card's approval key lived in React state. Detached runs make
  this the common case — the agent asks while nobody is attached — and today a
  reload already loses it, rendering the blocked call as a *successful* step.
  Rebuild the card in the projection from the trailing gated `tool_use`: name and
  arguments are stored and the approval key is a pure function of them.
- **`isStreaming` becomes `run.status == "running"`.** It is per-fetch today, and
  the composer's queue drains on its falling edge — a dropped stream would fire a
  queued message into the live run and take a `409`. Four other behaviours hang off
  the same edge (files-panel reload, canvas re-fetch key, working-loader reset,
  survey counter) and would fire once, mid-run, against a half-written workspace.
- Stop calls `POST /chats/{id}/stop` and drops the reader. Clicking a chat in the
  panel and New Chat detach the view; they never `abort()` a running stream.
  Deleting a chat with a live run stops it first — a detached run must not
  heartbeat into a deleted chat. Each run captures its chat id: the stream writes
  the last bubble with no chat guard today, so removing the `loadChat` abort would
  stream chat A's parts into chat B.
- Hold a Web Lock for the duration of a run: Edge does not sleep and Chrome does
  not freeze a tab that holds one, which removes most desktop drops at the source.
  On mobile web, a Screen Wake Lock too. Neither exists in the Expo client — that
  is the opt-in rule in §1 earning its keep.
- Analytics move with the run. `turn_completed` fires in the stream reader's
  `finally`, so once the stream ending stops meaning the turn ending it silently
  becomes "how long the browser stayed attached" — emit it when the poll sees
  status leave `running`, or tag it attached/detached. And `409`/`503` are not
  `message_failed`, whose alert fires above 2%: left alone, the rollout trips its
  own alarm. One new event, `stream_broken`, carries the error name,
  `visibilityState`, `navigator.onLine`, seconds since the last byte and run
  duration — that is how we learn the cause per user instead of guessing.

### 5. Cloud

In `Cycls/cloud` `gcp.py` `_deploy_to_cloud_run`, for agent deployments (the repo
is unchanged since this note was written, so all of this still applies as stated):

- `ResourceRequirements(cpu_idle=False)`: CPU stays allocated when no request is
  open, which is what lets the task keep working after the browser drops.
  Instance-based billing; idle instances live up to 15 minutes. Price it from the
  cost view before flipping: agents already run mostly one request per instance.
- Default memory `2Gi` and concurrency `10` for agents (today 1Gi and 80). 73 OOM
  kills in 14 days at 1Gi, before detached runs, MCP schemas and browser sessions
  start sharing an instance. Measure the real per-run footprint on super-dev and
  set the per-instance cap from it.

Exposed as deploy fields; `@cycls.agent` sends them.

Note what this does and does not buy. A detached run is no longer *cancelled* by
the disconnect; it is not *guaranteed to finish*. It lives as long as Cloud Run
keeps the instance warm, and if the instance goes away the run resumes from its
last checkpoint rather than completing.

## Failure table

| Event | Today | After |
| --- | --- | --- |
| browser connection drops (tab parked, phone locked, reload, network) | run dies, user retypes | run continues; client polls or reloads into the result |
| user presses Stop | stream aborted, run dies, tools keep running | `stop` endpoint, batch cancelled, history valid |
| two runs on one chat | interleaved writes, turns lost (2 chats so far) | second POST takes `409`; create-only writes make any residue loud |
| a reader lands mid-run | rewrites and renumbers the chat under the run | pure read |
| container OOM or replaced mid-run | run dies, every run on the instance | heartbeat goes stale, chat shows `interrupted`, Continue resumes from the last checkpointed step |
| deploy | in-flight requests drained | same; the shutdown hook checkpoints detached runs as `interrupted` |
| run longer than 1200s | killed | request ends, run continues, client polls |
| Cloud Run scales the instance in while a detached run is active | n/a | ends as `interrupted`, resumable |

Bounded loss in every case: the in-flight model turn or tool batch, plus any
remote state it held (today, only the browser page). Never a user message, never
a completed turn.

## What the user sees

They close the laptop, come back, open the chat, and see the run still working
(per-turn updates, marked as running in the background) or the finished document.
If they left the tab entirely, whatever the deployment hung off the run-finished
event reaches them.
Token-level streaming returns on their next message. "كمل" becomes a button, and
mostly unnecessary.

## Order of work

1. **Stop corrupting chats.** Readers do not repair; create-only turn writes;
   `add_user` checkpoints; one run per chat. No infra change, no detachment —
   these fix live bugs (two chats with holes, 42 lost messages, the duplicate-POST
   case) and every later step depends on them. Re-run the invariant scan
   afterwards as the regression check.
2. **The run becomes a task**: registry plus lease, `chat/{id}/run` with
   heartbeat, `stop` endpoint, the cancel path that takes the tool batch back,
   the shutdown hook, run budget, instance cap, `/chat/completions` excluded,
   opt-in flag, and the run-finished event.
3. **The client**: `since=`, polling fallback, visibility and page-load checks,
   `isStreaming` from `run.status`, the background-run indicator in the chat and
   the chat list, card rebuilt from the transcript, stop endpoint, no aborts on
   navigation, Web Lock, and the analytics moves.
4. **Cloud**: `cpu_idle`, memory, concurrency as deploy fields. Enable on
   super-dev, watch `stream_broken`, the cut count and memory for a few days, then
   super and haseef.
5. **Lease takeover**: a stale heartbeat lets the next container resume the run
   from its checkpoint instead of waiting for the user to press Continue. Sized as
   optional when OOM looked rare; at 73 in 14 days it is the difference between
   the common failure being automatic and being a manual click.

Steps 1 to 3 without 4 already help: a detached run keeps CPU for as long as any
other request is active on the instance, and otherwise ends as `interrupted` with
precise state. Step 4 makes it complete.

## Later, if the data asks for it

- Token-level re-attach: a hot `GET /chats/{id}/stream?since=N` served from the
  owner's memory, with an owner check and `409` fallback to polling. Only worth it
  if users notice per-turn granularity after a drop.
- The mobile client adopting the opt-in flag, the stop endpoint and the poll, with
  AppState in place of `visibilitychange`. Half of it is already built: on a
  mid-stream failure it foregrounds and refetches the chat.

## Related

Prerequisites for step 4, not footnotes — both sit on the path super now runs:
`_OVERFLOW_RE` in `harness/main.py` does not match SGLang's "longer than the
model's context length", so an overflowing chat errors instead of compacting; the
OpenAI provider stubs every attached document, so files never reach the model on
Modal K3.

- [ask-round-trip.md](ask-round-trip.md) for how terminal tools end a turn.
- [tool-rows.md](tool-rows.md) for the `Tool` row the loop reads.
- [plugins-connectors.md](plugins-connectors.md) for approvals and the cards.

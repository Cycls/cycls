# Video for Cycls agents

**Status: on `feat/agent-video`; in production on super-dev since 2026-10-10 (revision
`super-dev-00065-rwh`, SDK `a8f2cd1b`) for one organisation, against the production service
`https://cycls--cycls-video-web.modal.run`.**
A Cycls agent can make **short videos that move** — explainers, reels and stories,
announcements, animated stats, a deck or a design turned into a video, with on-screen text and
captions — and show them on the canvas, with **no video engine in the agent image**. The engine
([HyperFrames](https://github.com/heygen-com/hyperframes), Apache-2.0, pinned 0.8.143: HTML
compositions rendered by a seeking headless Chrome) runs in one shared service, **cycls-video**,
on Modal GPUs. The SDK ships a thin client (`cycls/_agent/video`) and the built-in `Video` tool.
First version: generated video only, silent; no footage, music or voice yet.

The agent and the person meet at one file, `videos/<name>.video.html` — the composition. The
agent writes and edits it; the canvas plays it live in a sandboxed player; `render` makes
`videos/<name>.mp4` beside it.

Enable it with `"Video"` in `allowed_tools`, `VIDEO_URL` and `VIDEO_SECRET` pointing at a
deployed cycls-video, and `VIDEO_ORGS` naming who may use it.

## How a video is made

1. Every request carries only the tool's **short form** (620 characters): what Video is for, and
   that `guide` comes first. The model calls `video {action: "guide"}`.
2. The SDK fetches the service's **contract** — how a composition is written, about 5,700
   characters — checks its Ed25519 signature, and from the next model call the tool's
   description is the short text + the contract + the actions (`tools/ondemand.py`). The guide
   also starts a GPU, so its cold start overlaps the minutes the model spends writing.
3. `write {name, html}` saves `videos/<name>.video.html` and sends it, with the images it names,
   to the service. The door prepares and lints it on CPU in a second or two. With errors the
   model gets them with fix hints and repairs with `edit` (exact find and replace). Clean, a GPU
   runs the browser check and takes nine frames; the model gets one report and **one labelled
   sheet** (times burned into the cells), and the canvas opens the composition.
4. `edit` changes it and checks again; the canvas refreshes it. `look {at, zoom}` shows frames at
   the moments asked.
5. `render` makes the MP4 (a minute or two), streams it into the workspace, opens it on the
   canvas, and asks the model for one `canvas` call so the file card survives a reload.

Measured (proof B, 2026-10-10, Kimi K3 through this loop against the dev service): the spike's
three briefs, twice each, one in Arabic, were lint-clean on the first write six times of six —
the Arabic brief asked for a font the catalogue lacks and `dir="rtl"`, and the contract steered
it — and all six were rendered; 110 to 157 s from the request to the MP4. Of ten `write` calls
each, ten carried 10,000 characters intact and ten 30,000. With Design also offered, "a reel" (in
English and Arabic) went to Video's guide and "a poster" to Design; "animate this deck" began
with a `read` of the deck. Shown a sheet with a counter stuck at 0 and Arabic letters broken
apart, K3 named both in two of three runs and fixed the Arabic in the third.

## The tool

| Action | Input | What comes back |
|---|---|---|
| `guide` | — | Loads the contract, starts the GPU, lists formats, fonts and the videos already here. |
| `write` | `name`, `html` (or `path` to adopt a file) | Saved even with errors. Lint errors with fixes; when clean, the browser check and one sheet. Opens the composition when clean. |
| `edit` | `name`, `changes: [{old, new, all?}]` | Every change or none; a miss names the closest line. Same report. Refreshes the canvas. |
| `look` | `name`, `at?: [s]`, `zoom?` | Frames at those times (up to 9); no times: the file checked again. |
| `render` | `name`, `quality?: final \| draft` | The MP4 path, length, size; opens it. Refused while lint finds errors. |
| `restore` | `name` | The version before the last save. |

Rules that shaped it:

- **A call made before `guide` runs.** Losing a composition costs minutes of writing; its reply
  says the instructions are now loaded. (Design's short form discards such a call.)
- **One sheet a reply, at most nine cells and 120 KB; text under 12,000 characters.** On Kimi K3 a
  tool's images arrive unlabelled in a later message (`providers/openai.py`), and compaction
  counts base64 at four characters a token.
- **The tool owns every write**, through `design.store.write_fig` under `design.deck.lock`:
  versioned, compare-then-replace, safe against parallel calls.
- **Names.** A name this chat made is its own: writing it again replaces it, the old file kept as
  a version. A name already in the workspace before the chat takes a suffix (`reel-2`), and the
  reply says so. A render replaces only this chat's own MP4, which goes to the trash first.
  The chat's names and its started renders are a sidecar, `.cache/video/<chat id>.json`.
- **A cut-off call never loses a render.** Stop, a dropped connection, the run budget and a
  replaced instance all look alike to a tool; the job's token is in the sidecar and its
  submission keyed, so the next `render` collects it rather than paying twice. When the service
  itself restarted under a job, the tool asks once more.
- **Time limits in the client** (the loop has none): 5 minutes for a save with its frames, 3 for
  `look`, 15 for `render`. Past them the reply says what is still running and what to call.
- **Routing.** The tool row's `prompt` adds one paragraph to the system prompt: anything that
  moves is Video; stills, slides and documents are Design; a deck becomes a video from its slides
  exported as JPEG.

## What the agent needs

- **Vision on** (the sheet is how the model sees its video), **`Editor`** (its `read` shows the
  model a composition again), and **`.max_tokens()` of at least 32,000**: a composition is written
  whole in one call, the spike's ran to 8,800 output tokens, and Kimi's reasoning counts too.
  `examples/agents/video_dev.py` uses 64,000.
- `VIDEO_ORGS`: an agent that admits anyone who signs in must not switch Video on for all of them
  by setting a URL. Entries match a workspace's organisation, its person (a personal account) or
  its workspace id; `*` is everyone (local development only).

## The canvas

A composition is the file kind `composition` (its suffix, before html, on both sides). Opened,
`GET /files/<x>.video.html?as=player` (`web/video_routes.py`) answers `{html, reason, version,
render}`, always 200: the page the service built — its bundle, the pinned player inlined beside
it, the catalogue's fonts and the composition's images inside it, nothing loaded from anywhere —
cached under `.cache/video/` by the composition's bytes, each image's path, time and size, and the
service's bundle version. `composition-view.tsx` plays it in an iframe with
`sandbox="allow-scripts"` and nothing else, under a CSP that allows no request. When the video is
rendered a Preview / Video switch shows the MP4; with no preview (the service away, errors to fix)
the MP4 shows, or a card says why.

- `refresh_canvas {path}` is a generic UI action: an open view of that file fetches it again at
  once. The Video tool sends it after every save.
- No "Open in new tab" for a composition: in its own tab its script would run on the app's origin.
- **Shares:** a shared composition is a download, whatever `as` says — never played on the app's
  origin, never sent through the service for someone else. To share a video, share its MP4.
- The loop's keep-alive `ping` used to end a live tool row after 15 s; the client now skips it.

## The contract

The text the model learns from lives with the service (`cycls-video/contract/v1.md`) and ships
with it, **signed**: whoever can change it steers every agent with Video on, so the service only
serves it; the private key stays on the machine that signs (`~/.cycls/cycls-video-contract-cv1.key`),
and `contract.py` here holds the public keys and refuses an envelope that does not verify. A turn
waits 4 s for it, `guide` 30 s; when none can be had or none verifies, the built-in copy
(`fallback.py`, generated from the signed v1) is used and the reply says so. Changing the contract
means signing it again (`scripts/contract.py sign`) and deploying the service; no agent redeploys.

## Environment

| Variable | Meaning |
|---|---|
| `VIDEO_URL` | The service's door. Unset: the tool is not offered. |
| `VIDEO_SECRET` | The key every request carries (`X-Video-Key`). |
| `VIDEO_ORGS` | Who may use it, comma separated: organisation ids, a person's id, a workspace id, or `*`. Empty: nobody. |

## The service

cycls-video (private repo `Cycls/cycls-video`, on Modal) has two units. **`web`, the door**, a
CPU container and the only one with a URL and the secret: it checks the key, enforces the limits,
prepares and lints on CPU (as a separate user with an empty environment), and holds each GPU job.
**`renderer`**, an L4 (or a T4 when Modal has no L4 free) with **no network, no Modal access and
no secrets**, whose results Modal carries only as plain data; the HyperFrames CLI and Chrome run
there as another user, in a fresh folder per job.

A restricted function's results can leave it only inline — under 2 MiB, and never from a spawned
call (Modal stores those as blobs, which such a container cannot upload). So the renderer is a
generator that says it started, then sends its report and sheet, then the MP4 in 1.5 MiB pieces,
and the door holds each job as a live call. The door is a single container keeping its jobs; a
door restart loses the jobs in flight and the SDK asks once more.

**One organisation per GPU container.** The renderer is `Renderer(slot, gen)`, each pair a pool of
at most one container; the door gives each organisation one of two slots, and its jobs queue on
its own container. A slot passes to another organisation only after the door has stopped its
container and moved its generation on, so no container serves two. Containers also retire after
50 jobs or on a capture-mode fault.

**The ledger and the allowances.** The door charges GPU seconds per organisation and per person
per day — each job and the idle tail after a container's last one, as Modal bills them — and
checks the daily allowances (4 GPU hours an organisation, 1 a person, settable in the service's
settings Dict) after lint and before any GPU work. Over them a clean composition gets a 429 with
one sentence: the client raises `OverAllowance` (an `Unavailable`), a save stays saved and opens
in the canvas with lint passed (its preview needs no GPU), and a render says why it did not run.
`GET /v1/ledger?day=YYYY-MM-DD` sums a day.

Routes the SDK calls (all need `X-Video-Key`; the SDK also sends a hashed tenant and user):
`GET /health`, `GET /v1/contract`, `POST /v1/warm`, `POST /v1/compile`, `POST /v1/jobs` (422 lint, 429 allowance),
`GET /v1/jobs/{token}?wait=25`, `GET /v1/jobs/{token}/video`. Requests carry a JSON `meta` part
and the images under hashed ASCII names; nothing waits more than 30 s.

Measured on the L4 (2026-10-10): the 30 s 1080p benchmark renders in 59 s on one worker, 37 on
two, 27 on four, 21.5 on eight, always BeginFrame on the hardware GPU (issue 4584 did not show at
eight); a 90 s video on one worker in 164 s; frames of four- and eight-worker renders match the
one-worker render exactly (issue 4435 did not show); colour bars come out within 3/255 (a static
ffmpeg in place of Debian's, issue 4899). A warm check and nine frames take about 22 s for 30 s of
video. A cold renderer took 32 s when its image was already on the host, and about four minutes
twice when Modal had no L4 free.

Its own notes: `cycls-video/docs/quirks.md` (what HyperFrames gets wrong, the proofs, the upgrade
checklist) and its README.

## Where the code is

| Path | What |
|---|---|
| `cycls/_agent/video/client.py` | The door's API: contract, warm, compile, submit, long-poll, the MP4 streamed to disk. |
| `cycls/_agent/video/contract.py`, `fallback.py` | The signed contract, verified; the built-in copy. |
| `cycls/_agent/video/tool.py` | The short and the whole form; `video_called`; the routing paragraph. |
| `cycls/_agent/video/run.py` | The executor. |
| `cycls/_agent/video/files.py`, `media.py`, `report.py` | Names and the sidecar; the images sent; the reply. |
| `cycls/_agent/tools/ondemand.py` | The seam: a tool short until a chat uses it, swapped in by the loop; its start warms the GPU. |
| `cycls/_agent/web/video_routes.py` | `?as=player`. |
| `client/src/components/composition-view.tsx` | The sandboxed player. |
| `tests/agent/video_test.py`, `scenarios/test_video_live.py` | Mocked and live tests. |
| `examples/agents/video_dev.py` | The agent it is built against. |

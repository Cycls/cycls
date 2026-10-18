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

## Sound (protocol 2; in production on super-dev since 2026-10-10, revision `super-dev-00066-t44`, SDK `91f07aac`)

Version 2 adds a voice-over and music. The SDK speaks protocol 2 (`X-Video-Proto: 2`); the service
answers protocol 1 exactly as before and serves each agent the contract for its protocol, so the
production agent is taught nothing it cannot make until it runs this SDK.

- `voice {name, text, voice?, language?}`: the script is read aloud on the organisation's GPU (Chatterbox
  Multilingual V3, or NAMAA's Saudi voice for `voice: "saudi"`; chosen by a blind listening test, docs in
  cycls-video `docs/quirks.md`). Numbers, money and dates are read out in words; every word is timed by the
  service's aligner. Saved as `videos/voice/<name>.m4a` and `<name>.words.json` (versioned through
  `write_fig`). The reply gives each sentence's times, the word timeline and the `<audio>` and captions lines
  to use. The same name, script and voice is the same take; a take cut off is collected by the next call
  (the sidecar keeps its token).
- `music {query?}`: the library's tracks from the signed contract's data (CC0, chosen by the user), each used
  as `src="music:<id>"`. Music only when the person asks.
- Every check and render sends the composition's audio files and their word timings (`media.collect_audio`)
  and its key covers them; every reply carries the sound map (`report.sound_text`): the tracks, when each
  sentence is spoken, and notes such as a scene starting inside a word. A render reply adds the MP4's
  loudness and peak.
- The service expands `data-duck` (music dips under the voice) and `data-captions` (a captions box filled
  from the voice's words, line by line, on its clock), and gives music a length, a fade and a level. The
  preview plays one mixed track kept in step with the player; the canvas needs no change (proof P1).

## Footage (protocol 3; in production on super-dev since 2026-10-13, revision `super-dev-00073-qh9`, SDK `57357c8e`)

Version 2's second half: the person's own clips, and stock video, cut into a video. The SDK speaks
protocol 3; the service still answers 1 and 2 as before and serves contract v3 (the FOOTAGE section)
only to an agent that speaks 3.

- `footage {path}` makes a clip ready. The SDK names the clip by the sha256 of its bytes (remembered
  by path, size and time in `.cache/video/clips.json`, so a 400 MB file is hashed once), asks the
  service whether it holds it, and if not sends it **in pieces of 8 MiB**, in order, going on from
  wherever the service says it is (`client.send_clip`; a call that runs out of its four minutes says
  so, and the next one goes on). Then one `ingest` job on the organisation's GPU: the clip becomes a
  mezzanine every render reads (H.264, exactly 30 fps, a key frame a second, at most 1920 on its long
  side, standard colour; a phone's HEVC, 60 fps, HDR and sideways flag all handled) and a 640 px
  proxy the preview reads; its shots are found, its loudness measured, and what is said in it is
  written down and timed word by word (Whisper large-v3-turbo, then the service's own aligner).
- The reply is what the model cannot see or hear (`report.footage_text`): length and shape, the
  shots, **a sheet of the clip's frames**, each sentence with its times, and the `<video>` line for
  the first sentence. Asking after a clip already made ready costs no GPU and shows the same sheet.
- The transcript is written **beside the clip**, `<name>.words.json` (the shape of a voice-over's
  word timings, plus the clip's hash). It is the workspace's: a misheard word corrected there is the
  word the captions show, and a transcript for these same bytes is never written over. Replace the
  clip's bytes and the old transcript is no longer its.
- `footage {stock: "a few words", pick?, orientation?}` finds a clip on Pexels (`video/stock.py`,
  the key Design's stock photos use), saves it as `videos/footage/<words>-<id>.mp4`, makes it ready
  the same way, credits the filmmaker and lists the search's other results by number.
- In a composition a piece of a clip is `<video src="uploads/interview.mp4" data-start
  data-media-start data-duration>` at the root. Every check and render sends
  `footage: {path: sha}` and the transcripts (`media.collect_footage`), never the clip. The service
  points the element at its copy, adds the length and the `muted` or `data-has-audio` the model left
  out, and refuses a clip inside a timed scene, `loop`, or a start past the clip's end. A clip's
  sound is a track in the sound map; what is said in it feeds `data-captions` (one id, or several
  for the pieces of an interview) and `data-duck` exactly as a voice-over's words do. A cut that
  lands inside a word is pointed out with where to cut instead.
- Every reply reads the cuts back (`report.sound_text`, "Footage:"): which seconds of the video show
  which seconds of which clip. The check's sheet shows the footage itself.
- The preview page carries each piece as a cut of the clip's proxy (a `data:` address, muted; the
  sound is the one mixed track), up to about 20 MB of proxy a page; past that the canvas says to
  render a draft. `video_routes.py` keys its cache on each clip's hash and transcript, and now keeps
  at most 200 MB of pages (and no longer sweeps the chats' own sidecars, which share the folder).
- Limits: a clip up to 512 MB and 10 minutes, 8 clips a video; a rendered MP4 up to 256 MiB (was
  64: 90 s of footage came to 62 MB in proof P5).

Measured on the dev L4 (cycls-video `docs/quirks.md`, P5 and phase 8): a 10 s clip made ready in
9–16 s; English heard word for word and Arabic with 2 words in 22 wrong (both read by the service's
own voices); word times within 20–30 ms; music with nobody speaking gives no transcript. A render
with footage runs at about 2.2× the video's length (204 s for 90 s) and peaks at 9.4 GB of 16.

Decided (2026-10-13): Whisper large-v3-turbo stays, and the comparison with Cohere Transcribe Arabic is dropped; a transcript is
corrected by hand where it matters. Not done: real speech (every spoken test clip was read by the service's own voices); real
Safari; a clip's used stretch alone being sent to a renderer (the whole mezzanine goes, once a container).

In production since 2026-10-13: the service from cycls-video `acb8a16`, then super-dev on SDK `57357c8e`
(production's `12cd826e` plus the four footage commits, from a deploy tree that holds nothing else).
Checked through the real agent on 2026-10-14 (the Cycls organisation, Personal workspace): a 10.5 s
clip attached in the chat, cut with a Pexels shot over its second sentence, word-lit captions, a title
and ducked music — guide, `footage` (37 s), `music`, `footage` stock (19 s), write, edit, render (45 s),
canvas; 5.6 minutes, $0.26 of model calls; the MP4 (7.8 s, 1920x1080) played with its sound in Chrome.
Two things seen on the way:

- Video is per organisation (`VIDEO_ORGS`). In the app, "Personal" in the organisation menu is the
  person's own account, not the Cycls organisation's Personal workspace; there the tool is not
  offered, and the model tried to do the same brief in its sandbox (ffmpeg, `pip install faster-whisper`).
- `_ingest` (harness/main.py) answers an attachment `read` cannot take with "too large… use bash…
  propose a way to extract its content". With Video offered the model still went to `footage`, but
  for a clip or a sound file the note could name `footage` instead.

## The tool

| Action | Input | What comes back |
|---|---|---|
| `guide` | — | Loads the contract, starts the GPU, lists formats, fonts and the videos already here. |
| `footage` | `path`, or `stock` (+ `pick`, `orientation`); `language?` | The clip made ready: its facts, shots, a sheet of its frames, what is said with times, the `<video>` line. |
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

## The editor (protocol 4)

A person changes a video by hand inside the canvas: **Edit** on a composition opens the Cycls video
editor (HyperFrames' own editor, pinned, trimmed and made Cycls's — `cycls-video/editor/`) as a
full-page overlay; **Done** (or Escape) saves what is unsaved and brings the preview back. They can
retime and trim scenes and pieces of footage, drag and restyle titles (colours, size, the catalogue's
fonts), fix text, fix a word of the captions (the Transcript, which writes the words file the
captions come from), swap the library music and set its level, remove or split media clips, then
select something and **Ask Cycls** about it, or **Render**.

- **The session.** `POST /video/editor?path=` (`web/video_routes.py` → `video/editor.py`) sends the
  composition and what it names — the images, audio, words files and clips a check sends — to the
  service's Editor (`VIDEO_EDITOR_URL`), which answers `{sid, url}`; the canvas embeds `url`
  (`/s/<sid>/`, the session's random id is the capability). The reply's `versions` are the versions
  of the files the editor may write back: the composition and its words files.
- **Saves.** The editor's page (`video-editor-view.tsx`) writes each `saved` with `PUT /files?base=`
  only to the composition it opened and to the words files the session was given (checked for shape
  and size). `.video.html` and `.words.json` are versioned files like a design's `.fig`: `GET`
  serves `X-Version`, a write goes through `design.store.write_fig` (what it replaces is kept as a
  version), a stale base is a 412 and the conflict dialog (Load the latest / Keep mine); a
  composition is at most 400,000 bytes.
- **What the editor may change** is decided on the service, at every write (the guard,
  `cycls-video/node/editor-source.mjs`): timing, level, position, size, colour, catalogue type, text,
  media clips — never scripts, styles or the page's head, never what the preview adds.
- **The agent and the person.** The agent's `edit` writes against the version it read and, on a
  412, reads and applies once more; a match that fails after a save from the editor says to read the
  file again (a save from the editor writes the file afresh). After the agent's save,
  `refresh_canvas {path, version}` reaches an open editor (`reloadVideoEditors`): what is unsaved
  goes first, then the new file is loaded. Restoring a version does the same.
- **Older videos.** A video made before protocol 4 is upgraded by the service when the editor opens
  it (animations made relative to their scene, cutaways onto their own track; `cycls-video/node/
  upgrade.mjs`), and `editor.open` keeps that upgrade as a version of its own (reason `upgrade`)
  before the session opens.
- **Selection.** `selection` and `ask` are the design editor's selection with a `time`: the
  composer's chip reads `launch.video.html · 4.2 s: title`, and the model reads
  `[Selected in videos/launch.video.html at 4.2 s: title (h1) "…"]` (`_clean_selection`,
  `_with_selection`). Ask also attaches it and focuses the composer.
- **Render.** `POST /video/render?path=&quality=` starts a render of the saved file (the editor
  waits for its saves first); `GET /video/render?path=` is its state; the MP4 replaces the one beside
  the composition (the old one to the Trash).
- **Where it shows.** `Config.public()` says `video_editor: true` when `VIDEO_EDITOR_URL` and
  `VIDEO_URL` are set; whether an organisation has Video at all is `POST /video/editor`'s answer (503
  when not). Edit is hidden on a shared page, on touch-only devices and below 900 px.

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
| `VIDEO_EDITOR_URL` | The service's Editor (`https://<workspace>--cycls-video-editor-serve.<region>.modal.run`). Unset: no Edit on a video. |

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
| `cycls/_agent/video/editor.py` | The editor's sessions (open, replace, close) and the render it asks for. |
| `cycls/_agent/web/video_routes.py` | `?as=player`; `/video/editor`, `/video/render`; which files are versioned. |
| `client/src/components/composition-view.tsx` | The sandboxed player, and Edit. |
| `client/src/components/video-editor-view.tsx` | The editor overlay: the bridge's host side, saves, conflicts, flushes. |
| `tests/agent/video_test.py`, `video_editor_test.py`, `scenarios/test_video_live.py` | Mocked and live tests. |
| `client/tests/video-editor-view.test.tsx` | The editor overlay (vitest). |
| `examples/agents/video_dev.py` | The agent it is built against. |

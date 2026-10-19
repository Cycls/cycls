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
corrected by hand where it matters. Not done: real Safari; a clip's used stretch alone being sent to a renderer (the whole
mezzanine goes, once a container). Real speech was measured on 2026-10-19 (cycls-video `scripts/speech_check.py`, `docs/quirks.md`):
English about 3 % word error, MSA about 5 % character error, Gulf dialect about 17 %, in noise, music and quiet alike; it
found one window of Emirati speech dropped in silence, fixed in the service. What the service still cannot make out comes back as
`unheard` spans, and the footage reply names them ("Nothing could be made out at 18.6–22.5 s …", `report.footage_text`), so
captions over that stretch are not taken as complete.

In production since 2026-10-19: the service from cycls-video `d9e5ff3`, then super-dev revision `super-dev-00083-snr` on SDK
`8447f909` (production's `f0bb2dcd` plus `fe4e5dde`, `3d9fd3c1`, `91948fee`, the client rebuilt; the versions change
`f849d982` is not in it — it waits for super-dev to move to this branch). A real chat on the Cycls organisation's Personal
workspace: a clip of a person reading attached, nothing said of footage; `footage` came first, then write, edit, render;
3.1 minutes, $0.23; the MP4 played with its sound and word-lit captions. Then the versions change (`f849d982`, with `17046c16`: a teammate
named from the organisation's member list, since the production sign-in token carries no name) went out on its own on top of
that, cherry-picked onto the deploy tree (docstring conflicts only): `super-dev-00085-7ch`. Checked on production: a save
through the files route kept the person (`who`, `mine: true` for them) and the file was put back as it was.

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
  for a clip the note could name `footage` instead. **Done 2026-10-19 (`fe4e5dde`):** with Video
  offered, an attached MP4, MOV, M4V or WebM is named as a clip and sent to `footage`, unread.

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

## Subtitle files

A render with something said in it writes `videos/<name>.srt` and `videos/<name>.vtt` beside the MP4
(`subtitles.py`, called from `run._render`), for platforms that take a captions file. The words are
the voice-overs' and clips' own word timings, as written (a voice-over keeps "2 minutes", "1,200");
each is placed on the video's clock from the sound map the render's submit returned (a track's start,
end and where in its file it begins, kept with the pending render so a render collected on a later
call has it too), so a clip cut into pieces gives only the words shown, when they are heard. Cues: a
sentence or a part of one, two lines of 42 characters and 6 s at most, broken at a sentence's end or
a 0.6 s pause. A render of this chat's video again replaces them (the old ones to the Trash); one
with nothing said writes none. Checked on the dev service: a voice-over placed at 0.5 s gave three
cues starting 0.55 s, 2.03 s and 5.25 s.

### In another language

The `subtitles` action (2026-10-19). `subtitles {name}` lists what is said in the composition,
sentence by sentence: the sentences of each voice-over and piece of footage that are heard (a word
inside the piece, the service's rule), in the order they are heard, each once. The model translates
them itself and sends `subtitles {name, to, lines}`, exactly as many, in order. Nothing goes to
another service.

The translation is **kept with the words**: each words file gets `translations: {<lang>:
{<sentence index>: text}}` (merged, so sentences of an earlier cut keep theirs). It is used twice,
and both follow the cut because both are placed from the words:

- **Captions on the video**: a captions box with `data-cap-lang="<lang>"` (the service, `node/audio.mjs`
  `translatedLines`) shows each translated sentence over the stretch in which it is heard (the
  longest stretch, when pieces show it in parts), in lines of whole words that share that time by
  their length, "phrase" style only (a translation has no word timings). A sentence heard with no
  translation is the error `captions_untranslated`. The editor refuses typing into such a box: "ask
  Cycls to change a line of it". The contract (v4) does not describe the attribute; the tool text
  and the action's reply do (the exact box, with the ids of the original's box). Put it in the
  contract at its next version.
- **Subtitle files**: `videos/<name>.<lang>.srt` and `.vtt`, a sentence a cue (split into parts of two
  42-character lines when long), written at every render for each language kept, and only when every
  sentence heard has its translation (the reply says when one does not). A translation sent after
  the render writes them at once, timed by the render's sound map, which is kept for the workspace
  in `.cache/video/sound/<name>.json` (so a later chat can add a language).

A sentence-by-sentence translation reads better than one made line by line: Arabic word order does
not follow English line breaks. The first version (deployed in super-dev-00090 for a few hours)
translated the `.srt`'s cues; its files are moved to the Trash at the next render, as old
translations are. Checked on the dev service: three Arabic sentences over a voice-over, the box
above the English captions, joined and right to left, each sentence on screen while it is spoken;
`subs.ar.srt` written at the render with the English file's times.

## A talking clip tidied

`footage {path, tidy: true}` adds to the reply the clip with its long pauses cut (`tidy.py`): from its
word timings (the transcript kept beside it, corrected or not), every stretch between words longer
than 0.7 s goes, each side keeping 0.15 s of breath, and so does the silence before the first word
and after the last. Every word is kept; a filler the recogniser left out sits in a pause and goes with
it. The reply gives the `<video>` pieces back to back (`piece1`…), the captions line across them, and
what was cut; the model puts them in place of one piece and tells the person. Chosen by the user
(2026-10-19): long pauses only — not filler words, not false starts. Checked on the dev service with a
real reader's 37.5 s clip with silences put in: 4 pieces, 18.1 s; the render came out 18.2 s with its
sound and subtitles, one pause left of 0.84 s (word ends run a little past the sound).

## Several sizes

One composition, several MP4s (`sizes.py`, 2026-10-19). The root lists the other sizes,
`data-sizes="vertical square"` (vertical 1080x1920, portrait 1080x1350, square 1080x1080, wide
1920x1080; the service's format names `reel`, `story`, `post-portrait`, `slide` and `WxH` are taken
too); its own size is the main one. For every check (`write`, `edit`, `template`, `look`) and render,
the SDK makes each size from the file: the root's `data-width`/`data-height`, a `data-shape="<size>"`
on the root, the viewport, and a `<style data-cycls-size>` that sets the root's box over the file's
own rule; `data-sizes` is taken off. Nothing else changes, so the scenes, timing, sound and captions
are the same everywhere (the service breaks caption lines to each size's own budget). The model
writes what one size needs as rules for it alone, `#root[data-shape="vertical"] .title {…}`; the file
as written is the main size, so the editor (which shows the file) and the main render agree.

- **Checks** run at every size at once (`run._checks`): the main reply, then "At vertical 1080x1920
  (rendered as videos/<name>.vertical.mp4 …)" with that size's browser check and sheet. The sound
  map and the reminder to look are said once. `look {size}` looks at one size. A main size that
  fails lint is answered alone.
- **Renders**: one job per size, all at once, each kept in the chat's record as `<name>@<size>` so
  a cut-off render is collected, not paid twice; any size refused by lint stops the render and the
  reply names the size. Out: `videos/<name>.mp4` and `videos/<name>.<size>.mp4`; a new render moves
  every size's old MP4 to the Trash (a size dropped from the list too). The subtitle files are written
  once, from the main size's sound map: the timing is the same in every size.
- **The editor's Render** renders every size the same way (`editor._render`).

### A crop that follows the person (auto-reframe)

`data-reframe` on a `<video>` (2026-10-19, service `cycls_video/faces.py` + `node/audio.mjs`): when a
clip is made ready, the service finds the faces in it (OpenCV's YuNet, 4 times a second on the
proxy, about 5% of the clip's length), follows the largest, and smooths it a shot at a time like a
camera operator — still while the face moves a little (3% of the width), easing after it when it
moves away, a jump at a cut. The track is kept with the clip's facts (`focus`) and goes to prepare
with them; for a reframed piece it becomes `object-position` keyframes, worked out in the page for
the box the piece is laid out in, so one track serves a vertical, square or wide box (and every
size of a video with `data-sizes`). The footage reply says when a face can be followed
(`report.footage_text`, "A face is on screen in N% of it…"). A clip with no face, or made ready
before faces were looked for, gets the warning `reframe_no_face`; such an older clip is made ready
again the next time `footage` asks for it (the store says "none" for facts without `faces_v`).
Checked on the dev service: an off-centre speaker in a wide clip, in a vertical video — reframed he
fills the frame, the centre crop showed the camera behind him and half his face.

No service change for several sizes. Checked on the dev service: a wide title card with a voice-over and word captions,
`data-sizes="vertical square"`, two rules of its own — three clean checks, three sheets (the
vertical one with the title centred and the captions higher, its own rule), three MP4s (1920x1080,
1080x1920, 1080x1080, about 0.5 MB each).

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
  goes first, then the new file is loaded. Restoring a version does the same. A video changed by
  any other file tool (the model sometimes reaches for the generic `edit`) is caught when the turn
  ends: each open editor reads its file's version and reloads only if it changed
  (`refreshVideoEditors`, beside the canvas's own refetch), so a turn that left the video alone
  keeps the person's undo history.
- **Older videos.** A video made before protocol 4 is upgraded by the service when the editor opens
  it (animations made relative to their scene, cutaways onto their own track; `cycls-video/node/
  upgrade.mjs`), and `editor.open` keeps that upgrade as a version of its own (reason `upgrade`)
  before the session opens.
- **Selection.** `selection` and `ask` are the design editor's selection with a `time`: the
  composer's chip reads `launch.video.html · 4.2 s: title`, and the model reads
  `[Selected in videos/launch.video.html at 4.2 s: title (h1) "…"]` (`_clean_selection`,
  `_with_selection`). Ask also attaches it and focuses the composer — which the full-page editor
  covers, so Ask steps the editor aside: still open and loaded (saves kept, an agent edit reaches
  it), out of sight and click-through, with **Back to the editor** at the top of the page and on the
  video's Edit button. Escape does not close it while aside; a save conflict brings it back.
  Another tab shown meanwhile (the agent opens the MP4 it rendered, or a page it wrote) leaves it
  open: the canvas keeps the video's tab mounted, hidden, while its editor is open (`held` in
  `Canvas`, told of opens and closes by `watchVideoEditors`); the video's tab closed meanwhile saves
  what is unsaved first, as a design's does.
- **Render.** `POST /video/render?path=&quality=` starts a render of the saved file (the editor
  waits for its saves first); `GET /video/render?path=` is its state; the MP4 replaces the one beside
  the composition (the old one to the Trash).
- **Where it shows.** `Config.public()` says `video_editor: true` when `VIDEO_EDITOR_URL` and
  `VIDEO_URL` are set; whether an organisation has Video at all is `POST /video/editor`'s answer (503
  when not). Edit is hidden on a shared page, on touch-only devices and below 900 px.
- **Aside is see-through, never `visibility: hidden`.** Chrome stops drawing a cross-origin frame
  hidden that way, so an agent's change loaded into an aside editor never got its preview, and the
  editor gave up after 45 s ("The preview did not reload"). Seen on production; fixed in `00df2208`,
  live as `super-dev-00080-l5q` and checked there (Ask, an agent change and render, Back after 112 s: the preview current).
- **Two people on one video** (walked 2026-10-19, 18 of 18, headless on the real page with the
  routes mounted for four test people, against the dev editor): in a team workspace each person gets
  an editor of their own; the second to save over the first meets the conflict dialog and Load the
  latest brings in the first's change; a write from outside the editor (as an agent's) stops the
  next save the same way; someone in another organisation cannot close a session by its id (the
  service checks the organisation) and someone off the team cannot reach it (404), nor read the file
  or open an editor on it. Taken off the team with the editor open, a person's saves are refused and
  the editor now says "Not saved — you no longer have access to this file" (`3d9fd3c1`; it said
  "try again"). Two things as designed, worth knowing: autosaves keep at most one version a file
  every 5 minutes whoever saves (`versions.GAP`; "Keep mine" always keeps one), and a version says
  `by: user`, not which person — in a team the history cannot say who made a change.

In production since 2026-10-18: the service from cycls-video `d6fdc9a` (the editor at
`https://cycls--cycls-video-editor-serve.us-east.modal.run`), then super-dev revision
`super-dev-00079-9cr` on SDK `f7b843c2` (production's `655170a3` plus the five video commits, the
client rebuilt) with `VIDEO_EDITOR_URL` set. Checked with a real chat on the Cycls organisation's
Personal workspace: made, rendered, Edit, a trim saved, Ask, the agent's change over it, the MP4 tab
with the editor still open, Back, Done.

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

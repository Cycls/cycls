# Transcribe

Speech in, text out, for every Cycls agent: a recording in the workspace (the `Transcribe` tool) or the
chat microphone, written down by a shared service on Modal GPUs. Strong on Gulf Arabic first, MSA and
English next; other languages work too.

Status (2026-10-20): built and tested on both sides; the service is **deployed to dev**
(`https://cycls--cycls-transcribe-dev-web.us-east.modal.run`, key and URL in
`~/.cycls/cycls-transcribe-dev.env`) **with Whisper only** — Cohere's weights need a Hugging Face token
(below). On cycls-video's real-speech clips the dev service matches cycls-video's Whisper numbers
(Arabic clean CER 4.6 %, dialect 13.8 %, English WER 4.7 %); through the SDK a 30 s Emirati voice note
(m4a) is transcribed and saved in 7.5 s, and a 12 s webm through the mic's path in 2.4 s. Branch
`feat/audio-transcription`; the service is its own repo, `E:\Cycls\cycls-transcribe` (local, not on
GitHub yet). Nothing in production.

## Why this model

Cohere Transcribe Arabic (07-2026; 2.07B parameters, BF16, Apache-2.0, gated on Hugging Face), self-hosted:

- Cohere's own figures (word error rate, lower is better): Gulf 24.4 against Whisper large-v3's 46.1;
  Najdi 26.2 / 45.0; Hijazi 16.2 / 30.6; Arabic–English mixed 27.8 / 36.9. First on the open Arabic
  leaderboard among models we could check (25.9 average).
- Our own baseline to beat, measured by cycls-video on real speech: Whisper large-v3-turbo, Gulf CER
  17.0% pooled (8.8–30.5% per clip; it writes MSA spellings), MSA CER 5.1%, English WER 3.1%.
- Self-hosted: no per-minute bill, no rate limit, nobody's audio leaves Cycls. Cohere's own API takes no
  m4a or webm and its production tier is a dedicated instance through sales.

What the model does not do, and what covers it:

| Gap | Cover |
|---|---|
| No timestamps | Our CTC aligner (wav2vec2 Arabic + English, from cycls-video) times every word |
| Invents words over silence and noise | The loudness gate in front and the guard behind (`listen.py`, from cycls-video) |
| No language detection | Whisper large-v3-turbo names it (11 of 11 on cycls-video's real speech) |
| Arabic and English only, here | Whisper writes every other language |
| At most ~35 s a piece | Windows of at most 24 s, cut at the quietest moment |
| No speakers | Not yet (pyannote community-1 later) |

## The service: cycls-transcribe

Copied from cycls-video's proven pieces (the loudness gate, windows, guard and halves heard again;
the aligner; the number reader; the job tokens; the door's key and hashed headers; the ledger).

- **Two Modal apps**: `cycls-transcribe-dev`, `cycls-transcribe`. Each has a **door** (CPU, FastAPI,
  the only secret `TRANSCRIBE_SECRET`) and **listeners** (`gpu=["L4", "A10G"]` — BF16 needs Ampere —
  no network, no Modal access, no secrets, at most 3, each stopping 5 minutes after its last part).
- **Decoding on the door**: our static ffmpeg (cycls-video's pinned build) as its own user with an
  empty environment, local files only (`-protocol_whitelist file`), audio demuxers only
  (`-format_whitelist`), stopped at 3 hours. Measured: m4a, mp3, ogg, opus, webm, flac, aac, wav, mp4,
  mkv, caf and amr all decode; a text file and a playlist naming a URL are refused.
- **Parts**: the samples go to a listener in parts of at most 5 minutes (9.6 MB; a restricted GPU input
  is at most 64 MiB), cut at the quietest 20 ms of each part's last 30 s. With `auto`, the first part
  names the language and the rest are heard in it; two parts at a time.
- **Routes**: `POST /v1/transcribe` (one request, up to 25 MB and 10 minutes, 504 `busy` past 110 s —
  the mic), `PUT /v1/assets/{sha}` in pieces + `POST /v1/jobs` + `GET /v1/jobs/{token}?wait=25`
  (long recordings), `POST /v1/warm`, `GET /v1/ledger`, `GET /health`.
- **Allowance**: per organisation 24 hours of audio a day, per person 6 (settings Dict overrides);
  past it, 429 with one sentence.
- **Output**: `{version, kind: "audio", language, duration, text, sentences, words: [{text, start, end,
  score}], engine, unheard?}` — the shape of a Video footage transcript.
- **Without Cohere's weights** (no Modal secret `cycls-transcribe-hf` at deploy) the image has Whisper
  only, and it writes Arabic and English too; `/health` says `"cohere": false`.

Deploy: `uv run python scripts/deploy.py dev` (creates the dev secret on first run and writes
`~/.cycls/cycls-transcribe-dev.env` with `TRANSCRIBE_URL` + `TRANSCRIBE_SECRET`; then 401 checks,
health, warm, a short recording and a job). Production only on the user's go.

## The SDK

- `cycls/_agent/transcribe/client.py`: `configured()`, the headers (the key; the organisation and
  the person as hashes, never raw ids), `short()` for the mic, `state` / `send` / `start` / `poll` /
  `wait` for a long recording, `warm()`. Retries only what is safe to repeat. Errors: `Unavailable`,
  `Busy` (the mic falls back), `OverAllowance`, `Refused`.
- `cycls/_agent/transcribe/tool.py`: the schema the model sees — `transcribe {path, language?: auto |
  ar | en, fresh?}`.
- `cycls/_agent/transcribe/run.py`: the executor. Sends the recording by its sha256 (remembered in
  `.cache/transcribe/shas.json`), hears it as a job (the token kept per chat; "still transcribing, call
  again" past 300 s), writes `<name>.transcript.md` (paragraphs with `[mm:ss]`) and `<name>.words.json`
  (with `sha` and `clip`) beside the recording, both as versions. The same bytes again → the saved
  transcript, no GPU; a corrected words file is kept; `fresh` hears it again.
- `tools/__init__.py`: offered when `TRANSCRIBE_URL` is set and the author lists `Transcribe`.
- `harness/main.py` `_ingest`: an attached recording (mp3, m4a, wav, ogg, opus, flac, aac, …) points the
  model at the tool; a clip (mp4, mov, webm) goes to Video's `footage` when Video is on (the note names
  Transcribe for its words alone), and to Transcribe when it is not.
- The mic: `POST /transcribe` uses the service when configured (OpenAI with a 45 s cut when a key is set
  behind it, 130 s without); `POST /transcribe/warm`; `config.voice_warm` tells the browser to warm a
  listener as recording starts; `mic_transcribed.engine` says `cycls` or `openai`. The mic sends no
  language: Whisper names it (the app's language would be wrong for an Arabic interface spoken to in
  English).

## Open

1. The Hugging Face token: accept the gate on
   https://huggingface.co/CohereLabs/cohere-transcribe-arabic-07-2026 with a Cycls account, then a Modal
   secret `cycls-transcribe-hf` with `HF_TOKEN`; `scripts/deploy.py dev` again (Cohere then goes in).
2. Prove the model: `scripts/speech_check.py dev` again (the Whisper run of 2026-10-20 is the baseline) +
   the user's own recordings (`--own DIR`); go if Gulf CER is clearly under Whisper's (13.8–17 %; target
   12 % or less) and English stays acceptable.
3. Push both repos (the service to GitHub as Cycls/cycls-transcribe) on the user's word.
4. super-dev with `TRANSCRIBE_URL` / `TRANSCRIBE_SECRET` and `Transcribe` in its tools; a real chat.
5. Production (service, then super-dev) on the user's go. Docs at docs.cycls.com.
6. Later: speakers, subtitles from `words`, Video's footage on the same service, live transcription.

# Voice input: the mic's recording made words, on the server

The composer's mic records, and the server turns the recording into text with a speech-to-text model. The browser
sends audio and gets words back. It never learns which service or model heard them, and never holds a key.

```
mic → MediaRecorder (mp4 in Safari and Chrome, webm or ogg in Firefox; m4a from the phone app)
    → POST /transcribe (multipart `file`)
    → voice.transcribe → the service's /audio/transcriptions
    → {"text": "..."} → the composer
```

## Choosing the model

`Web().voice(...)` sets it, the way `cycls.LLM` sets a chat model:

```python
cycls.Web().voice("openrouter/elevenlabs/scribe-v2", base_url="https://openrouter.ai/api/v1")   # key: OPENROUTER_API_KEY
cycls.Web().voice("groq/whisper-large-v3-turbo", base_url="https://api.groq.com/openai/v1")   # key: GROQ_API_KEY
cycls.Web().voice("mistral/voxtral-mini-latest", base_url="https://api.mistral.ai/v1", api_key=os.environ["MISTRAL_API_KEY"])
cycls.Web().voice("modal/whisper", base_url="https://….modal.run/v1", headers={"Modal-Key": ..., "Modal-Secret": ...})
cycls.Web().voice(False)   # no mic
```

- **`"vendor/model"`**: the service sees only the model. The vendor names the key in the environment.
- **`base_url`**: the service's OpenAI-compatible root. Only OpenAI's own may be left out; any other vendor without it
  is refused when the agent is built, instead of sending its key to OpenAI.
- **`api_key`**: the key, read on the build machine as the LLM's is. Without it, the server reads `VENDOR_API_KEY`
  from its environment (`GROQ_API_KEY` for `groq/…`), and with neither it sends no `Authorization` at all.
- **`headers`**: for an endpoint that authenticates otherwise: a Modal proxy, a gateway, Cloudflare Access.
- **Unset**: `openai/gpt-4o-transcribe` whenever `OPENAI_API_KEY` is there, no mic when it isn't. This was the only
  behaviour before `.voice()`, so an agent that never calls it is unchanged.

`Config.transcription` carries the setting, and `voice.resolve` turns it into what the server runs as it starts.
`Config.voice` (whether the mic shows) is set from that, never by hand.

## One shape: OpenAI's audio transcriptions API

There is no API every service speaks natively. OpenAI's `/audio/transcriptions` comes closest, and it is the one
path built: a multipart `file` and `model`, a Bearer key, `{"text": ...}` back. OpenAI, Groq, Mistral, Together and a
self-hosted Whisper (vLLM, faster-whisper servers, a Modal deployment) speak it.

ElevenLabs (`/v1/speech-to-text`, `xi-api-key`, `model_id`), Deepgram (`/v1/listen`, raw bytes, `Token` auth, and
Arabic only with `language=ar`) and Gemini (`generateContent` with the audio inline) each have their own. They reach
this path through a gateway that speaks OpenAI's shape: OpenRouter (below), or LiteLLM. No per-service adapters: less to keep
working. If one is ever needed, it is a branch in `voice.transcribe` keyed on the vendor, and nothing else moves.

## Every model through OpenRouter

OpenRouter's `/audio/transcriptions` takes this shape for every transcription model it carries (28 in October 2026),
each named `openrouter/<its id>` with `base_url="https://openrouter.ai/api/v1"` and one key, `OPENROUTER_API_KEY`:
ElevenLabs, Deepgram and AssemblyAI among them, whose own APIs aren't this shape. Super and Haseef hear the mic this
way, with ElevenLabs Scribe v2. The list and its prices: `GET https://openrouter.ai/api/v1/models?output_modalities=transcription`.

One spoken Arabic sentence through each (2026-10-27):

| | |
|---|---|
| Right, in 1-2 s | `elevenlabs/scribe-v2` (with its vowel marks), `assemblyai/universal-3-6-pro`, `openai/gpt-transcribe`, `x-ai/grok-stt-1.0`, `mistralai/voxtral-mini-transcribe-3-0`, and the open `openai/whisper-large-v3-turbo` and `nvidia/nemotron-3.5-asr-streaming-multilingual-0.6b` |
| Right, slower | `google/chirp-3` (2.5 s, no hamzas), `google/gemini-3.5-transcribe` (3.1 s), the open `qwen/qwen3-asr-1.7b` (21 s) |
| Wrong | `deepgram/nova-3` wrote it in Latin letters: it hears Arabic only when told the language, which this path doesn't send. The open `nvidia/parakeet-tdt-0.6b-v3` has no Arabic |
| Refused | `microsoft/mai-transcribe-2` (the m4a), `meta/muse-voice-transcribe-1.0` (WAV only) |

## Keeping the service private

Who transcribes is the agent's business, not the visitor's:

- `/transcribe` answers `{"text": ...}` alone. The service's own fields (its usage, its model name) are dropped.
- A failure is a plain `502 Couldn't transcribe the recording`. The service's status and the start of its reply
  go to the log as `transcription failed: …`, since its error text often names it ("see platform.openai.com").
  The browser shows its own `micFailed` message in the reader's language, not the server's words.
- Off, it is `501 Voice input isn't set up`.
- `/config` carries `voice: true|false` only. `Config.public()` leaves `transcription` out, so the model, its
  endpoint and its key never reach the page.

## The recording's format

Services read the format off the file's name. The server keeps the extension the recording came with when it is one
they take (`m4a`, `mp4`, `webm`, `ogg`, `mp3`, `wav`) and calls anything else `voice.m4a`. Before this rule, Firefox's
webm went out named `.m4a` and was refused.

## Who depends on it

- The web client: `client/src/hooks/use-speech.ts` records, posts, and reads `text`.
- The phone app: `transcribe()` in `mobile-app/src/net/api.ts` posts `audio.m4a` and reads `text`.

Both read only `text`. Keep `POST /transcribe` → `{"text"}` as it is, or change the phone app with it.

## Events

`mic_started`, `mic_stopped` (`duration_ms`, `audio_bytes`, `reason: "too_short"` under 1 KB, which is not sent),
`mic_cancelled`, `mic_transcribed` (`audio_ms`, `transcribe_ms`, `text_length`, `empty`), `mic_transcription_failed`
(`status`, 0 when the request never answered) and `mic_permission_denied` (`reason`, the browser's error name). None
of them names the model.

## Where

- `cycls/_agent/web/voice.py`: `resolve` and `transcribe`.
- `cycls/_agent/web/server.py`: the `/transcribe` route, and `Config.voice` / `Config.transcription`.
- `cycls/_agent/web/builder.py`: `Web.voice`.
- Tests in `tests/agent/web_test.py`: `test_transcribe_keeps_the_recording_format`,
  `test_voice_runs_on_any_openai_shaped_service_and_names_none`,
  `test_voice_unset_is_openai_with_its_key_and_its_model_stays_on_the_server`.

## Voice conversation: the reply read aloud

`Web().speech(...)` adds a second button beside the mic, a voice conversation. It needs the mic too (`Config.talk`
is both set). It listens, sends what was said, reads the reply aloud while it streams, then listens again:

```
tap → mic on (use-speech) → the level falls quiet 1.3 s after speech → /transcribe → sent with `spoken: true`
    → the reply streams → each finished sentence (Intl.Segmenter: knows ؟ and ۔, not ،) → POST /speak {text}
    → voice.speak → the service's /audio/speech → MP3 → played in order, 3 fetched ahead → all said: mic on again
```

```python
cycls.Web().speech("openrouter/x-ai/grok-voice-tts-1.0", voice="ara", base_url="https://openrouter.ai/api/v1")
```

The setting has the shape of `.voice()`, plus the service's `voice`. OpenRouter's `/audio/speech` carries ElevenLabs,
Gemini, Grok, MiniMax and others in this one shape (`GET /api/v1/models?output_modalities=speech`, voices in each
model's `supported_voices`). One Najdi sentence, read and heard back by Scribe v2 word for word (2026-10-28):

| | first byte | per 1M characters |
|---|---|---|
| `x-ai/grok-voice-tts-1.0` (`ara`) | 0.7 s | $15 |
| `elevenlabs/eleven-v4-turbo` (`sarah`) | 1.7 s | $40 |
| `elevenlabs/eleven-flash-v2.5` (`sarah`) | 2.8 s | $40 |
| `google/gemini-3.8-flash-tts` (`Kore`, PCM only, so not here) | 3.4 s | per token |

- **The mic is off while a reply is read**, so the speakers never answer themselves. "Stop speaking" drops what is
  left and listens; the mic doesn't hear the person over the reply.
- **What is read**: the reply's text parts without code blocks, table rows, addresses and markdown marks
  (`speakable`, kept a prefix of itself as the reply grows, so a sentence read stays read).
- **A spoken turn** reaches the agent as `context.spoken`, and the harness adds one line the model reads,
  `[Spoken: …]` (`SPOKEN`): short spoken sentences, no tables, lists, code or links. The chat shows only what was said.
  An agent may also turn its model's thinking off for these turns: the reply starts sooner.
- **Ends itself** after 30 s with nothing said, or when the mic can't start.
- `/speak` takes up to 1000 characters a call, a sentence and not a book.

## Live conversation: a speech-to-speech model as the agent's voice

`Web().realtime("openai/gpt-realtime-2.1-mini", voice="marin", instructions=...)` puts a live conversation in place
of the turn-by-turn one, whenever `OPENAI_API_KEY` (or `api_key`) is there (`Config.live`). The person can cut in.

```
tap → RTCPeerConnection + mic → POST /realtime (the offer) → voice.call opens the call at OpenAI's /realtime/calls
    with the session set on the server (model, voice, instructions, the one tool) → the answer → audio both ways
the person speaks → the voice says a word or two and calls ask_agent {request: their words, word for word}
    → sent to the chat as a spoken turn → the reply ends → function_call_output → the voice says it
```

- **Everything goes to the agent.** Left to answer small talk itself, the voice called itself ChatGPT and its words
  never reached the chat (2026-10-28). Now the chat shows the whole conversation, the agent answers as itself, and
  the voice only says its answers. `LIVE` and `ASK` in `voice.py` say so; an agent's `instructions` replace `LIVE`.
- **The page holds no key**: it posts its offer and gets the answer, OpenAI's "all-in-one" flow. No `OpenAI-Beta`
  header (the GA API).
- Measured locally (2026-10-28), from the end of the question: the voice speaks after 0.6 s, the agent's answer after
  about 6.6 s (the turn-by-turn conversation: 6.9 s, and nothing before).
- Testing without a mic: a `getUserMedia` that plays an MP3 into a MediaStreamDestination, **with faint noise under
  it**. Perfect digital silence sends nothing, so the far side never hears the speech end.

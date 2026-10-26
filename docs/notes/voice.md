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
this path through a gateway that speaks OpenAI's shape, such as LiteLLM. No per-service adapters: less to keep
working. If one is ever needed, it is a branch in `voice.transcribe` keyed on the vendor, and nothing else moves.

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

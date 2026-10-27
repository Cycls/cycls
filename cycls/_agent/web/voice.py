"""Voice input: a recording made words on the server, so the browser gets the text and never learns which model
heard it. One shape for every service, OpenAI's audio transcriptions API: OpenAI, Groq, Mistral and a self-hosted
Whisper speak it, and a gateway puts it in front of the rest."""
import os

import httpx

OPENAI = "https://api.openai.com/v1"
FORMATS = ("m4a", "mp4", "webm", "ogg", "mp3", "wav")


def resolve(setting):
    """Web.voice, as the server runs it: unset is OpenAI's model whenever its key is there; False is no mic."""
    if setting is None:
        return {"model": "openai/gpt-4o-transcribe"} if os.environ.get("OPENAI_API_KEY") else None
    return setting or None


async def transcribe(setting, audio, filename, content_type):
    """The words in `audio`. The key is the one given, else VENDOR_API_KEY from the environment."""
    vendor, model = setting["model"].split("/", 1)
    key = setting.get("api_key") or os.environ.get(f"{vendor.upper()}_API_KEY")
    # The service reads the format off the name: Firefox records webm, Safari and Chrome m4a.
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    name = f"voice.{ext}" if ext in FORMATS else "voice.m4a"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{(setting.get('base_url') or OPENAI).rstrip('/')}/audio/transcriptions",
            headers={**({"Authorization": f"Bearer {key}"} if key else {}), **(setting.get("headers") or {})},
            files={"file": (name, audio, content_type or "audio/mp4")},
            data={"model": model},
            timeout=60,
        )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json().get("text", "")

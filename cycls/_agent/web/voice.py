"""Voice input: a recording made words on the server, so the browser gets the text and never learns which model
heard it. One shape for every service, OpenAI's audio transcriptions API: OpenAI, Groq, Mistral and a self-hosted
Whisper speak it, and a gateway puts it in front of the rest. Voice output is its twin, OpenAI's audio speech API:
a reply's sentence made sound, for the voice conversation."""
import json
import os

import httpx

OPENAI = "https://api.openai.com/v1"
FORMATS = ("m4a", "mp4", "webm", "ogg", "mp3", "wav")


def resolve(setting):
    """Web.voice, as the server runs it: unset is OpenAI's model whenever its key is there; False is no mic."""
    if setting is None:
        return {"model": "openai/gpt-4o-transcribe"} if os.environ.get("OPENAI_API_KEY") else None
    return setting or None


def _service(setting, route):
    """The route's URL, its headers and the model's own name. The key is the one given, else VENDOR_API_KEY."""
    vendor, model = setting["model"].split("/", 1)
    key = setting.get("api_key") or os.environ.get(f"{vendor.upper()}_API_KEY")
    headers = {**({"Authorization": f"Bearer {key}"} if key else {}), **(setting.get("headers") or {})}
    return f"{(setting.get('base_url') or OPENAI).rstrip('/')}/audio/{route}", headers, model


async def transcribe(setting, audio, filename, content_type):
    """The words in `audio`."""
    url, headers, model = _service(setting, "transcriptions")
    # The service reads the format off the name: Firefox records webm, Safari and Chrome m4a.
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    name = f"voice.{ext}" if ext in FORMATS else "voice.m4a"
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url,
            headers=headers,
            files={"file": (name, audio, content_type or "audio/mp4")},
            data={"model": model},
            timeout=60,
        )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json().get("text", "")


async def speak(setting, text):
    """`text` read aloud, as MP3 bytes."""
    url, headers, model = _service(setting, "speech")
    body = {"model": model, "input": text, "response_format": "mp3", **({"voice": setting["voice"]} if setting.get("voice") else {})}
    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.content


# The live conversation (Web.realtime): a speech-to-speech model is the agent's voice over WebRTC. Everything the
# person says goes to the agent through one tool, word for word, so the chat shows the whole conversation, the agent
# answers as itself with its own tools, and the voice says the answer. Left to answer small talk itself, the voice
# called itself ChatGPT and its words never reached the chat (2026-10-28).
ASK = {
    "type": "function", "name": "ask_agent",
    "description": "Pass what the person just said to the agent, which answers it with its tools and keeps the chat the "
                   "person sees. Call it for everything they say, small talk too.",
    "parameters": {"type": "object", "properties": {"request": {
        "type": "string", "description": "What the person just said, word for word, in their language and dialect. "
                                          "Don't rephrase, translate or add to it."},
        "language": {"type": "string", "description": "The language they said it in, as its English name: "
                                                       "\"English\", \"Arabic\", \"French\"."}}, "required": ["request", "language"]},
}
LIVE = ("You are the voice of {name}, not an assistant of your own: never answer from yourself, never give a name of "
        "your own or say who made you. Pass everything the person says to ask_agent, word for word. While you wait, "
        "say one or two short words in their language, like \"one moment\". When the answer comes, say it as it is, "
        "in natural speech in their language, without tables, links or code. If they cut in, stop and listen.")


async def call(setting, sdp, name):
    """The answer to the browser's WebRTC offer: the server opens the call with the session set here, so the
    browser holds no key and can't change the model, its instructions or its tools."""
    vendor, model = setting["model"].split("/", 1)
    key = setting.get("api_key") or os.environ.get(f"{vendor.upper()}_API_KEY")
    session = {"type": "realtime", "model": model, "tools": [ASK], "tool_choice": "auto",
               "instructions": setting.get("instructions") or LIVE.format(name=name or "the agent"),
               "audio": {"output": {"voice": setting.get("voice") or "marin"}}}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{(setting.get('base_url') or OPENAI).rstrip('/')}/realtime/calls",
                              headers={"Authorization": f"Bearer {key}"} if key else {},
                              files={"sdp": (None, sdp), "session": (None, json.dumps(session))}, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.text

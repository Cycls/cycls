"""Transcribe for Cycls agents — speech to text through one of two engines: ElevenLabs Scribe (an API) or
the shared cycls-transcribe service (Cohere Transcribe Arabic and Whisper on Modal GPUs). The SDK ships
the clients, the tool and the microphone's route; the service is deployed once. See
docs/notes/transcribe.md."""
from .client import (Busy, OverAllowance, Refused, Unavailable, configured, engine, fallback, hear_short, poll,
                     send, service_configured, short, start, state, subject_of, wait, warm)

__all__ = ["Busy", "OverAllowance", "Refused", "Unavailable", "configured", "engine", "fallback", "hear_short",
           "poll", "send", "service_configured", "short", "start", "state", "subject_of", "wait", "warm"]

"""Transcribe for Cycls agents — a thin client to the shared cycls-transcribe service (Cohere
Transcribe Arabic and Whisper on Modal GPUs). The SDK ships this client, the tool and the
microphone's route; the service is deployed once. See docs/notes/transcribe.md."""
from .client import (Busy, OverAllowance, Refused, Unavailable, configured, poll, send, short, start, state,
                     subject_of, wait, warm)

__all__ = ["Busy", "OverAllowance", "Refused", "Unavailable", "configured", "poll", "send", "short", "start", "state",
           "subject_of", "wait", "warm"]

"""Video for Cycls agents — a thin client to the shared cycls-video service (HyperFrames on a Modal
GPU). The SDK ships this client and the tool; the service is deployed once. See docs/notes/video.md."""
from .client import (OverAllowance, Refused, Unavailable, clip_state, compile, configured, dub, fetch, fill_template,
                     forget_clip, get_contract, ingest, offered, poll, send_clip, submit, voice, wait, warm)

__all__ = ["OverAllowance", "Refused", "Unavailable", "clip_state", "compile", "configured", "dub", "fetch", "fill_template",
           "forget_clip", "get_contract", "ingest", "offered", "poll", "send_clip", "submit", "voice", "wait", "warm"]

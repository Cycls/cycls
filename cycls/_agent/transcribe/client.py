"""A thin client to the cycls-transcribe service (its own repo, on Modal): speech to text, strong on
Gulf Arabic (Cohere Transcribe Arabic for Arabic and English, Whisper for every other language, our
own aligner for word times).

Configured by the env an agent sets:
  TRANSCRIBE_URL      the service's door, https://<workspace>--cycls-transcribe-web.modal.run
  TRANSCRIBE_SECRET   the key every request carries (X-Transcribe-Key)

Unset TRANSCRIBE_URL and the Transcribe tool is simply not offered, and the chat microphone uses
OpenAI as before (when OPENAI_API_KEY is set). Who may use it is the service's to say: it keeps a
daily allowance per organisation and per person, and answers 429 past it.

Two ways in: `short()` sends a recording of up to 25 MB / 10 minutes in one request and gets its
transcript back (the microphone); a longer one is sent in pieces by the sha256 of its bytes
(`send`), heard as a job (`start`) and collected by long-polling (`wait`), because Modal cuts a web
request at 150 s. A redirect is never followed: the only host this client talks to is TRANSCRIBE_URL.
"""
import asyncio
import hashlib
import os
import time
from pathlib import Path

import httpx

PROTO = 1
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_PIECE = 8 * 1024 * 1024        # the door takes up to 16 MiB a piece
_WAIT = 25                      # seconds the door holds a poll open
SHORT_BYTES = 25 * 1024 * 1024
SHORT_SECONDS = 600
# A deploy swaps the service's containers under requests in flight: a dropped connection or a bare
# 502/503 is tried again, twice — only for calls that change nothing when made twice.
_RETRY_WAITS = (1, 3)
_GONE = (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


class Unavailable(RuntimeError):
    """The service is not configured, unreachable, paused, or refused the key."""


class Busy(Unavailable):
    """The listeners did not start in time for a short recording (the microphone falls back)."""


class OverAllowance(Unavailable):
    """Today's allowance (hours of audio) is used up, the organisation's or the person's."""


class Refused(RuntimeError):
    """The service refused the recording itself: not audio, too large or too long."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def configured():
    return bool(os.environ.get("TRANSCRIBE_URL"))


def _hash(kind, value):
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:32]


def subject_of(user):
    """The subject a workspace would have for this person (cycls/_app/db.py): "org:user", "user", or "local"."""
    if user is None:
        return "local"
    return f"{user.org_id}:{user.id}" if getattr(user, "org_id", None) else str(user.id)


def _headers(subject=None):
    h = {"X-Transcribe-Proto": str(PROTO)}
    if secret := os.environ.get("TRANSCRIBE_SECRET"):
        h["X-Transcribe-Key"] = secret
    if subject is not None:
        subject = str(subject or "local")
        h["X-Transcribe-Tenant"] = _hash("tenant", subject.partition(":")[0] or "local")
        h["X-Transcribe-User"] = _hash("user", subject)
    return h


def _subject(workspace):
    return str(getattr(workspace, "subject", "") or "local") if workspace is not None else None


def _url(path):
    url = os.environ.get("TRANSCRIBE_URL")
    if not url:
        raise Unavailable("transcription is not configured (TRANSCRIBE_URL)")
    return url.rstrip("/") + path


def _body(resp):
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _ours(resp):
    return isinstance(_body(resp), dict) and "error" in _body(resp)


def _error(resp):
    data = _body(resp)
    detail = data.get("error") if isinstance(data, dict) else None
    return RuntimeError(detail or f"transcription service {resp.status_code}: {resp.text[:200]}")


async def _request(method, path, *, workspace=None, subject=None, retry=False, timeout=_TIMEOUT, headers=None, **kw):
    headers = {**_headers(subject if subject is not None else _subject(workspace)), **(headers or {})}
    gone = None
    waits = (0, *_RETRY_WAITS) if retry else (0,)
    for wait in waits:
        if wait:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                resp = await client.request(method, _url(path), headers=headers, **kw)
        except _GONE as e:
            gone = e
            continue
        except httpx.HTTPError as e:
            raise Unavailable(f"the transcription service is unreachable: {type(e).__name__}") from e
        # The platform's own failures, not the door's (which carry {"error"}).
        if resp.status_code in (500, 502, 503, 504) and not _ours(resp):
            gone = RuntimeError(f"transcription service {resp.status_code} (no answer from the service itself)")
            continue
        break
    else:
        raise Unavailable(f"the transcription service is unreachable after {len(waits)} tries: {gone}") from gone
    if 300 <= resp.status_code < 400:
        raise Unavailable(f"the transcription service answered a redirect ({resp.status_code}); it is not followed")
    if resp.status_code == 401:
        raise Unavailable("the transcription service refused the key (TRANSCRIBE_SECRET)")
    if resp.status_code == 503 and _ours(resp):
        raise Unavailable(_body(resp).get("error") or "the transcription service is paused")
    if resp.status_code == 429 and _ours(resp):
        raise OverAllowance(_body(resp)["error"])
    return resp


async def warm(workspace=None, *, subject=None):
    """Ask for a listener to start (the microphone does as recording begins). Never raises."""
    try:
        resp = await _request("POST", "/v1/warm", workspace=workspace, subject=subject,
                              timeout=httpx.Timeout(20.0, connect=10.0))
        return resp.json() if resp.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        return {}


async def short(data, *, filename="voice.m4a", language="auto", workspace=None, subject=None, timeout=130.0):
    """A recording of up to SHORT_BYTES / SHORT_SECONDS in one request → its transcript.
    Raises Busy when the listeners were too slow to start, Refused when it is not a short
    recording this service reads."""
    files = {"file": (filename or "voice.m4a", data, "application/octet-stream")}
    resp = await _request("POST", "/v1/transcribe", workspace=workspace, subject=subject, files=files,
                          data={"language": language or "auto"}, timeout=httpx.Timeout(timeout, connect=15.0))
    if resp.status_code == 504 and _ours(resp):
        raise Busy(_body(resp)["error"])
    if resp.status_code in (413, 422):
        data = _body(resp) or {}
        raise Refused(data.get("error") or "the recording was refused", data.get("refused"))
    if resp.status_code != 200:
        raise _error(resp)
    return resp.json()


async def state(workspace, sha):
    """What the door has of a recording sent in pieces: {"state": none | partial | uploaded, "at"}."""
    resp = await _request("GET", f"/v1/assets/{sha}", workspace=workspace, retry=True)
    if resp.status_code != 200:
        raise _error(resp)
    return resp.json()


def _read_piece(path, at, size):
    with open(path, "rb") as f:
        f.seek(at)
        return f.read(size)


async def send(workspace, path, sha, *, at=0, budget=240):
    """Send a recording to the door in pieces, in order, from byte `at`; a piece the door says does
    not follow on is resumed from where the door is. Stops when `budget` seconds have passed.
    → (bytes the door has, whether that is all of it)."""
    size = Path(path).stat().st_size
    deadline, gaps = time.monotonic() + budget, 0
    while at < size:
        if time.monotonic() > deadline:
            return at, False
        data = await asyncio.to_thread(_read_piece, path, at, _PIECE)
        last = at + len(data) >= size
        resp = await _request("PUT", f"/v1/assets/{sha}", workspace=workspace, retry=True, content=data,
                              params={"offset": at, "last": int(last)}, headers={"Content-Type": "application/octet-stream"},
                              timeout=httpx.Timeout(300.0, connect=15.0))
        if resp.status_code == 409 and gaps < 5:
            at, gaps = int((_body(resp) or {}).get("at") or 0), gaps + 1
            continue
        if resp.status_code in (413, 422):
            data = _body(resp) or {}
            raise Refused(data.get("error") or "the recording was refused", data.get("refused"))
        if resp.status_code != 200:
            raise _error(resp)
        body = resp.json()
        if body.get("state") == "uploaded":
            return size, True
        at = int(body.get("at") or at + len(data))
    return at, True


async def start(workspace, sha, *, language="auto", key=None):
    """Hear a recording the door holds. → {token, eta_s}. Refused with code "missing" when the door no
    longer has it (it restarted): send it again."""
    headers = {"Idempotency-Key": key} if key else {}
    resp = await _request("POST", "/v1/jobs", workspace=workspace, retry=bool(key), headers=headers,
                          json={"sha": sha, "language": language or "auto"})
    if resp.status_code == 404 and (_body(resp) or {}).get("missing"):
        raise Refused((_body(resp) or {}).get("error") or "send the recording again", "missing")
    if resp.status_code != 200:
        raise _error(resp)
    return resp.json()


async def poll(workspace, token, wait=_WAIT):
    resp = await _request("GET", f"/v1/jobs/{token}", workspace=workspace, retry=True, params={"wait": wait},
                          timeout=httpx.Timeout(wait + 30.0, connect=15.0))
    if resp.status_code in (404, 410):
        data = _body(resp) or {}
        return {"state": data.get("state") or "gone", "error": data.get("error") or "no such job"}
    if resp.status_code != 200:
        raise _error(resp)
    return resp.json()


async def wait(workspace, token, budget):
    """Poll until the job ends or `budget` seconds pass. → the result, or the last pending state."""
    deadline = time.monotonic() + budget
    while True:
        left = deadline - time.monotonic()
        r = await poll(workspace, token, wait=max(1, min(_WAIT, int(left))))
        if r.get("state") != "pending" or time.monotonic() >= deadline - 1:
            return r

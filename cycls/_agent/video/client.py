"""Video for Cycls agents: a thin client to the cycls-video service.

The service (its own repo, cycls-video, on Modal) checks a composition, shows its frames, builds its
live preview and renders it to MP4 on a GPU. This module only talks to it; the files live in the
calling agent's workspace.

Configured by the env an agent sets:
  VIDEO_URL      the service's door, https://<workspace>--cycls-video-web.modal.run
  VIDEO_SECRET   the key every request carries (X-Video-Key)
  VIDEO_ORGS     who may use it: organisation ids (or a person's id for a personal account),
                 comma separated. Empty means nobody, "*" everybody. An agent that admits anyone
                 who signs in must not switch Video on for all of them by setting a URL.

Unset VIDEO_URL and the tool is simply not offered.

Renders outlive a request: Modal cuts a web request at 150 s with a redirect, so a job is
submitted, then collected by long-polling, and the MP4 is streamed to disk. A redirect is never
followed: the only host this client talks to is the one in VIDEO_URL.
"""
import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import httpx

PROTO = 1
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_WAIT = 25                  # seconds the door holds a poll open; it never holds one longer than 30
# A deploy of the service swaps its containers under requests in flight: a dropped connection or a
# front-end 502/503 is tried again, twice. Only for calls that change nothing when made twice
# (reads, and job submissions, which carry an idempotency key).
_RETRY_WAITS = (1, 3)
_GONE = (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


class Unavailable(RuntimeError):
    """The service is not configured, unreachable, paused, or refused the key."""


class Refused(RuntimeError):
    """The door refused a job before any GPU work: the composition has errors to fix first."""

    def __init__(self, message, findings):
        super().__init__(message)
        self.findings = findings


def configured():
    return bool(os.environ.get("VIDEO_URL"))


def _allowed():
    return {s.strip() for s in os.environ.get("VIDEO_ORGS", "").replace(";", ",").split(",") if s.strip()}


def _org(workspace):
    subject = str(getattr(workspace, "subject", "") or "")
    return subject.partition(":")[0] or "local"


def offered(workspace):
    """Is Video on for this workspace's organisation? The URL alone does not switch it on."""
    if not configured():
        return False
    allowed = _allowed()
    if "*" in allowed:
        return True
    subject = str(getattr(workspace, "subject", "") or "")
    org, _, user = subject.partition(":")
    return bool(allowed & {org, user, getattr(workspace, "ws", None)} - {"", None})


def _hash(kind, value):
    return hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:32]


def _headers(workspace=None):
    h = {"X-Video-Proto": str(PROTO)}
    if secret := os.environ.get("VIDEO_SECRET"):
        h["X-Video-Key"] = secret
    if workspace is not None:
        h["X-Video-Tenant"] = _hash("tenant", _org(workspace))
        h["X-Video-User"] = _hash("user", getattr(workspace, "subject", "") or "local")
    return h


def _url(path):
    url = os.environ.get("VIDEO_URL")
    if not url:
        raise Unavailable("video is not configured (VIDEO_URL)")
    return url.rstrip("/") + path


async def _request(method, path, *, workspace=None, retry=False, timeout=_TIMEOUT, headers=None, **kw):
    headers = {**_headers(workspace), **(headers or {})}
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
            raise Unavailable(f"the video service is unreachable: {type(e).__name__}") from e
        # The platform's own failures, not the door's (which carry {"error"}): a request that met a
        # container as it stopped came back as a bare 500 after half a minute (2026-10-10).
        if resp.status_code in (500, 502, 503, 504) and not _ours(resp):
            gone = RuntimeError(f"video service {resp.status_code} (no answer from the service itself)")
            continue
        break
    else:
        raise Unavailable(f"the video service is unreachable after {len(waits)} tries: {gone}") from gone
    if 300 <= resp.status_code < 400:
        raise Unavailable(f"the video service answered a redirect ({resp.status_code}); it is not followed")
    if resp.status_code == 401:
        raise Unavailable("the video service refused the key (VIDEO_SECRET)")
    if resp.status_code == 503 and _ours(resp):
        raise Unavailable(_body(resp).get("error") or "the video service is paused")
    return resp


def _ours(resp):
    return isinstance(_body(resp), dict) and "error" in _body(resp)


def _body(resp):
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _error(resp):
    data = _body(resp)
    detail = data.get("error") if isinstance(data, dict) else None
    return RuntimeError(detail or f"video service {resp.status_code}: {resp.text[:200]}")


async def get_contract(etag=None):
    """The signed contract with the formats, fonts and limits; None when unchanged (304)."""
    headers = {"If-None-Match": etag} if etag else {}
    resp = await _request("GET", "/v1/contract", retry=True, headers=headers, timeout=httpx.Timeout(30.0, connect=10.0))
    if resp.status_code == 304:
        return None
    if resp.status_code != 200:
        raise _error(resp)
    return {**resp.json(), "etag": resp.headers.get("etag")}


async def fill_template(workspace, template, variables):
    """A template filled with the model's variables → the composition's HTML, or Refused saying what
    to change."""
    resp = await _request("POST", "/v1/templates/fill", workspace=workspace, retry=True,
                          json={"template": template, "vars": variables}, timeout=httpx.Timeout(60.0, connect=15.0))
    if resp.status_code == 422:
        raise Refused((_body(resp) or {}).get("error") or "the variables do not fit the template", [])
    if resp.status_code != 200:
        raise _error(resp)
    return resp.json()["html"]


async def warm(workspace=None):
    """Ask for a renderer to start. Never raises: warming is a hint."""
    try:
        resp = await _request("POST", "/v1/warm", workspace=workspace, timeout=httpx.Timeout(20.0, connect=10.0))
        return resp.json() if resp.status_code == 200 else {}
    except Exception:  # noqa: BLE001
        return {}


def _parts(meta, files):
    parts = [("meta", (None, json.dumps(meta)))]
    for name, data in (files or {}).items():
        parts.append((name, (name, data, "application/octet-stream")))
    return parts


async def compile(workspace, html, images=None, files=None, *, preview=False):
    """Prepare and lint on CPU; with `preview`, the page the canvas plays."""
    meta = {"html": html, "images": images or {}, "preview": preview}
    resp = await _request("POST", "/v1/compile", workspace=workspace, retry=True, files=_parts(meta, files),
                          timeout=httpx.Timeout(120.0, connect=15.0))
    if resp.status_code != 200:
        raise _error(resp)
    return resp.json()


async def submit(workspace, kind, html, images=None, files=None, *, params=None, key=None):
    """Start a review, look or render. → {token, eta_s, times}. A repeated `key` returns the same job."""
    meta = {"kind": kind, "html": html, "images": images or {}, "params": params or {}}
    headers = {"Idempotency-Key": key} if key else {}
    resp = await _request("POST", "/v1/jobs", workspace=workspace, retry=bool(key), files=_parts(meta, files),
                          headers=headers, timeout=httpx.Timeout(120.0, connect=15.0))
    if resp.status_code == 422:
        data = _body(resp) or {}
        raise Refused(data.get("error") or "the composition has errors", data.get("findings") or [])
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


async def fetch(workspace, token, dest, scratch):
    """Stream a finished render to `dest`, by way of a temp file in `scratch` that never outlives
    the call. → bytes written."""
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = scratch / f"video-{uuid.uuid4().hex}.part"
    try:
        size = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0), follow_redirects=False) as client:
            async with client.stream("GET", _url(f"/v1/jobs/{token}/video"), headers=_headers(workspace)) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    raise _error(resp)
                with open(tmp, "wb") as f:
                    async for chunk in resp.aiter_bytes(1 << 20):
                        f.write(chunk)
                        size += len(chunk)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
        return size
    finally:
        tmp.unlink(missing_ok=True)

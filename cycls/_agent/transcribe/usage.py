"""What transcription an organisation and a person used today, the allowance checked against it, and one
log line per transcription — whatever engine heard it.

The cycls-transcribe service keeps its own ledger, but ElevenLabs keeps none of ours: without this an
agent open to anyone who signs in would transcribe without limit on the account's bill. So the SDK
counts seconds of audio per organisation and per person per day (UTC) in the organisation's own `.usage`
store, refuses a new transcription once either is used, and logs each one (`level: "transcribe"`:
engine, route, seconds, time taken) for `cycls sql`.

Allowances, in hours of audio a day (env): TRANSCRIBE_DAILY_HOURS_ORG (default 24) and
TRANSCRIBE_DAILY_HOURS_USER (default 6); 0 means no limit. A recording is checked before it is heard and
charged its real length after, so the last one of a day can run past the allowance; never by more than
one recording.
"""
import asyncio
import datetime
import os

from ..logs import log

DEFAULT_HOURS = {"org": 24.0, "user": 6.0}
_lock = asyncio.Lock()


def _hours(kind):
    raw = os.environ.get(f"TRANSCRIBE_DAILY_HOURS_{kind.upper()}")
    try:
        return float(raw) if raw not in (None, "") else DEFAULT_HOURS[kind]
    except ValueError:
        return DEFAULT_HOURS[kind]


def day(now=None):
    return (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%d")


def _who(subject):
    subject = str(subject or "local")
    return subject.partition(":")[0] or "local", subject


def _db(subject, volume, base):
    from cycls._app.db import DB, workspace

    org, _ = _who(subject)
    return DB(workspace(org, volume, base=base, slot=".usage"))


def store_of(ws):
    """(subject, volume, base) for a workspace, or None when it has no store (a test's stand-in)."""
    subject, base = getattr(ws, "subject", None), getattr(ws, "base", None)
    try:
        volume = ws.volume
    except (AttributeError, IndexError, TypeError):
        return None
    return (subject, volume, base) if subject and base else None


def _keys(subject, when):
    org, person = _who(subject)
    return f"transcribe/{when}/org", f"transcribe/{when}/people/{person.replace(':', '_')}"


async def refusal(subject, volume, base):
    """None while today's allowances hold, else the one sentence the person reads."""
    db = _db(subject, volume, base)
    org_key, person_key = _keys(subject, day())
    for kind, key, who in (("org", org_key, "This organisation has"), ("user", person_key, "You have")):
        limit = _hours(kind)
        if limit <= 0:
            continue
        row = await db.get(key, {}) or {}
        if float(row.get("audio_s") or 0) >= limit * 3600:
            return (f"{who} transcribed today's allowance ({limit:g} hours of audio); "
                    "it starts again at midnight UTC.")
    return None


async def charge(subject, volume, base, *, seconds, engine, via, ms=None, user=None, chat_id=None):
    """Count a transcription (`seconds` of audio) for today, and log it. Never raises: bookkeeping."""
    log("transcribe", user=user, chat_id=chat_id, engine=engine, via=via, audio_s=round(float(seconds or 0), 1), ms=ms,
        subject_org=_who(subject)[0])
    try:
        db = _db(subject, volume, base)
        async with _lock:
            for key in _keys(subject, day()):
                row = await db.get(key, {}) or {}
                row["audio_s"] = round(float(row.get("audio_s") or 0) + max(0.0, float(seconds or 0)), 2)
                row["jobs"] = int(row.get("jobs") or 0) + 1
                by = dict(row.get("by_engine") or {})
                by[engine] = round(float(by.get(engine) or 0) + max(0.0, float(seconds or 0)), 2)
                row["by_engine"] = by
                await db.put(key, row)
    except Exception as e:  # noqa: BLE001 - a lost count never fails a transcription
        log("warn", user=user, chat_id=chat_id, message=f"transcribe usage not counted: {type(e).__name__}: {str(e)[:120]}")

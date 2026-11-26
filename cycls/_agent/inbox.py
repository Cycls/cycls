"""A person's notifications (docs/rfc-notifications.md): one inbox across every workspace they are in, the newest
30, when they last opened it, and how each kind reaches them away from the app (their picks). `notify` writes it and
pushes; the bell reads it, and opening a chat reads what it has about that chat."""
import asyncio, secrets, uuid
from datetime import datetime, timezone

import httpx

from cycls._app.auth import User
from cycls._app.db import DB, workspace
from cycls._agent import activity, state, webpush
from cycls._agent.logs import log

KEEP = 30   # a bell shows what is recent; the chats keep the rest
HOLD = 10   # seconds a mention waits: whoever has the chat open reads it by then (it looks every 3), and is not told
_LATER = set()
PICKS = {"mention": "push", "away": "push", "routine": "push"}   # each kind's way out of the app until picked: push, or off
_PUSH = {}   # OneSignal's app id and REST key, and the agent's id, when the server has them

_SAID = {   # what a push says: who and what, never the message
    "mention": ("{name} mentioned you", "إشارة إليك من {name}"),
    "reply": ("{name} replied to you", "رد عليك من {name}"),
    "done": ("Your task is done", "انتهت مهمتك"),
    "asks": ("A question about your task", "سؤال عن مهمتك"),
    "approve": ("Your task needs your OK", "مهمتك تنتظر موافقتك"),
    "failed": ("Your task stopped", "توقفت مهمتك"),
    "routine": ("{name} has something new", "جديد من {name}"),   # a routine's: its name only
    "stuck": ("{name} could not run", "تعذّر تشغيل {name}"),
    "paused": ("{name} is paused", "أُوقف {name} مؤقتًا"),
}


def push_with(app_id, key, agent):
    """Set once by the server: with no key, nothing is pushed and the bell still has it all."""
    _PUSH.update(app_id=app_id, key=key, agent=agent)


def _db(org, pid, volume, base):
    """Beside their workspaces, not in one: it reaches them in whichever they open."""
    return DB(workspace(pid if org == pid else f"{org}:{pid}", volume, base=base, slot=".inbox"))


async def notify(ws, people, kind, *, name=None, origin=None, **item):
    """One item into each person's inbox, and a push to those whose pick for it is push. It never fails its caller: a
    write or a push that fails is logged."""
    org = ws.subject.partition(":")[0]
    row = {"id": secrets.token_hex(6), "kind": kind, "ws": ws.ws, "at": datetime.now(timezone.utc).isoformat(), **item}
    pick = "mention" if kind == "reply" else kind

    async def one(pid):
        try:
            was, _ = await state._change(_db(org, pid, ws.volume, ws.base), "inbox",
                                         lambda box: {**box, "items": [row, *box.get("items", [])][:KEEP]}, {})
            return {**PICKS, **was.get("picks", {})}.get(pick) == "push" and pid
        except Exception as e:
            log("warn", message=f"inbox: {kind} for {pid} not kept: {type(e).__name__}: {e}"[:300])
    to = [p for p in await asyncio.gather(*(one(p) for p in set(people))) if p]
    if to:
        await asyncio.gather(*([_push(to, row, name, origin)] if _PUSH else []),
                             *(_browsers(p, row, name, ws) for p in to) if webpush.public() else ())


def _words(row, name):
    """What a push says, in English and Arabic: who and what, never the message."""
    return tuple(s.replace("{name}", name or n) for s, n in zip(_SAID[row.get("state") or row["kind"]], ("Someone", "شخص")))


def _opens(row):
    return "&".join(f"{k}={v}" for k, v in (("ws", row.get("ws")), ("id", row.get("chat"))) if v)


async def _browsers(pid, row, name, ws):
    """Each browser they turned push on in, by Web Push: in its language, opening the chat where it lives. One the push
    service says is gone is dropped."""
    words, at = dict(zip(("en", "ar"), _words(row, name))), _opens(row)
    try:
        devices = await _devices(pid, ws.volume, ws.base).get("devices") or []
        for origin in {d["origin"] for d in devices}:
            mine = [d for d in devices if d["origin"] == origin]
            gone = await webpush.send(mine, lambda d: {"title": words.get(d.get("lang"), words["en"]), "tag": row["id"],
                                                        "ws": row.get("ws"), "chat": row.get("chat"),
                                                        "url": f"{origin}/?{at}" if at else f"{origin}/"}, origin)
            if gone:
                await state._change(_devices(pid, ws.volume, ws.base), "devices", lambda ds: [d for d in ds or [] if d["endpoint"] not in gone], [])
    except Exception as e:
        log("warn", message=f"web push for {pid}: {type(e).__name__}: {e}"[:300])


def _devices(pid, volume, base):
    return _db(pid, pid, volume, base)   # a person's devices are theirs, whichever organization they are in


async def add_device(user, volume, base, sub, origin):
    """This browser, to push to: its push address and keys, its language and where the app is. The newest 10 are kept."""
    row = {"endpoint": str(sub["endpoint"]), "keys": {k: str(sub["keys"][k]) for k in ("p256dh", "auth")},
           "lang": "ar" if sub.get("lang") == "ar" else "en", "origin": origin, "at": datetime.now(timezone.utc).isoformat()}
    if not row["endpoint"].startswith("https://") or len(row["endpoint"]) > 1000 or not origin:
        raise ValueError("not a push address")
    await state._change(_devices(user.id, volume, base), "devices",
                        lambda ds: [row, *[d for d in ds or [] if d["endpoint"] != row["endpoint"]]][:10], [])


async def drop_device(user, volume, base, endpoint):
    """Push turned off in this browser, or its person signed out there."""
    await state._change(_devices(user.id, volume, base), "devices",
                        lambda ds: [d for d in ds or [] if d["endpoint"] != endpoint], [])


async def _push(pids, row, name, origin):
    """One OneSignal call for everyone: the words in English and Arabic (the device picks), where it opens on a phone
    and in a browser, and the item's id so a retry never sends twice. With our own Web Push on, phones only."""
    en, ar = _words(row, name)
    chat, ws = row.get("chat"), row.get("ws")
    at = _opens(row)
    body = {"app_id": _PUSH["app_id"], "include_aliases": {"external_id": sorted(pids)}, "target_channel": "push",
            "contents": {"en": en, "ar": ar}, "idempotency_key": str(uuid.uuid5(uuid.NAMESPACE_URL, row["id"])),
            "data": {"path": f"/agent/{_PUSH['agent']}" + (f"?chat={chat}" + (f"&ws={ws}" if ws else "") if chat else "")},
            **({"web_url": f"{origin}/?{at}"} if origin else {}),
            **({"isAnyWeb": False, "isChromeWeb": False, "isFirefox": False, "isSafari": False} if webpush.public() else {})}
    scheme = "Key" if _PUSH["key"].startswith("os_v2") else "Basic"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post("https://api.onesignal.com/notifications?c=push", json=body,
                                  headers={"Authorization": f"{scheme} {_PUSH['key']}"})
        if r.status_code >= 300:
            log("warn", message=f"push: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log("warn", message=f"push failed: {type(e).__name__}: {e}"[:300])


async def members(ws):
    """Who is in a team workspace: its member rows, or on General the org's people bar those left out."""
    orgdb = state.org_db(ws.subject.partition(":")[0], ws.volume, ws.base)
    rows = {k.rsplit("/", 1)[1]: m async for k, m in orgdb.scan(prefix=f"members/{ws.ws}/")}
    if ((await orgdb.get(f"workspaces/{ws.ws}")) or {}).get("builtin") == "org":
        return [p for p in await activity.people(ws) if rows.get(p, {}).get("role") != "excluded"]
    return [p for p, m in rows.items() if m.get("role") != "excluded"]


async def later(job):
    """Beside the request, not before its answer, and kept until it is done."""
    task = asyncio.create_task(job)
    _LATER.add(task)
    task.add_done_callback(_LATER.discard)


async def mentioned(ws, chat_id, said, by, origin=None):
    """A team message, `ws` its chats: whoever it names, everyone for @all, and whoever wrote the message it answers,
    never its sender, nor anyone who read it in the HOLD after it (the chat was open in front of them). Like `notify`,
    it never fails the message."""
    try:
        named = set(by.get("mentions") or ())
        if "all" in named:
            named |= set(await members(ws))
        named -= {"all", by["id"]}
        if not named:
            return
        at = datetime.now(timezone.utc).isoformat()
        await asyncio.sleep(HOLD)
        org, people = ws.subject.partition(":")[0], sorted(named)
        reads = await asyncio.gather(*(state.seen(workspace(f"{org}:{p}", ws.volume, base=ws.base, ws=ws.ws)) for p in people))
        named -= {p for p, r in zip(people, reads) if r.get(chat_id, "") >= at}
        if not named:
            return
        answered = {(by.get("reply") or {}).get("by")} & named
        item = {"by": by["id"], "chat": chat_id, "turn": by.get("turn"), "text": " ".join(state.user_text(said).split())[:140],
                "title": ((await state.get_meta(ws, chat_id)) or {}).get("title", "")}
        say = {"name": by.get("name"), "origin": origin}
        await asyncio.gather(notify(ws, named - answered, "mention", **say, **item), notify(ws, answered, "reply", **say, **item))
    except Exception as e:
        log("warn", chat_id=chat_id, message=f"inbox: a mention not told: {type(e).__name__}: {e}"[:300])


async def away(ws, pid, chat_id, status, waiting=None, origin=None):
    """A run its owner was no longer watching ended: done, with a question for them, waiting for their OK, or not."""
    try:
        how = {"ask": "asks", "confirm": "approve", "connect": "approve"}.get(waiting, "done") if status == "done" else "failed"
        title = ((await state.get_meta(ws, chat_id)) or {}).get("title", "")
        await notify(ws, [pid], "away", origin=origin, chat=chat_id, state=how, title=title)
    except Exception as e:
        log("warn", chat_id=chat_id, message=f"inbox: a run's end not told: {type(e).__name__}: {e}"[:300])


def _mine(user, volume, base):
    return _db(state.org_of(user), user.id, volume, base)


_ME = {}   # (org, person) -> what was last kept, so a chat message writes it only when it changed


async def remember(user, volume, base, tz=None):
    """Who they are, as their sign-in says, for what runs for them while they are away: a routine runs as its owner,
    with their plan. Written only when it changed; it never fails the message."""
    me = {k: v for k, v in (("id", user.id), ("org_id", user.org_id), ("plan", user.plan), ("features", user.features),
                            ("name", user.name), ("tz", tz)) if v}
    if _ME.get(key := (state.org_of(user), user.id)) == me:
        return
    try:
        await _mine(user, volume, base).put("me", me)
        _ME[key] = me
    except Exception as e:
        log("warn", message=f"inbox: who {user.id} is not kept: {type(e).__name__}: {e}"[:300])


async def person(subject, volume, base):
    """A routine's owner, as they last used the app, or None."""
    org, _, pid = subject.partition(":")
    me = await _db(org, pid or org, volume, base).get("me")
    return User(**{k: v for k, v in me.items() if k != "tz"}) if me else None


async def read(user, volume, base, limit=None):
    """Newest first, each `by` a face, and how many came since the bell was last opened, bar the chats opened since."""
    box = await _mine(user, volume, base).get("inbox") or {}
    items = box.get("items", [])
    faces = await activity.people(workspace(user, volume, base=base))
    return {"items": [{**i, "by": {"id": i["by"], **faces.get(i["by"], {})}} if i.get("by") else i for i in items[:limit]],
            "unread": _unread(box)}


def _unread(box):
    return sum(i["at"] > box.get("seen", "") and not i.get("read") for i in box.get("items", []))


async def seen(user, volume, base, chat=None):
    """The bell was opened: everything in it is read. With `chat`, that chat is open in front of them. How many are
    left unread."""
    return await _seen(_mine(user, volume, base), chat)


async def opened(ws, chat_id):
    """A chat was opened, on any device: what the bell has about it is read. It never fails the chat's load."""
    org, _, pid = ws.subject.partition(":")
    try:
        await _seen(_db(org, pid or org, ws.volume, ws.base), chat_id)
    except Exception as e:
        log("warn", chat_id=chat_id, message=f"inbox: an opened chat not read: {type(e).__name__}: {e}"[:300])


async def _seen(db, chat=None):
    if not chat:
        _, box = await state._change(db, "inbox", lambda box: {**box, "seen": datetime.now(timezone.utc).isoformat()}, {})
        return _unread(box)
    box = await db.get("inbox") or {}
    if any(i.get("chat") == chat and not i.get("read") and i["at"] > box.get("seen", "") for i in box.get("items", [])):   # written only then
        _, box = await state._change(db, "inbox", lambda b: {**b, "items": [{**i, "read": True} if i.get("chat") == chat else i
                                                                            for i in b.get("items", [])]}, {})
    return _unread(box)


async def picks(user, volume, base, changes=None):
    """How each kind reaches them away from the app; `changes` sets some first."""
    clean = {k: v for k, v in (changes or {}).items() if k in PICKS and v in ("push", "off")}
    if clean:
        await state._change(_mine(user, volume, base), "inbox", lambda box: {**box, "picks": {**box.get("picks", {}), **clean}}, {})
    return {**PICKS, **((await _mine(user, volume, base).get("inbox")) or {}).get("picks", {})}

"""Who made and changed each file, and an organization's audit log (docs/rfc-file-metadata.md).

A file's record lives in the workspace's `.files` store under its path: its last KEEP changes, and as object
metadata the summary a folder's listing reads in one LIST. People (name, picture) and the audit log live in the
org's store. Both are managed slots: no agent, bash command, file tool or file route reaches them."""
import asyncio, contextvars, os, secrets, stat, time
from datetime import date, datetime, timezone
from pathlib import Path

from cycls._app.db import DB, Conflict, workspace
from . import state
from .logs import log

KEEP = 20
TRASHED = ".trash/"   # a deleted file's record waits here for a restore; no workspace path starts with it
RETAIN_DAYS = 180     # an audit row's life
RUN_MOST = 100        # files a run's walk records one by one; the rest are one row
NOISE = {"node_modules", "__pycache__", "venv", "site-packages"}   # what a build leaves, never a person's file
_PEOPLE_TTL = 60
_people = {}          # org -> (when read, {id: {name, image}})
_swept = {}           # org store -> the day its old audit rows were last cleared

# Where the request came from (ip, client), and for a run its agent and chat: set by the server per request.
ORIGIN = contextvars.ContextVar("activity_origin", default={})


def origin_of(headers, client=None):
    """The caller's address and what it is: the web app, the phone app, or a program calling the API."""
    ua = headers.get("user-agent", "")
    ip = (headers.get("x-forwarded-for") or "").split(",")[0].strip() or getattr(client, "host", None)
    kind = ("web" if "Mozilla" in ua else "ios" if "CFNetwork" in ua or "Darwin" in ua
            else "android" if "okhttp" in ua else "api")
    return {"ip": ip, "client": kind}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _org(ws):
    return ws.subject.partition(":")[0]


def files_db(ws):
    """One store per workspace, shared by its members."""
    return DB(workspace(_org(ws), ws.volume, base=ws.base, slot=".files", ws=ws.ws))


def change(ws, action, *, agent=None, chat=None, title=None, frm=None, **more):
    """A change made for the person behind `ws`: the one who asked, when an agent made it."""
    return {"by": state.actor_of(ws.subject), "at": _now(), "action": action,
            **{k: v for k, v in (("agent", agent), ("chat", chat), ("title", title), ("from", frm), *more.items()) if v}}


def _meta(rec):
    """The summary a listing needs, flat strings: the last change (e_), the creation (c_), the file as recorded."""
    out = {f"e_{k}": v for k, v in (rec["activity"][0] if rec.get("activity") else {}).items()}
    out |= {f"c_{k}": v for k, v in (rec.get("created") or {}).items()}
    return {k: str(v) for k, v in {**out, "mtime": rec.get("mtime"), "size": rec.get("size")}.items() if v not in (None, "")}


def _file(st):
    return st is not None and stat.S_ISREG(st.st_mode)


def _stat(ws, rel):
    try: return (Path(ws.root) / rel).stat()
    except OSError: return None


async def record(ws, rel, c):
    """`c` happened to `rel`: the record keeps the newest KEEP and the file's size and time as recorded."""
    rel, db, st = rel.strip("/"), files_db(ws), _stat(ws, rel)
    for _ in range(3):
        rec, gen = await db.get_gen(rel, {})
        acts = rec.get("activity") or []
        burst = bool(acts) and _burst(acts[0], c)
        acts = [c, *acts[burst:]][:KEEP]
        rec = {"created": rec.get("created") or (c if c["action"] in ("created", "uploaded") else None), "activity": acts,
               "mtime": f"{st.st_mtime:.3f}" if _file(st) else "", "size": str(st.st_size) if _file(st) else ""}
        try:
            await db.put(rel, rec, meta=_meta(rec), **({"gen": gen} if gen else {"create": True}))
            break
        except Conflict:
            continue
    if not burst:
        await audit(ws, c, rel)


def _burst(last, c):
    """Saves in a row, by the same person the same way, within 10 minutes: one edit."""
    return (last.get("action") == c["action"] == "edited" and all(last.get(k) == c.get(k) for k in ("by", "agent", "chat"))
            and _ts(c["at"]) - _ts(last.get("at")) < 600)


async def _carry(db, src, dst):
    """Every record at `src` or under it, moved to `dst`."""
    keys = [k for k in [src, *await db.keys(prefix=f"{src}/")] if k == src or k.startswith(f"{src}/")]
    for k in keys:
        if (rec := await db.get(k)) is not None:
            new = dst + k[len(src):]
            await db.put(new, rec, meta=_meta(rec))
            await db.delete(k)


async def moved(ws, src, dst, c):
    """A rename or a move: the record goes along (a folder's, every one under it), the change on top."""
    await _carry(files_db(ws), src.strip("/"), dst.strip("/"))
    await record(ws, dst, c)


async def trashed(ws, rel, tid, c):
    """A delete: the record waits under the trash entry, so a restore brings its history back."""
    await _carry(files_db(ws), rel.strip("/"), f"{TRASHED}{tid}")
    await audit(ws, c, rel)


async def restored(ws, tid, dst, c):
    await _carry(files_db(ws), f"{TRASHED}{tid}", dst.strip("/"))
    await record(ws, dst, c)


async def purged(ws, tid=None):
    db = files_db(ws)
    if tid: await db.delete(f"{TRASHED}{tid}")
    await db.delete(f"{TRASHED}{tid}/" if tid else TRASHED)


# ---- Faces ----

async def people(ws):
    """{id: {name, image}} for the workspace's org, read at most once a minute per instance."""
    org = _org(ws)
    seen = _people.get(org)
    if seen and time.monotonic() - seen[0] < _PEOPLE_TTL:
        return seen[1]
    found = {k.split("/", 1)[1]: m async for k, m in state.org_db(org, ws.volume, ws.base).scan(prefix="people/")}
    _people[org] = (time.monotonic(), found)
    return found


async def put_person(ws, name=None, image=None):
    """The signed-in person's name and picture, as their sign-in has them."""
    row = {k: str(v)[:500] for k, v in (("name", name), ("image", image)) if v and (k != "image" or str(v).startswith("https://"))}
    pid = state.actor_of(ws.subject)
    if not row or (await people(ws)).get(pid) == row:
        return
    await state.org_db(_org(ws), ws.volume, ws.base).put(f"people/{pid}", row, meta=row)
    _people.pop(_org(ws), None)


def _who(pid, faces, me):
    return {"id": pid, **faces.get(pid, {}), **({"you": True} if pid == me else {})}


def _out(c, faces, me):
    """A change as the client reads it: `by` a person, and the chat it came from for that chat's owner alone."""
    return {**{k: v for k, v in c.items() if k not in ("by", "chat", "title")}, "by": _who(c.get("by"), faces, me),
            **({"chat": {"id": c["chat"], "title": c.get("title")}} if c.get("chat") and c.get("by") == me else {})}


def _flat(m, p):
    return {k[2:]: v for k, v in m.items() if k.startswith(p)}


def _fresh(m, mtime, size):
    """The record still describes the file: nothing changed it since without being recorded."""
    try: return abs(float(m["mtime"]) - mtime) < 1 and int(m["size"]) == size
    except (KeyError, ValueError): return False


async def folder(ws, rel_dir, entries):
    """A folder's listing, each entry with who created it and who edited it last, while its record holds."""
    rel_dir = rel_dir.strip("/")
    recs = {k: _meta(m) if "activity" in m else m   # a local store lists bodies, object storage the summaries
            async for k, m in files_db(ws).scan(glob=f"{rel_dir}/*" if rel_dir else "*")}
    if not recs:
        return entries
    faces, me = await people(ws), state.actor_of(ws.subject)
    for e in entries:
        if not (m := recs.get(f"{rel_dir}/{e['name']}" if rel_dir else e["name"])):
            continue
        if (c := _flat(m, "c_")).get("by"):
            e["created"] = _out(c, faces, me)
        if e.get("type") == "directory" or _fresh(m, _ts(e.get("modified")), e.get("size")):
            if (c := _flat(m, "e_")).get("by"):
                e["edited"] = _out(c, faces, me)
    return entries


async def info(ws, rel):
    rel = rel.strip("/")
    rec = await files_db(ws).get(rel)
    if not rec:
        return {"activity": []}
    faces, me, st = await people(ws), state.actor_of(ws.subject), _stat(ws, rel)
    acts = [_out(c, faces, me) for c in rec.get("activity") or []]
    fresh = st is not None and (stat.S_ISDIR(st.st_mode) or _fresh(rec, st.st_mtime, st.st_size))
    return {"created": _out(rec["created"], faces, me) if rec.get("created") else None,
            "edited": acts[0] if acts and fresh else None, "activity": acts}


async def note(ws, rel):
    """What an agent reading a team workspace's file is told about its last edit, or ""."""
    if not (ws.ws or "").startswith("t-"):
        return ""
    try: got = await info(ws, rel)
    except Exception: return ""
    if not (c := got.get("edited")):
        return ""
    when = datetime.fromisoformat(c["at"]).strftime("%d %b %Y")
    via = f", via {c['agent']}" + (f" in “{c['chat']['title']}”" if c.get("chat", {}).get("title") else "") if c.get("agent") else ""
    return f"[Last edited by {c['by'].get('name') or 'a member'} on {when}{via}.]\n\n"


def _ts(iso):
    try: return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError): return 0.0


# ---- After a run ----

def names(root):
    """The workspace's file paths, names only (no stat): what was there before a run."""
    root, out = Path(root), set()
    for parent, subdirs, files in os.walk(root):
        subdirs[:] = [d for d in subdirs if not d.startswith(".")]
        rel = Path(parent).relative_to(root)
        out.update((rel / f).as_posix() for f in files if not f.startswith("."))
    return out


async def after_run(ws, before, since, chat_id, agent):
    """A run that called tools changed files any way it liked, bash included: every file changed since it began,
    and not recorded by anyone else meanwhile, is its change, for its person, agent and chat."""
    from .web.routers import _walk_catalog
    entries, _ = await asyncio.to_thread(_walk_catalog, ws.root)
    start = _ts(since) - 1
    changed = [e for e in entries if e["type"] == "file" and _ts(e["modified"]) >= start
               and not NOISE & set(e["path"].split("/"))]
    if not changed:
        return
    db = files_db(ws)
    title = ((await state.get_meta(ws, chat_id)) or {}).get("title") if chat_id else None
    made = lambda action, **kw: change(ws, action, agent=agent, chat=chat_id, title=title, **kw)
    apps = sorted({e["path"].split("/")[1] for e in changed if e["path"].startswith("apps/") and e["path"].count("/") > 1})
    for slug in apps:   # an app is one thing to its team, not the files it is built from
        await audit(ws, made("app_published"), f"apps/{slug}")
    files = [e for e in changed if not e["path"].startswith("apps/")]
    for e in files[:RUN_MOST]:
        rec = await db.get(e["path"])
        if rec and _fresh(rec, _ts(e["modified"]), e["size"]):
            continue   # someone's change, recorded as it happened
        new = before is not None and e["path"] not in before
        await record(ws, e["path"], made("created" if new else "edited"))
    if len(files) > RUN_MOST:
        await audit(ws, made("files_changed", count=len(files) - RUN_MOST), "")


# ---- The audit log ----

def _audit_db(ws_or_org, volume=None, base=None):
    if isinstance(ws_or_org, str):
        return state.org_db(ws_or_org, volume, base)
    return state.org_db(_org(ws_or_org), ws_or_org.volume, ws_or_org.base)


async def audit(ws, c, target):
    """A change in an org's team workspace, one row in the org's log. Personal workspaces stay out."""
    if (ws.ws or "").startswith("t-") and ":" in ws.subject:
        await log_org(_audit_db(ws), {**c, "target": target, "ws": ws.ws})


async def acted(ctx, tool, connector, how):
    """The agent changed something outside through a connector, for its person: the tool and how it was let, no
    arguments."""
    o = ORIGIN.get()
    await audit(ctx.workspace, change(ctx.workspace, "connector_action", agent=o.get("agent"), chat=o.get("chat"),
                                      connector=connector, how=how), tool)


async def log_org(orgdb, row):
    """One row, keyed so the newest sorts first, with where it came from and never a chat's title. Never fails
    what it records; rows past RETAIN_DAYS go, once a day."""
    o = ORIGIN.get()
    key = f"audit/{10 ** 13 - int(time.time() * 1000):013d}-{secrets.token_hex(3)}"
    row = {k: str(v) for k, v in {"ip": o.get("ip"), "client": o.get("client"), **row}.items()
           if v not in (None, "") and k != "title"}
    try:
        await orgdb.put(key, row, meta=row)
        await _clear_old(orgdb)
    except Exception as e:
        log("warn", message=f"audit row not kept: {e}")


async def _clear_old(orgdb):
    where = str(getattr(orgdb._store, "root", None) or getattr(orgdb._store, "prefix", "")) or id(orgdb)
    if _swept.get(where) == date.today():
        return
    _swept[where] = date.today()
    cutoff = f"audit/{10 ** 13 - int((time.time() - RETAIN_DAYS * 86400) * 1000):013d}"
    old, _ = await orgdb.page("audit/", after=cutoff, limit=500)
    for k, _ in old:
        await orgdb.delete(k)


async def audit_page(orgdb, ws, after=None, limit=50):
    rows, nxt = await orgdb.page("audit/", after=after, limit=limit)
    faces, me = await people(ws), state.actor_of(ws.subject)
    names = {k.split("/", 1)[1]: m.get("name") async for k, m in orgdb.scan(prefix="workspaces/")}
    return [{**_out(m, faces, me), "ws_name": names.get(m.get("ws")),
             **({"member": _who(m.get("target"), faces, me)} if m.get("action", "").startswith(("member_", "role_")) else {})}
            for _, m in rows], nxt

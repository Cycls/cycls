"""Agent state primitives — chat (index + turns + Session), shares, and the
LLM-facing database tool. All built on cycls._app.db.DB.

Chat layout — one folder per chat:
    chat/{id}/index           — chat metadata (title, updatedAt, createdAt)
    chat/{id}/{turn:06d}      — one file per message, ordered

The `index` file is the sidebar's enumeration target: `db.scan(glob=
"chat/*/index")` returns one entry per chat in a single LIST round-trip.
Delete is a single subtree wipe of `chat/{id}/` — catches the index AND
every turn in one operation.

Keys:
    chat/{id}/index           — chat metadata (sidebar target)
    chat/{id}/{turn:06d}      — turns (append-only; the full transcript)
    chat/{id}/compaction      — compaction marker (summary, first_kept, cleared)
    share/{token}             — opaque share tokens (RFC003)
    <.database/ slot>         — agent-controlled KV exposed to the LLM
    <.org/ slot>              — workspaces registry + ACL (docs/workspaces.md)
"""
import asyncio, json, os, re, secrets, shutil
from datetime import datetime, timezone
from pathlib import Path

from cycls._app.db import DB, Conflict, workspace, _store
from .logs import log


# ---- Chat metadata ----

# Whitelist: alphanumeric + `_` / `-`. Rejects path separators, glob metachars
# (`*?[]{}`), dot-prefixed names, unicode tricks. UUIDs fit comfortably.
_CHAT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate(chat_id):
    if not _CHAT_ID.match(chat_id or ""):
        raise ValueError(f"Invalid chat id: {chat_id!r}")


async def get_meta(workspace, chat_id):
    _validate(chat_id)
    return await DB(workspace).get(f"chat/{chat_id}/index")


async def put_meta(workspace, chat_id, data):
    _validate(chat_id)
    await DB(workspace).put(f"chat/{chat_id}/index", data, meta=data)


# ---- Run record: `chat/{id}/run`, one object beside the turns ----
#
# Its own object, not a key on the index: the index has six writers, `put_meta`
# hands the whole dict to the object store's metadata channel (which takes only
# strings), and a heartbeat racing `add_cost` there would lose billing.

RUN_STALE = 30   # a heartbeat older than this means the container is gone


async def get_run(workspace, chat_id):
    _validate(chat_id)
    return await DB(workspace).get(f"chat/{chat_id}/run")


async def put_run(workspace, chat_id, row):
    """Flat strings only — the row rides the metadata channel so `list_runs`
    reads a whole workspace in one listing."""
    _validate(chat_id)
    row = {k: str(v) for k, v in row.items() if v is not None}
    await DB(workspace).put(f"chat/{chat_id}/run", row, meta=row)


async def list_runs(workspace):
    """chat_id -> row, in one listing. Locally the body stands in for metadata."""
    return {k.split("/")[1]: row async for k, row in DB(workspace).scan(glob="chat/*/run")}


def run_status(row):
    """What a reader sees. A heartbeat that stopped means the container died
    mid-run, whatever the stored status still says — so no chat is left reading
    `running` forever."""
    if not row:
        return None
    if row.get("status") != "running":
        return row.get("status")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["heartbeat"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return "interrupted"
    return "running" if age < RUN_STALE else "interrupted"


async def mark_first_use(user, volume, base, mode):
    """The account's first agent use, as a durable marker in the user's
    personal workspace — the one workspace every user always has, whichever
    one is active. True exactly once per account; also leaves an activated-at
    timestamp the server can consult later."""
    personal = workspace(user, volume, base=base, ws=f"u-{user.id}" if mode else None)
    db = DB(personal)
    key = "activation/first_use_at"
    if await db.get(key) is not None:
        return False
    await db.put(key, datetime.now(timezone.utc).isoformat())
    return True


async def list_chats(workspace):
    """Yield (chat_id, {title, updatedAt}) for every chat. One LIST via
    object storage; one glob+read on local FS. Rows whose custom-meta channel
    was wiped (any gcsfuse move drops it — e.g. an operator CLI migration) are
    self-healed from the body, which is canonical."""
    db = DB(workspace)
    async for key, meta in db.scan(glob="chat/*/index"):
        if not meta.get("updatedAt"):
            body = await db.get(key)
            if isinstance(body, dict) and body.get("updatedAt"):
                meta = body
                await db.put(key, body, meta={k: v for k, v in body.items() if isinstance(v, str)})
        yield key.split("/")[1], meta


async def add_cost(workspace, chat_id, delta):
    """Increment the chat's running cost total (USD). Stored as a stringified
    decimal in the index so it rides on the str:str meta contract."""
    if delta <= 0: return
    _validate(chat_id)
    existing = (await get_meta(workspace, chat_id)) or {}
    current = float(existing.get("cost") or 0)
    existing["cost"] = f"{current + delta:.6f}"
    await put_meta(workspace, chat_id, existing)


async def touch_meta(workspace, chat_id, content):
    """Stamp `updatedAt` for chat-list ordering; on the first turn also derive
    title from the user message and set createdAt. Sole writer of chat meta —
    the FE shouldn't PUT this back."""
    existing = (await get_meta(workspace, chat_id)) or {}
    now = datetime.now(timezone.utc).isoformat()
    meta = {**existing, "id": chat_id, "updatedAt": now}
    if "createdAt" not in meta:
        meta["createdAt"] = now
    if not meta.get("title"):
        text = content if isinstance(content, str) else next(
            (b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"), "")
        if (title := text.strip()[:80]):
            meta["title"] = title
    await put_meta(workspace, chat_id, meta)


# ---- Chat message log ----

def normalize(messages):
    """Return a copy of *messages* that satisfies all provider API pairing
    invariants. Strips blocks/messages that can't be repaired in place.
    The single safety net — runs at load time and before every provider
    send, so the API never sees a half-written turn regardless of how
    persistence got there.

    Invariants enforced:
      1. Assistant `tool_use` (client-side) blocks must be paired with a
         matching `tool_result` in the next user message.
      2. User `tool_result` blocks must point to a `tool_use` in the prior
         assistant message.
      3. Assistant `server_tool_use` blocks must have a matching
         `*_tool_result` block in the same content list (server-side
         tools like web_search return both blocks within one turn).

    Messages that become empty after stripping are dropped entirely.
    """
    out = []
    n = len(messages)
    for i, m in enumerate(messages):
        role = m.get("role")
        content = m.get("content")

        if role == "assistant":
            if not isinstance(content, list):
                out.append(m); continue
            next_msg = messages[i+1] if i+1 < n else None
            new_content = _normalize_assistant_blocks(content, next_msg)
            if new_content:
                out.append({**m, "content": new_content})
            continue

        if role == "user":
            if not isinstance(content, list):
                out.append(m); continue
            prior = out[-1] if out else None
            new_content = _normalize_user_blocks(content, prior)
            if new_content:
                out.append({**m, "content": new_content})
            continue

        # Unknown role: drop
    return out


def _normalize_assistant_blocks(blocks, next_msg):
    # Server-side pairing (intra-message): server_tool_use ↔ *_tool_result
    server_uses = {b["id"] for b in blocks
                   if isinstance(b, dict) and b.get("type") == "server_tool_use" and "id" in b}
    server_results = {b.get("tool_use_id") for b in blocks
                      if isinstance(b, dict)
                      and isinstance(b.get("type"), str)
                      and b["type"].endswith("_tool_result")
                      and b["type"] != "tool_result"}
    paired_server = server_uses & server_results

    # Client-side pairing: assistant tool_use ↔ tool_result in NEXT user message
    next_result_ids = set()
    if next_msg and next_msg.get("role") == "user":
        nc = next_msg.get("content")
        if isinstance(nc, list):
            next_result_ids = {b.get("tool_use_id") for b in nc
                               if isinstance(b, dict) and b.get("type") == "tool_result"}
    client_uses = {b["id"] for b in blocks
                   if isinstance(b, dict) and b.get("type") == "tool_use" and "id" in b}
    paired_client = client_uses & next_result_ids

    def keep(b):
        if not isinstance(b, dict): return True
        t = b.get("type")
        if t == "tool_use": return b.get("id") in paired_client
        if t == "server_tool_use": return b.get("id") in paired_server
        if isinstance(t, str) and t.endswith("_tool_result") and t != "tool_result":
            return b.get("tool_use_id") in paired_server
        return True

    return [b for b in blocks if keep(b)]


def _normalize_user_blocks(blocks, prior):
    prior_use_ids = set()
    if prior and prior.get("role") == "assistant":
        pc = prior.get("content")
        if isinstance(pc, list):
            prior_use_ids = {b["id"] for b in pc
                             if isinstance(b, dict) and b.get("type") == "tool_use" and "id" in b}

    def keep(b):
        if not isinstance(b, dict): return True
        if b.get("type") == "tool_result":
            return b.get("tool_use_id") in prior_use_ids
        return True

    return [b for b in blocks if keep(b)]


async def load_messages(workspace, chat_id):
    """All messages for *chat_id* in turn order, normalized to satisfy provider
    pairing invariants.

    Normalization is in memory and stays there. Nothing writes a repair back:
    renumbering turn files moves slots a live run is still appending to, which is
    how two production chats lost turns (docs/notes/runs.md), and a run killed
    mid-tool-batch now leaves an unpaired turn routinely, so that path would fire
    constantly instead of never. The writer appends past the end of disk instead
    — see `Session.open`."""
    _validate(chat_id)
    db = DB(workspace)
    # Glob `[0-9]*` selects turn files (000000, 000001, ...) — index excluded.
    messages = [msg async for _, msg in db.items(glob=f"chat/{chat_id}/[0-9]*")]
    return normalize(messages)


async def turn_end(workspace, chat_id):
    """The next free turn index. Not `len()`: a chat can have holes, and two in
    production did."""
    _validate(chat_id)
    keys = await DB(workspace).keys(glob=f"chat/{chat_id}/[0-9]*")
    return max((int(k.rsplit("/", 1)[1]) for k in keys), default=-1) + 1


async def load_tail(workspace, chat_id, since):
    """Turns from index *since* on, raw. Returns (turns, end), or (None, end) if
    the caller is ahead of us and should reload from scratch.

    No normalization: a window is a view, not a provider payload. Normalizing one
    would strip a `tool_result` whose `tool_use` sits before it, or an assistant
    turn whose result lands after it, and silently blank the poll."""
    _validate(chat_id)
    db = DB(workspace)
    idx = sorted(int(k.rsplit("/", 1)[1]) for k in await db.keys(glob=f"chat/{chat_id}/[0-9]*"))
    end = idx[-1] + 1 if idx else 0
    if since > end:
        return None, end
    want = [f"chat/{chat_id}/{i:06d}" for i in idx if i >= since]
    return [m for m in await asyncio.gather(*[db.get(k) for k in want]) if m is not None], end


async def append_messages(workspace, chat_id, messages, start_idx, *, create=True):
    """Append *messages* starting at turn index *start_idx*; returns how many
    landed.

    `create=True` refuses to overwrite an existing turn. A slot that is already
    taken means this caller's idea of the next index is stale — someone else
    wrote the chat — and overwriting is how turns were lost before; failing is
    how the caller finds out in time to re-read.

    Sequential rather than gathered: `asyncio.gather` propagates the first
    failure while its siblings keep writing, so the count would be a guess. Any
    exception carries `written` — cancellation included, since the caller still
    has to know which slots are spent."""
    _validate(chat_id)
    if not messages:
        return 0
    db = DB(workspace)
    written = 0
    for i, msg in enumerate(messages):
        try:
            await db.put(f"chat/{chat_id}/{(start_idx + i):06d}", msg, create=create)
        except BaseException as e:
            e.written = written
            raise
        written += 1
    return written


async def replace_messages(workspace, chat_id, messages):
    """Wipe and rewrite all messages for *chat_id*. Preserves the index file —
    only turns are rewritten. Renumbers from 0, so it invalidates any index a
    live `Session` is holding: the only caller is `truncate_last_exchange`, where
    the person asked for it and the route refuses while a run is going."""
    _validate(chat_id)
    db = DB(workspace)
    # keys(), not scan(): scan reads bodies and drops what it cannot decode, so a
    # torn turn file would survive the wipe and sit above the rewritten prefix.
    turn_keys = await db.keys(glob=f"chat/{chat_id}/[0-9]*")
    await asyncio.gather(*(db.delete(k) for k in turn_keys))
    # create=False: rewriting these slots is the point.
    await append_messages(workspace, chat_id, messages, 0, create=False)


async def get_compaction(workspace, chat_id):
    """The chat's compaction marker `{summary, first_kept, cleared}`, or None. Raw turns
    stay on disk; this marker projects the model's context over them."""
    _validate(chat_id)
    return await DB(workspace).get(f"chat/{chat_id}/compaction")


async def put_compaction(workspace, chat_id, data):
    _validate(chat_id)
    await DB(workspace).put(f"chat/{chat_id}/compaction", data)


def _is_plain_user(msg):
    """A real user turn — not harness scaffolding and not a tool-result batch."""
    if msg.get("role") != "user" or msg.get("internal"):
        return False
    c = msg.get("content")
    if isinstance(c, list):
        return not all(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
    return True


async def truncate_last_exchange(workspace, chat_id):
    """Drop the last user turn and everything after it. Returns the removed
    user content, or None when there was nothing to remove.

    Backs `regenerate`: the caller re-sends the same message, so the run that
    follows is an ordinary send — the loop needs no special case.

    Two invariants make this the only safe shape of deletion here:
      * Turn files are `{turn:06d}` and `Session._saved` is `len(messages)`, so
        an in-place delete would leave a numbering gap and the next append
        would overwrite a live turn. `replace_messages` rewrites contiguously.
      * The cut lands on a plain user turn, so the removed span starts with an
        assistant message — no `tool_result` can be orphaned by it.
    """
    _validate(chat_id)
    messages = await load_messages(workspace, chat_id)
    cut = next((i for i in range(len(messages) - 1, -1, -1) if _is_plain_user(messages[i])), None)
    if cut is None:
        return None
    removed = messages[cut].get("content")
    await replace_messages(workspace, chat_id, messages[:cut])
    # `first_kept` and `cleared` index the message list. Session clamps on load,
    # but the marker on disk must shrink too: a stale value larger than the
    # new length would re-clamp past the turns appended after this one and
    # silently hide them from the model's context on the following run.
    marker = await get_compaction(workspace, chat_id)
    keys = ("first_kept", "cleared")
    if marker and any(int(marker.get(k, 0)) > cut for k in keys):
        await put_compaction(workspace, chat_id, {**marker, **{k: min(int(marker.get(k, 0)), cut) for k in keys}})
    return removed


async def delete_chat(workspace, chat_id):
    """Delete the chat — index and all turns in one subtree wipe."""
    _validate(chat_id)
    await DB(workspace).delete(f"chat/{chat_id}/")


# ---- Session ----

def _ephemeralize(messages):
    """Strip any persisted `cache_control` markers from history. The provider
    re-applies cache breakpoints fresh each turn (system + last tool + last
    user message); persisted markers would risk exceeding Anthropic's 4-
    breakpoint cap."""
    for msg in messages:
        c = msg.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    return messages


class Session:
    """The working message list plus its persistence. The loop appends to
    `.messages` and calls `.checkpoint()` whenever the list is consistent (a
    complete turn or tool-result batch) and `.rollback()` after an error that
    may have left a half-written turn. An anonymous request — no chat_id or no
    signed-in user — gets a pure in-memory session: checkpoint/rollback are
    no-ops and nothing touches disk.

    `add_user` is itself a checkpoint: the person's turn is on disk when it
    returns, so `rollback()` can only drop the assistant tail. Custom loops
    (`.loop(fn)`) get this for free, and inherit the same contract."""

    @classmethod
    async def open(cls, context):
        persist = bool(context.chat_id and context.user)
        if not persist:
            return cls(context.workspace, None, [])
        # Append-only: the normalized list can be shorter than disk, so writes
        # go past every existing slot rather than over one.
        messages = _ephemeralize(await load_messages(context.workspace, context.chat_id))
        marker = await get_compaction(context.workspace, context.chat_id) or {}
        return cls(context.workspace, context.chat_id, messages,
                   summary=marker.get("summary"), first_kept=int(marker.get("first_kept", 0)),
                   cleared=int(marker.get("cleared", 0)),
                   next_idx=await turn_end(context.workspace, context.chat_id))

    def __init__(self, workspace, chat_id, messages, summary=None, first_kept=0, next_idx=None, cleared=0):
        self.workspace, self.chat_id, self.messages = workspace, chat_id, messages
        self.summary, self.first_kept = summary, min(first_kept, len(messages))
        self.cleared = min(cleared, len(messages))
        # Two counters, deliberately: `_saved` indexes `.messages`, `_next_idx`
        # names the next turn file. They diverge whenever normalization dropped a
        # turn the files still hold, so never re-derive either from the other —
        # a turn missing from the list does not free the slot it owns on disk.
        self._saved = len(messages)
        self._next_idx = len(messages) if next_idx is None else next_idx

    def context(self):
        """The model's view: the summary (once compacted) standing in for the folded
        prefix, tool results before `cleared` stubbed, the rest verbatim."""
        from .harness.compact import prefix, clear
        k = max(self.first_kept, self.cleared)
        return [*(prefix(self.summary) if self.summary is not None else []),
                *clear(self.messages[self.first_kept:k]), *self.messages[k:]]

    async def clear(self, keep, enough):
        """Stub tool results older than the recent `keep` tokens — the cheap tier.
        False when that frees under `enough`, so the caller summarizes instead."""
        from .harness.compact import clear_to
        cut, freed = clear_to(self.messages[self.first_kept:], max(self.cleared - self.first_kept, 0), keep)
        if freed < enough: return False
        self.cleared = self.first_kept + cut
        await self._mark()
        return True

    async def compact(self, provider, keep):
        """Fold the projected context into a summary marker — raw turns on disk
        are never touched, so the full transcript survives for the UI."""
        from .harness.compact import compact
        result = await compact(provider, self.context(), keep)
        self.summary = result[0]["content"]
        self.first_kept = len(self.messages) - (len(result) - 2)
        await self._mark()

    async def _mark(self):
        if self.chat_id:
            await put_compaction(self.workspace, self.chat_id,
                                 {"summary": self.summary, "first_kept": self.first_kept, "cleared": self.cleared})

    async def add_user(self, content, *, attachments=None, internal=False):
        """`internal` marks a turn the person did not type — an approval carried back from a confirm
        card. The model reads it, the chat never shows it, and it never becomes the chat's title.

        The turn is durable when this returns. It used to reach disk only at the
        first checkpoint, after the first tool batch, so a run that died before
        then lost what the person typed. Shielded because this runs outside the loop's
        try, where a disconnect cancels at the nearest await."""
        msg = {"role": "user", "content": content}
        if internal:
            msg["internal"] = True
        if attachments:
            msg["attachments"] = attachments
        self.messages.append(msg)
        # Before the meta touch: a turn with no index is recoverable (the next
        # touch_meta fills the title, add_cost and the chat-list self-heal both
        # write one), an index with no turn is the loss we are closing.
        await asyncio.shield(self.checkpoint())
        if self.chat_id and not internal:
            try: await touch_meta(self.workspace, self.chat_id, content)
            except Exception as e: print(f"[WARN] meta touch failed: {e}")

    async def checkpoint(self):
        """Flush the unsaved tail of `.messages` to disk."""
        if not self.chat_id:
            self._saved = len(self.messages)
            return
        pending = self.messages[self._saved:]
        if not pending:
            return
        try:
            n = await append_messages(self.workspace, self.chat_id, pending, self._next_idx)
        except BaseException as e:
            # Bank whatever landed, on any failure including cancellation, so a
            # later write does not re-use a spent slot. A Conflict means another
            # writer owns the chat — loud, because silent overwriting is the bug
            # this replaces.
            n = getattr(e, "written", 0)
            self._saved += n
            self._next_idx += n
            if isinstance(e, Conflict):
                log("error", chat_id=self.chat_id, kind="turn_conflict",
                    key=e.key, written=n, next_idx=self._next_idx)
            raise
        self._saved += n
        self._next_idx += n

    def rollback(self):
        """Drop any tail not yet flushed by `checkpoint()`."""
        del self.messages[self._saved:]


# ---- Share tokens (RFC003) ----

async def find_share(workspace, token):
    """The share row, audience unchecked — callers gate with `share_allows` so
    'no such share' stays distinguishable from 'not yours to see'."""
    return await DB(workspace).get(f"share/{token}")


def share_allows(row, requester):
    aud = (row or {}).get("audience", "public")
    if aud == "public":
        return True
    return aud.startswith("org:") and getattr(requester, "org_id", None) == aud[4:]


async def resolve(workspace, token, requester=None):
    row = await find_share(workspace, token)
    return row if row and share_allows(row, requester) else None


# ---- Workspaces registry + ACL (docs/workspaces.md) ----
#
# Org-level rows under the `.org` slot — OUTSIDE every workspace root, so
# they are never bind-mounted into a sandbox and unreachable by path tools:
#     workspaces/{ws_id}            — team registry {id, name, type, created_by, created_at}
#     members/{ws_id}/{user_id}     — ACL row {role, added_by, added_at}
# Personal workspaces (`u-{user_id}`) have no rows: owner-only by construction,
# and org admins get lifecycle (list/delete), never content.

def org_of(user):
    """Org segment for a User — mirrors workspace() subject derivation."""
    return getattr(user, "org_id", None) or user.id


def org_db(org, volume, base):
    """DB over the org-level `.org` tree (registry + ACL)."""
    return DB(workspace(org, volume, base=base, slot=".org"))


async def create_team_ws(orgdb, name, creator_id, icon=None):
    ws_id = f"t-{secrets.token_urlsafe(8)}"   # urlsafe alphabet ⊂ [A-Za-z0-9_-]
    now = datetime.now(timezone.utc).isoformat()
    row = {"id": ws_id, "name": name, "type": "team",
           "created_by": creator_id, "created_at": now}
    if icon: row["icon"] = icon
    member = {"role": "owner", "added_by": creator_id, "added_at": now}
    # Rows are flat str:str so they ride object-store custom-meta (O(1) scan).
    await orgdb.put(f"workspaces/{ws_id}", row, meta=row)
    await orgdb.put(f"members/{ws_id}/{creator_id}", member, meta=member)
    return row


async def resolve_role(user, ws_id, orgdb):
    """`user`'s role in `ws_id`, or None (no access — callers 404, not 403).

    Personal: owner-only; even org admins get None (lifecycle-only access to
    other people's personal workspaces goes through the explicit lifecycle
    endpoints, never through content routes). Team: the member row wins;
    org admins hold implicit `admin` on any registered team workspace; a
    `builtin: org` registry row (the org's default General workspace) makes
    every org member an editor without per-user rows."""
    if ws_id == f"u-{user.id}":
        return "owner"
    if not ws_id.startswith("t-"):
        return None
    reg = await orgdb.get(f"workspaces/{ws_id}")
    if reg and reg.get("builtin") == "org":
        # Builtin (General): everyone in the org is a member by default; the
        # only member row honored is an `excluded` marker (org admins may
        # remove people). Role rows are otherwise ignored — a stray row could
        # downgrade an org admin. Admins are immune to exclusion.
        if getattr(user, "org_role", None) == "admin":
            return "admin"
        if not getattr(user, "org_id", None):
            return None
        row = await orgdb.get(f"members/{ws_id}/{user.id}")
        if row and row.get("role") == "excluded":
            return None
        return "editor"
    row = await orgdb.get(f"members/{ws_id}/{user.id}")
    if row:
        return row.get("role")
    if reg and getattr(user, "org_role", None) == "admin":
        return "admin"
    return None


async def member_of(orgdb, user_id):
    """Team workspace ids `user_id` belongs to — one glob LIST round-trip."""
    return [k.split("/")[1] async for k, _ in orgdb.scan(glob=f"members/*/{user_id}")]


async def wipe_workspace(org, ws_id, volume, base):
    """Delete a workspace's file tree and object-store subtree, then its
    registry + ACL rows. Trusted-code only — authorization happens in the
    router. Idempotent: missing trees are fine. Deriving the root through
    workspace() revalidates org and ws_id before anything is destroyed."""
    root = Path(workspace(org, volume, base=base, ws=ws_id).root)
    if root.exists():
        await asyncio.to_thread(shutil.rmtree, root, True)
    # Prod files ride gcsfuse but DB objects are written via the GCS API —
    # sweep the object-store prefix too so no .json rows survive the rmtree.
    await _store(f"{str(base).rstrip('/')}/{org}").remove_prefix(f"ws/{ws_id}/")
    orgdb = org_db(org, volume, base)
    await orgdb.delete(f"workspaces/{ws_id}")
    await orgdb.delete(f"members/{ws_id}/")


_provisioned = set()
_provision_lock = None


async def ensure_general(user, volume, base):
    """Provision the builtin General registry row on an org's first touch.
    A tombstone row (admin deleted General — permanent) blocks re-creation.
    Data migration is operator-run via the CLI, never in-request; solo
    accounts need nothing — their personal workspace IS the account root."""
    global _provision_lock
    if not getattr(user, "org_id", None):
        return
    org = org_of(user)
    if org in _provisioned:
        return
    if _provision_lock is None:
        _provision_lock = asyncio.Lock()
    async with _provision_lock:
        if org not in _provisioned:
            orgdb = org_db(org, volume, base)
            if await orgdb.get("workspaces/t-shared") is None:
                row = {"id": "t-shared", "name": "General", "type": "team", "builtin": "org",
                       "created_by": "cycls", "created_at": datetime.now(timezone.utc).isoformat()}
                await orgdb.put("workspaces/t-shared", row, meta=row)
            _provisioned.add(org)


# ---- Agent KV (LLM-facing tool) ----
#
# A key under `apps/` addresses the workspace's app data; anything else is the
# agent's own memory. `u` is reserved under a slug — see docs/notes/apps.md.

APPS_SLOT, APPS_ROOT, USER_MARK = ".apps", "apps/", "u"


def actor_of(subject):
    """The person in a `{org}:{user}` subject — the org itself on a solo account."""
    org, _, user = subject.partition(":")
    return user or org


def apps_db(ws):
    """One shelf per workspace, not per person: target the org so `workspace()` adds no user."""
    return DB(workspace(ws.subject.partition(":")[0], ws.volume, base=ws.base, slot=APPS_SLOT, ws=ws.ws))


def app_shelf(slug, key="", *, user=None, everyone=False):
    """Store key for app data — the workspace's shelf, one member's, or the whole `u/` subtree."""
    if not slug or slug in (".", "..") or "/" in slug:
        raise ValueError(f"invalid app: {slug!r}")
    if key: _validate_db_key(key)
    if everyone: return f"{slug}/{USER_MARK}/{key}"
    if user:
        if "/" in user or user in (".", ".."): raise ValueError(f"invalid member: {user!r}")
        return f"{slug}/{USER_MARK}/{user}/{key}"
    if key.split("/")[0] == USER_MARK:
        raise ValueError(f"{USER_MARK!r} is reserved: a member's own app data is not reachable here")
    return f"{slug}/{key}"


def _validate_db_key(key):
    """Allow trailing slash (= subtree marker for delete); reject empty,
    leading '/', '..' segments, and empty middle segments."""
    if not key: raise ValueError("key required")
    parts = key.split("/")
    if key.startswith("/") or ".." in parts or "" in parts[:-1]:
        raise ValueError(f"invalid key: {key!r}")


def _route(ws, key, *, prefix=False):
    """(db, store key). `apps/<slug>/…` is the workspace's app shelf; anything else the agent's own."""
    if key.startswith(APPS_ROOT):
        slug, _, rest = key[len(APPS_ROOT):].partition("/")
        if not rest.strip("/") and not prefix:
            raise ValueError(f"app key needs apps/<slug>/<key>: {key!r}")
        return apps_db(ws), app_shelf(slug, rest)
    if not prefix: _validate_db_key(key)
    return DB(workspace(ws.subject, ws.volume, base=ws.base, slot=".database", ws=ws.ws)), key


async def _exec_database(inp, ws):
    """All returns are strings — Anthropic tool_result.content accepts
    str or content-blocks (each with a `type`); raw dicts/lists from JSON
    values would 400. JSON-encode the data ones."""
    cmd, key = inp.get("command"), inp.get("key", "")
    try:
        if cmd == "get":
            db, k = _route(ws, key)
            v = await db.get(k)
            return json.dumps(v) if v is not None else f"Error: key {key!r} not found"
        if cmd == "put":
            db, k = _route(ws, key)
            await db.put(k, inp.get("value"))
            return f"Stored {key!r}"
        if cmd == "delete":
            db, k = _route(ws, key)
            await db.delete(k)
            return f"Deleted {key!r}"
        if cmd == "scan":
            prefix = inp.get("prefix", "")
            db, p = _route(ws, prefix, prefix=True)
            app = prefix.startswith(APPS_ROOT)
            limit = max(1, int(inp.get("limit", 100)))
            pairs = [{"key": APPS_ROOT + k if app else k, "value": v}
                     async for k, v in db.items(prefix=p, limit=limit + 1)
                     if not (app and k.split("/")[1:2] == [USER_MARK])]
            truncated = len(pairs) > limit
            if truncated: pairs = pairs[:limit]
            if not pairs: return f"No keys with prefix {prefix!r}"
            result = json.dumps(pairs)
            return f"{result}\n[truncated at {limit}; use a narrower prefix or higher limit]" if truncated else result
        return f"Error: unknown command {cmd!r}"
    except ValueError as e:
        return f"Error: {e}"

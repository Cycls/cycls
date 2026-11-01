"""Skill discovery, loading and publishing — progressive disclosure for the agent
(docs/notes/skills.md).

A skill is a directory holding a SKILL.md: `---` fenced frontmatter (name,
description) followed by full instructions, plus any support files (scripts,
templates, reference docs). Only the catalog (name + description per skill)
enters the system prompt; the model calls the `skill` tool to load the body
on demand.

Four sources, one catalog, a later one winning a shared name:
- Developer skills ship read-only in the image (registered via
  `cycls.LLM().skills(dir)`), scanned once per process.
- The org's own, in `{org}/.skills`, in every workspace of the org.
- A team workspace's own, in its `.skills` slot.
- The person's own, in their personal workspace's `.skills`, which follow
  them into every workspace.
A slot keeps each skill as versions that never change and a pointer to the one
that loads: `.skills/<name>/meta.json` beside `.skills/<name>/v3/`. It is a
managed slot (`MANAGED`), written only by `publish` and the Skills routes, and
rescanned on a short TTL (the workspace is a gcsfuse mount in prod — metadata
ops are expensive). Every skill in a turn's catalog is ro-bind-mounted into the
bash sandbox at /skills/<name>, wherever it is kept.
"""
import asyncio, io, json, os, re, time, zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from cycls._app.db import workspace
from .. import state
from ..logs import log
from ..paths import _resolve_path

MAX_DESCRIPTION = 1024        # catalog entry cap
MAX_SKILL_BYTES = 48 * 1024   # loaded SKILL.md / support file cap
MAX_PUBLISH, MAX_FILES = 10 * 1024 * 1024, 500   # one version, all its files
_HEAD_BYTES = 4096            # how much of SKILL.md a catalog scan reads
_TTL = 30.0                   # slot rescan interval
_NAME_RE = re.compile(r"^(?=.{1,64}$)[a-z0-9]+(-[a-z0-9]+)*$")   # the Agent Skills spec
_JUNK = (".DS_Store", "Thumbs.db", "__MACOSX", "__pycache__", ".git")

MOUNT = "/skills"             # where every skill appears inside the sandbox
SLOT = ".skills"              # where a workspace keeps its own
DRAFTS = "skill-drafts"       # where the agent writes one, as ordinary files


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    dir: Path       # directory containing SKILL.md (image path for dev skills)
    source: str     # "dev" | "workspace" | "me"
    version: int | None = None
    title: str = ""            # what people see: frontmatter `metadata.title`, `title-ar`, `description-ar`;
    title_ar: str = ""         # `name` and `description` stay what the model reads
    description_ar: str = ""


_ENTRY_RE = re.compile(r"[A-Za-z0-9_-]+:(\s|$)")


def parse_frontmatter(text):
    """Split `---` fenced `key: value` frontmatter from the body. String keys,
    folded values (`>-` + indented lines) joined, and one level of map (a bare
    `metadata:` over indented `key: value` lines, read as `metadata.key`) —
    enough for SKILL.md, no YAML dependency. Unparseable → ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    lines = text.split("\n")
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            meta, key, maps = {}, None, set()
            for raw in lines[1:i]:
                if key and raw[:1] in (" ", "\t"):
                    if key in maps and not meta[key] and _ENTRY_RE.match(raw.strip()):
                        k, _, value = raw.strip().partition(":")
                        meta[f"{key}.{k.strip().lower()}"] = value.strip().strip("'\"")
                    else:   # a bare key's first line that isn't `key: value` makes it text after all
                        maps.discard(key)
                        meta[key] = (meta[key] + " " + raw.strip()).strip()
                    continue
                k, sep, value = raw.partition(":")
                if sep and k.strip():
                    key = k.strip().lower()
                    value = value.strip().strip("'\"")
                    if not value:
                        maps.add(key)
                    meta[key] = "" if value in (">", ">-", "|", "|-") else value
            return meta, "\n".join(lines[i + 1:])
    return {}, text


def _read_text(path, cap):
    """First `cap` bytes of a file as text, plus whether it was truncated.
    Raises OSError; NUL bytes mean binary → ValueError."""
    with open(path, "rb") as f:
        data = f.read(cap + 1)
    if b"\x00" in data:
        raise ValueError(f"{path.name} is a binary file")
    return data[:cap].decode("utf-8", errors="replace"), len(data) > cap


def _load_skill(path, source, fallback=None):
    """Catalog entry from a skill directory; None if unusable. Fallbacks:
    name = `fallback` or the directory name, description = first non-empty body line."""
    try:
        head, _ = _read_text(path / "SKILL.md", _HEAD_BYTES)
    except (OSError, ValueError):
        return None
    meta, body = parse_frontmatter(head)
    name = meta.get("name") or fallback or path.name
    if not _NAME_RE.match(name):
        return None
    desc = meta.get("description") or next((l.strip() for l in body.split("\n") if l.strip()), "")
    if len(desc) > MAX_DESCRIPTION:
        desc = desc[:MAX_DESCRIPTION] + "…"
    return Skill(name, desc, path, source, title=meta.get("metadata.title", ""),
                 title_ar=meta.get("metadata.title-ar", ""), description_ar=meta.get("metadata.description-ar", ""))


def _scan_dir(root, source):
    """One skill per <root>/<name>/SKILL.md; a bare <root>/SKILL.md makes
    the root itself a single skill. Sorted, hidden entries skipped, never raises."""
    root = Path(root)
    try:
        if (root / "SKILL.md").is_file():
            skill = _load_skill(root, source)
            return [skill] if skill else []
        found = []
        for child in sorted(root.iterdir()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            if (child / "SKILL.md").is_file():
                skill = _load_skill(child, source)
                if skill:
                    found.append(skill)
        return found
    except OSError:
        return []


_dev_sources = []
_dev_cache = {}    # resolved source path -> list[Skill]; the image is immutable
_slot_cache = {}   # str(slot owner's root) -> (deadline, [Skill])


def configure(sources):
    """Register developer skill sources (dirs shipped in the image).
    Each is scanned once per process."""
    global _dev_sources
    _dev_sources = [str(s) for s in (sources or [])]
    for src in _dev_sources:
        key = str(Path(src).resolve())
        if key not in _dev_cache:
            _dev_cache[key] = _scan_dir(src, "dev")
    # bwrap can't mkdir inside its read-only root, so the mount point is made here and each skill
    # binds inside a tmpfs over it. Best-effort: without write access only the bash mounts are lost.
    try:
        Path(MOUNT).mkdir(exist_ok=True)
    except OSError:
        pass


def _dev():
    return {s.name: s for src in _dev_sources for s in _dev_cache.get(str(Path(src).resolve()), [])}


# ---- The slots: a workspace's own, and the person's ----

def roots(ws):
    """{source: folder whose .skills join the catalog}, the most specific last so it wins a shared name: the
    org's, the team workspace's, the person's own (their personal workspace's). Without workspaces an org
    member has no place of their own: the one root is the org's."""
    org, _, user = ws.subject.partition(":")
    found = {"org": Path(workspace(org, ws.volume, base=ws.base).root)} if user else {}
    if ws.ws and not ws.ws.startswith("u-"):
        found["workspace"] = Path(ws.root)
    if ws.ws or not user:
        found["me"] = Path(workspace(ws.subject, ws.volume, base=ws.base, ws=f"u-{user or org}").root)
    return found


def _meta(d):
    try:
        meta = json.loads((d / "meta.json").read_text())
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _scan_slot(root, source):
    """The version that loads of every skill kept in root/.skills. Never raises."""
    try:
        dirs = sorted(p for p in (Path(root) / SLOT).iterdir() if p.is_dir() and _NAME_RE.match(p.name))
    except OSError:
        return []
    found = []
    for d in dirs:
        v = (_meta(d) or {}).get("default")
        if isinstance(v, int) and (skill := _load_skill(d / f"v{v}", source, d.name)) and skill.name == d.name:
            found.append(replace(skill, version=v))
    return found


def discover(ws, hidden=()):
    """{name: Skill} — the image's, the workspace's over them, the person's over both, less the names
    in `hidden`. Sync; callers wrap in asyncio.to_thread."""
    catalog, now = _dev(), time.monotonic()
    for source, root in roots(ws).items():
        if (cached := _slot_cache.get(str(root))) is None or now >= cached[0]:
            cached = _slot_cache[str(root)] = (now + _TTL, _scan_slot(root, source))
        catalog.update((s.name, s) for s in cached[1])
    return {n: s for n, s in catalog.items() if n not in hidden}


async def available(ws):
    """A turn's catalog, less what an org admin blocked for everyone and the person switched off for themselves."""
    blocked = await state.org_db(ws.subject.partition(":")[0], ws.volume, ws.base).get("skills") or {}
    off = await state.settings_db(ws).get("skills") or {}
    return await asyncio.to_thread(discover, ws, {*blocked.get("blocked", []), *off.get("off", [])})


# ---- Publishing: a folder checked, then kept as a new version ----

def collect(folder):
    """{relative path: bytes} of a folder to publish, junk dropped. A link is refused: read here, outside
    the sandbox, it could name any file on the volume."""
    files, size = {}, 0
    for top, dirs, names in os.walk(folder):
        if links := [n for n in dirs + names if os.path.islink(os.path.join(top, n))]:
            raise ValueError(f"{links[0]} is a link; copy the file in instead")
        dirs[:] = [d for d in dirs if d not in _JUNK]
        for n in names:
            if n not in _JUNK and not n.startswith("._") and not n.endswith(".pyc"):
                size += os.path.getsize(p := os.path.join(top, n))   # the caps stop the walk before a read
                if size > MAX_PUBLISH or len(files) >= MAX_FILES:
                    raise ValueError(f"a skill is at most {MAX_FILES} files and {MAX_PUBLISH >> 20} MB")
                files[Path(p).relative_to(folder).as_posix()] = Path(p).read_bytes()
    return files


def unzip(data):
    """{relative path: bytes} of a .skill or .zip: SKILL.md at its root or in its one top folder, junk dropped."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entries = [i for i in z.infolist() if not i.is_dir()
                   and not any(p in _JUNK or p.startswith("._") for p in i.filename.split("/"))]
        if len(entries) > MAX_FILES or sum(i.file_size for i in entries) > MAX_PUBLISH:   # before a byte is inflated
            raise ValueError(f"a skill is at most {MAX_FILES} files and {MAX_PUBLISH >> 20} MB")
        top = {i.filename.split("/")[0] for i in entries}
        cut = len(top.pop()) + 1 if len(top) == 1 and all("/" in i.filename for i in entries) else 0
        files = {i.filename[cut:]: z.read(i) for i in entries}
    if any(p.startswith("/") or ".." in p.split("/") for p in files):
        raise ValueError("a path in the archive leaves the skill")
    return files


def prepare(files, name=None):
    """The skill's name, or ValueError naming what the loader would refuse. SKILL.md's line endings become
    LF: a CRLF copy loses its frontmatter."""
    files["SKILL.md"] = files.get("SKILL.md", b"").replace(b"\r\n", b"\n")
    meta, _ = parse_frontmatter(files["SKILL.md"][:_HEAD_BYTES].decode("utf-8", "replace"))
    name = name or meta.get("name", "")
    if not _NAME_RE.match(name) or meta.get("name", name) != name or not 0 < len(meta.get("description", "")) <= MAX_DESCRIPTION:
        raise ValueError(f"the folder needs a SKILL.md opening with `---` frontmatter, ended in its first 4 KB, "
                         f"with `name: {name}` (lowercase, hyphens, at most 64) and a `description` of at most "
                         f"{MAX_DESCRIPTION} characters saying what it does and when to use it")
    return name


def store(root, name, files, *, by=None, who=None):
    """A new version of `name` under root/.skills, made the one that loads; returns its number. The files
    land first and the pointer last, so a reader sees the old version or the new, never half of one."""
    d = Path(root) / SLOT / name
    versions = (_meta(d) or {}).get("versions", [])
    v = max((x["v"] for x in versions), default=0) + 1
    for rel, data in files.items():
        (d / f"v{v}" / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / f"v{v}" / rel).write_bytes(data)
    versions.append({"v": v, "at": datetime.now(timezone.utc).isoformat(), "by": by, "who": who})
    (d / "meta.json").write_text(json.dumps({"default": v, "versions": versions}, indent=1))
    _slot_cache.pop(str(root), None)
    return v


def point(root, name, v):
    """Make version `v` the one that loads: a rollback. None takes the skill out of every catalog, its
    versions kept, so publishing it again carries on from them."""
    d = Path(root) / SLOT / name
    meta = _meta(d) or {}
    if v is not None and not any(x["v"] == v for x in meta.get("versions", [])):
        raise ValueError(f"{name} has no version {v}")
    if meta:
        (d / "meta.json").write_text(json.dumps({**meta, "default": v}, indent=1))
    _slot_cache.pop(str(root), None)


def versions(skill):
    """A kept skill's versions, newest first; the image's have none."""
    return [] if skill.source == "dev" else sorted((_meta(skill.dir.parent) or {}).get("versions", []), key=lambda x: -x["v"])


def files_in(d):
    return sorted(p.relative_to(d).as_posix() for p in Path(d).rglob("*") if p.is_file())


def skill_md(name, description, body, **shown):
    """A SKILL.md from the fields a person fills in. `shown` (title, title_ar, description_ar) is what the Skills
    tab shows, kept under `metadata` where the standard keeps what isn't its own."""
    extra = "".join(f"\n  {k.replace('_', '-')}: {' '.join(v.split())}" for k, v in shown.items() if v and v.strip())
    return (f"---\nname: {name}\ndescription: {' '.join(description.split())}\n"
            f"{'metadata:' + extra + chr(10) if extra else ''}---\n\n{body.strip()}\n").encode()


def bundle(skill):
    """The skill as a .zip with its folder at the root: what Claude and the standard's other tools install."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(skill.dir.rglob("*")):
            if p.is_file():
                z.write(p, f"{skill.name}/{p.relative_to(skill.dir).as_posix()}")
    return buf.getvalue()


async def may_publish(ws, user, scope):
    """Anyone keeps their own skills; an org's are its admins', a team workspace's its owners' and admins'."""
    if scope == "org":
        return getattr(user, "org_role", None) == "admin"
    if scope == "workspace":
        return bool(getattr(user, "id", None)) and await state.resolve_role(
            user, ws.ws, state.org_db(state.org_of(user), ws.volume, ws.base)) in ("owner", "admin")
    return scope == "me"


# ---- What the sandbox and the read tool see ----

def mounts(catalog=None):
    """[(dir, sandbox_path)] — one ro bind per skill, so scripts and templates are at /skills/<name>/
    wherever the skill is kept. Without a catalog, the image's skills."""
    return [(str(s.dir), f"{MOUNT}/{s.name}") for s in (_dev() if catalog is None else catalog).values()]


def resolve_path(raw_path, catalog=None):
    """Map a sandbox-style /skills/<name>/... path to the file it names, for
    read-only access. None when the path isn't under /skills; ValueError on an
    unknown skill or traversal — mirrors `_resolve_path`'s contract. Without a
    catalog, the image's skills."""
    if not str(raw_path).startswith(f"{MOUNT}/"):
        return None
    name, _, rest = str(raw_path)[len(MOUNT) + 1:].partition("/")
    skill = (_dev() if catalog is None else catalog).get(name)
    if skill is None:
        raise ValueError(f"unknown skill path {raw_path}")
    base = skill.dir.resolve()
    path = (base / rest).resolve() if rest else base
    if not path.is_relative_to(base):
        raise ValueError("path escapes the skill directory")
    return path


# ---- The model's side ----

def catalog_text(catalog):
    """The <skills> system-prompt block; '' when the catalog is empty."""
    if not catalog:
        return ""
    lines = "\n".join(f"- {s.name}: {s.description}" for s in catalog.values())
    return (
        "<skills>\n"
        "You have skills: packs of task-specific instructions. When a request "
        "matches a skill's description, call the `skill` tool with its name to "
        "load the full instructions BEFORE doing the task yourself. Available skills:\n"
        f"{lines}\n"
        "</skills>"
    )


SKILL_TOOL = {
    "type": "custom",
    "name": "skill",
    "description": (
        "Load a skill — a pack of task-specific instructions — or make one.\n\n"
        "Usage:\n"
        "- Call this BEFORE starting work whenever the request matches a skill "
        "listed in your system prompt.\n"
        "- The result names the skill's directory, /skills/<name>/ (read-only); its support files (scripts, "
        "templates, reference docs) live there for bash and `read`.\n"
        "- Pass `path` to read a text support file directly (relative to the "
        "skill's directory, e.g. REFERENCE.md).\n"
        f"- `action: publish` makes a folder (default {DRAFTS}/<name>/) the skill's next version, for the whole "
        "organization (`scope: org`, its admins), everyone in a team workspace (`scope: workspace`, its owners "
        "and admins) or the person alone, everywhere (`scope: me`). It loads from their next message.\n"
        f"- To change a skill, copy /skills/<name>/ to {DRAFTS}/<name>/ and edit it there. To install one someone "
        f"shares (a .skill or .zip file, a GitHub folder), unpack or fetch it into {DRAFTS}/<name>/. Then publish.\n"
        "- `name` and `description` are what you read, so write them in English. What people see in the Skills "
        "tab goes under `metadata` in the frontmatter: `title`, and in Arabic `title-ar` and `description-ar`."
    ),
    "input_schema": {"type": "object", "properties": {
        "name": {"type": "string", "description": "Skill name: as listed in the system prompt, or the one to publish."},
        "action": {"type": "string", "enum": ["load", "publish"], "description": "Default load."},
        "path": {"type": "string", "description": "load: a support file relative to the skill directory. "
                                                  f"publish: the folder to publish (default {DRAFTS}/<name>)."},
        "scope": {"type": "string", "enum": ["org", "workspace", "me"],
                  "description": "publish: who it is for. Default: the person alone; they share it from the Skills tab."},
    }, "required": ["name"]},
}


def loads_skill(block):
    """Is this tool call a skill being loaded — the `skill` tool, or the Design tool's own `skill`
    action? Its result is instructions, not history: never spilled to a file, never cleared."""
    if block.get("name") == "skill":
        return True
    return block.get("name") == "design" and str((block.get("input") or {}).get("action") or "").lower() == "skill"


async def _exec_skill(inp, ws, ctx=None):
    action, name = inp.get("action") or "load", (inp.get("name") or "").strip()
    if action == "publish":
        return await _publish(inp, ws, ctx, name)
    catalog = getattr(ctx, "skills", None)
    if catalog is None:   # outside a turn
        catalog = await available(ws)
    if not (skill := catalog.get(name)):
        return f"Error: unknown skill '{name}'. Available skills: {', '.join(sorted(catalog)) or 'none'}"
    base = skill.dir.resolve()
    target = (base / (inp.get("path") or "SKILL.md")).resolve()
    if not target.is_relative_to(base):
        return "Error: path escapes the skill directory"
    try:
        text, truncated = await asyncio.to_thread(_read_text, target, MAX_SKILL_BYTES)
    except (OSError, ValueError) as e:
        return f"Error: {e}"
    if truncated:
        text += "\n... (truncated)"
    return f"[skill: {skill.name} — files in {MOUNT}/{skill.name}/]\n\n{text}"


async def _publish(inp, ws, ctx, name):
    places = roots(ws)
    scope = inp.get("scope") or ("me" if "me" in places else next(iter(places)))   # one's own until shared
    if scope not in places:
        return f"Error: scope {scope} is not available here; use {' or '.join(places)}."
    try:
        files = await asyncio.to_thread(collect, _resolve_path(inp.get("path") or f"{DRAFTS}/{name}", ws.root))
        prepare(files, name)
    except (OSError, ValueError) as e:
        return f"Error: {e}"
    user = getattr(ctx, "user", None)
    if not await may_publish(ws, user, scope):
        return ("Error: an org's skills are published by its admins and a team workspace's by its owners and "
                "admins; scope `me` keeps it for this person.")
    v = await asyncio.to_thread(store, places[scope], name, files, by=getattr(user, "id", None) or ws.subject,
                                who=getattr(user, "name", None))
    log("skill", user=user, chat_id=getattr(ctx, "chat_id", None), action="published", skill=name, scope=scope, v=v)
    who = {"org": "everyone in the organization", "workspace": "everyone in this workspace", "me": "you"}[scope]
    return f"Published {name} v{v} for {who}. It loads from the next message."

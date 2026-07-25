"""Skill discovery and loading — progressive disclosure for the agent.

A skill is a directory holding a SKILL.md: `---` fenced frontmatter (name,
description) followed by full instructions, plus any support files (scripts,
templates, reference docs). Only the catalog (name + description per skill)
enters the system prompt; the model calls the `skill` tool to load the body
on demand.

Two sources, one catalog:
- Developer skills ship read-only in the image (registered via
  `cycls.LLM().skills(dir)`), scanned once per process. Their directories are
  ro-bind-mounted into the bash sandbox at /skills/<name> so scripts and
  binary templates are executable/readable there — the harness itself only
  ever reads text from them.
- User skills live at <workspace>/skills/<name>/SKILL.md, rescanned on a
  short TTL (the workspace is a gcsfuse mount in prod — metadata ops are
  expensive). On a name collision the user's skill wins.
"""
import asyncio, re, time
from dataclasses import dataclass
from pathlib import Path

MAX_DESCRIPTION = 1024        # catalog entry cap
MAX_SKILL_BYTES = 48 * 1024   # loaded SKILL.md / support file cap
_HEAD_BYTES = 4096            # how much of SKILL.md a catalog scan reads
_TTL = 30.0                   # user-skill rescan interval per workspace
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

MOUNT = "/skills"             # where dev skills appear inside the sandbox


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    dir: Path       # directory containing SKILL.md (image path for dev skills)
    source: str     # "dev" | "user"


def parse_frontmatter(text):
    """Split `---` fenced `key: value` frontmatter from the body. Flat string
    keys only, with folded values (`>-` + indented lines) joined — enough for
    SKILL.md, no YAML dependency. Unparseable → ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    lines = text.split("\n")
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            meta, key = {}, None
            for raw in lines[1:i]:
                if key and raw[:1] in (" ", "\t"):
                    meta[key] = (meta[key] + " " + raw.strip()).strip()
                    continue
                k, sep, value = raw.partition(":")
                if sep and k.strip():
                    key = k.strip().lower()
                    value = value.strip().strip("'\"")
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


def _load_skill(path, source):
    """Catalog entry from a skill directory; None if unusable. Fallbacks:
    name = directory name, description = first non-empty body line."""
    try:
        head, _ = _read_text(path / "SKILL.md", _HEAD_BYTES)
    except (OSError, ValueError):
        return None
    meta, body = parse_frontmatter(head)
    name = meta.get("name") or path.name
    if not _NAME_RE.match(name):
        return None
    desc = meta.get("description") or next((l.strip() for l in body.split("\n") if l.strip()), "")
    if len(desc) > MAX_DESCRIPTION:
        desc = desc[:MAX_DESCRIPTION] + "…"
    return Skill(name, desc, path, source)


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
_user_cache = {}   # str(workspace root) -> (deadline, {name: Skill})


def configure(sources):
    """Register developer skill sources (dirs shipped in the image).
    Each is scanned once per process."""
    global _dev_sources
    _dev_sources = [str(s) for s in (sources or [])]
    for src in _dev_sources:
        key = str(Path(src).resolve())
        if key not in _dev_cache:
            _dev_cache[key] = _scan_dir(src, "dev")


def _dev_skills():
    for src in _dev_sources:
        for skill in _dev_cache.get(str(Path(src).resolve()), []):
            yield skill


def dev_mounts():
    """[(image_dir, sandbox_path)] — one ro bind per dev skill, so scripts and
    templates are visible in the bash sandbox at /skills/<name>/."""
    return [(str(s.dir), f"{MOUNT}/{s.name}") for s in _dev_skills()]


def resolve_dev_path(raw_path):
    """Map a sandbox-style /skills/<name>/... path to the image file it names,
    for read-only access. None when the path isn't under /skills; ValueError
    on unknown skill or traversal — mirrors `_resolve_path`'s contract."""
    if not str(raw_path).startswith(f"{MOUNT}/"):
        return None
    rel = str(raw_path)[len(MOUNT) + 1:]
    name, _, rest = rel.partition("/")
    skill = next((s for s in _dev_skills() if s.name == name), None)
    if skill is None:
        raise ValueError(f"unknown skill path {raw_path}")
    base = skill.dir.resolve()
    path = (base / rest).resolve() if rest else base
    if not path.is_relative_to(base):
        raise ValueError("path escapes the skill directory")
    return path


def discover(root):
    """{name: Skill} for a workspace — dev skills overlaid by the user's
    skills/ dir (user wins). Sync; callers wrap in asyncio.to_thread."""
    catalog = {s.name: s for s in _dev_skills()}
    key = str(root)
    now = time.monotonic()
    cached = _user_cache.get(key)
    if cached and now < cached[0]:
        user = cached[1]
    else:
        user = {s.name: s for s in _scan_dir(Path(root) / "skills", "user")}
        _user_cache[key] = (now + _TTL, user)
    catalog.update(user)
    return catalog


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
        "Load a skill — a pack of task-specific instructions.\n\n"
        "Usage:\n"
        "- Call this BEFORE starting work whenever the request matches a skill "
        "listed in your system prompt.\n"
        "- The result names the skill's directory; its support files (scripts, "
        "templates, reference docs) live there for bash and `read`.\n"
        "- Pass `path` to read a text support file directly (relative to the "
        "skill's directory, e.g. REFERENCE.md)."
    ),
    "input_schema": {"type": "object", "properties": {
        "name": {"type": "string", "description": "Skill name exactly as listed in the system prompt."},
        "path": {"type": "string", "description": "Optional support file relative to the skill directory."},
    }, "required": ["name"]},
}


def _locator(skill, workspace_root):
    """Where the skill's files are, in paths the sandbox/read tool understand:
    /skills/<name> for dev skills, workspace-relative skills/<name> for user."""
    if skill.source == "dev":
        return f"{MOUNT}/{skill.name}"
    try:
        return str(skill.dir.resolve().relative_to(Path(workspace_root).resolve()))
    except ValueError:
        return str(skill.dir)


async def _exec_skill(inp, workspace_root):
    catalog = await asyncio.to_thread(discover, workspace_root)
    name = (inp.get("name") or "").strip()
    skill = catalog.get(name)
    if not skill:
        avail = ", ".join(sorted(catalog)) or "none"
        return f"Error: unknown skill '{name}'. Available skills: {avail}"
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
    return f"[skill: {skill.name} — files in {_locator(skill, workspace_root)}/]\n\n{text}"

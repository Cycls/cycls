"""The Design tool's own skills — how to choose a look, and how to lay out each kind of work well in few
calls — loaded with `design {"action": "skill", "skill": […]}`. Each is a markdown file in skills/, read
once; its frontmatter's `description` is its line in the tool's description. Stdlib only: tool.py, which
lists them, is imported before the harness's own skills module."""
import pathlib, re

_DIR = pathlib.Path(__file__).with_name("skills")
_HEAD = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _read(path):
    """A skill file → (name, description, body)."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    head = _HEAD.match(text)
    meta = dict(re.findall(r"^(\w+):\s*(.+)$", head.group(1), re.M)) if head else {}
    return meta.get("name") or path.stem, meta.get("description", ""), text[head.end() if head else 0:].strip()


_FIRST = ("design-direction", "graphic-design", "deck-design", "document-design")   # the look, then each kind
SKILLS = {name: (description, body) for name, description, body in
          sorted(map(_read, _DIR.glob("*.md")), key=lambda s: (_FIRST.index(s[0]) if s[0] in _FIRST else len(_FIRST), s[0]))}


def catalog():
    """One line a skill, for the tool's description."""
    return "\n".join(f"  · {name} — {description}" for name, (description, _) in SKILLS.items())


def load(asked):
    """The skills asked for — a name, a list of them, or names in one string — as the text the model reads."""
    names = asked if isinstance(asked, list) else re.split(r"[\s,]+", str(asked or ""))
    names = list(dict.fromkeys(str(n).strip().lower() for n in names if str(n).strip()))
    unknown = [n for n in names if n not in SKILLS]
    if not names or unknown:
        what = f"no skill named {', '.join(map(repr, unknown))}" if unknown else "`skill` names the skills to load"
        return (f"Error: {what} — the Design skills are: {', '.join(SKILLS)}. Load the ones a design needs in one call: "
                "{\"action\": \"skill\", \"skill\": [\"design-direction\", \"graphic-design\"]}. Nothing was made or changed.")
    parts = [f"<design-skill name=\"{n}\">\n{SKILLS[n][1]}\n</design-skill>" for n in names]
    return "\n\n".join(parts) + "\n\nThese skills are loaded and stay with this chat. Nothing was made or changed by this call."

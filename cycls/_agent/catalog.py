"""Ready-made apps an agent offers (docs/notes/apps.md, "Ready-made apps"): built bundles in a folder or on a volume,
one per slug, as build_app would write them. Installing copies one into apps/<slug>/, so nothing downstream learns a
new kind of thing; what marks it as ours is the stamp in its app.json."""
import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

STAMP = "catalog"   # an installed app's app.json: the {version, at, shipped} of the bundle it came from
LOOKS = ("classic", "ocean", "palm", "sand", "rose", "custom")
_versions = {}      # (path, mtime, size) -> hash: a bundle on a volume is read again only once it changed
FOUND_FOR = 60      # seconds a folder's bundles are taken as read: one put on the volume shows within a minute
_found = {}         # (folder, slugs looked for) -> (when, slug -> its folder)


def _manifest(path):
    try:
        m = json.loads(Path(path).read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def bundles(folder, slugs=None):
    """slug -> its folder, for each one with an index.html: among `slugs` (the ones the CMS names), else all of them.
    Every look is a call over the volume, so what was found holds for FOUND_FOR."""
    key = (str(folder), None if slugs is None else tuple(slugs))
    at, found = _found.get(key, (float("-inf"), {}))
    if time.monotonic() - at > FOUND_FOR:
        folder = Path(folder)
        names = slugs if slugs is not None else sorted(d.name for d in folder.iterdir()) if folder.is_dir() else ()
        found = {s: folder / s for s in names if isinstance(s, str) and re.fullmatch(r"[\w-]+", s)
                 and (folder / s / "index.html").is_file()}
        _found[key] = (time.monotonic(), found)
    return found


def version(bundle):
    f = Path(bundle) / "index.html"
    st = f.stat()
    key = (str(f), st.st_mtime_ns, st.st_size)
    if key not in _versions:
        _versions[key] = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
    return _versions[key]


def own_copy(slug, bundle):
    """What a bundle's own app.json says about it, in the CMS's shape: for an agent with no `.cms(apps=…)`."""
    m = _manifest(Path(bundle) / "app.json")
    two = lambda k: {"en": str(m.get(k) or ""), "ar": str(m.get(f"{k}_ar") or "")}
    return {"slug": slug, "title": two("name"), "description": two("description"), "category": two("category"),
            "icon": "", "picture": "", "featured": False}


def _shipped(slug, copy):
    """The name and icon the gallery gives an app: an update brings them, unless the person changed theirs."""
    svg = copy.get("icon") or ""
    return {"name": copy["title"]["en"] or copy["title"]["ar"] or slug, "name_ar": copy["title"]["ar"],
            **({"icon": f"data:image/svg+xml;utf8,{quote(svg)}"} if svg.startswith("<svg") else {})}


def states(root, rows, found):
    """Each row's state in one workspace, its apps/ listed once rather than asked after slug by slug."""
    apps = Path(root) / "apps"
    have = {p.name for p in apps.iterdir()} if apps.is_dir() else set()
    return [state(root, a["slug"], found[a["slug"]], a) if a["slug"] in have else "available" for a in rows]


def state(root, slug, bundle, copy):
    """available | installed | update | changed | taken, for one bundle in one workspace. Update: its page, name or
    icon is new in the gallery. Changed: the agent rebuilt it after it was installed (build_app's `built`), so it is
    the person's now and no update writes over it. Taken: the slug is the person's own app."""
    app = Path(root) / "apps" / slug
    if not app.exists():
        return "available"
    m = _manifest(app / "app.json")
    if not isinstance(m.get(STAMP), dict):
        return "taken"
    if "built" in m:
        return "changed"
    now = _shipped(slug, copy)
    return "installed" if (m[STAMP].get("version"), m[STAMP].get("shipped", now)) == (version(bundle), now) else "update"


def install(root, slug, bundle, copy, trash):
    """Copy a bundle into apps/<slug>/, or over the copy there for an update: its data untouched, the page it replaces
    kept by `trash(rel)`, a name or icon the person changed kept. `copy` is what the gallery says about it (own_copy's
    shape)."""
    app = Path(root) / "apps" / slug
    was = _manifest(app / "app.json")
    shipped, before = _shipped(slug, copy), (was.get(STAMP) or {}).get("shipped") or {}
    m = {**{k: v for k, v in _manifest(Path(bundle) / "app.json").items() if k not in ("built", STAMP)}, **shipped,
         "description": copy["description"]["en"], "description_ar": copy["description"]["ar"],
         **{k: was[k] for k in ("name", "name_ar", "icon") if was.get(k) and was[k] != before.get(k)},
         STAMP: {"version": version(bundle), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "shipped": shipped}}
    app.mkdir(parents=True, exist_ok=True)
    (app / "data").mkdir(exist_ok=True)
    # The stamp first: a folder holding our page without it would read as the person's own.
    (app / "app.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    if (app / "index.html").exists():
        trash(f"apps/{slug}/index.html")
    for p in Path(bundle).rglob("*"):
        rel = p.relative_to(bundle)
        if p.is_file() and not p.is_symlink() and rel.parts[0] not in ("data", "app.json", "preview.webp"):
            (app / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, app / rel)   # copy2's chmod and utime are slow on gcsfuse
    return m


def clean_look(raw):
    """The look a workspace's apps wear: one of LOOKS, and for `custom` the company's colour."""
    look = raw.get("look") if isinstance(raw, dict) else None
    if look not in LOOKS:
        raise ValueError(f"look is one of {', '.join(LOOKS)}")
    if look != "custom":
        return {"look": look}
    color = str(raw.get("color") or "")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("a custom look needs a #rrggbb color")
    return {"look": look, "color": color.lower()}

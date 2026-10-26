"""An agent's app catalog: built bundles shipped in the image, installed into a workspace on request.

`cycls.Web().apps("default_apps")` names a folder of bundles, one per slug:

    default_apps/<slug>/index.html   the built app — what `build_app` would have written
    default_apps/<slug>/app.json     name, name_ar, icon, description, description_ar, category, category_ar
    default_apps/<slug>/README.md    the app's data model, for the agent
    default_apps/<slug>/src/**       its source, so `build_app` can rebuild it later

An install copies one into `apps/<slug>/` exactly as `build_app` lands an app, so nothing downstream —
the bridge, `appScope()`, the Apps tab, `app_catalog()`, the trash — learns a new kind of thing. What
marks it as ours is a stamp in its app.json, `"catalog": {"version", "at"}`; the version is the bundle's
content hash, so a redeploy that changes a bundle shows as an update in every workspace that has it.

The rules, in the order they bite:

- **A user's app is never touched.** A folder at `apps/<slug>/` with an index.html or app.json but no
  stamp is someone's own (built by the agent, written by hand, restored from the trash): install and
  update refuse it with 409, and uninstall refuses it with 409 — the Files/Apps delete is the way.
- **`data/` is never touched,** and neither is anything a person may have added beside the bundle.
- **Replacing is recoverable.** An update trashes the index.html it replaces, as a rebuild does.
- **The name and icon a person gave it stay** across updates; the description and the stamp are ours.
- **A fresh install starts on an empty shelf,** as `build_app` does on a fresh slug: rows left by a
  dead app of that slug would open under a schema that does not match.

`default_apps.py` in the super agent did the same per turn from the agent side; its stamp is
`"default_app"` and this module reads it as the same thing, so a workspace those agents seeded shows its
apps as installed-and-current here with no migration.
"""
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

STAMP = "catalog"
LEGACY_STAMP = "default_app"          # super's agent-side installer (default_apps.py)
_SLUG = re.compile(r"^[a-z0-9_-]{1,64}$")   # build_app's alphabet (_APP_SLUG_OK)
_SKIP = {"data", "app.json", "index.html"}   # handled explicitly, or never touched
_FIELDS = ("name", "name_ar", "icon", "description", "description_ar", "category", "category_ar")
_CAPS = {"name": 60, "name_ar": 60, "icon": 512, "description": 300, "description_ar": 300,
         "category": 40, "category_ar": 40}


class NotOurs(Exception):
    """The folder is a person's own app; the catalog leaves it alone."""


def valid_slug(slug):
    return isinstance(slug, str) and bool(_SLUG.fullmatch(slug))


def _manifest(path):
    try:
        m = json.loads(Path(path).read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _version(html_bytes):
    return hashlib.sha256(html_bytes).hexdigest()[:12]


def stamp_of(manifest):
    """The catalog stamp an installed app carries, from this module or the legacy installer — or None."""
    for k in (STAMP, LEGACY_STAMP):
        if isinstance(manifest.get(k), dict) and manifest[k].get("version"):
            return manifest[k]
    return None


class Catalog:
    """The bundles under one folder. Read once per process: the image does not change under it."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self._entries = None

    def entries(self):
        if self._entries is None:
            out = {}
            if self.folder.is_dir():
                for d in sorted(self.folder.iterdir()):
                    if not d.is_dir() or not valid_slug(d.name) or not (d / "index.html").is_file():
                        continue
                    m = _manifest(d / "app.json")
                    html = (d / "index.html").read_bytes()
                    row = {k: str(m[k])[:_CAPS[k]] for k in _FIELDS if isinstance(m.get(k), str) and m[k].strip()}
                    row.setdefault("name", d.name.replace("-", " ").replace("_", " ").title())
                    out[d.name] = {"slug": d.name, **row, "version": _version(html), "bytes": len(html)}
            self._entries = out
        return self._entries

    def bundle(self, slug):
        if slug not in self.entries():
            raise KeyError(slug)
        return self.folder / slug


def state_of(root, entry):
    """'available' | 'installed' | 'update' | 'conflict' for one catalog entry in a workspace."""
    app = Path(root) / "apps" / entry["slug"]
    if not app.exists():
        return "available"
    stamp = stamp_of(_manifest(app / "app.json"))
    if stamp is None:
        return "conflict" if ((app / "index.html").exists() or (app / "app.json").exists()) else "available"
    return "installed" if stamp.get("version") == entry["version"] else "update"


def listing(root, catalog):
    """The catalog as the Apps tab shows it: every entry with its state in this workspace."""
    rows = []
    for entry in catalog.entries().values():
        st = state_of(root, entry)
        installed = _manifest(Path(root) / "apps" / entry["slug"] / "app.json") if st in ("installed", "update") else {}
        rows.append({**entry, "state": st,
                     # a renamed install keeps its name; the card shows what the Apps tab shows
                     **({"installed_name": installed["name"]} if installed.get("name") and installed["name"] != entry["name"] else {})})
    return rows


def _copy_tree(src, dst):
    """README.md, src/** and any other shipped file; never data/, never the two written explicitly."""
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if rel.parts[0] in _SKIP or not p.is_file() or p.is_symlink():
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, out)   # copy2's chmod/utime are slow on gcsfuse


def install(root, catalog, slug, *, trash=None, allow_update=True):
    """Copy one bundle into `apps/<slug>/`. Returns 'installed' | 'updated' | 'current'.

    `trash(root, rel)` moves a replaced index.html to the trash (the caller passes the SDK's).
    Raises NotOurs for a person's own app at that slug, KeyError for a slug not in the catalog."""
    root = Path(root)
    bundle = catalog.bundle(slug)
    entry = catalog.entries()[slug]
    app = root / "apps" / slug
    st = state_of(root, entry)
    if st == "conflict":
        raise NotOurs(slug)
    if st == "installed":
        return "current"
    if st == "update" and not allow_update:
        return "current"
    fresh = st == "available"
    current = _manifest(app / "app.json")
    shipped = _manifest(bundle / "app.json")
    shipped.pop("extension", None)          # build_app must stay able to rebuild it
    shipped.pop(LEGACY_STAMP, None)
    keep = {k: current[k] for k in ("name", "icon") if not fresh and current.get(k)}
    manifest = {**shipped, **keep}
    manifest.pop(LEGACY_STAMP, None)        # one stamp from now on
    manifest[STAMP] = {"version": entry["version"],
                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    app.mkdir(parents=True, exist_ok=True)
    (app / "data").mkdir(exist_ok=True)
    # The stamp first: a folder holding our index.html without it would read as a person's app.
    (app / "app.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    index = app / "index.html"
    if index.exists() and trash is not None:
        try:
            trash(root, f"apps/{slug}/index.html")
        except Exception:
            pass
    index.write_bytes((bundle / "index.html").read_bytes())
    _copy_tree(bundle, app)
    return "installed" if fresh else "updated"


def is_ours(root, slug):
    return stamp_of(_manifest(Path(root) / "apps" / slug / "app.json")) is not None


# ---- The workspace's app theme --------------------------------------------------------------
#
# One choice per workspace — what every member's apps wear — so it is a row in the workspace's
# `.apps` slot, not the person's `.settings` (which is one per person and follows them across
# workspaces). The key `.theme` can never be a slug's prefix: build_app's alphabet has no dot.
# The server keeps the CHOICE only; the CSS tokens are derived in the client (lib/app-theme.ts),
# which also needs them for the live preview before anything is saved.

THEME_KEY = ".theme"
BASES = ("neutral", "zinc", "slate", "stone")
COLORS = ("base", "blue", "green", "orange", "red", "rose", "violet", "yellow")
RADII = (0, 0.3, 0.5, 0.625, 0.75, 1.0)
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean_theme(raw):
    """A theme from a request, validated field by field. Raises ValueError naming the field."""
    if not isinstance(raw, dict):
        raise ValueError("a theme is an object")
    out = {}
    base = raw.get("base", "neutral")
    if base not in BASES:
        raise ValueError(f"base is one of {', '.join(BASES)}")
    out["base"] = base
    color = raw.get("color", "base")
    if color not in COLORS:
        raise ValueError(f"color is one of {', '.join(COLORS)}")
    out["color"] = color
    radius = raw.get("radius", 0.625)
    if not isinstance(radius, (int, float)) or isinstance(radius, bool) or float(radius) not in RADII:
        raise ValueError(f"radius is one of {', '.join(str(r) for r in RADII)} (rem)")
    out["radius"] = float(radius)
    primary = raw.get("primary")
    if primary not in (None, ""):
        if not isinstance(primary, str) or not _HEX.fullmatch(primary):
            raise ValueError("primary is a #rrggbb color")
        out["primary"] = primary.lower()
    return out

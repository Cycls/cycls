"""Put the Studio app into a workspace, and keep it current.

Mirrors how build_app installs (tools._exec_build_app): the bundle is ours
(shipped in the package), the data is the user's. A bundle whose hash changed
is replaced — the old one to the trash — and nothing under data/ is touched
except seeding an empty scene the first time.
"""
import asyncio
import hashlib
import json
import pathlib
from datetime import datetime, timezone

from . import APP_DIR, SCENE, SLUG
from . import scene as S

BUNDLE = pathlib.Path(__file__).parent / "app" / "index.html"
ICON = "🧊"
DESCRIPTION = "Blender-style 3D studio — build a scene in chat, move things by hand, render with Blender."

README = """# Studio

A Blender-style 3D scene, rendered by real Blender. **Change it with the `studio`
tool, not by editing these files** — the tool validates every change, keeps the
open app in sync and lets a change be reverted.

- `data/scene.json` — the scene document (format `cycls.studio.scene`, version 3).
  Z up, metres, angles in degrees (Euler XYZ), colours as sRGB hex. `objects`,
  `meshes`, `materials` and `textures` are maps keyed by id; `animation` is the
  timeline and an object's `keys` its motion; `rev` counts saves.
- `data/meshes/m-<hash>.json`, `data/textures/t-<hash>.json` — explicit meshes and
  images (base64), immutable.
- `data/history/<rev>.json` — the scenes the last agent edits replaced.
- `data/renders.json` — the renders made from this scene (images and videos are in `renders/`).
- `data/jobs/` — videos rendering, a chunk at a time, while the Studio is open.
"""


def bundle():
    text = BUNDLE.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode()).hexdigest()[:12]


class InstallError(Exception):
    pass


def _manifest(app):
    try:
        m = json.loads((app / "app.json").read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _install(root, html, version):
    from .. import trash
    app = pathlib.Path(root) / APP_DIR
    fresh = not app.exists()
    manifest = _manifest(app)
    if not fresh and not manifest.get("studio") and (app / "index.html").exists():
        raise InstallError(f"{APP_DIR}/ is another app — rename or remove it to use Studio")
    changed = fresh or manifest.get("studio", {}).get("version") != version
    (app / "data").mkdir(parents=True, exist_ok=True)
    scene = pathlib.Path(root) / SCENE
    if not scene.exists():
        scene.write_text(json.dumps(S.new_scene(), indent=1), encoding="utf-8")
    if not changed:
        return fresh, changed
    # The stamp first: a folder with our index.html but no stamp reads as someone else's app.
    manifest.update(name=manifest.get("name") or "Studio", icon=manifest.get("icon") or ICON,
                    description=DESCRIPTION,
                    studio={"version": version},
                    built={"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "source": "cycls", "builder": f"studio-{version}"})
    (app / "app.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    entry = app / "index.html"
    if entry.exists():
        trash.trash_path(root, f"{APP_DIR}/index.html", by="agent", reason="upgrade")
    entry.write_text(html, encoding="utf-8")
    (app / "README.md").write_text(README, encoding="utf-8")
    return fresh, changed


_locks = {}


async def ensure_installed(ws):
    """Idempotent; cheap when current. Returns 'installed' | 'upgraded' | None."""
    from ..state import app_shelf, apps_db
    html, version = bundle()
    key = str(pathlib.Path(ws.root).resolve())
    async with _locks.setdefault(key, asyncio.Lock()):
        fresh, changed = await asyncio.to_thread(_install, ws.root, html, version)
    if fresh:                     # a reused slug must not inherit another app's rows
        await apps_db(ws).delete(app_shelf(SLUG))
    if changed:
        from .. import tools
        tools._apps_cache.pop(ws.root, None)
    return "installed" if fresh else "upgraded" if changed else None

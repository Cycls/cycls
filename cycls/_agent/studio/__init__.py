"""Cycls Studio — a Blender-style 3D environment as a workspace app, with real
Blender (a deployed engine) behind it. See docs/notes/studio.md.

Enabled with `.allowed_tools([..., "Studio"])` once CYCLS_STUDIO_ENGINE names the
engine deployment (and an API key can call it). Unset, the tool is silently absent,
like Browser without BROWSER_URL.
"""
import os

SLUG = "studio"
APP_DIR = f"apps/{SLUG}"
SCENE = f"{APP_DIR}/data/scene.json"


def engine_name():
    return os.environ.get("CYCLS_STUDIO_ENGINE") or None


def renderer_name():
    """Final renders may live on their own deployment; interactive ops then never
    queue behind a minute-long render."""
    return os.environ.get("CYCLS_STUDIO_RENDERER") or engine_name()


def configured():
    from cycls._function.main import _get_api_key
    return bool(engine_name() and _get_api_key())

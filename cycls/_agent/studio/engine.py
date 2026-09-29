"""The Blender engine, called by name with cycls.remote. The engine is stateless:
the scene document and the mesh files it references go up with every call, and
bytes come back in the reply (never a pickle built from Blender's output)."""
import asyncio

from . import engine_name, renderer_name

TIMEOUTS = {"evaluate": 90, "apply": 150, "snapshot": 150, "render": 660, "export": 210,
            "script": 150, "import": 210, "selftest": 150, "ping": 60, "texture": 90}
APP_OPS = {"evaluate", "apply", "snapshot", "render", "export"}      # what the Studio app may ask for
AGENT_OPS = APP_OPS | {"script", "import", "texture"}


class EngineError(Exception):
    """The engine refused or failed; the message is written for the model/user."""


async def call(op, scene, *, blobs=None, params=None):
    import cycls
    from cycls._function.remote import RemoteError
    name = renderer_name() if op == "render" else engine_name()
    if not name:
        raise EngineError("Studio isn't configured (CYCLS_STUDIO_ENGINE)")
    fn = cycls.remote(name, timeout=TIMEOUTS.get(op, 120))
    try:
        r = await asyncio.to_thread(fn, op=op, scene=scene, blobs=blobs or {}, params=params or {})
    except RemoteError as e:
        if getattr(e, "status", None) in (429, 503):
            raise EngineError("the Studio engine is busy — try again in a minute") from None
        raise EngineError(f"the Studio engine is unavailable ({str(e)[:300]})") from None
    except Exception as e:
        raise EngineError(f"the Studio engine is unavailable ({type(e).__name__}: {str(e)[:300]})") from None
    if not isinstance(r, dict):
        raise EngineError(f"the Studio engine returned {type(r).__name__}, not a result")
    if not r.get("ok"):
        raise EngineError(str(r.get("error") or "the engine failed")[:2000])
    return r

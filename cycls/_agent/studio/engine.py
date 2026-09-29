"""The Blender engine, called by name with cycls.remote. The engine is stateless:
the scene document and the mesh files it references go up with every call, and
bytes come back in the reply (never a pickle built from Blender's output)."""
import asyncio
import gzip

from . import engine_name, renderer_name

TIMEOUTS = {"evaluate": 90, "apply": 150, "snapshot": 150, "render": 660, "export": 210,
            "script": 150, "import": 210, "selftest": 150, "ping": 60, "texture": 90}
APP_OPS = {"evaluate", "apply", "snapshot", "render", "export"}      # what the Studio app may ask for
AGENT_OPS = APP_OPS | {"script", "import", "texture"}


PACK_MIN = 256_000           # smaller files aren't worth compressing


class EngineError(Exception):
    """The engine refused or failed; the message is written for the model/user."""


def pack(blobs):
    """Lossless gzip for the files worth it: a .blend saved uncompressed is ~27% of itself, mesh
    files ~60%. An agent on a laptop sends a big scene over a slow uplink with every call. What
    barely shrinks (images, a compressed .blend) goes as it is."""
    out = {}
    for name, data in (blobs or {}).items():
        raw = data.encode() if isinstance(data, str) else data
        if len(raw) >= PACK_MIN:
            z = gzip.compress(raw, compresslevel=1)          # level 1: nearly level 6's ratio, 3x faster
            if len(z) < 0.9 * len(raw):
                out[name + ".gz"] = z
                continue
        out[name] = data
    return out


def unpack(files):
    return {(n[:-3] if n.endswith(".gz") else n): (gzip.decompress(v) if n.endswith(".gz") else v)
            for n, v in (files or {}).items()}


async def call(op, scene, *, blobs=None, params=None):
    import cycls
    from cycls._function.remote import RemoteError
    name = renderer_name() if op == "render" else engine_name()
    if not name:
        raise EngineError("Studio isn't configured (CYCLS_STUDIO_ENGINE)")
    packed = await asyncio.to_thread(pack, blobs)
    # A 100 MB scene takes minutes just to go up from a slow uplink (a laptop running the
    # agent): the timeout grows with what's sent, ~4 s a megabyte.
    up = sum(len(v) for v in packed.values())
    fn = cycls.remote(name, timeout=TIMEOUTS.get(op, 120) + up // 250_000)
    try:
        r = await asyncio.to_thread(fn, op=op, scene=scene, blobs=packed, params=params or {}, gzip=True)
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
    if any(n.endswith(".gz") for n in r.get("files") or {}):
        r["files"] = await asyncio.to_thread(unpack, r["files"])
    return r

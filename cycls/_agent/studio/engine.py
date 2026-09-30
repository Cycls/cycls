"""The Blender engine, called by name with cycls.remote. The engine is stateless:
the scene document and the mesh files it references go up with every call, and
bytes come back in the reply (never a pickle built from Blender's output)."""
import asyncio
import gzip
import hashlib
import pathlib

from . import engine_name, renderer_name

TIMEOUTS = {"evaluate": 90, "apply": 150, "snapshot": 150, "render": 660, "export": 210,
            "script": 150, "import": 330, "selftest": 150, "ping": 60, "texture": 90,
            "video": 660, "encode": 210}
LONG_OPS = {"render", "video", "encode"}      # a separate renderer takes these, when there is one
APP_OPS = {"evaluate", "apply", "snapshot", "render", "export"}      # what the Studio app may ask for
AGENT_OPS = APP_OPS | {"script", "import", "texture"}


PACK_MIN = 256_000           # smaller files aren't worth compressing
CACHEABLE = ("meshes/", "textures/")     # named by their content: the engine may already have them


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


def cache_key(ws):
    """This workspace's shelf in the engine's file cache: private to whoever holds the API key."""
    from cycls._function.main import _get_api_key
    return hashlib.sha256(f"{_get_api_key()}|{pathlib.Path(ws.root).resolve()}".encode()).hexdigest()[:32]


async def call(op, scene, *, blobs=None, params=None, ws=None):
    """One engine op. With `ws`, the mesh and image files go by name first: the engine keeps
    what it has been sent (per workspace), answers with what it's missing, and only those
    follow — a snapshot after a lighting change sends none of a big scene's meshes."""
    name = renderer_name() if op in LONG_OPS else engine_name()
    if not name:
        raise EngineError("Studio isn't configured (CYCLS_STUDIO_ENGINE)")
    blobs = blobs or {}
    if ws is None:
        return await _send(name, op, scene, blobs, params)
    ns = cache_key(ws)
    held = {n: v for n, v in blobs.items() if n.startswith(CACHEABLE)}
    inline = {n: v for n, v in blobs.items() if n not in held}
    extra = {"cache": ns, "refs": sorted(held)}
    r = await _send(name, op, scene, inline, params, extra)
    for attempt in (1, 2):                 # the missing ones; then everything, if another instance answered
        if r.get("ok") or not r.get("missing"):
            break
        send = {n: held[n] for n in r["missing"] if n in held} if attempt == 1 else held
        r = await _send(name, op, scene, {**inline, **send}, params, extra)
    return _result(r)


async def _send(name, op, scene, blobs, params, extra=None):
    import cycls
    from cycls._function.remote import RemoteError
    packed = await asyncio.to_thread(pack, blobs)
    # A 100 MB scene takes minutes just to go up from a slow uplink (a laptop running the
    # agent): the timeout grows with what's sent, ~4 s a megabyte.
    up = sum(len(v) for v in packed.values())
    fn = cycls.remote(name, timeout=TIMEOUTS.get(op, 120) + up // 250_000, sticky=True)
    try:
        r = await asyncio.to_thread(fn, op=op, scene=scene, blobs=packed, params=params or {}, gzip=True,
                                    **(extra or {}))
    except RemoteError as e:
        if getattr(e, "status", None) in (429, 503):
            raise EngineError("the Studio engine is busy — try again in a minute") from None
        raise EngineError(f"the Studio engine is unavailable ({str(e)[:300]})") from None
    except Exception as e:
        raise EngineError(f"the Studio engine is unavailable ({type(e).__name__}: {str(e)[:300]})") from None
    if not isinstance(r, dict):
        raise EngineError(f"the Studio engine returned {type(r).__name__}, not a result")
    if r.get("ok") and any(n.endswith(".gz") for n in r.get("files") or {}):
        r["files"] = await asyncio.to_thread(unpack, r["files"])
    return r if extra else _result(r)


def _result(r):
    if not r.get("ok"):
        raise EngineError(str(r.get("error") or "the engine failed")[:2000])
    return r

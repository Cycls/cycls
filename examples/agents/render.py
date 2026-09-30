# A 3D product-shot studio in chat: describe an object, get a Blender render on
# the canvas plus the .glb to orbit. The heavy part — headless Blender, a 1 GB
# image — is its own deployment, called by name; this agent's image stays small.
#
#   uv run cycls deploy render_fn.py        # once, from services/render → cycls-render
#   uv run cycls run examples/agents/render.py
#
# cycls.remote authenticates with CYCLS_API_KEY, so a deployed agent needs it in
# its .providers.env next to the model key.
import asyncio
import re
from pathlib import Path

import cycls

RENDERER = "cycls-render"

RENDER_TOOL = {
    "name": "render",
    "description": (
        "Render a studio product shot of one object with headless Blender (Cycles, CPU) and "
        "show it on the canvas. Also saves the object as a .glb 3D model. "
        "The default 1280x720 at 32 samples (denoised) takes about 40 seconds; 1920x1080 "
        "about a minute; more samples add time for little visible gain, so raise them only "
        "when the user asks for a final render. Glass and chrome show what "
        "surrounds them, so they read best on a dark or colored backdrop."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "file name, e.g. 'gold-torus'"},
            "object": {"type": "string", "enum": ["sphere", "ico-sphere", "cube", "rounded-cube",
                                                  "torus", "cylinder", "cone", "monkey", "text"]},
            "text": {"type": "string",
                     "description": "the word to extrude when object is 'text' (Latin script, max 24)"},
            "material": {"type": "string",
                         "enum": ["gold", "brushed-gold", "chrome", "brushed-steel", "copper",
                                  "plastic", "matte", "ceramic", "glass", "rubber", "neon"]},
            "color": {"type": "string", "description": "hex color overriding the material's, e.g. '#1e6fd9'"},
            "metallic": {"type": "number", "minimum": 0, "maximum": 1},
            "roughness": {"type": "number", "minimum": 0, "maximum": 1},
            "backdrop": {"type": "string", "description": "hex color of the studio sweep behind the object"},
            "lighting": {"type": "string", "enum": ["studio-3point", "softbox", "dramatic", "rim"]},
            "camera": {"type": "string", "enum": ["front", "front-3/4", "side", "top", "low", "hero"]},
            "focal_mm": {"type": "number", "minimum": 18, "maximum": 200},
            "resolution": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2,
                           "description": "[width, height]; at most 1920x1080 worth of pixels"},
            "samples": {"type": "integer", "minimum": 1, "maximum": 256},
        },
        "required": ["name", "object"],
    },
}


def _slug(s):
    return re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")[:48] or "render"


def _config(args):
    cfg = {k: args[k] for k in ("object", "text", "backdrop", "lighting", "resolution", "samples")
           if args.get(k) is not None}
    material = {"preset": args.get("material") or "plastic"}
    material.update({k: args[k] for k in ("color", "metallic", "roughness") if args.get(k) is not None})
    camera = {"angle": args.get("camera") or "front-3/4"}
    if args.get("focal_mm"):
        camera["focal_mm"] = args["focal_mm"]
    return {**cfg, "material": material, "camera": camera}


async def render(args, ctx):
    try:
        r = await asyncio.to_thread(cycls.remote(RENDERER, timeout=900), _config(args))
    except Exception as e:
        return f"Error: the render service is unavailable ({type(e).__name__}: {e})"
    if not r.get("ok"):
        return f"Error: {r['error']}"      # a bad config says exactly which field to fix

    folder = Path(ctx.workspace.root) / "renders"
    folder.mkdir(parents=True, exist_ok=True)
    base = name = _slug(args.get("name") or args["object"])
    n = 1
    while (folder / f"{name}.png").exists() or (folder / f"{name}.glb").exists():
        n += 1
        name = f"{base}-{n}"
    await asyncio.to_thread((folder / f"{name}.png").write_bytes, r["png"])
    if r.get("glb"):
        await asyncio.to_thread((folder / f"{name}.glb").write_bytes, r["glb"])

    cfg, rel = r["config"], f"renders/{name}.png"
    w, h = cfg["resolution"]
    ack = (f"Rendered {rel} ({w}x{h}, {cfg['samples']} samples, {r['render_seconds']:.0f}s "
           f"in Blender {r['blender']}) and opened it on the canvas.")
    if r.get("glb"):
        ack += f" The 3D model is renders/{name}.glb — the canvas can open it for orbiting."
    ui = {"type": "ui", "action": "open_canvas", "path": rel, "name": f"{name}.png"}
    if not r.get("preview"):
        return {"_model": ack, "_ui": ui}
    import base64
    ack += " The render is attached: check it matches the request before you describe it."
    return {"_model": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(r["preview"]).decode()}},
                       {"type": "text", "text": ack}],
            "_ui": ui}


llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-5")
    .system(
        "You are a 3D product-shot studio. Turn what the user describes into one `render` call: "
        "pick the closest object, material and lighting, and use `color` and `backdrop` (hex) "
        "for anything the presets don't cover. Keep the defaults (1280x720, 32 samples) unless "
        "the user asks for a final or high-resolution render. Afterwards say in a sentence or "
        "two what you rendered and offer one concrete variation. If a render errors, fix the "
        "field it names and try once more."
    )
    .tools([RENDER_TOOL])
    .on("render", render, label=lambda i: i.get("name") or i.get("object", "render"))
)


@cycls.agent(
    image=cycls.Image().copy(".providers.env", ".env"),
    web=cycls.Web().auth(cycls.Clerk()).title("Shots"),
    volumes={"/workspace": cycls.Volume("render-agent")},
)
async def shots(context):
    async for ev in llm.run(context=context):
        yield ev

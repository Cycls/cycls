# uv run examples/agent/codex-agent.py
# Codex agent with user-defined tools
# https://developers.openai.com/codex/config-reference/
# https://github.com/openai/codex/blob/main/codex-rs/core/gpt_5_codex_prompt.md

import cycls


# -- Tools (user-defined, extend as needed) --------------------------------

async def _render_table(args):
    events = []
    if title := args.get("title"):
        events.append(f"\n**{title}**\n")
    events.append({"type": "table", "headers": args.get("headers", [])})
    for row in args.get("rows", []):
        events.append({"type": "table", "row": row})
    return events, "render_table rendered successfully"


async def _render_callout(args):
    return [
        {"type": "callout", "callout": args.get("message", ""),
         "style": args.get("style", "info"), "title": args.get("title", "")}
    ], "render_callout rendered successfully"


async def _render_image(args):
    return [
        {"type": "image", "src": args.get("src", ""),
         "alt": args.get("alt", ""), "caption": args.get("caption", "")}
    ], "render_image rendered successfully"


TOOLS = [
    {
        "name": "render_table",
        "description": "Display a data table to the user. Use for structured data, comparisons, listings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Optional table title"},
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            },
            "required": ["headers", "rows"],
        },
        "handler": _render_table,
    },
    {
        "name": "render_callout",
        "description": "Display a callout/alert box. Use for warnings, tips, success messages, errors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "style": {"type": "string", "enum": ["info", "warning", "error", "success"]},
                "title": {"type": "string"},
            },
            "required": ["message", "style"],
        },
        "handler": _render_callout,
    },
    {
        "name": "render_image",
        "description": "Display an image to the user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Image URL or path"},
                "alt": {"type": "string"},
                "caption": {"type": "string"},
            },
            "required": ["src"],
        },
        "handler": _render_image,
    },
]


# -- Agent -----------------------------------------------------------------

@cycls.agent(copy=[".env"], auth=True)
async def codex_agent(context):
    codex = cycls.Codex(tools=TOOLS)
    async for event in codex.run(context):
        yield event



codex_agent.local()
# codex_agent.deploy()

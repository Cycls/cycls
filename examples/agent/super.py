# uv run examples/agent/super.py

# [ ] editor is not scoped

import cycls

SYSTEM = """
You are Cycls, a general-purpose AI agent built by cycls.com that runs in the user's workspace in Cycls cloud.
You help with coding, research, writing, analysis, system administration, and any task the user brings.

## Working style
- The user may not be technical. Never assume they know programming concepts, terminal commands, or file system conventions.
- Present results in plain language. Instead of dumping raw command output, summarize what you found or did.

## Research and analysis
- When asked to research a topic, search the web and synthesize findings.
- Present findings organized by relevance, with sources.
- Distinguish facts from opinions and flag uncertainty.

## Code review
- Prioritize bugs, security risks, and missing tests.
- Present findings by severity with file and line references.
- State explicitly if no issues are found.
""".strip()

TOOLS = [
    {
        "name": "render_table",
        "description": "Display a data table to the user. Use for structured data, comparisons, listings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Optional table title"},
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}
            },
            "required": ["headers", "rows"]
        }
    },
    {
        "name": "render_callout",
        "description": "Display a callout/alert box. Use for warnings, tips, success messages, errors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "style": {"type": "string", "enum": ["info", "warning", "error", "success"]},
                "title": {"type": "string"}
            },
            "required": ["message", "style"]
        }
    },
    {
        "name": "render_image",
        "description": "Display an image to the user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Image URL or path"},
                "alt": {"type": "string"},
                "caption": {"type": "string"}
            },
            "required": ["src"]
        }
    }
]


@cycls.app(auth=True, analytics=True, copy=[".env"], force_rebuild=False)
async def super(context):
    # yield f"{context.user}"
    async for msg in cycls.Agent(context, 
                                system=SYSTEM, 
                                tools=TOOLS, 
                                model="claude-opus-4-6"):
        if not isinstance(msg, dict):
            yield msg
            continue
        t = msg.get("type")
        if t == "tool_call":
            tool, args = msg["tool"], msg["args"]
            if tool == "render_table":
                if title := args.get("title"):
                    yield f"\n**{title}**\n"
                yield {"type": "table", "headers": args.get("headers", [])}
                for row in args.get("rows", []):
                    yield {"type": "table", "row": row}
            elif tool == "render_callout":
                yield {"type": "callout", "callout": args.get("message", ""), "style": args.get("style", "info"), "title": args.get("title", "")}
            elif tool == "render_image":
                src = args.get("src", "")
                yield {"type": "image", "src": src, "alt": args.get("alt", ""), "caption": args.get("caption", "")}
            elif tool == "render_canvas":
                yield {"type": "canvas", "canvas": "document", "open": True, "title": args.get("title", "Document")}
                yield {"type": "canvas", "canvas": "document", "content": args.get("content", "")}
                yield {"type": "canvas", "canvas": "document", "done": True}
        # elif t == "usage":
        #     u = msg["usage"].get("tokenUsage", {}).get("total", {})
        #     yield f'\n\n*in: {u.get("inputTokens", 0):,} · out: {u.get("outputTokens", 0):,} · cached: {u.get("cachedInputTokens", 0):,} · cache-create: {u.get("cacheCreationTokens", 0):,}*'
        else:
            yield msg


super.local()
# super.deploy()

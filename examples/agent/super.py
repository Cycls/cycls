# uv run examples/agent/super.py

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
        "name": "render_chart",
        "description": "Display a chart to the user. Use for visualizing data trends, distributions, comparisons.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "chart_type": {"type": "string", "enum": ["bar", "line", "pie"]},
                "data": {"type": "object"}
            },
            "required": ["title", "chart_type", "data"]
        }
    }
]


@cycls.app(auth=True, analytics=True, copy=[".env"], force_rebuild=False) # .env here is bad
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
            elif tool == "render_chart":
                yield {"type": "chart", "title": args.get("title", ""), "chart_type": args.get("chart_type", "bar"), "data": args.get("data", {})}
        # elif t == "usage":
        #     u = msg["usage"].get("tokenUsage", {}).get("total", {})
        #     yield f'\n\n*in: {u.get("inputTokens", 0):,} · out: {u.get("outputTokens", 0):,} · cached: {u.get("cachedInputTokens", 0):,} · cache-create: {u.get("cacheCreationTokens", 0):,}*'
        else:
            yield msg


super.local()
# super.deploy()

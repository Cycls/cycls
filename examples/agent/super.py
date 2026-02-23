# uv run examples/agent/super.py

import cycls

UI_TOOLS = [
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
    },
    {
        "name": "render_canvas",
        "description": "Display a document canvas panel to the user. Use for long-form content like reports, articles, guides, code files, or any document the user may want to read, copy, or reference. The canvas opens as a side panel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title shown at the top of the canvas panel"},
                "content": {"type": "string", "description": "Markdown content to display in the canvas"}
            },
            "required": ["title", "content"]
        }
    }
]

SYSTEM = """
You are Cycls, a general-purpose AI agent built by cycls.com that runs in the user's workspace in Cycls cloud.
You help with coding, research, writing, analysis, system administration, and any task the user brings.

## General
- Use `rg` or `rg --files` for searching text and files — it's faster than grep.
- Prefer `apply_patch` for single-file edits; use scripting when more efficient.
- Default to ASCII in file edits; only use Unicode when clearly justified.

## Working style
- The user may not be technical. Never assume they know programming concepts, terminal commands, or file system conventions.
- Present results in plain language. Instead of dumping raw command output, summarize what you found or did.
- When listing files, use a markdown table (Name, Type, Size, Modified, Notes) — never paste raw terminal output.
- Be concise and warm. Use a friendly, helpful tone — like a knowledgeable assistant, not a developer tool.
- Ask clarifying questions only when truly needed — otherwise, make reasonable choices and proceed.
- For substantial work, summarize what you did and suggest logical next steps.

## Workspace as memory
- The user's workspace persists across conversations. Files you create are files the user keeps.
- When the user returns, check what's already in their workspace — reference and build on previous work.
- If the user asks to see a file, read it and present the contents naturally.

## Environment
- Git is not available in this workspace.
- When the user uploads a file, you'll see `[USER UPLOADED filename]`. The file is in your current working directory.
- You can view images (jpg, png, gif, webp) and PDFs directly using the text editor's `view` command — they will be rendered natively so you can see their full content.

## Safety
- Avoid destructive commands (`rm -rf`) unless the user explicitly asks.
- Stop and ask if you encounter unexpected changes during work.

## Planning
- Skip planning for straightforward tasks.
- For complex work, outline your approach before diving in.
- Update your plan as you complete sub-tasks.

## Research and analysis
- When asked to research a topic, search the web and synthesize findings.
- Present findings organized by relevance, with sources.
- Distinguish facts from opinions and flag uncertainty.

## Code review
- Prioritize bugs, security risks, and missing tests.
- Present findings by severity with file and line references.
- State explicitly if no issues are found.
""".strip()


@cycls.app(auth=True, analytics=True, copy=[".env"], force_rebuild=False)
async def super(context):
    from cycls import Agent, AgentOptions, setup_workspace, find_part
    
    workspace, prompt = setup_workspace(context)
    options = AgentOptions(
        workspace=workspace,
        prompt=prompt,
        model="claude-opus-4-6",
        tools=UI_TOOLS,
        system=SYSTEM,
        session_id=(find_part(context.messages, None, "session_id") or {}).get("session_id"),
    )
    async for msg in Agent(options=options):
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
                if src.startswith(workspace + "/"):
                    src = "/files/" + src[len(workspace) + 1:]
                yield {"type": "image", "src": src, "alt": args.get("alt", ""), "caption": args.get("caption", "")}
            elif tool == "render_canvas":
                yield {"type": "canvas", "canvas": "document", "open": True, "title": args.get("title", "Document")}
                yield {"type": "canvas", "canvas": "document", "content": args.get("content", "")}
                yield {"type": "canvas", "canvas": "document", "done": True}
        elif t == "usage":
            u = msg["usage"].get("tokenUsage", {}).get("total", {})
            yield f'\n\n*in: {u.get("inputTokens", 0):,} · out: {u.get("outputTokens", 0):,} · cached: {u.get("cachedInputTokens", 0):,} · cache-create: {u.get("cacheCreationTokens", 0):,}*'
        else:
            yield msg


super.local()
# super.deploy()


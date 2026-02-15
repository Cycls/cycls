# uv run examples/agent/codex-agent.py
# Minimal Codex app-server agent
# https://developers.openai.com/codex/config-reference/
# https://github.com/openai/codex/blob/main/codex-rs/core/gpt_5_codex_prompt.md
# https://github.com/Piebald-AI/claude-code-system-prompts/tree/main

import cycls
from cycls.agent import CodexAgent, CodexAgentOptions, setup_workspace, find_part

# --- Config ---

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
    }
]

# https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide
BASE_INSTRUCTIONS = """
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
- After substantial research, analysis, or writing, save the output as a file (e.g. `report.md`, `notes.txt`). Tell the user you saved it.
- Organize naturally: create folders for topics when it makes sense (e.g. `research/`, `drafts/`).
- When the user returns, check what's already in their workspace — reference and build on previous work.
- If the user asks to see a file, read it and present the contents naturally.

## Environment
- Git is not available in this workspace.
- When the user uploads a file, you'll see `[USER UPLOADED filename]`. The file is in your current working directory.

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

AGENTS_MD = """
you're a lawyer
""".strip()


@cycls.agent(auth=True, analytics=True, copy=[".env"])
async def codex_agent(context):
    ws, prompt = setup_workspace(context, instructions=BASE_INSTRUCTIONS, agent_instructions=AGENTS_MD)
    options = CodexAgentOptions(
        workspace=ws,
        prompt=prompt,
        model="gpt-5.2-codex",
        effort="high",
        tools=UI_TOOLS,
        policy="never",
        sandbox="danger-full-access",
        session_id=(find_part(context.messages, None, "session_id") or {}).get("session_id"),
        pending=find_part(context.messages, "assistant", "pending_approval"),
    )
    async for message in CodexAgent(options=options):
        if not isinstance(message, dict):
            yield message
            continue
        t = message.get("type")
        if t == "tool_call":
            tool, args = message["tool"], message["args"]
            if tool == "render_table":
                if title := args.get("title"):
                    yield f"\n**{title}**\n"
                yield {"type": "table", "headers": args.get("headers", [])}
                for row in args.get("rows", []):
                    yield {"type": "table", "row": row}
            elif tool == "render_callout":
                yield {"type": "callout", "callout": args.get("message", ""), "style": args.get("style", "info"), "title": args.get("title", "")}
            elif tool == "render_image":
                yield {"type": "image", "src": args.get("src", ""), "alt": args.get("alt", ""), "caption": args.get("caption", "")}
        elif t == "approval":
            desc = f"\n**Bash(** {message['command']} **)**\n"
            if message.get("cwd"):
                desc += f"dir: `{message['cwd']}`\n"
            if message.get("reason"):
                desc += f"reason: {message['reason']}\n"
            yield {"type": "thinking", "thinking": desc + "Reply **yes** to approve."}
            yield {"type": "pending_approval", "action_type": message["method"], "action_detail": message["command"]}
        elif t == "diff":
            yield {"type": "canvas", "canvas": "document", "open": True, "title": "Changes"}
            yield {"type": "canvas", "canvas": "document", "content": message["diff"]}
            yield {"type": "canvas", "canvas": "document", "done": True}
        elif t == "usage":
            u = message["usage"].get("tokenUsage", {}).get("total", {})
            inp, cached, out = u.get("inputTokens", 0), u.get("cachedInputTokens", 0), u.get("outputTokens", 0)
            yield f'\n\n*in: {inp:,} · out: {out:,} · cached: {cached:,}*'
        else:
            yield message


codex_agent.local()
# codex_agent.deploy()

# export CYCLS_API_KEY=
# uv run examples/agent/codex-agent.py

import re
import cycls


def extract_session_id(messages):
    """Extract session_id from previous assistant messages."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str):
                match = re.search(r"<!--s:(.+?)-->", content)
                if match:
                    return match.group(1)
    return None


@cycls.app(apt=["nodejs", "npm"], copy=[".env"], memory="512Mi", run_commands=["npm i -g @openai/codex"])
async def codex_agent(context):
    import os
    import json
    import asyncio

    yield {"type": "thinking", "thinking": "Analyzing your request..."}

    # Per-user workspace and config
    user_id = context.user.id if context.user else "default"
    user_workspace = f"/workspace/{user_id}"
    user_codex_home = f"{user_workspace}/.codex"
    os.makedirs(user_workspace, exist_ok=True)
    os.makedirs(user_codex_home, exist_ok=True)

    session_id = extract_session_id(context.messages)

    # Build command
    if session_id:
        # Resume existing session (--cd not supported for resume)
        cmd = ["codex", "exec", "resume", "--json", "--full-auto", "--skip-git-repo-check", session_id, context.last_message]
    else:
        # New session
        cmd = ["codex", "exec", "--json", "--full-auto", "--skip-git-repo-check", "--cd", user_workspace, context.last_message]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=user_workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "NO_COLOR": "1",
            "CODEX_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "CODEX_HOME": user_codex_home,
        },
    )

    yield {"type": "thinking", "thinking": "Done.", "done": True}

    new_session_id = None

    async for line in proc.stdout:
        try:
            event = json.loads(line.decode().strip())
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")

        # Capture session_id for continuity
        if event_type == "thread.started":
            new_session_id = event.get("thread_id")

        elif event_type == "item.started":
            item = event.get("item", {})
            item_type = item.get("type", "")

            if item_type == "command_execution":
                cmd_str = item.get("command", "")
                yield {"type": "step", "step": f"Running: {cmd_str[:50]}..."}
            elif item_type == "file_change":
                yield {"type": "step", "step": f"Editing file..."}
            elif item_type == "web_search":
                yield {"type": "step", "step": "Searching web..."}
            elif item_type == "reasoning":
                text = item.get("text", "")
                if text:
                    yield {"type": "thinking", "thinking": text}

        elif event_type == "item.completed":
            item = event.get("item", {})
            item_type = item.get("type", "")

            if item_type == "agent_message":
                text = item.get("text", "")
                if text:
                    yield text
            elif item_type == "reasoning":
                text = item.get("text", "")
                if text:
                    yield {"type": "thinking", "thinking": text}

    await proc.wait()

    # Check for errors
    stderr = await proc.stderr.read()
    if stderr:
        yield {"type": "callout", "callout": stderr.decode(), "style": "error"}

    # Embed session_id for resume
    if new_session_id:
        yield f"\u200B<!--s:{new_session_id}-->\u200B"


codex_agent.local()
# codex_agent.deploy()

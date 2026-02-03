# export CYCLS_API_KEY=
# uv run examples/agent/codex-agent.py
# ref: https://github.com/cheolwanpark/codex-client/tree/main

import cycls


def extract_session_id(messages):
    try:
        return (getattr(messages, "raw", None) or messages)[1]["parts"][-1]["session_id"]
    except:
        return None


async def handle_event(event, state):
    event_type = event.get("type", "")

    if event_type == "thread.started":
        state["session_id"] = event.get("thread_id")
        return

    if event_type in ("session.configured", "task.started", "task.completed", "token.count"):
        return

    if event_type == "item.started":
        item = event.get("item", {})
        item_type = item.get("type", "")
        if item_type == "command_execution":
            yield {"type": "step", "step": f"Running: {item.get('command', '')[:50]}..."}
        elif item_type == "file_change":
            yield {"type": "step", "step": "Editing file..."}
        elif item_type == "web_search":
            yield {"type": "step", "step": "Searching web..."}
        elif item_type == "tool_call":
            yield {"type": "step", "step": f"Using tool: {item.get('tool', '')}..." if item.get("tool") else "Using tool..."}
        return

    if event_type == "item.completed":
        item = event.get("item", {})
        item_type = item.get("type", "")
        if item_type == "agent_message" and item.get("text"):
            yield item["text"]
        elif item_type == "reasoning" and item.get("text"):
            yield {"type": "thinking", "thinking": item["text"]}
        return

    if event_type == "tool.call.started":
        yield {"type": "step", "step": f"Using tool: {event.get('tool', '')}..." if event.get("tool") else "Using tool..."}
    elif event_type == "tool.call.completed":
        yield {"type": "step", "step": "Tool finished"}


@cycls.app(apt=["nodejs", "npm", "proot"], copy=[".env"], memory="512Mi", run_commands=["npm i -g @openai/codex"], auth=True)
async def codex_agent(context):
    import os
    import json
    import asyncio

    yield {"type": "thinking", "thinking": "Analyzing your request..."}

    # Per-user workspace and config
    user_id = context.user.id if context.user else "default"
    session_id = extract_session_id(context.messages)
    user_workspace = f"/workspace/{user_id}"
    os.makedirs(f"{user_workspace}/.codex", exist_ok=True)

    # Build command - use proot to isolate user to their workspace
    codex_cmd = ["codex", "--yolo", "exec"]
    if session_id:
        codex_cmd += ["resume", "--json", "--skip-git-repo-check", session_id, context.last_message]
    else:
        codex_cmd += ["--json", "--skip-git-repo-check", context.last_message]

    cmd = ["proot", "-b", f"{user_workspace}:/workspace", "-w", "/workspace"] + codex_cmd

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=user_workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "NO_COLOR": "1",
            "CODEX_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "CODEX_HOME": "/workspace/.codex",
        },
    )

    state = {"session_id": None}

    while line := await proc.stdout.readline():
        try:
            event = json.loads(line)
            async for output in handle_event(event, state):
                yield output
        except json.JSONDecodeError:
            pass

    await proc.wait()

    # Check for errors
    stderr = await proc.stderr.read()
    if stderr:
        yield {"type": "callout", "callout": stderr.decode(), "style": "error"}

    # Embed session_id for resume
    if state["session_id"]:
        yield {"type": "session_id", "session_id": state["session_id"]}


codex_agent.local()
# codex_agent.deploy()

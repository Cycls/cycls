# export CYCLS_API_KEY=
# uv run examples/agent/codex-agent.py
# ref: https://github.com/cheolwanpark/codex-client/tree/main

import cycls


def extract_session_id(messages):
    """Extract session_id from previous assistant messages."""
    raw_messages = getattr(messages, "raw", None) or messages
    for msg in reversed(raw_messages):
        if msg.get("role") == "assistant":
            for part in msg.get("parts", []) or []:
                if part.get("type") == "session_id":
                    return part.get("session_id")
    return None


@cycls.app(apt=["nodejs", "npm"], copy=[".env"], memory="512Mi", run_commands=["npm i -g @openai/codex"], auth=True)
async def codex_agent(context):
    import os
    import json
    import asyncio

    # yield {"type": "thinking", "thinking": "Analyzing your request..."}

    # Per-user workspace and config (single workspace per user)
    user_id = context.user.id if context.user else "default"
    session_id = extract_session_id(context.messages)
    workspace_root = f"/workspace/{user_id}"
    user_workspace = workspace_root
    user_codex_home = f"{user_workspace}/.codex"
    os.makedirs(user_workspace, exist_ok=True)
    os.makedirs(user_codex_home, exist_ok=True)

    # Build command
    # Cloud Run kernel doesn't support Landlock - see https://github.com/openai/codex/issues/2267
    if session_id:
        cmd = ["codex", "--yolo", "exec", "resume", "--json", "--skip-git-repo-check", session_id, context.last_message]
    else:
        cmd = ["codex", "--yolo", "exec", "--json", "--skip-git-repo-check", context.last_message]

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

    # yield {"type": "thinking", "thinking": "Done.", "done": True}

    state = {"session_id": None}

    def emit_step(text):
        return {"type": "step", "step": text}

    async def handle_event(event):
        event_type = event.get("type", "")

        # Capture session_id for continuity
        if event_type == "thread.started":
            state["session_id"] = event.get("thread_id")
            return

        # Session/task lifecycle (ignore; we only emit step/thinking)
        if event_type in ("session.configured", "task.started", "task.completed", "token.count"):
            return

        # Item-based events
        if event_type == "item.started":
            item = event.get("item", {})
            item_type = item.get("type", "")

            if item_type == "command_execution":
                cmd_str = item.get("command", "")
                yield emit_step(f"Running: {cmd_str[:50]}...")
            elif item_type == "file_change":
                yield emit_step("Editing file...")
            elif item_type == "web_search":
                yield emit_step("Searching web...")
            elif item_type == "tool_call":
                tool = item.get("tool", "")
                yield emit_step(f"Using tool: {tool}" if tool else "Using tool...")
            # elif item_type == "reasoning":
            #     text = item.get("text", "")
            #     if text:
            #         yield {"type": "thinking", "thinking": text}
            return

        if event_type == "item.completed":
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
            return

        # Generic tool events (if present)
        if event_type == "tool.call.started":
            tool = event.get("tool", "")
            yield emit_step(f"Using tool: {tool}" if tool else "Using tool...")
            return

        if event_type == "tool.call.completed":
            yield emit_step("Tool finished")
            return

    buffer = b""
    max_buffer = 4 * 1024 * 1024
    while True:
        chunk = await proc.stdout.read(65536)
        if not chunk:
            break
        buffer += chunk
        if len(buffer) > max_buffer:
            buffer = buffer[-max_buffer:]
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if not line:
                continue
            try:
                event = json.loads(line.decode(errors="ignore").strip())
            except json.JSONDecodeError:
                continue

            async for output in handle_event(event):
                yield output

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

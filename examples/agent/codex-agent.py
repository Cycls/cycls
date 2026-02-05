# uv run examples/agent/codex-agent.py
import os
import shlex
import shutil
from urllib.parse import unquote
import cycls


def extract_prompt(messages, user_workspace):
    """Extract prompt text and copy attachments to user workspace."""
    content = messages.raw[-1].get("content", "")
    if isinstance(content, list):
        prompt = next((p["text"] for p in content if p.get("type") == "text"), "")
        for p in content:
            if p.get("type") in ("image", "file"):
                url = p.get("image") or p.get("file")
                if url:
                    url = unquote(url)
                    filename = os.path.basename(url)
                    shutil.copy(f"/workspace{url}", f"{user_workspace}/{filename}")
                    prompt += f" [USER UPLOADED {filename}]"
        return prompt
    return content


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
            state["seen_step"] = True
            cmd = item.get("command", "")
            try:
                args = shlex.split(cmd)
                cmd = args[-1] if len(args) >= 3 else cmd
            except ValueError:
                pass
            yield {"type": "step", "step": f"Bash({cmd[:60]}{'...' if len(cmd) > 60 else ''})"}
        elif item_type == "file_change":
            state["seen_step"] = True
            fname = item.get("filename", item.get("file", ""))
            yield {"type": "step", "step": f"Editing {fname}" if fname else "Editing file..."}
        elif item_type == "web_search":
            state["seen_step"] = True
            yield {"type": "step", "step": "Searching web..."}
        elif item_type == "tool_call":
            state["seen_step"] = True
            yield {"type": "step", "step": f"Using tool: {item.get('tool', '')}..." if item.get("tool") else "Using tool..."}
        return

    if event_type == "item.completed":
        item = event.get("item", {})
        item_type = item.get("type", "")
        if item_type == "agent_message" and item.get("text"):
            yield item["text"]
        elif item_type == "reasoning" and item.get("text") and not state["seen_step"]:
            yield {"type": "thinking", "thinking": item["text"]}
        return

    if event_type == "tool.call.started":
        state["seen_step"] = True
        yield {"type": "step", "step": f"Using tool: {event.get('tool', '')}..." if event.get("tool") else "Using tool..."}
    elif event_type == "tool.call.completed":
        state["seen_step"] = True
        yield {"type": "step", "step": "Tool finished"}
    else:
        print(f"[unhandled] {event}")


@cycls.app(
    apt=["curl", "proot", "xz-utils"],
    copy=[".env"],
    memory="512Mi",
    run_commands=[
        "curl -fsSL https://nodejs.org/dist/v24.13.0/node-v24.13.0-linux-x64.tar.xz | tar -xJ -C /usr/local --strip-components=1",
        "npm i -g @openai/codex@0.94.0",
    ],
    auth=True,
    # force_rebuild=True
)
async def codex_agent(context):
    import json
    import asyncio

    # print(context.messages.raw)
    yield {"type": "thinking", "thinking": "Analyzing your request..."}

    # 1. Open canvas
    # yield {"type": "canvas", "canvas": "document", "open": True, "title": "Travel Guide"}
    # yield {"type": "canvas", "canvas": "document", "content": "# Travel Guide\n"}
    # yield {"type": "canvas", "canvas": "document", "content": "## Introduction\n"}
    # yield {"type": "canvas", "canvas": "document", "content": "Welcome to..."}
    # yield {"type": "canvas", "canvas": "document", "done": True}


    # Per-user workspace and config
    user_id = context.user.id if context.user else "default"
    session_id = extract_session_id(context.messages)
    user_workspace = f"/workspace/{user_id}"
    os.makedirs(f"{user_workspace}/.codex", exist_ok=True)

    prompt = extract_prompt(context.messages, user_workspace)

    # Build command - use proot to isolate user to their workspace
    codex_cmd = ["codex", "--yolo", "exec"]
    if session_id:
        codex_cmd += ["resume", "--json", "--skip-git-repo-check", session_id, prompt]
    else:
        codex_cmd += ["--json", "--skip-git-repo-check", prompt]

    cmd = ["proot", "-b", f"{user_workspace}:/workspace", "-w", "/workspace"] + codex_cmd
    # cmd = codex_cmd  # proot disabled for testing

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=user_workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "NO_COLOR": "1",
            "CODEX_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "CODEX_HOME": "/workspace/.codex",
        },
    )

    state = {"session_id": None, "seen_step": False}

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

    # Yield canvas if it exists
    # canvas_path = f"{user_workspace}/canvas.md"
    # if os.path.exists(canvas_path):
    #     with open(canvas_path) as f:
    #         yield {"type": "canvas", "canvas": f.read()}

    # Embed session_id for resume (why at then end not the begining)
    if state["session_id"]:
        yield {"type": "session_id", "session_id": state["session_id"]}


codex_agent.local()
# codex_agent.deploy()


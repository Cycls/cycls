# uv run examples/agent/codex-app-server-agent.py

# Codex app-server agent — JSON-RPC over stdio
# Streams text deltas token-by-token (unlike exec which dumps all at once)

import os
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
        raw = getattr(messages, "raw", None) or messages
        for msg in reversed(raw):
            for part in msg.get("parts", []) or []:
                if part.get("type") == "session_id":
                    return part["session_id"]
    except:
        pass
    return None


async def send_jsonrpc(proc, method, params=None, msg_id=None):
    """Send a JSON-RPC message to the app-server process."""
    import json
    msg = {"method": method}
    if msg_id is not None:
        msg["id"] = msg_id
    if params is not None:
        msg["params"] = params
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    await proc.stdin.drain()


async def read_until_response(proc, expected_id, result_holder):
    """Read lines until we get a response matching expected_id. Yield notifications along the way."""
    import json
    while line := await proc.stdout.readline():
        try:
            msg = json.loads(line)
        except:
            continue
        if "id" in msg and msg["id"] == expected_id:
            result_holder["response"] = msg
            return
        if "method" in msg:
            yield msg


async def handle_notification(notif, state):
    """Map app-server notifications to Cycls UI components."""
    method = notif.get("method", "")
    params = notif.get("params", {})
    msg = params.get("msg", {})

    # Streaming text delta — the key win over exec
    if method == "codex/event/agent_message_delta":
        delta = msg.get("delta", "")
        if delta:
            yield delta
        return

    # Reasoning summary delta (both namespaces)
    if method in ("item/reasoning/summaryTextDelta", "codex/event/reasoning_summary_text_delta"):
        if not state["seen_step"]:
            delta = params.get("delta", "") or msg.get("delta", "")
            if delta:
                state["thinking_buf"] += delta
        return

    # Item started — show steps (both namespaces)
    if method in ("item/started", "codex/event/item_started"):
        item = params.get("item", {}) or msg.get("item", {})
        item_type = item.get("type", "").lower()
        if item_type == "commandexecution":
            state["seen_step"] = True
            cmd = item.get("command", "")
            import shlex
            try:
                args = shlex.split(cmd)
                cmd = args[-1] if len(args) >= 3 else cmd
            except ValueError:
                pass
            yield {"type": "step", "step": f"Bash({cmd[:60]}{'...' if len(cmd) > 60 else ''})"}
        elif item_type == "filechange":
            state["seen_step"] = True
            changes = item.get("changes", [])
            fname = changes[0].get("path", "") if changes else ""
            yield {"type": "step", "step": f"Editing {fname}" if fname else "Editing file..."}
        elif item_type == "websearch":
            state["seen_step"] = True
            yield {"type": "step", "step": "Searching web..."}
        elif item_type in ("mcptoolcall", "toolcall"):
            state["seen_step"] = True
            tool = item.get("tool", "")
            yield {"type": "step", "step": f"Using tool: {tool}..." if tool else "Using tool..."}
        elif item_type == "reasoning":
            state["thinking_buf"] = ""
        return

    # Item completed (both namespaces)
    if method in ("item/completed", "codex/event/item_completed"):
        item = params.get("item", {}) or msg.get("item", {})
        item_type = item.get("type", "").lower()
        if item_type == "reasoning" and state["thinking_buf"] and not state["seen_step"]:
            yield {"type": "thinking", "thinking": state["thinking_buf"]}
            state["thinking_buf"] = ""
        return

    # Task/turn completed
    if method in ("codex/event/task_complete", "turn/completed"):
        state["turn_done"] = True
        return

    # Thread started
    if method == "thread/started":
        thread = params.get("thread", {})
        state["session_id"] = thread.get("id")
        return

    # Ignore known noise
    if method in ("codex/event/agent_message_content_delta", "codex/event/agent_message",
                   "codex/event/agent_reasoning_delta", "codex/event/agent_reasoning",
                   "codex/event/agent_reasoning_section_break",
                   "codex/event/reasoning_content_delta",
                   "codex/event/user_message", "codex/event/token_count",
                   "codex/event/task_started", "codex/event/mcp_startup_complete",
                   "codex/event/exec_command_begin", "codex/event/exec_command_end",
                   "codex/event/exec_command_output_delta",
                   "item/reasoning/summaryPartAdded",
                   "item/commandExecution/outputDelta",
                   "turn/started", "turn/diff/updated",
                   "thread/tokenUsage/updated", "thread/name/updated",
                   "account/rateLimits/updated"):
        return

    # Log unhandled
    print(f"[unhandled] {notif}")


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

    # yield {"type": "thinking", "thinking": "Analyzing your request..."}

    # Per-user workspace and config
    user_id = context.user.id if context.user else "default"
    session_id = extract_session_id(context.messages)
    print(f"[debug] session_id from messages: {session_id}")
    print(f"[debug] raw messages: {context.messages.raw}")
    user_workspace = f"/workspace/{user_id}"
    os.makedirs(f"{user_workspace}/.codex", exist_ok=True)

    prompt = extract_prompt(context.messages, user_workspace)
    print(f"[debug] prompt: {prompt}")

    # Spawn app-server
    codex_home = f"{user_workspace}/.codex"
    os.makedirs(codex_home, exist_ok=True)
    auth_path = f"{codex_home}/auth.json"
    if not os.path.exists(auth_path):
        import json as _json
        api_key = os.environ.get("OPENAI_API_KEY", "")
        with open(auth_path, "w") as f:
            _json.dump({"auth_mode": "apikey", "OPENAI_API_KEY": api_key}, f)
    proc = await asyncio.create_subprocess_exec(
        "codex", "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=user_workspace,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "NO_COLOR": "1",
            "CODEX_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "CODEX_HOME": codex_home,
        },
    )

    state = {
        "session_id": None,
        "seen_step": False,
        "thinking_buf": "",
        "turn_done": False,
        "pending_approvals": [],
    }

    msg_id = 0

    try:
        # 1. Initialize
        print("[debug] sending initialize")
        await send_jsonrpc(proc, "initialize", {
            "clientInfo": {"name": "cycls_agent", "title": "Cycls Codex Agent", "version": "0.1.0"},
            "capabilities": None,
        }, msg_id=msg_id)

        # Read until we get the initialize response
        res = {}
        async for notif in read_until_response(proc, msg_id, res):
            pass  # ignore notifications during init
        print(f"[debug] initialize response: {res}")
        if not res:
            stderr = await proc.stderr.read()
            print(f"[debug] stderr: {stderr.decode()}")
            yield {"type": "callout", "callout": f"app-server died during init: {stderr.decode()}", "style": "error"}
            return
        msg_id += 1

        # Send initialized notification
        print("[debug] sending initialized")
        await send_jsonrpc(proc, "initialized")

        # 2. Start or resume thread
        if session_id:
            print(f"[debug] resuming thread {session_id}")
            await send_jsonrpc(proc, "thread/resume", {
                "threadId": session_id,
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
            }, msg_id=msg_id)
        else:
            print("[debug] starting new thread")
            await send_jsonrpc(proc, "thread/start", {
                "cwd": "/workspace",
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
            }, msg_id=msg_id)

        thread_id = None
        res = {}
        async for notif in read_until_response(proc, msg_id, res):
            async for output in handle_notification(notif, state):
                yield output
        print(f"[debug] thread response: {res}")

        # Get thread_id from response, state, or prior session
        try:
            thread_id = res["response"]["result"]["thread"]["id"]
        except (KeyError, TypeError):
            thread_id = state["session_id"] or session_id
        print(f"[debug] thread_id: {thread_id}")
        msg_id += 1

        # Emit session_id early
        if thread_id:
            yield {"type": "session_id", "session_id": thread_id}

        # 3. Send user message
        print(f"[debug] sending turn/start with prompt: {prompt[:50]}")
        await send_jsonrpc(proc, "turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
        }, msg_id=msg_id)

        # Read the turn/start response
        res = {}
        async for notif in read_until_response(proc, msg_id, res):
            async for output in handle_notification(notif, state):
                yield output
        print(f"[debug] turn/start response: {res}")
        msg_id += 1

        # 4. Stream events until turn completes
        while not state["turn_done"]:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except:
                continue

            # Handle approval requests — auto-approve
            if "id" in msg and "method" in msg:
                await send_jsonrpc(proc, None, None, msg_id=None)
                # Respond to the server's request
                response = json.dumps({"id": msg["id"], "result": {"decision": "accept"}}) + "\n"
                proc.stdin.write(response.encode())
                await proc.stdin.drain()
                continue

            if "method" in msg:
                async for output in handle_notification(msg, state):
                    yield output

    except Exception as e:
        yield {"type": "callout", "callout": str(e), "style": "error"}
    finally:
        # Clean up
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()

        stderr = await proc.stderr.read()
        if stderr:
            yield {"type": "callout", "callout": stderr.decode(), "style": "error"}


codex_agent.local()
# codex_agent.deploy()

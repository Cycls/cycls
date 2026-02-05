# uv run examples/agent/codex-app-server-agent.py
# Codex app-server agent — JSON-RPC over stdio, streams text deltas

import json
import os
import shlex
import shutil
from urllib.parse import unquote
import cycls


def extract_prompt(messages, user_workspace):
    content = messages.raw[-1].get("content", "")
    if isinstance(content, list):
        prompt = next((p["text"] for p in content if p.get("type") == "text"), "")
        for p in content:
            if p.get("type") in ("image", "file"):
                url = unquote(p.get("image") or p.get("file") or "")
                if url:
                    fname = os.path.basename(url)
                    src = os.path.realpath(f"/workspace{url}")
                    if not src.startswith("/workspace/"):
                        continue
                    shutil.copy(src, f"{user_workspace}/{fname}")
                    prompt += f" [USER UPLOADED {fname}]"
        return prompt
    return content


def extract_session_id(messages):
    try:
        for msg in reversed(getattr(messages, "raw", None) or messages):
            for part in msg.get("parts", []) or []:
                if part.get("type") == "session_id":
                    return part["session_id"]
    except Exception:
        pass
    return None


async def rpc_send(proc, method, params=None, msg_id=None):
    msg = {"method": method}
    if msg_id is not None:
        msg["id"] = msg_id
    if params is not None:
        msg["params"] = params
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    await proc.stdin.drain()


async def rpc_read(proc, expected_id, result):
    while line := await proc.stdout.readline():
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if "id" in msg and msg["id"] == expected_id:
            result["response"] = msg
            return
        if "method" in msg:
            yield msg



async def handle(notif, state):
    method = notif.get("method", "")
    params = notif.get("params", {})
    msg = params.get("msg", {})

    if method == "item/agentMessage/delta":
        delta = params.get("delta", "")
        if delta:
            yield delta
        return

    if method in ("item/reasoning/summaryTextDelta", "codex/event/reasoning_summary_text_delta"):
        if not state["seen_step"]:
            delta = params.get("delta", "") or msg.get("delta", "")
            if delta:
                state["thinking_buf"] += delta
        return

    if method in ("item/started", "codex/event/item_started"):
        item = params.get("item", {}) or msg.get("item", {})
        t = item.get("type", "").lower()
        if t == "commandexecution":
            state["seen_step"] = True
            cmd = item.get("command", "")
            try:
                args = shlex.split(cmd)
                cmd = args[-1] if len(args) >= 3 else cmd
            except ValueError:
                pass
            yield {"type": "step", "step": f"Bash({cmd[:60]}{'...' if len(cmd) > 60 else ''})"}
        elif t == "filechange":
            state["seen_step"] = True
            changes = item.get("changes", [])
            fname = changes[0].get("path", "") if changes else ""
            yield {"type": "step", "step": f"Editing {fname}" if fname else "Editing file..."}
        elif t == "websearch":
            state["seen_step"] = True
            yield {"type": "step", "step": "Searching web..."}
        elif t in ("mcptoolcall", "toolcall"):
            state["seen_step"] = True
            tool = item.get("tool", "")
            yield {"type": "step", "step": f"Using tool: {tool}..." if tool else "Using tool..."}
        elif t == "reasoning":
            state["thinking_buf"] = ""
        return

    if method in ("item/completed", "codex/event/item_completed"):
        item = params.get("item", {}) or msg.get("item", {})
        if item.get("type", "").lower() == "reasoning" and state["thinking_buf"] and not state["seen_step"]:
            yield {"type": "thinking", "thinking": state["thinking_buf"]}
            state["thinking_buf"] = ""
        return

    if method in ("codex/event/task_complete", "turn/completed"):
        state["turn_done"] = True
        return

    if method == "thread/started":
        state["session_id"] = params.get("thread", {}).get("id")
        return

    return


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
    import asyncio

    user_id = context.user.id if context.user else "default"
    session_id = extract_session_id(context.messages)
    user_workspace = f"/workspace/{user_id}"
    codex_home = f"{user_workspace}/.codex"
    os.makedirs(codex_home, exist_ok=True)

    # Write auth.json if missing
    auth_path = f"{codex_home}/auth.json"
    if not os.path.exists(auth_path):
        with open(auth_path, "w") as f:
            json.dump({"auth_mode": "apikey", "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "")}, f)

    prompt = extract_prompt(context.messages, user_workspace)

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

    state = {"session_id": None, "seen_step": False, "thinking_buf": "", "turn_done": False}
    msg_id = 0

    try:
        # Initialize
        await rpc_send(proc, "initialize", {
            "clientInfo": {"name": "cycls_agent", "title": "Cycls Codex Agent", "version": "0.1.0"},
            "capabilities": None,
        }, msg_id=msg_id)
        res = {}
        async for notif in rpc_read(proc, msg_id, res):
            pass
        if not res:
            stderr = await proc.stderr.read()
            yield {"type": "callout", "callout": f"app-server init failed: {stderr.decode()}", "style": "error"}
            return
        msg_id += 1
        await rpc_send(proc, "initialized")

        # Start or resume thread
        if session_id:
            await rpc_send(proc, "thread/resume", {"threadId": session_id, "approvalPolicy": "never", "sandbox": "danger-full-access"}, msg_id=msg_id)
        else:
            await rpc_send(proc, "thread/start", {"cwd": user_workspace, "approvalPolicy": "never", "sandbox": "danger-full-access"}, msg_id=msg_id)
        res = {}
        async for notif in rpc_read(proc, msg_id, res):
            async for out in handle(notif, state):
                yield out
        try:
            thread_id = res["response"]["result"]["thread"]["id"]
        except (KeyError, TypeError):
            thread_id = state["session_id"] or session_id
        msg_id += 1

        if thread_id:
            yield {"type": "session_id", "session_id": thread_id}

        # Send user message
        await rpc_send(proc, "turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]}, msg_id=msg_id)
        res = {}
        async for notif in rpc_read(proc, msg_id, res):
            async for out in handle(notif, state):
                yield out
        msg_id += 1

        # Stream until turn completes
        while not state["turn_done"]:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if "id" in msg and "method" in msg:
                response = json.dumps({"id": msg["id"], "result": {"decision": "accept"}}) + "\n"
                proc.stdin.write(response.encode())
                await proc.stdin.drain()
                continue
            if "method" in msg:
                async for out in handle(msg, state):
                    yield out

    except Exception as e:
        yield {"type": "callout", "callout": str(e), "style": "error"}
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
        stderr = await proc.stderr.read()
        if stderr:
            yield {"type": "callout", "callout": stderr.decode(), "style": "error"}


# codex_agent.local()
codex_agent.deploy()

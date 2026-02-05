# uv run examples/agent/codex-golf.py
# Minimal Codex app-server agent

import json, os, shlex, shutil
from urllib.parse import unquote
import cycls

APPROVAL_POLICY = os.environ.get("CODEX_APPROVAL_POLICY", "untrusted")

BASE_INSTRUCTIONS = """
You are Cycls, a general-purpose AI agent built by cycls.com that runs in the user's workspace in Cycls cloud.
You help with coding, research, writing, analysis, system administration, and any task the user brings.

## General
- Use `rg` or `rg --files` for searching text and files — it's faster than grep.
- Prefer `apply_patch` for single-file edits; use scripting when more efficient.
- Default to ASCII in file edits; only use Unicode when clearly justified.

## Working style
- Be concise and direct. Use a friendly, collaborative tone.
- Ask clarifying questions only when truly needed — otherwise, make reasonable choices and proceed.
- For substantial work, summarize what you did and suggest logical next steps.
- Reference file paths with inline code and include line numbers when relevant.
- Don't dump large file contents; reference paths instead.

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

APPROVAL_HTML = '\n\n<div style="border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:8px 0;background:#f8fafc"><div style="font-weight:600;margin-bottom:8px">Approval Required</div>\n\n<code style="background:#e2e8f0;padding:2px 6px;border-radius:4px;font-size:13px">{cmd}</code>\n\n<div style="margin-top:10px;color:#64748b;font-size:13px">Reply <b>yes</b> to approve</div></div>\n\n'
STEP_TYPES = {
    "commandexecution": lambda i: f"Bash({parse_cmd(i.get('command', ''))[:60]})",
    "filechange": lambda i: f"Editing {(i.get('changes') or [{}])[0].get('path', 'file')}",
    "mcptoolcall": lambda i: f"{i.get('tool', 'mcp')}({i.get('query', i.get('input', ''))[:40]})",
    "toolcall": lambda i: f"{i.get('tool', 'tool')}({i.get('query', i.get('input', ''))[:40]})",
}


def parse_cmd(cmd):
    try:
        a = shlex.split(cmd)
        return a[-1] if len(a) >= 3 else cmd
    except ValueError:
        return cmd


def extract_prompt(messages, ws):
    content = messages.raw[-1].get("content", "")
    if not isinstance(content, list):
        return content
    prompt = next((p["text"] for p in content if p.get("type") == "text"), "")
    for p in content:
        if p.get("type") not in ("image", "file"):
            continue
        url = unquote(p.get("image") or p.get("file") or "")
        if not url:
            continue
        fname = os.path.basename(url)
        src = os.path.realpath(f"/workspace{url}")
        if src.startswith("/workspace/"):
            shutil.copy(src, f"{ws}/{fname}")
            prompt += f" [USER UPLOADED {fname}]"
    return prompt


def find_part(messages, role, ptype):
    for msg in reversed(getattr(messages, "raw", None) or messages):
        if role and msg.get("role") != role:
            continue
        for part in msg.get("parts", []) or []:
            if part.get("type") == ptype:
                return part
        if role:
            return None
    return None


async def rpc_send(proc, method, params=None, msg_id=None):
    proc.stdin.write((json.dumps({k: v for k, v in {"id": msg_id, "method": method, "params": params}.items() if v is not None}) + "\n").encode())
    await proc.stdin.drain()


async def rpc_read(proc, expected_id, res):
    while line := await proc.stdout.readline():
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("id") == expected_id and "method" not in msg:
            res["response"] = msg
            return
        if "method" in msg:
            yield msg


async def handle(proc, notif, s):
    if "id" in notif:  # server request (approval)
        p = notif.get("params", {})
        cmd = parse_cmd(p.get("command", "")) or json.dumps(p)
        proc.stdin.write((json.dumps({"id": notif["id"], "result": {"decision": "decline"}}) + "\n").encode())
        await proc.stdin.drain()
        yield APPROVAL_HTML.format(cmd=cmd)
        yield {"type": "pending_approval", "action_type": notif.get("method", ""), "action_detail": cmd}
        s["approval"] = True
        return
    m, p = notif.get("method", ""), notif.get("params", {})
    if m == "item/agentMessage/delta":
        if d := p.get("delta"):
            yield d
    elif m == "item/reasoning/summaryTextDelta":
        if not s["stepped"] and (d := p.get("delta")):
            s["think"] += d
    elif m == "item/started":
        item = p.get("item") or {}
        t = item.get("type", "").lower()
        if t in STEP_TYPES:
            s["stepped"] = True
            yield {"type": "step", "step": STEP_TYPES[t](item)}
        elif t == "reasoning":
            s["think"] = ""
    elif m == "item/completed":
        item = p.get("item") or {}
        t = item.get("type", "").lower()
        if t == "websearch" and (q := item.get("query")):
            s["stepped"] = True
            yield {"type": "step", "step": f'Web Search("{q}")'}
        if t == "reasoning" and s["think"] and not s["stepped"]:
            yield {"type": "thinking", "thinking": s["think"]}
            s["think"] = ""
    elif m == "turn/completed":
        s["done"] = True
    elif m == "thread/started":
        s["thread"] = p.get("thread", {}).get("id")


@cycls.app(
    apt=["curl", "proot", "xz-utils"], copy=[".env"], memory="512Mi",
    run_commands=[
        "curl -fsSL https://nodejs.org/dist/v24.13.0/node-v24.13.0-linux-x64.tar.xz | tar -xJ -C /usr/local --strip-components=1",
        "npm i -g @openai/codex@0.94.0",
    ],
    auth=True,
    # force_rebuild=True,
)
async def codex_agent(context):
    import asyncio

    user_id = context.user.id if context.user else "default"
    sid_part = find_part(context.messages, None, "session_id")
    session_id = sid_part["session_id"] if sid_part else None
    ws = f"/workspace/{user_id}"
    home = f"{ws}/.cycls"
    os.makedirs(home, exist_ok=True)
    instructions_path = f"{home}/instructions.md"
    with open(instructions_path, "w") as f:
        f.write(BASE_INSTRUCTIONS)
    with open(f"{home}/config.toml", "w") as f:
        f.write(f'model_instructions_file = {json.dumps(instructions_path)}\n')
    auth_path = f"{home}/auth.json"
    if not os.path.exists(auth_path):
        with open(auth_path, "w") as f:
            json.dump({"auth_mode": "apikey", "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "")}, f)

    prompt = extract_prompt(context.messages, ws)
    policy = APPROVAL_POLICY
    pending = find_part(context.messages, "assistant", "pending_approval")
    if pending and prompt.strip().lower() in ("yes", "y", "approve"):
        policy = "never"
        action = pending.get("action_detail", pending.get("action_type", "the action"))
        prompt = f"The user approved the previous action. Please retry: {action}"

    proc = await asyncio.create_subprocess_exec(
        "codex", "app-server",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=ws, env={
            "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
            "NO_COLOR": "1", "CODEX_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""), "CODEX_HOME": home,
        },
    )
    s = {"thread": None, "stepped": False, "think": "", "done": False, "approval": False, "stderr": []}
    mid = 0

    async def drain_stderr():
        async for line in proc.stderr:
            s["stderr"].append(line)

    stderr_task = asyncio.create_task(drain_stderr())
    try:
        await rpc_send(proc, "initialize", {"clientInfo": {"name": "cycls", "version": "0.1.0"}}, msg_id=mid)
        res = {}
        async for _ in rpc_read(proc, mid, res):
            pass
        if not res:
            yield {"type": "callout", "callout": f"init failed: {(await proc.stderr.read()).decode()}", "style": "error"}
            return
        mid += 1
        await rpc_send(proc, "initialized")

        thread_params = {"approvalPolicy": policy, "sandbox": "danger-full-access"}
        thread_params["threadId" if session_id else "cwd"] = session_id or ws
        await rpc_send(proc, "thread/resume" if session_id else "thread/start", thread_params, msg_id=mid)
        res = {}
        async for notif in rpc_read(proc, mid, res):
            async for out in handle(proc, notif, s):
                yield out
        if res.get("response", {}).get("error"):
            yield {"type": "callout", "callout": "Session expired. Please start a new conversation.", "style": "warning"}
            return
        try:
            tid = res["response"]["result"]["thread"]["id"]
        except (KeyError, TypeError):
            tid = s["thread"] or session_id
        mid += 1
        if tid:
            yield {"type": "session_id", "session_id": tid}

        await rpc_send(proc, "turn/start", {"threadId": tid, "input": [{"type": "text", "text": prompt}]}, msg_id=mid)
        res = {}
        async for notif in rpc_read(proc, mid, res):
            async for out in handle(proc, notif, s):
                yield out
        mid += 1

        while not s["done"] and not s["approval"]:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except Exception:
                continue
            async for out in handle(proc, msg, s):
                yield out
            if s["approval"]:
                break

    except Exception as e:
        yield {"type": "callout", "callout": str(e), "style": "error"}
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        stderr_task.cancel()
        err = b"".join(s["stderr"])
        if err:
            yield {"type": "callout", "callout": err.decode(), "style": "error"}


codex_agent.local()
# codex_agent.deploy()

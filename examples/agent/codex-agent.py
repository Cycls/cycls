# uv run examples/agent/codex-agent.py
# Minimal Codex app-server agent
# https://developers.openai.com/codex/config-reference/
# https://github.com/openai/codex/blob/main/codex-rs/core/gpt_5_codex_prompt.md
# https://github.com/Piebald-AI/claude-code-system-prompts/tree/main

import asyncio, json, os, shlex, shutil
from urllib.parse import unquote
import cycls

# APPROVAL_POLICY = os.environ.get("CODEX_APPROVAL_POLICY", "untrusted")
APPROVAL_POLICY = "never"

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


async def rpc_respond(proc, msg_id, result):
    proc.stdin.write((json.dumps({"id": msg_id, "result": result}) + "\n").encode())
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
    if "id" in notif and "method" in notif:
        method = notif["method"]
        if method == "item/tool/call":
            p = notif.get("params", {})
            tool = p.get("tool", "")
            args = p.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
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
            await rpc_respond(proc, notif["id"], {"contentItems": [{"type": "inputText", "text": f"{tool} rendered successfully"}], "success": True})
        elif method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            p = notif.get("params", {})
            actions = p.get("commandActions") or [{}]
            cmd = actions[0].get("command") or parse_cmd(p.get("command", "")) or json.dumps(p)
            cwd = p.get("cwd", "")
            reason = p.get("reason", "")
            lines = [f"\n**Bash(** {cmd} **)**\n"]
            if cwd:
                lines.append(f"dir: `{cwd}`\n")
            if reason:
                lines.append(f"reason: {reason}\n")
            lines.append("Reply **yes** to approve.")
            await rpc_respond(proc, notif["id"], {"decision": "decline"})
            yield {"type": "thinking", "thinking": "\n".join(lines)}
            yield {"type": "pending_approval", "action_type": method, "action_detail": cmd}
            s["approval"] = True
        else:
            await rpc_respond(proc, notif["id"], {"decision": "decline"})
        return
    m, p = notif.get("method", ""), notif.get("params", {})
    if m == "item/agentMessage/delta":
        if d := p.get("delta"):
            yield d
    elif m == "item/commandExecution/outputDelta":
        if d := p.get("delta"):
            yield {"type": "step_data", "data": d}
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
    elif m == "turn/diff/updated":
        s["turn_diff"] = p.get("diff", "")
    elif m == "turn/plan/updated":
        steps = p.get("steps") or []
        for step in steps:
            label = step.get("label", step.get("title", ""))
            done = step.get("status") == "completed"
            if label:
                yield {"type": "status", "status": f"{'[x]' if done else '[ ]'} {label}"}
    elif m == "turn/completed":
        s["done"] = True
    elif m == "thread/tokenUsage/updated":
        s["usage"] = p
    elif m == "thread/started":
        s["thread"] = p.get("thread", {}).get("id")


def setup_workspace(context):
    user_id = context.user.id if context.user else "default"
    org_id = context.user.org_id if context.user else None
    ws = f"/workspace/{org_id}" if org_id else f"/workspace/{user_id}"
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
    return ws, home


async def Agent(ws, home, prompt, policy="never", session_id=None, tools=None, model=None, effort=None, instructions=None, pending=None):
    if pending and prompt.strip().lower() in ("yes", "y", "approve"):
        policy = "never"
        action = pending.get("action_detail", pending.get("action_type", "the action"))
        prompt = f"The user approved the previous action. Please retry: {action}"
    if instructions:
        with open(f"{ws}/AGENTS.md", "w") as f:
            f.write(instructions)
    proc = await asyncio.create_subprocess_exec(
        "codex", "app-server", limit=10 * 1024 * 1024,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=ws, env={
            "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
            "NO_COLOR": "1", "CODEX_HOME": home,
            "CODEX_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        },
    )
    s = {"thread": None, "stepped": False, "think": "", "done": False, "approval": False, "stderr": [], "usage": None, "turn_diff": ""}
    mid = 0

    async def drain_stderr():
        async for line in proc.stderr:
            s["stderr"].append(line)

    stderr_task = asyncio.create_task(drain_stderr())
    try:
        await rpc_send(proc, "initialize", {"clientInfo": {"name": "cycls", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}, msg_id=mid)
        res = {}
        async for _ in rpc_read(proc, mid, res):
            pass
        if not res:
            yield {"type": "callout", "callout": f"init failed: {(await proc.stderr.read()).decode()}", "style": "error"}
            return
        mid += 1
        await rpc_send(proc, "initialized")

        thread_params = {"approvalPolicy": policy, "sandbox": "danger-full-access", "dynamicTools": tools or []}
        if model:
            thread_params["model"] = model
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

        turn_params = {"threadId": tid, "input": [{"type": "text", "text": prompt}]}
        if effort:
            turn_params["effort"] = effort
        await rpc_send(proc, "turn/start", turn_params, msg_id=mid)
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

        # Canvas: show aggregated diff from turn
        if s.get("turn_diff"):
            yield {"type": "canvas", "canvas": "document", "open": True, "title": "Changes"}
            yield {"type": "canvas", "canvas": "document", "content": s["turn_diff"]}
            yield {"type": "canvas", "canvas": "document", "done": True}

        if s["usage"]:
            u = s["usage"].get("tokenUsage", {}).get("total", {})
            inp, cached, out = u.get("inputTokens", 0), u.get("cachedInputTokens", 0), u.get("outputTokens", 0)
            yield f'\n\n*in: {inp:,} · out: {out:,} · cached: {cached:,}*'

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
        err = b"".join(s["stderr"]).decode()
        err = "\n".join(l for l in err.splitlines() if "state db missing rollout" not in l).strip()
        if err:
            yield {"type": "callout", "callout": err, "style": "error"}

####

AGENTS_MD = """
you're a lawyer
""".strip()

DYNAMIC_TOOLS = [
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

@cycls.app(
    apt=["curl", "xz-utils"], copy=[".env"], # TODO: proot?
    run_commands=[
        "curl -fsSL https://nodejs.org/dist/v24.13.0/node-v24.13.0-linux-x64.tar.xz | tar -xJ -C /usr/local --strip-components=1",
        "npm i -g @openai/codex@0.98.0",
    ],
    auth=True,
    # force_rebuild=True,
)
async def codex_agent(context):
    ws, home = setup_workspace(context)
    prompt = extract_prompt(context.messages, ws)
    async for out in Agent(ws,
                           home,
                           prompt,
                           policy=APPROVAL_POLICY,
                           session_id=(find_part(context.messages, None, "session_id") or {}).get("session_id"),
                           tools=DYNAMIC_TOOLS,
                           instructions=AGENTS_MD,
                           model="gpt-5.2-codex",
                           effort="high",
                           pending=find_part(context.messages, "assistant", "pending_approval")):
        yield out


codex_agent.local()
# codex_agent.deploy()
import asyncio
import json
import os
import shlex
import shutil
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import unquote

from .app import App

# --- Constants ---

_STEP_TYPES = {
    "commandexecution": lambda i: f"Bash({_parse_cmd(i.get('command', ''))[:60]})",
    "filechange": lambda i: f"Editing {(i.get('changes') or [{}])[0].get('path', 'file')}",
    "mcptoolcall": lambda i: f"{i.get('tool', 'mcp')}({i.get('query', i.get('input', ''))[:40]})",
    "toolcall": lambda i: f"{i.get('tool', 'tool')}({i.get('query', i.get('input', ''))[:40]})",
}


def _parse_cmd(cmd):
    try:
        a = shlex.split(cmd)
        return a[-1] if len(a) >= 3 else cmd
    except ValueError:
        return cmd


# --- JSON-RPC Protocol ---


async def _rpc_write(proc, **msg):
    proc.stdin.write((json.dumps({k: v for k, v in msg.items() if v is not None}) + "\n").encode())
    await proc.stdin.drain()


async def _rpc_read(proc, expected_id, res, stop=None):
    while line := await proc.stdout.readline():
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("id") == expected_id and "method" not in msg:
            res["response"] = msg
            if not stop:
                return
        if "method" in msg:
            yield msg
        if stop and stop():
            return


async def _rpc_call(proc, s, mid, method, params=None, stop=None):
    await _rpc_write(proc, id=mid, method=method, params=params)
    s["_res"] = {}
    async for notif in _rpc_read(proc, mid, s["_res"], stop):
        async for out in _handle(proc, notif, s):
            yield out


# --- Notification Handler ---


async def _handle(proc, notif, s):
    if "id" in notif and "method" in notif:
        method = notif["method"]
        if method == "item/tool/call":
            p = notif.get("params", {})
            tool = p.get("tool", "")
            args = p.get("arguments", {})
            if isinstance(args, str):
                try: args = json.loads(args)
                except Exception: args = {}
            yield {"type": "tool_call", "tool": tool, "args": args}
            await _rpc_write(proc, id=notif["id"], result={"contentItems": [{"type": "inputText", "text": f"{tool} rendered successfully"}], "success": True})
        elif "requestApproval" in method:
            p = notif.get("params", {})
            cmd = (p.get("commandActions") or [{}])[0].get("command") or _parse_cmd(p.get("command", "")) or json.dumps(p)
            await _rpc_write(proc, id=notif["id"], result={"decision": "decline"})
            yield {"type": "approval", "method": method, "command": cmd, "cwd": p.get("cwd"), "reason": p.get("reason")}
            s["approval"] = True
        else:
            await _rpc_write(proc, id=notif["id"], result={"decision": "decline"})
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
        if t in _STEP_TYPES:
            s["stepped"] = True
            yield {"type": "step", "step": _STEP_TYPES[t](item)}
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
        for step in p.get("steps") or []:
            if label := step.get("label", step.get("title", "")):
                yield {"type": "status", "status": f"{'[x]' if step.get('status') == 'completed' else '[ ]'} {label}"}
    elif m == "turn/completed":
        s["done"] = True
    elif m == "thread/tokenUsage/updated":
        s["usage"] = p
    elif m == "thread/started":
        s["thread"] = p.get("thread", {}).get("id")


# --- Public API ---


def find_part(messages, role, ptype):
    """Search message history for a part matching the given type."""
    for msg in reversed(getattr(messages, "raw", None) or messages):
        if role and msg.get("role") != role:
            continue
        for part in msg.get("parts", []) or []:
            if part.get("type") == ptype:
                return part
        if role:
            return None
    return None


def setup_workspace(context, instructions=None, agent_instructions=None):
    """Initialize per-user workspace, write Codex config, extract prompt.

    Returns (workspace_path, prompt_string).
    """
    user_id = context.user.id if context.user else "default"
    org_id = context.user.org_id if context.user else None
    ws = f"/workspace/{org_id}" if org_id else f"/workspace/{user_id}"
    home = f"{ws}/.cycls"
    os.makedirs(home, exist_ok=True)
    if instructions:
        instructions_path = f"{home}/instructions.md"
        with open(instructions_path, "w") as f:
            f.write(instructions)
        with open(f"{home}/config.toml", "w") as f:
            f.write(f'model_instructions_file = {json.dumps(instructions_path)}\n')
    auth_path = f"{home}/auth.json"
    if not os.path.exists(auth_path):
        with open(auth_path, "w") as f:
            json.dump({"auth_mode": "apikey", "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "")}, f)
    if agent_instructions:
        with open(f"{ws}/AGENTS.md", "w") as f:
            f.write(agent_instructions)
    # Extract prompt and copy uploads
    content = context.messages.raw[-1].get("content", "")
    if not isinstance(content, list):
        return ws, content
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
    return ws, prompt


@dataclass
class CodexOptions:
    """Configuration for a single Codex turn."""
    workspace: str
    prompt: str
    model: Optional[str] = None
    effort: Optional[str] = None
    tools: List[dict] = field(default_factory=list)
    policy: str = "never"
    sandbox: str = "danger-full-access"
    session_id: Optional[str] = None
    pending: Optional[dict] = None


async def Codex(*, options):
    """Run one Codex turn. Async generator yielding streaming components."""
    ws = options.workspace
    prompt = options.prompt
    policy = options.policy
    home = f"{ws}/.cycls"
    if options.pending and prompt.strip().lower() in ("yes", "y", "approve"):
        policy = "never"
        prompt = f"The user approved the previous action. Please retry: {options.pending.get('action_detail', options.pending.get('action_type', 'the action'))}"
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
    s = {"thread": None, "stepped": False, "think": "", "done": False, "approval": False, "usage": None, "turn_diff": ""}
    mid = 0
    try:
        async for _ in _rpc_call(proc, s, mid, "initialize", {"clientInfo": {"name": "cycls", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}):
            pass
        if not s["_res"]:
            yield {"type": "callout", "callout": f"init failed: {(await proc.stderr.read()).decode()}", "style": "error"}
            return
        mid += 1
        await _rpc_write(proc, method="initialized")

        thread_params = {"approvalPolicy": policy, "sandbox": options.sandbox, "dynamicTools": options.tools or []}
        if options.model:
            thread_params["model"] = options.model
        thread_params["threadId" if options.session_id else "cwd"] = options.session_id or ws
        async for out in _rpc_call(proc, s, mid, "thread/resume" if options.session_id else "thread/start", thread_params):
            yield out
        if s["_res"].get("response", {}).get("error"):
            yield {"type": "callout", "callout": "Session expired. Please start a new conversation.", "style": "warning"}
            return
        try:
            tid = s["_res"]["response"]["result"]["thread"]["id"]
        except (KeyError, TypeError):
            tid = s["thread"] or options.session_id
        mid += 1
        if tid:
            yield {"type": "session_id", "session_id": tid}

        turn_params = {"threadId": tid, "input": [{"type": "text", "text": prompt}]}
        if options.effort:
            turn_params["effort"] = options.effort
        async for out in _rpc_call(proc, s, mid, "turn/start", turn_params, stop=lambda: s["done"] or s["approval"]):
            yield out
        mid += 1

        if s.get("turn_diff"):
            yield {"type": "diff", "diff": s["turn_diff"]}
        if s["usage"]:
            yield {"type": "usage", "usage": s["usage"]}

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
        err = (await proc.stderr.read()).decode()
        err = "\n".join(l for l in err.splitlines() if "state db missing rollout" not in l).strip()
        if err:
            yield {"type": "callout", "callout": err, "style": "error"}


# --- Decorator ---


class Agent(App):
    """App subclass that bundles Node.js and Codex CLI dependencies."""

    def __init__(self, func, name, codex_version="0.101.0", node_version="v24.13.0",
                 pip=None, apt=None, run_commands=None, copy=None, **kwargs):
        node_install = (
            f"curl -fsSL https://nodejs.org/dist/{node_version}/node-{node_version}-linux-x64.tar.xz"
            f" | tar -xJ -C /usr/local --strip-components=1"
        )
        codex_install = f"npm i -g @openai/codex@{codex_version}"
        super().__init__(
            func=func,
            name=name,
            pip=pip,
            apt=["xz-utils", *(apt or [])],
            run_commands=[node_install, codex_install, *(run_commands or [])],
            copy=copy,
            **kwargs,
        )


def agent(name=None, codex_version="0.98.0", node_version="v24.13.0", **kwargs):
    """Decorator that transforms a function into a deployable Codex agent."""
    def decorator(func):
        return Agent(
            func=func,
            name=name or func.__name__,
            codex_version=codex_version,
            node_version=node_version,
            **kwargs,
        )
    return decorator

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
class CodexAgentOptions:
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


async def CodexAgent(*, options):
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
            "NO_COLOR": "1", "CODEX_HOME": home
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


# --- ClaudeAgent ---


@dataclass
class ClaudeAgentOptions:
    """Configuration for a single Claude turn."""
    workspace: str
    prompt: str
    model: str = "claude-sonnet-4-20250514"
    tools: List[dict] = field(default_factory=list)
    policy: str = "never"
    pending: Optional[dict] = None
    system: str = ""
    max_tokens: int = 16384
    thinking: bool = True
    thinking_budget: int = 10000


def _build_claude_tools(options):
    tools = [
        {"type": "bash_20250124", "name": "bash"},
        {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
        {"type": "web_search_20250305", "name": "web_search"},
    ]
    for t in options.tools or []:
        schema = t.get("inputSchema", t.get("input_schema", {}))
        tools.append({
            "type": "custom",
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": schema,
        })
    return tools


async def _exec_bash(command, cwd):
    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    output = stdout.decode(errors="replace")
    if stderr:
        output += stderr.decode(errors="replace")
    if len(output) > 20000:
        output = output[:10000] + "\n... (truncated) ...\n" + output[-10000:]
    return output.strip() or "(no output)", proc.returncode


def _exec_text_editor(inp, workspace):
    import pathlib
    command = inp["command"]
    path = pathlib.Path(inp["path"])
    if not path.is_absolute():
        path = pathlib.Path(workspace) / path
    path = path.resolve()
    if not str(path).startswith(os.path.realpath(workspace)):
        return f"Error: path {path} is outside workspace"

    if command == "view":
        if not path.exists():
            return f"Error: {path} does not exist"
        text = path.read_text()
        lines = text.splitlines()
        vr = inp.get("view_range")
        if vr:
            start, end = vr
            lines = lines[start - 1:end]
            start_num = start
        else:
            start_num = 1
        numbered = [f"{i + start_num:6}\t{l}" for i, l in enumerate(lines)]
        return "\n".join(numbered)

    elif command == "str_replace":
        if not path.exists():
            return f"Error: {path} does not exist"
        text = path.read_text()
        old = inp["old_str"]
        new = inp.get("new_str", "")
        count = text.count(old)
        if count == 0:
            return f"Error: old_str not found in {path}"
        if count > 1:
            return f"Error: old_str found {count} times, must be unique"
        path.write_text(text.replace(old, new, 1))
        return f"Replaced in {path}"

    elif command == "create":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inp["file_text"])
        return f"Created {path}"

    elif command == "insert":
        if not path.exists():
            return f"Error: {path} does not exist"
        lines = path.read_text().splitlines(keepends=True)
        pos = inp["insert_line"]
        new_lines = inp["new_str"].splitlines(keepends=True)
        if not new_lines[-1:] or not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        lines[pos:pos] = new_lines
        path.write_text("".join(lines))
        return f"Inserted at line {pos} in {path}"

    return f"Error: unknown command {command}"


def _snapshot_files(workspace):
    import pathlib
    snap = {}
    ws = pathlib.Path(workspace)
    for p in ws.rglob("*"):
        if p.is_file() and ".cycls" not in p.parts:
            try:
                snap[str(p.relative_to(ws))] = p.read_text(errors="replace")
            except Exception:
                pass
    return snap


def _generate_diff(workspace, before):
    import difflib
    import pathlib
    ws = pathlib.Path(workspace)
    after = _snapshot_files(workspace)
    all_files = sorted(set(before) | set(after))
    parts = []
    for f in all_files:
        old = before.get(f, "").splitlines(keepends=True)
        new = after.get(f, "").splitlines(keepends=True)
        if old == new:
            continue
        diff = difflib.unified_diff(old, new, fromfile=f"a/{f}", tofile=f"b/{f}")
        parts.append("".join(diff))
    return "\n".join(parts)


async def ClaudeAgent(*, options):
    """Run one Claude turn. Async generator yielding streaming components."""
    import anthropic

    ws = options.workspace
    prompt = options.prompt
    policy = options.policy

    if options.pending and prompt.strip().lower() in ("yes", "y", "approve"):
        policy = "never"
        prompt = f"The user approved the previous action. Please retry: {options.pending.get('action_detail', options.pending.get('action_type', 'the action'))}"

    before = _snapshot_files(ws)
    client = anthropic.AsyncAnthropic()
    tools = _build_claude_tools(options)
    messages = [{"role": "user", "content": prompt}]

    model_kwargs = {
        "model": options.model,
        "max_tokens": options.max_tokens,
        "tools": tools,
        "messages": messages,
    }
    if options.system:
        model_kwargs["system"] = options.system
    if options.thinking:
        model_kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": options.thinking_budget,
        }

    total_input = 0
    total_output = 0

    try:
        while True:
            thinking_text = ""
            text_parts = []
            tool_use_blocks = []

            async with client.messages.stream(**model_kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            name = block.name
                            if name == "bash":
                                pass  # step yielded after we have input
                            elif name == "str_replace_based_edit_tool":
                                pass  # step yielded after we have input
                            elif name not in ("web_search",):
                                yield {"type": "status", "status": f"Using {name}..."}
                        elif block.type == "server_tool_use":
                            if block.name == "web_search":
                                yield {"type": "step", "step": 'Web Search'}
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "thinking_delta":
                            thinking_text += delta.thinking
                        elif delta.type == "text_delta":
                            yield delta.text
                    elif event.type == "content_block_stop":
                        if thinking_text:
                            yield {"type": "thinking", "thinking": thinking_text}
                            thinking_text = ""

                response = await stream.get_final_message()

            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens
            if hasattr(response.usage, "cache_read_input_tokens"):
                cache_read = response.usage.cache_read_input_tokens or 0
            else:
                cache_read = 0

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_use_blocks.append(block)
                elif block.type == "server_tool_use" and block.name == "web_search":
                    q = (block.input or {}).get("query", "")
                    if q:
                        yield {"type": "step", "step": f'Web Search("{q}")'}

            if response.stop_reason != "tool_use":
                break

            # Execute tools
            tool_results = []
            approval_needed = False
            for block in tool_use_blocks:
                name = block.name
                inp = block.input

                if name == "bash":
                    cmd = inp.get("command", "")
                    yield {"type": "step", "step": f"Bash({cmd[:60]})"}
                    if policy != "never":
                        yield {"type": "approval", "method": "requestApproval", "command": cmd, "cwd": ws}
                        approval_needed = True
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Command approval was denied by the user.",
                        })
                        break
                    output, _ = await _exec_bash(cmd, ws)
                    yield {"type": "step_data", "data": output}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })

                elif name == "str_replace_based_edit_tool":
                    cmd_type = inp.get("command", "")
                    fpath = inp.get("path", "file")
                    if cmd_type in ("str_replace", "create", "insert"):
                        yield {"type": "step", "step": f"Editing {fpath}"}
                    else:
                        yield {"type": "step", "step": f"Viewing {fpath}"}
                    result = _exec_text_editor(inp, ws)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                else:
                    # UI dynamic tool
                    args = inp
                    yield {"type": "tool_call", "tool": name, "args": args}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"{name} rendered successfully",
                    })

            if approval_needed:
                break

            # Append assistant response + tool results for next loop
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            model_kwargs["messages"] = messages

        # Diff
        diff = _generate_diff(ws, before)
        if diff:
            yield {"type": "diff", "diff": diff}

        # Usage
        yield {"type": "usage", "usage": {
            "tokenUsage": {"total": {
                "inputTokens": total_input,
                "outputTokens": total_output,
                "cachedInputTokens": cache_read,
            }}
        }}

    except Exception as e:
        yield {"type": "callout", "callout": str(e), "style": "error"}


# --- Decorator ---


class Agent(App):
    """App subclass that bundles Node.js and Codex CLI dependencies."""

    def __init__(self, func, name, codex_version, node_version,
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


def agent(name=None, codex_version="0.101.0", node_version="v24.13.0", **kwargs):
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

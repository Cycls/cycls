import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import unquote

from .app import App


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


def setup_workspace(context):
    """Initialize per-user workspace and extract prompt.

    Returns (workspace_path, prompt_string).
    """
    user_id = context.user.id if context.user else "default"
    org_id = context.user.org_id if context.user else None
    ws = f"/workspace/{org_id}" if org_id else f"/workspace/{user_id}"
    os.makedirs(ws, exist_ok=True)
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
class ClaudeAgentOptions:
    workspace: str
    prompt: str
    model: str = "claude-sonnet-4-20250514"
    tools: List[dict] = field(default_factory=list)
    system: str = ""
    max_tokens: int = 16384
    thinking: bool = True
    thinking_budget: int = 10000
    session_id: Optional[str] = None


# --- Tool execution ---


async def _exec_bash(command, cwd):
    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    out = stdout.decode(errors="replace")
    if stderr:
        out += stderr.decode(errors="replace")
    if len(out) > 20000:
        out = out[:10000] + "\n... (truncated) ...\n" + out[-10000:]
    return out.strip() or "(no output)", proc.returncode


def _exec_editor(inp, workspace):
    import pathlib
    cmd = inp["command"]
    path = pathlib.Path(inp["path"])
    if not path.is_absolute():
        path = pathlib.Path(workspace) / path
    path = path.resolve()
    if not str(path).startswith(os.path.realpath(workspace)):
        return f"Error: path {path} is outside workspace"

    if cmd == "view":
        if not path.exists():
            return f"Error: {path} does not exist"
        lines = path.read_text().splitlines()
        vr = inp.get("view_range")
        start = vr[0] if vr else 1
        if vr:
            lines = lines[vr[0] - 1:vr[1]]
        return "\n".join(f"{i + start:6}\t{l}" for i, l in enumerate(lines))

    if cmd == "str_replace":
        if not path.exists():
            return f"Error: {path} does not exist"
        text = path.read_text()
        old = inp["old_str"]
        count = text.count(old)
        if count == 0:
            return f"Error: old_str not found in {path}"
        if count > 1:
            return f"Error: old_str found {count} times, must be unique"
        path.write_text(text.replace(old, inp.get("new_str", ""), 1))
        return f"Replaced in {path}"

    if cmd == "create":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inp["file_text"])
        return f"Created {path}"

    if cmd == "insert":
        if not path.exists():
            return f"Error: {path} does not exist"
        lines = path.read_text().splitlines(keepends=True)
        new = inp["new_str"].splitlines(keepends=True)
        if not new[-1:] or not new[-1].endswith("\n"):
            new.append("\n")
        pos = inp["insert_line"]
        lines[pos:pos] = new
        path.write_text("".join(lines))
        return f"Inserted at line {pos} in {path}"

    return f"Error: unknown command {cmd}"


# --- Agent ---


async def ClaudeAgent(*, options):
    """Run one Claude turn. Async generator yielding streaming components."""
    import anthropic

    import uuid

    ws = options.workspace
    client = anthropic.AsyncAnthropic()

    sid = options.session_id or str(uuid.uuid4())
    if not options.session_id:
        yield {"type": "session_id", "session_id": sid}

    history_path = os.path.join(ws, ".cycls", f"history_{sid}.json")
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    try:
        with open(history_path) as f:
            messages = json.load(f)
        for msg in messages:
            c = msg.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict):
                        b.pop("cache_control", None)
    except (FileNotFoundError, json.JSONDecodeError):
        messages = []

    # Cache breakpoint 3: history boundary (last msg before new user input)
    if messages:
        prev = messages[-1]
        c = prev.get("content")
        if isinstance(c, list) and c:
            c[-1]["cache_control"] = {"type": "ephemeral"}
        elif isinstance(c, str):
            prev["content"] = [{"type": "text", "text": c, "cache_control": {"type": "ephemeral"}}]

    messages.append({"role": "user", "content": options.prompt})

    tools = [
        {"type": "bash_20250124", "name": "bash"},
        {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
        {"type": "web_search_20250305", "name": "web_search"},
    ] + [{"type": "custom", "name": t["name"], "description": t.get("description", ""),
          "input_schema": t.get("inputSchema", t.get("input_schema", {}))} for t in options.tools or []]

    # Cache breakpoint 2: tools
    if tools:
        tools[-1]["cache_control"] = {"type": "ephemeral"}

    kwargs = {"model": options.model, "max_tokens": options.max_tokens, "tools": tools, "messages": messages}
    # Cache breakpoint 1: system prompt
    if options.system:
        kwargs["system"] = [{"type": "text", "text": options.system, "cache_control": {"type": "ephemeral"}}]
    if options.thinking:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": options.thinking_budget}

    total_in = total_out = cache_read = 0

    try:
        while True:
            thinking_text = ""
            tool_blocks = []
            ws_idx, ws_input = None, ""

            async with client.messages.stream(**kwargs) as stream:
                async for ev in stream:
                    if ev.type == "content_block_start":
                        b = ev.content_block
                        if b.type == "server_tool_use" and b.name == "web_search":
                            ws_idx, ws_input = ev.index, ""
                    elif ev.type == "content_block_delta":
                        if ev.delta.type == "thinking_delta":
                            thinking_text += ev.delta.thinking
                        elif ev.delta.type == "text_delta":
                            yield ev.delta.text
                        elif ev.delta.type == "input_json_delta" and ev.index == ws_idx:
                            ws_input += ev.delta.partial_json
                    elif ev.type == "content_block_stop":
                        if thinking_text:
                            yield {"type": "thinking", "thinking": thinking_text}
                            thinking_text = ""
                        if ev.index == ws_idx:
                            try:
                                q = json.loads(ws_input).get("query", "")
                            except Exception:
                                q = ""
                            yield {"type": "step", "step": f'Web Search("{q}")' if q else "Web Search"}
                            ws_idx = None
                response = await stream.get_final_message()

            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0

            for block in response.content:
                if block.type == "tool_use":
                    tool_blocks.append(block)

            _content = [b.model_dump(exclude_none=True) for b in response.content]

            if response.stop_reason != "tool_use":
                messages.append({"role": "assistant", "content": _content})
                break

            results = []
            for block in tool_blocks:
                name, inp = block.name, block.input

                if name == "bash":
                    cmd = inp.get("command", "")
                    yield {"type": "step", "step": f"Bash({cmd[:60]})"}
                    output, _ = await _exec_bash(cmd, ws)
                    yield {"type": "step_data", "data": output}
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

                elif name == "str_replace_based_edit_tool":
                    fpath = inp.get("path", "file")
                    verb = "Editing" if inp.get("command") in ("str_replace", "create", "insert") else "Viewing"
                    yield {"type": "step", "step": f"{verb} {fpath}"}
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": _exec_editor(inp, ws)})

                else:
                    yield {"type": "tool_call", "tool": name, "args": inp}
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"{name} rendered successfully"})

            messages.append({"role": "assistant", "content": _content})
            messages.append({"role": "user", "content": results})
            kwargs["messages"] = messages

        with open(history_path, "w") as f:
            json.dump(messages, f)

        yield {"type": "usage", "usage": {"tokenUsage": {"total": {"inputTokens": total_in, "outputTokens": total_out, "cachedInputTokens": cache_read}}}}

    except Exception as e:
        yield {"type": "callout", "callout": str(e), "style": "error"}


# --- Decorator ---


class Agent(App):
    def __init__(self, func, name, pip=None, **kwargs):
        super().__init__(func=func, name=name, pip=["anthropic", *(pip or [])], **kwargs)


def agent(name=None, **kwargs):
    def decorator(func):
        return Agent(func=func, name=name or func.__name__, **kwargs)
    return decorator

import asyncio, json, os, shutil
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import unquote

from .app import App

COMPACT_THRESHOLD = 100_000


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


def setup_workspace(context):
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


def _load_history(path):
    messages = []
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if line:
                    messages.append(json.loads(line))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except UnicodeDecodeError as e:
        print(f"[DEBUG] UnicodeDecodeError in {path} at line {i}: {e}")
        return messages
    for msg in messages:
        c = msg.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    if messages:
        c = messages[-1].get("content")
        if isinstance(c, str):
            messages[-1]["content"] = [{"type": "text", "text": c, "cache_control": {"type": "ephemeral"}}]
        elif isinstance(c, list) and c:
            c[-1]["cache_control"] = {"type": "ephemeral"}
    return messages

def _append_history(path, messages):
    with open(path, "a") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

def _rewrite_history(path, messages):
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

async def _compact(client, model, messages):
    """Summarize conversation into a compact continuation message."""
    response = await client.messages.create(
        model=model, max_tokens=8192,
        system=[{"type": "text", "text": (
            "Summarize this conversation concisely but thoroughly. Include: "
            "key decisions made, code changes with file paths, current state "
            "of work, and any pending tasks. This summary replaces the full "
            "conversation history."
        )}],
        messages=messages + [{"role": "user", "content": "Summarize our conversation so far for continuity."}],
    )
    summary = response.content[0].text
    return [
        {"role": "user", "content": (
            "This session is being continued from a previous conversation "
            "that ran out of context. The conversation is summarized below:\n\n"
            + summary
        )},
        {"role": "assistant", "content": "Understood. I have the full context from our previous conversation. How can I help?"},
    ]

def _build_tools(custom):
    tools = [
        {"type": "bash_20250124", "name": "bash"},
        {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
        {"type": "web_search_20250305", "name": "web_search"},
    ] + [{"type": "custom", "name": t["name"], "description": t.get("description", ""),
          "input_schema": t.get("inputSchema", t.get("input_schema", {}))} for t in custom or []]
    tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools

def _tool_result(bid, content):
    return {"type": "tool_result", "tool_use_id": bid, "content": content}

async def _exec_bash(command, cwd):
    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd)
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    out = stdout.decode(errors="replace") + (stderr.decode(errors="replace") if stderr else "")
    if len(out) > 20000:
        out = out[:10000] + "\n... (truncated) ...\n" + out[-10000:]
    return out.strip() or "(no output)"

def _exec_editor(inp, workspace):
    import pathlib
    cmd, path = inp["command"], pathlib.Path(inp["path"])
    if not path.is_absolute():
        path = pathlib.Path(workspace) / path
    path = path.resolve()
    if not str(path).startswith(os.path.realpath(workspace)):
        return f"Error: path {path} is outside workspace"
    if cmd != "create" and not path.exists():
        return f"Error: {path} does not exist"
    if cmd == "view":
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            return f"Error: {path} is a binary file"
        vr = inp.get("view_range")
        start = vr[0] if vr else 1
        if vr: lines = lines[vr[0] - 1:vr[1]]
        return "\n".join(f"{i + start:6}\t{l}" for i, l in enumerate(lines))
    if cmd == "str_replace":
        text, old = path.read_text(), inp["old_str"]
        count = text.count(old)
        if count == 0: return f"Error: old_str not found in {path}"
        if count > 1: return f"Error: old_str found {count} times, must be unique"
        path.write_text(text.replace(old, inp.get("new_str", ""), 1))
        return f"Replaced in {path}"
    if cmd == "create":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inp["file_text"])
        return f"Created {path}"
    if cmd == "insert":
        lines = path.read_text().splitlines(keepends=True)
        new = inp["new_str"].splitlines(keepends=True)
        if not new[-1:] or not new[-1].endswith("\n"): new.append("\n")
        pos = inp["insert_line"]
        lines[pos:pos] = new
        path.write_text("".join(lines))
        return f"Inserted at line {pos} in {path}"
    return f"Error: unknown command {cmd}"


async def ClaudeAgent(*, options):
    """Run one Claude turn. Async generator yielding streaming components."""
    import anthropic, uuid

    ws = options.workspace
    client = anthropic.AsyncAnthropic()

    sid = options.session_id or str(uuid.uuid4())
    if not options.session_id:
        yield {"type": "session_id", "session_id": sid}

    history_path = os.path.join(ws, ".cycls", f"{sid}.jsonl")
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    messages = _load_history(history_path)
    loaded_count = len(messages)
    messages.append({"role": "user", "content": options.prompt})

    kwargs = {
        "model": options.model, "max_tokens": options.max_tokens,
        "tools": _build_tools(options.tools), "messages": messages,
    }
    if options.system:
        kwargs["system"] = [{"type": "text", "text": options.system, "cache_control": {"type": "ephemeral"}}]
    if options.thinking:
        kwargs["thinking"] = {"type": "adaptive"}

    total_in = total_out = cache_read = cache_create = 0

    try:
        while True:
            thinking_text = ""
            search_idx, search_query = None, ""

            async with client.messages.stream(**kwargs) as stream:
                async for ev in stream:
                    if ev.type == "content_block_start":
                        b = ev.content_block
                        if b.type == "server_tool_use" and b.name == "web_search":
                            search_idx, search_query = ev.index, ""
                    elif ev.type == "content_block_delta":
                        if ev.delta.type == "thinking_delta":
                            thinking_text += ev.delta.thinking
                        elif ev.delta.type == "text_delta":
                            yield ev.delta.text
                        elif ev.delta.type == "input_json_delta" and ev.index == search_idx:
                            search_query += ev.delta.partial_json
                    elif ev.type == "content_block_stop":
                        if thinking_text:
                            yield {"type": "thinking", "thinking": thinking_text}
                            thinking_text = ""
                        if ev.index == search_idx:
                            try: q = json.loads(search_query).get("query", "")
                            except Exception: q = ""
                            yield {"type": "step", "step": f'Web Search("{q}")' if q else "Web Search"}
                            search_idx = None
                response = await stream.get_final_message()

            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens
            cache_read += getattr(response.usage, "cache_read_input_tokens", 0) or 0
            cache_create += getattr(response.usage, "cache_creation_input_tokens", 0) or 0

            content = [b.model_dump(exclude_none=True) for b in response.content]
            messages.append({"role": "assistant", "content": content})
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            if response.stop_reason != "tool_use":
                break

            results = []
            for block in tool_blocks:
                name, inp = block.name, block.input
                if name == "bash":
                    yield {"type": "step", "step": f"Bash({inp.get('command', '')[:60]})"}
                    out = await _exec_bash(inp.get("command", ""), ws)
                    yield {"type": "step_data", "data": out}
                    results.append(_tool_result(block.id, out))
                elif name == "str_replace_based_edit_tool":
                    fpath = inp.get("path", "file")
                    verb = "Editing" if inp.get("command") in ("str_replace", "create", "insert") else "Viewing"
                    yield {"type": "step", "step": f"{verb} {fpath}"}
                    results.append(_tool_result(block.id, _exec_editor(inp, ws)))
                else:
                    yield {"type": "tool_call", "tool": name, "args": inp}
                    results.append(_tool_result(block.id, f"{name} rendered successfully"))
            messages.append({"role": "user", "content": results})

    except Exception as e:
        import traceback
        print(f"[DEBUG] ClaudeAgent error: {e}\n{traceback.format_exc()}")
        yield {"type": "callout", "callout": str(e), "style": "error"}

    new_messages = messages[loaded_count:]
    if total_in > COMPACT_THRESHOLD and messages:
        try:
            yield {"type": "step", "step": "Compacting context..."}
            messages = await _compact(client, options.model, messages)
            _rewrite_history(history_path, messages)
        except Exception:
            if new_messages and new_messages[-1].get("role") == "assistant":
                _append_history(history_path, new_messages)
    elif new_messages and new_messages[-1].get("role") == "assistant":
        _append_history(history_path, new_messages)
    if total_in:
        yield {"type": "usage", "usage": {"tokenUsage": {"total": {
            "inputTokens": total_in, "outputTokens": total_out,
            "cachedInputTokens": cache_read, "cacheCreationTokens": cache_create,
        }}}}


class Agent(App):
    def __init__(self, func, name, pip=None, **kwargs):
        super().__init__(func=func, name=name, pip=["anthropic", *(pip or [])], **kwargs)

def agent(name=None, **kwargs):
    def decorator(func):
        return Agent(func=func, name=name or func.__name__, **kwargs)
    return decorator

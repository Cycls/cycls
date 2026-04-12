"""Agent loop — streams Claude tool-use turns with sandboxed execution."""

import asyncio, base64, json, os, pathlib, random, re
from cycls.app.state import ensure_workspace, history_path, load_history, save_history

# ---- Config ----

COMPACT_BUFFER = 30_000   # compact when within this many tokens of context window
KEEP_RECENT = 10          # keep last N messages verbatim during partial compaction
MAX_RETRIES = 10
MAX_OUTPUT = 30_000
BASE_DELAY_MS = 500
MAX_DELAY_MS = 32_000
_RETRYABLE_STATUSES = {429, 502, 503, 504, 529}
_BUILTINS = {
    "Bash": {"type": "bash_20250124", "name": "bash"},
    "WebSearch": {"type": "web_search_20250305", "name": "web_search"},
}
_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
_DOC_EXTS = {"pdf"}

# Custom tool schemas
_READ_TOOL = {
    "name": "read",
    "description": (
        "Read a file from the workspace.\n\n"
        "Usage:\n"
        "- Reads text files with line numbers (cat -n format, 1-indexed).\n"
        "- Reads images (PNG, JPG, GIF, WebP) and PDFs visually — you will see their contents.\n"
        "- When you already know which part of the file you need, use offset and limit to read only that part.\n"
        "- Only reads files, not directories. Use `ls` via bash for directories.\n"
        "- If you need to read a file the user mentioned, always use this tool — assume the path is valid.\n"
        "- It is okay to read a file that does not exist; an error will be returned."
    ),
    "inputSchema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Relative path to read (e.g. src/main.py)"},
        "offset": {"type": "integer", "description": "Start line, 1-indexed (default: 1)"},
        "limit": {"type": "integer", "description": "Max lines to read. Omit to read entire file."},
    }, "required": ["path"]}
}
_EDIT_TOOL = {
    "name": "edit",
    "description": (
        "Edit or create files in the workspace.\n\n"
        "Usage:\n"
        "- You MUST read a file with the `read` tool before editing it.\n"
        "- When using text from read output, preserve exact indentation (tabs/spaces) as shown after the line number.\n"
        "- The edit will FAIL if old_str is not unique in the file. Provide enough surrounding context to make it unique.\n"
        "- ALWAYS prefer editing existing files. NEVER create new files unless explicitly required.\n"
        "- Only use emojis if the user explicitly requests it.\n\n"
        "Commands:\n"
        "- str_replace: Replace old_str with new_str (old_str must appear exactly once).\n"
        "- create: Create a new file with file_text as content.\n"
        "- insert: Insert new_str at insert_line."
    ),
    "inputSchema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Relative path to edit"},
        "command": {"type": "string", "enum": ["str_replace", "create", "insert"]},
        "old_str": {"type": "string", "description": "Exact string to replace (must be unique in file)"},
        "new_str": {"type": "string", "description": "Replacement string or text to insert"},
        "file_text": {"type": "string", "description": "Full file content (create only)"},
        "insert_line": {"type": "integer", "description": "Line number to insert before (insert only)"},
    }, "required": ["path", "command"]}
}

_COMPACT_SYSTEM = """CRITICAL: Respond with TEXT ONLY. Do NOT call any tools. Tool calls will be REJECTED.
Your entire response must be an <analysis> block followed by a <summary> block.

Before writing your summary, use <analysis> tags to organize your thoughts:

1. Chronologically analyze each portion of the conversation. For each, identify:
   - The user's explicit requests and intents
   - Your approach to addressing them
   - Key decisions and technical concepts
   - Specific details: file names, code snippets, function signatures, file edits
   - Errors encountered and how they were fixed
   - User feedback, especially corrections or changed direction

2. Double-check for technical accuracy and completeness.

Then write your <summary> with these sections:

1. Primary Request and Intent: All user requests and intents in detail.
2. Key Technical Concepts: Technologies, frameworks, and patterns discussed.
3. Files and Code: Files examined, modified, or created. Include code snippets and why each matters.
4. Errors and Fixes: Errors encountered and how they were resolved, including user feedback.
5. Problem Solving: Problems solved and ongoing troubleshooting.
6. All User Messages: Every non-tool-result user message (critical for understanding intent changes).
7. Pending Tasks: Tasks explicitly asked for but not yet completed.
8. Current Work: Precisely what was being worked on before compaction, with file names and code.
9. Next Step: The immediate next step, with direct quotes from recent conversation showing where you left off. Only include if directly in line with the user's most recent request."""

_DEFAULT_SYSTEM = """You are Cycls, a general-purpose AI agent built by cycls.com that runs in the user's workspace in Cycls cloud.
You help with coding, research, writing, analysis, system administration, and any task the user brings.

## Tools
- Use `rg` or `rg --files` for searching text and files — it's faster than grep.
- Use the `read` tool to view any file — text, images (jpg, png, gif, webp), and PDFs.
- Use the `edit` tool to modify files — str_replace for changes, create for new files, insert for adding lines.
- Default to ASCII in file edits; only use Unicode when clearly justified.
- If a file format is not supported by `read` (e.g. docx, xlsx, pptx, mp4, mp3), tell the user what the file is and propose a way to extract its content. Do not run any code until the user approves.
- Always use relative paths (e.g. `foo.py`, `src/bar.py`) — never absolute paths.

## Workspace
- Your working directory is `/workspace`. All commands run here and all file paths are relative to it.
- The user's workspace persists across conversations. Files you create are files the user keeps.
- When the user returns, check what's already in their workspace — reference and build on previous work.
- Git is not available in this workspace.
- You are already in `/workspace` — never prefix commands with `cd /workspace`.
- Avoid destructive commands (`rm -rf`) unless the user explicitly asks.

## Working style
- The user may not be technical. Never assume they know programming concepts, terminal commands, or file system conventions.
- Present results in plain language. Instead of dumping raw command output, summarize what you found or did.

## Research and analysis
- When asked to research a topic, search the web and synthesize findings.
- Present findings organized by relevance, with sources.
- Distinguish facts from opinions and flag uncertainty.

## Code review
- Prioritize bugs, security risks, and missing tests.
- Present findings by severity with file and line references.
- State explicitly if no issues are found.
"""

# ---- Helpers ----

def _prepare_prompt(context):
    content = context.messages.raw[-1].get("content", "")
    if not isinstance(content, list):
        return content
    texts = [p["text"] for p in content if p.get("type") == "text"]
    files = [p.get("image") or p.get("file") for p in content if p.get("type") in ("image", "file")]
    files = [f for f in files if f]
    return " ".join(texts) + (f"\n\nAttached files: {', '.join(files)}" if files else "")

def _build_tools(builtin_tools, custom):
    tools = [_BUILTINS[b] for b in builtin_tools if b in _BUILTINS]
    editor = [_READ_TOOL, _EDIT_TOOL] if "Editor" in builtin_tools else []
    for t in editor + (custom or []):
        tools.append({"type": "custom", "name": t["name"], "description": t.get("description", ""),
                      "input_schema": t.get("inputSchema", t.get("input_schema", {}))})
    if tools:
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
    return tools

def _resolve_path(raw_path, workspace):
    ws = pathlib.Path(workspace).resolve()
    rel = raw_path.removeprefix("/workspace/").lstrip("/")
    path = (ws / rel).resolve()
    if not path.is_relative_to(ws): raise ValueError("path escapes workspace")
    return path

# ---- Tool execution ----

async def _exec_bash(command, cwd, timeout=600):
    proc = await asyncio.create_subprocess_exec(
        "bwrap", "--ro-bind", "/", "/", "--bind", cwd, "/workspace",
        "--tmpfs", "/app", "--tmpfs", "/tmp", "--dev", "/dev", "--proc", "/proc",
        "--chdir", "/workspace", "--die-with-parent", "--clearenv",
        "--setenv", "PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "--setenv", "HOME", "/workspace", "--setenv", "TERM", "xterm",
        "--setenv", "LANG", os.environ.get("LANG", "C.UTF-8"),
        "--", "bash", "-c", command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try: stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill(); await proc.wait()
        return f"Error: Command timed out after {timeout}s"
    out = stdout.decode(errors="replace") + (stderr.decode(errors="replace") if stderr else "")
    if len(out) > MAX_OUTPUT:
        h = MAX_OUTPUT // 2
        out = out[:h] + "\n... (truncated) ...\n" + out[-h:]
    return out.strip() or "(no output)"

def _exec_read(inp, workspace):
    try: path = _resolve_path(inp["path"], workspace)
    except ValueError as e: return f"Error: {e}"
    if not path.exists(): return f"Error: {path} does not exist"
    if path.is_dir(): return f"Error: {path} is a directory"
    ext = path.suffix.lower().lstrip(".")
    if ext in _IMAGE_EXTS or ext in _DOC_EXTS:
        kind = "image" if ext in _IMAGE_EXTS else "document"
        mt = ("image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}") if ext in _IMAGE_EXTS else f"application/{ext}"
        return [{"type": kind, "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(path.read_bytes()).decode()}}]
    try: lines = path.read_text().splitlines()
    except UnicodeDecodeError: return f"Error: {path} is a binary file"
    start = max(1, inp.get("offset", 1))
    limit = inp.get("limit")
    sliced = lines[start-1 : start-1+limit] if limit else lines[start-1:]
    return "\n".join(f"{i+start:6}\t{l}" for i, l in enumerate(sliced))

def _exec_edit(inp, workspace):
    try: path = _resolve_path(inp["path"], workspace)
    except ValueError as e: return f"Error: {e}"
    cmd = inp["command"]
    if cmd != "create" and not path.exists(): return f"Error: {path} does not exist"
    if path.exists() and path.is_dir(): return f"Error: {path} is a directory"
    if cmd == "str_replace":
        text, old = path.read_text(), inp["old_str"]
        n = text.count(old)
        if n == 0: return f"Error: old_str not found in {path}"
        if n > 1: return f"Error: old_str found {n} times, must be unique"
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
        pos = inp["insert_line"]; lines[pos:pos] = new
        path.write_text("".join(lines))
        return f"Inserted at line {pos} in {path}"
    return f"Error: unknown command {cmd}"

# ---- Dispatch ----

def _dispatch(block, ws, timeout):
    name, inp = block.name, block.input
    if name == "bash":
        cmd = inp.get("command", "")
        step = cmd if len(cmd) <= 80 else cmd[:60] + " … " + cmd[-17:]
        return {"type": "step", "tool_name": "Bash", "step": step}, _exec_bash(cmd, ws, timeout=timeout)
    if name == "read":
        return {"type": "step", "tool_name": "Reading", "step": inp.get("path", "")}, asyncio.to_thread(_exec_read, inp, ws)
    if name == "edit":
        return {"type": "step", "tool_name": "Editing", "step": inp.get("path", "")}, asyncio.to_thread(_exec_edit, inp, ws)
    return {"type": "tool_call", "tool": name, "args": inp}, asyncio.sleep(0, result=f"{name} executed")

# ---- Stream ----

async def _iter_stream(stream):
    search_idx, search_buf = None, ""
    async for ev in stream:
        if ev.type == "content_block_start":
            if ev.content_block.type == "server_tool_use" and ev.content_block.name == "web_search":
                search_idx, search_buf = ev.index, ""
        elif ev.type == "content_block_delta":
            d = ev.delta
            if d.type == "thinking_delta": yield {"type": "thinking", "thinking": d.thinking}
            elif d.type == "text_delta": yield d.text
            elif d.type == "input_json_delta" and ev.index == search_idx: search_buf += d.partial_json
        elif ev.type == "content_block_stop":
            if ev.index == search_idx:
                try: q = json.loads(search_buf).get("query", "")
                except Exception: q = ""
                yield {"type": "step", "step": q, "tool_name": "Web Search"}; search_idx = None

# ---- Retry & Recovery ----

def _is_retryable(e):
    """Check if error is retryable. Uses status code when available (Anthropic SDK), falls back to string match."""
    status = getattr(e, 'status_code', None) or getattr(e, 'status', None)
    if status and status in _RETRYABLE_STATUSES: return True
    msg = str(e).lower()
    return any(s in msg for s in ("overloaded", "rate limit", "too many requests", "429", "529"))

def _retry_delay(attempt, error=None):
    """Exponential backoff with jitter + retry-after header support (like Claude Code)."""
    # Respect retry-after header if present
    retry_after = getattr(error, 'headers', {}).get('retry-after') if error else None
    if retry_after:
        try: return int(retry_after)  # already in seconds
        except (ValueError, TypeError): pass
    base = min(BASE_DELAY_MS * (2 ** (attempt - 1)), MAX_DELAY_MS)
    jitter = random.random() * 0.25 * base
    return (base + jitter) / 1000  # seconds

def _recover(e, messages):
    last = messages[-1] if messages else {}
    content = last.get("content", [])
    if not isinstance(content, list): return False
    if last.get("role") == "assistant" and any(b.get("type") == "tool_use" for b in content):
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b["id"], "content": f"Error: {e}"}
            for b in content if b.get("type") == "tool_use"]})
        return True
    return False

# ---- Compaction ----

def _context_window(model):
    windows = {"claude-sonnet": 200_000, "claude-opus": 1_000_000, "claude-haiku": 200_000}
    return next((v for k, v in windows.items() if k in model), 200_000)

def _microcompact(messages):
    """Strip old tool results from messages older than KEEP_RECENT. Mutates in place."""
    keep = min(len(messages), KEEP_RECENT)
    for msg in messages[:-keep] if keep else []:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list): continue
        for block in msg["content"]:
            if block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                block["content"] = "[Old tool result cleared]"

async def _compact(client, model, messages):
    """Partial compaction: summarize old messages, keep recent verbatim. Returns new messages list."""
    _microcompact(messages)
    keep = min(len(messages), KEEP_RECENT)
    old = messages[:-keep] if keep else messages
    recent = messages[-keep:] if keep else []
    r = await client.messages.create(model=model, max_tokens=16384,
        system=[{"type": "text", "text": _COMPACT_SYSTEM}],
        messages=old + [{"role": "user", "content":
            "Summarize the conversation above following the structured format. "
            "Use <analysis> to think through everything, then <summary> for the final output. "
            "Recent messages will be preserved separately — focus on the older context."}])
    raw = r.content[0].text
    raw = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw)
    m = re.search(r"<summary>([\s\S]*?)</summary>", raw)
    summary = m.group(1).strip() if m else raw.strip()
    return [
        {"role": "user", "content": "This session continues from a previous conversation. Summary of earlier work:\n\n" + summary},
        {"role": "assistant", "content": "Understood. I have the full context. Recent messages follow."},
        *recent]

# ---- Agent ----

async def Agent(*, context, system="", tools=None, builtin_tools=[],
                model="claude-sonnet-4-20250514", max_tokens=16384, thinking=True,
                bash_timeout=600, show_usage=False, client=None):
    if client is None:
        import anthropic
        client = anthropic.AsyncAnthropic()
    ws = context.workspace
    ensure_workspace(ws)
    hp = history_path(context.user, context.session_id) if context.session_id and context.user else None
    messages = load_history(hp) if hp else []
    saved = len(messages)
    messages.append({"role": "user", "content": _prepare_prompt(context)})
    window = _context_window(model)

    kwargs = {
        "model": model, "max_tokens": max_tokens,
        "tools": _build_tools(builtin_tools, tools or []),
        "messages": messages,
        "system": [{"type": "text", "text": _DEFAULT_SYSTEM + ("\n\n" + system if system else ""),
                     "cache_control": {"type": "ephemeral"}}],
        **({"thinking": {"type": "adaptive"}} if thinking else {}),
    }
    usage = [0, 0, 0, 0]  # in, out, cached, cache_create
    retries = 0

    while True:
        try:
            # Pre-turn compaction: compact before API call if approaching context limit
            if usage[0] > window - COMPACT_BUFFER and len(messages) > KEEP_RECENT:
                yield {"type": "step", "step": "Compacting context..."}
                try:
                    messages[:] = await _compact(client, model, messages)
                    usage[0] = 0  # reset so we don't compact every turn
                    if hp: save_history(hp, messages, mode="w"); saved = len(messages)
                except Exception as ce:
                    yield {"type": "callout", "callout": f"Compaction failed: {ce}", "style": "warning"}

            async with client.messages.stream(**kwargs) as stream:
                async for event in _iter_stream(stream): yield event
                response = await stream.get_final_message()

            retries = 0
            u = response.usage
            usage[0] += u.input_tokens; usage[1] += u.output_tokens
            usage[2] += u.cache_read_input_tokens or 0; usage[3] += u.cache_creation_input_tokens or 0
            messages.append({"role": "assistant",
                            "content": [b.model_dump(exclude_none=True) for b in response.content]})
            if response.stop_reason != "tool_use": break

            blocks = [b for b in response.content if b.type == "tool_use"]
            pairs = [_dispatch(b, ws, bash_timeout) for b in blocks]
            for step, _ in pairs: yield step
            outputs = await asyncio.gather(*(c for _, c in pairs), return_exceptions=True)

            results = []
            for block, out in zip(blocks, outputs):
                if isinstance(out, BaseException): out = f"Error: {out}"
                if isinstance(out, str) and "timed out" in out:
                    yield {"type": "callout", "callout": out, "style": "warning"}
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            messages.append({"role": "user", "content": results})
            if hp: save_history(hp, messages[saved:]); saved = len(messages)

        except Exception as e:
            if _is_retryable(e) and retries < MAX_RETRIES:
                retries += 1
                delay = _retry_delay(retries, e)
                yield {"type": "step", "step": f"Rate limited, retrying in {delay:.1f}s... (attempt {retries}/{MAX_RETRIES})"}
                await asyncio.sleep(delay); continue
            if not _recover(e, messages):
                yield {"type": "callout", "callout": str(e), "style": "error"}; break
            if hp: save_history(hp, messages[saved:]); saved = len(messages)
            continue

    # Finalize: save any unsaved messages
    if hp and saved < len(messages):
        save_history(hp, messages[saved:])
    if show_usage and usage[0]:
        yield f'\n\n*in: {usage[0]:,} · out: {usage[1]:,} · cached: {usage[2]:,} · cache-create: {usage[3]:,}*'

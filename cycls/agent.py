"""Agent loop — streams Claude tool-use turns with sandboxed execution."""

import asyncio, base64, json, os, pathlib
from cycls.app.state import ensure_workspace, history_path, load_history, save_history

COMPACT_THRESHOLD = 300_000
MAX_ATTACHMENTS = 5
MAX_RETRIES = 3
_RETRYABLE = ("overloaded", "rate limit", "too many requests", "429", "502", "503", "504")

_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    ".pdf": "application/pdf",
}

_DEFAULT_SYSTEM = """You are Cycls, a general-purpose AI agent built by cycls.com that runs in the user's workspace in Cycls cloud.
You help with coding, research, writing, analysis, system administration, and any task the user brings.

## Tools
- Use `rg` or `rg --files` for searching text and files — it's faster than grep.
- Prefer `apply_patch` for single-file edits; use scripting when more efficient.
- Default to ASCII in file edits; only use Unicode when clearly justified.
- Always use the text editor `view` command to read files, including images (jpg, png, gif, webp) and PDFs.
- If a file format is not supported by `view` (e.g. docx, xlsx, pptx, mp4, mp3), tell the user what the file is and propose a way to extract its content. Do not run any code until the user approves. MS Office files (docx, xlsx, pptx) are ZIP archives containing XML — `unzip` is the simplest way to extract their text.
- Always use relative paths (e.g. `foo.py`, `src/bar.py`) with the text editor — never absolute paths.

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

_UI_TOOLS = [
    {
        "name": "render_canvas",
        "description": "Display a document canvas panel to the user. Use for long-form content like reports, articles, guides, code files, or any document the user may want to read, copy, or reference. The canvas opens as a side panel.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title shown at the top of the canvas panel"},
                "content": {"type": "string", "description": "Markdown content to display in the canvas"}
            },
            "required": ["title", "content"]
        }
    }
]

def _sniff_media_type(data: bytes) -> str | None:
    head = data[:12]
    if head[:3] == b"\xff\xd8\xff":          return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":    return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):  return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP": return "image/webp"
    if head[:4] == b"%PDF":                  return "application/pdf"
    return None

def _is_retryable(e):
    msg = str(e).lower()
    return any(s in msg for s in _RETRYABLE)

def _prepare_prompt(context):
    content = context.messages.raw[-1].get("content", "")
    if not isinstance(content, list):
        return content
    texts = []
    files = []
    for p in content:
        if p.get("type") == "text":
            texts.append(p["text"])
        elif p.get("type") in ("image", "file"):
            fname = p.get("image") or p.get("file")
            if fname:
                files.append(fname)
    if len(files) > MAX_ATTACHMENTS:
        extra = files[MAX_ATTACHMENTS:]
        files = files[:MAX_ATTACHMENTS]
        texts.append(f"(Only the first {MAX_ATTACHMENTS} files are in context. "
                     f"These {len(extra)} files are also in the workspace but not loaded: "
                     + ", ".join(extra) + ". Use the text editor view command to read them.)")
    prompt = " ".join(texts)
    if files:
        prompt += "\n\nAttached files: " + ", ".join(files)
    return prompt

async def _compact(client, model, messages):
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
    return [
        {"role": "user", "content": "This session is being continued from a previous conversation that ran out of context. The conversation is summarized below:\n\n" + response.content[0].text},
        {"role": "assistant", "content": "Understood. I have the full context from our previous conversation. How can I help?"},
    ]

_BUILTINS = {
    "Bash": {"type": "bash_20250124", "name": "bash"},
    "Editor": {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
    "WebSearch": {"type": "web_search_20250305", "name": "web_search"},
}

def _build_tools(builtin_tools, custom):
    tools = [_BUILTINS[b] for b in builtin_tools]
    tools += [{"type": "custom", "name": t["name"], "description": t.get("description", ""),
               "input_schema": t.get("inputSchema", t.get("input_schema", {}))} for t in custom or []]
    tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
    return tools

# ---- Tool execution ----

async def _exec_bash(command, cwd, timeout=600):
    proc = await asyncio.create_subprocess_exec(
        "bwrap",
        "--ro-bind", "/", "/",
        "--bind", cwd, "/workspace",
        "--tmpfs", "/app",
        "--tmpfs", "/tmp",
        "--dev", "/dev",
        "--proc", "/proc",
        "--chdir", "/workspace",
        "--die-with-parent",
        "--clearenv",
        "--setenv", "PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "--setenv", "HOME", "/workspace",
        "--setenv", "TERM", "xterm",
        "--setenv", "LANG", os.environ.get("LANG", "C.UTF-8"),
        "--",
        "bash", "-c", command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: Command timed out after {timeout}s"
    out = stdout.decode(errors="replace") + (stderr.decode(errors="replace") if stderr else "")
    if len(out) > 20000:
        out = out[:10000] + "\n... (truncated) ...\n" + out[-10000:]
    return out.strip() or "(no output)"

def _exec_editor(inp, workspace):
    cmd = inp["command"]
    ws = pathlib.Path(workspace).resolve()
    raw = pathlib.PurePosixPath(inp["path"])
    try:
        rel = raw.relative_to("/workspace")
    except ValueError:
        rel = pathlib.PurePosixPath(raw.as_posix().lstrip("/"))
    path = (ws / rel).resolve()
    if not path.is_relative_to(ws):
        return "Error: path escapes workspace"
    if cmd != "create" and not path.exists():
        return f"Error: {path} does not exist"
    if path.is_dir():
        return f"Error: {path} is a directory, not a file"
    if cmd == "view":
        media_type = _MEDIA_TYPES.get(path.suffix.lower())
        if media_type:
            blob = path.read_bytes()
            media_type = _sniff_media_type(blob) or media_type
            data = base64.b64encode(blob).decode()
            kind = "document" if not media_type.startswith("image/") else "image"
            return [{"type": kind, "source": {"type": "base64", "media_type": media_type, "data": data}}]
        try: lines = path.read_text().splitlines()
        except UnicodeDecodeError: return f"Error: {path} is a binary file"
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

async def _defer(fn, *args): return fn(*args)

_UI_TOOL_NAMES = {t["name"] for t in _UI_TOOLS}

def _render_ui_tool(name, args):
    if name == "render_table":
        events = []
        if title := args.get("title"):
            events.append(f"\n**{title}**\n")
        events.append({"type": "table", "headers": args.get("headers", [])})
        for row in args.get("rows", []):
            events.append({"type": "table", "row": row})
        return events
    if name == "render_callout":
        return [{"type": "callout", "callout": args.get("message", ""), "style": args.get("style", "info"), "title": args.get("title", "")}]
    if name == "render_image":
        return [{"type": "image", "src": args.get("src", ""), "alt": args.get("alt", ""), "caption": args.get("caption", "")}]
    if name == "render_canvas":
        return [
            {"type": "canvas", "canvas": "document", "open": True, "title": args.get("title", "Document")},
            {"type": "canvas", "canvas": "document", "content": args.get("content", "")},
            {"type": "canvas", "canvas": "document", "done": True},
        ]
    return None

def _prepare_tool(block, ws, timeout):
    name, inp = block.name, block.input
    if name == "bash":
        cmd = inp.get('command', '')
        label = cmd if len(cmd) <= 80 else cmd[:60] + ' … ' + cmd[-17:]
        step = {"type": "step", "step": f"Bash({label})"}
        coro = _exec_bash(inp.get("command", ""), ws, timeout=timeout)
    elif name == "str_replace_based_edit_tool":
        verb = "Editing" if inp.get("command") in ("str_replace", "create", "insert") else "Viewing"
        step = {"type": "step", "step": f"{verb} {inp.get('path', 'file')}"}
        coro = _defer(_exec_editor, inp, ws)
    elif name in _UI_TOOL_NAMES:
        step = _render_ui_tool(name, inp) or []
        coro = asyncio.sleep(0, result=f"{name} rendered successfully")
    else:
        step = {"type": "tool_call", "tool": name, "args": inp}
        coro = asyncio.sleep(0, result=f"{name} rendered successfully")
    return step, coro

# ---- Agent ----

def _recover(e, messages):
    """Try to patch messages for recovery. Returns save mode ("a"/"w") or None."""
    last = messages[-1] if messages else {}
    content = last.get("content", [])
    if not isinstance(content, list):
        return None
    if last.get("role") == "assistant" and any(b.get("type") == "tool_use" for b in content):
        results = [{"type": "tool_result", "tool_use_id": b["id"], "content": f"Error: {e}"}
                   for b in content if b.get("type") == "tool_use"]
        messages.append({"role": "user", "content": results})
        return "a"
    if any(b.get("type") == "tool_result" and not str(b.get("content", "")).startswith("Error:")
           for b in content):
        for b in content:
            if b.get("type") == "tool_result":
                b["content"] = f"Error: {e}"
        return "w"
    return None

async def _finalize(client, model, hp, messages, saved, usage, show_usage=False):
    new = messages[saved:]
    if hp:
        did_compact = False
        if usage["inputTokens"] > COMPACT_THRESHOLD and messages:
            try:
                yield {"type": "step", "step": "Compacting context..."}
                summary = await _compact(client, model, messages)
                save_history(hp, summary, mode="w")
                did_compact = True
            except Exception:
                pass
        if not did_compact and new and new[-1].get("role") == "assistant":
            save_history(hp, new)
    if show_usage and usage["inputTokens"]:
        yield f'\n\n*in: {usage["inputTokens"]:,} · out: {usage["outputTokens"]:,} · cached: {usage["cachedInputTokens"]:,} · cache-create: {usage["cacheCreationTokens"]:,}*'

async def Agent(*, context, system="", tools=None, builtin_tools=[],
                model="claude-sonnet-4-20250514", max_tokens=16384, thinking=True,
                bash_timeout=600, show_usage=False):
    """Run one Claude agent turn. Async generator yielding streaming UI components."""
    import anthropic

    ws = context.workspace
    ensure_workspace(ws)
    prompt = _prepare_prompt(context)
    client = anthropic.AsyncAnthropic()
    hp = history_path(context.user, context.session_id) if context.session_id and context.user else None
    messages = load_history(hp) if hp else []
    saved = len(messages)
    messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": model, "max_tokens": max_tokens,
        "tools": _build_tools(builtin_tools, _UI_TOOLS + (tools or [])),
        "messages": messages,
        "system": [{"type": "text", "text": _DEFAULT_SYSTEM + ("\n\n" + system if system else ""),
                     "cache_control": {"type": "ephemeral"}}],
        **({"thinking": {"type": "adaptive"}} if thinking else {}),
    }

    usage = {"inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "cacheCreationTokens": 0}
    retries = 0

    while True:
        try:
            # ---- Stream ----
            thinking_text, search_idx, search_query = "", None, ""
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

            # ---- Process ----
            retries = 0
            u = response.usage
            usage["inputTokens"] += u.input_tokens
            usage["outputTokens"] += u.output_tokens
            usage["cachedInputTokens"] += u.cache_read_input_tokens or 0
            usage["cacheCreationTokens"] += u.cache_creation_input_tokens or 0

            messages.append({"role": "assistant",
                            "content": [b.model_dump(exclude_none=True) for b in response.content]})

            if response.stop_reason != "tool_use":
                break

            # ---- Execute tools ----
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            steps, coros = zip(*(_prepare_tool(b, ws, bash_timeout) for b in tool_blocks))
            for s in steps:
                if isinstance(s, list):
                    for e in s: yield e
                else:
                    yield s
            outputs = await asyncio.gather(*coros, return_exceptions=True)

            results = []
            for block, out in zip(tool_blocks, outputs):
                if isinstance(out, BaseException): out = f"Error: {out}"
                if isinstance(out, str) and out.startswith("Error: Command timed out"):
                    yield {"type": "callout", "callout": out, "style": "warning"}
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            messages.append({"role": "user", "content": results})

            if hp:
                save_history(hp, messages[saved:])
                saved = len(messages)

        except Exception as e:
            if _is_retryable(e) and retries < MAX_RETRIES:
                retries += 1
                delay = 2 ** retries
                yield {"type": "step", "step": f"Rate limited, retrying in {delay}s..."}
                await asyncio.sleep(delay)
                continue
            mode = _recover(e, messages)
            if mode is None:
                yield {"type": "callout", "callout": str(e), "style": "error"}
                break
            if hp:
                save_history(hp, messages if mode == "w" else messages[saved:], mode=mode)
                saved = len(messages)
            continue

    async for event in _finalize(client, model, hp, messages, saved, usage, show_usage):
        yield event

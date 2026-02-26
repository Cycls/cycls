import asyncio, base64, json, os

from cycls.app.state import read_file, _MEDIA_TYPES, ensure_workspace, history_path, load_history, save_history

COMPACT_THRESHOLD = 100_000

_DEFAULT_SYSTEM = """## Tools
- Use `rg` or `rg --files` for searching text and files — it's faster than grep.
- Prefer `apply_patch` for single-file edits; use scripting when more efficient.
- Default to ASCII in file edits; only use Unicode when clearly justified.
- You can view images (jpg, png, gif, webp) and PDFs directly using the text editor's `view` command.

## Workspace
- The user's workspace persists across conversations. Files you create are files the user keeps.
- When the user returns, check what's already in their workspace — reference and build on previous work.
- Git is not available in this workspace.
- Avoid destructive commands (`rm -rf`) unless the user explicitly asks.
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

# ---- Internal helpers ----

def _prepare_prompt(context):
    ws = context.workspace
    ensure_workspace(ws)
    content = context.messages.raw[-1].get("content", "")
    if not isinstance(content, list):
        return ws, content
    blocks = []
    has_media = False
    for p in content:
        if p.get("type") == "text":
            blocks.append({"type": "text", "text": p["text"]})
            continue
        if p.get("type") not in ("image", "file"):
            continue
        fname = p.get("image") or p.get("file") or ""
        if not fname:
            continue
        try:
            media_type, data = read_file(ws, fname)
        except (ValueError, FileNotFoundError):
            continue
        if media_type:
            has_media = True
            encoded = base64.b64encode(data).decode()
            kind = "document" if media_type == "application/pdf" else "image"
            blocks.append({"type": kind, "source": {"type": "base64", "media_type": media_type, "data": encoded}})
        else:
            text = data
            if len(text) > 400_000:
                text = text[:400_000] + "\n\n[... truncated ...]"
            blocks.append({"type": "text", "text": f"[File: {fname}]\n{text}\n[End of file]"})
    if not has_media:
        return ws, " ".join(b["text"] for b in blocks if b.get("type") == "text")
    return ws, blocks


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
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    out = stdout.decode(errors="replace") + (stderr.decode(errors="replace") if stderr else "")
    if len(out) > 20000:
        out = out[:10000] + "\n... (truncated) ...\n" + out[-10000:]
    return out.strip() or "(no output)"

async def _run_tool(block, ws):
    name, inp = block.name, block.input
    if name == "bash":
        return await _exec_bash(inp.get("command", ""), ws)
    elif name == "str_replace_based_edit_tool":
        return _exec_editor(inp, ws)
    return f"{name} rendered successfully"

def _exec_editor(inp, workspace):
    import pathlib
    cmd = inp["command"]
    raw = pathlib.Path(inp["path"])
    path = raw if raw.is_absolute() else (pathlib.Path(workspace) / raw).resolve()
    if cmd != "create" and not path.exists():
        return f"Error: {path} does not exist"
    if path.is_dir():
        return f"Error: {path} is a directory, not a file"
    if cmd == "view":
        ext = path.suffix.lower()
        media_type = _MEDIA_TYPES.get(ext)
        if media_type:
            data = base64.b64encode(path.read_bytes()).decode()
            kind = "document" if not media_type.startswith("image/") else "image"
            return [{"type": kind, "source": {"type": "base64", "media_type": media_type, "data": data}}]
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

# ---- Public API ----

async def Agent(context, *, system="", tools=None, model="claude-sonnet-4-20250514",
                max_tokens=16384, thinking=True):
    """Run one Claude agent turn. Async generator yielding streaming UI components."""
    import anthropic

    ws, prompt = _prepare_prompt(context)
    client = anthropic.AsyncAnthropic()

    sid = context.session_id
    user = context.user
    hp = history_path(user, sid) if sid and user else None

    messages = load_history(hp) if hp else []
    loaded_count = len(messages)
    messages.append({"role": "user", "content": prompt})

    all_tools = _UI_TOOLS + (tools or [])
    full_system = _DEFAULT_SYSTEM + ("\n\n" + system if system else "")

    kwargs = {
        "model": model, "max_tokens": max_tokens,
        "tools": _build_tools(all_tools), "messages": messages,
        "system": [{"type": "text", "text": full_system, "cache_control": {"type": "ephemeral"}}],
    }
    if thinking:
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
            cache_read += response.usage.cache_read_input_tokens or 0
            cache_create += response.usage.cache_creation_input_tokens or 0

            content = [b.model_dump(exclude_none=True) for b in response.content]
            messages.append({"role": "assistant", "content": content})
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            if response.stop_reason != "tool_use":
                break

            # Yield step indicators, then execute tools in parallel
            for block in tool_blocks:
                name, inp = block.name, block.input
                if name == "bash":
                    yield {"type": "step", "step": f"Bash({inp.get('command', '')[:60]})"}
                elif name == "str_replace_based_edit_tool":
                    verb = "Editing" if inp.get("command") in ("str_replace", "create", "insert") else "Viewing"
                    yield {"type": "step", "step": f"{verb} {inp.get('path', 'file')}"}
                else:
                    yield {"type": "tool_call", "tool": name, "args": inp}

            if len(tool_blocks) > 1:
                print(f"[PARALLEL] Running {len(tool_blocks)} tools concurrently")
            outputs = await asyncio.gather(*[_run_tool(b, ws) for b in tool_blocks])
            results = []
            for block, out in zip(tool_blocks, outputs):
                if block.name == "bash":
                    yield {"type": "step_data", "data": out}
                results.append(_tool_result(block.id, out))
            messages.append({"role": "user", "content": results})

    except Exception as e:
        import traceback
        print(f"[DEBUG] Agent error: {e}\n{traceback.format_exc()}")
        yield {"type": "callout", "callout": str(e), "style": "error"}

    new_messages = messages[loaded_count:]
    if hp:
        if total_in > COMPACT_THRESHOLD and messages:
            try:
                yield {"type": "step", "step": "Compacting context..."}
                messages = await _compact(client, model, messages)
                save_history(hp, messages, mode="w")
            except Exception:
                if new_messages and new_messages[-1].get("role") == "assistant":
                    save_history(hp, new_messages)
        elif new_messages and new_messages[-1].get("role") == "assistant":
            save_history(hp, new_messages)
    if total_in:
        yield {"type": "usage", "usage": {"tokenUsage": {"total": {
            "inputTokens": total_in, "outputTokens": total_out,
            "cachedInputTokens": cache_read, "cacheCreationTokens": cache_create,
        }}}}

"""Agent loop — streams LLM tool-use turns with sandboxed execution."""

import asyncio, base64, json, os, pathlib, warnings
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")
import litellm
litellm.drop_params = True
from cycls.app.state import ensure_workspace, history_path, load_history, save_history

COMPACT_THRESHOLD = 100_000
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
    # {
    #     "name": "render_canvas",
    #     "description": "Display a document canvas panel to the user. Use for long-form content like reports, articles, guides, code files, or any document the user may want to read, copy, or reference. The canvas opens as a side panel.",
    #     "inputSchema": {
    #         "type": "object",
    #         "properties": {
    #             "title": {"type": "string", "description": "Title shown at the top of the canvas panel"},
    #             "content": {"type": "string", "description": "Markdown content to display in the canvas"}
    #         },
    #         "required": ["title", "content"]
    #     }
    # }
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

def _track_usage(usage, chunk):
    u = getattr(chunk, "usage", None)
    if not u:
        return
    usage["inputTokens"] += getattr(u, "prompt_tokens", 0) or 0
    usage["outputTokens"] += getattr(u, "completion_tokens", 0) or 0
    pd = getattr(u, "prompt_tokens_details", None)
    if pd:
        usage["cachedInputTokens"] += getattr(pd, "cached_tokens", 0) or 0

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

async def _compact(model, messages):
    sys_content = ("Summarize this conversation concisely but thoroughly. Include: "
                   "key decisions made, code changes with file paths, current state "
                   "of work, and any pending tasks. This summary replaces the full "
                   "conversation history.")
    response = await litellm.acompletion(
        model=model, max_tokens=8192,
        messages=[{"role": "system", "content": sys_content}]
                 + messages
                 + [{"role": "user", "content": "Summarize our conversation so far for continuity."}],
    )
    summary = response.choices[0].message.content
    return [
        {"role": "user", "content": "This session is being continued from a previous conversation that ran out of context. The conversation is summarized below:\n\n" + summary},
        {"role": "assistant", "content": "Understood. I have the full context from our previous conversation. How can I help?"},
    ]

_BUILTINS = {
    "Bash": {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a bash command in the sandbox. Working directory is /workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to run"}
                },
                "required": ["command"]
            }
        }
    },
    "Editor": {
        "type": "function",
        "function": {
            "name": "str_replace_based_edit_tool",
            "description": (
                "View, create, or edit files using commands: view, str_replace, create, insert. "
                "Always use relative paths from /workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "enum": ["view", "str_replace", "create", "insert"],
                                "description": "The operation to perform"},
                    "path": {"type": "string", "description": "Relative file path"},
                    "old_str": {"type": "string", "description": "Text to find and replace (str_replace)"},
                    "new_str": {"type": "string", "description": "Replacement text (str_replace/insert)"},
                    "file_text": {"type": "string", "description": "Full file content (create)"},
                    "insert_line": {"type": "integer", "description": "Line number to insert at (insert)"},
                    "view_range": {"type": "array", "items": {"type": "integer"},
                                   "description": "[start_line, end_line] range to view"}
                },
                "required": ["command", "path"]
            }
        }
    },
    # WebSearch is handled via web_search_options param, not as a tool
}

def _build_tools(builtin_tools, custom):
    tools = [_BUILTINS[b] for b in builtin_tools if b in _BUILTINS]
    seen = {t["function"]["name"] for t in tools}
    for t in (custom or []):
        name = t["name"]
        if name in seen:
            continue
        seen.add(name)
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", t.get("input_schema", {}))
            }
        })
    return tools or None

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

def _prepare_tool(name, inp, ws, timeout):
    if name == "bash":
        cmd = inp.get('command', '')
        label = cmd if len(cmd) <= 80 else cmd[:60] + ' … ' + cmd[-17:]
        step = {"type": "step", "step": label, "tool_name": "Bash"}
        coro = _exec_bash(inp.get("command", ""), ws, timeout=timeout)
    elif name == "str_replace_based_edit_tool":
        verb = "Editing" if inp.get("command") in ("str_replace", "create", "insert") else "Viewing"
        step = {"type": "step", "step": inp.get('path', 'file'), "tool_name": verb}
        async def _run_editor(i=inp, w=ws): return _exec_editor(i, w)
        coro = _run_editor()
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
    # Case 1: assistant made tool_calls, API rejected next request → inject error tool results
    if last.get("role") == "assistant" and last.get("tool_calls"):
        for tc in last["tool_calls"]:
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": f"Error: {e}"})
        return "a"
    # Case 2: tool results exist but content was rejected (e.g. oversized) → replace with error
    if last.get("role") == "tool" and not str(last.get("content", "")).startswith("Error:"):
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "tool":
                messages[i]["content"] = f"Error: {e}"
            else:
                break
        return "w"
    return None

async def _finalize(model, hp, messages, saved, usage, show_usage=False):
    new = messages[saved:]
    if hp:
        did_compact = False
        if usage["inputTokens"] > COMPACT_THRESHOLD and messages:
            try:
                yield {"type": "step", "step": "Compacting context..."}
                summary = await _compact(model, messages)
                save_history(hp, summary, mode="w")
                did_compact = True
            except Exception:
                pass
        if not did_compact and new and new[-1].get("role") == "assistant":
            save_history(hp, new)
    if show_usage and usage["inputTokens"]:
        yield f'\n\n*in: {usage["inputTokens"]:,} · out: {usage["outputTokens"]:,} · cached: {usage["cachedInputTokens"]:,}*'

async def Agent(*, context, system="", tools=None, builtin_tools=[],
                model="claude-sonnet-4-20250514", max_tokens=16384, thinking=True,
                bash_timeout=600, show_usage=False):
    """Run one agent turn. Async generator yielding streaming UI components."""

    ws = context.workspace
    ensure_workspace(ws)
    prompt = _prepare_prompt(context)
    hp = history_path(context.user, context.session_id) if context.session_id and context.user else None
    messages = load_history(hp) if hp else []
    saved = len(messages)
    messages.append({"role": "user", "content": prompt})

    sys_msg = {"role": "system", "content": _DEFAULT_SYSTEM + ("\n\n" + system if system else "")}
    tool_defs = _build_tools(builtin_tools, _UI_TOOLS + (tools or []))

    kwargs = {
        "model": model, "max_tokens": max_tokens,
        "messages": [sys_msg] + messages,
        "stream": True,
    }
    if tool_defs:
        kwargs["tools"] = tool_defs
    if "WebSearch" in builtin_tools:
        kwargs["web_search_options"] = {"search_context_size": "medium"}
        # Gemini requires this to combine built-in search with function calling
        if "gemini" in model.lower():
            kwargs["include_server_side_tool_invocations"] = True
    if thinking:
        kwargs["reasoning_effort"] = "high"

    usage = {"inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0}
    retries = 0

    while True:
        try:
            # ---- Stream ----
            text_parts = []
            tool_calls_acc = {}
            server_tool_indices = set()

            response = await litellm.acompletion(**kwargs)
            async for chunk in response:
                choice = chunk.choices[0] if chunk.choices else None
                if not choice:
                    _track_usage(usage, chunk)
                    continue

                delta = choice.delta

                # Thinking / reasoning — yield each chunk immediately
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    yield {"type": "thinking", "thinking": rc}

                if delta.content:
                    yield delta.content
                    text_parts.append(delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                            # Detect server-side tools immediately
                            if tc.id.startswith("srvtoolu_"):
                                server_tool_indices.add(idx)
                        if tc.function and tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                            # Emit Web Search step in real-time
                            if tc.function.name == "web_search":
                                server_tool_indices.add(idx)
                                yield {"type": "step", "step": "", "tool_name": "Web Search"}
                        if tc.function and tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

                if choice.finish_reason:
                    _track_usage(usage, chunk)

            # ---- Build assistant message ----
            retries = 0
            assistant_msg = {"role": "assistant", "content": "".join(text_parts) or None}
            parsed_calls = [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for idx, tc in sorted(tool_calls_acc.items()) if idx not in server_tool_indices
            ]
            if parsed_calls:
                assistant_msg["tool_calls"] = parsed_calls
            messages.append(assistant_msg)

            if not parsed_calls:
                break

            # ---- Execute tools ----
            tool_inputs = []
            for tc in parsed_calls:
                try: inp = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError): inp = {}
                tool_inputs.append((tc, *_prepare_tool(tc["function"]["name"], inp, ws, bash_timeout)))

            for _, step, _ in tool_inputs:
                if isinstance(step, list):
                    for e in step: yield e
                else:
                    yield step

            outputs = await asyncio.gather(*(coro for _, _, coro in tool_inputs), return_exceptions=True)

            for (tc, _, _), out in zip(tool_inputs, outputs):
                if isinstance(out, BaseException): out = f"Error: {out}"
                if isinstance(out, str) and "Command timed out" in out:
                    yield {"type": "callout", "callout": out, "style": "warning"}
                out = json.dumps(out) if isinstance(out, list) else str(out) if not isinstance(out, str) else out
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": out})

            if hp:
                save_history(hp, messages[saved:])
                saved = len(messages)

            kwargs["messages"] = [sys_msg] + messages

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
            kwargs["messages"] = [sys_msg] + messages
            continue

    async for event in _finalize(model, hp, messages, saved, usage, show_usage):
        yield event

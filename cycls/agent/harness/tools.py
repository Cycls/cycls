"""Tool schemas, execution, and dispatch."""
import asyncio, base64, os, pathlib
from . import pdf

MAX_OUTPUT = 30_000

_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
_DOC_EXTS = {"pdf"}

# Custom tool schemas
_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Execute a shell command in the workspace sandbox.\n\n"
        "Usage:\n"
        "- Working directory is /workspace. Never prefix commands with `cd /workspace`.\n"
        "- Use `rg` or `rg --files` for searching — it's faster than grep.\n"
        "- Use `jq` to extract fields from JSON.\n"
        "- Use the `read` tool (not cat/head/tail) for viewing files.\n"
        "- Use the `edit` tool (not sed/awk) for modifying files.\n"
        "- Always quote paths containing spaces with double quotes.\n"
        "- Output over 30K chars is truncated in the middle — use head/grep/tail in the command to keep results focused.\n"
        "- Default timeout is 600s; adjust via `timeout` parameter (milliseconds).\n"
        "- Avoid destructive commands (`rm -rf`) unless the user explicitly asks.\n"
        "- When issuing multiple independent commands, send multiple bash tool calls in parallel rather than chaining with &&."
    ),
    "inputSchema": {"type": "object", "properties": {
        "command": {"type": "string", "description": "The shell command to execute."},
        "timeout": {"type": "integer", "description": "Timeout in milliseconds (default: 600000, max: 600000)."},
        "description": {"type": "string", "description": "Short 5-10 word active-voice summary of what this command does (shown in the UI). Example: 'List files in current directory', 'Run pytest suite'."},
    }, "required": ["command"]}
}

_READ_TOOL = {
    "name": "read",
    "description": (
        "Read a file from the workspace.\n\n"
        "Usage:\n"
        "- Reads text files with line numbers (cat -n format, 1-indexed).\n"
        "- Reads images (PNG, JPG, GIF, WebP) and small PDFs visually — you will see their contents.\n"
        "- For LARGE PDFs (over 3MB): you MUST provide the `pages` parameter, e.g. pages='1-5'. "
        "The tool will render those pages as images. Maximum 20 pages per read. "
        "If you don't know how many pages the PDF has, the error message will tell you.\n"
        "- When you already know which part of the file you need, use offset and limit to read only that part.\n"
        "- Only reads files, not directories. Use `ls` via bash for directories.\n"
        "- If you need to read a file the user mentioned, always use this tool — assume the path is valid.\n"
        "- It is okay to read a file that does not exist; an error will be returned."
    ),
    "inputSchema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Relative path to read (e.g. src/main.py)"},
        "offset": {"type": "integer", "description": "Start line, 1-indexed (default: 1)"},
        "limit": {"type": "integer", "description": "Max lines to read. Omit to read entire file."},
        "pages": {"type": "string", "description": "Page range for large PDFs, e.g. '1-5' or '3'. Required for PDFs over 3MB. Max 20 pages."},
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

def _to_custom(t):
    return {"type": "custom", "name": t["name"], "description": t.get("description", ""),
            "input_schema": t.get("inputSchema", t.get("input_schema", {}))}

_BUILTINS = {
    "WebSearch": [{"type": "web_search_20250305", "name": "web_search"}],
    "Bash": [_to_custom(_BASH_TOOL)],
    "Editor": [_to_custom(_READ_TOOL), _to_custom(_EDIT_TOOL)],
}

def build_tools(allowed_tools, custom):
    tools = []
    for name in allowed_tools:
        tools.extend(_BUILTINS.get(name, []))
    for t in (custom or []):
        tools.append(_to_custom(t))
    if tools:
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return tools

def _resolve_path(raw_path, workspace):
    ws = pathlib.Path(workspace).resolve()
    rel = raw_path.removeprefix("/workspace/").lstrip("/")
    path = (ws / rel).resolve()
    if not path.is_relative_to(ws): raise ValueError("path escapes workspace")
    reserved = ws / ".cycls"
    if path == reserved or path.is_relative_to(reserved):
        raise ValueError(".cycls/ is managed by cycls")
    return path

# ---- Tool execution ----

async def _exec_bash(command, cwd, timeout=600, network=False):
    # Network is isolated only when requested off — unshare-net works in nested
    # containers where --unshare-pid (and its procfs mount) doesn't.
    net_flags = () if network else ("--unshare-net",)
    # bwrap itself is visible inside the sandbox's /proc, so its own environ
    # must be sanitized — --clearenv only affects the child (bash).
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    lang = os.environ.get("LANG", "C.UTF-8")
    bwrap_env = {"PATH": path, "LANG": lang}
    proc = await asyncio.create_subprocess_exec(
        "bwrap", "--ro-bind", "/", "/", "--bind", cwd, "/workspace",
        "--ro-bind-try", str(pathlib.Path(cwd) / ".cycls"), "/workspace/.cycls",
        "--tmpfs", "/app", "--tmpfs", "/tmp", "--dev", "/dev", "--proc", "/proc",
        *net_flags,
        "--chdir", "/workspace", "--die-with-parent", "--clearenv",
        "--setenv", "PATH", path,
        "--setenv", "HOME", "/workspace", "--setenv", "TERM", "xterm",
        "--setenv", "LANG", lang,
        "--", "bash", "-c", command,
        env=bwrap_env,
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

async def _exec_read(inp, workspace):
    try: path = _resolve_path(inp["path"], workspace)
    except ValueError as e: return f"Error: {e}"
    if not path.exists(): return f"Error: {path} does not exist"
    if path.is_dir(): return f"Error: {path} is a directory"
    ext = path.suffix.lower().lstrip(".")
    size = path.stat().st_size

    # Large PDF → extract page range via pdftoppm
    if ext == "pdf" and size > pdf.EXTRACT_SIZE_THRESHOLD:
        pages_spec = inp.get("pages")
        if not pages_spec:
            count = await pdf.page_count(path)
            hint = f"{count} pages" if count else "unknown page count"
            return (f"Error: PDF is {size//1024//1024}MB ({hint}). "
                    f"Provide the `pages` parameter, e.g. pages='1-5'. "
                    f"Max {pdf.MAX_PAGES_PER_READ} pages per read.")
        parsed = pdf.parse_pages(pages_spec)
        if not parsed:
            return f"Error: invalid pages '{pages_spec}'. Use format '1-5' or '3'."
        return await pdf.extract(path, *parsed)

    # Other large files → reject
    if size > 3 * 1024 * 1024:
        return f"Error: file is too large to read (>3 MB). Use bash (head/grep/jq) to extract what you need from `{inp['path']}`."

    # Small media → native content block
    if ext in _IMAGE_EXTS or ext in _DOC_EXTS:
        kind = "image" if ext in _IMAGE_EXTS else "document"
        mt = ("image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}") if ext in _IMAGE_EXTS else f"application/{ext}"
        return [{"type": kind, "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(path.read_bytes()).decode()}}]

    # Text → line-numbered output
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

def dispatch(block, ws, timeout, handlers=None, network=False):
    name, inp = block.name, block.input
    if name == "bash":
        cmd = inp.get("command", "")
        step = inp.get("description") or cmd
        t = inp.get("timeout")
        secs = t / 1000 if t else timeout
        return {"type": "step", "tool_name": "Bash", "step": step}, _exec_bash(cmd, ws, timeout=secs, network=network)
    if name == "read":
        return {"type": "step", "tool_name": "Reading", "step": inp.get("path", "")}, _exec_read(inp, ws)
    if name == "edit":
        return {"type": "step", "tool_name": "Editing", "step": inp.get("path", "")}, asyncio.to_thread(_exec_edit, inp, ws)
    if handlers and name in handlers:
        return {"type": "step", "tool_name": name, "step": ""}, handlers[name](inp)
    return {"type": "tool_call", "tool": name, "args": inp}, asyncio.sleep(0, result=f"{name} executed")

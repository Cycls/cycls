"""Tool schemas, execution, and dispatch.

`Tool` is the foundation primitive — name + description + input_schema, plus
an optional `raw` for provider-specific built-ins (e.g. web_search). All tools
(built-in and user-supplied) flow through this shape; `build_tools` projects
to the Anthropic API format at the boundary."""
import asyncio, base64, json, os, pathlib
from dataclasses import dataclass, field
from typing import Optional

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
        "- Use the `edit` tool to create OR modify files — never `cat >`, `echo >`, heredocs, or `sed`/`awk`. Bash for files bypasses safety checks and blows the output-token budget on long content.\n"
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
_DATABASE_TOOL = {
    "name": "database",
    "description": (
        "Persistent key-value store scoped to this workspace. Use for state that must "
        "survive across turns or chat sessions: notes, user preferences, task progress, "
        "anything you'd otherwise jam into a JSON file. Atomic writes, prefix scans, "
        "no race conditions. Prefer this over writing JSON files via bash.\n\n"
        "Commands:\n"
        "- get:    read a value at `key`. Returns the stored JSON or 'not found'.\n"
        "- put:    write `value` (any JSON-serializable type) at `key`.\n"
        "- delete: remove `key`.\n"
        "- scan:   list all {key, value} pairs whose key starts with `prefix`. "
        "Empty prefix lists everything.\n\n"
        "Keys are opaque slash-separated strings — design your own schema. "
        "Use prefixes to group related data, e.g. `tasks/<id>`, `notes/<topic>`, "
        "`prefs/<scope>`."
    ),
    "inputSchema": {"type": "object", "properties": {
        "command": {"type": "string", "enum": ["get", "put", "delete", "scan"]},
        "key": {"type": "string", "description": "Key to operate on (get, put, delete)."},
        "value": {"description": "Value to store (put only). Any JSON-serializable type."},
        "prefix": {"type": "string", "description": "Key prefix to list (scan only). Empty = all keys."},
    }, "required": ["command"]}
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

@dataclass(frozen=True)
class Tool:
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    raw: Optional[dict] = None  # provider-native shape (e.g. web_search server-tool)

    def to_anthropic(self) -> dict:
        return self.raw or {"type": "custom", "name": self.name,
                            "description": self.description, "input_schema": self.input_schema}

    @classmethod
    def from_dict(cls, d: dict) -> "Tool":
        return cls(name=d["name"], description=d.get("description", ""),
                   input_schema=d.get("inputSchema", d.get("input_schema", {})))


_BUILTINS: dict[str, list[Tool]] = {
    "WebSearch": [Tool(name="web_search", raw={"type": "web_search_20250305", "name": "web_search"})],
    "Bash":     [Tool.from_dict(_BASH_TOOL)],
    "Editor":   [Tool.from_dict(_READ_TOOL), Tool.from_dict(_EDIT_TOOL)],
    "DataBase": [Tool.from_dict(_DATABASE_TOOL)],
}


def build_tools(allowed_tools, custom):
    tools = []
    for name in allowed_tools:
        tools.extend(t.to_anthropic() for t in _BUILTINS.get(name, []))
    for t in (custom or []):
        tools.append(Tool.from_dict(t).to_anthropic())
    if tools:
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return tools

def _resolve_path(raw_path, workspace):
    ws = pathlib.Path(workspace).resolve()
    rel = raw_path.removeprefix("/workspace/").lstrip("/")
    path = (ws / rel).resolve()
    if not path.is_relative_to(ws): raise ValueError("path escapes workspace")
    for name in (".db", ".database"):
        reserved = ws / name
        if path == reserved or path.is_relative_to(reserved):
            raise ValueError(f"{name}/ is managed by cycls")
    return path

# ---- Tool execution ----

async def _exec_bash(command, cwd, timeout=600, network=False):
    from cycls.app.sandbox import Sandbox
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    lang = os.environ.get("LANG", "C.UTF-8")
    sb = (Sandbox()
          .bind(cwd, "/workspace")
          .tmpfs("/workspace/.db")        # cycls state (chat, shares); editor blocks via _resolve_path
          .tmpfs("/workspace/.database")  # agent KV store; same blocking
          .tmpfs("/app")
          .chdir("/workspace")
          .setenv(PATH=path, LANG=lang)
          .network(network).timeout(timeout))
    result = await sb.run(["bash", "-c", command], env={"PATH": path, "LANG": lang})
    if result.timed_out:
        return f"Error: Command timed out after {timeout}s"
    out = result.output
    if len(out) > MAX_OUTPUT:
        h = MAX_OUTPUT // 2
        out = out[:h] + "\n... (truncated) ...\n" + out[-h:]
    return out.strip() or "(no output)"

async def _exec_read(inp, workspace):
    try: path = _resolve_path(inp["path"], workspace)
    except ValueError as e: return f"Error: {e}"
    if not path.exists(): return f"Error: {path} does not exist"
    if path.is_dir(): return f"Error: {path} is a directory"
    ext, size = path.suffix.lower().lstrip("."), path.stat().st_size

    if ext == "pdf" and size > pdf.EXTRACT_SIZE_THRESHOLD:
        if not (pages_spec := inp.get("pages")):
            count = await pdf.page_count(path)
            hint = f"{count} pages" if count else "unknown page count"
            return (f"Error: PDF is {size//1024//1024}MB ({hint}). Provide pages='1-5'. "
                    f"Max {pdf.MAX_PAGES_PER_READ} pages per read.")
        parsed = pdf.parse_pages(pages_spec)
        if not parsed: return f"Error: invalid pages '{pages_spec}'. Use '1-5' or '3'."
        return await pdf.extract(path, *parsed)

    if size > 3 * 1024 * 1024:
        return f"Error: file too large (>3 MB). Use bash (head/grep/jq) on `{inp['path']}`."

    if ext in _IMAGE_EXTS or ext in _DOC_EXTS:
        kind = "image" if ext in _IMAGE_EXTS else "document"
        mt = ("image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}") if ext in _IMAGE_EXTS else f"application/{ext}"
        return [{"type": kind, "source": {"type": "base64", "media_type": mt,
                                          "data": base64.b64encode(path.read_bytes()).decode()}}]

    try: lines = path.read_text().splitlines()
    except UnicodeDecodeError: return f"Error: {path} is a binary file"
    start = max(1, inp.get("offset", 1))
    sliced = lines[start-1 : start-1 + inp["limit"]] if inp.get("limit") else lines[start-1:]
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

# ---- Database ----

async def _exec_database(inp, workspace):
    """All returns are strings — Anthropic tool_result.content accepts
    str or content-blocks (each with a `type`); raw dicts/lists from JSON
    values would 400. JSON-encode the data ones."""
    from cycls.app.workspace import workspace_at, DB
    agent_ws = workspace_at(workspace.subject, workspace.root.parent,
                            base=workspace.base, slot=".database")
    db = DB(agent_ws)
    cmd, key = inp.get("command"), inp.get("key", "")
    if cmd == "get":
        v = await db.get(key)
        return json.dumps(v) if v is not None else f"Error: key {key!r} not found"
    if cmd == "put":
        if not key: return "Error: put requires `key`"
        await db.put(key, inp.get("value"))
        return f"Stored {key!r}"
    if cmd == "delete":
        if not key: return "Error: delete requires `key`"
        await db.delete(key)
        return f"Deleted {key!r}"
    if cmd == "scan":
        prefix = inp.get("prefix", "")
        pairs = [{"key": k, "value": v} async for k, v in db.items(prefix=prefix)]
        return json.dumps(pairs) if pairs else f"No keys with prefix {prefix!r}"
    return f"Error: unknown command {cmd!r}"


# ---- Registry & dispatch ----
#
# One entry per harness tool: (run, step). `run(inp, workspace, *, timeout,
# network)` returns the awaitable result, or is None for tools that execute
# elsewhere (web_search runs server-side; it's here only for the UI label).
# `step(inp)` renders the {tool_name, step} line, shared by the live dispatch
# path and the refetch path (to_ui_messages) so they agree.

def _run_bash(inp, workspace, *, timeout, network):
    t = inp.get("timeout")
    return _exec_bash(inp.get("command", ""), workspace.root, timeout=t / 1000 if t else timeout, network=network)

_TOOLS = {
    "bash":       (_run_bash,
                   lambda inp: {"tool_name": "Bash", "step": inp.get("description") or inp.get("command", "")}),
    "read":       (lambda inp, ws, **_: _exec_read(inp, ws.root),
                   lambda inp: {"tool_name": "Reading", "step": inp.get("path", "")}),
    "edit":       (lambda inp, ws, **_: asyncio.to_thread(_exec_edit, inp, ws.root),
                   lambda inp: {"tool_name": "Editing", "step": inp.get("path", "")}),
    "database":   (lambda inp, ws, **_: _exec_database(inp, ws),
                   lambda inp: {"tool_name": "Database",
                                "step": f"{inp.get('command', '')} {inp.get('key') or inp.get('prefix', '')}".strip()}),
    "web_search": (None,
                   lambda inp: {"tool_name": "Web Search", "step": inp.get("query", "")}),
}


def tool_step(name, input):
    inp = input or {}
    entry = _TOOLS.get(name)
    return entry[1](inp) if entry else {"tool_name": name, "step": ""}


def dispatch(block, workspace, timeout, handlers=None, network=False):
    """*block* is a tool_use content block (dict): {type, id, name, input}.
    Returns (step_event_dict, awaitable_result). The step carries the block's
    `id` so the FE can fold it into the `ToolStart`/`ToolArgs` it already showed."""
    bid, name, inp = block["id"], block["name"], block.get("input") or {}
    entry = _TOOLS.get(name)
    if entry and entry[0]:
        return {"type": "step", "id": bid, **entry[1](inp)}, entry[0](inp, workspace, timeout=timeout, network=network)
    if handlers and name in handlers:
        return {"type": "step", "id": bid, **tool_step(name, inp)}, handlers[name](inp)
    return {"type": "tool_call", "id": bid, "tool": name, "args": inp}, asyncio.sleep(0, result=f"{name} executed")

"""Tool schemas, execution, and dispatch. Each built-in is stored in Anthropic
API shape (`type` / `name` / `description` / `input_schema`) and registered in
`_BUILTINS`; `build_tools` emits them as-is. User-supplied custom tools come
through `_normalize_tool` (accepts the camelCase `inputSchema` form too)."""
import asyncio, base64, ipaddress, json, os, pathlib, socket
from html.parser import HTMLParser
from . import pdf, skills
from ..state import _exec_database

MAX_OUTPUT = 30_000

_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
_DOC_EXTS = {"pdf"}

_BASH_TOOL = {
    "type": "custom",
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
    "input_schema": {"type": "object", "properties": {
        "command": {"type": "string", "description": "The shell command to execute."},
        "timeout": {"type": "integer", "description": "Timeout in milliseconds (default: 600000, max: 600000)."},
        "description": {"type": "string", "description": "Short 5-10 word active-voice summary of what this command does (shown in the UI). Example: 'List files in current directory', 'Run pytest suite'."},
    }, "required": ["command"]}
}

_READ_TOOL = {
    "type": "custom",
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
    "input_schema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Relative path to read (e.g. src/main.py)"},
        "offset": {"type": "integer", "description": "Start line, 1-indexed (default: 1)"},
        "limit": {"type": "integer", "description": "Max lines to read. Omit to read entire file."},
        "pages": {"type": "string", "description": "Page range for large PDFs, e.g. '1-5' or '3'. Required for PDFs over 3MB. Max 20 pages."},
    }, "required": ["path"]}
}

_DATABASE_TOOL = {
    "type": "custom",
    "name": "database",
    "description": (
        "Persistent key-value store scoped to this workspace. Use for state that must "
        "survive across turns or chat sessions: notes, user preferences, task progress, "
        "anything you'd otherwise jam into a JSON file. Atomic per-key writes, prefix "
        "scans. Prefer this over writing JSON files via bash.\n\n"
        "Commands:\n"
        "- get:    read a value at `key`. Returns the stored JSON or 'not found'.\n"
        "- put:    write `value` (any JSON-serializable type) at `key`.\n"
        "- delete: remove `key`. Trailing slash wipes a namespace (`notes/` removes everything under it).\n"
        "- scan:   list {key, value} pairs whose key starts with `prefix`. "
        "Truncates at `limit` (default 100) so a huge prefix won't blow the context.\n\n"
        "Keys are slash-separated (e.g. `tasks/<id>`). Cannot start with `/` or contain `..`."
    ),
    "input_schema": {"type": "object", "properties": {
        "command": {"type": "string", "enum": ["get", "put", "delete", "scan"]},
        "key": {"type": "string", "description": "Key to operate on (get, put, delete)."},
        "value": {"description": "Value to store (put only). Any JSON-serializable type."},
        "prefix": {"type": "string", "description": "Key prefix (scan only). Empty = all keys."},
        "limit": {"type": "integer", "description": "Max results returned by scan (default 100)."},
    }, "required": ["command"]}
}

_EDIT_TOOL = {
    "type": "custom",
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
    "input_schema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Relative path to edit"},
        "command": {"type": "string", "enum": ["str_replace", "create", "insert"]},
        "old_str": {"type": "string", "description": "Exact string to replace (must be unique in file)"},
        "new_str": {"type": "string", "description": "Replacement string or text to insert"},
        "file_text": {"type": "string", "description": "Full file content (create only)"},
        "insert_line": {"type": "integer", "description": "Line number to insert before (insert only)"},
    }, "required": ["path", "command"]}
}

_CANVAS_TOOL = {
    "type": "custom",
    "name": "canvas",
    "description": (
        "Show a FINISHED deliverable to the user in the canvas viewer (a side "
        "panel). Renders markdown, HTML, PDF, images, audio/video, code/text, CSV, "
        "and Excel (xlsx/xls/ods); other types offer a download.\n\n"
        "Use ONLY for a final artifact the user is actually expecting to view — the "
        "report, document, dashboard, sheet, or chart they asked you to produce, "
        "and only once it is complete.\n"
        "Do NOT open transient or intermediate files: scripts you run, scratch or "
        "work-in-progress notes, intermediate/partial markdown, helper or config "
        "files, or anything you are still editing. When unsure, don't open it.\n"
        "Call this at most once, after the deliverable is ready. Give the "
        "workspace-relative path."
    ),
    "input_schema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Relative path of the file to display (e.g. report.xlsx)."},
    }, "required": ["path"]}
}

# Portable web tools (Brave search + a generic fetch), client-side so they run
# on any provider. `WebSearch` enables the pair; `web_search="native"` swaps in
# the provider's own server-side search instead (Anthropic only, for now).
_WEB_SEARCH_TOOL = {
    "type": "custom",
    "name": "web_search",
    "description": (
        "Search the web with Brave. Returns ranked results — each with its title, "
        "URL, and the most relevant passages from the page. One call is usually "
        "enough; when a result's passages aren't sufficient, follow up with "
        "`web_fetch` on its URL.\n"
        "Use for current events, facts, docs, or anything outside your training."
    ),
    "input_schema": {"type": "object", "properties": {
        "query": {"type": "string", "description": "The search query."},
        "count": {"type": "integer", "description": "Number of results (default 5, max 20)."},
    }, "required": ["query"]}
}
_WEB_FETCH_TOOL = {
    "type": "custom",
    "name": "web_fetch",
    "description": (
        "Fetch a web page by URL and return its readable text. Use after "
        "`web_search` when you need the full page, not just the passages. "
        "Give the exact http(s) URL."
    ),
    "input_schema": {"type": "object", "properties": {
        "url": {"type": "string", "description": "The full http(s) URL to fetch."},
        "max_chars": {"type": "integer", "description": "Max characters to return (default 20000)."},
    }, "required": ["url"]}
}
_NATIVE_WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search"}

_BUILTINS = {
    "Bash":     [_BASH_TOOL],
    "Editor":   [_READ_TOOL, _EDIT_TOOL],
    "DataBase": [_DATABASE_TOOL],
    "Canvas":   [_CANVAS_TOOL],
}


def _web_search_tools(vendor, mode):
    """`native` → the provider's server-side search (Anthropic only, for now);
    otherwise our portable Brave search + fetch. `brave` without a
    BRAVE_API_KEY falls back to native where the provider has one."""
    native_ok = vendor in (None, "anthropic")
    if mode == "native" or (native_ok and not os.environ.get("BRAVE_API_KEY")):
        return [_NATIVE_WEB_SEARCH] if native_ok else []
    return [_WEB_SEARCH_TOOL, _WEB_FETCH_TOOL]


def vendor_skips(allowed_tools, vendor, web_search="brave"):
    """Requested tools the active vendor can't run — native search off Anthropic."""
    if "WebSearch" in allowed_tools and web_search == "native" and vendor not in (None, "anthropic"):
        return ["WebSearch"]
    return []


def _normalize_tool(spec):
    """User-supplied custom tool → Anthropic shape. Accepts `inputSchema` too."""
    if spec.get("type"):  # already provider-native (web_search, etc.)
        return spec
    return {"type": "custom", "name": spec["name"],
            "description": spec.get("description", ""),
            "input_schema": spec.get("inputSchema", spec.get("input_schema", {}))}


def build_tools(allowed_tools, custom, vendor=None, web_search="brave"):
    """Provider-neutral list. The Anthropic provider attaches a `cache_control`
    breakpoint to the last tool at request time."""
    tools = []
    for name in allowed_tools:
        if name == "WebSearch":
            tools += _web_search_tools(vendor, web_search)
        else:
            tools += _BUILTINS.get(name, [])
    tools += [_normalize_tool(t) for t in (custom or [])]
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
    for src, dst in skills.dev_mounts():   # dev skill scripts/templates, read-only
        sb = sb.ro_bind(src, dst)
    result = await sb.run(["bash", "-c", command], env={"PATH": path, "LANG": lang})
    if result.timed_out:
        return f"Error: Command timed out after {timeout}s"
    out = result.output
    if len(out) > MAX_OUTPUT:
        h = MAX_OUTPUT // 2
        out = out[:h] + "\n... (truncated) ...\n" + out[-h:]
    return out.strip() or "(no output)"

async def _exec_web_search(inp):
    """Brave web search — one call, native-parity. Each result carries its
    clean passages (description + extra_snippets), so no second fetch is needed
    for most queries. Key from `BRAVE_API_KEY`."""
    key = os.environ.get("BRAVE_API_KEY")
    if not key: return "Error: web search is unavailable (BRAVE_API_KEY not set)."
    query = (inp.get("query") or "").strip()
    if not query: return "Error: query is required."
    count = min(max(int(inp.get("count") or 5), 1), 20)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://api.search.brave.com/res/v1/web/search",
                                  params={"q": query, "count": count},
                                  headers={"X-Subscription-Token": key, "Accept": "application/json"})
        r.raise_for_status()
        results = ((r.json().get("web") or {}).get("results") or [])[:count]
    except Exception as e:
        return f"Error: web search failed ({e})."
    if not results: return f"No results for {query!r}."
    def fmt(i, x):
        passages = " ".join([x.get("description", ""), *x.get("extra_snippets", [])]).strip()
        return f"{i+1}. {x.get('title', '')}\n{x.get('url', '')}\n{passages}"
    return "\n\n".join(fmt(i, x) for i, x in enumerate(results))


class _TextExtractor(HTMLParser):
    """Minimal HTML → text: drop scripts/styles/nav, keep visible text. Zero deps."""
    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP: self._skip += 1
    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip: self._skip -= 1
    def handle_data(self, data):
        if not self._skip and (t := data.strip()): self.parts.append(t)


def _html_to_text(html):
    p = _TextExtractor()
    try: p.feed(html)
    except Exception: pass
    return "\n".join(p.parts)


_FETCH_MAX_BYTES = 2_000_000
_FETCH_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CyclsAgent/1.0)"}


def _is_public_host(host):
    """web_fetch runs in the server process, not the bash sandbox — refuse
    hosts that resolve to loopback/private/link-local addresses (SSRF)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        return all(ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)
    except (OSError, ValueError):
        return False


async def _exec_web_fetch(inp):
    """Fetch a URL and return readable text — the model's on-demand 'read the
    full page' step after web_search."""
    url = (inp.get("url") or "").strip()
    if not url.startswith(("http://", "https://")): return "Error: a full http(s) URL is required."
    limit = min(max(int(inp.get("max_chars") or 20_000), 500), 100_000)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for _ in range(5):  # redirect hops, each host re-checked
                if not await asyncio.to_thread(_is_public_host, httpx.URL(url).host):
                    return "Error: URL resolves to a private or unreachable address."
                async with client.stream("GET", url, headers=_FETCH_HEADERS) as r:
                    if r.is_redirect:
                        url = str(httpx.URL(url).join(r.headers.get("location", "")))
                        continue
                    r.raise_for_status()
                    total, chunks = 0, []
                    async for chunk in r.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= _FETCH_MAX_BYTES: break
                    body = b"".join(chunks).decode(r.encoding or "utf-8", "replace")
                    ctype = r.headers.get("content-type", "")
                    break
            else:
                return "Error: too many redirects."
    except Exception as e:
        return f"Error: fetch failed ({e})."
    text = (_html_to_text(body) if "html" in ctype else body).strip()
    return (text[:limit] + "\n... (truncated)") if len(text) > limit else (text or "(no readable text)")


async def _exec_read(inp, workspace):
    try: path = skills.resolve_dev_path(inp["path"]) or _resolve_path(inp["path"], workspace)
    except ValueError as e: return f"Error: {e}"
    if not path.exists(): return f"Error: {inp['path']} does not exist"
    if path.is_dir(): return f"Error: {inp['path']} is a directory"
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
    except UnicodeDecodeError: return f"Error: {inp['path']} is a binary file"
    start = max(1, inp.get("offset", 1))
    sliced = lines[start-1 : start-1 + inp["limit"]] if inp.get("limit") else lines[start-1:]
    return "\n".join(f"{i+start:6}\t{l}" for i, l in enumerate(sliced))

async def _exec_canvas(inp, workspace):
    """Resolve + validate the path, then return a UI event the loop forwards to
    the client to open the canvas. The model gets a short ack (see the loop)."""
    raw = inp.get("path", "")
    try: path = _resolve_path(raw, workspace)
    except ValueError as e: return f"Error: {e}"
    if not path.exists(): return f"Error: {raw} does not exist"
    if path.is_dir(): return f"Error: {raw} is a directory"
    rel = raw.removeprefix("/workspace/").lstrip("/")
    return {"type": "ui", "action": "open_canvas", "path": rel, "name": path.name}

def _exec_edit(inp, workspace):
    # Echo the model's own relative path back — resolved paths leak the
    # tenant dir and the model reuses them verbatim (e.g. in canvas calls).
    rel = inp.get("path", "")
    try: path = _resolve_path(inp["path"], workspace)
    except ValueError as e: return f"Error: {e}"
    cmd = inp["command"]
    if cmd != "create" and not path.exists(): return f"Error: {rel} does not exist"
    if path.exists() and path.is_dir(): return f"Error: {rel} is a directory"
    if cmd == "str_replace":
        text, old = path.read_text(), inp["old_str"]
        n = text.count(old)
        if n == 0: return f"Error: old_str not found in {rel}"
        if n > 1: return f"Error: old_str found {n} times, must be unique"
        path.write_text(text.replace(old, inp.get("new_str", ""), 1))
        return f"Replaced in {rel}"
    if cmd == "create":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(inp["file_text"])
        return f"Created {rel}"
    if cmd == "insert":
        lines = path.read_text().splitlines(keepends=True)
        new = inp["new_str"].splitlines(keepends=True)
        if not new[-1:] or not new[-1].endswith("\n"): new.append("\n")
        pos = inp["insert_line"]; lines[pos:pos] = new
        path.write_text("".join(lines))
        return f"Inserted at line {pos} in {rel}"
    return f"Error: unknown command {cmd}"

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
    "canvas":     (lambda inp, ws, **_: _exec_canvas(inp, ws.root),
                   lambda inp: {"tool_name": "Canvas", "step": inp.get("path", "")}),
    "skill":      (lambda inp, ws, **_: skills._exec_skill(inp, ws.root),
                   lambda inp: {"tool_name": "Skill", "step": inp.get("name", "")}),
    "web_search": (lambda inp, ws, **_: _exec_web_search(inp),
                   lambda inp: {"tool_name": "Web Search", "step": inp.get("query", "")}),
    "web_fetch":  (lambda inp, ws, **_: _exec_web_fetch(inp),
                   lambda inp: {"tool_name": "Fetching", "step": inp.get("url", "")}),
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

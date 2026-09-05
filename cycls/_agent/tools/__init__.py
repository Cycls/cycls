"""Tool schemas, execution, and dispatch. Each built-in is stored in Anthropic
API shape (`type` / `name` / `description` / `input_schema`) and registered in
`_BUILTINS`; `build_tools` emits them as-is. User-supplied custom tools come
through `_normalize_tool` (accepts the camelCase `inputSchema` form too)."""
import asyncio, base64, ipaddress, json, os, pathlib, socket
from html.parser import HTMLParser
from typing import NamedTuple
from . import pdf, skills
from ..state import _exec_database
from .. import trash

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
        "- Save files in the workspace, never /tmp — every command gets its own /tmp, "
        "discarded the moment it exits, and the read/edit/canvas tools cannot see it. "
        "Download with `curl -o report.pdf <url>`, not `curl -o /tmp/report.pdf <url>`.\n"
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
        "Excel (xlsx/xls/ods), and 3D models (glb/gltf); other types offer a download.\n\n"
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
        "Search the web with Brave. Returns JSON — `{query, results: [{title, "
        "url, snippet}]}` — ranked, each snippet holding the most relevant "
        "passages from the page. One call is usually enough; when a result's "
        "snippet isn't sufficient, follow up with `web_fetch` on its URL.\n"
        "Search BEFORE answering — never from memory — whenever:\n"
        "- the answer could have changed since training: news, prices, versions, "
        "people's roles, laws, schedules\n"
        "- the question involves niche or specialized detail — small entities, "
        "local info, fan wikis, fiction/lore, regulations. Your memory of "
        "specifics is unreliable even when the topic feels familiar.\n"
        "- the user names a source (a wiki, site, or publication) — consulting it "
        "is mandatory, never answer on its behalf\n"
        "- the user disputes something you said — verify before re-answering; "
        "confidence is not a reason to skip\n"
        "- getting a small detail wrong is costly\n"
        "Keep queries short and specific (1-6 words), in the language of the "
        "likely best sources; if results miss, reformulate with different terms "
        "rather than repeating.\n"
        "Cite only URLs this tool or `web_fetch` returned — the user sees them "
        "as source chips, so a URL you invented is visibly unbacked. Never "
        "attribute a claim to a source you did not retrieve; if results don't "
        "contain the answer, say so — don't fill the gap.\n"
        "Do NOT end your answer with a 'Sources:' list — the client already "
        "shows every result the search returned, as chips under your answer. "
        "Link inline only where a specific claim needs its source named."
    ),
    "input_schema": {"type": "object", "properties": {
        "query": {"type": "string", "description": "The search query."},
        "count": {"type": "integer", "description": "Number of results (default 5, max 20)."},
        "country": {"type": "string", "description": "2-letter country code (e.g. 'sa', 'us') — biases ranking toward that region. Set it when regional or local results matter; omit for global topics."},
        "search_lang": {"type": "string", "description": "2-letter language code (e.g. 'ar', 'en') — restricts result language. Set it only when sources must be in that language; omit to let the query language decide."},
    }, "required": ["query"]}
}
_WEB_FETCH_TOOL = {
    "type": "custom",
    "name": "web_fetch",
    "description": (
        "Fetch a web page by URL and return its readable text. Use after "
        "`web_search` when you need the full page, not just the passages — and "
        "ALWAYS when the user gives a URL or points at a specific page. "
        "Give the exact http(s) URL."
    ),
    "input_schema": {"type": "object", "properties": {
        "url": {"type": "string", "description": "The full http(s) URL to fetch."},
        "max_chars": {"type": "integer", "description": "Max characters to return (default 20000)."},
    }, "required": ["url"]}
}
_NATIVE_WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search"}

_BUILD_APP_TOOL = {
    "type": "custom",
    "name": "build_app",
    "description": (
        "Bundle app source into a single self-contained HTML file and install "
        "it as an app, which the user opens from the Apps tab.\n\n"
        "Write the source into the workspace first with the editor — one file per "
        "component, `index.html` as the entry — then call this with that folder. "
        "The source stays in the workspace so you can edit and rebuild it later; "
        "do NOT paste source into this call.\n\n"
        "The bundler inlines everything (an app runs sandboxed, where an "
        "external script, stylesheet or font is blocked). Available to import: "
        "react, react-dom, recharts, lucide-react, date-fns, clsx, tailwind-merge, "
        "and Tailwind v4 via `@import \"tailwindcss\"`. Nothing else — you cannot "
        "add a dependency.\n\n"
        "Inside the app, `cycls.read`/`write` reach files in the app's own folder, "
        "`cycls.get`/`set` are a key-value store, and `cycls.save(name, content)` "
        "asks the user where to put a file anywhere in the workspace.\n\n"
        "On failure the build log comes back — fix the source and call again."
    ),
    "input_schema": {"type": "object", "properties": {
        "slug": {"type": "string",
                 "description": "App folder name under apps/, e.g. `burnup` (lowercase, no spaces)."},
        "source": {"type": "string",
                   "description": "Folder holding the source, e.g. `apps/burnup/src`. Must contain index.html."},
        "name": {"type": "string", "description": "Display name shown in the Apps tab."},
        "icon": {"type": "string", "description": (
            "An emoji, or an image file in the app's folder (e.g. `logo.png`). "
            "Defaults to the first letter of the name.")},
    }, "required": ["slug", "source"]}
}

_SUGGEST_TOOL = {
    "type": "custom",
    "name": "suggest",
    "description": (
        "Offer the user ONE suggested follow-up message — the single most "
        "useful next step, shown as a one-tap chip above the composer. Write "
        "it as a message the user would send (their voice, their language), "
        "short enough to read at a glance.\n"
        "Prefer steps that move the session toward a FINISHED deliverable — "
        "'Turn this into a document', 'Make this a web page' — over "
        "open-ended exploration.\n"
        "Call at most once per turn, as your LAST action, after the answer "
        "is complete. Skip it when you asked the user a question or the turn "
        "already ended in the final artifact."
    ),
    "input_schema": {"type": "object", "properties": {
        "text": {"type": "string", "description": "The follow-up message, in the user's voice and language (aim for under 80 characters)."},
    }, "required": ["text"]}
}

_ASK_MAX_QUESTIONS = 3

_ASK_TOOL = {
    "type": "custom",
    "name": "ask",
    "description": (
        "Ask the user up to 3 questions in ONE call and stop, when you genuinely "
        "cannot pick a sensible default and different answers lead to materially "
        "different work. They appear as a card above the composer where the user "
        "answers and submits; they may also ignore the options and type any reply, "
        "so never say 'choose one of the following'.\n"
        "Batch every question you need into a single call — each call ends your "
        "turn, so asking one at a time costs the user a full round-trip each time.\n"
        "Per question: give 2-4 `options` when the answers are known, each a short "
        "noun phrase with a one-line description of what it means or what happens "
        "if chosen; omit `options` for an open question. Set `multi_select` when "
        "several of that question's answers can hold at once (which formats to "
        "export, which sections to include). Give each question a short `header` "
        "(1-2 words) — it labels the answer when several come back together. "
        "Write everything in the user's language.\n"
        "Call at most once per turn, as your LAST action — the turn ends there and "
        "the user's next message carries the answers. Do NOT call it to confirm "
        "something obvious, to ask permission for work already requested, or when "
        "a careful colleague would just make the call and say so."
    ),
    "input_schema": {"type": "object", "properties": {
        "questions": {"type": "array", "minItems": 1, "maxItems": _ASK_MAX_QUESTIONS,
                      "description": "1-3 questions, asked together on one card.",
                      "items": {
            "type": "object", "properties": {
                "question": {"type": "string",
                             "description": "The question, in the user's language. One sentence."},
                "header": {"type": "string", "description": (
                    "1-2 word label for this answer, in the user's language (e.g. "
                    "'Format', 'Sections'). It is sent verbatim beside the answer "
                    "when several come back together.")},
                "options": {"type": "array", "maxItems": 4, "description": (
                    "2-4 suggested answers. Omit for an open question."), "items": {
                    "type": "object", "properties": {
                        "label": {"type": "string", "description": "The answer, as the user would say it (under 80 chars)."},
                        "description": {"type": "string", "description": "One line on what it means or implies."},
                    }, "required": ["label"]}},
                "multi_select": {"type": "boolean", "description": (
                    "True when the user may pick several of THIS question's options "
                    "at once. Default false (exactly one answer).")},
            }, "required": ["question"]}},
    }, "required": ["questions"]}
}

# Attached to the `Tool` rows below, so enabling a tool is the only switch.

SUGGEST_GUIDANCE = """## Suggested follow-up
After a substantive answer, when there is an obvious next step, call `suggest` with ONE follow-up message. Steer the session toward a completed artifact: prefer the step that turns work-in-progress into a finished document, page, sheet, or app the user keeps — "Turn this into a document", "Make this a web page" — over open-ended exploration. Write it as a message the user would send, in the user's language. Call it at most once, as the last action of your turn — the turn ends there, so say everything you have to say before calling it. Skip it when you asked the user a question, or when the turn already delivered the final artifact and nothing obvious remains."""

ASK_GUIDANCE = """## Asking the user
Call `ask` only when you genuinely cannot resolve a choice from the request, the workspace, or a sensible default, AND the readings lead to materially different work. Make routine judgment calls yourself and say which you made. Do everything that does not depend on the answers first.
Ask once per turn, as the last action of the turn — the turn ends there and the user's next message carries their answers, so never guess and carry on. Put every question you need into that single call (up to 3): each call costs the user a full round-trip, so asking one at a time is worse than asking together. Give each question a short `header` so the answers come back labelled, and set `multi_select` only when several of that question's own answers can genuinely hold at once. The user can ignore your options and type anything, so read their reply as an answer to what you asked, not as a fresh request."""


_BUILTINS = {
    "Bash":     [_BASH_TOOL],
    "Editor":   [_READ_TOOL, _EDIT_TOOL],
    "DataBase": [_DATABASE_TOOL],
    "Canvas":   [_CANVAS_TOOL],
    "Apps":     [_BUILD_APP_TOOL],
    "MiniApp":  [_BUILD_APP_TOOL],   # legacy alias for Apps
    "Suggest":  [_SUGGEST_TOOL],
    "Ask":      [_ASK_TOOL],
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

_TMP_ERROR = ("/tmp is not shared — every bash command gets its own, discarded when it "
              "exits, and the file tools cannot see it. Save into the workspace instead "
              "(relative paths, e.g. report.pdf)")


def _resolve_path(raw_path, workspace):
    ws = pathlib.Path(workspace).resolve()
    # Every other absolute path is silently read as workspace-relative, which
    # turns a /tmp write into a confusing "does not exist" one step later.
    if raw_path == "/tmp" or raw_path.startswith("/tmp/"):
        raise ValueError(_TMP_ERROR)
    # HOME is /workspace in the sandbox, so `~/x` names a workspace file.
    rel = raw_path.removeprefix("~/").removeprefix("/workspace/").lstrip("/")
    path = (ws / rel).resolve()
    if not path.is_relative_to(ws): raise ValueError("path escapes workspace")
    for name in (".db", ".database", ".trash"):
        reserved = ws / name
        if path == reserved or path.is_relative_to(reserved):
            raise ValueError(f"{name}/ is managed by cycls")
    return path

# ---- Tool execution ----

async def _exec_bash(command, cwd, timeout=600, network=False):
    from cycls._app.sandbox import Sandbox
    path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    lang = os.environ.get("LANG", "C.UTF-8")
    # The trash is masked inside /workspace (the model never sees it) and bound
    # beside it, where the rm shim writes; the shims dir goes first on PATH so
    # `rm`/`rmdir` move to the trash instead of unlinking.
    trash_dir = os.path.join(cwd, trash.DIR)
    os.makedirs(trash_dir, exist_ok=True)
    # bwrap can't create bind mount points inside its read-only root (`--ro-bind /
    # /`), so every top-level bind target must already exist on the real fs. The
    # dev-skill mounts below are guarded by `os.path.isdir`; /workspace comes from
    # the volume mount; but /workspace-trash and /opt/cycls-bin are always bound and
    # nothing else creates them — so bwrap dies with "Can't mkdir /workspace-trash:
    # Read-only file system". Pre-create them here (cf. skills.configure, which does
    # the same for /skills/<name>). Best-effort: a read-only container root would
    # only cost the bash tool, not crash the agent.
    for _mnt in ("/workspace-trash", "/opt/cycls-bin"):
        try:
            os.makedirs(_mnt, exist_ok=True)
        except OSError:
            pass
    shims = str(pathlib.Path(__file__).parent / "shims")
    env = {"PATH": f"/opt/cycls-bin:{path}", "LANG": lang,
           "CYCLS_WORKSPACE": "/workspace", "CYCLS_TRASH": "/workspace-trash"}
    sb = (Sandbox()
          .bind(cwd, "/workspace")
          .tmpfs("/workspace/.db")        # cycls state (chat, shares); editor blocks via _resolve_path
          .tmpfs("/workspace/.database")  # agent KV store; same blocking
          .tmpfs("/workspace/.trash")
          .bind(trash_dir, "/workspace-trash")
          .ro_bind(shims, "/opt/cycls-bin")
          .tmpfs("/app")
          .chdir("/workspace")
          .setenv(**env)
          .network(network).timeout(timeout))
    for src, dst in skills.dev_mounts():   # dev skill scripts/templates, read-only
        # a missing mount point would fail every bash command — skip it instead
        if os.path.isdir(dst):
            sb = sb.ro_bind(src, dst)
    # bwrap's own environ stays PATH/LANG; the trash vars reach only the inner shell (--setenv).
    result = await sb.run(["bash", "-c", command], env={"PATH": env["PATH"], "LANG": lang})
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
    for most queries. Key from `BRAVE_API_KEY`; `BRAVE_COUNTRY` and
    `BRAVE_SEARCH_LANG` set deployment-wide defaults the model can override
    per query."""
    key = os.environ.get("BRAVE_API_KEY")
    if not key: return "Error: web search is unavailable (BRAVE_API_KEY not set)."
    query = (inp.get("query") or "").strip()
    if not query: return "Error: query is required."
    count = min(max(int(inp.get("count") or 5), 1), 20)
    params = {"q": query, "count": count}
    for k in ("country", "search_lang"):
        if v := str(inp.get(k) or os.environ.get(f"BRAVE_{k.upper()}") or "").strip().lower():
            params[k] = v
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://api.search.brave.com/res/v1/web/search",
                                  params=params,
                                  headers={"X-Subscription-Token": key, "Accept": "application/json"})
        r.raise_for_status()
        results = ((r.json().get("web") or {}).get("results") or [])[:count]
    except Exception as e:
        return f"Error: web search failed ({e})."
    if not results: return f"No results for {query!r}."
    rows = []
    for x in results:
        url = (x.get("url") or "").strip()
        if not url: continue
        rows.append({
            "title": (x.get("title") or "").strip()[:200],
            "url": url,
            "snippet": " ".join([x.get("description", ""), *x.get("extra_snippets", [])]).strip()[:400],
        })
    if not rows: return f"No results for {query!r}."
    # Two channels: the model reads JSON, the client gets the same rows as a
    # `sources` part. The tool_result IS the JSON, so `to_ui_messages` can
    # rebuild the citations on refetch from the same source of truth the live
    # stream used — one format, both paths, no prose to re-parse.
    return {
        "_model": json.dumps({"query": query, "results": rows}, ensure_ascii=False),
        "_ui": {"type": "sources", "sources": rows},
    }


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
    return {"type": "ui", "action": "open_canvas", "path": rel,
            **_app_identity(path, path.name)}


async def _exec_suggest(inp):
    """No workspace effect — the suggestion drives the client (a one-tap chip
    above the composer). `ack` is what the model reads back (the loop strips
    it before forwarding the event)."""
    text = str(inp.get("text", "")).strip()
    if not text:
        return "Error: suggestion text is empty"
    return {"type": "ui", "action": "suggest", "text": text[:200],
            "ack": "Suggestion offered to the user."}


def _ask_options(raw):
    """Bare strings, blank labels and non-dicts all land on [{label, description?}]."""
    options = []
    for o in (raw or [])[:4]:
        if isinstance(o, str): o = {"label": o}
        if not isinstance(o, dict): continue
        label = str(o.get("label", "")).strip()
        if not label: continue
        opt = {"label": label[:80]}
        if desc := str(o.get("description", "")).strip():
            opt["description"] = desc[:160]
        options.append(opt)
    return options


async def _exec_ask(inp):
    """No workspace effect — the questions drive the client (one card above the
    composer). The turn ends here and the user's next message carries every
    answer. The singular `{question, options, ...}` shape is accepted too:
    models improvise, and pre-plural history still has to replay."""
    raw = inp.get("questions")
    if not isinstance(raw, list):
        raw = [inp] if str(inp.get("question", "")).strip() else []
    questions = []
    for q in raw[:_ASK_MAX_QUESTIONS]:
        if isinstance(q, str): q = {"question": q}
        if not isinstance(q, dict): continue
        text = str(q.get("question", "")).strip()
        if not text: continue
        options = _ask_options(q.get("options"))
        entry = {"question": text[:400], "options": options,
                 "multi_select": bool(q.get("multi_select")) and len(options) > 1}
        if header := str(q.get("header", "")).strip():
            entry["header"] = header[:24]
        questions.append(entry)
    if not questions:
        return "Error: no question given"
    n, dropped = len(questions), max(0, len(raw) - _ASK_MAX_QUESTIONS)
    ack = (f"Asked the user {n} question{'s' if n > 1 else ''}. "
           "End your turn now — their next message is the answer.")
    if dropped:
        ack = (f"Only the first {_ASK_MAX_QUESTIONS} questions were asked ({dropped} "
               f"dropped — the card takes at most {_ASK_MAX_QUESTIONS}). ") + ack
    return {"type": "ui", "action": "ask", "questions": questions,
            # The first question flattened onto the old singular keys: the mobile
            # client ships on its own cadence and reads that shape.
            "question": questions[0]["question"],
            "options": questions[0]["options"],
            "multi_select": questions[0]["multi_select"],
            "ack": ack}


def _app_identity(path, fallback):
    """An app opens under its manifest name and icon, not `index.html`."""
    if path.name != "index.html" or path.parent.parent.name != "apps":
        return {"name": fallback}
    try:
        manifest = json.loads((path.parent / "app.json").read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    name = manifest.get("name")
    icon = manifest.get("icon")
    out = {"name": (name if isinstance(name, str) and name.strip() else
                    path.parent.name.replace("-", " ").replace("_", " ").title())[:60]}
    if isinstance(icon, str) and icon.strip():
        out["icon"] = icon.strip()[:8]
    return out


# The build runs as a deployed Cycls function; override to point at your own.
APP_BUILDER = os.environ.get("CYCLS_APP_BUILDER", "miniapp-build")
_APP_SRC_MAX_FILES = 400
_APP_SRC_MAX_BYTES = 12_000_000
_APP_SLUG_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-_")


def _collect_source(src_dir):
    """Text files under `src_dir`, keyed by relative path. Binaries and dot/
    node_modules folders are skipped — the bundler takes source, not assets."""
    files, total = {}, 0
    for p in sorted(src_dir.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(src_dir).parts
        if any(part.startswith(".") or part == "node_modules" for part in parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        total += len(text.encode())
        if len(files) >= _APP_SRC_MAX_FILES or total > _APP_SRC_MAX_BYTES:
            raise ValueError("source folder is too large to build")
        files["/".join(parts)] = text
    return files


async def _exec_build_app(inp, workspace):
    import cycls

    slug = str(inp.get("slug", "")).strip().lower()
    if not slug or set(slug) - _APP_SLUG_OK:
        return "Error: slug must be lowercase letters, digits, - or _"

    try:
        src_dir = _resolve_path(inp.get("source", ""), workspace)
    except ValueError as e:
        return f"Error: {e}"
    if not src_dir.is_dir():
        return f"Error: {inp.get('source')} is not a folder"

    try:
        files = _collect_source(src_dir)
    except ValueError as e:
        return f"Error: {e}"
    if "index.html" not in files:
        return f"Error: {inp.get('source')} has no index.html"

    try:
        result = await asyncio.to_thread(cycls.remote(APP_BUILDER), files=files)
    except Exception as e:
        return f"Error: the build service is unavailable ({type(e).__name__}: {e})"

    if not result.get("ok"):
        return (f"Build failed: {result.get('error')}\n\n{result.get('log', '')}"[:MAX_OUTPUT]
                + "\n\nFix the source and call build_app again.")

    app_dir = pathlib.Path(workspace) / "apps" / slug
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "index.html").write_text(result["html"], encoding="utf-8")

    manifest_path = app_dir / "app.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            manifest = {}
    except Exception:
        manifest = {}
    if inp.get("name"):
        manifest["name"] = str(inp["name"])[:60]
    if inp.get("icon"):
        manifest["icon"] = str(inp["icon"])[:512]
    manifest.setdefault("name", slug.replace("-", " ").replace("_", " ").title())
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    kb = result["bytes"] / 1024
    out = f"Installed apps/{slug}/index.html ({kb:.0f} KB). It is in the Apps tab."
    if result.get("stray"):
        out += ("\nWARNING: these assets could not be inlined and will be blocked "
                f"when the app runs: {', '.join(result['stray'])}")
    return out


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
        if path.exists():   # an overwrite deletes the old content — keep it recoverable
            trash.trash_path(workspace, str(path.relative_to(pathlib.Path(workspace).resolve())),
                             by="agent", reason="overwrite")
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
# One `Tool` per harness tool. `run(inp, workspace, *, timeout, network)`
# returns the awaitable result, or is None for tools that execute elsewhere
# (web_search runs server-side; it's here only for the UI label). `step(inp)`
# renders the {tool_name, step} line, shared by the live dispatch path and the
# refetch path (to_ui_messages) so they agree.
#
# The flags are facts the loop acts on, so a tool's contract stops being a
# sentence the model is asked to honor. NamedTuple keeps `entry[0]` working.


class Tool(NamedTuple):
    """`once`: one call per batch. `terminal`: a successful call ends the turn.
    `prompt`: guidance appended while the tool is enabled."""
    run: object
    step: object
    once: bool = False
    terminal: bool = False
    prompt: str = ""


def _run_bash(inp, workspace, *, timeout, network):
    t = inp.get("timeout")
    return _exec_bash(inp.get("command", ""), workspace.root, timeout=t / 1000 if t else timeout, network=network)


def _ask_step(inp):
    """First question plus a count of the rest; the singular branch is replayed history."""
    qs = inp.get("questions")
    if isinstance(qs, list) and qs:
        first = qs[0]
        text = first.get("question", "") if isinstance(first, dict) else str(first)
        extra = len(qs) - 1
        return {"tool_name": "Ask", "step": f"{text} (+{extra})" if extra > 0 else text}
    return {"tool_name": "Ask", "step": inp.get("question", "")}


_TOOLS = {
    "bash":       Tool(_run_bash,
                       lambda inp: {"tool_name": "Bash", "step": inp.get("description") or inp.get("command", "")}),
    "read":       Tool(lambda inp, ws, **_: _exec_read(inp, ws.root),
                       lambda inp: {"tool_name": "Reading", "step": inp.get("path", "")}),
    "edit":       Tool(lambda inp, ws, **_: asyncio.to_thread(_exec_edit, inp, ws.root),
                       lambda inp: {"tool_name": "Editing", "step": inp.get("path", "")}),
    "database":   Tool(lambda inp, ws, **_: _exec_database(inp, ws),
                       lambda inp: {"tool_name": "Database",
                                    "step": f"{inp.get('command', '')} {inp.get('key') or inp.get('prefix', '')}".strip()}),
    "canvas":     Tool(lambda inp, ws, **_: _exec_canvas(inp, ws.root),
                       lambda inp: {"tool_name": "Canvas", "step": inp.get("path", "")}),
    "suggest":    Tool(lambda inp, ws, **_: _exec_suggest(inp),
                       lambda inp: {"tool_name": "Suggest", "step": inp.get("text", "")},
                       once=True, terminal=True, prompt=SUGGEST_GUIDANCE),
    "ask":        Tool(lambda inp, ws, **_: _exec_ask(inp), _ask_step,
                       once=True, terminal=True, prompt=ASK_GUIDANCE),
    "build_app":  Tool(lambda inp, ws, **_: _exec_build_app(inp, ws.root),
                       lambda inp: {"tool_name": "Building app", "step": inp.get("slug", "")}),
    "skill":      Tool(lambda inp, ws, **_: skills._exec_skill(inp, ws.root),
                       lambda inp: {"tool_name": "Skill", "step": inp.get("name", "")}),
    "web_search": Tool(lambda inp, ws, **_: _exec_web_search(inp),
                       lambda inp: {"tool_name": "Web Search", "step": inp.get("query", "")}),
    "web_fetch":  Tool(lambda inp, ws, **_: _exec_web_fetch(inp),
                       lambda inp: {"tool_name": "Fetching", "step": inp.get("url", "")}),
}


def tool_prompts(tools_list):
    """Guidance for every enabled tool that ships some, in `tools_list` order —
    so a new tool with guidance never means editing the loop."""
    return [row.prompt for t in (tools_list or [])
            if (row := _TOOLS.get(t.get("name"))) and row.prompt]


def is_terminal(name):
    """Whether a successful call to *name* should end the turn."""
    row = _TOOLS.get(name)
    return bool(row and row.terminal)


_custom_labels = {}


def register_labels(labels):
    """UI step labels for custom tools: name → (input dict → str). Registered
    by LLM.run() so both live steps and the refetch projection render them."""
    _custom_labels.update(labels or {})


def tool_step(name, input):
    inp = input or {}
    entry = _TOOLS.get(name)
    if entry:
        return entry.step(inp)
    if fn := _custom_labels.get(name):
        try:
            return {"tool_name": name, "step": str(fn(inp))}
        except Exception:
            pass
    # No label — show the first string value, like Bash(command).
    step = next((v for v in inp.values() if isinstance(v, str) and v.strip()), "")
    return {"tool_name": name, "step": step if len(step) <= 120 else step[:117] + "..."}


def dispatch(block, workspace, timeout, handlers=None, network=False, seen=None):
    """*block* is a tool_use content block (dict): {type, id, name, input}.
    Returns (step_event_dict, awaitable_result). The step carries the block's
    `id` so the FE can fold it into the `ToolStart`/`ToolArgs` it already showed.

    *seen* is the caller's per-batch set of dispatched `once` tools; omitting
    it (the default) dispatches every block."""
    bid, name, inp = block["id"], block["name"], block.get("input") or {}
    entry = _TOOLS.get(name)
    if entry and entry.once and seen is not None:
        if name in seen:
            # Refused, but still a step and a tool_result — every tool_use keeps its pair.
            return ({"type": "step", "id": bid, **entry.step(inp), "ok": False},
                    asyncio.sleep(0, result=(
                        f"Error: `{name}` was already called this turn and only the first "
                        "call ran. Send everything in a single call.")))
        seen.add(name)
    if entry and entry.run:
        return {"type": "step", "id": bid, **entry.step(inp)}, entry.run(inp, workspace, timeout=timeout, network=network)
    if handlers and name in handlers:
        return {"type": "step", "id": bid, **tool_step(name, inp)}, handlers[name](inp)
    return {"type": "tool_call", "id": bid, "tool": name, "args": inp}, asyncio.sleep(0, result=f"{name} executed")

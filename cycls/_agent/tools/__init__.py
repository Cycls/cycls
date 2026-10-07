"""Tool schemas, execution, and dispatch. Each built-in is stored in Anthropic
API shape (`type` / `name` / `description` / `input_schema`) and registered in
`_BUILTINS`; `build_tools` emits them as-is. User-supplied custom tools come
through `_normalize_tool` (accepts the camelCase `inputSchema` form too)."""
import asyncio, base64, inspect, ipaddress, json, os, pathlib, re, socket, struct, time, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import NamedTuple
from . import pdf, skills
from ..connectors import approval_key
from ..logs import log
from ..state import _exec_database, app_shelf, apps_db
from .. import credentials, spill, trash

TRASH_MOUNT, SHIMS_MOUNT = "/workspace-trash", "/opt/cycls-bin"   # created by the image (Agent._base_run)

MAX_OUTPUT = 2_000_000   # memory ceiling; the loop spills anything large to .tmp/
READ_MAX = 50_000        # chars per read (~25k tokens) — attachments inline through read

_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
_DOC_EXTS = {"pdf"}

_BASH_TOOL = {
    "type": "custom",
    "name": "bash",
    "description": (
        "Execute a shell command in the workspace sandbox.\n\n"
        "Usage:\n"
        "- Working directory is /workspace. Never prefix commands with `cd /workspace`.\n"
        "- Scratch goes in `.tmp/`: downloads, intermediate data, anything "
        "the user should not see in their files — it is hidden and cleaned up. Files the user "
        "keeps go in the workspace root. Never /tmp: every command gets its own, gone when it exits.\n"
        "- Use `rg` or `rg --files` for searching — it's faster than grep.\n"
        "- Use `jq` to extract fields from JSON.\n"
        "- Use the `read` tool (not cat/head/tail) for viewing files.\n"
        "- Use the `edit` tool to create OR modify files — never `cat >`, `echo >`, heredocs, or `sed`/`awk`. Bash for files bypasses safety checks and blows the output-token budget on long content.\n"
        "- Always quote paths containing spaces with double quotes.\n"
        "- Large output is saved to `.tmp/` with a preview — analyse it with jq, rg or python.\n"
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
        "- Returns up to 50,000 characters per call; a longer file ends with the offset to continue from.\n"
        "- When you already know which part of the file you need, use offset and limit to read only that part.\n"
        "- Only reads files, not directories. Use `ls` via bash for directories.\n"
        "- If you need to read a file the user mentioned, always use this tool — assume the path is valid.\n"
        "- It is okay to read a file that does not exist; an error will be returned."
    ),
    "input_schema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Relative path to read (e.g. src/main.py)"},
        "offset": {"type": "integer", "description": "Start line, 1-indexed (default: 1)"},
        "limit": {"type": "integer", "description": "Max lines to read. Omit to read as much as fits."},
        "pages": {"type": "string", "description": "Page range for large PDFs, e.g. '1-5' or '3'. Required for PDFs over 3MB. Max 20 pages."},
    }, "required": ["path"]}
}

_DATABASE_TOOL = {
    "type": "custom",
    "name": "database",
    "description": (
        "Persistent key-value store, PER USER — no other member of the workspace can see it, "
        "and neither can an app. Your own memory across turns and chats: notes, preferences, "
        "task progress. Atomic per-key writes, prefix scans.\n"
        "Anything a teammate or an app must read goes in `apps/<slug>/data/` or a workspace "
        "file instead.\n\n"
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

# Full browser automation, backed by the shared real-Chrome service (see
# cycls/_agent/browser). Enabled by "Browser" in allowed_tools, but only offered
# to the model when the service is configured — else it's silently absent, like
# an unconfigured office-render. The page persists BETWEEN calls in a turn, so
# the model works step by step; it acts on elements by the number `read` prints.
_BROWSER_TOOL = {
    "type": "custom",
    "name": "browser",
    "description": (
        "Drive a REAL web browser for things a plain fetch can't do: pages "
        "behind JavaScript, logins, search boxes, forms, multi-step flows. The "
        "page stays OPEN between calls this turn — work step by step:\n"
        "- open {url}        go to a page\n"
        "- read              get the page text + a NUMBERED list of the "
        "clickable/typable elements\n"
        "- click {ref}       click element number `ref` from the last read\n"
        "- type {ref,text}   type text into element `ref`\n"
        "- press {key}       press a key, e.g. 'Enter'\n"
        "- back              go back\n"
        "- screenshot        save a PNG of the page into the workspace\n"
        "- download {ref|url} save a file the page offers into the workspace — "
        "a download button/link `ref` (from the last read), or a direct file "
        "`url` (uses the page's session, so files behind a login work); then "
        "open it with bash/python (e.g. pandas for .xlsx)\n"
        "- evaluate {script} run JavaScript in the page and get its return value "
        "— for SCRAPING structured data the `read` text truncates (e.g. every row "
        "of a table). `script` is a JS expression or arrow function returning "
        "JSON-serializable data, e.g. "
        "\"[...document.querySelectorAll('table tr')].map(r=>[...r.cells].map(c=>c.innerText))\"\n"
        "Always `read` first to learn the element numbers, then act by number. "
        "After each click/type the page is re-read for you — use the fresh "
        "numbers. Prefer this over web_fetch whenever a site needs interaction "
        "or renders its content with JavaScript."
    ),
    "input_schema": {"type": "object", "properties": {
        "action": {"type": "string",
                   "enum": ["open", "read", "click", "type", "press", "back",
                            "screenshot", "download", "evaluate"],
                   "description": "What to do."},
        "url": {"type": "string", "description": "For `open`/`download`: the full http(s) URL."},
        "ref": {"type": "integer", "description": "For `click`/`type`/`download`: the element number from the last `read`."},
        "text": {"type": "string", "description": "For `type`: the text to enter."},
        "key": {"type": "string", "description": "For `press`: the key, e.g. 'Enter'."},
        "script": {"type": "string", "description": "For `evaluate`: JavaScript returning JSON-serializable data."},
    }, "required": ["action"]}
}

# Visual design (social posts + slides), backed by the shared cycls-design
# service (see cycls/_agent/design). Enabled by "Design" in allowed_tools, but
# only offered when the service is configured — else silently absent, like an
# unconfigured office-render. The model describes a design as a spec; the service
# renders it to an image (shown on the canvas) plus an editable .fig source.
_DESIGN_TOOL = {
    "type": "custom",
    "name": "design",
    "description": (
        "Create a visual design — a social-media post or a slide — and show it to "
        "the user on the canvas. You describe the design; the service renders it to "
        "an image and to an editable design file saved in the workspace.\n\n"
        "Two ways to call:\n"
        "- render {spec, name, format?} — the normal way. `spec` is a JSON design:\n"
        "    {\"size\": [W, H] | \"<preset>\", \"fill\": <paint>, \"nodes\": [ ... ]}\n"
        "  Coordinates are pixels from the top-left. `size` takes a preset name instead of "
        "[W, H]: square 1080×1080, post-portrait 1080×1350, story / reel 1080×1920, "
        "slide / wide 1920×1080, x-post 1600×900, a4-poster 1240×1754 (print-ready at the "
        "default @2x).\n"
        "  A <paint> (any `fill`, or a text `color`) is a solid \"#4f46e5\" OR a "
        "gradient {\"gradient\":[\"#4f46e5\",\"#db2777\"], \"angle\":135} — even stops, "
        "angle 0=→ 45=↘ 90=↓ 135=↙ (or placed stops [[\"#a\",0],[\"#b\",0.6],[\"#c\",1]]). "
        "A glow is a radial gradient: {\"gradient\":[\"#fde68a\",\"#b4530900\"],\"type\":\"radial\","
        "\"center\":[0.7,0.3],\"radius\":0.6} (centre and radius are fractions of the box). "
        "A colour may carry alpha as #rrggbbaa. A gradient background reads far richer "
        "than a flat colour.\n"
        "  Node types (every node needs its `type`):\n"
        "    text    {\"type\":\"text\",\"text\":\"…\",\"x\":,\"y\":,\"w\"?:,\"size\":,"
        "\"font\"?:\"Playfair Display Bold\"|{\"family\":,\"style\":},\"weight\"?:100-900,\"italic\"?:bool,"
        "\"color\":<paint>,"
        "\"align\"?:\"left|center|right\",\"lineHeight\"?:px,\"letterSpacing\"?:px,\"opacity\"?:0-1,"
        "\"h\"?:,\"fit\"?:\"shrink\"}  (with `h`, fit:\"shrink\" steps the size down until it fits the box)\n"
        "    rect    {\"type\":\"rect\",\"x\":,\"y\":,\"w\":,\"h\":,\"radius\"?:,\"fill\":<paint>,"
        "\"stroke\"?:\"#hex\",\"strokeWeight\"?:,\"opacity\"?:,\"shadow\"?:}\n"
        "    ellipse {\"type\":\"ellipse\",\"x\":,\"y\":,\"w\":,\"h\":,\"fill\":<paint>,\"stroke\"?:,\"shadow\"?:}  (a circle when w==h; "
        "only a `stroke` and no `fill` = an outline ring)\n"
        "    line    {\"type\":\"line\",\"x\":,\"y\":,\"w\":,\"h\"?:2,\"fill\":\"#hex\"}  a thin divider\n"
        "    image   {\"type\":\"image\",\"src\":\"attachments/photo.jpg\",\"x\":,\"y\":,\"w\"?:,\"h\"?:,"
        "\"fit\"?:\"cover|contain\",\"radius\"?:,\"opacity\"?:,\"shadow\"?:}\n"
        "    stack   {\"type\":\"stack\",\"x\":,\"y\":,\"w\"?:,\"gap\"?:24,\"direction\"?:\"vertical|horizontal\","
        "\"align\"?:\"start|center|end\",\"anchor\"?:\"top|center|bottom\",\"children\":[nodes without x/y]}\n"
        "    icon    {\"type\":\"icon\",\"name\":\"lucide:rocket\",\"x\":,\"y\":,\"size\":64,\"color\"?:}  any Iconify icon "
        "(sets: lucide, tabler, mdi, ph, heroicons, ri…)\n"
        "    svg     {\"type\":\"svg\",\"src\":\"brand/logo.svg\"|\"svg\":\"<svg…>\",\"x\":,\"y\":,\"w\":,\"h\"?:,\"color\"?:}  a logo or mark\n"
        "    qr      {\"type\":\"qr\",\"text\":\"https://…\",\"x\":,\"y\":,\"size\":240}\n"
        "    line    {\"type\":\"line\",\"from\":[x,y],\"to\":[x,y],\"color\":,\"width\"?:4,\"end\"?:\"arrow\",\"start\"?:\"arrow\"}  "
        "(a connector or pointer; the old x/y/w form is a divider)\n"
        "    list    {\"type\":\"list\",\"items\":[\"…\"],\"marker\"?:\"•|1.|—|none\",\"x\":,\"y\":,\"w\":,\"size\":,\"color\"?:}  "
        "bullets or steps with a hanging indent (right-to-left for Arabic)\n"
        "    chart   {\"type\":\"chart\",\"kind\":\"column|bar|stacked|line|area|pie|donut\",\"x\":,\"y\":,\"w\":,\"h\":,"
        "\"data\":{\"labels\":[…],\"series\":[{\"name\":,\"values\":[…],\"color\"?:}]},\"values\"?:true,"
        "\"prefix\"?:\"$\",\"suffix\"?:\"%\",\"short\"?:true}  real data → a clean chart\n"
        "    table   {\"type\":\"table\",\"x\":,\"y\":,\"w\":,\"columns\":[…],\"rows\":[[…]],\"widths\"?:[fractions],"
        "\"headerFill\"?:,\"zebra\"?:}  rows sized to their text\n"
        "  A text takes \"runs\":[{\"text\":\"Grow \"},{\"text\":\"3×\",\"color\":\"#f59e0b\",\"font\":\"Playfair Display Bold\"}] "
        "instead of `text` for mixed styles in one line. Any node takes `blur`, and `backdropBlur` "
        "(frosted glass: a translucent card, e.g. fill \"#ffffff26\", over a photo). An image takes "
        "shape:\"circle\" (an avatar), `focus`:[x,y] (0–1, what stays in frame when cover crops) and "
        "`crop`:[x,y,w,h] (fractions). Photos up to 15 MB are fine — they're fitted to their box.\n"
        "  A STACK lays its children out one after another, `gap` apart, from their REAL "
        "measured sizes — a headline that wraps to three lines pushes the subtitle down. "
        "Use one for every block of text (eyebrow → headline → subtitle → button): no y to "
        "guess, nothing overlaps. In a vertical stack a text child without `w` wraps to the "
        "stack's width and takes its `align`; `anchor`:\"bottom\" makes `y` the stack's "
        "bottom edge (a caption block over a photo). A stack of text, shapes and photos stays "
        "ONE block named by its `id`: `move` or `duplicate` it by that name, and a line edited "
        "longer pushes the rest down, in the editor too. Give any node an `id` (\"headline\") "
        "— it's the node's name in the file, for edits and the layout check.\n"
        "  An image is a PNG / JPEG / WebP / GIF already IN the workspace (an upload, a stock "
        "photo you saved, brand/logo.png) — `src` is its path; save a web image to the workspace "
        "first. Or NAME a photo to find: \"stock\":\"coffee beans on wood\" in place of `src` "
        "(a deck slide's image: {\"stock\":\"…\"}) — a stock photo is found, saved to "
        "attachments/stock/ and credited in the result; `pick`:1 takes the next one. `cover` (default) fills the w×h box and crops the overflow; `contain` fits the "
        "whole image inside it (logos). Give w, h or both — a missing one follows the image's "
        "aspect. A full-bleed photo background = an image at 0,0 the frame's size FIRST in "
        "`nodes`, then a SCRIM behind where the text sits — a rect whose gradient fades from "
        "transparent to dark, e.g. fill {\"gradient\":[\"#00000000\",\"#000000cc\"],\"angle\":90} "
        "over the lower half (no hard edge across the photo) — and text with an explicit light "
        "`color` on top; the auto text colour only knows the frame's fill, not a photo. "
        "A round avatar = a square image with radius = w/2.\n"
        "  `shadow` is true or {\"blur\":40,\"y\":16,\"opacity\":0.25,\"color\"?,\"x\"?,\"spread\"?} "
        "— a drop shadow that lifts a card or button off the background.\n"
        "  DESIGN — make it look intentional, not a wireframe: one clear idea, a strong "
        "hierarchy (a big bold headline 72–120px, a small letter-spaced eyebrow ~24px "
        "with letterSpacing 4–6, a muted subtitle ~32px), a tight palette (a gradient "
        "or one background colour + white / near-white text + ONE accent), generous "
        "margins (~8–10% of the width), and a touch of depth (a shadow on the button or "
        "a card, or a big soft low-opacity ellipse bleeding off an edge for flair). "
        "A pill button = a rect with radius = h/2 and centered text.\n"
        "  FONTS: any Google Font by its exact family name plus a style — \"Playfair Display "
        "Bold\", \"DM Sans Medium\", \"Montserrat Extra Bold Italic\", \"Bebas Neue\" — or "
        "{\"family\":\"Poppins\",\"style\":\"Semi Bold\"}; `weight` and `italic` work too; the "
        "default is Inter. Pair a characterful headline face (a serif or display font) with a "
        "clean sans for body copy. Arabic text needs an Arabic font — Cairo, Tajawal, Almarai, "
        "IBM Plex Sans Arabic, Amiri, Noto Kufi Arabic, Readex Pro; any other face falls back "
        "to Noto Naskh Arabic. Arial / Helvetica / Times are swapped for their open twins. A "
        "font that doesn't exist is an error; a weight the family lacks falls back to Regular "
        "— the result tells you either way.\n"
        "  BRAND: if the workspace has a brand kit (brand/brand.yaml), what you leave out comes "
        "from it: a background `fill` → the brand primary, a shape `fill` → the accent, a text "
        "`font` → the brand heading face (display sizes, ≥48px) or body face — or write the "
        "brand's colours and fonts yourself. Text with no `color` gets white or near-black, "
        "whichever reads on its background.\n"
        "  LAYOUT: put text blocks in a stack. Text outside one needs room to WRAP — "
        "give any multi-word text a `w` and put the next node below the whole wrapped "
        "block. Every render comes back with a LAYOUT CHECK (overlapping text, text off or "
        "crowding an edge, text too small, low contrast on what's behind it) — fix what "
        "it lists before you present.\n"
        "  RTL: for Arabic / Hebrew set text `align`:\"right\" and give it a `w`, then "
        "ANCHOR it to the right margin — place the box so its right edge (`x`+`w`) sits "
        "inside the frame (`x` ≈ frameW − margin − `w`), NOT at the small `x` you'd use "
        "for left-aligned English (that runs the text off the right edge). Shaping, bidi "
        "(mixed digits / Latin) and diacritics are automatic, so write the text naturally "
        "— but skip `letterSpacing` on Arabic.\n"
        "- A presentation DECK: pass a deck of LAYOUTS — the normal way. You fill each slide's "
        "slots; the service lays them out, so every slide shares margins, title position, type "
        "scale, footer and page numbers, and nothing is placed by hand:\n"
        "    {\"deck\": {\"theme\": \"editorial\", \"footer\"?: {\"text\": \"Brewly · Seed 2026\"}, \"slides\": [\n"
        "      {\"layout\": \"title\", \"eyebrow\"?:, \"title\":, \"subtitle\"?:, \"meta\"?:, \"image\"?: \"attachments/hero.jpg\", \"notes\": \"…\"},\n"
        "      {\"layout\": \"bullets\", \"title\":, \"bullets\": [\"…\"], \"image\"?:, \"notes\": \"…\"}, … ]}}\n"
        "  Layouts and slots: title {eyebrow?, title, subtitle?, meta?, image? (full-bleed), align?:\"center\"} · "
        "section {number?, title, subtitle?} · agenda {title, items} · bullets {eyebrow?, title, subtitle?, "
        "bullets, image?} · two-column {title, left:{heading?, text|bullets}, right:{…}} · image-left / "
        "image-right {eyebrow?, title, text|bullets, image} · image {image, title?, caption?} (full-bleed "
        "photo) · quote {quote, author?, role?, image?} · stats {eyebrow?, title?, items:[{value, label}] "
        "(1–4)} · timeline {title, items:[{date, title, text?}] (2–6)} · table {title, columns, rows, "
        "caption?} · chart {title, chart:{kind, data, …chart keys}, caption?, takeaway?:{value?, text}} · "
        "team {title, people:[{name, role?, photo?}] (≤8)} · closing {title, subtitle?, cta?, contact?, "
        "qr?:\"https://…\"} · poll {question, options (2–6)} (a LIVE poll: when the deck is "
        "presented the audience votes from their phones — the presenter shows a join QR — and the bars "
        "fill live; exports show the empty poll) · custom {nodes, fill?} (a hand-built slide, for what no "
        "layout fits). Every "
        "slide also takes notes, transition, id. Images are workspace paths.\n"
        "  Themes: minimal-light, minimal-dark, bold-gradient, editorial, corporate, tech-dark, warm, mono, "
        "\"brand\" (the workspace brand kit — the default when one exists), or overrides on a base: "
        "{\"base\":\"minimal-dark\",\"accent\":\"#f59e0b\",\"heading\":\"Sora Bold\"}. An Arabic slide is laid out "
        "right-to-left and an English one left-to-right, automatically; a slide mixing both (an Arabic "
        "headline over English bullets) follows the deck's `dir` — set \"dir\":\"rtl\" on an "
        "Arabic-first bilingual deck (else the language with more words decides). Keep slide text short — titles shrink to fit their place, "
        "and the layout check names anything that still doesn't fit.\n"
        "- A deck of hand-built frames (or a carousel), when you need full control:\n"
        "    {\"frames\": [ {\"size\":\"slide\", \"fill\":…, \"nodes\":[…], \"id\"?:\"cover\", "
        "\"title\"?:\"Cover\", \"notes\"?:\"what the presenter says\", \"transition\"?:\"fade|slide|none\"}, … ]}\n"
        "  one object per slide, every slide the SAME size. format \"pptx\" is one PowerPoint "
        "file — each slide's speaker `notes` and `transition` are written into it, and its text, "
        "rects, ellipses and lines stay editable there, charts and tables are PowerPoint's own "
        "(their data edits there), Arabic keeps its side (gradients, icons, SVG, photos and "
        "blurs become pictures, one element each; decor bleeding off a slide "
        "is cropped by the slide in the show). \"pdf\" is one page per slide, its words searchable. png / jpg / webp "
        "save every slide as its own image, <name>-slide-1, -slide-2 … (an Instagram carousel). "
        "Write notes for a talk deck. Every slide comes back to you to QA.\n"
        "  PAGES — one design, several VARIANTS of the same piece of work (a post, a story and a "
        "banner of one campaign; a light and a dark version): spec = {\"pages\":[{\"name\":\"Post\","
        "\"size\":\"square\",\"fill\":…,\"nodes\":[…]}, {\"name\":\"Story\",\"size\":\"story\",…}]} — each page "
        "a design of its own (its own size; or {\"name\", \"frames\":[…]} for a carousel), under a "
        "name no other page has. It is ONE file (designs/<name>.fig) whose pages the user switches "
        "between in the editor, previews and downloads one at a time; each page's image is saved "
        "too (<name>.png the first, then <name>-page-2.png, -page-3 …). Use pages when the user "
        "asks for the same thing in several formats or versions — not separate renders, and not "
        "for a deck's slides (those are `frames` / a `deck`). Lay each page out for ITS size: "
        "never the same coordinates on another shape.\n"
        "  A DOCUMENT — a report, a proposal, a white paper, a guide, a brochure, a CV: anything that "
        "is read on paper-sized pages and comes out as a PDF — is spec = {\"document\": {\"title\", "
        "\"subtitle\"?, \"author\"?, \"date\"?, \"organization\"?, \"size\"?: \"a4\"|\"letter\"|\"a5\" "
        "(\"landscape\": true), \"theme\"?, \"cover\"?: {\"style\": \"full\"|\"band\"|\"minimal\"|\"split\"|\"type\", "
        "\"eyebrow\"?, \"image\"?}, \"openers\"?: \"plain\"|\"band\", \"sections\": [{\"title\", \"blocks\": […]}], \"back\"?: {\"title\", "
        "\"text\", \"contact\"}}}. You write the CONTENT, in order; the pages make themselves: text flows "
        "from page to page, a heading never ends a page, the contents page, running header and page "
        "numbers are added. A block is {\"<kind>\": …}: \"lead\" (the opening paragraph) · \"p\" (or a "
        "bare string; takes **bold**, *italic*, [links](https://…)) · \"h2\" · \"h3\" · \"bullets\" / "
        "\"numbered\": [..] · \"callout\": {title?, text, tone?} · \"quote\" + \"by\" · \"stats\": "
        "[{value, label}] · \"chart\": {kind, data} + \"title\", \"caption\" · \"table\": {columns, rows} + \"title\" "
        "/ \"caption\" · \"image\": \"path\" (or {\"stock\": \"query\"}) + \"caption\" — a photo is cropped "
        "to a band, a diagram or screenshot shown whole (\"fit\": \"cover\"|\"contain\" to say) · "
        "\"columns\": [[blocks],[blocks]] · "
        "\"cards\": [{icon?, title, text}] · \"pairs\": [[label, value]] · \"note\" (a source) · "
        "\"nodes\": [spec nodes] + \"h\" (a hand-built area) · \"break\". A `p` takes \"aside\": a short "
        "note in the margin beside it — and an h2 / h3 takes it at the far end of its line (a role's dates: "
        "{\"h3\": \"Lead designer — Brewly\", \"aside\": \"2021 – now\"}); a key a block doesn't read is said "
        "in the reply, not kept; `[^key]` in any text cites the document's \"footnotes\": {key: text} "
        "(numbered, set at the end of the section); \"numbering\": true numbers figures and tables; a chart "
        "or table can read a workspace spreadsheet instead of carrying its data — \"chart\": {kind, "
        "\"from\": \"data/sales.csv\", x?, y?: [columns]} · \"table\": {\"from\": \"data/sales.csv\", columns?, "
        "limit?} (.csv, .tsv, .xlsx). A section opens a new page, or runs on under a few lines left over "
        "(\"break\": \"page\" forces one, \"none\" never). Write it as a real document: "
        "open each section with what it found, real numbers, a caption on every chart and table, short "
        "paragraphs. The LOOK is yours to choose unless the user says: the workspace brand kit when "
        "there is one (the default), else a theme that fits the subject — and its accent or fonts "
        "overridden ({base, accent, heading, body}) when that fits better. The cover sets the tone: "
        "\"full\" (the theme's dark colour — or a photo, \"image\" — the title at the foot), \"split\" (the "
        "title on a dark panel beside a full-height photo), \"type\" (the whole page in the accent, the "
        "title large: no photo needed), \"band\", \"minimal\" (quiet: a letterhead, a legal paper); and "
        "\"openers\": \"band\" opens each section on a band of the dark colour — for a report meant to "
        "look designed, where \"plain\" is the sober choice. It saves designs/<name>.pdf "
        "and opens in the page viewer; every page comes back to you to QA (past twelve pages: the first "
        "four to read, the rest small on contact sheets — look at how each is laid out). A small fix on one page is "
        "an `edit` (ops with `frame`: the page, from 0). Anything that changes the length is made on the "
        "document itself, and only the part that changes is sent: update_section {name, number, section: "
        "{title?, blocks?}} · add_section {name, section, at?} · move_section {name, number, to} · "
        "delete_section {name, number} · update_document {name, document: {title?, theme?, cover?, …}} — "
        "`inspect` lists its sections; it is rendered again in place (the earlier version is kept). Or "
        "the whole render again with \"replace\": true. Never a new name for a change. If the user edited "
        "its pages by hand since the last render, the tool says what they changed instead of rendering: keep "
        "their wording in what you send, tell them what can't be kept, then repeat with \"discard_edits\": true. "
        "A one-page CV, a letter, an invoice, a brief has no cover page: \"cover\": false — its title heads "
        "page 1 (\"kind\": a small label over it; \"meta\": a line under it, e.g. contact details), sections "
        "run on under compact headings, and a few lines too many for the page are set a little tighter to fit. "
        "When it must fit a number of pages — a one-page CV — say \"max_pages\": 1: its type is set smaller, "
        "down to 85%, until it does, and the reply says if even that isn't enough (then cut content, once).\n"
        "- extract {path, name?} — an EXISTING PDF taken apart to be redesigned: its text page by page "
        "(in reading order, its tables as they are laid out; a long one a few pages at a time — the reply "
        "says how to read on: \"pages\": \"5-12\"), and its pictures saved into "
        "designs/<name>-assets/ to use again; then write it as a document. A chart or diagram drawn in "
        "the PDF is not among its pictures: extract {path, page: N} shows that page, and with "
        "\"area\": [left, top, width, height] (parts of the page, 0 to 1) cuts the figure out and saves it. "
        "A scan, or text the reply says can't be trusted, is read from its pages the same way.\n"
        "- script {script, name, format?} — escape hatch: a raw OpenPencil / Figma "
        "plugin-API script for what the spec can't express. It MUST end with "
        "`console.log('__FRAME__'+frame.id)` naming the frame to export.\n"
        "- Change a DECK's slides (name = the deck): add_slide {name, slide, at?} · update_slide {name, "
        "number, slide} (rebuild it — take its layout `source` from inspect and change what you need) or "
        "{name, number, notes?|title?|transition?} · move_slide {name, number, to} · duplicate_slide "
        "{name, number} · delete_slide {name, number}. Slides are numbered from 1; a new slide takes the "
        "deck's theme and footer, and page numbers follow any change. Use these — not a re-render — to "
        "change a deck's structure; `edit` ops still tweak nodes on a slide.\n"
        "- inspect {name, page?} — the design's frames and every node by name (its `id`, else "
        "text-1, rect-2…), with its box, text, font and colour. Do this before an edit you "
        "can't name from the spec you wrote. A design with several pages lists them, and shows "
        "ONE: `page` (its name), the first when you give none. A message that carries "
        "\"[Selected in designs/<name>.fig › <frame>: <node> (<type>), …]\" is the person "
        "pointing: \"this\" / \"the selection\" means those nodes — edit them by those names "
        "(\"[… page \"Story\" › …]\" says which page they are on: pass it as `page`).\n"
        "- edit {ops, name, page?, intent?} — change a design you rendered (designs/<name>.fig) with "
        "named operations, applied in order: "
        "[{\"op\":\"set_text\",\"node\":\"headline\",\"text\":\"New\"}, "
        "{\"op\":\"style\",\"node\":\"headline\",\"color\":\"#f5a623\",\"font\":\"Playfair Display Bold\"}, "
        "{\"op\":\"move\",\"node\":\"cta\",\"dy\":40}, {\"op\":\"add\",\"node\":{…a spec node…}}] — "
        "the full list is in the `ops` field. Ops paint, set fonts and lay out exactly as a "
        "render does. The edit is applied to the saved design first: a node that doesn't "
        "exist is an error listing the ones that do, and nothing changes; on success the "
        ".fig is saved, its image re-exported, and the edited design comes back to you to "
        "check, with a layout check. If the design is open, the user WATCHES a labeled "
        "'Super' cursor replay the change live — pass a short `intent` ('making the "
        "headline gold') shown on it. Use `edit` to tweak a design ('bigger headline', "
        "'move the button down'); `render` to CREATE one. A chart's or table's DATA (values, "
        "labels, rows) changes by rebuilding it — update_slide with the new data, or a new render "
        "— never by moving its bars one by one (that chart then goes into PowerPoint as shapes). "
        "`name` is the design's base name "
        "(e.g. `launch`). An edit is made on ONE page — `page`, the first when absent; the same "
        "node name on another page is another node. Page ops (in `ops`) change the pages "
        "themselves: page_add {name, spec} (a new variant, `spec` as in render), page_duplicate "
        "{page?, name?} (a copy to restyle — the ops after it in the same edit land on the copy), "
        "page_rename {page?, name}, page_delete {page?}.\n"
        "  For what ops can't do, `edit` also takes a raw `script` instead: a Figma "
        "plugin-API snippet mutating the document (figma.currentPage.findOne(…)); set "
        "`figma.currentPage.selection` to what you change. Fonts there are "
        "{family:'Poppins',style:'Semi Bold'} (spaced style names); `textAlignHorizontal` "
        "follows the text's direction (on Arabic 'LEFT' is the right side).\n\n"
        "`format` is png (default), jpg, webp, svg, pptx (PowerPoint) or pdf — pptx or pdf "
        "for a deck. `name` is the file base name, e.g. `launch`. The render opens on the "
        "canvas; the editable `.fig` is saved beside it for later edits. Every render "
        "also comes back to YOU as an image (a deck: every slide) — look at it and "
        "fix what's off before you present it. A fresh "
        "`render`/`script` NEVER overwrites an earlier design — if the name is taken "
        "it gets a numeric suffix (`launch-2`); to CHANGE an existing design use `edit`."
    ),
    "input_schema": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["render", "script", "edit", "inspect", "add_slide", "update_slide", "move_slide", "duplicate_slide", "delete_slide",
                                              "add_section", "update_section", "move_section", "delete_section", "update_document", "extract"],
                   "description": "`render` a JSON spec (normal), run a raw `script` (escape hatch), `inspect` a rendered design (its frames and named nodes; a document's sections), `edit` it (checked, saved, replayed live in the editor), change a deck's slides: add_slide / update_slide / move_slide / duplicate_slide / delete_slide, change a document: add_section / update_section / move_section / delete_section / update_document, or `extract` an existing PDF's text and pictures."},
        "section": {"type": "object", "description": "For add_section / update_section: the section {title, blocks: […]}. update_section takes just the keys that change — {blocks} rewrites it, {title} renames it."},
        "document": {"type": "object", "description": "For update_document: the document's own keys that change — title, subtitle, author, date, theme, cover, size, footnotes, numbering… (null removes one). Not its sections."},
        "path": {"type": "string", "description": "For `extract`: the PDF in the workspace, e.g. attachments/report.pdf."},
        "page": {"type": ["string", "integer"], "description": "For `inspect` / `edit` on a design with several pages: the page's name (default: the first page). For `extract`: the PDF's page to look at, a number from 1."},
        "area": {"type": "array", "items": {"type": "number"}, "description": "For `extract` with `page`: the part of that page to cut out and save as a picture — [left, top, width, height], each a part of the page from 0 to 1."},
        "pages": {"type": ["string", "integer"], "description": "For `extract`: read on in a long PDF — the pages whose text to show, e.g. \"5-12\" (the reply says which are left)."},
        "replace": {"type": "boolean", "description": "For `render` of a document: re-render it under the SAME name (after changing its content) instead of making a new one; the earlier version is kept in its history."},
        "discard_edits": {"type": "boolean", "description": "For a document's re-render (`replace`, or a section action) after the tool said its pages were edited by hand since the last render: true once those edits are accounted for — their wording put into what you send, the user told what can't be kept."},
        "slide": {"type": "object", "description": "For add_slide / update_slide: the slide — a layout slide {layout, …slots, notes?} laid out with the deck's own theme and footer, or a hand-built one {nodes, fill?}. update_slide replaces the slide whole: start from its `source` in inspect and change what you need."},
        "number": {"type": "integer", "description": "For update_slide / move_slide / duplicate_slide / delete_slide: the slide's number, from 1. For update_section / move_section / delete_section: the section's."},
        "to": {"type": "integer", "description": "For move_slide / move_section: the position it moves to, from 1."},
        "at": {"type": "integer", "description": "For add_slide / add_section: the position of the new one, from 1 (default: the end)."},
        "notes": {"type": "string", "description": "For update_slide without `slide`: the slide's new speaker notes (also `title`, `transition`)."},
        "title": {"type": "string", "description": "For update_slide without `slide`: the slide's title (its name in the deck viewer)."},
        "transition": {"type": "string", "enum": ["fade", "slide", "none"], "description": "For update_slide without `slide`: how the slide enters when presented."},
        "ops": {"type": "array", "items": {"type": "object"},
                "description": "For `edit`: operations by node name (see `inspect`), applied in order — set_text {node,text}; style {node, color?, fill?, font?, size?, weight?, italic?, opacity?, radius?, align?, letterSpacing?, lineHeight?, stroke?, strokeWeight?}; move {node, x?, y?, dx?, dy?} (a stack's id moves the whole block; a node in a stack moved on its own leaves it); resize {node, w?, h?}; delete {node}; duplicate {node, dx?, dy?, id?} (in a stack, the copy is its next item); replace_image {node, src}; add {node:<spec node>, frame?}; background {fill, frame?} — the slide's OWN fill: a colour, {\"gradient\": [...]} or \"none\" (a slide isn't a node `style` can name — never cover it with a full-size rect). `frame` (slide index from 0) narrows a name to one slide. Pages: page_add {name, spec}; page_duplicate {page?, name?}; page_rename {page?, name}; page_delete {page?}."},
        "spec": {"type": "object", "description": "For `render`: a single design {size, fill, nodes}; several variants of one design as pages {pages:[{name, size, fill, nodes}]}; a document (a report or any PDF that flows over pages) {document:{title, sections:[{title, blocks:[…]}]}}; a presentation as a deck of layouts {deck:{theme, footer?, slides:[{layout, …slots, notes}]}} (the normal way for decks); or hand-built frames {frames:[...]} (one per slide, all one size, each with optional id/title/notes/transition; export pptx or pdf, or png for a carousel); size is [W,H] or a preset (square, post-portrait, story, reel, slide, wide, x-post, a4-poster). Nodes are text/rect/ellipse/line/image/stack (image `src` = a workspace file; a stack lays out `children` from their measured sizes); a fill or text color is a solid \"#hex\" or a gradient {gradient:[...],angle}; nodes take opacity, shadow, and shapes take stroke/strokeWeight."},
        "script": {"type": "string",
                   "description": "For `script`: a Figma plugin-API script ending in console.log('__FRAME__'+id). For `edit`: a snippet mutating the open doc that also sets figma.currentPage.selection to the changed node(s). Scripts may use only `figma` (and `console`): no `this`, globals, network, eval/Function or `.constructor` — anything else is refused before it runs."},
        "intent": {"type": "string",
                   "description": "For `edit`: a short label of the change (e.g. 'making the headline gold') shown on the live 'Super' cursor."},
        "name": {"type": "string", "description": "Output file base name, e.g. `launch` (lowercase, no extension)."},
        "format": {"type": "string", "enum": ["png", "jpg", "webp", "svg", "pptx", "pdf"],
                   "description": "Output format (default png). A deck: pptx (PowerPoint, with speaker notes) or pdf; png for a carousel (one image per slide)."},
        "scale": {"type": "integer", "description": "Raster scale for png/jpg/webp (default 2 = @2x)."},
    }, "required": ["action"]}
}

_BUILD_APP_TOOL = {
    "type": "custom",
    "name": "build_app",
    "description": (
        "Bundle a source folder into one self-contained HTML file and install it as an app the "
        "user opens from the Apps tab. Write the source with the editor first — `index.html` is the "
        "entry — and pass the folder; never paste source here. It stays, so you can rebuild.\n"
        "Everything is inlined under a CSP: no external script or font, and the app cannot fetch. "
        "React 19.2.8 (`createRoot`), Tailwind v4 via `@import \"tailwindcss\"`, and: "
        "@base-ui/react, @dnd-kit/core, @dnd-kit/modifiers, @dnd-kit/sortable, @dnd-kit/utilities, @hookform/resolvers, @radix-ui/react-slot, @tanstack/react-table, @tanstack/react-virtual, class-variance-authority, clsx, cmdk, date-fns, embla-carousel-react, input-otp, lucide-react, motion, radix-ui, react-day-picker, react-dom, react-hook-form, recharts, sonner, tailwind-merge, tailwind-variants, tw-animate-css, vaul, zod. "
        "Nothing else — you cannot add a dependency.\n"
        "In the app: `cycls.read`/`write` reach `data/` in its own folder, `cycls.get`/`set` are a "
        "key-value store there, `cycls.save(name, content)` asks where to put a file anywhere, and "
        "`await cycls.connector(name).json(path, init)` calls a connected connector's REST API with "
        "the credential attached server-side — so a dashboard stays live and holds no key. Never put "
        "an API key in app source.\n"
        "On failure the build log comes back."
    ),
    "input_schema": {"type": "object", "properties": {
        "slug": {"type": "string", "description": "Folder under apps/, lowercase, e.g. `burnup`."},
        "source": {"type": "string", "description": "Folder holding the source, e.g. `apps/burnup/src`."},
        "name": {"type": "string", "description": "Display name in the Apps tab."},
        "description": {"type": "string", "description": "One line on what it is for; a later session reads this."},
        "icon": {"type": "string", "description": "An emoji, or an image file in the app's folder."},
    }, "required": ["slug", "source"]}
}


_SUGGEST_TOOL = {
    "type": "custom",
    "name": "suggest",
    "description": (
        "Offer ONE follow-up message as a one-tap chip above the composer, written as the "
        "user would send it."
    ),
    "input_schema": {"type": "object", "properties": {
        "text": {"type": "string", "description": "The follow-up, in the user's voice and language. Under 80 characters."},
    }, "required": ["text"]}
}

_ASK_MAX_QUESTIONS = 3

_ASK_TOOL = {
    "type": "custom",
    "name": "ask",
    "description": (
        "Ask the user up to 3 questions on one card above the composer, and stop. "
        "They can ignore the options and type anything, so never write 'choose one "
        "of the following'. Everything in the user's language."
    ),
    "input_schema": {"type": "object", "properties": {
        "questions": {"type": "array", "minItems": 1, "maxItems": _ASK_MAX_QUESTIONS,
                      "description": "1-3 questions, asked together on one card.",
                      "items": {
            "type": "object", "properties": {
                "question": {"type": "string", "description": "One sentence."},
                "header": {"type": "string", "description": "1-2 words labelling the answer, e.g. 'Format'."},
                "options": {"type": "array", "maxItems": 4,
                            "description": "2-4 answers. Omit for an open question.", "items": {
                    "type": "object", "properties": {
                        "label": {"type": "string", "description": "The answer, as the user would say it."},
                        "description": {"type": "string", "description": "One line on what it implies."},
                    }, "required": ["label"]}},
                "multi_select": {"type": "boolean",
                                 "description": "Several of THIS question's options can hold at once."},
            }, "required": ["question"]}},
    }, "required": ["questions"]}
}

# Attached to the `Tool` rows below, so enabling a tool is the only switch.

SUGGEST_GUIDANCE = """## Suggested follow-up
After a substantive answer with an obvious next step, call `suggest` once, as the last action of the turn — it ends there, so say everything first. Steer toward a finished artifact the user keeps ("Turn this into a document", "Make this a web page") over open-ended exploration. Skip it when you asked a question, or when the turn already delivered the artifact."""

ASK_GUIDANCE = """## Asking the user
Call `ask` only when you cannot resolve a choice from the request, the workspace or a sensible default, AND the readings lead to materially different work — not to confirm the obvious or to ask permission for work already requested. Make routine calls yourself and say which you made; do everything that does not depend on the answers first.
Ask once per turn, as the last action: the turn ends there and the user's next message carries the answers. Put every question into that one call — each costs a full round-trip. Read their reply as an answer to what you asked, not as a fresh request."""


_BUILTINS = {
    "Bash":     [_BASH_TOOL],
    "Editor":   [_READ_TOOL, _EDIT_TOOL],
    "DataBase": [_DATABASE_TOOL],
    "Canvas":   [_CANVAS_TOOL],
    "Apps":     [_BUILD_APP_TOOL],
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
        elif name == "Browser":
            # Only offered when the shared browser service is wired — else the
            # tool is silently absent, exactly like an unconfigured office-render.
            from cycls._agent import browser as _browser
            if _browser.configured():
                tools.append(_BROWSER_TOOL)
        elif name == "Design":
            # Same gate as Browser: only offered when the cycls-design service is
            # configured (DESIGN_URL), else silently absent.
            from cycls._agent import design as _design
            if _design.configured():
                tools.append(_DESIGN_TOOL)
        elif name in _BUILTINS:
            tools += _BUILTINS[name]
        else:
            # A package's tools (cycls.Extension) — absent while it isn't configured.
            from .. import extension
            tools += extension.schemas(name)
    tools += [_normalize_tool(t) for t in (custom or [])]
    return tools

_TMP_ERROR = ("/tmp is not shared — every bash command gets its own, discarded when it "
              "exits, and the file tools cannot see it. Use .tmp/ for scratch and the workspace "
              "root for files the user keeps")


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
    for name in (".db", ".database", ".trash", ".versions", ".settings", credentials.USER, credentials.SHARED):
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
    shims = str(pathlib.Path(__file__).parent / "shims")
    env = {"PATH": f"{SHIMS_MOUNT}:{path}", "LANG": lang,
           "CYCLS_WORKSPACE": "/workspace", "CYCLS_TRASH": TRASH_MOUNT}
    sb = (Sandbox()
          .bind(cwd, "/workspace")
          .tmpfs("/workspace/.db")        # cycls state (chat, shares); editor blocks via _resolve_path
          .tmpfs("/workspace/.database")  # agent KV store; same blocking
          .tmpfs("/workspace/.trash")
          .tmpfs("/workspace/.versions")   # a design's earlier versions (cycls/_agent/versions.py)
          .tmpfs(f"/workspace/{credentials.USER}")
          .tmpfs(f"/workspace/{credentials.SHARED}")
          .tmpfs("/workspace/.settings")  # the person's tool settings: bash must not grant itself "allow"
          .bind(trash_dir, TRASH_MOUNT)
          .ro_bind(shims, SHIMS_MOUNT)
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
    text = "\n".join(f"{i:6}\t{l[:2000]}" for i, l in enumerate(sliced, start))
    if len(text) <= READ_MAX: return text
    text = text[:text.rfind("\n", 0, READ_MAX)]
    nxt = start + text.count("\n") + 1
    return f"{text}\n\n[Stopped at line {nxt - 1} of {len(lines)}. Continue with offset={nxt}.]"

async def _exec_canvas(inp, workspace):
    """Resolve + validate the path, then return a UI event the loop forwards to
    the client to open the canvas. The model gets a short ack (see the loop)."""
    raw = inp.get("path", "")
    try: path = _resolve_path(raw, workspace)
    except ValueError as e: return f"Error: {e}"
    if not path.exists(): return f"Error: {raw} does not exist"
    if path.is_dir(): return f"Error: {raw} is a directory"
    rel = raw.removeprefix("/workspace/").lstrip("/")
    if path.relative_to(pathlib.Path(workspace).resolve()).parts[:1] == (spill.DIR,):
        return f"Error: {spill.DIR}/ is scratch that may be deleted — write the deliverable elsewhere and open that"
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
APP_BUILDER = os.environ.get("CYCLS_APP_BUILDER", "app-build")
_APP_SRC_MAX_FILES = 400
_APP_SRC_MAX_BYTES = 12_000_000
_APP_SRC_MAX_FILE = 2_000_000    # the builder's cap, mirrored so it fails here naming the file
_APP_BUILD_TIMEOUT = 420         # seconds — the build function itself is killed at 300+120
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
        size = len(text.encode())
        if size > _APP_SRC_MAX_FILE:
            raise ValueError(f"{'/'.join(parts)} is {size // 1000} KB; the limit is "
                             f"{_APP_SRC_MAX_FILE // 1_000_000} MB per file — split it")
        total += size
        if len(files) >= _APP_SRC_MAX_FILES or total > _APP_SRC_MAX_BYTES:
            raise ValueError("source folder is too large to build")
        files["/".join(parts)] = text
    return files


_APPS_TTL = 30.0
_apps_cache = {}   # root -> (deadline, text)


def app_catalog(root):
    """One line per app, so the model knows they exist without a scan per turn."""
    hit = _apps_cache.get(root)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    lines = []
    try:
        for d in sorted((pathlib.Path(root) / "apps").iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            try: m = json.loads((d / "app.json").read_text(encoding="utf-8"))
            except Exception: m = {}
            m = m if isinstance(m, dict) else {}
            desc = str(m.get("description") or "").strip()[:100]
            lines.append(f"- {d.name}: {m.get('name') or d.name}" + (f" — {desc}" if desc else ""))
    except OSError:
        pass
    text = ("## Apps in this workspace\n"
            "Their data is in apps/<slug>/data/. Read apps/<slug>/README.md before changing it.\n"
            + "\n".join(lines)) if lines else ""
    _apps_cache[root] = (time.monotonic() + _APPS_TTL, text)
    return text


def _extension_app(root, slug):
    """The extension that installed apps/<slug> (its manifest's `extension`), if one did."""
    try:
        owner = json.loads((pathlib.Path(root) / "apps" / slug / "app.json").read_text(encoding="utf-8")).get("extension")
    except Exception:
        return None
    return owner if isinstance(owner, str) and owner else None


async def _exec_build_app(inp, ws):
    import cycls

    workspace = ws.root

    slug = str(inp.get("slug", "")).strip().lower()
    if not slug or set(slug) - _APP_SLUG_OK:
        return "Error: slug must be lowercase letters, digits, - or _"
    if owner := _extension_app(workspace, slug):
        return (f"Error: apps/{slug} is the {owner} app — change it with its own tool, "
                "or build your app under another slug.")

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
        build = cycls.remote(APP_BUILDER, timeout=_APP_BUILD_TIMEOUT)
        result = await asyncio.to_thread(build, files=files)
    except Exception as e:
        return f"Error: the build service is unavailable ({type(e).__name__}: {e})"

    if not isinstance(result, dict):
        return f"Build failed: the build service returned {type(result).__name__}, not a result."
    if not result.get("ok"):
        have = result.get("packages") or []
        return (f"Build failed: {result.get('error')}\n\n{result.get('log', '')}"[:MAX_OUTPUT]
                + (f"\n\nAvailable packages: {', '.join(have)}." if have else "")
                + "\n\nFix the source and call build_app again.")
    if not isinstance(result.get("html"), str):
        return "Build failed: the build service reported success but returned no html."

    app_dir = pathlib.Path(workspace) / "apps" / slug
    fresh = not app_dir.exists()
    app_dir.mkdir(parents=True, exist_ok=True)
    if fresh:   # a reused slug must not inherit the rows of the app that had it
        await apps_db(ws).delete(app_shelf(slug))
    entry = app_dir / "index.html"
    if entry.exists():   # a bad rebuild stays recoverable, as `edit` keeps an overwrite
        trash.trash_path(workspace, f"apps/{slug}/index.html", by="agent", reason="rebuild")
    entry.write_text(result["html"], encoding="utf-8")

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
    if inp.get("description"):
        manifest["description"] = str(inp["description"])[:200]
    manifest.setdefault("name", slug.replace("-", " ").replace("_", " ").title())
    manifest["built"] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "source": str(inp.get("source") or ""),
                         "builder": str(result.get("version") or "unknown")}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    kb = (result.get("bytes") or len(result["html"].encode())) / 1024
    out = (f"Installed apps/{slug}/index.html ({kb:.0f} KB). It is in the Apps tab.\n"
           f"Now write apps/{slug}/README.md describing each file the app reads under "
           f"apps/{slug}/data/ and its shape. A later session updates that data without "
           f"you — and without it, the only way to learn the schema is to read the bundle.")
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
    `prompt`: guidance appended while the tool is enabled. `interrupted`: what the
    model is told when the call is cancelled mid-flight."""
    run: object
    step: object
    once: bool = False
    terminal: bool = False
    prompt: str = ""
    interrupted: str = ""


def _run_bash(inp, workspace, *, timeout, network, **_):
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


def _browser_snapshot_text(snap):
    """A page snapshot → the compact text the model reads: title/url, the
    visible text, then the numbered interactive elements it acts on by ref."""
    lines = [f"{snap['title']} — {snap['url']}"]
    if snap.get("text"):
        lines += ["", snap["text"] + (" …(truncated)" if snap.get("text_truncated") else "")]
    lines += ["", "Interactive elements (act by ref):"]
    for e in snap.get("refs", []):
        typ = f"({e['type']})" if e.get("type") else ""
        label = f' "{e["label"]}"' if e.get("label") else ""
        lines.append(f"[{e['ref']}] {e['tag']}{typ}{label}")
    if not snap.get("refs"):
        lines.append("(none)")
    elif snap.get("refs_truncated"):
        lines.append("… (more elements not shown — narrow the page or scroll)")
    return "\n".join(lines)


async def _browser_read(s):
    return _browser_snapshot_text(await s.snapshot())


def _safe_filename(name, default="download"):
    """A filename safe to write under the workspace: basename only (no path
    traversal via `/`, `\\`, or `..`), trimmed, with a fallback."""
    base = os.path.basename((name or "").replace("\\", "/")).strip().strip(".")
    return base or default


async def _exec_browser(inp, workspace, chat_id=None):
    """Drive the shared browser service one action at a time. State lives in the
    remote page (which persists between calls), so every navigational action
    returns a fresh read — the numbered elements the model acts on next."""
    from cycls._agent import browser
    action = (inp.get("action") or "").lower()
    subject = getattr(workspace, "subject", None)
    # Forward the first navigation's URL so the service can route this session to
    # the proxy by domain (per-site routing). Only `open` carries a target URL.
    nav_url = inp.get("url") if action == "open" else None
    try:
        async with await browser.session(subject, nav_url=nav_url, chat_id=chat_id) as s:
            if action == "open":
                if not inp.get("url"):
                    return "Error: `open` needs a `url`."
                await s.goto(inp["url"])
                return await _browser_read(s)
            if action == "read":
                return await _browser_read(s)
            if action == "click":
                if inp.get("ref") is None:
                    return "Error: `click` needs a `ref` (an element number from `read`)."
                await s.click_ref(inp["ref"])
                return await _browser_read(s)
            if action == "type":
                if inp.get("ref") is None or inp.get("text") is None:
                    return "Error: `type` needs a `ref` and `text`."
                await s.type_ref(inp["ref"], inp["text"])
                return await _browser_read(s)
            if action == "press":
                await s.press(inp.get("key") or "Enter")
                return await _browser_read(s)
            if action == "back":
                await s.back()
                return await _browser_read(s)
            if action == "screenshot":
                png = await s.screenshot(full_page=bool(inp.get("full_page")))
                info = await s.info()
                rel = f"screenshots/{uuid.uuid4().hex[:12]}.png"
                dst = pathlib.Path(workspace.root) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(dst.write_bytes, png)
                name = rel.rsplit("/", 1)[-1]
                # Two channels: the model reads the ack; the client opens the PNG
                # on the canvas (same open_canvas event the Canvas tool uses).
                return {"_model": f"Screenshot of {info['url']} saved to {rel} "
                                  f"({len(png) // 1024} KB) and opened on the canvas.",
                        "_ui": {"type": "ui", "action": "open_canvas", "path": rel, "name": name}}
            if action == "download":
                ref, url = inp.get("ref"), inp.get("url")
                if ref is None and not url:
                    return ("Error: `download` needs a `ref` (a download button/link "
                            "from the last `read`) or a `url`.")
                fname, data = await s.download(ref=ref, url=url)
                rel = f"downloads/{_safe_filename(fname)}"
                dst = pathlib.Path(workspace.root) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(dst.write_bytes, data)
                return (f"Downloaded {rel} ({len(data) // 1024} KB) — open it from the "
                        f"workspace (e.g. read it in bash/python; .xlsx via pandas).")
            if action == "evaluate":
                if not inp.get("script"):
                    return ("Error: `evaluate` needs a `script` (JS expression/function "
                            "returning JSON-serializable data).")
                out = await s.evaluate(inp["script"])
                text = out.get("result") or "(no result)"
                if out.get("truncated"):
                    text += "\n… (result truncated — narrow the script, e.g. slice/filter)"
                return text
            return f"Error: unknown browser action {action!r}."
    except browser.Unavailable as e:
        return f"Error: browser unavailable — {e}"
    except Exception as e:
        return f"Error: browser {action or '?'} failed — {type(e).__name__}: {e}"


def _browser_step(inp):
    a = inp.get("action", "")
    detail = (inp.get("url") or (f"[{inp['ref']}]" if inp.get("ref") is not None else "")
              or inp.get("key") or "")
    return {"tool_name": "Browser", "step": f"{a} {detail}".strip()}


_DESIGN_EXTS = {"png", "jpg", "webp", "svg", "pptx", "pdf"}
# Formats that are the whole deck in one file (every other format is per frame).
_DECK_EXTS = ("pptx", "pdf")


# Named sizes a spec may pass as `size` instead of [W, H], so a common format is
# never guessed or mis-sized. The A4 poster is 150dpi — the default @2x render
# lands it at print-quality 300dpi.
_DESIGN_SIZES = {
    "square": [1080, 1080], "post-portrait": [1080, 1350],
    "story": [1080, 1920], "reel": [1080, 1920],
    "slide": [1920, 1080], "wide": [1920, 1080],
    "x-post": [1600, 900], "a4-poster": [1240, 1754],
}
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}")
# A render the model sees, to QA before presenting it — bounded like `read`.
_DESIGN_QA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_DESIGN_QA_MAX = 3 * 1024 * 1024
_DESIGN_QA_SLIDES = 12             # a deck's slides the model QAs, in order


def _norm_hex(c):
    """`#abc`/`#AABBCC` → `#aabbcc`; anything else → None."""
    if not isinstance(c, str) or not _HEX.fullmatch(c.strip()):
        return None
    h = c.strip()[1:].lower()
    return "#" + (h if len(h) == 6 else "".join(ch * 2 for ch in h))


def _load_brand(root):
    """The workspace brand kit — `brand/brand.yaml`, written by the brand-kit skill —
    as {primary, accent, heading, body} (any may be None), or None when there is no
    kit or it names neither a hex primary nor a font. Reads the flat keys
    (`primary_color: "#0c2340"`, `font_heading: "Playfair Display"`) and the older
    nested ones (`colors:` / `  primary: …`, `fonts:` / `  heading: …`) with a
    pattern, not a YAML parser — the SDK carries no YAML dependency."""
    try:
        text = (pathlib.Path(root) / "brand" / "brand.yaml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    def pick(flat, nested):
        m = (re.search(rf"^{flat}\s*:\s*['\"]?({_HEX.pattern})\b", text, re.M)
             or re.search(rf"^\s+{nested}\s*:\s*['\"]?({_HEX.pattern})\b", text, re.M))
        return _norm_hex(m.group(1)) if m else None

    def font(flat, nested):
        value = r"""\s*:\s*['"]?([A-Za-z][A-Za-z0-9 \-]*?)['"]?\s*(?:#.*)?$"""
        m = re.search(rf"^{flat}{value}", text, re.M) or re.search(rf"^\s+{nested}{value}", text, re.M)
        return m.group(1).strip() if m and m.group(1).strip().lower() not in ("null", "none", "") else None

    primary = pick("primary_color", "primary")
    brand = {"primary": primary, "accent": pick("accent_color", "accent") or primary,
             "heading": font("font_heading", "heading"), "body": font("font_body", "body")}
    return brand if primary or brand["heading"] or brand["body"] else None


_BRAND_COLOR_KEYS = ("primary", "secondary", "accent", "background", "text", "neutral")


def _brand_palette(root):
    """The brand kit's named colours for the design editor's Brand variables —
    {primary, secondary, accent, background, text, neutral}, each only when
    `brand/brand.yaml` gives it a hex, flat (`secondary_color: "#…"`) or nested under
    `colors:`. Unlike `_load_brand`, nothing is inferred (no accent from primary)."""
    try:
        text = (pathlib.Path(root) / "brand" / "brand.yaml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    palette = {}
    for key in _BRAND_COLOR_KEYS:
        m = (re.search(rf"^{key}_colou?r\s*:\s*['\"]?({_HEX.pattern})\b", text, re.M)
             or re.search(rf"^\s+{key}\s*:\s*['\"]?({_HEX.pattern})\b", text, re.M))
        if m and (value := _norm_hex(m.group(1))):
            palette[key] = value
    return palette


def _first_color(paint):
    """A paint's representative colour: the hex itself, or a gradient's first stop."""
    if isinstance(paint, dict) and isinstance(paint.get("gradient"), list) and paint["gradient"]:
        paint = paint["gradient"][0]
        if isinstance(paint, (list, tuple)) and paint:
            paint = paint[0]
        elif isinstance(paint, dict):
            paint = paint.get("color")
    return _norm_hex(paint)


def _luminance(hex_):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a, b):
    """The WCAG contrast ratio of two #rrggbb colours."""
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _readable_on(bg):
    """White or near-black — whichever text reads better on `bg` (WCAG luminance)."""
    return "#ffffff" if _luminance(bg) < 0.179 else "#111111"


# An image node's bytes ride to the stateless service as base64 inside the spec —
# bounded so a request stays under the platform's 32 MiB (base64 adds a third). The
# service fits each photo to its box (cover-crop, at most 2× the box) before it's
# drawn, so the .fig stays light however big the original.
_DESIGN_IMAGE_MAX = 15 * 1024 * 1024
_DESIGN_IMAGES_MAX = 20 * 1024 * 1024
_DESIGN_SVG_MAX = 200 * 1024


def _exif_orientation(tiff):
    """The Orientation tag (0x0112) of an EXIF TIFF block, else 1."""
    try:
        e = {b"II": "<", b"MM": ">"}[tiff[:2]]
        off = struct.unpack(e + "I", tiff[4:8])[0]
        for k in range(struct.unpack(e + "H", tiff[off:off + 2])[0]):
            p = off + 2 + 12 * k
            if struct.unpack(e + "H", tiff[p:p + 2])[0] == 0x0112:
                return struct.unpack(e + "H", tiff[p + 8:p + 10])[0]
    except (KeyError, struct.error):
        pass
    return 1


def _jpeg_size(data):
    i, turned = 2, False
    while i + 9 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xFF:                                  # fill byte
            i += 1
            continue
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            turned = _exif_orientation(data[i + 10:i + 2 + seg]) in (5, 6, 7, 8)
        elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return (h, w) if turned else (w, h)
        i += 2 + seg
    return None


def _image_size(data):
    """(width, height) of a PNG / JPEG / WebP / GIF as the renderer DRAWS it — a
    JPEG's EXIF quarter-turn (orientation 5–8) swaps the two, since the renderer
    honours it — else None (an SVG included)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        kind = data[12:16]
        if kind == b"VP8X":
            return (int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1)
        if kind == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return (w & 0x3FFF, h & 0x3FFF)
        if kind == b"VP8L":
            b = int.from_bytes(data[21:25], "little")
            return ((b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1)
        return None
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    return None


def _place_image(n, root):
    """An image node's `src` (a workspace file) → the bytes the service draws, in
    its final box: `fit` "cover" (default) fills w×h, cropping the overflow;
    "contain" shrinks the box to the image's aspect and centres it (the renderer's
    own FIT distorts). Give w, h or both — a missing one follows the image's
    aspect. Rewrites the node in place; returns the byte count. Raises ValueError
    with the fix."""
    src = n.get("src")
    if not isinstance(src, str) or not src.strip():
        raise ValueError("an image node needs `src` — a workspace file, e.g. attachments/photo.jpg — "
                         "or `stock`: a photo to find, e.g. \"stock\": \"coffee beans on wood\"")
    if src.startswith(("http://", "https://", "data:")):
        raise ValueError(f"image src {src[:60]!r} must be a workspace file — save it into the workspace first")
    path = _resolve_path(src, root)
    if not path.is_file():
        raise ValueError(f"image {src!r} does not exist in the workspace")
    if (size := path.stat().st_size) > _DESIGN_IMAGE_MAX:
        raise ValueError(f"image {src!r} is {size / 2**20:.1f} MB, over the {_DESIGN_IMAGE_MAX >> 20} MB "
                         f"a design takes — save a smaller copy (longest side ~2000px) and use that")
    data = path.read_bytes()
    if not (dims := _image_size(data)) or not all(dims):
        raise ValueError(f"image {src!r} isn't a PNG, JPEG, WebP or GIF (convert an SVG to PNG first)")
    (iw, ih), w, h = dims, n.get("w"), n.get("h")
    if not w and not h:
        raise ValueError(f"image {src!r} needs `w` and/or `h` (the other follows its {iw}×{ih} aspect)")
    w, h = (w or h * iw / ih), (h or w * ih / iw)
    fit = str(n.pop("fit", "cover")).lower()
    if fit == "contain":
        s = min(w / iw, h / ih)
        n["x"] = (n.get("x") or 0) + (w - iw * s) / 2
        n["y"] = (n.get("y") or 0) + (h - ih * s) / 2
        w, h = iw * s, ih * s
    elif fit != "cover":
        raise ValueError(f"image `fit` is cover or contain, not {fit!r}")
    n["w"], n["h"] = round(w, 2), round(h, 2)
    n["image"] = base64.b64encode(data).decode()
    del n["src"]
    return len(data)


_NUMERIC = ("x", "y", "w", "h", "size", "radius", "lineHeight", "letterSpacing",
            "opacity", "strokeWeight", "rotation", "gap", "width", "blur", "backdropBlur")


def _num(v):
    """A number the model may have quoted ("1500", "96px") → int/float, else None."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and (m := re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:px)?\s*", v)):
        f = float(m.group(1))
        return int(f) if f.is_integer() else f
    return None


def _frame_size(fr):
    """A frame's [W, H] from whatever shape the model gave it — [W, H], a preset
    name, "1080x1920", {w, h}, or width/height keys on the frame — else the
    renderer's own 1080² default. Raises ValueError for anything else."""
    s = fr.get("size")
    if s is None and "width" in fr and "height" in fr:
        s = [fr.pop("width"), fr.pop("height")]
    if isinstance(s, dict):
        s = [s.get("w", s.get("width")), s.get("h", s.get("height"))]
    if s is None:
        return [1080, 1080]
    if isinstance(s, str):
        key = s.strip().lower()
        if key in _DESIGN_SIZES:
            return list(_DESIGN_SIZES[key])
        if m := re.fullmatch(r"(\d+)\s*[x×]\s*(\d+)", key):
            return [int(m.group(1)), int(m.group(2))]
        raise ValueError(f"unknown size {s!r} — use [W, H] or one of: {', '.join(_DESIGN_SIZES)}")
    if isinstance(s, (list, tuple)) and len(s) == 2 and all((_num(v) or 0) > 0 for v in s):
        return [_num(v) for v in s]
    raise ValueError(f"`size` {s!r} isn't a size — use [W, H] or a preset ({', '.join(_DESIGN_SIZES)})")


def _prepare_spec(spec, brand, root=None):
    """The spec the service renders, made safe to draw: preset sizes resolved to
    [W, H]; a node with `text` but no `type` typed as text (the renderer silently
    drops an untyped node); fonts mapped onto Inter; image `src` files read from the
    workspace under `root` and placed (see _place_image); with a brand kit, a frame
    `fill` left out becomes the brand primary and a shape `fill` the accent; text
    with no colour gets white or near-black against its frame. Never overrides a
    colour the model set. A copy — the model's input stays as written. Returns
    (spec, error, notes), notes being lines for the model's ack."""
    if isinstance(spec.get("deck"), dict):
        return _prepare_deck(spec, brand, root)
    if spec.get("pages") is not None:
        return _prepare_pages(spec, brand, root)
    colors = {_norm_hex(m) for m in _HEX.findall(json.dumps(spec))}
    spec = json.loads(json.dumps(spec))
    frames = spec["frames"] if isinstance(spec.get("frames"), list) and spec["frames"] else [spec]
    filled, branded_fonts, image_bytes = 0, 0, 0
    first_size = None
    for i, fr in enumerate(frames, 1):
        if not isinstance(fr, dict):
            continue
        try:
            fr["size"] = W, H = _frame_size(fr)
        except ValueError as e:
            return None, f"Error: {e}.", []
        # A deck is one size: PowerPoint takes the first slide's size for the whole
        # file and letterboxes the rest.
        if first_size is None:
            first_size = [W, H]
        elif [W, H] != first_size:
            return None, (f"Error: every slide of a deck must be the same size — slide 1 is "
                          f"{first_size[0]}×{first_size[1]}, slide {i} is {W}×{H}. Give every "
                          f"frame the same `size`."), []
        if brand and brand["primary"] and fr.get("fill") is None:
            fr["fill"], filled = brand["primary"], filled + 1
        bg = _first_color(fr.get("fill"))

        def prepare(n, top):
            """One node, made safe (a stack's children too). → an error, or None."""
            nonlocal filled, branded_fonts, image_bytes
            if n.get("type") is None and ("text" in n or "src" in n):
                n["type"] = "text" if "text" in n else "image"
            for k in _NUMERIC:                           # "1500" would reach the renderer as a string —
                if k in n and n[k] is not None and _num(n[k]) is None:     # and a string y sinks the text
                    return f"Error: `{k}` must be a number, not {n[k]!r} ({json.dumps(n)[:80]})."
                if k in n and n[k] is not None:
                    n[k] = _num(n[k])
            if n.get("type") == "text":
                # Fonts go to the service as written — it resolves any Google Font
                # (and says what it swapped). A brand kit's fonts fill in where the spec
                # named none: the heading face for display sizes, the body face below.
                if brand and n.get("font") is None:
                    face = brand["heading"] if (n.get("size") or 32) >= 48 else brand["body"]
                    face = face or brand["heading"] or brand["body"]
                    if face:
                        n["font"], branded_fonts = face, branded_fonts + 1
                if bg and n.get("color") is None and n.get("fill") is None:
                    n["color"] = _readable_on(bg)
            elif n.get("type") in ("rect", "ellipse", "line"):
                if n.get("fill") is None and n.get("color") is not None:
                    n["fill"] = n.pop("color")          # a shape draws `fill` only — as text reads either
                if brand and brand["accent"] and n.get("fill") is None and not n.get("stroke"):
                    n["fill"], filled = brand["accent"], filled + 1
            elif n.get("type") == "image":
                try:
                    image_bytes += _place_image(n, root)
                except ValueError as e:
                    return f"Error: {e}"
                if image_bytes > _DESIGN_IMAGES_MAX:
                    return (f"Error: the design's images total over {_DESIGN_IMAGES_MAX >> 20} MB — "
                            f"use smaller copies (longest side ~2000px).")
            elif n.get("type") in ("icon", "svg", "qr", "list", "chart", "table"):
                kind = n["type"]
                if kind == "icon" and not (isinstance(n.get("name"), str) and ":" in n["name"]):
                    return f"Error: an icon needs `name` — an Iconify name like \"lucide:rocket\" or \"mdi:coffee\" ({json.dumps(n)[:80]})."
                if kind == "svg" and n.get("src") and not n.get("svg"):
                    path = _resolve_path(str(n.pop("src")), root)
                    if not path.is_file() or path.suffix.lower() != ".svg":
                        return f"Error: svg `src` must be an .svg file in the workspace ({json.dumps(n)[:80]})."
                    if path.stat().st_size > _DESIGN_SVG_MAX:
                        return f"Error: {path.name} is over {_DESIGN_SVG_MAX >> 10} KB — use a simpler SVG (or a PNG image)."
                    n["svg"] = path.read_text(encoding="utf-8", errors="replace")
                if kind == "svg" and not (isinstance(n.get("svg"), str) and "<svg" in n["svg"]):
                    return "Error: an svg node needs `svg` (the markup) or `src` (an .svg file in the workspace)."
                if kind == "qr" and not str(n.get("text") or "").strip():
                    return "Error: a qr node needs `text` — the link or text to encode."
                if kind == "list" and not isinstance(n.get("items"), list):
                    return "Error: a list needs `items` — a list of strings."
                if kind == "chart" and not isinstance((n.get("data") or {}).get("series") or n.get("values"), list):
                    return "Error: a chart needs `data`: {labels:[…], series:[{name, values:[…]}]}."
                if kind == "table" and not isinstance(n.get("rows"), list):
                    return "Error: a table needs `rows` (a list of rows, each a list of cells) and usually `columns`."
                # Marks and text-bearing nodes read on their background like text does.
                if bg and n.get("color") is None and kind != "svg":
                    n["color"] = _readable_on(bg)
                if brand and n.get("font") is None and kind in ("list", "chart", "table") and brand["body"]:
                    n["font"], branded_fonts = brand["body"], branded_fonts + 1
            elif n.get("type") == "stack":
                kids = n.get("children")
                if not isinstance(kids, list) or not kids:
                    return f"Error: a stack needs `children` — the nodes it lays out ({json.dumps(n)[:80]})."
                for c in kids:
                    if not isinstance(c, dict):
                        return f"Error: a stack's children are nodes, not {c!r}."
                    if err := prepare(c, False):
                        return err
            else:
                return (f"Error: a node has type {n.get('type')!r} ({json.dumps(n)[:80]}) — "
                        f"every node needs a `type`: text, rect, ellipse, line, image, stack, list, "
                        f"table, chart, icon, svg or qr.")
            # Content placed wholly outside the frame is a layout built for another size:
            # the renderer would clamp every such text box to the edge, piling it up.
            # (A stack places its children itself.)
            if top and n["type"] not in ("rect", "ellipse", "line") and ((n.get("x") or 0) >= W or (n.get("y") or 0) >= H):
                what = repr(n.get("text"))[:40] if n["type"] == "text" else f"a{'n' if n['type'] == 'image' else ''} {n['type']}"
                return (f"Error: {what} starts at ({n.get('x') or 0}, {n.get('y') or 0}), outside the "
                        f"{W}×{H} frame — set the frame's `size` (e.g. \"story\" for 1080×1920) "
                        f"or move it inside.")
            return None

        for n in fr.get("nodes") or []:
            if isinstance(n, dict) and (err := prepare(n, True)):
                return None, err, []
    notes = []
    if branded_fonts:
        notes.append(f"Brand fonts applied to {branded_fonts} text node(s) with no font "
                     f"(heading {brand['heading'] or brand['body']}, body {brand['body'] or brand['heading']}).")
    if brand and filled:
        notes.append(f"Brand kit applied to {filled} unset fill(s) "
                     f"(primary {brand['primary']}, accent {brand['accent']}).")
    elif brand and brand["primary"] and not colors & {brand["primary"], brand["accent"]}:
        notes.append(f"Note: the workspace has a brand kit (primary {brand['primary']}, accent "
                     f"{brand['accent']}) and this design uses neither — if it should be on-brand, fix that.")
    return spec, None, notes


def _prepare_pages(spec, brand, root):
    """A design of several pages — its variants — each prepared as a design of its own
    (its own size; a carousel's frames one size). → (spec, error, notes)."""
    pages = spec.get("pages")
    if not isinstance(pages, list) or not pages:
        return None, ('Error: `pages` is a list of pages, each a design with a name: '
                      '[{"name": "Post", "size": "square", "fill": …, "nodes": […]}, …].'), []
    out, notes, seen = [], [], set()
    for n, page in enumerate(pages, 1):
        if not isinstance(page, dict):
            return None, f"Error: page {n} must be an object: {{name, size, fill, nodes}}.", []
        name = str(page.get("name") or "").strip()
        if not name:
            return None, f'Error: page {n} needs a `name` (e.g. "Post", "Story") — edits and downloads name a page.', []
        if name.lower() in seen:
            return None, f"Error: two pages are named {name!r} — every page needs its own name.", []
        seen.add(name.lower())
        if page.get("deck") is not None or page.get("pages") is not None:
            return None, (f"Error: page {name!r} is a design ({{size, fill, nodes}}) or a carousel "
                          f"({{frames}}) — a deck of layouts is a design of its own (render it by itself)."), []
        made, err, more = _prepare_spec({k: v for k, v in page.items() if k != "name"}, brand, root)
        if err:
            return None, err.replace("Error: ", f"Error: page {name!r}: ", 1), []
        out.append({"name": name[:40], **made})
        notes += [m for m in more if m not in notes]
    return {"pages": out}, None, notes


_DECK_THEMES = ("minimal-light", "minimal-dark", "bold-gradient", "editorial", "corporate", "tech-dark", "warm", "mono")
_BRAND_LOGOS = ("logo.svg", "logo.png", "logo.webp", "logo.jpg", "logo.jpeg")


def _image_slot(src, root):
    """A deck's image slot — a workspace path, or {src, focus} — → what the service
    draws: {image: base64, src[, focus]} for a PNG / JPEG / WebP / GIF, or {svg, src}.
    → (slot, bytes read). Raises ValueError with the fix."""
    focus = None
    if isinstance(src, dict):
        focus, src = src.get("focus"), src.get("src")
    if not isinstance(src, str) or not src.strip():
        raise ValueError('an image slot is a workspace file path, e.g. "attachments/photo.jpg"')
    if src.startswith(("http://", "https://", "data:")):
        raise ValueError(f"image {src[:60]!r} must be a workspace file — save it into the workspace first")
    path = _resolve_path(src, root)
    if not path.is_file():
        raise ValueError(f"image {src!r} does not exist in the workspace")
    size = path.stat().st_size
    if path.suffix.lower() == ".svg":
        if size > _DESIGN_SVG_MAX:
            raise ValueError(f"{src} is over {_DESIGN_SVG_MAX >> 10} KB — use a simpler SVG (or a PNG)")
        return {"svg": path.read_text(encoding="utf-8", errors="replace"), "src": src}, size
    if size > _DESIGN_IMAGE_MAX:
        raise ValueError(f"image {src!r} is {size / 2**20:.1f} MB, over the {_DESIGN_IMAGE_MAX >> 20} MB a design takes")
    data = path.read_bytes()
    if not _image_size(data):
        raise ValueError(f"image {src!r} isn't a PNG, JPEG, WebP, GIF or SVG")
    slot = {"image": base64.b64encode(data).decode(), "src": src}
    if (natural := _image_size(data)):
        slot["w"], slot["h"] = natural                      # a document sizes a picture from its own shape
    if isinstance(focus, list) and len(focus) == 2:
        slot["focus"] = focus
    return slot, size


def _brand_theme(brand):
    """The deck theme a brand kit makes, on the minimal-light base: the primary as the
    hero (title, section and closing slides), the accent for highlights — swapped for
    the primary where it wouldn't read as text on white — and the brand's fonts."""
    primary, accent = brand.get("primary"), brand.get("accent") or brand.get("primary")
    theme = {"base": "minimal-light", "name": "brand"}
    hero_text = None
    if primary:
        hero_text = _readable_on(primary)
        theme.update(hero=primary, heroText=hero_text, heroMuted=hero_text + "b3")
    if accent:
        on_white = (accent if _contrast(accent, "#ffffff") >= 4.5
                    else primary if primary and _contrast(primary, "#ffffff") >= 4.5 else "#0f172a")
        theme.update(accent=on_white, accent2=accent, onAccent=_readable_on(on_white),
                     heroAccent=accent if not primary or _contrast(accent, primary) >= 3 else hero_text)
    if brand.get("heading"):
        theme["heading"] = f"{brand['heading']} Bold"
    if brand.get("body"):
        theme["body"] = brand["body"]
    return theme


def _prepare_deck(spec, brand, root):
    """A deck of layouts — {deck: {theme, slides: [{layout, …}]}} — made ready for the
    service, which lays it out (cycls-design layouts.js): the size resolved; image slots
    (a slide's `image`, a team member's `photo`, the deck's `logo` and footer logo) read
    from the workspace; theme "brand" — or no theme, when the workspace has a brand kit —
    built from the brand kit, with brand/logo.* as the deck logo; a custom slide's
    `nodes` prepared like a single design's. → (spec, error, notes)."""
    spec = json.loads(json.dumps(spec))
    deck = spec["deck"]
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        return None, "Error: a deck needs `slides` — a list of {layout, …} (the layouts are in the tool description).", []
    try:
        deck["size"] = size = _frame_size({"size": deck.get("size") or "slide"})
    except ValueError as e:
        return None, f"Error: {e}.", []
    notes, total = [], 0

    def slot(value):
        nonlocal total
        resolved, n = _image_slot(value, root)
        total += n
        if total > _DESIGN_IMAGES_MAX:
            raise ValueError(f"the deck's images total over {_DESIGN_IMAGES_MAX >> 20} MB — use smaller copies "
                             f"(longest side ~2000px)")
        return resolved

    theme = deck.get("theme")
    if theme == "brand" and not brand:
        return None, (f"Error: theme \"brand\" needs a brand kit (brand/brand.yaml) — or pick a theme: "
                      f"{', '.join(_DECK_THEMES)}."), []
    if (theme is None or theme == "brand") and brand:
        deck["theme"] = theme = _brand_theme(brand)
        logo = next((f"brand/{n}" for n in _BRAND_LOGOS if root and (pathlib.Path(root) / "brand" / n).is_file()), None)
        if logo and not deck.get("logo"):
            deck["logo"] = logo
        fonts = " / ".join(f for f in (brand.get("heading"), brand.get("body")) if f)
        notes.append(f"The deck uses the workspace brand kit as its theme (primary {brand['primary']}, accent "
                     f"{brand['accent']}{', fonts ' + fonts if fonts else ''}{', logo ' + logo if logo else ''}).")
    try:
        if deck.get("logo"):
            deck["logo"] = slot(deck["logo"])
        if isinstance(deck.get("footer"), dict) and deck["footer"].get("logo"):
            deck["footer"]["logo"] = slot(deck["footer"]["logo"])
        if isinstance(theme, dict) and theme.get("logo"):
            theme["logo"] = slot(theme["logo"])
        for i, s in enumerate(slides, 1):
            if not isinstance(s, dict):
                return None, f"Error: slide {i} must be an object: {{layout, …}}.", []
            if s.get("image"):
                s["image"] = slot(s["image"])
            for person in s.get("people") or []:
                if isinstance(person, dict) and person.get("photo"):
                    person["photo"] = slot(person["photo"])
            if isinstance(s.get("nodes"), list):
                sub, err, _ = _prepare_spec({"size": size, "fill": s.get("fill"), "nodes": s["nodes"]}, None, root)
                if err:
                    return None, err.replace("Error: ", f"Error: slide {i}: ", 1), []
                s["nodes"] = sub["nodes"]
    except ValueError as e:
        return None, f"Error: {e}.", []
    return spec, None, notes


_PAPER = {"a4": [1240, 1754], "letter": [1275, 1650], "a5": [874, 1240], "a3": [1754, 2480]}   # px at 150 dpi


_SHEET_ROWS = 2000      # rows read from a spreadsheet for a chart or a table


def _number(text):
    """A cell as a number — 1,204.5, 12%, (30) — or None."""
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return text
    s = str(text or "").strip().replace(",", "").replace("\u00a0", "").replace(" ", "")
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").rstrip("%").lstrip("$€£")
    try:
        v = float(s)
    except ValueError:
        return None
    v = -v if negative else v
    return int(v) if v.is_integer() and "." not in s else v


def _sheet(src, root, sheet=None):
    """A workspace spreadsheet — .csv / .tsv, or .xlsx (its first sheet, or `sheet`) —
    → (columns, rows): the first row names the columns. Raises ValueError with the fix."""
    if not isinstance(src, str) or not src.strip():
        raise ValueError('`from` is a workspace spreadsheet, e.g. "data/sales.csv"')
    path = _resolve_path(src, root)
    ext = path.suffix.lower()
    if ext not in (".csv", ".tsv", ".xlsx"):
        raise ValueError(f"{src} isn't a spreadsheet this reads — use a .csv, .tsv or .xlsx file")
    if not path.is_file():
        raise ValueError(f"{src} does not exist in the workspace")
    if ext == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            raise ValueError(f"{src}: reading .xlsx needs openpyxl in this agent's image — save the sheet as .csv instead")
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            if sheet is not None and str(sheet) not in book.sheetnames:
                raise ValueError(f"{src} has no sheet {str(sheet)!r} — its sheets: {', '.join(book.sheetnames)}")
            ws = book[str(sheet)] if sheet is not None else book[book.sheetnames[0]]
            table = [list(r) for _, r in zip(range(_SHEET_ROWS + 1), ws.iter_rows(values_only=True))]
        finally:
            book.close()
    else:
        import csv
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        table = [r for _, r in zip(range(_SHEET_ROWS + 1), csv.reader(text.splitlines(), delimiter="\t" if ext == ".tsv" else ","))]
    table = [r for r in table if any(c not in (None, "") for c in r)]
    if len(table) < 2:
        raise ValueError(f"{src} needs a header row and at least one row of data")
    cell = lambda v: "" if v is None else str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip()
    columns = [cell(c) or f"Column {i + 1}" for i, c in enumerate(table[0])]
    rows = [[r[i] if i < len(r) else None for i in range(len(columns))] for r in table[1:]]
    return columns, rows, cell


def _block_data(b, root):
    """A chart or a table that names its data — {"from": "data/sales.csv", …} — filled
    from that file: a chart's `x` (the column of labels; the first when not said) and `y`
    (the columns of numbers; every one when not said), a table's `columns` (a choice, in
    order) and `limit`. Raises ValueError with the fix."""
    chart, table = b.get("chart"), b.get("table")
    if isinstance(chart, dict) and chart.get("from"):
        columns, rows, cell = _sheet(chart["from"], root, chart.get("sheet"))

        def col(name):
            if str(name) not in columns:
                raise ValueError(f"{chart['from']} has no column {json.dumps(str(name))} — its columns: {', '.join(columns)}")
            return columns.index(str(name))
        x = col(chart["x"]) if chart.get("x") is not None else 0
        given = chart.get("y")
        ys = [col(y) for y in (given if isinstance(given, list) else [given])] if given is not None else [
            i for i in range(len(columns)) if i != x and rows and all(_number(r[i]) is not None for r in rows if r[i] not in (None, ""))
            and any(r[i] not in (None, "") for r in rows)]
        if not ys:
            raise ValueError(f"{chart['from']} has no column of numbers to chart — its columns: {', '.join(columns)}")
        series = []
        for i in ys:
            values = [_number(r[i]) for r in rows]
            if any(v is None for v in values):
                raise ValueError(f"{chart['from']}: column {json.dumps(columns[i])} isn't all numbers")
            series.append({"name": columns[i], "values": values})
        rest = {k: v for k, v in chart.items() if k not in ("from", "sheet", "x", "y")}
        b["chart"] = {**rest, "data": {"labels": [cell(r[x]) for r in rows], "series": series}}
    if isinstance(table, dict) and table.get("from"):
        columns, rows, cell = _sheet(table["from"], root, table.get("sheet"))
        pick = table.get("columns")
        if isinstance(pick, list) and pick:
            missing = [str(c) for c in pick if str(c) not in columns]
            if missing:
                raise ValueError(f"{table['from']} has no column {json.dumps(missing[0])} — its columns: {', '.join(columns)}")
            order = [columns.index(str(c)) for c in pick]
        else:
            order = list(range(len(columns)))
        limit = _num(table.get("limit"))
        if limit and limit > 0:
            rows = rows[:int(limit)]
        rest = {k: v for k, v in table.items() if k not in ("from", "sheet", "columns", "limit")}
        b["table"] = {**rest, "columns": [columns[i] for i in order], "rows": [[cell(r[i]) for i in order] for r in rows]}


def _prepare_document(spec, brand, root):
    """A document — {document: {title, sections: [{title, blocks: […]}]}} — made ready for
    the service, which designs and paginates it (cycls-design document.js / flow.js):
    every image (the cover's, the logo, an `image` block's, wherever it sits) read from
    the workspace; theme "brand" — or no theme, when the workspace has a brand kit —
    built from the kit, with brand/logo.* as the logo; hand-built `nodes` and `pages`
    prepared like a single design's. → (spec, error, notes)."""
    spec = json.loads(json.dumps(spec))
    doc = spec["document"]
    sections = doc.get("sections")
    if not isinstance(sections, list) or not sections:
        return None, ("Error: a document needs `sections` — a list of {title, blocks: […]} "
                      "(the blocks are in the tool description)."), []
    if not str(doc.get("title") or "").strip():
        return None, "Error: a document needs a `title`.", []
    notes, total = [], 0

    def slot(value):
        nonlocal total
        if isinstance(value, dict) and (isinstance(value.get("image"), str) or isinstance(value.get("svg"), str)):
            return value                                      # resolved already
        resolved, n = _image_slot(value, root)
        total += n
        if total > _DESIGN_IMAGES_MAX:
            raise ValueError(f"the document's images total over {_DESIGN_IMAGES_MAX >> 20} MB — use smaller copies "
                             f"(longest side ~2000px)")
        return resolved

    def nodes_of(nodes, size, fill=None):
        sub, err, _ = _prepare_spec({"size": size, "fill": fill, "nodes": nodes}, None, root)
        if err:
            raise ValueError(err.replace("Error: ", "", 1).rstrip("."))
        return sub["nodes"]

    def block(b):
        """One block's images and hand-built nodes, wherever they are nested."""
        if not isinstance(b, dict):
            return b
        for key in ("image", "photo", "picture"):
            if b.get(key):
                b[key] = slot(b[key])
        if str(b.get("type") or "") in ("image", "photo", "picture") and b.get("src") and not b.get("image"):
            b["image"] = slot(b.pop("src"))
        if isinstance(b.get("columns"), list):
            b["columns"] = [[block(x) for x in col] if isinstance(col, list) else block(col) for col in b["columns"]]
        if isinstance(b.get("nodes"), list):
            b["nodes"] = nodes_of(b["nodes"], [100000, 100000])
        _block_data(b, root)                                  # a chart / a table read from a spreadsheet
        return b

    theme = doc.get("theme")
    if theme == "brand" and not brand:
        return None, (f"Error: theme \"brand\" needs a brand kit (brand/brand.yaml) — or pick a theme: "
                      f"{', '.join(_DECK_THEMES)}."), []
    if (theme is None or theme == "brand") and brand:
        doc["theme"] = _brand_theme(brand)
        logo = next((f"brand/{n}" for n in _BRAND_LOGOS if root and (pathlib.Path(root) / "brand" / n).is_file()), None)
        if logo and not doc.get("logo"):
            doc["logo"] = logo
        fonts = " / ".join(f for f in (brand.get("heading"), brand.get("body")) if f)
        notes.append(f"The document uses the workspace brand kit as its theme (primary {brand['primary']}, accent "
                     f"{brand['accent']}{', fonts ' + fonts if fonts else ''}{', logo ' + logo if logo else ''}).")
    size = doc.get("size") or "a4"
    paper = list(_PAPER.get(str(size).lower().replace("-landscape", "").replace(" landscape", ""), _PAPER["a4"])) \
        if isinstance(size, str) else size
    try:
        if doc.get("logo"):
            doc["logo"] = slot(doc["logo"])
        if isinstance(doc.get("cover"), dict) and doc["cover"].get("image"):
            doc["cover"]["image"] = slot(doc["cover"]["image"])
        for i, s in enumerate(sections, 1):
            if not isinstance(s, dict):
                return None, f"Error: section {i} must be an object: {{title, blocks: […]}}.", []
            if isinstance(s.get("blocks"), list):
                s["blocks"] = [block(b) for b in s["blocks"]]
        for i, p in enumerate(doc.get("pages") or [], 1):
            if not isinstance(p, dict) or not isinstance(p.get("nodes"), list):
                return None, f"Error: pages[{i}] must be {{nodes: [spec nodes], fill?}} — a hand-built page.", []
            p["nodes"] = nodes_of(p["nodes"], paper, p.get("fill"))
    except ValueError as e:
        return None, f"Error: {e}.", []
    return spec, None, notes


_OP_NUMERIC = ("x", "y", "dx", "dy", "w", "h", "size", "radius", "opacity", "letterSpacing",
               "lineHeight", "strokeWeight", "frame")


def _prepare_ops(ops, root):
    """Edit ops made safe to send: numbers the model quoted become numbers; a
    replace_image `src` (a workspace file) becomes the image bytes; an `add`ed node
    goes through the render path (types, numbers, image files). → (ops, error)."""
    if not isinstance(ops, list):
        return None, "Error: `ops` must be a list of operations."
    ops = json.loads(json.dumps(ops))
    for k, op in enumerate(ops, 1):
        if not isinstance(op, dict) or not op.get("op"):
            return None, f"Error: op {k} must be an object with an `op` (set_text, style, move, …)."
        for key in _OP_NUMERIC:
            if key in op and op[key] is not None:
                if (v := _num(op[key])) is None:
                    return None, f"Error: op {k}: `{key}` must be a number, not {op[key]!r}."
                op[key] = v
        if op["op"] == "replace_image":
            probe = {"src": op.pop("src", None), "w": 1, "h": 1}
            try:
                _place_image(probe, root)
            except ValueError as e:
                return None, f"Error: op {k}: {e}"
            op["image"] = probe["image"]
        elif op["op"] == "add":
            if not isinstance(op.get("node"), dict):
                return None, f"Error: op {k}: `add` needs a `node` (a spec node, e.g. a text or a stack)."
            spec, err, _ = _prepare_spec({"size": [100000, 100000], "nodes": [op["node"]]}, None, root)
            if err:
                return None, err.replace("Error: ", f"Error: op {k}: ", 1)
            op["node"] = spec["nodes"][0]
        elif op["op"] == "page_add":
            # A new page is a design: prepared as a render's is (sizes, brand, images).
            if not isinstance(op.get("spec"), dict) or op["spec"].get("deck") or op["spec"].get("pages"):
                return None, (f"Error: op {k}: `page_add` needs `spec` — the page's design, "
                              f"{{size, fill, nodes}} (or a carousel's {{frames}}).")
            spec, err, _ = _prepare_spec(op["spec"], _load_brand(root) if root else None, root)
            if err:
                return None, err.replace("Error: ", f"Error: op {k}: ", 1)
            op["spec"] = spec
    return ops, None


def _outline_text(rel, frames, pages=None, page=None):
    """A design's outline (from the service's inspect) as compact lines for the model:
    each frame, then each node — name, type, box, and its text/font/colour or fill. A
    design of several `pages` says which one this is, and names the others."""
    several = pages and len(pages) > 1
    where = f"{rel} — page {json.dumps(page, ensure_ascii=False)}" if several else rel
    others = ""
    if several:
        listed = ", ".join(json.dumps(p["name"], ensure_ascii=False) for p in pages)
        others = (f" This design has {len(pages)} pages: {listed} — inspect or edit another by "
                  f"passing its name as `page`.")
    if not frames:
        return f"{where} has no frames.{others}"
    out = [f"{where} — {len(frames)} frame{'s' if len(frames) != 1 else ''}. Edit with ops that name these nodes.{others}"]
    for f in frames:
        w, h = (f.get("size") or [0, 0])[:2]
        meta = "".join(f", {k} {json.dumps(f[k], ensure_ascii=False)}" for k in ("title", "transition") if f.get(k))
        out.append(f"slide {f.get('slide')} \"{f.get('name', '')}\" ({w}×{h}"
                   f"{', fill ' + f['fill'] if f.get('fill') else ''}{meta}):")
        if f.get("notes"):
            notes = str(f["notes"])
            out.append(f"  notes: {json.dumps(notes[:300] + ('…' if len(notes) > 300 else ''), ensure_ascii=False)}")
        if f.get("source"):
            # A layout slide as it was asked for — what update_slide re-sends, changed.
            source = str(f["source"])
            out.append(f"  layout source: {source[:1500]}{' …' if len(source) > 1500 else ''}")
        for n in f.get("nodes") or []:
            box = f"({n.get('x')},{n.get('y')} {n.get('w')}×{n.get('h')})"
            bits = [f"  {n.get('name')}", n.get("type", ""), box]
            if n.get("in"):
                bits.append(f"in {n['in']}")
            if "text" in n:
                bits.append(json.dumps(n["text"], ensure_ascii=False))
                bits.append(f"{n.get('font')} {n.get('size')}px {n.get('color', '')}".strip())
                if n.get("align"):
                    bits.append(f"align {n['align']}")
            else:
                if n.get("fill"):
                    bits.append(f"fill {n['fill']}")
                if n.get("radius"):
                    bits.append(f"radius {n['radius']}")
                if n.get("stroke"):
                    bits.append(f"stroke {n['stroke']}")
            if n.get("opacity") is not None:
                bits.append(f"opacity {n['opacity']}")
            out.append("  ".join(str(b) for b in bits if b != ""))
    return "\n".join(out)


def _dedupe_design_name(designs_dir, name, fmt):
    """A base name whose `<name>.<fmt>` and `<name>.fig` are both free under
    `designs_dir`, so a fresh render never overwrites an existing design:
    `launch`, else `launch-2`, `launch-3`, … The render output and its `.fig`
    stay paired under one base. (`edit` targets an existing design — it does not
    dedupe.)"""
    def taken(base):
        return any((designs_dir / f).exists() for f in
                   (f"{base}.{fmt}", f"{base}.fig", f"{base}-slide-1.{fmt}", f"{base}.deck.json"))
    if not taken(name):
        return name
    n = 2
    while taken(f"{name}-{n}"):
        n += 1
    return f"{name}-{n}"


_SLIDE_ACTIONS = ("add_slide", "update_slide", "move_slide", "duplicate_slide", "delete_slide")
_DOCUMENT_ACTIONS = ("add_section", "update_section", "move_section", "delete_section", "update_document")
_BLOCK_KINDS = ("lead", "p", "h2", "h3", "bullets", "numbered", "callout", "quote", "stats", "chart", "table", "image",
                "columns", "cards", "pairs", "note", "nodes", "break")


def _document_source(root, name):
    """The source a document was rendered from (kept in its deck document), or None."""
    try:
        deck = json.loads((pathlib.Path(root) / f"designs/{name}.deck.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    doc = deck.get("document") if isinstance(deck, dict) and deck.get("kind") == "document" else None
    return doc if isinstance(doc, dict) and isinstance(doc.get("sections"), list) else None


def _sections_text(name, doc):
    """A document's sections as `inspect` lists them: what a section action names."""
    kind = lambda b: "p" if isinstance(b, str) else next((k for k in b if k in _BLOCK_KINDS), next(iter(b), "?")) if isinstance(b, dict) else "?"
    lines = [f"A document of {len(doc['sections'])} sections (its source is kept; a section action re-renders it in place):"]
    for i, s in enumerate(doc["sections"], 1):
        s = s if isinstance(s, dict) else {}
        lines.append(f"  {i}. {str(s.get('title') or '(untitled)')[:80]} — {', '.join(kind(b) for b in (s.get('blocks') or [])[:40]) or 'empty'}")
    lines.append(f"Change one with update_section {{name: \"{name}\", number, section: {{title?, blocks?}}}}; also add_section / "
                 f"move_section / delete_section, and update_document for its title, theme or cover.")
    return "\n".join(lines)


async def _exec_document(action, inp, workspace, name):
    """A document's own changes — a section added, rewritten, moved or removed; its title,
    look or cover changed — made on the source kept in its deck document, then rendered
    again in place (the earlier pages kept as a version). The model sends the part that
    changes, not the whole document; nothing is saved unless the render succeeds."""
    doc = await asyncio.to_thread(_document_source, workspace.root, name)
    if doc is None:
        return (f"Error: designs/{name}.deck.json isn't a document — `{action}` works on a document you rendered "
                f"({{document: …}}); a deck's slides have add_slide / update_slide.")
    sections = list(doc["sections"])

    def number(key, upto):
        v = _num(inp.get(key))
        if v is None or v < 1 or int(v) != v:
            raise ValueError(f"`{key}` is a section's number from 1, not {inp.get(key)!r} — the document has {len(sections)} sections")
        if v > upto:
            raise ValueError(f"`{key}` {int(v)}: the document has {len(sections)} sections")
        return int(v) - 1

    section = inp.get("section")
    try:
        if action in ("add_section", "update_section") and not isinstance(section, dict):
            return f"Error: `{action}` needs `section` — {{title, blocks: […]}}" + (" (or just the keys that change)." if action == "update_section" else ".")
        if action == "add_section":
            if not isinstance(section.get("blocks"), list):
                return "Error: a new section needs `blocks` — a list of blocks."
            at = number("at", len(sections) + 1) if inp.get("at") is not None else len(sections)
            sections.insert(at, section)
            intent = f"add section {at + 1}"
        elif action == "update_section":
            n = number("number", len(sections))
            sections[n] = {**(sections[n] if isinstance(sections[n], dict) else {}), **section}
            intent = f"change section {n + 1}"
        elif action == "move_section":
            n, to = number("number", len(sections)), number("to", len(sections))
            sections.insert(to, sections.pop(n))
            intent = f"move section {n + 1}"
        elif action == "delete_section":
            n = number("number", len(sections))
            if len(sections) == 1:
                return "Error: a document keeps at least one section."
            sections.pop(n)
            intent = f"delete section {n + 1}"
        else:
            change = inp.get("document")
            if not isinstance(change, dict) or not change:
                return "Error: `update_document` needs `document` — the keys that change, e.g. {title, theme, cover}."
            if "sections" in change:
                return "Error: `update_document` changes the document's own keys — its `sections` have add_section / update_section / move_section / delete_section."
            doc = {k: v for k, v in {**doc, **change}.items() if v is not None}
            intent = "change the document"
    except ValueError as e:
        return f"Error: {e}."
    return await _render_document({"spec": {"document": {**doc, "sections": sections}}, "replace": True,
                                   "intent": inp.get("intent") or intent, "discard_edits": inp.get("discard_edits")}, workspace, name)


async def _run_tool(*argv, timeout=60):
    """A command-line tool run to its end → (exit code, stdout)."""
    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    return proc.returncode, out


_PDF_TEXT_PAGE = 5000       # characters of one page's text handed to the model
_PDF_TEXT_ALL = 16000       # …and of one reply: with what follows it, under the 20,000 at which a reply is filed (spill.SPILL_AT)
_PDF_PICTURES = 30          # pictures kept
_PDF_PICTURE_MIN = 200      # px on its shorter side: smaller is an icon or a rule
_PDF_TABLE_ROWS = 40        # rows of one page's tables shown as they are laid out
_PDF_LOOK_DPI = 100         # a page drawn for the model to look at
_PDF_CUT_DPI = 200          # …and a figure cut out of one, to be used again
# Letters saved as the glyphs they were drawn with: Latin ligatures (ﬁ), and Arabic in its
# presentation forms (ﻟ ﺎ ﻋ) — what a PDF made from Word often holds instead of the letters.
_SHAPED = re.compile("[\ufb00-\ufb06\ufb50-\ufdff\ufe70-\ufeff]+")
_SHAPED_ARABIC = re.compile("[\ufb50-\ufdff\ufe70-\ufeff]")
_DIRECTION_MARKS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")     # what pdftotext wraps right-to-left text in


def _laid_out_tables(page):
    """The rows of a page's tables, from its text as laid out (`pdftotext -layout`): runs of
    lines that are three or more cells apart, two of them figures — each row's cells joined
    by " | ". Reading order keeps a paragraph whole and takes a table apart cell by cell;
    this is the other half."""
    cells = lambda line: [c for c in re.split(r"\s{2,}", line.strip()) if c]
    figure = lambda c: (len(c) <= 16 and bool(re.search(r"\d", c))) or c in ("-", "–", "—")
    lines = page.split("\n")
    row = [len(c) >= 3 and sum(map(figure, c)) >= 2 for c in map(cells, lines)]
    out, i = [], 0
    while i < len(lines):
        if not row[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(lines) and (row[j + 1] or (j + 2 < len(lines) and not lines[j + 1].strip() and row[j + 2])):
            j += 1
        rows = [k for k in range(i, j + 1) if row[k]]
        if len(rows) >= 3:
            head = next((k for k in range(i - 1, max(-1, i - 3), -1) if lines[k].strip()), None)
            if head is not None and len(cells(lines[head])) >= 3:
                rows.insert(0, head)                      # the line over them, when it is their heading
            out += ([""] if out else []) + [" | ".join(cells(lines[k])) for k in rows]
        i = j + 1
    return out[:_PDF_TABLE_ROWS]


async def _pdf_parts(inp, workspace, name):
    """An existing PDF taken apart to be made again as a document: its text, page by
    page, and its pictures saved into designs/<name>-assets/ (poppler: pdftotext,
    pdfimages). The model reads this, then renders a `document` that uses them.

    The words are read in reading order — "as laid out" set a two-column page's columns
    side by side on every line — and a page's tables are added from the laid-out reading,
    which alone keeps a row together. With `page`, one page is drawn to look at, and with
    `area` a figure is cut out of it (`_pdf_page`)."""
    import hashlib, tempfile, unicodedata
    src = inp.get("path") or inp.get("src")
    if not isinstance(src, str) or not src.strip():
        return 'Error: `extract` needs `path` — a PDF in the workspace, e.g. "attachments/report.pdf".'
    try:
        path = _resolve_path(src, workspace.root)
    except ValueError as e:
        return f"Error: {e}"
    if not path.is_file():
        return f"Error: {src} doesn't exist in the workspace."
    if path.suffix.lower() != ".pdf":
        return f"Error: {src} isn't a PDF — `extract` reads a PDF's text and pictures."
    if inp.get("page") is not None:
        return await _pdf_page(inp, workspace, name, path, src)
    # `pages`: reading on — a long PDF's text comes a reply's worth at a time.
    span = None
    if inp.get("pages") is not None:
        v, m = inp["pages"], None
        if isinstance(v, int) and not isinstance(v, bool):
            span = (v, v)
        elif isinstance(v, (list, tuple)) and len(v) in (1, 2) and all(isinstance(n, int) and not isinstance(n, bool) for n in v):
            span = (v[0], v[-1])
        elif isinstance(v, str) and (m := re.fullmatch(r"\s*(\d+)\s*(?:(?:[-–—:]|to)\s*(\d+))?\s*", v)):
            span = (int(m[1]), int(m[2] or m[1]))
        if not span or not 1 <= span[0] <= span[1]:
            return 'Error: `pages` is the pages to read — a number, or a range like "5-8".'
    only = ("-f", str(span[0]), "-l", str(span[1])) if span else ()
    root = pathlib.Path(workspace.root)
    assets_rel = f"designs/{name}-assets"
    letters = lambda t: _SHAPED.sub(lambda m: unicodedata.normalize("NFKC", m[0]), _DIRECTION_MARKS.sub("", t))
    try:
        _, info = await _run_tool("pdfinfo", str(path), timeout=20)
        info = info.decode("utf-8", "replace")
        length = int((re.search(r"^Pages:\s+(\d+)", info, re.M) or [0, 0])[1])
        if span and length and span[0] > length:
            return f"Error: {src} has {length} pages."
        code, text = await _run_tool("pdftotext", *only, "-enc", "UTF-8", str(path), "-", timeout=90)
        if code != 0:
            return f"Error: couldn't read {src} — it may be damaged or locked with a password."
        _, laid = await _run_tool("pdftotext", *only, "-layout", "-enc", "UTF-8", str(path), "-", timeout=90)
        text = text.decode("utf-8", "replace")
        shaped = len(_SHAPED_ARABIC.findall(text))
        pages = [letters(p).strip() for p in text.split("\f")]
        tables = [_laid_out_tables(letters(p)) for p in laid.decode("utf-8", "replace").split("\f")]
        # A scan is pictures of its pages: not pictures to use again.
        paper = re.search(r"^Page\s+(?:\d+\s+)?size:\s+([\d.]+) x ([\d.]+)", info, re.M)
        scan = not any(pages)
        shape = float(paper[1]) / float(paper[2]) if scan and paper and float(paper[2]) else None
        with tempfile.TemporaryDirectory() as tmp:
            if not span:                                  # (reading on: its pictures were taken the first time)
                await _run_tool("pdfimages", "-all", str(path), str(pathlib.Path(tmp) / "img"), timeout=120)
            found = sorted(pathlib.Path(tmp).iterdir())

            def keep():
                seen, kept = set(), []
                for f in found:
                    ext = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg"}.get(f.suffix.lower())
                    if not ext or len(kept) >= _PDF_PICTURES:
                        continue
                    data = f.read_bytes()
                    size, digest = _image_size(data), hashlib.sha1(data).hexdigest()
                    if not size or min(size) < _PDF_PICTURE_MIN or digest in seen or len(data) > _DESIGN_IMAGE_MAX:
                        continue
                    if shape and max(size) >= 900 and abs(size[0] / size[1] - shape) < 0.02 * shape:
                        continue                          # a page of a scan
                    seen.add(digest)
                    (root / assets_rel).mkdir(parents=True, exist_ok=True)
                    rel = f"{assets_rel}/picture-{len(kept) + 1}.{ext}"
                    (root / rel).write_bytes(data)
                    kept.append((rel, size))
                return kept
            pictures = await asyncio.to_thread(keep)
    except FileNotFoundError:
        return "Error: reading a PDF's parts needs poppler (pdftotext, pdfimages) in this agent's image."
    except asyncio.TimeoutError:
        return f"Error: {src} took too long to read — try a smaller PDF."
    field = lambda key: (re.search(rf"^{key}:[ \t]+(\S.*)$", info, re.M) or [None, ""])[1].strip()
    while pages and not pages[-1]:
        pages.pop()
    look = f'extract {{"path": {json.dumps(src, ensure_ascii=False)}, "page": 1}}'
    count = field("Pages") or str(len(pages))
    first = span[0] if span else 1
    end = first + len(pages) - 1
    if span:
        lines = [f"{src} — pages {first}–{end} of {count}." if end > first else f"{src} — page {first} of {count}."]
        if not any(pages):
            lines.append("There is no text on them.")
    else:
        lines = [f"{src} — {count} page{'' if count == '1' else 's'}" + (f", titled \"{field('Title')}\"" if field("Title") else "")
                 + (f", {field('Page size')}" if field("Page size") else "") + "."]
    total, held = 0, []
    for n, page in enumerate(pages, first):
        if not page:
            continue
        shown = page[:_PDF_TEXT_PAGE]
        rows = tables[n - first] if n - first < len(tables) else []
        # A reply's worth: the model reads what is here, and asks for the pages after it.
        if total and total + len(shown) + sum(map(len, rows)) > _PDF_TEXT_ALL:
            lines.append(f"\n(Pages {n}–{end} are not shown here: extract {{\"path\": {json.dumps(src, ensure_ascii=False)}, "
                         f"\"pages\": \"{n}-{end}\"}} reads on.)")
            break
        total += len(shown) + sum(map(len, rows))
        held.append(n)
        lines.append(f"\nPage {n}:\n{shown}" + (" […]" if len(page) > len(shown) else ""))
        if rows:
            lines.append("Its tables, as they are laid out:\n" + "\n".join(rows))
    if span and held:      # its first line names the pages it holds, not the range that was asked for
        lines[0] = f"{src} — pages {held[0]}–{held[-1]} of {count}." if held[-1] > held[0] else f"{src} — page {held[0]} of {count}."
    if span:
        if shaped > 20:
            lines.append(f"\nIts text can't be trusted as it stands (Arabic saved as drawn glyphs): take the wording from the pages themselves — {look} shows one.")
        return "\n".join(lines)
    if scan:
        lines.append(f"It is a scan — pictures of its pages, with no text in it. Look at a page with {look} (then 2, 3 …) "
                     "and take its words from what you see.")
    elif shaped > 20:
        lines.append(f"\nIts text can't be trusted as it stands: the Arabic is saved as the glyphs it was drawn with, so letters "
                     f"may be doubled and lines out of order. Take the wording from the pages themselves — {look} shows one.")
    if pictures:
        lines.append("\nIts pictures, saved to use again:")
        lines += [f"  {rel} ({w}×{h})" for rel, (w, h) in pictures]
        lines.append(f"Use one in a document as {{\"image\": \"{pictures[0][0]}\", \"caption\": \"…\"}} (or as the cover's `image`).")
    elif not scan:
        lines.append("\nIt has no pictures stored in it (photos of 200px or more).")
    if not scan:
        lines.append(f"A chart or a diagram that is drawn in the PDF is not a picture in it. To use one again, look at its page — {look} — "
                     "and cut it out: the same with \"area\": [left, top, width, height], each a part of the page from 0 to 1.")
    lines.append("To redesign it: write its content as a `document` — its own sections and words, better organised — and render that.")
    return "\n".join(lines)


async def _pdf_page(inp, workspace, name, path, src):
    """One page of a PDF drawn for the model to look at — or, with `area`, that part of it
    cut out and saved to designs/<name>-assets/figure-<n>.png: a chart or a diagram that is
    drawn in the PDF (so not among its pictures), to be used again in the redesign."""
    import tempfile
    page, area = inp.get("page"), inp.get("area")
    how = "`area` is [left, top, width, height], each a part of the page from 0 to 1 — e.g. [0.1, 0.25, 0.8, 0.3]"
    if isinstance(page, str) and page.strip().isdigit():
        page = int(page)
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        return "Error: `page` is the PDF's page number, from 1."
    if area is not None:
        if isinstance(area, str):
            try:
                area = json.loads(area)
            except ValueError:
                return f"Error: {how}."
        if not (isinstance(area, (list, tuple)) and len(area) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in area)):
            return f"Error: {how}."
        x, y, w, h = map(float, area)
        if not (0 <= x < 1 and 0 <= y < 1 and w >= 0.02 and h >= 0.02 and x + w <= 1.001 and y + h <= 1.001):
            return f"Error: {how} — this one runs off the page."
    which = ("-f", str(page), "-l", str(page))
    try:
        _, info = await _run_tool("pdfinfo", *which, str(path), timeout=20)
        info = info.decode("utf-8", "replace")
        count = int((re.search(r"^Pages:\s+(\d+)", info, re.M) or [0, 0])[1])
        if count and page > count:
            return f"Error: {src} has {count} pages."
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "page"
            if area is None:
                await _run_tool("pdftoppm", "-r", str(_PDF_LOOK_DPI), *which, "-jpeg", "-singlefile", str(path), str(out), timeout=60)
                made = out.with_suffix(".jpg")
            else:
                paper = re.search(r"^Page\s+(?:\d+\s+)?size:\s+([\d.]+) x ([\d.]+)", info, re.M)
                if not paper:
                    return f"Error: couldn't read the size of page {page} of {src}."
                W, H = (round(float(v) * _PDF_CUT_DPI / 72) for v in paper.groups())
                await _run_tool("pdftoppm", "-r", str(_PDF_CUT_DPI), *which, "-x", str(round(x * W)), "-y", str(round(y * H)),
                                "-W", str(round(w * W)), "-H", str(round(h * H)), "-png", "-singlefile", str(path), str(out), timeout=60)
                made = out.with_suffix(".png")
            if not made.is_file():
                return f"Error: page {page} of {src} couldn't be drawn — it may be damaged or locked with a password."
            data = await asyncio.to_thread(made.read_bytes)
    except FileNotFoundError:
        return "Error: reading a PDF's pages needs poppler (pdfinfo, pdftoppm) in this agent's image."
    except asyncio.TimeoutError:
        return f"Error: page {page} of {src} took too long to draw."
    said = json.dumps(src, ensure_ascii=False)
    if area is None:
        text = (f"Page {page} of {count or '?'} of {src}. To use a chart or a diagram on it again, cut it out: extract "
                f"{{\"path\": {said}, \"page\": {page}, \"area\": [left, top, width, height]}} — each a part of the page from 0 to 1 "
                f"(its top-left quarter is [0, 0, 0.5, 0.5]).")
        media = "image/jpeg"
    else:
        folder = pathlib.Path(workspace.root) / "designs" / f"{name}-assets"

        def save():
            folder.mkdir(parents=True, exist_ok=True)
            n = 1 + len(list(folder.glob("figure-*.png")))
            (folder / f"figure-{n}.png").write_bytes(data)
            return n
        n = await asyncio.to_thread(save)
        rel, size = f"designs/{name}-assets/figure-{n}.png", _image_size(data) or (0, 0)
        text = (f"Saved {rel} ({size[0]}×{size[1]}) — page {page} of {src}, cut at {[round(v, 3) for v in (x, y, w, h)]}. "
                f"Check it holds the whole figure and nothing beside it; if it doesn't, cut again with the area put right. "
                f"Use it in a document as {{\"image\": \"{rel}\", \"caption\": \"…\"}}.")
        media = "image/png"
    if len(data) > _DESIGN_QA_MAX:
        return text
    return {"_model": [{"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()}},
                       {"type": "text", "text": text}]}


def _prepare_slide(slide, settings, root):
    """A new or rebuilt slide, made ready the way a deck's slides are (_prepare_deck):
    → (slide, the deck settings with their images resolved, error)."""
    if not isinstance(slide, dict) or not (slide.get("layout") or isinstance(slide.get("nodes"), list)):
        return None, None, ('Error: `slide` is a layout slide ({"layout": "bullets", "title": …, "bullets": […]}) '
                            'or a hand-built one ({"nodes": […], "fill"?}).')
    spec, err, _ = _prepare_deck({"deck": {**settings, "slides": [slide]}}, None, root)
    if err:
        return None, None, err
    deck = spec["deck"]
    return deck.pop("slides")[0], deck, None


async def _exec_slides(action, inp, workspace, name):
    """A deck's slide actions — add / update (or its notes, title, transition) / move /
    duplicate / delete — run on the saved .fig through the service, like `edit`
    (design/deck.py). Slides are numbered from 1 here, as the user counts them."""
    from cycls._agent import design
    from cycls._agent.design import deck as decks
    root, subject = workspace.root, getattr(workspace, "subject", None)
    fig_path, fig_rel, deck_path, _ = decks.paths(root, name)
    if not fig_path.is_file():
        return f"Error: {fig_rel} doesn't exist — slide actions work on a deck you rendered."
    doc = await asyncio.to_thread(decks.read_doc, deck_path)
    # A slide's photos may be named, not saved yet: {"stock": "…"} → a workspace file.
    credits = []
    if isinstance(inp.get("slide"), dict):
        from cycls._agent.design import stock
        credits, err = await stock.resolve(inp["slide"], root)
        if err:
            return err

    def number(key):
        v = _num(inp.get(key))
        if v is None or v < 1 or int(v) != v:
            raise ValueError(f"`{key}` is a slide number from 1, not {inp.get(key)!r}")
        return int(v) - 1

    def slide_op(kind, extra):
        settings = doc.get("settings") or ({"size": doc["size"]} if doc.get("size") else {})
        slide = dict(inp.get("slide") or {})
        for k in ("notes", "title", "transition"):
            if inp.get(k) is not None and k not in slide:
                slide[k] = inp[k]
        slide, resolved, err = _prepare_slide(slide, settings, root)
        if err:
            raise ValueError(err.removeprefix("Error: "))
        return {"op": kind, **extra, "slide": slide, "deck": resolved}

    try:
        if action == "add_slide":
            op = slide_op("slide_add", {"at": number("at")} if inp.get("at") is not None else {})
            what = "Slide added" + (f" at position {op['at'] + 1}" if "at" in op else " at the end")
        elif action == "update_slide":
            index = number("number")
            if inp.get("slide") is not None:
                op, what = slide_op("slide_update", {"index": index}), f"Slide {index + 1} rebuilt"
            else:
                meta = {k: inp[k] for k in ("notes", "title", "transition") if inp.get(k) is not None}
                if not meta:
                    return "Error: `update_slide` needs `slide` (the new slide) or `notes` / `title` / `transition`."
                op, what = {"op": "slide_meta", "index": index, **meta}, f"Slide {index + 1}'s {', '.join(meta)} updated"
        elif action == "move_slide":
            op = {"op": "slide_move", "index": number("number"), "to": number("to")}
            what = f"Slide {op['index'] + 1} moved to position {op['to'] + 1}"
        elif action == "duplicate_slide":
            op = {"op": "slide_duplicate", "index": number("number")}
            what = f"Slide {op['index'] + 1} duplicated (the copy is slide {op['index'] + 2})"
        else:
            op = {"op": "slide_delete", "index": number("number")}
            what = f"Slide {op['index'] + 1} deleted"
    except ValueError as e:
        return f"Error: {e}."
    try:
        r = await decks.apply_ops(root, name, [op], user_id=subject, preview=True)
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: {action} failed on {fig_rel} — {e}. Nothing was changed."
    count = len(r.get("slides") or [])
    ack = (f"{what}. {fig_rel} now has {count} slide{'s' if count != 1 else ''}; the deck viewer and "
           f"the exports beside it update in a few seconds." + _layout_check(r.get("lint"), "pptx"))
    for credit in credits:
        ack += f" {credit}."
    command = {"type": "ui", "action": "design_command", "path": fig_rel, "script": r.get("script"),
               "version": r.get("version")}   # what the file is now — an open editor's saves go on from it
    if intent := inp.get("intent"):
        command["intent"] = str(intent)[:80]
    # Replayed live in an open editor, and the deck (re)opened in the viewer so the
    # user sees the change even when it wasn't showing.
    ui = [command, {"type": "ui", "action": "open_canvas", "path": f"designs/{name}.deck.json", "name": f"{name}.deck.json"}]
    blocks, total = [], 0
    for i, jpg in zip(r.get("touched") or [], r.get("previews") or []):
        if total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        blocks += [{"type": "text", "text": f"Slide {i + 1}:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if blocks:
        ack += " The changed slide is attached — check it matches the rest of the deck; fix it with update_slide if not."
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    return {"_model": ack, "_ui": ui}


async def _exec_design(inp, workspace):
    """Render a design via the shared cycls-design service, save the image + the
    editable `.fig` into the workspace, and open the image on the canvas. Two
    channels: the model reads a short ack; the client opens the render (same
    open_canvas event the Canvas tool and browser screenshots use)."""
    from cycls._agent import design
    # A model may hand a large nested argument over as its JSON text: read as the object.
    inp = dict(inp)
    for key in ("spec", "ops", "slide"):
        v = inp.get(key)
        if isinstance(v, str) and v.strip()[:1] in ("{", "["):
            try:
                inp[key] = json.loads(v)
            except json.JSONDecodeError as e:
                # Said where it breaks: "needs a `spec` object" told a model nothing, and a
                # 6,000-token document was written out again, blind.
                at = e.pos
                near = v[max(0, at - 60):at + 40].replace("\n", " ")
                # (Cut short: it stops where more was expected, or inside a string that never closes.)
                cut = at >= len(v.rstrip()) - 1 or e.msg.startswith("Unterminated string")
                why = ("it is cut off before its end — the call ran out of room" if cut else
                       f"{e.msg} at character {at} of {len(v)}, near: …{near}… (most often a quote left unescaped inside a string, or a line break in one)")
                more = (" A long document need not come in one call: render its first sections, then add_section for each of the rest."
                        if key == "spec" else "")
                return (f"Error: `{key}` came as text that isn't valid JSON — {why}. Nothing was done. "
                        f"Send `{key}` again as an object, with that put right.{more}")
    action = (inp.get("action") or "render").lower()
    fmt = (inp.get("format") or "png").lower()
    if fmt not in _DESIGN_EXTS:
        return f"Error: unknown format {fmt!r} (png, jpg, webp, svg, pptx)."
    scale = inp.get("scale") or 2
    # Base name only, no extension the model may have tacked on.
    name = _safe_filename(inp.get("name") or "design", "design").rsplit(".", 1)[0] or "design"
    subject = getattr(workspace, "subject", None)
    # `edit` changes a saved design. The service runs the script on the .fig first —
    # the editor's own plugin API, headless — so a script that throws is the model's
    # error now (it used to fail silently inside the browser), and a success is saved
    # and re-exported whether or not an editor is open. Then a UI event replays the
    # same script in the live editor, where the user watches the Super cursor make it.
    if action in _SLIDE_ACTIONS:
        return await _exec_slides(action, inp, workspace, name)
    if action in _DOCUMENT_ACTIONS:
        return await _exec_document(action, inp, workspace, name)
    if action == "extract":
        if not inp.get("name") and isinstance(inp.get("path"), str):
            name = _safe_filename(pathlib.PurePosixPath(inp["path"].replace("\\", "/")).stem or "pdf", "pdf")
        return await _pdf_parts(inp, workspace, name)
    if action in ("edit", "inspect"):
        rel = f"designs/{name}.fig"
        fig_path = pathlib.Path(workspace.root) / rel
        if not fig_path.is_file():
            return (f"Error: {rel} doesn't exist — `{action}` works on a design you rendered; "
                    f"`render` creates one.")
    # `inspect` lists a design's frames and their named nodes — what `edit` ops name.
    page = str(inp.get("page") or "").strip() or None      # the page an inspect / edit is about
    if action == "inspect":
        try:
            o = await design.outline(await asyncio.to_thread(fig_path.read_bytes), user_id=subject, page=page)
        except design.Unavailable as e:
            return f"Error: design unavailable — {e}"
        except Exception as e:
            return f"Error: couldn't inspect {rel} — {e}"
        text = _outline_text(rel, o["frames"], o["pages"], o["page"])
        doc = await asyncio.to_thread(_document_source, workspace.root, name)
        return f"{_sections_text(name, doc)}\n\n{text}" if doc else text
    # `edit` changes a saved design: named `ops` (the normal way) or a raw `script`.
    # The service applies it to the .fig first — the editor's own plugin API, headless
    # — so an edit that fails is the model's error now (it used to fail silently in
    # the browser), and a success is saved and re-exported whether or not an editor is
    # open. Then a UI event replays the same script in the live editor, where the user
    # watches the Super cursor make it. The model gets the result back to check.
    if action == "edit":
        script, ops = inp.get("script"), inp.get("ops")
        if not ops and not script:
            return ("Error: `edit` needs `ops` — e.g. [{\"op\":\"set_text\",\"node\":\"headline\",\"text\":\"…\"}] "
                    "(Design inspect lists the node names) — or a raw `script`.")
        credits = []
        if ops:
            from cycls._agent.design import stock
            credits, err = await stock.resolve(ops, workspace.root)   # {"stock": "…"} → a saved photo
            if err:
                return err
            ops, err = await asyncio.to_thread(_prepare_ops, ops, workspace.root)
            if err:
                return err
        from cycls._agent.design.deck import lock
        from cycls._agent.design.store import Stale, read_fig, write_fig
        async with lock(fig_path):                          # one change at a time per design
            for attempt in (1, 2):
                data, base = await asyncio.to_thread(read_fig, workspace.root, rel)
                try:
                    r = await design.apply(data, script=None if ops else script,
                                           ops=ops or None, preview=True, user_id=subject, page=page)
                except design.Unavailable as e:
                    return f"Error: design unavailable — {e}"
                except Exception as e:
                    return (f"Error: the edit failed on {rel} — {e}. Nothing was changed; fix the "
                            f"{'ops' if ops else 'script'} (Design inspect lists the nodes) and try again.")
                try:   # the person may have saved in the editor meanwhile: apply to that, once
                    version = await write_fig(workspace.root, rel, r["fig"], base=base, by="agent", reason="agent",
                                              intent=inp.get("intent"))
                    break
                except Stale:
                    if attempt == 2:
                        return (f"Error: {rel} changed while the edit was being made (it's being edited "
                                f"by hand). Nothing was changed; inspect it again, then edit.")
        from cycls._agent.design import refresh
        pages, ended = r.get("pages") or [], r.get("page") or ""
        made_page = any(isinstance(op, dict) and op.get("op") in ("page_add", "page_duplicate") for op in ops or [])
        # The image beside it follows — or is made; a page an edit made gets its own.
        refresh.schedule(workspace.root, rel, subject, ensure=True, pages=made_page)
        ui = {"type": "ui", "action": "design_command", "path": rel, "script": r.get("script") or script,
              "version": version}   # what the file is now — an open editor's saves go on from it
        if len(pages) > 1 or made_page:
            ui["page"] = r.get("started") or ""   # the page it is made on: an open editor shows it first
        if any(isinstance(op, dict) and str(op.get("op") or "").startswith("page_") for op in ops or []):
            # Pages added, copied, renamed or removed: an open editor re-opens the saved
            # file on the page the edit ended on — page surgery isn't replayed live.
            ui["reload"], ui["page"] = True, ended
        if intent := inp.get("intent"):
            ui["intent"] = str(intent)[:80]   # shown on the live "Super" cursor
        if len(pages) > 1:
            place = next((n for n, p in enumerate(pages, 1) if p["name"] == ended), 1)
            image = f"designs/{refresh.page_file(name, place, 'png')}"
            on = (f" on page {json.dumps(ended, ensure_ascii=False)} — the design's pages are now "
                  + ", ".join(json.dumps(p["name"], ensure_ascii=False) for p in pages))
        else:
            image, on = f"designs/{name}.png etc.", ""
        ack = (f"Edit applied and saved to {rel}{on}; the image beside it ({image}) "
               f"re-exports in a few seconds. If the design is open in the editor, the Super "
               f"cursor replays the change live there." + _layout_check(r.get("lint"), "png"))
        for credit in credits:
            ack += f" {credit}."
        if not r.get("preview") or len(r["preview"]) > _DESIGN_QA_MAX:
            return {"_model": ack, "_ui": ui}
        ack += (" The edited design is attached — check the change landed as intended and "
                "nothing else moved or collides; if not, edit again.")
        return {"_model": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": base64.b64encode(r["preview"]).decode()}},
                           {"type": "text", "text": ack}],
                "_ui": ui}
    notes, size = [], None
    try:
        if action == "render":
            if not isinstance(inp.get("spec"), dict):
                return "Error: `render` needs a `spec` object, e.g. {size:[1080,1080], fill:'#0f172a', nodes:[...]}."
            if isinstance(inp["spec"].get("document"), dict):
                return await _render_document(inp, workspace, name)
            root = workspace.root   # reads the brand kit + any image files: off the loop
            # Photos named rather than saved — {"stock": "coffee beans"} — are found and
            # saved to the workspace first, so the spec below sees ordinary files.
            from cycls._agent.design import stock
            credits, err = await stock.resolve(inp["spec"], root)
            if err:
                return err
            spec, err, notes = await asyncio.to_thread(lambda: _prepare_spec(inp["spec"], _load_brand(root), root))
            if err:
                return err
            notes = [*notes, *(f"{c}." for c in credits)]
            if isinstance(spec.get("deck"), dict):
                n_frames, size = len(spec["deck"]["slides"]), spec["deck"]["size"]
            elif isinstance(spec.get("pages"), list):
                # Several pages: one design, each page's own image (never a carousel or a deck file).
                if fmt in _DECK_EXTS:
                    return (f"Error: a design of several pages renders to an image (png, jpg, webp, svg) — "
                            f"each page is downloaded as PDF or PowerPoint from the canvas. Render it as png.")
                n_frames, size = 1, None
            else:
                frames = spec["frames"] if isinstance(spec.get("frames"), list) and spec["frames"] else [spec]
                n_frames, size = len(frames), frames[0].get("size")
            # Several frames in a raster format are a carousel: every slide comes back.
            r = await design.render(spec, fmt=fmt, scale=scale, user_id=subject,
                                    every=n_frames > 1 and fmt not in _DECK_EXTS)
            notes = [*notes, *r.notes]
        elif action == "script":
            if not inp.get("script"):
                return "Error: `script` needs a `script` string ending in console.log('__FRAME__'+id)."
            r = await design.evaluate(inp["script"], fmt=fmt, scale=scale, user_id=subject)
        else:
            return f"Error: unknown design action {action!r} (render or script)."
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: design {action} failed — {type(e).__name__}: {e}"
    image, fig, preview, lint = r.image, r.fig, r.preview, r.lint
    if len(r.pages) > 1:
        return await _save_pages(r, name, fmt, workspace, notes)
    count = max(len(r.previews), len(r.slides), 1)

    # Never clobber an earlier design: if this base name is taken, bump it
    # (launch → launch-2 → …). To CHANGE an existing design, the model uses `edit`.
    requested = name
    name = _dedupe_design_name(pathlib.Path(workspace.root) / "designs", name, fmt)
    root = pathlib.Path(workspace.root)
    (root / "designs").mkdir(parents=True, exist_ok=True)
    if len(r.images) > 1:
        # A carousel: one image per slide, <name>-slide-N (what gets posted, in order).
        saved = [f"designs/{name}-slide-{n}.{fmt}" for n in range(1, len(r.images) + 1)]
        for rel_n, data in zip(saved, r.images):
            await asyncio.to_thread((root / rel_n).write_bytes, data)
        rel = saved[0]
    else:
        saved = [rel := f"designs/{name}.{fmt}"]
        await asyncio.to_thread((root / rel).write_bytes, image)
    # The .fig is the durable, editable source of truth (opened by a drag-editor
    # later); saved beside the render but not itself shown on the canvas.
    fig_rel = f"designs/{name}.fig"
    await asyncio.to_thread((root / fig_rel).write_bytes, fig)
    if count > 1:
        # A deck (or carousel) gets its deck document: what the canvas opens to show
        # and present it. The slides' titles, notes and transitions live in the .fig.
        deck = {"type": "cycls.deck", "version": 1, "fig": fig_rel, "size": size,
                "slides": count, "exports": saved}
        if action == "render" and isinstance(spec.get("deck"), dict):
            from cycls._agent.design.deck import settings_of
            deck["settings"] = settings_of(spec["deck"])      # what a new slide is laid out with
            if r.dir and "dir" not in deck["settings"]:
                deck["settings"]["dir"] = r.dir                  # its bilingual slides' direction
        await asyncio.to_thread((root / f"designs/{name}.deck.json").write_text,
                                json.dumps(deck, indent=2), "utf-8")
    note = (f" (named '{name}' so it doesn't overwrite the existing '{requested}')"
            if name != requested else "")
    kb = (sum(map(len, r.images)) if len(saved) > 1 else len(image)) // 1024
    if len(saved) > 1:
        what = f"Carousel saved ({count} slides: {saved[0]} … {saved[-1]}, {kb} KB{note})"
    elif count > 1:
        what = f"Deck saved ({rel}, {count} slides, {kb} KB{note})"
    else:
        what = f"Design saved ({rel}, {kb} KB{note})"
    # Open the EDITABLE .fig in the in-canvas editor by default — the user came to
    # DESIGN, so every render lands them in a live editor they can refine, not a flat
    # PNG. The image is still saved (for download/sharing). Fall back to opening the
    # image only where no editor is wired up (DESIGN_EDITOR_URL unset).
    editor = bool(os.environ.get("DESIGN_EDITOR_URL"))
    if count > 1:
        # A deck (or carousel) opens in the deck viewer: its slides, Present, the
        # downloads, and Edit into the editor.
        deck_rel = f"designs/{name}.deck.json"
        # Said plainly, because the reply used to tell the person it was "open in the
        # design editor": a carousel opens here too, and is downloaded as its images.
        downloads = "its images (a .zip), PowerPoint or PDF" if len(saved) > 1 else "PowerPoint, PDF or its images"
        ack = (f"{what}. It's OPEN in the deck viewer ({deck_rel}) — say \"the deck viewer\", not the "
               f"design editor. There the user can page through it, Present it full screen (with the "
               f"speaker notes), and download it as {downloads}"
               f"{'; the viewer has an Edit button that opens the design editor' if editor else ''}. "
               f"Editable source: {fig_rel}; change it with Design edit.")
        ui = {"type": "ui", "action": "open_canvas", "path": deck_rel, "name": f"{name}.deck.json"}
    elif editor:
        ack = (f"{what}; its editable source {fig_rel} is now OPEN in the in-canvas editor — "
               f"the user can edit it live. Tell them they can tweak it directly there, or ask "
               f"you to change it (colors, copy, layout) and you'll apply it with Design edit.")
        ui = {"type": "ui", "action": "open_canvas", "path": fig_rel, "name": f"{name}.fig"}
    else:
        ack = f"{what}, opened on the canvas. Editable source: {fig_rel}."
        ui = {"type": "ui", "action": "open_canvas", "path": saved[0], "name": saved[0].rsplit("/", 1)[-1]}
    for line in notes:
        ack += " " + line
    ack += _layout_check(lint, fmt if count == 1 else "pptx")
    # Show the model its own render, so it QAs what it made before the user judges
    # it — a check the spec alone can't give (hierarchy, overlap, legibility, typos).
    # The service's small @1x JPEG previews when it sent them — one per slide for a
    # deck (a photo-heavy @2x PNG runs several MB; a PPTX isn't an image) — else the
    # render itself if it's a raster within `read`'s bound; otherwise the ack alone.
    fix = "Design edit (the same design — don't re-render)"
    if count > 1 and r.previews:
        blocks, total = [], 0
        for n, jpg in enumerate(r.previews[:_DESIGN_QA_SLIDES], 1):
            if blocks and total + len(jpg) > _DESIGN_QA_MAX:
                break
            total += len(jpg)
            blocks += [{"type": "text", "text": f"Slide {n}:"},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(jpg).decode()}}]
        shown = len(blocks) // 2
        which = (f"All {count} slides are attached" if shown == count else
                 f"Slides 1–{shown} of {count} are attached (Design inspect lists the rest)")
        ack += (f" {which} — QA EVERY slide before you present: its headline clearly dominant; "
                "margins ~8–10%, nothing crammed at an edge; every text legible on what's behind it; "
                "nothing overlapping or cut off; copy exactly right; and the slides CONSISTENT with "
                "each other (title position, margins, palette, fonts). If anything is off, fix it "
                f"now with {fix} (ops take `frame`, the slide index from 0), then present.")
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    look, media = (preview, "image/jpeg") if preview else (image, _DESIGN_QA_TYPES.get(fmt))
    if not media or len(look) > _DESIGN_QA_MAX:
        return {"_model": ack, "_ui": ui}
    shown = "The first slide is attached" if count > 1 or fmt in _DECK_EXTS else "The render is attached"
    ack += (f" {shown} — QA it before you present: headline clearly dominant; "
            "margins ~8–10%, nothing crammed at an edge; every text legible on what's behind it; "
            "aligned, nothing overlapping or cut off; copy exactly right (spelling, names, "
            f"numbers); on-brand. If anything is off, fix it now with {fix}, then present.")
    return {"_model": [{"type": "image", "source": {"type": "base64", "media_type": media,
                                                    "data": base64.b64encode(look).decode()}},
                       {"type": "text", "text": ack}],
            "_ui": ui}


_OUTLINE_STYLE = ("font", "size", "color", "fill", "radius", "stroke", "rotation", "opacity", "align")


def _rendered_copy(root, fig_rel):
    """Where a document's .fig is kept as it was rendered — to tell, later, what was
    changed on its pages by hand."""
    import hashlib
    return pathlib.Path(root) / ".cache" / "design" / f"{hashlib.sha1(fig_rel.encode('utf-8')).hexdigest()[:16]}.rendered.fig"


def _page_changes(before, after):
    """Two outlines of a document's pages — as rendered, and as they are now — → what
    was changed, a line a page: a text's new wording, the nodes moved or restyled, the
    ones added and removed."""
    def pair(new, old):
        """A text's wording now and before, each shown from just ahead of where they part
        (a long paragraph changed near its end is not its opening twice)."""
        same = next((i for i, (x, y) in enumerate(zip(new, old)) if x != y), min(len(new), len(old)))
        start = max(0, same - 60) if max(len(new), len(old)) > 300 else 0
        start = new.rfind(" ", 0, start) + 1 if start else 0
        show = lambda t: (("…" if start else "") + t[start:start + 300] + ("…" if len(t) > start + 300 else "")).replace("\n", " ")
        return show(new), show(old)
    count = lambda n, what: f"{n} node{'' if n == 1 else 's'} {what}"
    lines = []
    if len(before) != len(after):
        lines.append(f"it had {len(before)} pages as rendered and has {len(after)} now")
    for i, (a, b) in enumerate(zip(before, after), 1):
        old = {n.get("name"): n for n in reversed(a.get("nodes") or [])}
        new = {n.get("name"): n for n in reversed(b.get("nodes") or [])}
        texts, moved, added = [], [], 0
        for key in (n.get("name") for n in b.get("nodes") or []):
            n, o = new[key], old.get(key)
            if n is None or key in texts or key in moved:
                continue
            if o is None:
                added += 1
            elif str(n.get("text") or "") != str(o.get("text") or ""):
                now, was = pair(str(n.get("text") or ""), str(o.get("text") or ""))
                texts.append(f'"{key}" now reads "{now}" (was "{was}")')
            elif (any(abs((_num(n.get(k)) or 0) - (_num(o.get(k)) or 0)) > 1 for k in ("x", "y", "w", "h"))
                  or any(n.get(k) != o.get(k) for k in _OUTLINE_STYLE)) and key not in moved:
                moved.append(key)
            new[key] = None                                   # a name used twice on a page is told once
        removed = sum(1 for key in old if key not in new)
        parts = [*texts]
        if moved:
            parts.append(", ".join(f'"{k}"' for k in moved[:5]) + (f" and {len(moved) - 5} more" if len(moved) > 5 else "") + " moved, resized or restyled")
        if added:
            parts.append(count(added, "added"))
        if removed:
            parts.append(count(removed, "removed"))
        if parts:
            lines.append(f"page {i}: " + "; ".join(parts))
    return lines[:14]


async def _edits_since_render(workspace, name):
    """What was changed on a document's pages after it was last rendered — by hand in the
    editor, or by an `edit` — and so is not in its source. None: nothing was (or the
    document was rendered before its pages were kept, and it can't be told). A list:
    lines saying what — empty when only that it changed is known."""
    from cycls._agent import design
    from cycls._agent.design.store import version_of
    root = pathlib.Path(workspace.root)
    fig_rel = f"designs/{name}.fig"

    def read():
        try:
            deck = json.loads((root / f"designs/{name}.deck.json").read_text(encoding="utf-8"))
            current = (root / fig_rel).read_bytes()
        except (OSError, ValueError):
            return None, None, None
        rendered = deck.get("rendered") if isinstance(deck, dict) else None
        try:
            base = _rendered_copy(root, fig_rel).read_bytes()
        except OSError:
            base = None
        return rendered, current, base
    rendered, current, base = await asyncio.to_thread(read)
    if not rendered or current is None or version_of(current) == rendered:
        return None
    if base is None or version_of(base) != rendered:
        return []
    subject = getattr(workspace, "subject", None)
    try:
        before = (await design.outline(base, user_id=subject, full=True))["frames"]
        after = (await design.outline(current, user_id=subject, full=True))["frames"]
    except Exception:
        return []
    # (The editor may save a file again without changing a thing: its bytes differ, its pages don't.)
    return _page_changes(before, after) or None


def _edits_hold(name, changes):
    """Why a document was not rendered again, and what to do about it."""
    detail = "".join(f"\n- {line}" for line in changes) if changes else ""
    return (f"Error: not rendered — designs/{name}'s pages were changed after it was last rendered (by hand in the editor, or by an "
            f"`edit`), and those changes are not in its source: rendering it again lays every page out from the source, without them."
            f"{detail}\nDon't drop them silently. Put the wording changes into what you send (the section they are in — or the whole "
            f"document with `render` and \"replace\": true), tell the user which of the others can't be kept (a page laid out again "
            f"keeps no moved or restyled node), and call again with \"discard_edits\": true. The edited pages stay in History either way.")


def _seen_pages(deck_path):
    """The fingerprints of a document's pages as last rendered (kept in its deck document) —
    what the model has looked at — or [] when there are none to go by."""
    try:
        hashes = json.loads(deck_path.read_text(encoding="utf-8")).get("hashes")
    except (OSError, ValueError, AttributeError):
        return []
    return [h for h in hashes if isinstance(h, str)] if isinstance(hashes, list) else []


async def _render_document(inp, workspace, name):
    """A document (a report, a proposal — anything that flows over paper pages): rendered
    by the service to a PDF and its editable pages, saved as designs/<name>.pdf / .fig
    with a deck document (kind "document") that opens the page viewer; every page comes
    back to the model to QA. `replace` re-renders the same document — its earlier .fig
    kept as a version — instead of taking a new name."""
    from cycls._agent import design
    from cycls._agent.design import stock
    from cycls._agent.design.deck import lock
    from cycls._agent.design.store import write_fig
    from cycls._agent.design.store import version_of
    root, subject = pathlib.Path(workspace.root), getattr(workspace, "subject", None)
    designs = root / "designs"
    replacing = inp.get("replace") is True and (designs / f"{name}.fig").is_file() and (designs / f"{name}.deck.json").is_file()
    # Pages edited since the last render aren't in the source: they are not laid out again
    # without a word (the model folds what it can into what it sends, and says so).
    edited = await _edits_since_render(workspace, name) if replacing else None
    if edited is not None and inp.get("discard_edits") is not True:
        return _edits_hold(name, edited)
    credits, err = await stock.resolve(inp["spec"], workspace.root)
    if err:
        return err
    source = json.loads(json.dumps(inp["spec"]["document"]))       # as it was written (a stock photo: the file it became)
    spec, err, notes = await asyncio.to_thread(lambda: _prepare_document(inp["spec"], _load_brand(workspace.root), workspace.root))
    if err:
        return err
    try:
        # Rendered again: the pages the model has seen (their fingerprints, kept with the
        # document) are said, and only the ones that differ come back to be looked at.
        known = await asyncio.to_thread(_seen_pages, designs / f"{name}.deck.json") if replacing else []
        r = await design.render(spec, fmt="pdf", scale=2, user_id=subject, sheets=True, known=known)
    except design.Unavailable as e:
        return f"Error: design unavailable — {e}"
    except Exception as e:
        return f"Error: the document didn't render — {e}"
    notes = [*notes, *(f"{c}." for c in credits), *r.notes]
    if edited is not None:
        notes.append("The pages changed after the last render were laid out again from the source; they are kept in History.")
    await asyncio.to_thread(designs.mkdir, parents=True, exist_ok=True)
    requested = name
    if not replacing:
        name = _dedupe_design_name(designs, name, "pdf")
    fig_rel, pdf_rel, deck_rel = f"designs/{name}.fig", f"designs/{name}.pdf", f"designs/{name}.deck.json"
    version = None
    if replacing:
        async with lock(root / fig_rel):
            version = await write_fig(workspace.root, fig_rel, r.fig, by="agent", reason="agent",
                                      intent=str(inp.get("intent") or "re-rendered")[:80])
    else:
        await asyncio.to_thread((root / fig_rel).write_bytes, r.fig)
    await asyncio.to_thread((root / pdf_rel).write_bytes, r.image)

    def keep_rendered():                                           # its pages as rendered: what a later change is told against
        try:
            copy = _rendered_copy(root, fig_rel)
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(r.fig)
        except OSError:
            pass
    await asyncio.to_thread(keep_rendered)
    count = max(len(r.slides), 1)
    deck = {"type": "cycls.deck", "version": 1, "kind": "document", "fig": fig_rel, "size": r.size or _PAPER["a4"],
            "slides": count, "exports": [pdf_rel], "document": source, "rendered": version_of(r.fig),
            **({"hashes": r.hashes} if r.hashes else {})}
    await asyncio.to_thread((root / deck_rel).write_text, json.dumps(deck, indent=2, ensure_ascii=False), "utf-8")
    note = f" (named '{name}' so it doesn't overwrite the existing '{requested}')" if name != requested else ""
    editor = bool(os.environ.get("DESIGN_EDITOR_URL"))
    ack = (f"Document {'re-rendered' if replacing else 'saved'} ({pdf_rel}, {count} pages, {len(r.image) // 1024} KB{note}). "
           f"It's OPEN in the page viewer ({deck_rel}): the user pages through it and downloads the PDF"
           f"{'; Edit opens the pages in the design editor' if editor else ''}. Its pages were laid out from the "
           f"content — so a small fix on one page (a word, a colour) is Design edit {{name: \"{name}\", ops}} with "
           f"`frame` = the page from 0, and anything that changes the length is made on the document: "
           f"update_section {{name: \"{name}\", number, section}} (or add_section / move_section / delete_section / "
           f"update_document) sends only what changes and renders it again in place — or this render again with "
           f"\"replace\": true. A page edited by hand does not re-flow the pages after it.")
    for line in notes:
        ack += " " + line
    ack += _layout_check(r.lint, "pptx")
    ui = {"type": "ui", "action": "open_canvas", "path": deck_rel, "name": f"{name}.deck.json"}
    if replacing:      # what is open shows the new pages: the viewer fetches them again, an editor re-opens the file
        ui = [{"type": "ui", "action": "design_command", "path": fig_rel, "script": "", "version": version, "reload": True}, ui]
    blocks, total, held = [], 0, []
    numbers = r.preview_of if r.preview_of is not None else range(1, len(r.previews) + 1)
    for n, jpg in list(zip(numbers, r.previews))[:_DESIGN_QA_SLIDES]:
        if blocks and total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        held.append(n)
        blocks += [{"type": "text", "text": f"Page {n}:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if r.preview_of is not None:
        # Rendered again: the pages that differ from what the model last saw, and no others.
        if not held:
            return {"_model": ack + " No page changed from the last render: there is nothing to look at again.", "_ui": ui}
        rest = count - len(held)
        named = (f"Page {held[0]}" if len(held) == 1 else
                 "Pages " + ", ".join(map(str, held[:-1])) + f" and {held[-1]}")
        ack += (f" {named} changed and {'is' if len(held) == 1 else 'are'} attached; the other "
                f"{'page is as you last saw it' if rest == 1 else f'{rest} pages are as you last saw them'}. "
                "QA what changed before you present: no page ends in a large hole; nothing overlaps or is cut; "
                "names, numbers and dates are exactly right. If the content needs changing again, change it; then present.")
        return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}
    if not blocks:
        return {"_model": ack, "_ui": ui}
    shown = len(blocks) // 2
    # A long document: the pages after those, twelve to a contact sheet — all of it is seen.
    sheets = []
    for pages, jpg in zip(r.sheet_pages, r.sheets):
        if total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        sheets.append(pages)
        blocks += [{"type": "text", "text": f"Pages {pages[0]}–{pages[1]}, small:" if pages[1] > pages[0] else f"Page {pages[0]}, small:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if sheets:
        which = (f"Pages 1–{shown} are attached to read, and pages {sheets[0][0]}–{sheets[-1][1]} on {len(sheets)} contact "
                 f"sheet{'' if len(sheets) == 1 else 's'} (small — for how every page is laid out, not for its words)")
    else:
        which = (f"All {count} pages are attached" if shown >= count else
                 f"Pages 1–{shown} of {count} are attached (Design inspect lists the rest)")
    ack += (f" {which} — QA them before you present: the cover reads at a glance; no page ends in a large "
            "hole that a shorter or reordered block would close; every chart and table has its caption and "
            "says something; nothing overlaps or is cut; names, numbers and dates are exactly right. If the "
            "content needs changing, render again with \"replace\": true; then present.")
    return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}


async def _save_pages(r, name, fmt, workspace, notes):
    """A render of several pages, saved: the one `.fig`, and each page's image —
    `<name>.<fmt>` the first, `<name>-page-<n>.<fmt>` the others (design/refresh.py
    keeps them in step). It opens in the editor on its first page."""
    from cycls._agent.design.refresh import page_file
    requested = name
    root = pathlib.Path(workspace.root)
    name = _dedupe_design_name(root / "designs", name, fmt)
    (root / "designs").mkdir(parents=True, exist_ok=True)
    fig_rel = f"designs/{name}.fig"
    await asyncio.to_thread((root / fig_rel).write_bytes, r.fig)
    images = r.page_images or [r.image]
    listed = []
    for place, (page, data) in enumerate(zip(r.pages, images), 1):
        rel = f"designs/{page_file(name, place, fmt)}"
        if data:
            await asyncio.to_thread((root / rel).write_bytes, data)
        frames = f", {page['frames']} slides" if page["frames"] > 1 else ""
        listed.append(f"{json.dumps(page['name'], ensure_ascii=False)} ({rel if data else 'empty'}{frames})")
    note = f" (named '{name}' so it doesn't overwrite the existing '{requested}')" if name != requested else ""
    editor = bool(os.environ.get("DESIGN_EDITOR_URL"))
    ack = (f"Design saved as ONE file, {fig_rel}{note}, with {len(r.pages)} pages: {'; '.join(listed)}. "
           + (f"It's OPEN in the in-canvas editor on its first page — the user switches pages in the "
              f"editor's Pages panel (top left), and Preview and the downloads (PNG, PDF) act on the "
              f"page in view. " if editor else "Its first page is opened on the canvas. ")
           + f"Change a page with Design edit {{page: \"<its name>\", ops}}; add or copy one with the "
             f"page_add / page_duplicate ops.")
    first = f"designs/{page_file(name, 1, fmt)}"
    ui = {"type": "ui", "action": "open_canvas", **({"path": fig_rel, "name": f"{name}.fig"} if editor
                                                     else {"path": first, "name": first.rsplit("/", 1)[-1]})}
    for line in notes:
        ack += " " + line
    ack += _layout_check(r.lint, fmt)
    blocks, total = [], 0
    labels = r.preview_pages + [""] * (len(r.previews) - len(r.preview_pages))
    for label, jpg in list(zip(labels, r.previews))[:_DESIGN_QA_SLIDES]:
        if blocks and total + len(jpg) > _DESIGN_QA_MAX:
            break
        total += len(jpg)
        blocks += [{"type": "text", "text": f"Page {json.dumps(label, ensure_ascii=False)}:"},
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.b64encode(jpg).decode()}}]
    if not blocks:
        return {"_model": ack, "_ui": ui}
    shown = len(blocks) // 2
    which = "Every page is attached" if shown == len(r.previews) else f"The first {shown} of {len(r.previews)} frames are attached"
    ack += (f" {which} — QA EACH page before you present, as a design in its own right: its headline "
            "clearly dominant; margins ~8–10%, nothing crammed at an edge or left over from another "
            "size; every text legible on what's behind it; nothing overlapping or cut off; copy exactly "
            "right; and the pages recognisably ONE piece of work (palette, fonts, voice). If anything "
            "is off, fix it now with Design edit on that page (don't re-render), then present.")
    return {"_model": [*blocks, {"type": "text", "text": ack}], "_ui": ui}


def _layout_check(lint, fmt):
    """The service's layout check of a render, as one line for the ack: what's
    wrong, where, and the fix — the mechanical backstop to the model's own look."""
    if not lint:
        return " Layout check: clean."
    slide = fmt == "pptx" or any(i.get("frame") for i in lint)

    def line(i):
        where = f"slide {int(i.get('frame') or 0) + 1}: " if slide else ""
        if i.get("page"):
            where = f"page {json.dumps(i['page'], ensure_ascii=False)}: " + where
        return f"{where}{i.get('node', '')} {i.get('issue', '')} — {i.get('fix', '')}"
    items = [line(i) for i in lint[:6]]
    more = f" (+{len(lint) - 6} more)" if len(lint) > 6 else ""
    return (f" Layout check found {len(lint)} issue{'s' if len(lint) != 1 else ''}{more}: "
            + "; ".join(items) + ". Fix these before you present.")


def _design_step(inp):
    return {"tool_name": "Design", "step": f"{inp.get('action', 'render')} {inp.get('name', '')}".strip()}


_TOOLS = {
    "browser":    Tool(lambda inp, ws, ctx=None, **_: _exec_browser(inp, ws, getattr(ctx, "chat_id", None)), _browser_step,
                       interrupted="The page is still open but may have moved; re-read it "
                                   "before acting on any element ref."),
    "design":     Tool(lambda inp, ws, **_: _exec_design(inp, ws), _design_step),
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
    "build_app":  Tool(lambda inp, ws, **_: _exec_build_app(inp, ws),
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


def interrupted_note(name, reason):
    """What the model reads for a call cancelled mid-flight. It cannot be told the
    call did not happen: a thread-dispatched tool finishes regardless, and side
    effects outside the sandbox are already out there."""
    row = _TOOLS.get(name)
    return (f"Interrupted: the run was {reason}. This call may or may not have "
            f"completed — check before repeating it."
            + (f" {row.interrupted}" if row and row.interrupted else ""))


_custom_labels, _custom_names, _custom_owners, _custom_icons = {}, {}, {}, {}
_detailed = {"build_app"}   # step row carries Request/Response, and can show a failure; MCP tools join at runtime


def register_labels(labels, names=None, owners=None, icons=None, details=()):
    """UI step labels for custom tools: name → (input dict → str), an optional display name, the connector a tool
    acts with, an icon url, and whether the row opens into request and response. Registered by LLM.run() and by
    MCP discovery so both live steps and the refetch projection render them."""
    _custom_labels.update(labels or {})
    _custom_names.update(names or {})
    _custom_owners.update(owners or {})
    _custom_icons.update(icons or {})
    _detailed.update(details)


def detailed(name):
    """Does this tool's row open into its request and response? Its result is then the model's, not the chat's."""
    return name in _detailed


def excerpt(content, limit=3000):
    """What the chat shows of a tool's result: its text, cut to `limit`."""
    s = content if isinstance(content, str) else json.dumps(content, default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "\n…"


def tool_step(name, input):
    inp = input or {}
    entry = _TOOLS.get(name)
    if entry:
        return entry.step(inp)
    shown = _custom_names.get(name, name)
    if fn := _custom_labels.get(name):
        try:
            return {"tool_name": shown, "step": str(fn(inp))}
        except Exception:
            pass
    # No label. A connector's tool (it registered a display name) shows the `context` line its server asks the model
    # for, never the raw arguments; a custom tool shows the first string, like Bash(command).
    if name in _custom_names:
        step = inp.get("context") if isinstance(inp.get("context"), str) else ""
    else:
        step = next((v for v in inp.values() if isinstance(v, str) and v.strip()), "")
    out = {"tool_name": shown, "step": step if len(step) <= 120 else step[:117] + "..."}
    if name in _custom_owners:
        out["connector"] = _custom_owners[name]
    if name in _custom_icons:
        out["icon"] = _custom_icons[name]
    return out


# ---- What a builtin risks (docs/notes/plugins-connectors.md, Approvals) ----
# `rm` and `rmdir` are not here: the sandbox shims them into the trash (30 days, restorable), so a
# delete is a move and Auto lets it run. These have no trash behind them.
_DESTRUCTIVE_CMD = re.compile(
    # Each has to be an invocation, not the word sitting in a filename, a quoted
    # string or a comment — `shredder.py` and `grep "truncate the list"` were both
    # asking for approval. `dd` is only a write when it names an `of=`.
    r"\bshred\s|\bmkfs(\.\w+)?\s|\btruncate\s+-|\bdd\s[^;|&]*\bof="
    r"|\bdrop\s+(table|database)\b"
    r"|\bgit\s+(push\s+(-f|--force)|reset\s+--hard|clean\s+-\w*[fdx])"
    r"|\bkillall\s"
    r"|\bfind\s[^\n]*\s-delete\b"   # unlinks by itself, so the rm shim never moves it to the trash
    # A redirect into a block device overwrites a disk. Outside the groups above on
    # purpose: a word boundary cannot sit between a space and `>`, so `> /dev/sda`
    # never matched while `2>/dev/null` did — the rule was inverted.
    r"|>\s*/dev/r?(sd|hd|vd|nvme|mmcblk|loop|disk)", re.I)


_READ_CMD = re.compile(r"^\s*(ls|cat|head|tail|wc|grep|rg|find|stat|file|du|df|pwd|echo|which|type|tree|sort|uniq|diff|awk|true|sed\s+-n)\b", re.I)


def _reads(cmd):
    """Every command in the line only reads, not just the first. Quoted text is data; a redirect into a file,
    a substitution or a `find` action is not a read."""
    if re.search(r"\$\(|`|[<>]\(", cmd):
        return False
    bare = re.sub(r"\d*>>?\s*/dev/null\b|&>>?\s*/dev/null\b|\d*>&[\d-]", " ", re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", cmd))
    return ">" not in bare and all(_READ_CMD.match(s) and not re.search(r"\s-(delete|exec|execdir|ok|okdir|fprint0?|fprintf|fls)\b", s)
                                   for s in re.split(r"\|\||&&|[;|&\n]", bare) if s.strip())


def risk(name, inp):
    """None (a read — always runs), "write" (follows the composer switch) or "destructive" (asks in both modes)."""
    if name == "bash":
        cmd = str(inp.get("command") or "")
        return "destructive" if _DESTRUCTIVE_CMD.search(cmd) else None if _reads(cmd) else "write"
    if name == "database":
        return {"delete": "destructive", "put": "write"}.get(inp.get("command"))
    return "write" if name in ("edit", "build_app") else None


def _gate(name, inp, ctx, step):
    """The card a builtin returns instead of running, or None to run — the builtin half of `connectors.gated`."""
    r = risk(name, inp)
    if r is None or ctx is None:
        return None
    key, chosen = approval_key(name, inp), (getattr(ctx, "modes", None) or {}).get(name)
    how = ("approved" if key in ctx.approvals else "allow" if chosen == "allow"
           else "asked" if chosen == "ask" else "auto" if getattr(ctx, "auto", True) and r != "destructive" else "asked")
    log("approval", user=ctx.user, chat_id=ctx.chat_id, tool=name, risk=r, how=how)
    if how != "asked":
        return None
    label = f"{step['tool_name']} · {step['step']}".strip(" ·")[:80]
    return {"type": "ui", "action": "confirm", "tool": name, "key": key, "label": label, "args": inp,
            "ack": f"{label} needs the user's approval — a card is asking them. End your turn now. "
                       "If they approve, make this call again with exactly the same arguments: the approval covers "
                       "this call, so any change to the arguments asks them a second time."}


@dataclass(frozen=True)
class ToolContext:
    """Who a custom tool acts for. Handlers that declare a second parameter
    receive it; one-argument handlers are called as before."""
    user: object
    workspace: object
    chat_id: str | None = None
    approvals: frozenset = frozenset()   # approval keys from the confirm card, this turn only
    auto: bool = True                    # the composer's switch: writes run on their own, destructive ones still ask
    modes: dict = None                   # the person's own allow/ask per builtin, read once a turn

    async def secret(self, name):
        return await credentials.get(self.workspace, name)


def _takes_ctx(fn):
    kinds = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    return sum(p.kind in kinds for p in inspect.signature(fn).parameters.values()) > 1


def dispatch(block, workspace, timeout, handlers=None, network=False, seen=None, ctx=None):
    """*block* is a tool_use content block (dict): {type, id, name, input}.
    Returns (step_event_dict, awaitable_result). The step carries the block's
    `id` so the FE can fold it into the `ToolStart`/`ToolArgs` it already showed.

    *seen* is the caller's per-batch set of dispatched `once` tools; omitting
    it (the default) dispatches every block. *ctx* is the `ToolContext` handed
    to handlers that take one."""
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
        step = {"type": "step", "id": bid, **entry.step(inp)}
        if card := _gate(name, inp, ctx, step):
            return step, asyncio.sleep(0, result=card)
        return step, entry.run(inp, workspace, timeout=timeout, network=network, ctx=ctx)
    if handlers and name in handlers:
        fn = handlers[name]
        return {"type": "step", "id": bid, **tool_step(name, inp)}, fn(inp, ctx) if _takes_ctx(fn) else fn(inp)
    return {"type": "tool_call", "id": bid, "tool": name, "args": inp}, asyncio.sleep(0, result=f"{name} executed")

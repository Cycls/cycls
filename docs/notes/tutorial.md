# Cycls Tutorial

Cycls is the deep-stack AI SDK for Python. Every layer of an AI agent — container, UI, LLM — is a composable primitive. Write an agent in one file, deploy it with one command.

## Prerequisites

- Python 3.10+
- Docker running
- A Cycls API key from [cycls.com](https://cycls.com) (for deployment)

## Installation

```bash
pip install cycls
```

---

## Quick Start

```python
import cycls

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You are a helpful assistant.")
)


@cycls.agent()
async def hello(context):
    async for ev in llm.run(context=context):
        yield cycls.to_ui(ev)
```

Run it:

```bash
cycls run hello.py     # local Docker + hot-reload
cycls deploy hello.py  # production
```

You now have a streaming chat interface backed by Claude, live at `http://localhost:8080` (or `https://hello.cycls.ai` for the deploy).

---

## The Three Primitives

Every Cycls agent is composed from three fluent immutable builders:

```python
image = cycls.Image().pip("numpy").copy(".env")

web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .title("My Agent")
    .analytics(True)
)

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You are a helpful assistant.")
    .tools(TOOLS)
    .on("render_image", render_image)
    .allowed_tools(["Bash", "Editor", "WebSearch"])
)


@cycls.agent(image=image, web=web)
async def my_agent(context):
    async for ev in llm.run(context=context):
        yield cycls.to_ui(ev)
```

- **`cycls.Image`** — container build config (pip, apt, copy, run commands, volume)
- **`cycls.Web`** — UI, auth, branding, CMS, analytics
- **`cycls.LLM`** — model, system prompt, tools, handlers, allowed builtins, sandbox
- **`cycls.Workspace` / `cycls.Dict`** — persistent per-user state (see [Free-tier quota recipe](#free-tier-quota-recipe))

Each decorator accepts exactly the primitives it needs:

- `@cycls.function(image=)` — non-blocking compute
- `@cycls.app(image=)` — blocking ASGI service
- `@cycls.agent(image=, web=)` — managed chat product (LLM is consumed inside the body)

---

## The Context Object

Every agent body receives a `context`:

```python
async def my_agent(context):
    context.messages      # [{"role": ..., "content": ...}]
    context.messages.raw  # full data with all parts
    context.last_message  # shortcut: last user message text
    context.user          # User(id, org_id, plan, features, ...) when auth is set
    context.prod          # True when running via .deploy(), False on .local() — gate billing/analytics
    with context.workspace():   # per-user persistent scope — enables cycls.Dict(...)
        usage = cycls.Dict("usage")
```

---

## Streaming Components

Agent bodies yield strings or structured dicts. Strings render as markdown text. Dicts unlock rich components.

### Text

```python
yield "# Heading\n\n"
yield "This is **bold** and *italic*.\n"
```

### Thinking bubbles

Multiple `thinking` yields append to the same bubble until a different type is yielded. Provider reasoning deltas (Claude extended thinking, OpenAI `delta.reasoning`) automatically map here — you get thinking bubbles for free when using `llm.run()`.

```python
yield {"type": "thinking", "thinking": "Let me "}
yield {"type": "thinking", "thinking": "analyze this..."}
yield "Here's my answer."
```

### Code blocks

```python
yield {
    "type": "code",
    "code": "def fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)",
    "language": "python",
}
```

### Streaming tables

```python
yield {"type": "table", "headers": ["Server", "Status", "CPU"]}
yield {"type": "table", "row": ["web-1", "Online", "45%"]}
yield {"type": "table", "row": ["web-2", "Online", "62%"]}
```

### Callouts, status, images

```python
yield {"type": "callout", "callout": "Operation completed!", "style": "success"}
yield {"type": "status", "status": "Connecting to database..."}
yield {"type": "image", "src": "/public/chart.png", "alt": "Chart"}
```

### UI actions

Fire-and-forget client-side triggers — nothing is rendered in the conversation and nothing is persisted in session history. Use these to drive the chat UI from agent logic.

```python
# Free-tier hit their limit? Pop the plan modal.
if over_quota(context.user):
    yield {"type": "callout", "callout": "Free tier limit reached.", "style": "warning"}
    yield {"type": "ui", "action": "open_plan_modal"}
    return
```

Supported actions:

| Action | Fields | Behavior |
|--------|--------|----------|
| `open_plan_modal` | — | Opens the pricing modal. FE auto-picks `user` vs `organization` based on the active Clerk org. |

### Component reference

| Component | Required keys | Behavior |
|-----------|---------------|----------|
| `text` | `text` | Accumulates |
| `thinking` | `thinking` | Accumulates in a bubble |
| `code` | `code`, `language` | Accumulates |
| `table` | `headers` or `row` | Row by row |
| `callout` | `callout`, `style` | Single |
| `status` | `status` | Replaces previous |
| `image` | `src` | Single |
| `ui` | `action` | Fire-and-forget client action |

HTML strings pass through for custom styling.

---

## `cycls.Image` — Container Build Config

`cycls.Image` is a fluent dict-builder. Chain methods to declare packages, files, and build commands; pass it to any decorator via `image=`.

```python
image = (
    cycls.Image()
    .pip("openai", "pandas", "numpy")
    .apt("ffmpeg", "imagemagick")
    .copy("./utils.py")
    .copy("./models/", "app/models/")
    .run("curl -fsSL https://example.com/install.sh | sh")
    .rebuild()   # force Docker cache bust
)

@cycls.function(image=image)
def my_func(x):
    from utils import helper
    ...
```

| Method | Purpose |
|---|---|
| `.pip(*pkgs)` | Install Python packages |
| `.apt(*pkgs)` | Install system packages |
| `.copy(src, dst=None)` | Bundle local files/directories (dst defaults to src) |
| `.run(cmd)` | Run a shell command during build |
| `.rebuild()` | Force Docker cache bust |

Cycls hashes image config to create deterministic Docker tags. Same inputs = instant rebuild from cache. Changed inputs = rebuild only what changed.

### Splitting secrets by audience

A common pattern is to split a project `.env` into two files so CLI-only tokens never end up in the shipped image:

```
.env              # CYCLS_API_KEY, UV_PUBLISH_TOKEN — stays on dev machine
.providers.env    # OPENAI_API_KEY, ANTHROPIC_API_KEY — ships inside the container
```

```python
image = cycls.Image().copy(".providers.env", ".env")
```

`.copy(src, dst)` renames during copy, so `.providers.env` on disk becomes `.env` inside the container. The agent's `python-dotenv` loader finds it at the expected name; your CLI auth token and publish token never enter the image.

---

## `cycls.Web` — UI, Auth, Branding

```python
web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .title("My Agent")
    .theme("default")
    .cms(brand="https://cms.cycls.ai/agents/my-agent")
    .analytics(True)
    .copy_public("./assets/logo.png", "./downloads/")
)
```

| Method | Purpose |
|---|---|
| `.auth(provider)` | Set auth provider (`cycls.Clerk()` or `cycls.JWT(...)`) |
| `.title(str)` | Browser tab + app title |
| `.brand(locale=, name=, description=, logo=, brand=, og=, favicon=)` | Static branding per locale. `logo` is the agent icon (chat hero); `brand` is the wordmark shown in the nav bar (falls back to the Cycls logo when unset); `og`/`favicon` are global |
| `.theme(name)` | `"default"` or `"dev"` |
| `.cms(brand=, explore=, token=)` | Pull branding and/or the explore menu from any CMS: plain GET URLs returning the contract JSON, optional bearer `token`. Static `.brand()`/`.explore()` win, piece by piece |
| `.analytics(bool)` | Enable usage metrics |
| `.copy_public(*files)` | Static files served at `/public` |
| `.workspaces(create="member")` | Multi-workspace mode: every user gets a personal workspace, teams are shared with role-based access, selected per request via the `X-Workspace` header. Requires `.auth(...)`. `create` sets who may create team workspaces (`"member"` or `"admin"`) — see [docs/workspaces.md](../workspaces.md) |
| `.iap(cycls.AppleIAP(...))` | Apple In-App Purchase entitlements: a StoreKit 2 signed transaction (JWS) in a header is verified offline against the bundled Apple root cert and, when valid, upgrades the request's `user.plan`. See below |

Static files land at `https://your-app.cycls.ai/public/logo.png`.

### Apple IAP entitlements

For agents that sell subscriptions through Apple In-App Purchase, `.iap(...)`
verifies the buyer on every request without a round-trip to Apple. The iOS
client sends its current StoreKit 2 transaction (a JWS Apple signed) in a
header; `cycls.AppleIAP` validates the certificate chain against the bundled
Apple Root CA G3, checks the product and expiry, and confirms the purchase's
`appAccountToken` binds to the authenticated user (so it can't be replayed by
another account). A valid entitlement upgrades that request's `user.plan`.

```python
iap = cycls.AppleIAP(
    bundle_id="com.example.app",
    products={"com.example.app.pro.monthly"},
    namespace="<uuid the client also uses>",   # UUIDv5 namespace for appAccountToken
)
web = cycls.Web().auth(cycls.Clerk()).iap(iap)
```

Gate features on the upgraded plan inside the agent via `context.user.plan`.

---

## `cycls.LLM` — Model, Tools, Loop

```python
llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You are a helpful assistant.")
    .tools(TOOLS)                              # custom tool schemas
    .on("render_image", render_image)          # handler for a custom tool
    .allowed_tools(["Bash", "Editor", "WebSearch"])
    .context(200_000)                          # model context window (default 1M)
    .max_tokens(16384)
    .price(input=3, output=15, cache_read=0.30, cache_write=6)  # USD/1M, cost tracking
)

async for ev in llm.run(context=context):
    yield cycls.to_ui(ev)
```

| Method | Purpose |
|---|---|
| `.model(str)` | `provider/model` string — `anthropic/...`, `openai/...`, `groq/...`, etc. |
| `.system(str)` | System prompt |
| `.tools(list)` | Custom tool JSON schemas |
| `.on(name, fn, label=)` | Register async handler for a custom tool; `label` (input → str) renders the step line in the UI, like `Bash(command)` — default is the input's first string value |
| `.allowed_tools(names)` | Enable Cycls-provided builtins (`Bash`, `Editor`, `WebSearch`, `DataBase`, `Canvas`) |
| `.instructions(path)` | Workspace instructions file auto-loaded into the system prompt (default `AGENT.md`; `None` disables) |
| `.skills(*dirs)` | Ship skills with the agent (dirs of `<name>/SKILL.md` folders; `None` disables skills) |
| `.context(n)` | Model context window in tokens — sets when compaction kicks in (default 1M; set it for smaller models) |
| `.max_tokens(n)` | Max output tokens per request (default 8k) |
| `.price(input=, output=, cache_read=, cache_write=)` | Token prices in USD per 1M for cost tracking; unset → costs report as $0 |
| `.thinking(spec)` | Unified reasoning level: `"low"`/`"medium"`/`"high"`, `"adaptive"` (default), or `None` |
| `.vision(bool)` | Whether the model accepts base64 media (images, PDFs). Default on; pass `False` for text-only models (GLM, most local) — attachments then stay in the workspace and the model gets a note naming the file, instead of the provider rejecting the request |
| `.web_search(mode)` | `"brave"` (default, any model, needs `BRAVE_API_KEY`) or `"native"` (Anthropic server-side) |
| `.mcp(*servers)` | Remote MCP servers via `cycls.MCP` (Anthropic models only) |
| `.bash_timeout(secs)` | Bash sandbox timeout |
| `.sandbox(network=False)` | Cut bash off from the network (`curl`, `pip`, `git`). Default on |
| `.base_url(url)` | Custom endpoint (Groq, vLLM, HUMAIN, self-hosted) |
| `.api_key(key)` | Override API key |
| `.loop(fn)` | Replace the built-in loop (see *Hooking the loop* below) |

The Bash tool runs inside a `bubblewrap` sandbox with the workspace bound at `/workspace` and a sanitized environ. Network is on by default so `curl`/`pip`/`git` just work — but a prompt-injected bash could exfiltrate anything it can read, so pass `.sandbox(network=False)` when the agent doesn't need it. See [docs/sandbox-security.md](sandbox-security.md) for the full threat model.

### Hooking the loop

`llm.run()` yields *typed events* (`cycls.events` — `TextDelta`, `Thinking`, `Step`, `Usage`, `Failed`, `Compacting`, …). The body `to_ui`s them through; pattern-match first to react:

```python
async for ev in llm.run(context=context):
    match ev:
        case cycls.events.Step(query, "Web Search"): log_search(query)
        case cycls.events.Failed(msg):               alert_ops(msg)
        case _: pass
    yield cycls.to_ui(ev)
```

Need more than a hook? `.loop(fn)` swaps the loop entirely — `fn` is an async generator with the default loop's signature that yields events. The building blocks live in `cycls.agent.harness`: `default_loop`, `make_provider`, `Session` (the message log + persistence), `build_tools`, `dispatch`, `compact`, `events`.

### Multi-provider

Cycls has one Anthropic-native path and one OpenAI Chat Completions adapter. The adapter covers every OpenAI-compatible endpoint via `base_url`:

```python
cycls.LLM().model("anthropic/claude-sonnet-4-6")   # Anthropic native
cycls.LLM().model("openai/gpt-5.4")                # OpenAI
cycls.LLM().model("groq/llama-3.3-70b").base_url("https://api.groq.com/openai/v1")
cycls.LLM().model("humain/jais").base_url("https://inference.humain.ai/v1")
cycls.LLM().model("local/qwen").base_url("http://localhost:8000/v1")
```

Thinking/reasoning events, tool calls, and streaming are unified across providers.

### Custom tools

Tool schemas are bare JSON dicts. Handlers are plain async functions registered via `.on()`. The handler's return value is used as BOTH the UI stream event AND the `tool_result` content the LLM sees — one return, both destinations.

```python
TOOLS = [
    {
        "name": "render_image",
        "description": "Display an image to the user.",
        "inputSchema": {
            "type": "object",
            "properties": {"src": {"type": "string"}, "alt": {"type": "string"}},
            "required": ["src"],
        },
    }
]


async def render_image(args):
    return {"type": "text", "text": f"![{args.get('alt', '')}]({args['src']})"}


llm = cycls.LLM().tools(TOOLS).on("render_image", render_image)
```

### Workspace instructions and skills

**AGENT.md** — every turn, the harness reads `AGENT.md` from the user's workspace root (if present) and appends it to the system prompt, fenced as user preferences subordinate to your `.system()` prompt. Users edit it via the files panel or by asking the agent. Capped at 24KB (truncated beyond that); binary or unreadable files are ignored. Rename via `.instructions("NOTES.md")` or disable with `.instructions(None)`.

**Skills** are packs of task-specific instructions the model loads on demand: only each skill's name + description sit in the system prompt; the full body enters context when the model calls the `skill` tool (a reserved tool name). A skill is a folder with a `SKILL.md`:

```markdown
---
name: pdf-reports
description: Generate branded PDF reports from CSV data. Use when the user asks for a PDF report, invoice, or printable summary.
---
# Full instructions... (up to 48KB loaded on demand)
```

`name` is lowercase-hyphen (falls back to the folder name); `description` decides when the model reaches for it, so say *when to use* (max 1KB). Support files (scripts, templates, reference docs) live beside `SKILL.md`.

Skills come from two places:

- **Shipped with the agent** — put a `skills/` dir in your project, include it in the image, and register it:

  ```python
  image = cycls.Image().copy("skills/")
  llm = cycls.LLM().skills("skills")
  ```

  Shipped skills are read-only; each mounts at `/skills/<name>/` inside the bash sandbox, so the model runs `python /skills/pdf-reports/scripts/render.py` and scripts read their own templates from there. They version with your deploys.

- **User-created** — any `skills/<name>/SKILL.md` in a user's workspace joins the catalog automatically (rescanned every ~30s) and wins name collisions with shipped skills.

---

## Authentication

Auth providers are first-class objects. Both `cycls.Clerk` and `cycls.JWT` support dev/prod dual-mode out of the box — Cycls picks the right JWKS URL at serve time.

```python
# Cycls's hosted Clerk (default), dual-mode
web = cycls.Web().auth(cycls.Clerk())

# Custom Clerk tenant
web = cycls.Web().auth(cycls.Clerk(
    jwks_url="https://clerk.mycompany.com/.well-known/jwks.json",
    dev_jwks_url="https://dev-clerk.mycompany.com/.well-known/jwks.json",
))

# Generic OIDC (Auth0, WorkOS, Okta, Supabase, Firebase)
web = cycls.Web().auth(cycls.JWT(
    jwks_url="https://my-prod.auth0.com/.well-known/jwks.json",
    dev_jwks_url="https://my-dev.auth0.com/.well-known/jwks.json",
    issuer="https://my-prod.auth0.com/",
))
```

### User object

When auth is set, `context.user` is populated:

| Property | Description |
|---|---|
| `user.id` | Unique user ID |
| `user.org_id` | Organization ID (if set) |
| `user.org_slug` | Organization slug |
| `user.org_role` | Role in org |
| `user.org_permissions` | List of permissions |
| `user.plan` | Subscription plan |
| `user.features` | Feature flags |

---

## Analytics and Monetization

```python
web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .analytics(True)
    .cms(brand="https://cms.cycls.ai/agents/my-agent")
)
```

`.cms(...)` pulls branding from the Cycls CMS, which drives wallet-pass UI and [Cycls Pass](https://cycls.com) monetization.

`context.user.plan` exposes the authenticated user's subscription tier, set by your auth provider's JWT claim. The Cycls-hosted Clerk app emits values like `"u:free_user"` / `"o:free_org"` (user-plan / org-plan prefixes) and `"cycls_pass"` for paid subscribers. Gate features by inspecting the value:

```python
if context.user.plan == "cycls_pass":
    yield "Premium features unlocked."
else:
    yield "Upgrade for full access."
```

### Free-tier quota recipe

Block free orgs (b2b) and rate-limit free users (b2c) with a per-workspace counter. `cycls.Dict` stores the counter under the user's `.cycls/` directory; the key is the month, so history accumulates and resets happen naturally.

```python
from datetime import datetime, timezone
import cycls

FREE_MONTHLY_LIMIT = 10

@cycls.agent(image=image, web=web)
async def my_agent(context):
    user = context.user

    if user.plan == "o:free_org":
        yield {"type": "callout",
               "callout": "This workspace needs a paid plan.",
               "style": "error"}
        return

    with context.workspace():
        usage = cycls.Dict("usage")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        entry = usage.get(month, {"count": 0})

        if user.plan == "u:free_user" and entry["count"] >= FREE_MONTHLY_LIMIT:
            yield {"type": "callout",
                   "callout": f"Free tier limit reached ({FREE_MONTHLY_LIMIT}/mo).",
                   "style": "warning"}
            return

        entry["count"] += 1
        usage[month] = entry

    async for ev in llm.run(context=context):
        yield cycls.to_ui(ev)
```

`cycls.Dict("name")` is a persistent JSON-backed dict scoped to the surrounding `with context.workspace():` block. The `.cycls/` directory is framework-managed — user tools (Bash, Editor, files API) can read it but cannot write to it, so the quota cannot be tampered with from inside the agent.

---

## HTTP Extension

Agents expose the underlying FastAPI `APIRouter` via `.server` for webhooks, health checks, OAuth callbacks, and any custom routes. Use `Depends(my_agent.auth)` to protect routes with the same Clerk JWT the chat endpoint uses.

```python
from fastapi import Depends


@cycls.agent(web=cycls.Web().auth(cycls.Clerk()))
async def my_agent(context):
    async for ev in llm.run(context=context):
        yield cycls.to_ui(ev)


@my_agent.server.api_route("/webhook", methods=["POST"])
async def stripe_webhook(request):
    payload = await request.json()
    ...
    return {"ok": True}


@my_agent.server.api_route("/profile", methods=["GET"])
async def profile(user = Depends(my_agent.auth)):
    return {"id": user.id}
```

---

## Running

### CLI (recommended)

```bash
cycls run my_agent.py       # local Docker + hot-reload
cycls deploy my_agent.py    # production
cycls ls                    # list deployments
cycls logs <name> -f        # tail logs
cycls rm <name>             # delete a deployment
cycls init [name]           # scaffold a starter file
```

### Programmatic

```python
my_agent.local()             # local Docker + hot-reload
my_agent.local(watch=False)  # local Docker, no watch
my_agent.deploy()            # production deploy
```

For script-mode execution (`python my_agent.py`), wrap in the standard Python idiom:

```python
if __name__ == "__main__":
    my_agent.local()
```

---

## `@cycls.function` — Containerized Compute

For batch jobs, data processing, and services without a chat UI.

```python
@cycls.function(image=cycls.Image().pip("numpy"))
def compute(x, y):
    import numpy
    return (y * numpy.arange(x)).tolist()


print(compute.run(5, 2))   # [0, 2, 4, 6, 8]
```

Running a service:

```python
@cycls.function(image=cycls.Image().pip("fastapi", "uvicorn"))
def api_server(port):
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/")
    async def root():
        return {"message": "hello from a containerized FastAPI service"}

    uvicorn.run(app, host="0.0.0.0", port=port)


api_server.run(port=8000)
```

Two more decorator arguments round out deployed functions: `volumes=` mounts
named persistent storage (`cycls.Volume`) at a container path, and
`schedule=` makes the platform fire the function on a cron schedule with no
caller:

```python
@cycls.function(schedule=cycls.Cron("0 3 * * *", timezone="Asia/Riyadh"),
                volumes={"/out": cycls.Volume("scrapes")})
def nightly(): ...
```

See [docs/volume.md](../volume.md) and [docs/cron.md](../cron.md) for
semantics.

### Function vs Agent

| | `@cycls.function` | `@cycls.agent` |
|---|---|---|
| Input | Function args | `context` (messages, user) |
| Output | Return value | Yielded stream |
| Web UI | No | Yes |
| LLM loop | No | Yes (via `llm.run()`) |
| Use case | Batch jobs, services, cron | Chat interfaces |

### Function methods

| Method | Description |
|---|---|
| `.run(*args, **kwargs)` | Execute and return result |
| `.watch(*args, **kwargs)` | Run with file watching |
| `.build(*args, **kwargs)` | Build standalone Docker image |
| `.deploy(*args, **kwargs)` | Deploy to Cycls cloud |

---

## API Endpoints

Every agent exposes these HTTP endpoints:

```
POST /chat/cycls           # Cycls streaming protocol (SSE)
POST /chat/completions     # OpenAI-compatible format
GET  /config               # App config (title, plan, auth flag, ...)
POST /attachments          # File upload (multipart)
GET  /attachments/<token>  # Attachment download

# Authenticated:
GET    /chats                 # List chats
GET    /chats/<id>            # Get chat
PUT    /chats/<id>            # Create or update
DELETE /chats/<id>            # Delete

GET    /files                 # List files (?path=subdir)
GET    /files/<path>          # Download (?download for header)
PUT    /files/<path>          # Upload (multipart)
PATCH  /files/<path>          # Rename (body: {"to": "new/path"})
POST   /files/<path>          # Create directory
DELETE /files/<path>          # Delete
```

Sessions and files are per-user under `/workspace/<user_id>/`. Path traversal is blocked. State routers (sessions, files, share) are only installed when auth is configured.

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `CYCLS_API_KEY` | Cycls deploy API key |
| `CYCLS_BASE_URL` | Cycls API base URL (defaults to `https://api.cycls.ai`) |
| `ANTHROPIC_API_KEY` | Anthropic API key (auto-picked by adapter) |
| `OPENAI_API_KEY` | OpenAI API key (auto-picked by adapter) |
| `VITE_CLERK_PUBLISHABLE_KEY` | Frontend Clerk publishable key (optional override) |

---

## Troubleshooting

**Docker not running**

```bash
# macOS/Windows: start Docker Desktop
# Linux:
sudo systemctl start docker
```

**Missing API key**

```bash
export CYCLS_API_KEY=your_key
```

**Port already in use**

```python
my_agent.local(port=3000)
```

**Force rebuild Docker image**

```python
image = cycls.Image().pip("numpy").rebuild()
```

---

## Next Steps

- Explore the [examples](../examples/) directory for working code
- Read the [README](../../README.md) for the architectural overview
- Visit [cycls.com](https://cycls.com) for deploy + billing

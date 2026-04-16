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
    async for msg in llm.run(context=context):
        yield msg
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
    async for msg in llm.run(context=context):
        yield msg
```

- **`cycls.Image`** — container build config (pip, apt, copy, run commands)
- **`cycls.Web`** — UI, auth, branding, billing, analytics
- **`cycls.LLM`** — model, system prompt, tools, handlers, allowed builtins

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

---

## `cycls.Web` — UI, Auth, Branding

```python
web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .title("My Agent")
    .theme("default")
    .plan("cycls_pass")
    .analytics(True)
    .copy_public("./assets/logo.png", "./downloads/")
)
```

| Method | Purpose |
|---|---|
| `.auth(provider)` | Set auth provider (`cycls.Clerk()` or `cycls.JWT(...)`) |
| `.title(str)` | Browser tab + app title |
| `.theme(name)` | `"default"` or `"dev"` |
| `.plan(str)` | Billing plan (`"free"` or `"cycls_pass"`) |
| `.analytics(bool)` | Enable usage metrics |
| `.copy_public(*files)` | Static files served at `/public` |

Static files land at `https://your-app.cycls.ai/public/logo.png`.

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
    .max_tokens(16384)
    .show_usage(True)
)

async for msg in llm.run(context=context):
    yield msg
```

| Method | Purpose |
|---|---|
| `.model(str)` | `provider/model` string — `anthropic/...`, `openai/...`, `groq/...`, etc. |
| `.system(str)` | System prompt |
| `.tools(list)` | Custom tool JSON schemas |
| `.on(name, fn)` | Register async handler for a custom tool |
| `.allowed_tools(names)` | Enable Cycls-provided builtins (`Bash`, `Editor`, `WebSearch`) |
| `.max_tokens(n)` | Max output tokens |
| `.bash_timeout(secs)` | Bash sandbox timeout |
| `.show_usage(bool)` | Print cost + token usage at end of run |
| `.base_url(url)` | Custom endpoint (Groq, vLLM, HUMAIN, self-hosted) |
| `.api_key(key)` | Override API key |

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
    .plan("cycls_pass")
)
```

`plan("cycls_pass")` wires monetization via [Cycls Pass](https://cycls.com) subscriptions. Agents can read `context.user.plan` to gate features:

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

    async for msg in llm.run(context=context):
        yield msg
```

`cycls.Dict("name")` is a persistent JSON-backed dict scoped to the surrounding `with context.workspace():` block. The `.cycls/` directory is framework-managed — user tools (Bash, Editor, files API) can read it but cannot write to it, so the quota cannot be tampered with from inside the agent.

---

## HTTP Extension

Agents expose the underlying FastAPI `APIRouter` via `.server` for webhooks, health checks, OAuth callbacks, and any custom routes. Use `Depends(my_agent.auth)` to protect routes with the same Clerk JWT the chat endpoint uses.

```python
from fastapi import Depends


@cycls.agent(web=cycls.Web().auth(cycls.Clerk()))
async def my_agent(context):
    async for msg in llm.run(context=context):
        yield msg


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
GET    /sessions              # List sessions
GET    /sessions/<id>         # Get session
PUT    /sessions/<id>         # Create or update
DELETE /sessions/<id>         # Delete

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
- Read the [README](../README.md) for the architectural overview
- Visit [cycls.com](https://cycls.com) for deploy + billing

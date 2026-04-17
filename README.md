<h3 align="center">
Distribute Intelligence
</h3>

<h4 align="center">
  <a href="https://cycls.com">Website</a> |
  <a href="https://docs.cycls.com">Docs</a> |
  <a href="docs/tutorial.md">Tutorial</a>
</h4>

<h4 align="center">
  <a href="https://pypi.python.org/pypi/cycls"><img src="https://img.shields.io/pypi/v/cycls.svg?label=cycls+pypi&color=blueviolet" alt="cycls Python package on PyPi" /></a>
  <a href="https://github.com/Cycls/cycls/actions/workflows/tests.yml"><img src="https://github.com/Cycls/cycls/actions/workflows/tests.yml/badge.svg" alt="Tests" /></a>
  <a href="https://blog.cycls.com"><img src="https://img.shields.io/badge/newsletter-blueviolet.svg?logo=substack&label=cycls" alt="Cycls newsletter" /></a>
  <a href="https://x.com/cyclsai">
    <img src="https://img.shields.io/twitter/follow/CyclsAI" alt="Cycls Twitter" />
  </a>
</h4>

---

# Cycls

The deep-stack AI SDK for Python. Every layer of an AI agent — runtime, interface, intelligence, state — as a composable Python primitive, in one file, deployed with one command.

```
Agent extends App (chat product + managed LLM loop)
    └── App extends Function (blocking ASGI service)
        └── Function (Docker containerization)
```

## Distribute Intelligence

Write an agent. Three primitives compose it. Deploy it with one command.

```python
import cycls

image = cycls.Image().copy(".env")

web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .title("My Agent")
)

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You are a helpful assistant.")
    .allowed_tools(["Bash", "Editor", "WebSearch"])
)


@cycls.agent(image=image, web=web)
async def my_agent(context):
    async for msg in llm.run(context=context):
        yield msg
```

```bash
cycls deploy my_agent.py   # live at https://my-agent.cycls.ai
```

## Installation

```bash
pip install cycls
```

Requires Docker. See the [full tutorial](docs/tutorial.md) for a comprehensive guide.

## The Primitives

**Four composable builders, three decorators, one CLI.**

```
Primitives (declare once, reuse anywhere):
  cycls.Image   — container build config (pip, apt, copy, run commands)
  cycls.Web     — UI, auth, branding, billing, analytics
  cycls.LLM     — model, system prompt, tools, runtime config
  cycls.Clerk   — Clerk JWT auth provider (or cycls.JWT for generic OIDC)

Decorators (compose primitives into deployable units):
  @cycls.function(image=)                    — non-blocking compute
  @cycls.app(image=)                         — blocking ASGI service
  @cycls.agent(image=, web=)                 — managed chat product

CLI:
  cycls run file.py        — local Docker with hot-reload
  cycls deploy file.py     — production deploy
  cycls ls                 — list deployments
  cycls logs <name> -f     — tail logs
  cycls rm <name>          — delete a deployment
  cycls init [name]        — scaffold a starter agent
```

Every primitive is a fluent immutable builder. Every decorator accepts exactly those primitives, never grab-bag kwargs.

## Running

```python
my_agent.local()             # local Docker + hot-reload (localhost:8080)
my_agent.local(watch=False)  # local Docker, no watch
my_agent.deploy()            # production: https://my-agent.cycls.ai
```

Or via the CLI (recommended):

```bash
cycls run my_agent.py       # local Docker + hot-reload
cycls deploy my_agent.py    # production
```

Get an API key at [cycls.com](https://cycls.com).

## Authentication

Auth providers are first-class objects. `cycls.Clerk()` uses Cycls's hosted Clerk by default; `cycls.JWT(...)` covers any OIDC provider (Auth0, WorkOS, Supabase, Okta, Firebase).

```python
# Cycls's default Clerk (dev/prod dual mode, auto-switches)
web = cycls.Web().auth(cycls.Clerk())

# Custom Clerk tenant
web = cycls.Web().auth(cycls.Clerk(
    jwks_url="https://clerk.mycompany.com/.well-known/jwks.json",
))

# Generic OIDC (Auth0, WorkOS, etc)
web = cycls.Web().auth(cycls.JWT(
    jwks_url="https://my-prod.auth0.com/.well-known/jwks.json",
    dev_jwks_url="https://my-dev.auth0.com/.well-known/jwks.json",
))

@cycls.agent(web=web)
async def my_agent(context):
    user = context.user   # User(id, org_id, plan, features, ...)
    ...
```

## Analytics & Billing

```python
web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .analytics(True)        # usage metrics on the Cycls dashboard
    .cms("cycls.ai")        # CMS entry → monetize via Cycls Pass subscriptions
    .title("My Agent")
)
```

## Custom Tools

Tools are bare JSON schemas. Handlers are plain async functions registered via `.on(name, handler)`. Handler return values flow to both the UI stream and the LLM's `tool_result`.

```python
TOOLS = [
    {
        "name": "render_image",
        "description": "Display an image to the user.",
        "inputSchema": {
            "type": "object",
            "properties": {"src": {"type": "string"}},
            "required": ["src"],
        },
    }
]


async def render_image(args):
    return {"type": "text", "text": f"![image]({args['src']})"}


llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .tools(TOOLS)
    .on("render_image", render_image)
)
```

## Multi-provider LLM

One adapter covers Anthropic natively and every OpenAI-compatible endpoint (OpenAI, Groq, vLLM, HUMAIN, self-hosted, ...) via `provider/model` strings:

```python
cycls.LLM().model("anthropic/claude-sonnet-4-6")         # Anthropic native
cycls.LLM().model("openai/gpt-5.4")                      # OpenAI
cycls.LLM().model("groq/llama-3.3-70b").base_url(...)    # Groq or any OpenAI-compat
cycls.LLM().model("humain/jais").base_url(...)           # sovereign inference
```

Thinking/reasoning events, tool calls, and streaming are unified across providers.

## Streaming Components

Yield structured objects from an agent body for rich streaming responses:

```python
@cycls.agent(web=cycls.Web().auth(cycls.Clerk()))
async def demo(context):
    yield {"type": "thinking", "thinking": "Analyzing the request..."}
    yield "Here's what I found:\n\n"

    yield {"type": "table", "headers": ["Name", "Status"]}
    yield {"type": "table", "row": ["Server 1", "Online"]}
    yield {"type": "table", "row": ["Server 2", "Offline"]}

    yield {"type": "code", "code": "result = analyze(data)", "language": "python"}
    yield {"type": "callout", "callout": "Analysis complete!", "style": "success"}
```

| Component | Streaming |
|-----------|-----------|
| `{"type": "thinking", "thinking": "..."}` | Yes |
| `{"type": "code", "code": "...", "language": "..."}` | Yes |
| `{"type": "table", "headers": [...]}` / `{"type": "table", "row": [...]}` | Yes |
| `{"type": "status", "status": "..."}` | Yes |
| `{"type": "callout", "callout": "...", "style": "..."}` | Yes |
| `{"type": "image", "src": "..."}` | Yes |

### Thinking Bubbles

The `{"type": "thinking", ...}` component renders as a collapsible thinking bubble. Consecutive `thinking` yields append to the same bubble until a different component type is yielded. Cycls automatically maps provider reasoning deltas (Claude extended thinking, OpenAI `delta.reasoning`) to this channel, so you get thinking bubbles without doing anything special.

## Context Object

```python
@cycls.agent(web=cycls.Web().auth(cycls.Clerk()))
async def chat(context):
    context.messages      # [{"role": "user", "content": "..."}]
    context.messages.raw  # Full data including UI component parts
    context.user          # User(id, org_id, plan, features, ...) when auth is set
    context.prod          # True via .deploy(), False via .local() — gate billing/analytics
    with context.workspace():   # Per-user persistent scope — enables cycls.Dict(...)
        usage = cycls.Dict("usage")
```

## API Endpoints

| Endpoint | Format |
|----------|--------|
| `POST /chat/cycls` | Cycls streaming protocol |
| `POST /chat/completions` | OpenAI-compatible |

## HTTP Extension

Agents expose the underlying FastAPI surface via `.server` for webhooks, health checks, OAuth callbacks, and any custom routes:

```python
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
    return {"user_id": user.id}
```

## Declarative Infrastructure

The `cycls.Image` primitive holds container build config. Every field is chainable; the resulting Image is passed to any decorator via `image=`.

```python
image = (
    cycls.Image()
    .pip("openai", "pandas", "numpy", "transformers")
    .apt("ffmpeg", "imagemagick", "libpq-dev")
    .copy("./utils.py")
    .copy("./models/", "app/models/")
    .copy("/absolute/path/to/config.json")
    .run("echo 'hello from build' > /app/build_marker.txt")
)

@cycls.function(image=image)
def my_func(x):
    from utils import helper_function   # bundled via .copy()
    ...
```

### `.pip(*packages)` — Python packages

Install any packages from PyPI during container build.

```python
cycls.Image().pip("openai", "pandas", "numpy", "transformers")
```

### `.apt(*packages)` — System packages

Install apt-get dependencies. Need ffmpeg? ImageMagick? Declare it.

```python
cycls.Image().apt("ffmpeg", "imagemagick", "libpq-dev")
```

### `.copy(src, dst=None)` — Bundle files

Include local files and directories. Works with relative or absolute paths, single files or whole trees. `dst` defaults to `src`; pass both to relocate.

```python
(
    cycls.Image()
    .copy("./utils.py")                       # same path
    .copy("./models/", "app/models/")          # src → dst
    .copy("/home/user/configs/app.json")       # absolute
)
```

Import bundled modules in your function body:

```python
@cycls.function(image=cycls.Image().copy("./utils.py"))
def my_func(x):
    from utils import helper_function
    ...
```

### `.run(command)` — Build-time shell commands

```python
cycls.Image().run("pip install --upgrade pip").run("apt-get clean")
```

### `.rebuild()` — Force Docker cache bust

```python
image = cycls.Image().pip("numpy").rebuild()   # skip Docker cache
```

### Public static files via `cycls.Web`

Static files served from `/public` (images, downloads, assets) live on the Web primitive:

```python
web = cycls.Web().copy_public("./assets/logo.png", "./downloads/")
```

Access them at `https://your-app.cycls.ai/public/logo.png`.

---

### What You Get

- **One file** — Primitives, code, and infrastructure together
- **Three decorators** — `@function`, `@app`, `@agent`, each one strict and composable
- **Multi-LLM** — Anthropic native + every OpenAI-compatible endpoint
- **Managed loop** — retries, compaction, sandbox, tool handlers, history, sessions
- **CLI + SDK** — `cycls run`, `cycls deploy`, or programmatic `.local()` / `.deploy()`
- **No drift** — what you see is what runs

No YAML. No Dockerfiles. No infrastructure repo. The code is the deployment.

## Learn More

- [Tutorial](docs/tutorial.md) — comprehensive guide from basics to advanced
- [Sandbox threat model](docs/sandbox.md) — how the Bash tool is isolated
- [Examples](examples/) — working code samples

## License

MIT

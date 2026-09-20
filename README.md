<h3 align="center">
Distribute Intelligence
</h3>

<h4 align="center">
  <a href="https://cycls.com">Website</a> |
  <a href="https://docs.cycls.com">Docs</a> |
  <a href="https://cloud.cycls.com">Cycls Cloud</a> |
  <a href="docs/function.md">Functions</a> |
  <a href="docs/volume.md">Volumes</a> |
  <a href="docs/cli.md">CLI</a>
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

The deep-stack AI SDK for Python. Every layer of an AI agent (runtime, interface, intelligence, state) as a composable Python primitive, in one file, deployed with one command.

```
Agent extends App (chat product + managed LLM loop)
    └── App extends Function (blocking ASGI service)
        └── Function (Docker containerization)
```

## Distribute Intelligence

Write an agent. Four primitives compose it. Deploy it with one command.

```python
import cycls

image = cycls.Image().copy(".providers.env", ".env")

chats = cycls.Volume("my-agent")

web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .title("My Agent")
)

llm = (
    cycls.LLM()
    .model("anthropic/claude-sonnet-4-6")
    .system("You are a helpful assistant.")
    .allowed_tools(["Bash", "Editor", "WebSearch", "Canvas"])
)


@cycls.agent(image=image, web=web, volumes={"/workspace": chats})
async def my_agent(context):
    async for ev in llm.run(context=context):
        yield ev
```

```bash
cycls deploy my_agent.py   # live at https://my-agent.cycls.ai
```

That deploy gives you a chat interface, sign-in, per-user files and chats, share links, an OpenAI-compatible API endpoint, and a sandboxed tool loop.

## Installation

```bash
pip install cycls
```

Get an API key at [cloud.cycls.com](https://cloud.cycls.com). Full documentation at [docs.cycls.com](https://docs.cycls.com).

## The Primitives

**Four composable builders, three decorators, one CLI.**

```
Primitives (declare once, reuse anywhere):
  cycls.Image    container build config (pip, apt, copy, run commands)
  cycls.Web      UI, auth, branding, analytics, workspaces
  cycls.LLM      model, system prompt, tools, budgets, reasoning
  cycls.Volume   named persistent storage, attached by mount path

Decorators (compose primitives into deployable units):
  @cycls.function(image=, volumes=, schedule=)   containerized compute
  @cycls.app(image=, volumes=, auth=)            blocking ASGI service
  @cycls.agent(image=, web=, volumes=)           managed chat product

CLI:
  cycls init [name]             scaffold a starter agent
  cycls run file.py             local Docker with hot-reload
  cycls run file.py --remote    cloud dev loop, no Docker needed
  cycls deploy file.py          production deploy
  cycls ls                      list deployments
  cycls logs <name> -f          tail logs
  cycls cost <name>             aggregate model spend
  cycls sql [QUERY]             SQL over logs and billing
  cycls volume ls               manage persistent storage
  cycls rm <name>               delete a deployment
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
cycls run my_agent.py           # local Docker + hot-reload
cycls run my_agent.py --remote  # cloud dev URL, hot-swap on save
cycls deploy my_agent.py        # production
```

`run` is local, `--remote` is cloud, `deploy` freezes. The same three words work in Python and on the command line. See [docs/function.md](docs/function.md).

## State

Agents keep chats, files and credentials on a volume mounted at `/workspace`, so the decorator requires one:

```python
@cycls.agent(volumes={"/workspace": cycls.Volume("my-agent")})
async def my_agent(context):
    ...
```

Volumes are named storage, created on first reference, shared by name across deployments, and alive until you delete them explicitly. `cycls rm` detaches volumes and never touches their data. Full story: [docs/volume.md](docs/volume.md).

## Multi-provider LLM

One adapter covers Anthropic natively and every OpenAI-compatible endpoint through `provider/model` strings and a base URL:

```python
cycls.LLM().model("anthropic/claude-sonnet-4-6")     # Anthropic, native API
cycls.LLM().model("openai/gpt-5.4")                  # OpenAI

# Open weight models
cycls.LLM().model("deepseek/deepseek-flash").base_url("https://api.deepseek.com/v1")
cycls.LLM().model("moonshotai/kimi-k3").base_url("https://api.moonshot.ai/v1")
cycls.LLM().model("zai/glm-5.3").base_url("https://open.bigmodel.cn/api/paas/v4")

# Your own inference server
cycls.LLM().model("local/kimi-k3").base_url("http://localhost:8000/v1")
```

Reasoning control, tool calls and streaming are unified across providers. `.thinking("low"|"medium"|"high"|"adaptive"|None)` is translated into each vendor's dialect, and `.extra_body()` is the escape hatch for anything unmapped.

## Tools

Built-in tools are enabled by name. Each brings its own prompt guidance.

```python
llm = cycls.LLM().allowed_tools([
    "Bash",       # shell in a bubblewrap sandbox rooted at the workspace
    "Editor",     # read and edit workspace files
    "WebSearch",  # portable search + fetch, or provider-native
    "Browser",    # a real Chrome session, when a browser service is configured
    "DataBase",   # per-user key-value store
    "Canvas",     # open a finished file in the side panel
    "Apps",       # bundle a source folder into an installable mini app
    "Suggest",    # one follow-up chip above the composer
    "Ask",        # up to three questions on one card
])
```

Custom tools are bare JSON schemas with async handlers registered via `.on(name, handler)`. The handler's return value flows to both the UI stream and the model's `tool_result`.

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
    return {"type": "image", "src": args["src"]}


llm = cycls.LLM().tools(TOOLS).on("render_image", render_image, label=lambda i: i["src"])
```

A handler can declare a second parameter to receive a `ToolContext` with the user, workspace and chat id.

## Connectors and MCP

A connector is a grant a person makes once, for themselves or their team. Declare it on both builders and the loop attaches the credential server-side when a tool runs.

```python
notion = cycls.OAuth2(
    "notion",
    authorize="https://api.notion.com/v1/oauth/authorize",
    token="https://api.notion.com/v1/oauth/token",
    client_id=cycls.env("NOTION_CLIENT_ID"),
    secret=cycls.env("NOTION_CLIENT_SECRET"),
    scopes=["read_content"],
    api="https://api.notion.com",
    scope="either",
)

web = cycls.Web().auth(cycls.Clerk()).connectors(notion)
llm = cycls.LLM().connectors(notion)
```

`cycls.Key` takes a pasted key, `cycls.Endpoint` takes a private URL that is itself the credential. `cycls.MCP` connects remote MCP servers, and since the harness speaks the protocol itself, MCP works on every provider.

Every tool call is classified as read, write or destructive. Reads always run, writes follow the composer's Auto switch, destructive calls always ask, and an approval binds to the exact arguments shown on the card.

## Streaming Components

Yield structured objects from an agent body for rich streaming responses:

```python
@cycls.agent(web=web, volumes={"/workspace": chats})
async def demo(context):
    yield {"type": "thinking", "thinking": "Analyzing the request..."}
    yield "Here's what I found:\n\n"

    yield {"type": "table", "headers": ["Name", "Status"]}
    yield {"type": "table", "row": ["Server 1", "Online"]}
    yield {"type": "table", "row": ["Server 2", "Offline"]}

    yield {"type": "code", "code": "result = analyze(data)", "language": "python"}
    yield {"type": "callout", "callout": "Analysis complete!", "style": "success"}
```

| Component | Required keys |
|-----------|---------------|
| `{"type": "text", "text": "..."}` | a bare string does the same |
| `{"type": "thinking", "thinking": "..."}` | accumulates in a bubble |
| `{"type": "code", "code": "...", "language": "..."}` | accumulates |
| `{"type": "table", "headers": [...]}` / `{"type": "table", "row": [...]}` | row by row |
| `{"type": "status", "status": "..."}` | replaces the previous status |
| `{"type": "callout", "callout": "...", "style": "info\|warning\|error\|success"}` | one card |
| `{"type": "image", "src": "...", "alt": "...", "caption": "..."}` | one image |
| `{"type": "sources", "sources": [{"title", "url", "snippet"}]}` | citation chips |
| `{"type": "ui", "action": "open_plan_modal"}` | fire-and-forget client action |

Provider reasoning deltas (Claude extended thinking, OpenAI `delta.reasoning`) map to the thinking channel automatically, so `llm.run()` produces thinking bubbles with no extra work.

`llm.run()` yields these same dicts, so the body passes them through with `yield ev`. `cycls.to_ui(ev)` still works and is now an identity function kept for older code.

## Context Object

```python
@cycls.agent(web=web, volumes={"/workspace": chats})
async def chat(context):
    context.messages          # [{"role": "user", "content": "..."}]
    context.messages.raw      # full data including UI component parts
    context.last_message      # text of the most recent message
    context.user              # User(id, org_id, plan, features, ...) when auth is set
    context.chat_id           # current chat
    context.workspace         # this user's storage scope
    context.prod              # True via deploy, False via run
    context.disabled_tools    # tools the person switched off in Settings
```

## Authentication

Auth providers are first-class objects. `cycls.Clerk()` uses Cycls's hosted Clerk by default; `cycls.JWT(...)` covers any OIDC provider (Auth0, WorkOS, Supabase, Okta, Firebase).

```python
# Cycls's default Clerk (dev/prod dual mode, auto-switches)
web = cycls.Web().auth(cycls.Clerk())

# Custom Clerk tenant
web = cycls.Web().auth(cycls.Clerk(
    jwks_url="https://clerk.mycompany.com/.well-known/jwks.json",
))

# Generic OIDC
web = cycls.Web().auth(cycls.JWT(
    jwks_url="https://my-prod.auth0.com/.well-known/jwks.json",
    dev_jwks_url="https://my-dev.auth0.com/.well-known/jwks.json",
))
```

## Workspaces

Every user gets a personal workspace, and organizations can share team workspaces with role-based access. Each workspace is a full context: files, chats, `AGENT.md`, skills and key-value store.

```python
web = cycls.Web().auth(cycls.Clerk()).workspaces()          # any member can create teams
web = cycls.Web().auth(cycls.Clerk()).workspaces(create="admin")
```

The active workspace is selected per request with the `X-Workspace` header. See [docs/workspaces.md](docs/workspaces.md).

## Instructions and Skills

Every turn, the harness reads `AGENT.md` from the user's workspace root and appends it to the system prompt as user preferences subordinate to your `.system()` prompt.

Skills are packs of task-specific instructions loaded on demand: only the name and description sit in the system prompt, and the body enters context when the model calls the `skill` tool.

```python
image = cycls.Image().copy("skills/")
llm = cycls.LLM().skills("skills").instructions("AGENT.md")
```

User-created skills in `skills/<name>/SKILL.md` join the catalog automatically and win name collisions with shipped skills.

## Analytics, Billing and Cost

```python
web = (
    cycls.Web()
    .auth(cycls.Clerk())
    .analytics(cycls.PostHog(), cycls.GTM("GTM-ABCD123"))
    .notifications(cycls.OneSignal("<app-id>"))
    .cms(brand="https://cms.cycls.ai/agents/my-agent")
)

llm = cycls.LLM().price(input=3, output=15, cache_read=0.30, cache_write=6)
```

With prices set, every turn logs its cost:

```bash
cycls cost my-agent --by user
cycls sql 'SELECT ... FROM logs WHERE JSON_VALUE(json_payload, "$.level") = "usage"'
```

## API Endpoints

| Endpoint | Format |
|----------|--------|
| `POST /` | Cycls streaming protocol (SSE), `/chat` is an alias |
| `POST /chat/completions` | OpenAI-compatible |
| `GET /config` | app config (title, branding, auth flag) |
| `GET /chats`, `PUT /chats/<id>`, `DELETE /chats/<id>` | chat history |
| `GET /files`, `PUT /files/<path>`, `PATCH`, `DELETE` | per-user files |
| `POST /share`, `GET /shared/<user>/<token>` | share links |
| `GET /workspaces`, `POST /workspaces` | workspaces, when enabled |
| `GET /connectors`, `POST /connectors/<name>/authorize` | connectors, when declared |

State routers are installed only when auth is configured. Sessions and files live per user under `/workspace/<scope>/`.

## HTTP Extension

Agents expose the underlying FastAPI surface via `.server` for webhooks, health checks, OAuth callbacks, and any custom routes:

```python
from fastapi import Depends


@my_agent.server.api_route("/webhook", methods=["POST"])
async def stripe_webhook(request):
    payload = await request.json()
    return {"ok": True}


@my_agent.server.api_route("/profile", methods=["GET"])
async def profile(user=Depends(my_agent.auth)):
    return {"user_id": user.id}
```

## Declarative Infrastructure

The `cycls.Image` primitive holds container build config. Every field is chainable, and the resulting Image is passed to any decorator via `image=`.

```python
image = (
    cycls.Image()
    .pip("openai", "pandas", "numpy")
    .apt("ffmpeg", "imagemagick", "libpq-dev")
    .copy("./utils.py")
    .copy("./models/", "app/models/")
    .run("echo 'hello from build' > /app/build_marker.txt")
    .rebuild()                      # force a clean build
)

@cycls.function(image=image)
def my_func(x):
    from utils import helper_function   # bundled via .copy()
    ...
```

| Method | Purpose |
|---|---|
| `.pip(*packages)` | install Python packages from PyPI |
| `.apt(*packages)` | install system packages |
| `.copy(src, dst=None)` | bundle local files and directories, `dst` defaults to `src` |
| `.run(command)` | run a shell command during the build |
| `.rebuild()` | skip the Docker cache |

Images are content-hashed, including the contents of copied files, so identical inputs reuse the cached build and one changed package rebuilds only what depends on it.

Static files served at `/public` live on the Web primitive:

```python
web = cycls.Web().copy_public("./assets/logo.png", "./downloads/")
```

## Functions

For batch jobs, data processing, scheduled work and services without a chat UI:

```python
@cycls.function(image=cycls.Image().pip("numpy"))
def simulate(n=1_000_000):
    import numpy as np
    pts = np.random.rand(int(n), 2)
    return float(4 * ((pts ** 2).sum(axis=1) <= 1).mean())


simulate.run(1000)             # local Docker
simulate.remote(1000)          # cloud, current code
simulate.map([10**6] * 100)    # fan out, ordered results
simulate.deploy()              # frozen, callable by name
```

```python
import cycls
pi = cycls.remote("simulate")(10_000_000)
```

A function that takes `port` deploys as a server on its own URL. A bare function deploys as a named endpoint callable from any machine with your API key.

Add `schedule=` and the platform fires the deployed function on a cron:

```python
@cycls.function(schedule=cycls.Cron("0 3 * * *", timezone="Asia/Riyadh"),
                volumes={"/reports": cycls.Volume("daily-reports")})
def nightly():
    ...
```

## Sandbox

The Bash tool runs inside a `bubblewrap` sandbox: read-only root, cleared environment, the workspace as the only writable path, the chat store masked, and the cloud metadata range blocked. Network is on by default so `curl`, `pip` and `git` work.

```python
llm = cycls.LLM().sandbox(network=False).bash_timeout(120)
```

A prompt-injected shell can exfiltrate anything it can read, so turn the network off when the agent does not need it. Full threat model: [docs/notes/sandbox-security.md](docs/notes/sandbox-security.md).

### What You Get

- **One file**: primitives, code, and infrastructure together
- **Three decorators**: `@function`, `@app`, `@agent`, each strict and composable
- **Multi-LLM**: Anthropic native, OpenAI, open weight models, and your own servers
- **Managed loop**: retries, compaction, sandbox, tool handlers, history, background runs
- **CLI + SDK**: `cycls run`, `cycls deploy`, or programmatic `.local()` / `.deploy()`
- **No drift**: what you see is what runs

No YAML. No Dockerfiles. No infrastructure repo. The code is the deployment.

## Learn More

- [Documentation](https://docs.cycls.com): the full guide, reference and API
- [Functions](docs/function.md): the function interface, end to end
- [Volumes](docs/volume.md): persistent, shareable storage for deployments
- [Cron](docs/cron.md): fire a deployed function on a schedule
- [Workspaces](docs/workspaces.md): personal and team workspaces for agents
- [CLI](docs/cli.md): every command
- [Tutorial](docs/tutorial.md): comprehensive guide from basics to advanced
- [Sandbox security](docs/notes/sandbox-security.md): how the Bash tool is isolated
- [Office preview](docs/notes/office-preview.md): how docx/pptx/xlsx render on the canvas
- [Examples](examples/): working code samples

## License

MIT

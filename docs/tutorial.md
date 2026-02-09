# Cycls Tutorial

This tutorial covers everything you need to build, deploy, and monetize AI agents with Cycls.

## What is Cycls?

Cycls is a Python SDK for distributing intelligence. Write a function, and Cycls turns it into an API, a web interface, or both. No YAML, no Dockerfiles, no infrastructure repos. You write Python, Cycls handles the rest.

## Prerequisites

- Python 3.10 or higher
- Docker installed and running
- A Cycls API key from [cycls.com](https://cycls.com) (for deployment)

## Installation

```bash
pip install cycls
```

---

## Quick Start

```python
import cycls

@cycls.app()
async def hello(context):
    yield "Hello! "
    yield "How can I help you today?"

hello.local()
```

Run this file and you have a streaming chat interface at `http://localhost:8080`. Every `yield` streams to the user in real-time.

---

## The Context Object

Every app function receives a `context` with the conversation state.

```python
@cycls.app()
async def my_app(context):
    # Last user message (most common)
    yield f"You asked: {context.last_message}\n\n"

    # Full conversation history
    for msg in context.messages:
        role = msg["role"]     # "user" or "assistant"
        content = msg["content"]

    # Raw messages with all metadata and UI parts
    raw = context.messages.raw

    # User info (when auth=True)
    if context.user:
        yield f"Hello, {context.user.name}!"
```

| Property | Type | Description |
|----------|------|-------------|
| `context.messages` | Messages | Conversation history as `[{"role": ..., "content": ...}]` |
| `context.messages.raw` | list | Full messages with all metadata and parts |
| `context.last_message` | str | Shortcut for the last user message content |
| `context.user` | User / None | User object when `auth=True` |

---

## Sync vs Async

Both work:

```python
# Async (recommended for I/O)
@cycls.app()
async def async_app(context):
    yield "Async response"

# Sync (simpler for CPU-bound work)
@cycls.app()
def sync_app(context):
    yield "Sync response"
```

---

## Native UI Components

Plain strings stream as text with full markdown support. Structured dicts unlock richer components.

### Text

```python
yield "# Heading\n\n"
yield "This is **bold** and *italic*.\n"
```

### Thinking Bubbles

Multiple yields accumulate in the same bubble. A different type closes it.

```python
yield {"type": "thinking", "thinking": "Let me "}
yield {"type": "thinking", "thinking": "analyze this..."}

# Switching to text closes the thinking bubble
yield "Here's my answer."
```

### Code Blocks

```python
yield {
    "type": "code",
    "code": "def fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)",
    "language": "python"
}
```

### Streaming Tables

Headers first, then rows one at a time:

```python
yield {"type": "table", "headers": ["Server", "Status", "CPU"]}
yield {"type": "table", "row": ["web-1", "Online", "45%"]}
yield {"type": "table", "row": ["web-2", "Online", "62%"]}
yield {"type": "table", "row": ["db-1", "Offline", "0%"]}
```

### Callouts

```python
yield {"type": "callout", "callout": "Operation completed!", "style": "success"}
yield {"type": "callout", "callout": "Please review.", "style": "warning"}
yield {"type": "callout", "callout": "Helpful tip.", "style": "info"}
yield {"type": "callout", "callout": "Something failed.", "style": "error"}

# With optional title
yield {"type": "callout", "callout": "Saved.", "style": "success", "title": "Done"}
```

### Status Indicators

```python
yield {"type": "status", "status": "Connecting to database..."}
yield {"type": "status", "status": "Running query..."}
```

### Images

```python
yield {"type": "image", "src": "/public/chart.png", "alt": "Chart", "caption": "Q4 results"}
```

### HTML Passthrough

Raw HTML strings pass through for custom styling:

```python
yield '<div class="bg-gradient-to-r from-blue-500 to-purple-500 text-white p-4 rounded-lg">'
yield '<strong>Custom HTML</strong> works too!'
yield '</div>'
```

### Component Reference

| Component | Type | Required Keys | Streaming |
|-----------|------|---------------|-----------|
| Text | `text` | `text` | Accumulates |
| Thinking | `thinking` | `thinking` | Accumulates |
| Code | `code` | `code`, `language` | Accumulates |
| Table | `table` | `headers` or `row` | Row by row |
| Callout | `callout` | `callout`, `style` | Single |
| Image | `image` | `src` | Single |
| Status | `status` | `status` | Replaces |

---

## Declarative Infrastructure

All dependencies are declared in the decorator. No Dockerfiles needed.

### Python Packages

```python
@cycls.app(pip=["openai", "pandas", "numpy"])
async def data_app(context):
    import pandas as pd
    ...
```

### System Packages

```python
@cycls.app(pip=["Pillow"], apt=["ffmpeg", "imagemagick"])
async def media_app(context):
    ...
```

### Bundling Local Files

```python
@cycls.app(copy=["./utils.py", "./prompts/", "./models/config.json"])
async def custom_app(context):
    from utils import helper_function
    ...
```

### Static Assets

Files in `copy_public` are served at `/public`:

```python
@cycls.app(copy_public=["./assets/logo.png"])
async def branded_app(context):
    yield {"type": "image", "src": "/public/logo.png", "alt": "Logo"}
```

### Custom Build Commands

Run arbitrary shell commands during the Docker build:

```python
@cycls.app(
    apt=["curl", "xz-utils"],
    run_commands=[
        "curl -fsSL https://nodejs.org/dist/v24.13.0/node-v24.13.0-linux-x64.tar.xz | tar -xJ -C /usr/local --strip-components=1",
        "npm i -g some-tool",
    ]
)
async def tool_app(context):
    ...
```

### Image Caching

Cycls hashes your dependencies to create deterministic Docker tags. Same inputs = instant startup. Changed inputs = rebuild only what changed.

---

## Themes

Three built-in themes:

```python
@cycls.app(theme="default")   # Standard chat UI (downloaded at build time)
@cycls.app(theme="dev")       # Developer-oriented, darker
@cycls.app(theme="codex")     # Codex-style interface
```

### Header, Intro, and Title

```python
@cycls.app(
    title="DataBot",           # Browser tab title
    header="Welcome to DataBot", # Large text above chat
    intro="Ask me anything about your data." # Helper text before conversation starts
)
async def databot(context):
    yield "Processing..."
```

---

## Running Your App

### Local Development

```python
app.local()              # Docker with hot-reload (default)
app.local(watch=False)   # Docker without hot-reload
app.local(port=3000)     # Custom port

app._local()             # Non-Docker uvicorn (for debugging)
```

### Production Deployment

```python
import cycls
cycls.api_key = "YOUR_CYCLS_API_KEY"

@cycls.app(pip=["openai"], memory="512Mi")
async def my_agent(context):
    yield "Hello from production!"

my_agent.deploy()
```

Or set the key via environment:

```bash
export CYCLS_API_KEY=your_key_here
python my_app.py
```

---

## CLI

Chat with any running app from the terminal:

```bash
# By port
cycls chat 8080

# By URL
cycls chat https://my-agent.cycls.ai
```

Commands inside the CLI:
- `/q`, `exit`, `quit` - Exit
- `/c` - Clear conversation

The CLI renders all native components (thinking bubbles, tables, callouts, code blocks) in the terminal.

---

## Authentication

### Basic Auth

```python
@cycls.app(auth=True)
async def secure_app(context):
    user = context.user
    yield f"Welcome, {user.name}!\n"
    yield f"Email: {user.email}\n"
    yield f"ID: {user.id}\n"
```

### User Object

When `auth=True`, `context.user` contains:

| Property | Type | Description |
|----------|------|-------------|
| `user.id` | str | Unique user identifier |
| `user.name` | str | Display name |
| `user.email` | str | Email address |
| `user.org` | str | Organization (if set) |
| `user.plans` | list | Subscription plans |

### Organization-Based Access

```python
@cycls.app(auth=True, org="acme-corp")
async def org_app(context):
    yield f"Welcome to ACME Corp, {context.user.name}!"
```

---

## Analytics and Monetization

### Cycls Pass

Setting `plan="cycls_pass"` automatically enables both `auth` and `analytics`:

```python
@cycls.app(plan="cycls_pass")
async def premium_app(context):
    if "premium" in context.user.plans:
        yield "Premium features unlocked."
    else:
        yield "Upgrade for full access."
```

### Manual Analytics

```python
@cycls.app(auth=True, analytics=True)
async def tracked_app(context):
    yield "Usage is tracked."
```

---

## Integrating AI Providers

### OpenAI

```python
@cycls.app(pip=["openai"])
async def openai_chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    stream = await client.chat.completions.create(
        model="gpt-4",
        messages=context.messages,
        stream=True
    )
    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

openai_chat.local()
```

### OpenAI with Reasoning (o3-mini)

```python
@cycls.app(pip=["openai"], theme="dev")
async def reasoning_chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    stream = await client.responses.create(
        model="o3-mini",
        input=context.messages,
        stream=True,
        reasoning={"effort": "medium", "summary": "auto"},
    )
    async for event in stream:
        if event.type == "response.reasoning_summary_text.delta":
            yield {"type": "thinking", "thinking": event.delta}
        elif event.type == "response.output_text.delta":
            yield event.delta

reasoning_chat.local()
```

### Anthropic Claude

```python
@cycls.app(pip=["anthropic"])
async def claude_chat(context):
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic()

    async with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": m["role"], "content": m["content"]} for m in context.messages]
    ) as stream:
        async for text in stream.text_stream:
            yield text

claude_chat.local()
```

---

## Containerized Functions

For batch jobs, data processing, and services without a chat UI, use `@cycls.function()`.

### Basic Function

```python
import cycls

@cycls.function(pip=["numpy"])
def compute(x, y):
    import numpy
    return (y * numpy.arange(x)).tolist()

print(compute.run(5, 2))  # [0, 2, 4, 6, 8]
```

### Running Services

```python
@cycls.function(pip=["fastapi", "uvicorn"])
def api_server(port):
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/")
    async def root():
        return {"message": "Hello from a containerized FastAPI service"}

    uvicorn.run(app, host="0.0.0.0", port=port)

api_server.run(port=8000)
```

### Function vs App

| Feature | `@cycls.function` | `@cycls.app` |
|---------|-------------------|--------------|
| Input | Function arguments | `context.messages` |
| Output | Return value | Yield streaming |
| Web UI | No | Yes |
| Use case | Batch jobs, services | Chat interfaces |

### Function Methods

| Method | Description |
|--------|-------------|
| `.run(*args, **kwargs)` | Execute and return result |
| `.watch(*args, **kwargs)` | Run with file watching |
| `.build(*args, **kwargs)` | Build standalone Docker image |
| `.deploy(*args, **kwargs)` | Deploy to Cycls cloud |

---

## API Endpoints

Every app exposes these HTTP endpoints:

### Chat Endpoints

```
POST /              # Cycls streaming protocol (SSE)
POST /chat/cycls    # Same as above
POST /chat/completions  # OpenAI-compatible format
```

Request body:

```json
{
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}
```

Cycls SSE response:

```
data: {"type": "thinking", "thinking": "Processing..."}
data: {"type": "text", "text": "Hello!"}
data: [DONE]
```

OpenAI-compatible response:

```
data: {"choices": [{"delta": {"content": "Hello"}}]}
data: {"choices": [{"delta": {"content": "!"}}]}
data: [DONE]
```

### Configuration

```
GET /config
```

Returns the app's configuration (title, header, auth settings, etc.).

### Attachments (File Upload)

Upload files with token-based access:

```
POST /attachments
```

Multipart form with `file` field. Returns:

```json
{"url": "/attachments/<token>/<filename>"}
```

Download:

```
GET /attachments/<token>/<filename>
```

### Sessions API (requires auth)

Manage persistent conversation sessions:

```
GET    /sessions              # List all sessions
GET    /sessions/<id>         # Get session by ID
PUT    /sessions/<id>         # Create or update session
DELETE /sessions/<id>         # Delete session
```

Sessions are stored per-user under `/workspace/<user_id>/.sessions/`.

### File API (requires auth)

Full file management per user:

```
GET    /files                 # List files (?path=subdir)
GET    /files/<path>          # Get file (?download for attachment header)
PUT    /files/<path>          # Upload file (multipart)
PATCH  /files/<path>          # Rename (body: {"to": "new/path"})
POST   /files/<path>          # Create directory
DELETE /files/<path>          # Delete file or directory
```

Files are stored per-user under `/workspace/<user_id>/`. Path traversal is blocked.

---

## Decorator Reference

### @cycls.app()

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | function name | App name |
| `theme` | str | `"default"` | UI theme: `"default"`, `"dev"`, or `"codex"` |
| `pip` | list | `[]` | Python packages to install |
| `apt` | list | `[]` | System packages to install |
| `run_commands` | list | `[]` | Shell commands during Docker build |
| `copy` | list | `[]` | Local files/dirs to bundle |
| `copy_public` | list | `[]` | Static files served at `/public` |
| `auth` | bool | `False` | Enable JWT authentication |
| `org` | str | `None` | Organization identifier |
| `title` | str | `None` | Browser tab title |
| `header` | str | `None` | Header text above chat |
| `intro` | str | `None` | Introduction text |
| `plan` | str | `"free"` | `"free"` or `"cycls_pass"` |
| `analytics` | bool | `False` | Enable usage tracking |
| `memory` | str | `"1Gi"` | Memory allocation for deployment |
| `force_rebuild` | bool | `False` | Force Docker image rebuild |

### @cycls.function()

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | function name | Function name |
| `pip` | list | `[]` | Python packages to install |
| `apt` | list | `[]` | System packages to install |
| `run_commands` | list | `[]` | Shell commands during build |
| `copy` | list | `[]` | Local files/dirs to bundle |
| `python_version` | str | current | Python version for container |
| `force_rebuild` | bool | `False` | Force rebuild |

---

## Troubleshooting

**Docker not running**

```bash
# macOS/Windows: Start Docker Desktop
# Linux:
sudo systemctl start docker
```

**Missing API key**

```python
cycls.api_key = "your_key"
# or
export CYCLS_API_KEY=your_key
```

**Port already in use**

```python
app.local(port=3000)
```

**Package install fails** - check the package name, Python compatibility, and add `apt` deps for C extensions:

```python
@cycls.app(pip=["numpy"], apt=["gcc", "python3-dev"])
```

---

## Next Steps

- Explore the [examples](../examples/) directory for working code
- Join the community at [cycls.com](https://cycls.com)

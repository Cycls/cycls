<h3 align="center">
Distribute Intelligence
</h3>

<h4 align="center">
  <a href="https://cycls.com">Website</a> |
  <a href="https://docs.cycls.com">Docs</a>
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

The open-source SDK for distributing AI agents.

## Distribute Intelligence

Write a function. Deploy it as an API, a web interface, or both. Add authentication, analytics, and monetization with flags.

```python
import cycls

cycls.api_key = "YOUR_CYCLS_API_KEY"

@cycls.agent(pip=["openai"])
async def agent(context):
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
            yield {"type": "thinking", "thinking": event.delta}  # Renders as thinking bubble
        elif event.type == "response.output_text.delta":
            yield event.delta

agent.deploy()  # Live at https://agent.cycls.ai
```

## Installation

```bash
pip install cycls
```

Requires Docker.

## What You Get

- **Streaming API** - OpenAI-compatible `/chat/completions` endpoint
- **Web Interface** - Chat UI served automatically
- **Authentication** - `auth=True` enables JWT-based access control
- **Analytics** - `analytics=True` tracks usage
- **Monetization** - `plan="cycls_pass"` integrates with [Cycls Pass](https://cycls.ai) subscriptions
- **Native UI Components** - Render thinking bubbles, tables, code blocks in responses

## Running

```python
agent.local()             # Development with hot-reload (localhost:8080)
agent.local(watch=False)  # Development without hot-reload
agent.deploy()            # Production: https://agent.cycls.ai
```

Get an API key at [cycls.com](https://cycls.com).

## Authentication & Analytics

```python
@cycls.agent(pip=["openai"], auth=True, analytics=True)
async def agent(context):
    # context.user available when auth=True
    user = context.user  # User(id, email, name, plans)
    yield f"Hello {user.name}!"
```

| Flag | Description |
|------|-------------|
| `auth=True` | Universal user pool via Cycls Pass (Clerk-based). You can also use your own Clerk auth. |
| `analytics=True` | Rich usage metrics available on the Cycls dashboard. |
| `plan="cycls_pass"` | Monetization via Cycls Pass subscriptions. Enables both auth and analytics. |

## Native UI Components

Yield structured objects for rich streaming responses:

```python
@cycls.agent()
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
| `{"type": "table", "headers": [...]}` | Yes |
| `{"type": "table", "row": [...]}` | Yes |
| `{"type": "status", "status": "..."}` | Yes |
| `{"type": "callout", "callout": "...", "style": "..."}` | Yes |
| `{"type": "image", "src": "..."}` | Yes |

### Thinking Bubbles

The `{"type": "thinking", "thinking": "..."}` component renders as a collapsible thinking bubble in the UI. Each yield appends to the same bubble until a different component type is yielded:

```python
# Multiple yields build one thinking bubble
yield {"type": "thinking", "thinking": "Let me "}
yield {"type": "thinking", "thinking": "analyze this..."}
yield {"type": "thinking", "thinking": " Done thinking."}

# Then output the response
yield "Here's what I found..."
```

This works seamlessly with OpenAI's reasoning models - just map reasoning summaries to the thinking component.

## Context Object

```python
@cycls.agent()
async def chat(context):
    context.messages      # [{"role": "user", "content": "..."}]
    context.messages.raw  # Full data including UI component parts
    context.user          # User(id, email, name, plans) when auth=True
```

## API Endpoints

| Endpoint | Format |
|----------|--------|
| `POST chat/cycls` | Cycls streaming protocol |
| `POST chat/completions` | OpenAI-compatible |

## Streaming Protocol

Cycls streams structured components over SSE:

```
data: {"type": "thinking", "thinking": "Let me "}
data: {"type": "thinking", "thinking": "analyze..."}
data: {"type": "text", "text": "Here's the answer"}
data: {"type": "callout", "callout": "Done!", "style": "success"}
data: [DONE]
```

See [docs/streaming-protocol.md](docs/streaming-protocol.md) for frontend integration.

## Declarative Infrastructure

Define your entire runtime in the decorator:

```python
@cycls.agent(
    pip=["openai", "pandas", "numpy"],
    apt=["ffmpeg", "libmagic1"],
    copy=["./utils.py", "./models/", "/absolute/path/to/config.json"],
    copy_public=["./assets/logo.png", "./static/"],
)
async def my_agent(context):
    ...
```

### `pip` - Python Packages

Install any packages from PyPI. These are installed during the container build.

```python
pip=["openai", "pandas", "numpy", "transformers"]
```

### `apt` - System Packages

Install system-level dependencies via apt-get. Need ffmpeg for audio processing? ImageMagick for images? Just declare it.

```python
apt=["ffmpeg", "imagemagick", "libpq-dev"]
```

### `copy` - Bundle Files and Directories

Include local files and directories in your container. Works with both relative and absolute paths. Copies files and entire directory trees.

```python
copy=[
    "./utils.py",                    # Single file, relative path
    "./models/",                     # Entire directory
    "/home/user/configs/app.json",   # Absolute path
]
```

Then import them in your function:

```python
@cycls.agent(copy=["./utils.py"])
async def chat(context):
    from utils import helper_function  # Your bundled module
    ...
```

### `copy_public` - Static Files

Files and directories served at the `/public` endpoint. Perfect for images, downloads, or any static assets your agent needs to reference.

```python
copy_public=["./assets/logo.png", "./downloads/"]
```

Access them at `https://your-agent.cycls.ai/public/logo.png`.

---

### What You Get

- **One file** - Code, dependencies, configuration, and infrastructure together
- **Instant deploys** - Unchanged code deploys in seconds from cache
- **No drift** - What you see is what runs. Always.
- **Just works** - Closures, lambdas, dynamic imports - your function runs exactly as written

No YAML. No Dockerfiles. No infrastructure repo. The code is the deployment.

## License

MIT

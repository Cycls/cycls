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

AI capabilities shouldn't be locked in notebooks or trapped behind months of infrastructure work. Cycls turns your Python functions into production services - complete with APIs, interfaces, auth, and analytics. You focus on the intelligence. Cycls handles the distribution.

Write a function. Deploy it as an API, a web interface, or both. Add authentication, analytics, and monetization with flags.

```python
import cycls

agent = cycls.Agent(pip=["openai"])

@agent("my-agent", auth=True, analytics=True)
async def chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=context.messages,
        stream=True
    )

    async for chunk in response:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

agent.deploy()  # Live at https://my-agent.cycls.ai
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
- **Monetization** - `tier="cycls_pass"` integrates with [Cycls Pass](https://cycls.ai) subscriptions
- **Native UI Components** - Render thinking bubbles, tables, code blocks in responses

## Running

```python
agent.local()             # Development with hot-reload (localhost:8080)
agent.local(watch=False)  # Development without hot-reload
agent.deploy()            # Production: https://agent-name.cycls.ai
```

Get an API key at [cycls.com](https://cycls.com).

## Native UI Components

Yield structured objects for rich streaming responses:

```python
@agent()
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

### Reasoning Models

```python
@agent()
async def chat(context):
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
```

## Context Object

```python
@agent()
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

Define your entire runtime in Python:

```python
agent = cycls.Agent(
    pip=["openai", "pandas", "numpy"],
    apt=["ffmpeg", "libmagic1"],
    run_commands=["curl -sSL https://example.com/setup.sh | bash"],
    copy=["./utils.py", "./models/", "/absolute/path/to/config.json"],
    copy_public=["./assets/logo.png", "./static/"],
)
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

### `run_commands` - Shell Commands

Run arbitrary shell commands during the container build. Useful for custom setup scripts, downloading assets, or any build-time configuration.

```python
run_commands=[
    "curl -sSL https://example.com/setup.sh | bash",
    "chmod +x /app/scripts/*.sh"
]
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
@agent()
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

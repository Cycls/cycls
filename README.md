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

The function is the unit of abstraction in cycls. Your logic lives in a plain Python function — the decorator layers on everything else: containerization, authentication, deployment, analytics. You write the function, the `@` handles the infrastructure.

## Three Primitives

| Decorator | Purpose |
|-----------|---------|
| `@cycls.function()` | Containerized Python functions |
| `@cycls.app()` | Streaming chat applications |
| `@cycls.agent()` | **Agentic AI with tools and skills** |

## @cycls.agent() - Agentic AI

Build Claude Code-style agents with built-in tools and skills:

```python
import cycls

@cycls.agent(model="anthropic/claude-sonnet-4")
def coder():
    pass

coder.local()  # Full agent at localhost:8080
```

Out of the box you get:
- **Built-in tools**: read, write, edit, bash, glob, grep
- **Skills support**: Add capabilities via markdown files
- **Multi-provider**: `anthropic/`, `openai/` model prefixes
- **Streaming UI**: Tool calls and results rendered live

### Skills

Add Claude Code-style skills in `.cycls/skills/`:

```
.cycls/skills/
  code-review/
    SKILL.md
```

```yaml
# .cycls/skills/code-review/SKILL.md
---
name: code-review
description: Review code for bugs and best practices. Use when asked to review code.
allowed-tools: read, grep, glob
---

# Code Review

When reviewing code:
1. Read the file(s) to understand context
2. Check for bugs, security issues, performance problems
3. Provide specific feedback with line numbers
```

Skills are auto-discovered and available to the agent.

## @cycls.app() - Streaming Apps

Build streaming chat applications with full control over the response:

```python
import cycls

cycls.api_key = "YOUR_CYCLS_API_KEY"

@cycls.app(pip=["openai"])
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

chat.deploy()  # Live at https://chat.cycls.ai
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
my_app.local()             # Development with hot-reload (localhost:8080)
my_app.local(watch=False)  # Development without hot-reload
my_app.deploy()            # Production: https://my-app.cycls.ai
```

Get an API key at [cycls.com](https://cycls.com).

## Authentication & Analytics

```python
@cycls.app(pip=["openai"], auth=True, analytics=True)
async def chat(context):
    user = context.user  # User(id, email, name, plans)
    yield f"Hello {user.name}!"
```

| Flag | Description |
|------|-------------|
| `auth=True` | Universal user pool via Cycls Pass (Clerk-based). |
| `analytics=True` | Rich usage metrics on the Cycls dashboard. |
| `plan="cycls_pass"` | Monetization via Cycls Pass subscriptions. |

## Native UI Components

Yield structured objects for rich streaming responses:

```python
@cycls.app()
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

## Declarative Infrastructure

Define your entire runtime in the decorator:

```python
@cycls.app(
    pip=["openai", "pandas", "numpy"],
    apt=["ffmpeg", "libmagic1"],
    copy=["./utils.py", "./models/"],
    copy_public=["./assets/logo.png"],
)
async def my_app(context):
    ...
```

### `pip` - Python Packages

```python
pip=["openai", "pandas", "numpy", "transformers"]
```

### `apt` - System Packages

```python
apt=["ffmpeg", "imagemagick", "libpq-dev"]
```

### `copy` - Bundle Files

```python
copy=["./utils.py", "./models/", "/absolute/path/to/config.json"]
```

### `copy_public` - Static Files

```python
copy_public=["./assets/logo.png", "./downloads/"]
```

Access at `https://your-app.cycls.ai/public/logo.png`.

---

No YAML. No Dockerfiles. No infrastructure repo. The code is the deployment.

## License

MIT

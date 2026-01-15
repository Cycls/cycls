# Cycls Tutorial

This tutorial covers everything you need to build, deploy, and monetize AI agents with Cycls.

## What is Cycls?

Cycls is an open-source SDK for distributing intelligence. You write a Python function, and Cycls turns it into an API, a web interface, or both. Authentication, analytics, and monetization come built-in.

The core philosophy is simple: the code is the deployment. No YAML. No Dockerfiles. No infrastructure repositories. You write Python, and Cycls handles the rest.

## Prerequisites

Before starting, ensure you have:

- Python 3.10 or higher
- Docker installed and running
- A Cycls API key from [cycls.com](https://cycls.com)

## Installation

```bash
pip install cycls
```

## Quick Start

Here is the simplest possible Cycls app:

```python
import cycls

@cycls.app()
async def hello(context):
    yield "Hello! "
    yield "How can I help you today?"

hello.local()
```

Run this file, and you have a streaming chat interface at `http://localhost:8080`. Every `yield` streams to the user in real-time.

---

## Your First App

The `@cycls.app()` decorator transforms any generator function into a deployable web application.

```python
import cycls

@cycls.app()
async def greeter(context):
    user_message = context.last_message
    yield f"You said: {user_message}\n\n"
    yield "Thanks for using Cycls!"

greeter.local()
```

### Sync vs Async

Both synchronous and asynchronous generators work:

```python
# Async (recommended for I/O operations)
@cycls.app()
async def async_app(context):
    import asyncio
    await asyncio.sleep(0.1)
    yield "Async response"

# Sync (simpler for CPU-bound work)
@cycls.app()
def sync_app(context):
    yield "Sync response"
```

### Running Locally

Three ways to run your app:

```python
# Development with hot-reload (default)
app.local()

# Development without hot-reload
app.local(watch=False)

# Custom port
app.local(port=3000)
```

---

## The Context Object

Every app function receives a `context` object containing the conversation state.

```python
@cycls.app()
async def context_demo(context):
    # The last user message (most common use case)
    yield f"You asked: {context.last_message}\n\n"

    # Full conversation history
    yield f"Messages in conversation: {len(context.messages)}\n\n"

    # Iterate through history
    for msg in context.messages:
        role = msg["role"]  # "user" or "assistant"
        content = msg["content"]
        yield f"- {role}: {content[:50]}...\n"
```

### Context Properties

| Property | Type | Description |
|----------|------|-------------|
| `context.messages` | list | Conversation history as `[{"role": "...", "content": "..."}]` |
| `context.messages.raw` | list | Full messages with all metadata and parts |
| `context.last_message` | str | Shortcut for `context.messages[-1]["content"]` |
| `context.user` | User | User object when `auth=True` (see Authentication section) |

---

## Native UI Components

Plain text streaming works, but Cycls provides structured components for richer interfaces.

### Text

Plain strings become text components with full markdown support:

```python
@cycls.app()
async def text_demo(context):
    yield "# Heading\n\n"
    yield "This is **bold** and this is *italic*.\n\n"
    yield "- Bullet point\n"
    yield "- Another point\n"
```

### Thinking Bubbles

Show the agent's reasoning process:

```python
@cycls.app()
async def thinking_demo(context):
    # Multiple yields of the same type accumulate
    yield {"type": "thinking", "thinking": "Let me "}
    yield {"type": "thinking", "thinking": "analyze this "}
    yield {"type": "thinking", "thinking": "request..."}

    # Different type closes the thinking bubble
    yield "Here's my analysis:\n\n"
    yield "The answer is **42**."
```

### Code Blocks

Syntax-highlighted code with language specification:

```python
@cycls.app()
async def code_demo(context):
    yield "Here's the solution:\n\n"
    yield {
        "type": "code",
        "code": "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)",
        "language": "python"
    }
    yield "\n\nThis runs in O(2^n) time."
```

### Streaming Tables

Build tables row by row:

```python
@cycls.app()
async def table_demo(context):
    yield "## Server Status\n\n"

    # First: send headers
    yield {"type": "table", "headers": ["Server", "Status", "CPU", "Memory"]}

    # Then: stream rows one at a time
    yield {"type": "table", "row": ["web-1", "Online", "45%", "2.1 GB"]}
    yield {"type": "table", "row": ["web-2", "Online", "62%", "1.8 GB"]}
    yield {"type": "table", "row": ["db-1", "Online", "28%", "4.2 GB"]}
    yield {"type": "table", "row": ["cache-1", "Offline", "0%", "0 GB"]}
```

### Callouts

Highlighted message boxes with different styles:

```python
@cycls.app()
async def callout_demo(context):
    yield {"type": "callout", "callout": "Operation completed successfully!", "style": "success"}
    yield {"type": "callout", "callout": "Please review before proceeding.", "style": "warning"}
    yield {"type": "callout", "callout": "Here's some helpful information.", "style": "info"}
    yield {"type": "callout", "callout": "Something went wrong.", "style": "error"}

    # With optional title
    yield {"type": "callout", "callout": "Your changes have been saved.", "style": "success", "title": "Saved"}
```

### Images

Display images with optional captions:

```python
@cycls.app(copy_public=["./assets/chart.png"])
async def image_demo(context):
    yield "Here's the analysis:\n\n"
    yield {
        "type": "image",
        "src": "/public/chart.png",
        "alt": "Sales chart",
        "caption": "Q4 2024 sales performance"
    }
```

### Status Indicators

Show processing status:

```python
@cycls.app()
async def status_demo(context):
    yield {"type": "status", "status": "Connecting to database..."}
    # ... do work ...
    yield {"type": "status", "status": "Running query..."}
    # ... do work ...
    yield "Query complete!\n\n"
```

### Component Reference

| Component | Type | Keys | Streaming |
|-----------|------|------|-----------|
| Text | `text` | `text` | Accumulates |
| Thinking | `thinking` | `thinking` | Accumulates |
| Code | `code` | `code`, `language` | Accumulates |
| Table | `table` | `headers` or `row` | Row by row |
| Callout | `callout` | `callout`, `style`, `title` | Single |
| Image | `image` | `src`, `alt`, `caption` | Single |
| Status | `status` | `status` | Replaces |

---

## Declarative Infrastructure

Cycls handles dependencies declaratively. No Dockerfiles needed.

### Python Packages

```python
@cycls.app(pip=["openai", "pandas", "numpy", "requests"])
async def data_app(context):
    import pandas as pd
    import numpy as np
    # packages are available
```

### System Packages

```python
@cycls.app(
    pip=["python-magic", "Pillow"],
    apt=["libmagic1", "ffmpeg", "imagemagick"]
)
async def media_app(context):
    import magic
    # system libraries are installed
```

### Bundling Local Files

```python
@cycls.app(
    pip=["openai"],
    copy=["./utils.py", "./prompts/", "./models/config.json"]
)
async def custom_app(context):
    from utils import helper_function
    # local files are available in the container
```

### Static Assets

Files in `copy_public` are served at `/public`:

```python
@cycls.app(
    copy_public=["./assets/logo.png", "./assets/styles.css"]
)
async def branded_app(context):
    yield {"type": "image", "src": "/public/logo.png", "alt": "Logo"}
```

### How Caching Works

Cycls creates a deterministic hash of your dependencies. Same dependencies means instant startup. Changed dependencies triggers a rebuild of only what changed. This makes iteration fast.

---

## Integrating AI Providers

### OpenAI

```python
import cycls

@cycls.app(pip=["openai"])
async def openai_chat(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    # Show thinking
    yield {"type": "thinking", "thinking": "Processing with GPT-4..."}

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
import cycls

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
        # Map reasoning to thinking bubbles
        if event.type == "response.reasoning_summary_text.delta":
            yield {"type": "thinking", "thinking": event.delta}
        elif event.type == "response.output_text.delta":
            yield event.delta

reasoning_chat.local()
```

### Anthropic Claude

```python
import cycls

@cycls.app(pip=["anthropic"])
async def claude_chat(context):
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic()

    # Convert messages format
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in context.messages
    ]

    async with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=messages
    ) as stream:
        async for text in stream.text_stream:
            yield text

claude_chat.local()
```

### Claude Agent SDK

For agentic workflows with tool use:

```python
import cycls

@cycls.app(pip=["claude-agent-sdk"], copy=[".env"])
async def claude_agent(context):
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
    from claude_agent_sdk.types import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock

    async with ClaudeSDKClient(
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Glob", "Grep", "Bash", "WebSearch"],
            permission_mode="acceptEdits",
        )
    ) as client:
        await client.query(context.last_message)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield block.text
                    elif isinstance(block, ThinkingBlock):
                        yield {"type": "thinking", "thinking": block.thinking}
                    elif isinstance(block, ToolUseBlock):
                        yield {"type": "thinking", "thinking": f"Using tool: {block.name}"}

claude_agent.local()
```

---

## UI Customization

### Themes

Two built-in themes:

```python
# Default theme
@cycls.app(theme="default")
async def app1(context):
    yield "Default styling"

# Developer theme (darker, more technical)
@cycls.app(theme="dev")
async def app2(context):
    yield "Dev styling"
```

### Header, Intro, and Title

```python
@cycls.app(
    title="DataBot - AI Data Analyst",
    header="Welcome to DataBot",
    intro="I can help you analyze data, create visualizations, and generate reports. What would you like to explore?"
)
async def databot(context):
    yield "Processing your request..."
```

- `title` - Browser tab title
- `header` - Large text above the chat
- `intro` - Helper text shown before conversation starts

### HTML Passthrough

Raw HTML passes through for custom styling:

```python
@cycls.app()
async def custom_styled(context):
    yield '<div style="background: linear-gradient(to right, #667eea, #764ba2); color: white; padding: 20px; border-radius: 10px;">'
    yield '<h2>Custom Styled Content</h2>'
    yield '<p>You can use any HTML and CSS.</p>'
    yield '</div>'
```

---

## Authentication

Enable authentication to identify users and gate features.

### Basic Auth

```python
@cycls.app(auth=True)
async def secure_app(context):
    user = context.user

    yield f"Welcome, {user.name}!\n\n"
    yield f"Email: {user.email}\n"
    yield f"User ID: {user.id}\n"
```

### User Object

When `auth=True`, `context.user` contains:

| Property | Type | Description |
|----------|------|-------------|
| `user.id` | str | Unique user identifier |
| `user.name` | str | Display name |
| `user.email` | str | Email address |
| `user.org` | str | Organization (if set) |
| `user.plans` | list | List of subscription plans |

### Organization-Based Access

```python
@cycls.app(auth=True, org="acme-corp")
async def org_app(context):
    # Only users in acme-corp organization can access
    yield f"Welcome to the ACME Corp portal, {context.user.name}!"
```

---

## Analytics and Monetization

### Enabling Analytics

```python
@cycls.app(auth=True, analytics=True)
async def tracked_app(context):
    # Usage is automatically tracked
    yield "Your usage is being recorded for analytics."
```

### Monetization with Cycls Pass

```python
@cycls.app(plan="cycls_pass")
async def premium_app(context):
    # plan="cycls_pass" automatically enables auth and analytics
    user = context.user

    if "premium" in user.plans:
        yield "## Premium Features Unlocked\n\n"
        yield "You have access to all premium features."
    else:
        yield "## Free Tier\n\n"
        yield "Upgrade to premium for full access."
```

### Feature Gating

```python
@cycls.app(plan="cycls_pass")
async def gated_app(context):
    user = context.user

    # Basic features for everyone
    yield "## Basic Analysis\n\n"
    yield analyze_basic(context.last_message)

    # Premium features
    if "pro" in user.plans:
        yield "\n\n## Advanced Analysis (Pro)\n\n"
        yield analyze_advanced(context.last_message)
    else:
        yield "\n\n---\n"
        yield {"type": "callout", "callout": "Upgrade to Pro for advanced analysis.", "style": "info"}
```

---

## Error Handling

Errors are automatically caught and displayed to users.

### Automatic Error Display

```python
@cycls.app()
async def risky_app(context):
    yield "Processing...\n\n"

    # If this raises, the error appears in the UI
    result = some_operation_that_might_fail()

    yield f"Result: {result}"
```

### Graceful Degradation

```python
@cycls.app()
async def safe_app(context):
    yield "Processing your request...\n\n"

    try:
        result = risky_operation()
        yield f"Success: {result}"
    except ValueError as e:
        yield {"type": "callout", "callout": f"Invalid input: {e}", "style": "warning"}
        yield "Please try again with different input."
    except Exception as e:
        yield {"type": "callout", "callout": "Something went wrong.", "style": "error"}
        yield "Our team has been notified. Please try again later."
```

### Debug Mode

In local development, full tracebacks are shown. In production, only the error message appears.

---

## Deployment

### Development

```python
import cycls

@cycls.app(pip=["openai"])
async def my_agent(context):
    yield "Hello!"

# Local development with hot-reload
my_agent.local()

# Without hot-reload
my_agent.local(watch=False)

# Custom port
my_agent.local(port=3000)
```

### Production Deployment

```python
import cycls

cycls.api_key = "YOUR_CYCLS_API_KEY"

@cycls.app(pip=["openai"])
async def my_agent(context):
    yield "Hello from production!"

# Deploy to Cycls cloud
my_agent.deploy()
# Returns: https://my-agent.cycls.ai
```

You can also set the API key via environment variable:

```bash
export CYCLS_API_KEY=your_key_here
python my_app.py
```

---

## Containerized Functions

For batch jobs, data processing, and services, use `@cycls.function()`.

### Basic Function

```python
import cycls

@cycls.function(pip=["numpy"])
def compute_mean(data):
    import numpy as np
    return np.mean(data)

result = compute_mean.run([1, 2, 3, 4, 5])
print(result)  # 3.0
```

### Function vs App

| Feature | `@cycls.function` | `@cycls.app` |
|---------|-------------------|--------------|
| Input | Function arguments | `context.messages` |
| Output | Return value | Yield streaming |
| Web UI | No | Yes |
| Use case | Batch jobs, services | Chat interfaces |

### Running Services

```python
import cycls

@cycls.function(pip=["fastapi", "uvicorn"])
def api_server(port):
    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.get("/")
    def root():
        return {"status": "running"}

    @app.get("/compute/{x}")
    def compute(x: int):
        return {"result": x * 2}

    uvicorn.run(app, host="0.0.0.0", port=port)

api_server.run(port=8000)
# API available at http://localhost:8000
```

### Data Processing

```python
import cycls

@cycls.function(pip=["numpy", "pandas"])
def monte_carlo_pi(num_points: int = 1000000):
    import numpy as np

    # Generate random points
    points = np.random.rand(num_points, 2)

    # Count points inside unit circle
    distances = np.sqrt(points[:, 0]**2 + points[:, 1]**2)
    inside = np.sum(distances <= 1)

    # Estimate pi
    pi_estimate = 4 * (inside / num_points)

    return {"pi": float(pi_estimate), "points": num_points}

result = monte_carlo_pi.run(num_points=10000000)
print(f"Pi estimate: {result['pi']}")
```

### Function Methods

| Method | Description |
|--------|-------------|
| `.run(*args, **kwargs)` | Execute and return result |
| `.watch(*args, **kwargs)` | Run with file watching for development |
| `.build(*args, **kwargs)` | Build standalone Docker image |
| `.deploy(*args, **kwargs)` | Deploy to Cycls cloud |

---

## API Endpoints

Every deployed app exposes these endpoints:

### Cycls Protocol

```bash
POST /chat/cycls
Content-Type: application/json

{
  "messages": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi there!"},
    {"role": "user", "content": "How are you?"}
  ]
}
```

Response is Server-Sent Events:

```
data: {"type": "thinking", "thinking": "Processing..."}
data: {"type": "text", "text": "I'm doing great!"}
data: [DONE]
```

### OpenAI-Compatible

```bash
POST /chat/completions
Content-Type: application/json

{
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}
```

Response follows OpenAI streaming format:

```
data: {"choices": [{"delta": {"content": "Hello"}}]}
data: {"choices": [{"delta": {"content": " there!"}}]}
data: [DONE]
```

### Configuration

```bash
GET /config
```

Returns app configuration:

```json
{
  "title": "My App",
  "header": "Welcome",
  "intro": "How can I help?",
  "auth": true,
  "plan": "cycls_pass",
  "analytics": true
}
```

---

## Complete Examples

### AI Research Assistant

```python
import cycls

@cycls.app(
    pip=["openai"],
    theme="dev",
    title="Research Assistant",
    header="AI Research Assistant",
    intro="I can help you research topics, summarize papers, and find information."
)
async def research_assistant(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    yield {"type": "thinking", "thinking": "Analyzing your research question..."}

    system_prompt = """You are a research assistant. Help users:
    - Find relevant information on topics
    - Summarize complex papers and articles
    - Explain technical concepts clearly
    - Provide citations and sources

    Format responses with clear headings and bullet points."""

    messages = [{"role": "system", "content": system_prompt}] + context.messages

    stream = await client.chat.completions.create(
        model="gpt-4",
        messages=messages,
        stream=True
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

research_assistant.local()
```

### Data Dashboard

```python
import cycls
import asyncio

@cycls.app(
    pip=["pandas", "numpy"],
    title="Data Dashboard",
    header="Real-Time Data Dashboard"
)
async def data_dashboard(context):
    import pandas as pd
    import numpy as np

    yield {"type": "thinking", "thinking": "Generating dashboard data..."}

    yield "## System Metrics\n\n"

    # Streaming table
    yield {"type": "table", "headers": ["Metric", "Value", "Status"]}

    metrics = [
        ("CPU Usage", f"{np.random.randint(20, 80)}%", "Normal"),
        ("Memory", f"{np.random.uniform(2, 8):.1f} GB", "Normal"),
        ("Disk I/O", f"{np.random.randint(100, 500)} MB/s", "High"),
        ("Network", f"{np.random.randint(10, 100)} Mbps", "Normal"),
    ]

    for metric, value, status in metrics:
        await asyncio.sleep(0.3)  # Simulate real-time updates
        yield {"type": "table", "row": [metric, value, status]}

    yield "\n\n"
    yield {"type": "callout", "callout": "Dashboard updated successfully.", "style": "success"}

data_dashboard.local()
```

### Premium Service

```python
import cycls

@cycls.app(
    pip=["openai"],
    plan="cycls_pass",
    title="Premium AI Service",
    header="Premium AI Assistant"
)
async def premium_service(context):
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    user = context.user
    yield f"Welcome back, {user.name}!\n\n"

    # Check subscription
    is_premium = "premium" in user.plans

    if is_premium:
        model = "gpt-4"
        yield {"type": "callout", "callout": "Using GPT-4 (Premium)", "style": "success"}
    else:
        model = "gpt-3.5-turbo"
        yield {"type": "callout", "callout": "Using GPT-3.5 (Free tier). Upgrade for GPT-4.", "style": "info"}

    yield "\n"

    stream = await client.chat.completions.create(
        model=model,
        messages=context.messages,
        stream=True
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

premium_service.local()
```

---

## Decorator Parameters Reference

### @cycls.app()

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | function name | App name (used in URLs) |
| `theme` | str | `"default"` | UI theme: `"default"` or `"dev"` |
| `pip` | list | `[]` | Python packages to install |
| `apt` | list | `[]` | System packages to install |
| `copy` | list | `[]` | Local files to bundle |
| `copy_public` | list | `[]` | Static files served at `/public` |
| `auth` | bool | `False` | Enable authentication |
| `analytics` | bool | `False` | Enable usage tracking |
| `plan` | str | `"free"` | Plan: `"free"` or `"cycls_pass"` |
| `org` | str | `None` | Organization identifier |
| `title` | str | `None` | Browser tab title |
| `header` | str | `None` | Header text above chat |
| `intro` | str | `None` | Introduction text |

### @cycls.function()

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | function name | Function name |
| `pip` | list | `[]` | Python packages to install |
| `apt` | list | `[]` | System packages to install |
| `copy` | list | `[]` | Local files to bundle |
| `run_commands` | list | `[]` | Shell commands during build |
| `python_version` | str | current | Python version for container |

---

## Troubleshooting

### Docker not running

```
Error: Cannot connect to Docker daemon
```

Start Docker Desktop or the Docker service:

```bash
# macOS/Windows: Start Docker Desktop

# Linux
sudo systemctl start docker
```

### Missing API key

```
Error: CYCLS_API_KEY not set
```

Set your API key:

```python
import cycls
cycls.api_key = "your_key_here"
```

Or via environment:

```bash
export CYCLS_API_KEY=your_key_here
```

### Port already in use

```
Error: Address already in use
```

Use a different port:

```python
app.local(port=3000)
```

### Package installation fails

If a pip package fails to install, check:

1. Package name is correct
2. Package is compatible with Python version
3. For packages with C extensions, you may need `apt` dependencies

```python
@cycls.app(
    pip=["numpy", "pandas"],
    apt=["gcc", "python3-dev"]  # Build dependencies
)
```

---

## Next Steps

- Explore the [examples](../examples/) directory for more patterns
- Read the [streaming protocol](./streaming-protocol.md) for frontend integration
- Check [runtime documentation](./runtime.md) for containerization details
- Join the community at [cycls.com](https://cycls.com)

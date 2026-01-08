<h3 align="center">
Distribute Intelligence
</h3>

<h4 align="center">
  <a href="https://cycls.com">Website</a> |
  <a href="https://docs.cycls.com">Docs</a>
</h4>

<h4 align="center">
  <a href="https://pypi.python.org/pypi/cycls"><img src="https://img.shields.io/pypi/v/cycls.svg?label=cycls+pypi&color=blueviolet" alt="cycls Python package on PyPi" /></a>
  <a href="https://blog.cycls.com"><img src="https://img.shields.io/badge/newsletter-blueviolet.svg?logo=substack&label=cycls" alt="Cycls newsletter" /></a>
  <a href="https://x.com/cyclsai">
    <img src="https://img.shields.io/twitter/follow/CyclsAI" alt="Cycls Twitter" />
  </a>
</h4>

---

# Cycls

The open-source SDK for distributing AI agents.

Write a function. Deploy it as an API, a web interface, or both. Add authentication, analytics, and monetization with flags. Cycls handles containerization, streaming, and infrastructure.

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

agent.deploy(prod=True)  # Live at https://my-agent.cycls.ai
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

## Deploying

```python
agent.deploy(prod=False)  # Development: localhost:8080
agent.deploy(prod=True)   # Production: https://agent-name.cycls.ai
```

Get an API key at [cycls.com](https://cycls.com).

## Native UI Components

Yield structured objects for rich streaming responses:

```python
from cycls import UI

@agent()
async def demo(context):
    yield UI.thinking("Analyzing the request...")
    yield "Here's what I found:\n\n"

    yield UI.table(headers=["Name", "Status"])
    yield UI.table(row=["Server 1", "Online"])
    yield UI.table(row=["Server 2", "Offline"])

    yield UI.code("result = analyze(data)", language="python")
    yield UI.callout("Analysis complete!", type="success")
```

| Component | Streaming |
|-----------|-----------|
| `UI.thinking(content)` | Yes |
| `UI.code(content, language)` | Yes |
| `UI.table(headers=[], row=[])` | Yes |
| `UI.status(content)` | Yes |
| `UI.callout(content, type, title)` | No |
| `UI.image(src, alt, caption)` | No |

### Reasoning Models

```python
from cycls import UI

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
            yield UI.thinking(event.delta)
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
| `POST /` | Cycls streaming protocol |
| `POST /chat/cycls` | Cycls streaming protocol |
| `POST /chat/completions` | OpenAI-compatible |

## Streaming Protocol

Cycls streams structured components over SSE:

```
data: ["+", "thinking", {"content": "Let me "}]  # Start
data: ["~", {"content": "analyze..."}]           # Delta
data: ["-"]                                       # Close
data: ["=", {"name": "callout", "content": "!"}] # Complete
data: [DONE]
```

See [docs/streaming-protocol.md](docs/streaming-protocol.md) for frontend integration.

## Declarative Infrastructure

Your entire runtime is defined in Python. Dependencies, files, system packages - all declared where you use them:

```python
agent = cycls.Agent(
    pip=["openai", "pandas", "numpy"],
    apt=["ffmpeg", "libmagic1"],
    copy=["./models/classifier.pkl"],
    copy_public=["./assets/logo.png"],
)

@agent("my-agent", auth=True, analytics=True, tier="cycls_pass")
async def chat(context):
    import pandas as pd
    from classifier import predict
    ...
```

When you deploy, Cycls:

1. Resolves your Python version and dependencies
2. Generates a Dockerfile
3. Serializes your function with cloudpickle
4. Builds a container with the web server baked in
5. Deploys to serverless infrastructure

The result is a self-contained artifact. No external config files. No deployment scripts. No infrastructure drift. The code is the deployment.

## License

MIT

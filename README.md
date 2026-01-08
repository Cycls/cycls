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

Your entire runtime is defined in Python. No YAML. No Dockerfiles. No infrastructure repo.

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

### What Happens When You Deploy

Cycls builds a self-contained artifact from your code:

1. **Resolves your environment** - Python version, pip packages, apt packages, shell commands
2. **Generates a multi-stage Dockerfile** - Optimized layers for fast rebuilds
3. **Serializes your function** - Using cloudpickle to capture the function, its closures, and all references
4. **Hashes everything** - Dependencies, file contents, function bytecode → deterministic image tag
5. **Builds and caches** - Content-addressable images mean unchanged code = instant deploys
6. **Bakes in the web server** - FastAPI, streaming, auth - all included in the final image

The function *is* the deployment. Change a dependency, the hash changes, a new image builds. Change nothing, it deploys in seconds from cache.

### The Power of Serialization

Your function is serialized with [cloudpickle](https://github.com/cloudpipe/cloudpickle) - not just referenced, but captured entirely:

```python
# This works. The lambda, the closure, the dynamic import - all serialized.
model_name = "gpt-4o"

@agent()
async def chat(context):
    from openai import AsyncOpenAI  # Imported at runtime, inside the container
    client = AsyncOpenAI()

    process = lambda x: x.strip().lower()  # Closures work

    response = await client.chat.completions.create(
        model=model_name,  # Captured from outer scope
        messages=context.messages,
        stream=True
    )
    ...
```

The container doesn't import your module. It deserializes your function and runs it. This means:

- No `if __name__ == "__main__"` guards needed
- No module path issues
- No import order problems
- Your function runs exactly as written

### No Infrastructure Drift

Traditional deployment: code in one repo, infrastructure in another, configuration scattered across environment variables, secrets managers, and deploy scripts. They drift apart. Deploys break.

Cycls: the code *is* the infrastructure. One file. One truth. `git diff` shows you exactly what changed in your entire system - dependencies, configuration, and logic together.

## License

MIT

# Cycls

Python SDK for building, deploying, and monetizing AI agents. Write a function, deploy it as an API, web interface, or both.

## Tech Stack

- Python >= 3.9 (3.10+ for deployment)
- FastAPI + Uvicorn for web serving
- Docker for containerization
- uv for package management
- Cloudpickle for function serialization
- JWT (Clerk) for authentication

## Commands

```bash
# Install dependencies
uv sync --group test

# Run tests
uv run pytest tests/ -v -s

# Run example app
uv run examples/app/app.py

# Run example function
uv run examples/function/add.py

# Clean up Docker
docker system prune -af
```

## Project Structure

```
cycls/
├── cli.py                  # CLI: run, deploy, ls, rm, logs, init, version
├── function/
│   ├── main.py             # Function class + @cycls.function decorator
│   └── image.py            # cycls.Image fluent builder
├── app/
│   ├── main.py             # App class + @cycls.app + _make_decorator
│   ├── auth.py             # cycls.Clerk, cycls.JWT, User, make_validate
│   └── web.py              # cycls.Web fluent builder
└── agent/
    ├── main.py             # Agent class + @cycls.agent decorator
    ├── harness/            # LLM runtime (loop, tools, providers, compaction, prompts, pdf)
    │   └── llm.py          # cycls.LLM fluent builder
    ├── state/              # history I/O + sessions/files/share routers
    └── web/                # FastAPI chat server, OG images, themes
```

## Core Architecture

```
Agent extends App (chat product + managed LLM loop)
  └── App extends Function (blocking ASGI service)
      └── Function (Docker containerization)
```

## Key Patterns

**Decorator pattern** - `@cycls.function()` and `@cycls.app()` transform functions

**Generator pattern** - All functions must be generators using `yield`:
```python
@cycls.app()
async def my_app(context):
    yield "Hello!"  # Streams to client
```

**Declarative infrastructure** - Build config via the `cycls.Image` primitive:
```python
@cycls.function(image=cycls.Image().pip("numpy").apt("curl").copy("data/"))
def my_func(x):
    ...
```

## Streaming Components

Yield these from app functions:
- `"text"` or `{"type": "text", "text": "..."}` - Plain text
- `{"type": "thinking", "thinking": "..."}` - Thinking bubble
- `{"type": "code", "code": "...", "language": "..."}` - Code block
- `{"type": "table", "headers": [...]}` / `{"row": [...]}` - Tables
- `{"type": "status", "status": "..."}` - Status indicator
- `{"type": "callout", "callout": "...", "style": "info|warning|error|success"}`
- `{"type": "image", "src": "...", "alt": "...", "caption": "..."}`

## Environment Variables

- `CYCLS_API_KEY` - API key for production deployment
- `CYCLS_BASE_URL` - Base URL for deployment service
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` - For examples

## Code Style

- Use async for I/O operations, sync for CPU-bound work
- Functions are pickled - closures and lambdas work
- Yield frequently for responsive streaming UI
- Errors display as callouts in UI

## Testing

Tests require Docker running. Test files:
- `tests/app_test.py` - App decorator tests
- `tests/function_test.py` - Function integration tests
- `tests/web_test.py` - Web server tests

## Publishing

When asked to "publish":
1. Bump the version in `pyproject.toml`
2. Commit and push the changes to git (do not coauthor)
3. Run: `rm -rf dist && export $(cat .env | xargs) && uv build && uv publish`

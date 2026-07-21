# Cycls

Python SDK for building, deploying, and monetizing AI agents. Write a function, deploy it as an API, web interface, or both.

For a comprehensive walk through the primitives, decorators, CLI, and end-to-end patterns, see [docs/notes/tutorial.md](docs/notes/tutorial.md).

## Tech Stack

- Python >= 3.9 (3.10+ for deployment)
- FastAPI + Hypercorn for web serving (hypercorn for h2 end-to-end on Cloud Run)
- Docker for containerization
- uv for package management
- Cloudpickle for function serialization
- JWT (Clerk) for authentication

## Commands

```bash
# Install dependencies
uv sync --group test

# Run all backend tests (mocked; live tier auto-skipped)
uv run pytest tests/

# Run live tests against real Anthropic (needs ANTHROPIC_API_KEY)
set -a && source .providers.env && set +a
uv run pytest tests/agent/scenarios/test_live.py --live

# Run FE tests (vitest)
cd client && npm test

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
├── cli.py                  # CLI: run, deploy, shell, ls, rm, logs, cost, sql, init, version
├── function/
│   ├── main.py             # Function class + @cycls.function decorator
│   ├── image.py            # cycls.Image fluent builder
│   └── remote.py           # pickle-RPC shim + cycls.remote client (--remote deploys)
├── app/
│   ├── main.py             # App class + @cycls.app + _make_decorator
│   ├── auth.py             # cycls.Clerk, cycls.JWT, User, make_validate
│   └── web.py              # cycls.Web fluent builder
└── agent/
    ├── main.py             # Agent class + @cycls.agent decorator
    ├── state.py            # all agent state — chat meta+log+Session, shares, agent KV tool
    ├── mcp.py              # cycls.MCP — remote MCP servers via the Anthropic connector
    ├── tools/              # tool schemas + execution + dispatch registry (+ pdf.py, skills.py, Brave web search/fetch)
    ├── harness/            # the managed LLM loop and the kit a custom loop needs
    │   ├── llm.py          # cycls.LLM fluent builder (.loop(fn) swaps the loop; .price()/.context() set cost rates + window)
    │   ├── main.py         # the default loop (_run) + retry/recover + attachment ingest
    │   ├── providers/      # one streaming interface per vendor SDK
    │   │   ├── anthropic.py  # native Messages (cache breakpoints, thinking, MCP, server search)
    │   │   └── openai.py     # Chat Completions — also GLM (zai/*), Gemini-compat, Groq, vLLM via base_url
    │   ├── events.py       # typed loop events + to_ui (FE projection)
    │   ├── compact.py      # compaction — append-only marker, token-budgeted window, file ledger
    │   └── prompts.py      # system + compaction prompts + workspace instructions (AGENT.md)
    └── web/                # FastAPI chat server, state routers, OG images, themes
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
- `{"type": "ui", "action": "open_plan_modal"}` — fire-and-forget UI trigger; not rendered, not persisted in session history

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

Three tiers, mirrored to source:

```
tests/
├── conftest.py                  # autouse SlateDB pool reset; --live flag
├── function/                    # Function class + Image
├── app/                         # App, Sandbox argv, Workspace/DB, fence retry
├── agent/
│   ├── agent_test.py            # _run loop, retry, recovery, ingest, exec/_resolve_path
│   ├── chat_test.py             # to_ui_messages (FE projection) + _valid_prefix repair
│   ├── harness_test.py          # build_tools, web search/fetch, cost math, _resolve_path, LLM builder
│   ├── skills_test.py           # skill discovery, catalog text, the `skill` tool
│   ├── events_test.py           # to_ui wire shapes for the typed events
│   ├── pdf_test.py              # PDF page parsing
│   ├── web_test.py              # FastAPI routes, encoders, Messages, SEO/branding
│   ├── workspaces_test.py       # registry, ACL, team workspaces, admin lifecycle
│   ├── integration_test.py      # Agent on top of App
│   └── scenarios/
│       ├── test_load_repair.py  # SlateDB roundtrip + repair invariants
│       ├── test_database.py     # the `database` tool over the agent KV
│       └── test_live.py         # @pytest.mark.live, real Anthropic
└── client/src/hooks/__tests__/  # vitest — useChat + auth-header hooks
```

**Mocked tier** (default): no API calls, no docker. Runs in ~2min.
```bash
uv run pytest tests/                       # all ~325 mocked tests
uv run pytest tests/agent/ -v              # just agent tests
uv run pytest tests/agent/scenarios/ -v    # just scenarios
```

**Live tier** (gated `--live`): hits real Anthropic, costs ~$0.30-0.50/run, takes ~40s.
Needs `ANTHROPIC_API_KEY` (in `.providers.env` for dev). Skips silently without it.
```bash
set -a && source .providers.env && set +a
uv run pytest tests/agent/scenarios/test_live.py --live -v
```

**FE tier** (vitest): 16 tests — `useChat` (URL plumbing, callback identity stability, attachment blob fetch, retry gating) + `useAuthHeaders` (workspace header). Run from `client/`:
```bash
cd client && npm test           # one-shot
cd client && npm run test:watch # interactive
```

Function tests need Docker running.

## Publishing

When asked to "publish":
1. Bump the version in `pyproject.toml`
2. Commit and push the changes to git (do not coauthor)
3. Run: `rm -rf dist && export $(cat .env | xargs) && uv build && uv publish`

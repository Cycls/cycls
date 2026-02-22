# @cycls.agent — Design Doc

## Principles

1. **Cover the common cases** — Skills, MCPs, tool use, multi-model, memory
2. **Native Python loop behind FastAPI** — The agent loop is plain Python; the server is just plumbing
3. **Tiny engine** — The SDK does the minimum; push complexity to user code or upstream SDKs
4. **Developer control with great defaults** — Everything overridable, nothing mandatory
5. **No vendor lock-in** — Anthropic today, OpenAI-compatible response API tomorrow; the loop doesn't care

---

## What exists today

```
Agent(App)                        # Adds "anthropic" pip
ClaudeAgent(*, options) -> yield  # One-turn loop: stream → tool exec → repeat
```

`ClaudeAgent` is a **hardcoded Anthropic loop** that owns tool execution (bash, editor, web search), history (JSONL), and compaction. It works but violates principles 3–5: the engine is the vendor, and the developer can't swap anything.

---

## Target API

### Minimal example

```python
@cycls.agent()
async def my_agent(context):
    yield "Hello!"
```

Same yield-streaming contract as `@cycls.app`. No magic — an agent is an app that happens to loop.

### Full example

```python
@cycls.agent(
    model="claude-sonnet-4-20250514",   # default model
    tools=[search, calculator],          # python functions → auto-schema
    skills=[code_review, deploy],        # multi-step skills (chains of tools)
    mcp=["filesystem", "github"],        # MCP server names or URIs
    system="You are a helpful assistant.",
    memory=True,                         # enable conversation memory
)
async def my_agent(context):
    # context.messages  — full conversation
    # context.model     — configured model (can override per-turn)
    # context.tools     — resolved tool list
    # context.mcp       — connected MCP clients
    # context.memory    — read/write persistent memory
    # context.agent     — the agent loop helper

    response = await context.agent.run(context.last_message)
    async for chunk in response:
        yield chunk
```

### Escape hatch — bring your own loop

```python
@cycls.agent()
async def custom(context):
    import anthropic
    client = anthropic.AsyncAnthropic()

    messages = [{"role": "user", "content": context.last_message}]
    while True:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            messages=messages,
            tools=[...],
        )
        # stream text
        for block in response.content:
            if block.type == "text":
                yield block.text

        if response.stop_reason != "tool_use":
            break

        # execute tools yourself
        results = []
        for block in response.content:
            if block.type == "tool_use":
                result = await my_tool_dispatch(block)
                results.append(result)
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})
```

The decorator adds nothing the developer doesn't want. It's just `@cycls.app()` + agent defaults (pip, memory, etc).

---

## Architecture

```
┌─────────────────────────────────────────┐
│  @cycls.agent(tools, mcp, model, ...)   │  ← decorator: config + defaults
├─────────────────────────────────────────┤
│  context.agent.run(prompt)              │  ← optional built-in loop
│    ├── model.chat(messages, tools)      │  ← vendor-neutral call
│    ├── tool dispatch                    │  ← registered tools + MCP
│    └── repeat until done                │
├─────────────────────────────────────────┤
│  FastAPI SSE server (cycls/web.py)      │  ← unchanged
├─────────────────────────────────────────┤
│  Docker / Deploy (cycls/function.py)    │  ← unchanged
└─────────────────────────────────────────┘
```

### What the engine owns

| Concern | Engine does | Developer can override |
|---------|-------------|----------------------|
| **Model call** | Vendor-neutral wrapper | Bring any client |
| **Tool dispatch** | Auto-dispatch registered tools | Custom dispatch function |
| **MCP** | Connect to declared servers | Manual MCP client |
| **Memory** | JSONL history + compaction | Custom storage |
| **Streaming** | Yield-based SSE | Same |
| **Infra** | Docker + deploy | Same |

### What the engine does NOT own

- Prompt engineering
- Orchestration strategy (ReAct, plan-and-execute, etc.)
- Multi-agent coordination
- Guardrails / filtering
- Evaluation

These belong in user code or higher-level libraries.

---

## Key Components

### 1. Tools — Python functions with auto-schema

```python
def search(query: str) -> str:
    """Search the web for information."""
    return requests.get(f"https://api.search.com?q={query}").text

@cycls.agent(tools=[search])
async def agent(context):
    response = await context.agent.run(context.last_message)
    async for chunk in response:
        yield chunk
```

A tool is any callable with type hints. The engine extracts the JSON schema from the signature. No special base class, no decorator required.

For tools that need async or streaming feedback:

```python
async def deploy(repo: str, branch: str = "main") -> str:
    """Deploy a repository to production."""
    # long-running tool — can't stream mid-execution (tool results are atomic)
    result = await run_deploy(repo, branch)
    return f"Deployed {repo}@{branch}: {result}"
```

### 2. Skills — named multi-step capabilities

```python
code_review = Skill(
    name="code_review",
    description="Review code changes and suggest improvements",
    tools=[read_file, write_file, run_tests],
    instructions="Review the code, run tests, suggest fixes.",
)

@cycls.agent(skills=[code_review])
async def agent(context):
    ...
```

A skill is a named bundle of tools + instructions. When the model decides to invoke a skill, the engine runs a sub-loop with those tools and instructions injected. Skills compose — a skill can reference other skills.

**Open question:** Should skills be a first-class concept or just a pattern (a tool that internally runs another agent loop)? Leaning toward pattern — keep the engine small.

### 3. MCP — first-class server connections

```python
@cycls.agent(mcp=["filesystem", "github"])
async def agent(context):
    # context.mcp["filesystem"] — MCP client
    # tools from MCP servers appear in context.tools automatically
    ...
```

MCP servers declared in the decorator are connected at startup. Their tools are merged into the agent's tool list. The developer can also connect MCP servers manually:

```python
@cycls.agent()
async def agent(context):
    async with mcp_connect("github") as gh:
        tools = await gh.list_tools()
        ...
```

### 4. Model — vendor-neutral interface

```python
class Model:
    async def chat(self, messages, tools=None, **kwargs) -> AsyncIterator:
        """Send messages, get streaming response."""
        ...
```

Ship two implementations:

- `AnthropicModel` — wraps `anthropic.AsyncAnthropic`
- `OpenAIModel` — wraps OpenAI-compatible APIs (OpenAI, Groq, Together, etc.)

The `model` decorator param accepts:
- A string: `"claude-sonnet-4-20250514"` → auto-detect vendor from model name
- A `Model` instance: full control

```python
from cycls.models import OpenAIModel

@cycls.agent(model=OpenAIModel("gpt-4o", base_url="https://..."))
async def agent(context):
    ...
```

### 5. Memory — conversation persistence

Enabled by default. JSONL history per session, same as today.

```python
@cycls.agent(memory=True)  # default
async def agent(context):
    # context.memory.messages — loaded history
    # context.memory.save()  — explicit save
    # compaction happens automatically at threshold
    ...
```

Disable with `memory=False`. Swap storage with a custom backend:

```python
@cycls.agent(memory=RedisMemory(url="redis://..."))
async def agent(context):
    ...
```

### 6. Workspace — `/workspace` is a GCP bucket

In production, `/workspace` is a 1:1 mount of a GCP Cloud Storage bucket. The agent reads and writes files to `/workspace` using normal filesystem calls — the platform handles sync to the bucket transparently.

```
Local dev:    /workspace → local directory
Production:   /workspace → GCS bucket (1:1 sync)
```

This means:
- **Files persist across container restarts** — the bucket is the source of truth
- **File uploads land in `/workspace`** — context file handling already writes there
- **Tools (bash, editor) operate on real files** — no special API needed
- **Per-user isolation** — `/workspace/{user_id}` or `/workspace/{org_id}` as today

The developer never thinks about storage. `/workspace` just works — locally it's a directory, in prod it's a bucket.

---

## What changes from today

| Today | Next |
|-------|------|
| `ClaudeAgent` is a monolith | Split into Model + Tools + Memory |
| Tools are hardcoded (bash, editor, web_search) | Tools are declared, auto-dispatched |
| Anthropic-only | Vendor-neutral Model interface |
| No MCP | First-class MCP support |
| Agent class just adds pip | Agent class wires up the loop |
| Developer must write the full loop | `context.agent.run()` does it; override if needed |

## What stays the same

- `yield` streaming contract
- SSE transport via FastAPI
- Docker containerization
- Deploy pipeline
- Auth (Clerk JWT)
- The developer's function is the entry point

---

## Implementation order

1. **Tool registry** — auto-schema from type hints, dispatch by name
2. **Model abstraction** — `AnthropicModel` first, extract from current `ClaudeAgent`
3. **Agent loop** (`context.agent.run`) — model + tool dispatch + yield
4. **Memory** — extract JSONL logic, make pluggable
5. **MCP integration** — connect servers, merge tools
6. **OpenAI Model** — second vendor
7. **Skills** — if warranted (may stay as a pattern)

---

## Open questions

- **Tool streaming**: Should tools be able to yield status updates mid-execution? Today we yield `step` before and `step_data` after. Could allow tools to yield directly.
- **Multi-agent**: Out of scope for the engine, but should `context.agent.run()` be callable from tools to enable agent-as-tool patterns?
- **Approval / human-in-the-loop**: Keep the current confirmation pattern or formalize it?
- **Rate limiting / cost tracking**: Engine concern or user concern?

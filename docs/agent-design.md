# @cycls.agent — Implementation Notes

Companion to [agent.md](agent.md). Research from NanoClaw and notes on how to get from today's `ClaudeAgent` monolith to the target API.

---

## Research: NanoClaw (github.com/qwibitai/nanoclaw)

~4k lines TypeScript. WhatsApp-connected Claude agent in Docker containers. Anthropic-only (Claude Agent SDK / Claude Code as subprocess). Relevant design patterns:

### What to steal

**MCP via config dict** — NanoClaw registers MCP servers as a simple config object passed to the SDK:
```javascript
mcpServers: {
    nanoclaw: {
        command: 'node',
        args: [mcpServerPath],
        env: { NANOCLAW_CHAT_JID: ..., NANOCLAW_GROUP_FOLDER: ... },
    },
},
```
Their MCP server exposes 7 tools (send_message, schedule_task, etc.) over stdio JSON-RPC. Tools from MCP servers merge into the agent's tool list automatically. This maps directly to our target API:
```python
@cycls.agent(mcp=["filesystem", "github"])
```
Underneath, it's subprocess management + JSON-RPC. Three calls: `initialize`, `tools/list`, `tools/call`. ~80 lines.

**Hooks via callbacks** — Two hooks: `PreToolUse` (strips env vars from bash commands before execution) and `PreCompact` (archives transcript to markdown before context compaction). Clean pattern. Maps to our tool registry — each tool can have before/after hooks, or the agent loop exposes them globally.

**Tool allow-list** — NanoClaw declares exactly which tools are available:
```javascript
allowedTools: ['Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebSearch', 'mcp__nanoclaw__*']
```
We get this for free with the `tools=` decorator param. Only declared tools exist.

### What to skip

**Claude Agent SDK dependency** — They run Claude Code as a subprocess (Node.js + npm). Heavy, opaque, vendor-locked. Our native Python loop is better — lighter, portable, and we control the tool execution. The SDK handles tool execution internally, which means the developer can't intercept, modify, or replace tool behavior. Our `context.agent.run()` yields chunks the developer can filter.

**Sentinel-marker streaming** — They parse stdout for `---NANOCLAW_OUTPUT_START---` markers. Result-level, not token-level. Our SSE streaming is real-time text deltas — much better for web UI.

**Container-per-group isolation** — Security via Docker. Overkill for our model where the agent loop runs server-side behind FastAPI. We already have workspace-per-user isolation. Container security is a deployment concern (Docker in `function.py`), not an agent concern.

**Session resumption via SDK** — They pass `resume: sessionId` to the Claude Agent SDK, which manages history internally. Opaque — can't inspect, migrate, or compact history yourself. Our JSONL approach is portable and transparent. Maps to `context.memory`.

**Skills engine** — NanoClaw has a separate `/skills-engine/` (~50 files) for Claude Code slash commands that transform source code. A dev-time concept, not a runtime one. Our Skills (named bundles of tools + instructions) are a different, simpler idea.

### Comparison matrix

| Concern | NanoClaw | Target cycls API | Notes |
|---------|----------|-----------------|-------|
| **Model** | Anthropic-only (Claude Agent SDK) | Vendor-neutral `Model` interface | They didn't try multi-vendor |
| **Tools** | SDK-native (Bash, Read, etc.) | Python functions → auto-schema | Ours gives more control |
| **MCP** | stdio config dict, tools auto-merge | `mcp=["name"]` decorator param | Same idea, we need to build it |
| **Tool dispatch** | Internal to SDK, no interception | `context.agent.run()` → yield → developer filters | Our outer-loop pattern is better |
| **Memory** | SDK-managed sessions + pre-compact hook | JSONL + pluggable backend | Ours is more flexible |
| **Streaming** | Result-level (sentinel markers on stdout) | Token-level SSE | Ours is better for web |
| **Multi-modal** | Text-only (WhatsApp limitation) | Native content blocks (images, PDFs) | They punted, we should do it |
| **Concurrency** | Per-group container queue (max 5) | `asyncio.gather` on parallel tool calls | Different levels — we parallelize tools, they parallelize users |

---

## Implementation mapping to agent.md

### Step 1: Tool registry (agent.md §1)

Extract from `ClaudeAgent`'s hardcoded tool handling into a registry.

**Today:** `_build_tools` hardcodes bash/editor/web_search. Custom tools are yielded outward.
**Target:** Tools are Python functions with auto-schema. The engine dispatches all of them.

```python
# Auto-schema from type hints (inspect module)
def _tool_schema(fn):
    hints = get_type_hints(fn)
    params = inspect.signature(fn).parameters
    return {
        "name": fn.__name__,
        "description": fn.__doc__ or "",
        "input_schema": {
            "type": "object",
            "properties": {p: _type_to_json(hints.get(p)) for p in params if p != "return"},
            "required": [p for p, v in params.items() if v.default is inspect.Parameter.empty],
        }
    }
```

**NanoClaw insight:** They delegate all tool execution to the SDK. We should do the opposite — own the dispatch, call the functions directly. This is what makes `tools=[search, calculator]` work.

Built-in tools (bash, editor, web_search) become regular tools with default implementations, not special cases:
```python
DEFAULT_TOOLS = [bash, text_editor, web_search]  # pre-built functions

@cycls.agent(tools=DEFAULT_TOOLS + [my_custom_tool])
```

### Step 2: Model abstraction (agent.md §4)

Extract Anthropic-specific code from `ClaudeAgent` into `AnthropicModel`.

**What's vendor-specific in today's code:**
- Tool type IDs: `bash_20250124`, `text_editor_20250728`, `web_search_20250305`
- `thinking: {"type": "adaptive"}`
- `cache_control: {"type": "ephemeral"}`
- Stream event types: `thinking_delta`, `text_delta`, `input_json_delta`
- `response.stop_reason == "tool_use"`
- `response.usage.cache_read_input_tokens`

**What's already vendor-neutral:**
- `_exec_bash`, `_exec_editor` — pure tool execution
- JSONL history format
- The yield-based streaming pattern
- Workspace/session management

The `Model.chat()` interface returns a normalized stream — text chunks, tool calls, thinking blocks. The agent loop doesn't know which vendor produced them.

**NanoClaw insight:** They didn't try this at all (fully locked to Claude Agent SDK). Confirms this is a differentiator for us. But don't over-abstract — start with Anthropic, extract the interface once we add OpenAI.

### Step 3: Agent loop — `context.agent.run()` (agent.md §architecture)

Refactor `ClaudeAgent` into a method on the agent context. The loop becomes:

```python
async def run(self, prompt):
    messages = self.memory.load()
    messages.append({"role": "user", "content": prompt})
    while True:
        async for chunk in self.model.chat(messages, self.tools):
            if chunk.type == "text":
                yield chunk.text
            elif chunk.type == "tool_call":
                yield {"type": "step", "step": f"{chunk.name}(...)"}
                result = await self.dispatch(chunk.name, chunk.input)
                # ... append to messages, continue loop
        if not tool_calls:
            break
    self.memory.save(messages)
```

**Key difference from today:** The developer calls `context.agent.run()` and iterates the result. They can filter, transform, or intercept anything mid-stream. The escape hatch is: don't call `context.agent.run()` at all, write your own loop.

### Step 4: Memory (agent.md §5)

Extract JSONL history + compaction from `ClaudeAgent` into a `Memory` interface.

**Today's code to extract:** `_load_history`, `_append_history`, `_rewrite_history`, `_compact`, cache_control management.

```python
class Memory:
    async def load(self) -> list: ...
    async def save(self, messages): ...
    async def compact(self, messages) -> list: ...

class JSONLMemory(Memory):
    # Today's implementation, extracted
```

Compaction stays automatic (threshold-based) but hookable via `before_compact`.

### Step 5: MCP integration (agent.md §3)

**Implementation — the core is ~80 lines:**

```python
class MCPClient:
    """Manage a stdio MCP server subprocess."""

    async def connect(self, command, args, env):
        self.proc = await asyncio.create_subprocess_exec(
            command, *args, stdin=PIPE, stdout=PIPE, env={**os.environ, **env})
        await self._rpc("initialize", {"protocolVersion": "2025-03-26", ...})
        await self._notify("notifications/initialized")

    async def list_tools(self) -> list:
        result = await self._rpc("tools/list")
        return result.get("tools", [])

    async def call_tool(self, name, arguments) -> str:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        return "\n".join(c.get("text", "") for c in result.get("content", []))

    async def _rpc(self, method, params=None):
        # JSON-RPC over stdin/stdout, simple line-based protocol
```

MCP tools get namespaced (`mcp__{server}__{tool}`) and merged into the tool list. The agent loop dispatches them like any other tool.

**NanoClaw insight:** Their MCP server uses the `@modelcontextprotocol/sdk` npm package for the server side. For the client side (connecting to MCP servers), the Claude Agent SDK handles it internally via the `mcpServers` config. We need to implement the client ourselves, but it's just JSON-RPC — three methods.

### Step 6: Multi-modal input

NanoClaw punted (WhatsApp = text-only). We should handle this properly.

**Changes to `setup_workspace`:**
```python
def setup_workspace(context):
    # ... workspace setup ...
    content_blocks = []
    for p in content:
        if p.get("type") == "text":
            content_blocks.append({"type": "text", "text": p["text"]})
        elif p.get("type") == "image":
            data = base64.b64encode(open(src, "rb").read()).decode()
            content_blocks.append({"type": "image", "source": {"type": "base64", "media_type": ..., "data": data}})
        elif p.get("type") == "file":
            # Copy to workspace + text hint (model reads via tools)
            shutil.copy(src, f"{ws}/{fname}")
            content_blocks.append({"type": "text", "text": f"[USER UPLOADED {fname}]"})
    return ws, content_blocks
```

Images go as vision blocks (SDK handles them). Non-visual files go to workspace (agent reads them with tools). PDFs can use Anthropic's document type or fallback to workspace.

---

## Implementation order (aligned with agent.md)

```
1. Tool registry          — auto-schema, dispatch by name, DEFAULT_TOOLS
2. AnthropicModel         — extract vendor code from ClaudeAgent
3. context.agent.run()    — the new loop using Model + Tools
4. Memory                 — extract JSONL, make pluggable
5. MCP client             — stdio JSON-RPC, tool merging
6. Multi-modal            — content blocks in setup_workspace
7. OpenAIModel            — second vendor (later)
```

Each step is independently shippable. The old `ClaudeAgent` stays until step 3 is done, then it's replaced.

---

## Size budget

agent.md says "tiny engine." Target: **agent.py stays under 500 lines** after all of this.

| Component | Estimate |
|-----------|----------|
| Tool registry + auto-schema | ~60 lines |
| AnthropicModel | ~80 lines |
| Agent loop (context.agent.run) | ~60 lines |
| Memory (JSONL + compact) | ~60 lines (already exists) |
| MCP client | ~80 lines |
| Multi-modal setup | ~30 lines |
| Wiring / dataclasses | ~40 lines |
| **Total** | **~410 lines** |

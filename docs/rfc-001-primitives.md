# RFC 001: Declarative Primitives API

**Status**: Draft — parked
**Target**: 6-8 weeks out, after pricing + multi-LLM work
**Release**: `cycls 1.0` (hard break, no backwards compatibility)

---

## Summary

Replace the current grab-bag decorator kwargs with three fluent primitives (`Image`, `Web`, `LLM`) and three clean decorators (`@function`, `@app`, `@agent`). Add a CLI alongside the existing `.local()` / `.deploy()` methods. Tool handling via `async for call in context`.

## Decisions locked

- Three primitives: `Image`, `Web`, `LLM` — fluent immutable builders
- Three decorators: `@function(image=)`, `@app(image=, web=)`, `@agent(image=, web=, llm=)`
- `@agent` is a proper decorator, not an inline generator
- Tool handling via `async for call in context`
- HTTP route extension via `app.server.api_route(...)`
- CLI (`cycls run`, `cycls deploy`) alongside existing `.local()` / `.deploy()` methods
- `@agent` bodies only consume tool calls via `async for` — no `yield` path. Users who need to inject UI events mid-loop drop down to `@app` and write the loop manually.
- Hard break at `cycls 1.0` — no deprecation layer, no legacy kwargs

---

## Why

Today's pain:

- **Kwarg passthrough**: `@app` extends `@function`, dragging `pip`/`apt`/`copy` through the hierarchy.
- **Mixed concerns**: `@app(pip=[...], auth=True, plan="...", title="...")` mixes env + UI + billing + brand in one signature.
- **`cycls.Agent` isn't a decorator** — it's an inline generator, forcing users to wire it up and bloating `@app` with agent-specific routers.
- **Custom tools have no handlers** — schemas are dicts, `_dispatch` silently returns placeholders.
- **No CLI** — `.local()` / `.deploy()` on import forces `if __name__ == "__main__":` ceremony.

## Why now (or rather: not now)

The refactor is the right destination, not the right first stop. Revenue-critical work must ship first:

1. Pricing / Anthropic cost exposure
2. Multi-LLM abstraction
3. `@agent` as a proper decorator + move `state.py`
4. **Then** this RFC

---

## Design

```
Primitives (fluent immutable builders):
  cycls.Image   — env + resources (pip, apt, copy, memory, cpu, gpu, timeout)
  cycls.Web     — UI/brand/auth (auth, title, analytics, plan, theme)
  cycls.LLM     — model config (model, system, tools, builtin_tools, max_tokens, thinking)

Decorators:
  @cycls.function(image=)                   — compute
  @cycls.app(image=, web=)                  — service (user owns the loop)
  @cycls.agent(image=, web=, llm=)          — agent (managed loop)

Extensions:
  app.server.api_route(...)                 — arbitrary FastAPI routes
  async for call in context                 — tool handlers in @agent bodies

CLI:
  cycls run file.py                          — local Docker (hot reload) → app.local()
  cycls deploy file.py                       — production → app.deploy()
```

---

## Primitives

All three are **fluent immutable builders**. Every method returns a new instance. Scalars replace, list fields extend.

### `cycls.Image`

```python
image = (
    cycls.Image()
    .pip("openai", "anthropic")
    .apt("poppler-utils", "ripgrep", "jq")
    .copy("./utils.py")
    .run("npm i -g prettier")
    .volume("/workspace")     # create cloud bucket + gfuse mount
    .memory("1Gi")
    .cpu(2.0)
    .timeout(300)
)
```

| Method | Signature | Semantics |
|---|---|---|
| `cycls.Image()` | — | Empty base |
| `.pip(*pkgs)` | varargs | Add pip packages |
| `.apt(*pkgs)` | varargs | Add apt packages |
| `.run(*cmds)` | varargs | Shell commands executed **at image build time** (not request time) |
| `.copy(src, dest=None)` | path(s) | Copy files/dirs into image |
| `.env(**kv)` | kwargs | Environment variables |
| `.volume(path)` | str \| None | Create cloud bucket and gfuse-mount at `path`. `None` = ephemeral (no volume). |
| `.memory(size)` | str | `"1Gi"` |
| `.cpu(n)` | float | CPU count |
| `.gpu(kind)` | str | `"A100"` |
| `.timeout(seconds)` | int | Request timeout |

Composition via chaining:

```python
base = cycls.Image().pip("httpx").apt("curl")
heavy = base.pip("pandas").memory("4Gi")
```

**Cloud volume** (`.volume()`) — when set, Cycls creates a cloud bucket for this app and gfuse-mounts it at the given path. Files written to the mount persist across invocations. Omit or pass `None` for ephemeral (container filesystem only, wiped on restart).

```python
# Stateless compute — no volume
image = cycls.Image().pip("numpy")

# Stateful agent — cloud-backed workspace at /workspace
image = cycls.Image().pip("anthropic").volume("/workspace")

# Custom mount path
image = cycls.Image().pip("...").volume("/var/state")
```

`cycls.Image.agent()` is a preset with the minimum apt packages + workspace volume agents need. Locked floor: `.apt("bubblewrap", "poppler-utils", "ripgrep", "jq").volume("/workspace")`. Additional defaults may be added at implementation time.

### `cycls.Web`

```python
web = (
    cycls.Web()
    .auth(True)
    .analytics(True)
    .plan("cycls_pass")
    .title("My App")
    .theme("default")
    .og_image(True)
    .transcription(True)
)
```

| Method | Signature | Purpose |
|---|---|---|
| `cycls.Web()` | — | Empty base |
| `.auth(provider)` | bool \| obj | `True` for default Clerk, or a provider object |
| `.analytics(enabled)` | bool \| obj | Posthog or custom |
| `.plan(name)` | str | Billing plan |
| `.title(s)` | str | App title |
| `.theme(name)` | str | UI theme |
| `.og_image(enabled)` | bool | OG image endpoint |
| `.transcription(enabled)` | bool | Voice input endpoint |

**Auth providers**. v1 ships with two: `cycls.Clerk` (the Cycls Pass auth app in `cycls/app/auth.py` today) and `cycls.JWT` (generic OIDC for everything else). `.auth(True)` is shorthand for `.auth(cycls.Clerk())` — defaults to the Cycls-hosted Clerk tenant.

```python
web = cycls.Web().auth(True)               # default Cycls Pass Clerk tenant
web = cycls.Web().auth(cycls.Clerk())      # same — explicit
web = cycls.Web().auth(cycls.Clerk(instance="clerk.example.com"))  # custom Clerk tenant

# Any OIDC-compliant provider (Auth0, WorkOS, Firebase, Supabase, Okta, Cognito, Azure AD, Keycloak)
web = cycls.Web().auth(cycls.JWT(
    jwks_url="https://issuer.example.com/.well-known/jwks.json",
    issuer="https://issuer.example.com",
    audience="my-api",   # optional — verified when present
))
```

`cycls.Clerk` wraps the existing `app/auth.py` constants (default `instance="clerk.cycls.ai"`). `cycls.JWT` is a ~50-line base: fetch JWKS, cache, verify signature, check `iss` and (when configured) `aud` claims, return a user object. `audience` is **optional** — Clerk and similar issuer-based providers don't use it; Auth0, Firebase, Supabase, WorkOS, Cognito, Okta, and Azure AD do. Set it when your provider requires it; omit it otherwise. Named providers for Auth0, WorkOS, etc. can be added later as thin wrappers (~10 lines each) when customers ask — until then, they use `cycls.JWT(...)` directly.

### `cycls.LLM`

```python
llm = (
    cycls.LLM()
    .model("claude-sonnet-4-6")
    .system("You are Cycls.")
    .tools(*TOOLS)
    .builtin_tools("Bash", "Editor", "WebSearch")
    .max_tokens(16384)
    .thinking(True)
    .bash_timeout(600)
)
```

| Method | Signature | Purpose |
|---|---|---|
| `cycls.LLM()` | — | Empty base |
| `.model(name)` | str | Model identifier |
| `.system(prompt)` | str | System prompt |
| `.tools(*schemas)` | varargs | Custom tool schemas (extends) |
| `.builtin_tools(*names)` | varargs | Cycls built-ins (extends) |
| `.max_tokens(n)` | int | Max output tokens |
| `.thinking(enabled)` | bool | Extended thinking |
| `.bash_timeout(seconds)` | int | Default bash timeout |

---

## Decorators

### `@cycls.function`

```python
@cycls.function(image=image)
def compute(x, y):
    import numpy
    return (y * numpy.arange(x)).tolist()
```

### `@cycls.app` — user owns the loop

```python
@cycls.app(image=image, web=web)
async def chat(context):
    async for chunk in my_llm(context.messages):
        yield chunk
```

Body is an async generator. Each `yield` streams to the frontend.

### `@cycls.agent` — managed loop

```python
@cycls.agent(image=image, web=web, llm=llm)
async def super(context):
    async for call in context:
        if call.name == "check_weather":
            call.result = await fetch_weather(call.input["city"])
        elif call.name == "query_db":
            call.result = str(await db.execute(call.input["sql"]))
```

Body is an `async for` over custom tool calls. Cycls runs the loop; only custom calls (not built-ins) reach the body. Setting `call.result` resolves the call. Unhandled calls raise.

`Call` shape:

```python
class Call:
    name: str          # tool name
    input: dict        # parsed model input
    result: str | list # user sets — sent back to model
```

Default body when no customization needed:

```python
async def super(context):
    async for _ in context: pass
```

`context` still exposes `.user`, `.session_id`, `.workspace`, `.messages` for runtime state.

---

## Extension mechanisms

**`app.server.api_route(...)`** — progressive disclosure to FastAPI. Works on `@app` and `@agent`. Used by both end users AND by `@agent` internally — one mechanism, two audiences.

```python
@cycls.app(image=image, web=web.auth(True))
async def my_app(context):
    yield "chat fallback"

# Public route
@my_app.server.api_route("/health", methods=["GET"])
async def health():
    return {"ok": True}

# Authenticated route — opt into auth via dependency
@my_app.server.api_route("/webhook", methods=["POST"])
async def webhook(request, user = Depends(my_app.auth)):
    return {"user": user.id}
```

`my_app.auth` is a FastAPI dependency wired up by `Web().auth(...)`. Routes that want auth reference it; public routes skip it. Swapping providers later (`Web().auth(cycls.WorkOS())`) doesn't change the dependency shape.

**`@agent` uses the same `.server` extension point** to mount its internal routers (sessions, files, share). It reuses `@app`'s FastAPI infrastructure — same server, same auth dependency, same context — but installs a managed loop instead of letting the user's body be the loop, and attaches the agent-specific routers via `wrapped.server.include_router(...)`. No special-case internal API; `@agent` is a consumer of the public `.server` surface just like any user route.

This is why `cycls/app/state.py` can cleanly move to `cycls/agent/state.py` — `app/web.py` stops hardcoding agent-specific routers. The agent layer mounts its own routes via the public extension point.

**`async for call in context`** — covered in the `@cycls.agent` section above. The body iterates over pending custom tool calls, sets `call.result`, and the managed loop continues.

---

## CLI

Add a CLI alongside existing `.local()` / `.deploy()` methods. Both surfaces coexist.

```bash
cycls run file.py       # → app.local()  — Docker with hot reload
cycls deploy file.py    # → app.deploy() — production
```

`cycls run` calls `.local()` under the hood — always Dockerized. The existing docker-less debug path stays as an internal helper for tests, not CLI-exposed.

File discovery: `cycls deploy` loads the file and deploys all `@cycls.app` / `@cycls.agent` / `@cycls.function` instances. `file.py::name` targets a specific one.

Entry point: `pyproject.toml` adds `[project.scripts] cycls = "cycls.cli:main"`.

---

## Full example

```python
# examples/agent/super.py
import cycls

image = cycls.Image().pip("anthropic", "httpx").apt("poppler-utils").volume("/workspace").memory("1Gi")

web = cycls.Web().auth(True).analytics(True).title("Cycls").plan("cycls_pass")

TOOLS = [
    {
        "name": "check_weather",
        "description": "Get current weather for a city.",
        "inputSchema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
]

llm = (
    cycls.LLM()
    .model("claude-sonnet-4-6")
    .system("You are Cycls.")
    .tools(*TOOLS)
    .builtin_tools("Bash", "Editor", "WebSearch")
)

@cycls.agent(image=image, web=web, llm=llm)
async def super(context):
    async for call in context:
        if call.name == "check_weather":
            import httpx
            r = await httpx.AsyncClient().get(f"https://wttr.in/{call.input['city']}?format=3")
            call.result = r.text
```

```bash
cycls run examples/agent/super.py
cycls deploy examples/agent/super.py
```

---

## Migration

**Hard break at `cycls 1.0`.** No deprecation layer. Users pin the old version or migrate.

### What gets deleted

**`cycls/function.py`** — `Function.__init__` kwargs (`pip`, `apt`, `run_commands`, `copy`) replaced by `image=`. Dockerfile generation moves to `cycls/image.py`.

**`cycls/app/main.py`** — `App.__init__` env kwargs replaced by `image=`; brand/auth/plan kwargs replaced by `web=`. Hardcoded base apt list (`bubblewrap`, `poppler-utils`, `ripgrep`, `jq`) moves into the `Image.agent()` preset. `.local()`, `.deploy()`, `._local()` kept.

**`cycls/app/state.py`** — entire file moves to `cycls/agent/state.py`. It's all agent-specific (history, sessions, files, sharing, Anthropic `cache_control` stripping).

**`cycls/app/web.py`** — hardcoded mounting of `sessions_router` / `files_router` / `share_router` rips out. Chat UI routes, `/chat/completions`, OG image endpoint, static serving move to `cycls/agent/web.py`. `@agent` mounts them internally via `.server.api_route()`.

**`cycls/app/auth.py`** — moves to `cycls/auth.py`. The Clerk constants become defaults inside `cycls.Clerk()`, alongside the new `cycls.JWT` base class.

**`cycls/app/og.py`**, **`cycls/app/themes/`** — move to `cycls/agent/`.

**`cycls/agent/main.py`** — `Agent(...)` async generator replaced by the `@cycls.agent` decorator. Loop internals (stream, retry, recovery, compaction) stay.

**`cycls/agent/tools.py`** — `dispatch` updated to route custom tool calls through the `async for call in context` channel instead of placeholder sleeps.

### What gets added

- `cycls/image.py` — `Image` fluent builder
- `cycls/web.py` — `Web` fluent builder
- `cycls/llm.py` — `LLM` fluent builder (top-level, same as Image/Web)
- `cycls/auth.py` — `Clerk` + `JWT` provider classes (moved from `cycls/app/auth.py`)
- `cycls/cli.py` — CLI entry point
- Migration guide mapping old → new line by line

### Examples and tests

All examples (`examples/agent/super.py`, `examples/app/*.py`) rewritten to the new form. Test suite updated: `agent_test.py`, `app_test.py` migrate to `image=` / `web=` / `llm=`. New primitive builder tests.

---

## Rejected alternatives

**Inline kwargs on decorators (status quo)** — kwarg passthrough, incoherent signatures, no reuse.

**Four-level hierarchy with `@api`** — `.server.api_route()` escape hatch replaces the need. Four levels is cognitive overhead.

**Function-based tools with schema introspection** — user prefers explicit JSON schemas over introspection magic.

**`@context.on("tool_name")` hook registration** — feels like ceremony vs async-for. Control flow is implicit.

**Modal's separate resource kwargs on decorators** — reintroduces passthrough via the inheritance chain.

---

## Open questions

1. **Multi-provider LLM shape** — `cycls.LLM().provider("openai").model("gpt-5")` is a likely direction, not locked.
2. **Is `Web` optional on `@app`?** Probably yes, for headless API-only apps. Deferred.
3. **`Image.agent()` preset extras** — floor is locked (`bubblewrap`, `poppler-utils`, `ripgrep`, `jq`, `.volume("/workspace")`). Additional defaults (e.g. `tesseract-ocr`) deferred to implementation.
4. **Auth providers at 1.0** — `Clerk` (default, wraps existing `app/auth.py`) + generic `JWT` base. Named wrappers for Auth0, WorkOS, Supabase, etc. added on customer demand.

---

## Status tracker

Update when work begins.

**Prerequisites** (not part of this RFC, must ship first):

- [ ] Pricing refactor
- [ ] Multi-LLM abstraction
- [ ] `@agent` proper decorator + `state.py` moved to `cycls/agent/`

**This RFC**:

- [ ] `cycls.Image` implemented (fluent builder)
- [ ] `cycls.Web` implemented
- [ ] `cycls.LLM` implemented
- [ ] `cycls.Clerk` + `cycls.JWT` auth providers
- [ ] `async for call in context` implemented
- [ ] `app.server.api_route` extension documented
- [ ] CLI (`cycls run`, `cycls deploy`) implemented
- [ ] Migration guide written
- [ ] All existing examples rewritten to new form

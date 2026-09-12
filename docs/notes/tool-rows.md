# The tool row — what a builtin declares, and why the loop reads it

Every harness tool is one row in `_TOOLS` (`cycls/_agent/tools/__init__.py`):

```python
class Tool(NamedTuple):
    """`once`: one call per batch. `terminal`: a successful call ends the turn.
    `prompt`: guidance appended while the tool is enabled."""
    run: object
    step: object
    once: bool = False
    terminal: bool = False
    prompt: str = ""
```

```python
"ask": Tool(lambda inp, ws, **_: _exec_ask(inp), _ask_step,
            once=True, terminal=True, prompt=ASK_GUIDANCE),
```

The point of the row is that **enabling a tool is the only switch**. A tool
that needs prompt copy, that must not be called twice, or that ends the turn
declares it here — the loop reads the declaration instead of naming the tool.
Adding the next one touches no other file.

## The fields

**`run(inp, workspace, *, timeout, network)`** — returns the awaitable result.
`None` for tools that execute elsewhere (`web_search` under `web_search="native"`
runs Anthropic-side; the row exists only so the UI has a label).

**`step(inp)`** — renders the `{tool_name, step}` line. Shared by the live
dispatch path and the refetch projection (`to_ui_messages`) so a reloaded chat
shows what the stream showed.

**`once`** — one call per batch. `dispatch` takes a per-batch `seen` set; a
repeat is refused *but still gets a step and a tool_result*, because every
`tool_use` must keep its pair or the next request is a 400:

```python
return ({"type": "step", "id": bid, **entry.step(inp), "ok": False},
        asyncio.sleep(0, result=(
            f"Error: `{name}` was already called this turn and only the first "
            "call ran. Send everything in a single call.")))
```

The error text is the useful half — it tells the model to batch rather than
retry, which is what `ask` (up to 3 questions) and `suggest` (exactly one
follow-up) both want.

**`terminal`** — a successful call ends the turn. Enforced by the loop, not by
asking the model nicely in a prompt. See
[ask-round-trip.md](ask-round-trip.md) for the ordering that keeps history
valid across the break.

**`prompt`** — appended to the system prompt while the tool is enabled, via
`tool_prompts(tools_list)`. Note it keys off the **built tool list**, not the
`allowed_tools` names: a tool dropped by `vendor_skips` takes its guidance with
it, and the ordering follows the tools themselves.

## Return shapes a tool may use

`run` can answer in four ways. The loop checks them in this order:

**1. A plain string** — the ordinary case. It becomes the `tool_result`.

**2. Two channels — `{"_model": str, "_ui": event}`** — for a tool that must
tell the model one thing and the client another. `web_search` uses it: the
model reads JSON, the client gets the same rows as a `sources` event.

```python
return {
    "_model": json.dumps({"query": query, "results": rows}, ensure_ascii=False),
    "_ui": {"type": "sources", "sources": rows},
}
```

`_ui` is optional. The `_model` payload is what lands on disk, which is what
makes citations survive a reload: `to_ui_messages` parses that same JSON back
into the same `sources` part the live stream sent. One format, both paths, no
prose to re-parse — the same discipline `step` follows.

**3. A UI event — `{"type": "ui", ...}` with an optional `ack`** — for a tool
whose whole effect is on the client (`canvas`, `suggest`, `ask`). The event is
forwarded; `ack` is stripped and becomes the `tool_result`, so the string the
model reads is deliberate rather than a serialized dict.

**4. A custom handler's result** — registered through `LLM.on(name, fn)`. It is
both yielded to the agent body (for rendering) and serialized into the
`tool_result` (as data).

Whatever the shape, a `tool_use` always gets exactly one `tool_result`. That
invariant is what `state.normalize()` repairs at load and what the whole
persistence layer leans on (`tests/agent/scenarios/test_load_repair.py`).

## Adding a tool

1. Write the schema dict in Anthropic shape (`type` / `name` / `description` /
   `input_schema`) and register it under a capability name in `_BUILTINS`.
2. Write `_exec_<name>` and add the `Tool` row to `_TOOLS`.
3. Set `once` / `terminal` / `prompt` if it needs them. Don't add a matching
   `if "MyTool" in allowed_tools` anywhere — that's the coupling the row exists
   to remove.
4. If it renders something new in the transcript, teach `to_ui_messages` to
   rebuild it from storage, or it vanishes on reload.

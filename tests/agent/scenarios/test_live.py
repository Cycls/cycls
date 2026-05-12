"""Live API tests — hit real Anthropic. Catches what mocks can't:
streaming event shapes, real tool roundtrips, model behavior assumptions.

Off by default. Run with: ``pytest tests/agent/scenarios/test_live.py --live``

Each test costs ~$0.01-0.10. Full suite under $0.50 per run. Skipped
automatically if ANTHROPIC_API_KEY is unset.

Assertions check shapes, not exact strings — model output is non-deterministic.
Use the cheapest model that can complete the task (haiku for text, sonnet
for tool use) to keep cost down.
"""
import asyncio
import types
from pathlib import Path

import pytest

import cycls
from cycls.app.workspace import workspace_at


# All live tests use Sonnet — the harness hardcodes
# `thinking={"type": "adaptive"}` which Haiku doesn't support
# (returns 400 "adaptive thinking is not supported on this model").
# Making thinking conditional is a separate harness fix.
SONNET = "anthropic/claude-sonnet-4-6"


def _ctx(tmp_path, prompt, *, persist=False):
    """Build a Context-shaped object the harness expects."""
    ws_root = tmp_path / "tenant"
    ws_root.mkdir(exist_ok=True)
    ctx = types.SimpleNamespace()
    ctx.workspace = workspace_at(ws_root.name, ws_root.parent,
                                 base=f"file://{ws_root.parent}")
    ctx.chat_id = "live-test" if persist else None
    ctx.user = types.SimpleNamespace() if persist else None
    ctx.messages = types.SimpleNamespace(raw=[{"role": "user", "content": prompt}])
    return ws_root, ctx


async def _collect(llm, ctx):
    from cycls.agent.harness.events import to_ui
    out = []
    async for ev in llm.run(context=ctx):
        out.append(to_ui(ev))
    return out


def _text_of(events):
    return "".join(e for e in events if isinstance(e, str))


def _steps(events):
    return [e for e in events if isinstance(e, dict) and e.get("type") == "step"]


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_streaming_text_arrives(tmp_path):
    """Cheapest live test: a one-token answer. Pins that text deltas
    flow through the provider stream into the public event stream."""
    _, ctx = _ctx(tmp_path, "What is 2+2? Answer with one digit, nothing else.")
    llm = cycls.LLM().model(SONNET).max_tokens(20)
    events = asyncio.run(_collect(llm, ctx))
    text = _text_of(events).strip()
    assert text, f"no text events: {events!r}"
    assert "4" in text, f"expected '4' in output, got: {text!r}"


# ---------------------------------------------------------------------------
# Tool dispatch — real bwrap + model-sees-output roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_bash_tool_real_roundtrip(tmp_path):
    """Model uses bash to inspect a workspace file, sees real output,
    and reports back. Pins the entire dispatch path: tool schema sent
    to Claude, tool_use parsed, _exec_bash runs in real bwrap, output
    flows back as tool_result, model produces final response."""
    ws_root, ctx = _ctx(tmp_path,
        "Run `cat /workspace/marker.txt` and tell me exactly what it contains. "
        "Only quote the file content, no commentary.")
    (ws_root / "marker.txt").write_text("blue penguin")

    llm = cycls.LLM().model(SONNET).allowed_tools(["Bash"]).max_tokens(500)
    events = asyncio.run(_collect(llm, ctx))

    # Model used bash
    assert any(s.get("tool_name") == "Bash" for s in _steps(events)), \
        f"model didn't use bash; steps: {_steps(events)!r}"

    # Final response includes the file content
    text = _text_of(events).lower()
    assert "blue penguin" in text, f"expected 'blue penguin' in: {text!r}"


@pytest.mark.live
def test_editor_real_create_then_read(tmp_path):
    """Model creates a file via the editor tool, then reads it back.
    Pins create + read invariants for str_replace_based_edit_tool style
    blocks plus our own _resolve_path workspace guard."""
    ws_root, ctx = _ctx(tmp_path,
        "Create a file named greeting.txt in the workspace with the exact "
        "content 'hello cycls', then read it back. Confirm what you read.")

    llm = cycls.LLM().model(SONNET).allowed_tools(["Editor"]).max_tokens(800)
    events = asyncio.run(_collect(llm, ctx))

    # Used both editor sub-tools (or at least one — the model might just
    # write+confirm without re-reading)
    steps = _steps(events)
    assert any(s.get("tool_name") in ("Editing", "Reading") for s in steps), \
        f"model didn't use editor tools; steps: {steps!r}"

    # File on disk has the right content
    assert (ws_root / "greeting.txt").exists(), "file was not created"
    assert (ws_root / "greeting.txt").read_text() == "hello cycls"

    # Final response confirms it
    text = _text_of(events).lower()
    assert "hello cycls" in text


# ---------------------------------------------------------------------------
# Persistence + repair end-to-end with real model
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_persisted_chat_loads_clean_after_real_turn(tmp_path):
    """One real turn against Anthropic with chat_id set; verify the
    persisted history is _valid_prefix-clean (no orphans). This is
    the ultimate end-to-end pin: real model + real persistence +
    load-time repair invariants all converge."""
    from cycls.agent import sessions as chat

    _, ctx = _ctx(tmp_path, "Say 'ack' and stop.", persist=True)
    llm = cycls.LLM().model(SONNET).max_tokens(50)
    asyncio.run(_collect(llm, ctx))

    # Reload — repair should be a no-op on this clean turn
    msgs = asyncio.run(chat.load_messages(ctx.workspace, ctx.chat_id))
    assert len(msgs) >= 2  # user + assistant minimum
    assert msgs[0]["role"] == "user"
    assert msgs[-1]["role"] == "assistant"

    # Reload again — disk should be stable (idempotent)
    msgs2 = asyncio.run(chat.load_messages(ctx.workspace, ctx.chat_id))
    assert msgs2 == msgs


# ---------------------------------------------------------------------------
# Stress — failure paths against the real model
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_bash_failure_real_recovery(tmp_path):
    """Model uses bash on a missing file → tool returns error → model sees
    it and reports back. Pins the dispatch error path under real conditions:
    _exec_bash returning a non-zero/error string is digested by the model."""
    _, ctx = _ctx(tmp_path,
        "Run `cat /tmp/definitely-not-a-real-file.xyz` and tell me whether "
        "it succeeded. Answer with just 'failed' or 'succeeded'.")
    llm = cycls.LLM().model(SONNET).allowed_tools(["Bash"]).max_tokens(300)
    events = asyncio.run(_collect(llm, ctx))

    assert any(s.get("tool_name") == "Bash" for s in _steps(events))
    text = _text_of(events).lower()
    assert "fail" in text, f"model didn't recognize failure: {text!r}"


@pytest.mark.live
def test_multiturn_tool_chain_real(tmp_path):
    """Two-tool sequential workflow in one _run: create → read.
    Pins multi-turn dispatch + persist-per-turn boundaries with real model.
    Each turn should land cleanly on disk."""
    from cycls.agent import sessions as chat

    ws_root, ctx = _ctx(tmp_path,
        "Use the editor to create a file `data.txt` with the exact content "
        "`42`, then read it back. Tell me the content you read.",
        persist=True)
    llm = cycls.LLM().model(SONNET).allowed_tools(["Editor"]).max_tokens(800)
    events = asyncio.run(_collect(llm, ctx))

    text = _text_of(events)
    assert "42" in text, f"model didn't report content: {text!r}"
    assert (ws_root / "data.txt").exists()
    assert (ws_root / "data.txt").read_text() == "42"

    # Multi-turn persistence: load should return ALL turns clean.
    msgs = asyncio.run(chat.load_messages(ctx.workspace, ctx.chat_id))
    # Expect: user, assistant(tool_use create), user(tool_result), assistant(tool_use read), user(tool_result), assistant(final text)
    assert len(msgs) >= 4, f"multi-turn persistence dropped messages: {len(msgs)}"
    # Last must be assistant — clean turn boundary
    assert msgs[-1]["role"] == "assistant"


@pytest.mark.live
def test_max_tokens_recovery_chain_real(tmp_path):
    """Force the model to hit max_tokens with a long output ask + tight
    cap, verify the harness's synthetic recovery message fires (`Output
    limit hit, continuing...`) and the loop continues into another turn."""
    _, ctx = _ctx(tmp_path,
        "Count from 1 to 200. List each number on its own line, no skipping. "
        "Continue exactly where you left off if interrupted.")
    llm = cycls.LLM().model(SONNET).max_tokens(80)  # ~150 tokens worth of digits
    events = asyncio.run(_collect(llm, ctx))

    recovery_steps = [s for s in _steps(events)
                      if "Output limit" in s.get("step", "")]
    assert recovery_steps, (
        f"max_tokens recovery never fired; "
        f"got {len(_steps(events))} steps: {_steps(events)!r}"
    )


@pytest.mark.live
def test_long_bash_output_truncation_real(tmp_path):
    """Bash output > MAX_OUTPUT (30K chars) — _exec_bash truncates with
    `(truncated)` marker. Pins that truncation works under real model
    conditions and the model sees the marker without errors propagating."""
    _, ctx = _ctx(tmp_path,
        "Run `seq 1 20000` and tell me whether the output was truncated. "
        "Look for the word 'truncated' in the output. "
        "Answer with just 'truncated' or 'complete'.")
    llm = cycls.LLM().model(SONNET).allowed_tools(["Bash"]).max_tokens(500)
    events = asyncio.run(_collect(llm, ctx))

    assert any(s.get("tool_name") == "Bash" for s in _steps(events))
    text = _text_of(events).lower()
    assert "truncat" in text, f"model didn't see truncation marker: {text!r}"

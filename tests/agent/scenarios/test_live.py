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


SONNET = "anthropic/claude-sonnet-4-6"
HAIKU = "anthropic/claude-haiku-4-5-20251001"
OPENAI = "openai/gpt-4o-mini"


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
def test_openai_basic_real(tmp_path):
    """OpenAI is a first-class provider: basic chat + a real tool call work
    end-to-end. Pins the OpenAIProvider's stream/translation path against the
    real Chat Completions API."""
    ws_root, ctx = _ctx(tmp_path,
        "Run `cat /workspace/marker.txt` via bash and tell me exactly what it contains. "
        "Only quote the file content, no commentary.")
    (ws_root / "marker.txt").write_text("orange octopus")

    llm = cycls.LLM().model(OPENAI).allowed_tools(["Bash"]).max_tokens(500)
    events = asyncio.run(_collect(llm, ctx))

    assert any(s.get("tool_name") == "Bash" for s in _steps(events)), \
        f"OpenAI didn't use bash; steps: {_steps(events)!r}"
    text = _text_of(events).lower()
    assert "orange octopus" in text, f"expected 'orange octopus' in: {text!r}"


@pytest.mark.live
def test_openai_websearch_skipped_with_warning(tmp_path):
    """`WebSearch` is Anthropic-only. On OpenAI, the loop emits a Callout
    warning before the turn and the tool isn't registered with the model."""
    _, ctx = _ctx(tmp_path, "say hi in one word")
    llm = cycls.LLM().model(OPENAI).allowed_tools(["WebSearch"]).max_tokens(20)
    events = asyncio.run(_collect(llm, ctx))

    callouts = [c for c in events if isinstance(c, dict) and c.get("type") == "callout"]
    assert any("WebSearch" in c.get("callout", "") and "Anthropic-only" in c.get("callout", "")
               for c in callouts), f"expected WebSearch skip callout; got {callouts!r}"
    # And the model still produced a normal response.
    assert _text_of(events).strip(), f"no text from OpenAI; events={events!r}"


@pytest.mark.live
def test_haiku_works_without_adaptive_thinking(tmp_path):
    """Haiku doesn't support `thinking={"type":"adaptive"}` — the provider
    auto-disables it on `haiku` model names. Verifies that holds against the
    real API (Haiku used to 400 here with the hardcoded adaptive)."""
    _, ctx = _ctx(tmp_path, "say hi in one word")
    llm = cycls.LLM().model(HAIKU).max_tokens(20)
    events = asyncio.run(_collect(llm, ctx))
    assert _text_of(events).strip(), f"no text from Haiku; events={events!r}"


@pytest.mark.live
def test_max_tokens_stops_cleanly_real(tmp_path):
    """When the model hits max_tokens, the loop ends the turn with a
    `Stopped: max_tokens` callout — no auto-retry (pi-style). Partial output is
    preserved in the stream; the user re-sends to continue if they want."""
    _, ctx = _ctx(tmp_path,
        "Count from 1 to 200. List each number on its own line, no skipping.")
    llm = cycls.LLM().model(SONNET).max_tokens(80)  # ~150 tokens worth of digits
    events = asyncio.run(_collect(llm, ctx))

    callouts = [c for c in events if isinstance(c, dict) and c.get("type") == "callout"]
    assert any("max_tokens" in c.get("callout", "") for c in callouts), \
        f"expected `Stopped: max_tokens` callout; got callouts={callouts!r}"
    # Partial output was preserved in the stream (the digits the model managed to emit).
    assert _text_of(events).strip(), f"no partial text preserved; events={events!r}"


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


@pytest.mark.live
def test_compaction_real_roundtrip(tmp_path):
    """Force compaction by shrinking the buffers, then verify the loop
    summarizes real prior content and continues to produce a response.
    Exercises `provider.complete`, the `<summary>` regex, replace_messages, the
    `internal` flag, and the post-compact turn — none of which the mocked tests
    actually run end-to-end."""
    from unittest.mock import patch
    from cycls.agent import sessions

    _, ctx = _ctx(tmp_path, "what's 2+2? one word.", persist=True)

    # Pre-populate text-only history (no tool calls — keeps Anthropic's
    # tool_use/tool_result pairing rules out of the picture for this scenario).
    prior = [
        {"role": "user", "content": "your name?"},
        {"role": "assistant", "content": [{"type": "text", "text": "Cycls."}]},
        {"role": "user", "content": "capital of france?"},
        {"role": "assistant", "content": [{"type": "text", "text": "Paris."}]},
        {"role": "user", "content": "of germany?"},
        {"role": "assistant", "content": [{"type": "text", "text": "Berlin."}]},
    ]
    asyncio.run(sessions.append_messages(ctx.workspace, ctx.chat_id, prior, 0))

    llm = cycls.LLM().model(SONNET)

    # COMPACT_BUFFER huge ⇒ threshold negative ⇒ compaction fires immediately.
    # main.KEEP_RECENT=1 ⇒ the `len(messages) > KEEP_RECENT` guard passes.
    # compact.KEEP_RECENT=1 ⇒ recent = the just-added user msg, so the
    # post-compact list `[summary_user, understood_assistant, new_user]` stays
    # role-alternating (Anthropic rejects two consecutive assistants).
    with patch("cycls.agent.harness.main.COMPACT_BUFFER", 999_999_999), \
         patch("cycls.agent.harness.main.KEEP_RECENT", 1), \
         patch("cycls.agent.harness.compact.KEEP_RECENT", 1):
        events = asyncio.run(_collect(llm, ctx))

    assert any(isinstance(e, dict) and e.get("step") == "Compacting context..." for e in events), \
        f"expected Compacting step; got {events!r}"

    # History rewritten to the internal summary pair + the post-compact turn.
    msgs = asyncio.run(sessions.load_messages(ctx.workspace, ctx.chat_id))
    assert msgs[0]["role"] == "user" and msgs[0].get("internal") is True
    assert msgs[0]["content"].startswith("This session continues from a previous conversation.")
    assert msgs[1]["role"] == "assistant" and msgs[1].get("internal") is True
    # Real response came back.
    assert _text_of(events).strip(), f"no post-compact text; events={events!r}"

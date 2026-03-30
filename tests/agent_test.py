"""Tests for the Agent loop in cycls/agent.py.

Mocks litellm.acompletion to test streaming, incremental history saving,
and crash recovery without hitting a real LLM.
"""
import asyncio
import json
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cycls.agent import Agent, COMPACT_THRESHOLD, MAX_ATTACHMENTS, MAX_RETRIES, _exec_bash, _exec_editor, _is_retryable, _prepare_prompt, _prepare_tool, _sniff_media_type
from cycls.app.state import load_history


# ---------------------------------------------------------------------------
# Helpers — build OpenAI-format mock objects for litellm streaming
# ---------------------------------------------------------------------------

def _make_context(ws, hp):
    ctx = types.SimpleNamespace()
    ctx.workspace = ws
    ctx.session_id = "test-session"
    user = types.SimpleNamespace()
    user.sessions = Path(hp).parent
    ctx.user = user
    ctx.messages = types.SimpleNamespace()
    ctx.messages.raw = [{"role": "user", "content": "do stuff"}]
    return ctx


def _make_delta(content=None, tool_calls=None, reasoning_content=None):
    """Build an OpenAI-format delta object."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls
    delta.reasoning_content = reasoning_content
    return delta


def _make_tool_call_delta(index, tc_id=None, name=None, arguments=None):
    """Build a streaming tool_call chunk."""
    tc = MagicMock()
    tc.index = index
    tc.id = tc_id
    func = MagicMock()
    func.name = name
    func.arguments = arguments
    tc.function = func
    return tc


def _make_chunk(delta, finish_reason=None, usage=None):
    """Build an OpenAI-format streaming chunk."""
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


def _make_usage_chunk(prompt_tokens=500, completion_tokens=100):
    """Build a usage-only chunk (no choices)."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.prompt_tokens_details = None
    chunk = MagicMock()
    chunk.choices = []
    chunk.usage = usage
    return chunk


def _text_chunks(text="Done!"):
    """Return chunks for a simple text response."""
    return [
        _make_chunk(_make_delta(content=text)),
        _make_chunk(_make_delta(), finish_reason="stop"),
        _make_usage_chunk(),
    ]


def _tool_use_chunks(tool_id, name="bash", arguments='{"command": "echo hi"}'):
    """Return chunks for a tool_use response."""
    tc_start = _make_tool_call_delta(index=0, tc_id=tool_id, name=name, arguments=None)
    tc_args = _make_tool_call_delta(index=0, tc_id=None, name=None, arguments=arguments)
    return [
        _make_chunk(_make_delta(tool_calls=[tc_start])),
        _make_chunk(_make_delta(tool_calls=[tc_args])),
        _make_chunk(_make_delta(), finish_reason="tool_calls"),
        _make_usage_chunk(),
    ]


class FakeAsyncIter:
    """Wraps a list of chunks into an async iterator."""
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _mock_litellm_responses(*responses):
    """Create a mock for litellm.acompletion that returns sequences of chunk lists."""
    responses = list(responses)
    call_count = 0

    async def fake_acompletion(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > len(responses):
            raise Exception("Unexpected extra call to litellm.acompletion")
        chunk_list = responses[call_count - 1]
        if isinstance(chunk_list, Exception):
            raise chunk_list
        return FakeAsyncIter(list(chunk_list))

    return fake_acompletion, lambda: call_count


async def _drain(gen):
    items = []
    async for item in gen:
        items.append(item)
    return items


def _history_tool_ids(history):
    """Extract (tool_use_ids, tool_result_ids) from a history list (OpenAI format)."""
    use_ids, result_ids = [], []
    for msg in history:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                use_ids.append(tc["id"])
        elif msg.get("role") == "tool":
            result_ids.append(msg["tool_call_id"])
    return use_ids, result_ids


@pytest.fixture
def agent_env(tmp_path):
    """Create workspace + session dir + context for agent tests."""
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()
    hp_dir = tmp_path / "sessions"
    hp_dir.mkdir()
    hp = str(hp_dir / "test-session.history.jsonl")
    return ws, hp, _make_context(ws, hp)


# ---------------------------------------------------------------------------
# Incremental save tests
# ---------------------------------------------------------------------------

def test_history_saved_after_each_tool_round(agent_env):
    """Two tool rounds then final text — all messages should be on disk."""
    ws, hp, ctx = agent_env

    round1 = _tool_use_chunks("t1")
    round2 = _tool_use_chunks("t2")
    final = _text_chunks("All done")

    fake_acompletion, _ = _mock_litellm_responses(round1, round2, final)

    with patch("litellm.acompletion", side_effect=fake_acompletion), \
         patch("cycls.agent._exec_bash", new_callable=lambda: AsyncMock(return_value="ok")):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant", "tool", "assistant", "tool", "assistant"]


def test_history_survives_crash_after_first_tool_round(agent_env):
    """Crash during round 2 streaming — round 1 history should already be on disk."""
    ws, hp, ctx = agent_env

    round1 = _tool_use_chunks("t1")

    # After recovery from ConnectionError, the loop retries and gets a final response
    final = _text_chunks("Recovered after disconnect")
    fake_acompletion, _ = _mock_litellm_responses(round1, ConnectionError("Lost connection to API"), final)

    with patch("litellm.acompletion", side_effect=fake_acompletion), \
         patch("cycls.agent._exec_bash", new_callable=lambda: AsyncMock(return_value="ok")):
        items = asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    # Recovery handled the error — no error callout shown
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert not callouts

    # Round 1 messages survived on disk
    history = load_history(hp)
    assert len(history) >= 3  # user + assistant(tool_calls) + tool(result)
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[2]["role"] == "tool"


def test_error_recovery_saves_incrementally(agent_env):
    """When tool execution raises, the except handler patches error tool_results.
    Those should be saved incrementally."""
    ws, hp, ctx = agent_env

    # Round 1: editor tool with missing "command" key → raises KeyError
    round1 = _tool_use_chunks("t1", name="str_replace_based_edit_tool", arguments="{}")
    final = _text_chunks("Recovered")

    fake_acompletion, _ = _mock_litellm_responses(round1, final)

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    assert len(history) >= 3
    # The error recovery tool message should be on disk
    error_results = [m for m in history if m.get("role") == "tool"
                     and "Error:" in str(m.get("content", ""))]
    assert len(error_results) >= 1


def test_no_history_without_session(tmp_path):
    """No session_id → nothing saved to disk."""
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()

    ctx = types.SimpleNamespace()
    ctx.workspace = ws
    ctx.session_id = None
    ctx.user = None
    ctx.messages = types.SimpleNamespace()
    ctx.messages.raw = [{"role": "user", "content": "hi"}]

    final = _text_chunks("Hello!")
    fake_acompletion, _ = _mock_litellm_responses(final)

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    assert not list(tmp_path.glob("**/*.jsonl"))


# ---------------------------------------------------------------------------
# Media type sniffing tests
# ---------------------------------------------------------------------------

_JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 20
_PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
_GIF_HEADER = b"GIF89a" + b"\x00" * 20
_WEBP_HEADER = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20
_PDF_HEADER = b"%PDF-1.4" + b"\x00" * 20


def test_sniff_media_type_detects_all_formats():
    assert _sniff_media_type(_JPEG_HEADER) == "image/jpeg"
    assert _sniff_media_type(_PNG_HEADER) == "image/png"
    assert _sniff_media_type(_GIF_HEADER) == "image/gif"
    assert _sniff_media_type(_WEBP_HEADER) == "image/webp"
    assert _sniff_media_type(_PDF_HEADER) == "application/pdf"
    assert _sniff_media_type(b"unknown data") is None


def test_exec_editor_view_uses_content_sniffing_over_extension(tmp_path):
    """A .png file containing JPEG data should return media_type image/jpeg."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "fake.png").write_bytes(_JPEG_HEADER)

    result = _exec_editor({"command": "view", "path": "fake.png"}, str(ws))

    assert isinstance(result, list)
    assert result[0]["type"] == "image"
    assert result[0]["source"]["media_type"] == "image/jpeg"


def test_exec_editor_view_correct_extension_unchanged(tmp_path):
    """A .png file with actual PNG content should stay image/png."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "real.png").write_bytes(_PNG_HEADER)

    result = _exec_editor({"command": "view", "path": "real.png"}, str(ws))

    assert result[0]["source"]["media_type"] == "image/png"


# ---------------------------------------------------------------------------
# Tool history corruption tests
# ---------------------------------------------------------------------------

def test_tool_result_always_follows_tool_use_on_crash(agent_env):
    """Every tool_use id in history must have a matching tool_result,
    even when tool execution crashes mid-way."""
    ws, hp, ctx = agent_env

    round1 = _tool_use_chunks("crash-1", name="str_replace_based_edit_tool", arguments="{}")
    final = _text_chunks("Recovered")
    fake_acompletion, _ = _mock_litellm_responses(round1, final)

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    use_ids, result_ids = _history_tool_ids(history)
    assert use_ids == result_ids


def test_tool_result_present_after_bash_timeout(agent_env):
    """Simulates a bash timeout. The tool_result with the timeout error
    must be saved so follow-up messages don't trigger 400 errors."""
    ws, hp, ctx = agent_env

    round1 = _tool_use_chunks("timeout-1", name="bash",
                               arguments='{"command": "pip install heavy-package"}')
    final = _text_chunks("Sorry about the timeout")
    fake_acompletion, _ = _mock_litellm_responses(round1, final)

    with patch("litellm.acompletion", side_effect=fake_acompletion), \
         patch("cycls.agent._exec_bash",
               new_callable=lambda: AsyncMock(return_value="Error: Command timed out after 300s")):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    use_ids, result_ids = _history_tool_ids(history)
    assert use_ids == result_ids
    # Verify the timeout error made it into the correct tool message
    timeout_msgs = [m for m in history if m.get("role") == "tool"
                    and m.get("tool_call_id") == "timeout-1"]
    assert len(timeout_msgs) == 1, "Expected exactly one tool result for timeout-1"
    assert "timed out" in timeout_msgs[0]["content"]


def test_multiple_tool_calls_all_get_results(agent_env):
    """When the LLM issues multiple parallel tool calls and one fails,
    ALL tool_use ids must still have matching tool_results."""
    ws, hp, ctx = agent_env

    # Build chunks with two parallel tool calls
    tc1_start = _make_tool_call_delta(index=0, tc_id="ok-1", name="bash", arguments=None)
    tc2_start = _make_tool_call_delta(index=1, tc_id="fail-1", name="bash", arguments=None)
    tc1_args = _make_tool_call_delta(index=0, tc_id=None, name=None, arguments='{"command": "echo ok"}')
    tc2_args = _make_tool_call_delta(index=1, tc_id=None, name=None, arguments='{"command": "pip install heavy"}')
    round1 = [
        _make_chunk(_make_delta(tool_calls=[tc1_start, tc2_start])),
        _make_chunk(_make_delta(tool_calls=[tc1_args, tc2_args])),
        _make_chunk(_make_delta(), finish_reason="tool_calls"),
        _make_usage_chunk(),
    ]
    final = _text_chunks("Done")
    fake_acompletion, _ = _mock_litellm_responses(round1, final)

    async def mock_bash(cmd, cwd, **kw):
        if "heavy" in cmd:
            return "Error: Command timed out after 300s"
        return "ok"

    with patch("litellm.acompletion", side_effect=fake_acompletion), \
         patch("cycls.agent._exec_bash", side_effect=mock_bash):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    use_ids, result_ids = _history_tool_ids(history)
    assert sorted(use_ids) == sorted(result_ids)


# ---------------------------------------------------------------------------
# Bash timeout tests (_exec_bash directly, no LLM mock needed)
# ---------------------------------------------------------------------------

def test_exec_bash_returns_error_on_timeout(tmp_path):
    """_exec_bash must return a timeout error string when the process hangs."""
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    async def run():
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            return await _exec_bash("sleep 60", ws, timeout=5)

    result = asyncio.run(run())

    assert "timed out" in result
    assert "5s" in result
    mock_proc.kill.assert_called_once()
    mock_proc.wait.assert_awaited_once()


# ---------------------------------------------------------------------------
# API error recovery tests (e.g. oversized PDF in tool_results → 400)
# ---------------------------------------------------------------------------

def test_api_400_from_tool_result_lets_llm_recover(agent_env):
    """When the API rejects tool_results (e.g. oversized PDF), the agent loop
    should recover and let the LLM respond, not show a raw error."""
    ws, hp, ctx = agent_env

    # Round 1: LLM asks to view a file
    round1 = _tool_use_chunks("v1", name="str_replace_based_edit_tool",
                               arguments='{"command": "view", "path": "big.pdf"}')
    # Round 2: API rejects because tool_result has oversized content
    api_error = Exception("messages.1.content.0.tool_result: content too large")
    # Round 3 (after recovery): LLM responds with helpful text
    final = _text_chunks("The PDF is too large. Let me extract specific pages.")

    fake_acompletion, _ = _mock_litellm_responses(round1, api_error, final)

    # Create a fake PDF file so _exec_editor can view it
    (Path(ws) / "big.pdf").write_bytes(_PDF_HEADER)

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        items = asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    # Recovery = no error callout shown to user
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert not callouts, f"Raw error shown instead of recovering: {callouts}"

    # LLM got a third call (recovery round) and produced a final assistant message
    history = load_history(hp)
    assert history[-1]["role"] == "assistant"

    # Tool result content was replaced with error string (not raw PDF data)
    tool_msgs = [m for m in history if m.get("role") == "tool"]
    for msg in tool_msgs:
        assert isinstance(msg["content"], str), "Tool result content should be error string, not raw PDF"

    # All tool_use ids still have matching results
    use_ids, result_ids = _history_tool_ids(history)
    assert use_ids == result_ids


# ---------------------------------------------------------------------------
# File attachment limit tests
# ---------------------------------------------------------------------------

def test_prepare_prompt_under_limit(tmp_path):
    """Attachments under MAX_ATTACHMENTS all appear in prompt."""
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()
    parts = [{"type": "text", "text": "check these"}]
    parts += [{"type": "file", "file": f"doc{i}.pdf"} for i in range(MAX_ATTACHMENTS)]
    ctx = types.SimpleNamespace()
    ctx.workspace = ws
    ctx.messages = types.SimpleNamespace()
    ctx.messages.raw = [{"role": "user", "content": parts}]

    prompt = _prepare_prompt(ctx)
    for i in range(MAX_ATTACHMENTS):
        assert f"doc{i}.pdf" in prompt
    assert "not loaded" not in prompt


def test_prepare_prompt_over_limit(tmp_path):
    """Attachments over MAX_ATTACHMENTS are excluded and noted as on-disk."""
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()
    n = MAX_ATTACHMENTS + 5
    parts = [{"type": "text", "text": "check these"}]
    parts += [{"type": "image", "image": f"img{i}.png"} for i in range(n)]
    ctx = types.SimpleNamespace()
    ctx.workspace = ws
    ctx.messages = types.SimpleNamespace()
    ctx.messages.raw = [{"role": "user", "content": parts}]

    prompt = _prepare_prompt(ctx)
    for i in range(MAX_ATTACHMENTS):
        assert f"img{i}.png" in prompt
    for i in range(MAX_ATTACHMENTS, n):
        assert f"img{i}.png" in prompt
    assert "not loaded" in prompt
    assert "text editor view" in prompt


# ---------------------------------------------------------------------------
# Context compaction tests
# ---------------------------------------------------------------------------

def test_compaction_triggers_above_threshold(agent_env):
    """When input tokens exceed COMPACT_THRESHOLD, history is rewritten with summary."""
    ws, hp, ctx = agent_env

    # Final chunk with usage above threshold
    final_chunks = [
        _make_chunk(_make_delta(content="Done")),
        _make_chunk(_make_delta(), finish_reason="stop"),
        _make_usage_chunk(prompt_tokens=COMPACT_THRESHOLD + 1, completion_tokens=100),
    ]

    fake_acompletion, _ = _mock_litellm_responses(final_chunks)

    # Mock _compact to return a known summary
    summary_messages = [
        {"role": "user", "content": "Summary of previous work."},
        {"role": "assistant", "content": "Understood."},
    ]

    with patch("litellm.acompletion", side_effect=fake_acompletion), \
         patch("cycls.agent._compact", new_callable=lambda: AsyncMock(return_value=summary_messages)):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    assert len(history) == 2
    assert history[0]["content"] == "Summary of previous work."
    assert history[1]["content"] == "Understood."


def test_no_compaction_below_threshold(agent_env):
    """When input tokens are under COMPACT_THRESHOLD, history is appended normally."""
    ws, hp, ctx = agent_env

    final_chunks = [
        _make_chunk(_make_delta(content="Done")),
        _make_chunk(_make_delta(), finish_reason="stop"),
        _make_usage_chunk(prompt_tokens=COMPACT_THRESHOLD - 1, completion_tokens=100),
    ]

    fake_acompletion, _ = _mock_litellm_responses(final_chunks)

    with patch("litellm.acompletion", side_effect=fake_acompletion):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"]


def test_compaction_failure_still_saves_history(agent_env):
    """If _compact raises, the final assistant message must still be saved."""
    ws, hp, ctx = agent_env

    final_chunks = [
        _make_chunk(_make_delta(content="Important answer")),
        _make_chunk(_make_delta(), finish_reason="stop"),
        _make_usage_chunk(prompt_tokens=COMPACT_THRESHOLD + 1, completion_tokens=100),
    ]

    fake_acompletion, _ = _mock_litellm_responses(final_chunks)

    with patch("litellm.acompletion", side_effect=fake_acompletion), \
         patch("cycls.agent._compact", new_callable=lambda: AsyncMock(side_effect=Exception("API down"))):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"]
    # The actual answer must not be lost
    last = history[-1]["content"]
    text = last[0]["text"] if isinstance(last, list) else last
    assert "Important answer" in text


# ---------------------------------------------------------------------------
# Editor path traversal tests
# ---------------------------------------------------------------------------

def test_exec_editor_blocks_path_traversal(tmp_path):
    """Paths escaping the workspace must be rejected."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "legit.txt").write_text("ok")

    result = _exec_editor({"command": "view", "path": "../../etc/passwd"}, str(ws))
    assert "Error" in result

    result = _exec_editor({"command": "view", "path": "/etc/passwd"}, str(ws))
    assert "Error" in result


def test_exec_editor_allows_valid_paths(tmp_path):
    """Normal relative paths within workspace must work."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.txt").write_text("world")

    result = _exec_editor({"command": "view", "path": "hello.txt"}, str(ws))
    assert "world" in result


# ---------------------------------------------------------------------------
# Bash output truncation tests
# ---------------------------------------------------------------------------

def test_exec_bash_truncates_large_output(tmp_path):
    """Output exceeding 20K chars must be truncated with marker."""
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()

    big_output = ("x" * 30000).encode()
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(big_output, b""))
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    async def run():
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            return await _exec_bash("echo big", ws)

    result = asyncio.run(run())
    assert len(result) < 25000
    assert "truncated" in result


# ---------------------------------------------------------------------------
# Auto-retry tests
# ---------------------------------------------------------------------------

def test_is_retryable_detects_transient_errors():
    assert _is_retryable(Exception("overloaded"))
    assert _is_retryable(Exception("rate limit exceeded"))
    assert _is_retryable(Exception("429 Too Many Requests"))
    assert _is_retryable(Exception("502 Bad Gateway"))
    assert not _is_retryable(Exception("invalid api key"))
    assert not _is_retryable(Exception("context too long"))


def test_auto_retry_on_overloaded(agent_env):
    """Transient API errors should be retried, not shown as errors."""
    ws, hp, ctx = agent_env

    final = _text_chunks("Done")
    overloaded = Exception("overloaded")

    fake_acompletion, get_count = _mock_litellm_responses(overloaded, overloaded, final)

    with patch("litellm.acompletion", side_effect=fake_acompletion), \
         patch("asyncio.sleep", new_callable=lambda: AsyncMock(return_value=None)):
        items = asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    # No error callouts — retries handled it
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert not callouts
    # Should have retried and succeeded
    assert get_count() == 3


def test_auto_retry_exhausted_shows_error(agent_env):
    """After MAX_RETRIES, the error should surface to the user."""
    ws, hp, ctx = agent_env

    errors = [Exception("overloaded")] * (MAX_RETRIES + 2)
    fake_acompletion, _ = _mock_litellm_responses(*errors)

    with patch("litellm.acompletion", side_effect=fake_acompletion), \
         patch("asyncio.sleep", new_callable=lambda: AsyncMock(return_value=None)):
        items = asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert len(callouts) == 1
    assert "overloaded" in callouts[0]["callout"]

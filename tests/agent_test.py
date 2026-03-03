"""Tests for the Agent loop in cycls/agent.py.

Mocks the Anthropic streaming API to test incremental history saving
and crash recovery without hitting a real LLM.
"""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cycls.agent import Agent, COMPACT_THRESHOLD, MAX_ATTACHMENTS, MAX_RETRIES, _exec_bash, _exec_editor, _is_retryable, _prepare_prompt, _prepare_tool, _sniff_media_type
from cycls.app.state import load_history


# ---------------------------------------------------------------------------
# Helpers
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


def _tool_use_block(tool_id, name="bash", inp=None):
    b = MagicMock()
    b.type = "tool_use"
    b.name = name
    b.id = tool_id
    b.input = inp or {"command": "echo hi"}
    b.model_dump.return_value = {
        "type": "tool_use", "id": tool_id, "name": name, "input": b.input,
    }
    return b


def _text_block(text="Done!"):
    b = MagicMock()
    b.type = "text"
    b.text = text
    b.model_dump.return_value = {"type": "text", "text": text}
    return b


def _usage(inp=500, out=100):
    u = MagicMock()
    u.input_tokens = inp
    u.output_tokens = out
    u.cache_read_input_tokens = 0
    u.cache_creation_input_tokens = 0
    return u


def _make_response(content_blocks, stop_reason="end_turn", usage=None):
    resp = MagicMock()
    resp.content = content_blocks
    resp.stop_reason = stop_reason
    resp.usage = usage or _usage()
    return resp


class FakeStream:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def __aiter__(self):
        return
        yield

    async def get_final_message(self):
        return self._response


async def _drain(gen):
    items = []
    async for item in gen:
        items.append(item)
    return items


def _mock_anthropic(client):
    """Insert a fake anthropic module into sys.modules that returns *client*."""
    mod = types.ModuleType("anthropic")
    mod.AsyncAnthropic = lambda: client
    return patch.dict(sys.modules, {"anthropic": mod})


def _history_tool_ids(history):
    """Extract (tool_use_ids, tool_result_ids) from a history list."""
    use_ids, result_ids = [], []
    for msg in history:
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                use_ids.append(block["id"])
            elif block.get("type") == "tool_result":
                result_ids.append(block["tool_use_id"])
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
    """Two tool rounds then final text — all six messages should be on disk."""
    ws, hp, ctx = agent_env

    round1 = _make_response([_tool_use_block("t1")], stop_reason="tool_use")
    round2 = _make_response([_tool_use_block("t2")], stop_reason="tool_use")
    final = _make_response([_text_block("All done")])
    responses = iter([round1, round2, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    with _mock_anthropic(mock_client), \
         patch("cycls.agent._exec_bash", new_callable=lambda: AsyncMock(return_value="ok")):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]


def test_history_survives_crash_after_first_tool_round(agent_env):
    """Crash during round 2 streaming — round 1 history should already be on disk."""
    ws, hp, ctx = agent_env

    round1 = _make_response([_tool_use_block("t1")], stop_reason="tool_use")
    call_count = 0

    def stream_side_effect(**kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeStream(round1)
        raise ConnectionError("Lost connection to API")

    mock_client = MagicMock()
    mock_client.messages.stream = stream_side_effect

    with _mock_anthropic(mock_client), \
         patch("cycls.agent._exec_bash", new_callable=lambda: AsyncMock(return_value="ok")):
        items = asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    # Should have gotten an error callout
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert len(callouts) == 1
    assert "Lost connection" in callouts[0]["callout"]

    # Round 1 messages survived on disk
    history = load_history(hp)
    assert len(history) >= 3  # user + assistant(tool) + user(result)
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[2]["role"] == "user"


def test_error_recovery_saves_incrementally(agent_env):
    """When _exec_editor raises during coro building (after the assistant
    tool_use message is already appended), the except handler patches
    error tool_results. Those should be saved incrementally."""
    ws, hp, ctx = agent_env

    # Round 1: editor tool with missing "command" key → _exec_editor raises KeyError
    # synchronously during coro building, AFTER the assistant message is appended.
    bad_editor = _tool_use_block("t1", name="str_replace_based_edit_tool", inp={})
    round1 = _make_response([bad_editor], stop_reason="tool_use")
    # After error recovery injects error tool_results, the loop retries and gets final text.
    final = _make_response([_text_block("Recovered")])
    responses = iter([round1, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    with _mock_anthropic(mock_client):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    # Should have: user + assistant(bad tool_use) + user(error result) + assistant(final)
    assert len(history) >= 3
    # The error recovery tool_result should be on disk
    error_results = [m for m in history if m["role"] == "user"
                     and isinstance(m.get("content"), list)
                     and any("Error:" in str(r.get("content", "")) for r in m["content"])]
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

    final = _make_response([_text_block("Hello!")])
    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(final)

    with _mock_anthropic(mock_client):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    assert not list(tmp_path.glob("**/*.jsonl"))


# ---------------------------------------------------------------------------
# Media type sniffing tests
# ---------------------------------------------------------------------------

# Minimal valid file headers for each format
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

    bad_editor = _tool_use_block("crash-1", name="str_replace_based_edit_tool", inp={})
    round1 = _make_response([bad_editor], stop_reason="tool_use")
    final = _make_response([_text_block("Recovered")])
    responses = iter([round1, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    with _mock_anthropic(mock_client):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    use_ids, result_ids = _history_tool_ids(history)
    assert use_ids == result_ids


def test_tool_result_present_after_bash_timeout(agent_env):
    """Simulates a bash timeout. The tool_result with the timeout error
    must be saved so follow-up messages don't trigger 400 errors."""
    ws, hp, ctx = agent_env

    bash_block = _tool_use_block("timeout-1", name="bash",
                                  inp={"command": "pip install heavy-package"})
    round1 = _make_response([bash_block], stop_reason="tool_use")
    final = _make_response([_text_block("Sorry about the timeout")])
    responses = iter([round1, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    with _mock_anthropic(mock_client), \
         patch("cycls.agent._exec_bash",
               new_callable=lambda: AsyncMock(return_value="Error: Command timed out after 300s")):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    use_ids, result_ids = _history_tool_ids(history)
    assert use_ids == result_ids
    # Verify the timeout error made it into the correct tool_result
    timeout_result = [b for m in history for b in (m.get("content") or [])
                      if isinstance(b, dict) and b.get("tool_use_id") == "timeout-1"]
    assert len(timeout_result) == 1, "Expected exactly one tool_result for timeout-1"
    assert "timed out" in timeout_result[0]["content"]


def test_multiple_tool_calls_all_get_results(agent_env):
    """When the LLM issues multiple parallel tool calls and one fails,
    ALL tool_use ids must still have matching tool_results."""
    ws, hp, ctx = agent_env

    block_ok = _tool_use_block("ok-1", inp={"command": "echo ok"})
    block_fail = _tool_use_block("fail-1", inp={"command": "pip install heavy"})
    round1 = _make_response([block_ok, block_fail], stop_reason="tool_use")
    final = _make_response([_text_block("Done")])
    responses = iter([round1, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    async def mock_bash(cmd, cwd, **kw):
        if "heavy" in cmd:
            return "Error: Command timed out after 300s"
        return "ok"

    with _mock_anthropic(mock_client), \
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
    view_block = _tool_use_block("v1", name="str_replace_based_edit_tool",
                                  inp={"command": "view", "path": "big.pdf"})
    round1 = _make_response([view_block], stop_reason="tool_use")
    # Round 2: API rejects because tool_result has oversized PDF content
    # Round 3 (after recovery): LLM responds with helpful text
    final = _make_response([_text_block("The PDF is too large. Let me extract specific pages.")])

    call_count = 0

    def stream_side_effect(**kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeStream(round1)
        if call_count == 2:
            # Simulate Anthropic 400: content too large
            raise Exception("messages.1.content.0.tool_result: content too large")
        return FakeStream(final)

    mock_client = MagicMock()
    mock_client.messages.stream = stream_side_effect

    # Create a fake PDF file so _exec_editor can view it
    (Path(ws) / "big.pdf").write_bytes(_PDF_HEADER)

    with _mock_anthropic(mock_client):
        items = asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    # Recovery = no error callout shown to user
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert not callouts, f"Raw error shown instead of recovering: {callouts}"

    # LLM got a third call (recovery round) and produced a final assistant message
    history = load_history(hp)
    assert history[-1]["role"] == "assistant"

    # Tool_result content was replaced with error string (not the raw PDF)
    tool_results = [m for m in history if m["role"] == "user"
                    and isinstance(m.get("content"), list)
                    and any(b.get("type") == "tool_result" for b in m["content"])]
    for msg in tool_results:
        for b in msg["content"]:
            if b.get("type") == "tool_result":
                assert isinstance(b["content"], str), "Tool result content should be error string, not raw PDF"

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

    _, prompt = _prepare_prompt(ctx)
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

    _, prompt = _prepare_prompt(ctx)
    # First MAX_ATTACHMENTS are in the attached files list
    for i in range(MAX_ATTACHMENTS):
        assert f"img{i}.png" in prompt
    # Extras are mentioned as on-disk, not in attached files
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

    over = _usage(inp=COMPACT_THRESHOLD + 1)
    final = _make_response([_text_block("Done")], usage=over)

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(final)

    # Mock _compact to return a known summary
    summary_messages = [
        {"role": "user", "content": "Summary of previous work."},
        {"role": "assistant", "content": "Understood."},
    ]

    with _mock_anthropic(mock_client), \
         patch("cycls.agent._compact", new_callable=lambda: AsyncMock(return_value=summary_messages)):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    assert len(history) == 2
    assert history[0]["content"] == "Summary of previous work."
    # load_history wraps the last message's content with cache_control
    assert history[1]["content"][0]["text"] == "Understood."


def test_no_compaction_below_threshold(agent_env):
    """When input tokens are under COMPACT_THRESHOLD, history is appended normally."""
    ws, hp, ctx = agent_env

    under = _usage(inp=COMPACT_THRESHOLD - 1)
    final = _make_response([_text_block("Done")], usage=under)

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(final)

    with _mock_anthropic(mock_client):
        asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    history = load_history(hp)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"]


def test_compaction_failure_still_saves_history(agent_env):
    """If _compact raises, the final assistant message must still be saved."""
    ws, hp, ctx = agent_env

    over = _usage(inp=COMPACT_THRESHOLD + 1)
    final = _make_response([_text_block("Important answer")], usage=over)

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(final)

    with _mock_anthropic(mock_client), \
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

    call_count = 0
    final = _make_response([_text_block("Done")])

    def stream_side_effect(**kw):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("overloaded")
        return FakeStream(final)

    mock_client = MagicMock()
    mock_client.messages.stream = stream_side_effect

    with _mock_anthropic(mock_client), \
         patch("asyncio.sleep", new_callable=lambda: AsyncMock(return_value=None)):
        items = asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    # No error callouts — retries handled it
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert not callouts
    # Should have retried and succeeded
    assert call_count == 3


def test_auto_retry_exhausted_shows_error(agent_env):
    """After MAX_RETRIES, the error should surface to the user."""
    ws, hp, ctx = agent_env

    mock_client = MagicMock()
    mock_client.messages.stream = MagicMock(side_effect=Exception("overloaded"))

    with _mock_anthropic(mock_client), \
         patch("asyncio.sleep", new_callable=lambda: AsyncMock(return_value=None)):
        items = asyncio.run(_drain(Agent(context=ctx, thinking=False)))

    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert len(callouts) == 1
    assert "overloaded" in callouts[0]["callout"]


# ---------------------------------------------------------------------------
# bwrap sandbox configuration tests
# ---------------------------------------------------------------------------


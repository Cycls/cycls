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

from cycls.agent.harness.main import _run, MAX_RETRIES, _is_retryable, _ingest, _recover
from cycls.agent.harness.compact import COMPACT_BUFFER, KEEP_RECENT, microcompact, context_window
from cycls.agent.harness.tools import MAX_OUTPUT, _exec_bash, _exec_read, _exec_edit, _resolve_path, dispatch
from cycls.agent.chat import load_messages
from cycls.app.db import Workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_history(ctx):
    """Sync test helper around the async load_messages."""
    return asyncio.run(load_messages(ctx.workspace, ctx.chat_id))


def _make_context(ws):
    ctx = types.SimpleNamespace()
    ctx.workspace = Workspace(Path(ws))
    ctx.chat_id = "test-chat"
    user = types.SimpleNamespace()
    user.sessions = Path(ws) / ".sessions"  # legacy path; unused by KV-backed harness
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
    """Create workspace + context for agent tests. Returns (ws, ctx) — the
    chat log lives in `KV("chat", workspace)` keyed under `log/{chat_id}/`."""
    ws_root = tmp_path / "tenant"
    ws_root.mkdir()
    ws = str(ws_root)
    return ws, _make_context(ws)


# ---------------------------------------------------------------------------
# Incremental save tests
# ---------------------------------------------------------------------------

def test_history_saved_after_each_tool_round(agent_env):
    """Two tool rounds then final text — all six messages should be on disk."""
    ws, ctx = agent_env

    round1 = _make_response([_tool_use_block("t1")], stop_reason="tool_use")
    round2 = _make_response([_tool_use_block("t2")], stop_reason="tool_use")
    final = _make_response([_text_block("All done")])
    responses = iter([round1, round2, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    with _mock_anthropic(mock_client), \
         patch("cycls.agent.harness.tools._exec_bash", new_callable=lambda: AsyncMock(return_value="ok")):
        asyncio.run(_drain(_run(context=ctx)))

    history = _read_history(ctx)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]


def test_history_survives_crash_after_first_tool_round(agent_env):
    """Crash during round 2 streaming — round 1 history should already be on disk."""
    ws, ctx = agent_env

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
         patch("cycls.agent.harness.tools._exec_bash", new_callable=lambda: AsyncMock(return_value="ok")):
        items = asyncio.run(_drain(_run(context=ctx)))

    # Should have gotten an error callout
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert len(callouts) == 1
    assert "Lost connection" in callouts[0]["callout"]

    # Round 1 messages survived on disk
    history = _read_history(ctx)
    assert len(history) >= 3  # user + assistant(tool) + user(result)
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[2]["role"] == "user"


def test_error_recovery_saves_incrementally(agent_env):
    """When tool execution raises during dispatch, the except handler patches
    error tool_results. Those should be saved incrementally."""
    ws, ctx = agent_env

    # Round 1: edit tool with missing keys → _exec_edit raises KeyError
    bad_edit = _tool_use_block("t1", name="edit", inp={"path": "x.txt"})
    round1 = _make_response([bad_edit], stop_reason="tool_use")
    # After error recovery injects error tool_results, the loop retries and gets final text.
    final = _make_response([_text_block("Recovered")])
    responses = iter([round1, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    with _mock_anthropic(mock_client):
        asyncio.run(_drain(_run(context=ctx)))

    history = _read_history(ctx)
    # Should have: user + assistant(bad tool_use) + user(error result) + assistant(final)
    assert len(history) >= 3
    # The error recovery tool_result should be on disk
    error_results = [m for m in history if m["role"] == "user"
                     and isinstance(m.get("content"), list)
                     and any("Error:" in str(r.get("content", "")) for r in m["content"])]
    assert len(error_results) >= 1


def test_no_history_without_session(tmp_path):
    """No chat_id → nothing saved to disk."""
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()

    ctx = types.SimpleNamespace()
    ctx.workspace = types.SimpleNamespace(root=Path(ws))
    ctx.chat_id = None
    ctx.user = None
    ctx.messages = types.SimpleNamespace()
    ctx.messages.raw = [{"role": "user", "content": "hi"}]

    final = _make_response([_text_block("Hello!")])
    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(final)

    with _mock_anthropic(mock_client):
        asyncio.run(_drain(_run(context=ctx)))

    assert not list(tmp_path.glob("**/*.jsonl"))


# ---------------------------------------------------------------------------
# File reading tests (replaces editor view tests)
# ---------------------------------------------------------------------------

def test_exec_read_text_file(tmp_path):
    """Read a text file — should return line-numbered output."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.txt").write_text("line1\nline2\nline3")

    result = asyncio.run(_exec_read({"path": "hello.txt"}, str(ws)))
    assert "line1" in result
    assert "line2" in result
    assert "line3" in result


def test_exec_read_with_offset_and_limit(tmp_path):
    """Read with offset and limit should return only the requested range."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "lines.txt").write_text("\n".join(f"line{i}" for i in range(1, 11)))

    result = asyncio.run(_exec_read({"path": "lines.txt", "offset": 3, "limit": 2}, str(ws)))
    assert "line3" in result
    assert "line4" in result
    assert "line2" not in result
    assert "line5" not in result


def test_exec_read_image_returns_base64(tmp_path):
    """Reading a .png file should return an image content block."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    result = asyncio.run(_exec_read({"path": "photo.png"}, str(ws)))
    assert isinstance(result, list)
    assert result[0]["type"] == "image"
    assert result[0]["source"]["media_type"] == "image/png"


def test_exec_read_jpeg_extension(tmp_path):
    """Both .jpg and .jpeg should return image/jpeg."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "photo.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 20)

    result = asyncio.run(_exec_read({"path": "photo.jpg"}, str(ws)))
    assert result[0]["source"]["media_type"] == "image/jpeg"


def test_exec_read_pdf_returns_document(tmp_path):
    """Reading a .pdf should return a document content block."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "doc.pdf").write_bytes(b"%PDF-1.4" + b"\x00" * 20)

    result = asyncio.run(_exec_read({"path": "doc.pdf"}, str(ws)))
    assert isinstance(result, list)
    assert result[0]["type"] == "document"
    assert result[0]["source"]["media_type"] == "application/pdf"


def test_exec_read_nonexistent_file(tmp_path):
    """Reading a missing file should return an error string."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    result = asyncio.run(_exec_read({"path": "nope.txt"}, str(ws)))
    assert "Error" in result
    assert "does not exist" in result


def test_exec_read_binary_file(tmp_path):
    """Reading a file with invalid UTF-8 should return a binary error."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    # Write bytes that will trigger UnicodeDecodeError on .read_text()
    (ws / "data.bin").write_bytes(b"\x80\x81\x82\x83" * 100)

    result = asyncio.run(_exec_read({"path": "data.bin"}, str(ws)))
    assert "Error" in result
    assert "binary" in result


# ---------------------------------------------------------------------------
# File editing tests (replaces editor edit tests)
# ---------------------------------------------------------------------------

def test_exec_edit_str_replace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "f.txt").write_text("hello world")

    result = _exec_edit({"path": "f.txt", "command": "str_replace", "old_str": "hello", "new_str": "goodbye"}, str(ws))
    assert "Replaced" in result
    assert (ws / "f.txt").read_text() == "goodbye world"


def test_exec_edit_create(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    result = _exec_edit({"path": "new.txt", "command": "create", "file_text": "fresh file"}, str(ws))
    assert "Created" in result
    assert (ws / "new.txt").read_text() == "fresh file"


def test_exec_edit_insert(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "f.txt").write_text("line1\nline2\n")

    result = _exec_edit({"path": "f.txt", "command": "insert", "insert_line": 1, "new_str": "inserted\n"}, str(ws))
    assert "Inserted" in result
    assert "inserted" in (ws / "f.txt").read_text()


def test_exec_edit_str_replace_not_unique(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "f.txt").write_text("aaa aaa")

    result = _exec_edit({"path": "f.txt", "command": "str_replace", "old_str": "aaa"}, str(ws))
    assert "Error" in result
    assert "2 times" in result


# ---------------------------------------------------------------------------
# Path traversal tests
# ---------------------------------------------------------------------------

def test_resolve_path_blocks_traversal(tmp_path):
    """Paths escaping the workspace must be rejected."""
    ws = tmp_path / "workspace"
    ws.mkdir()

    with pytest.raises(ValueError, match="escapes"):
        _resolve_path("../../etc/passwd", str(ws))


def test_resolve_path_allows_valid(tmp_path):
    """Normal relative paths within workspace must work."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.txt").write_text("world")

    path = _resolve_path("hello.txt", str(ws))
    assert path.exists()
    assert path.name == "hello.txt"


def test_resolve_path_strips_workspace_prefix(tmp_path):
    """Paths prefixed with /workspace/ should work."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.txt").write_text("world")

    path = _resolve_path("/workspace/hello.txt", str(ws))
    assert path.name == "hello.txt"


def test_exec_read_blocks_path_traversal(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()

    result = asyncio.run(_exec_read({"path": "../../etc/passwd"}, str(ws)))
    assert "Error" in result

    result = asyncio.run(_exec_read({"path": "/etc/passwd"}, str(ws)))
    assert "Error" in result


# ---------------------------------------------------------------------------
# Tool history corruption tests
# ---------------------------------------------------------------------------

def test_tool_result_always_follows_tool_use_on_crash(agent_env):
    """Every tool_use id in history must have a matching tool_result,
    even when tool execution crashes mid-way."""
    ws, ctx = agent_env

    bad_edit = _tool_use_block("crash-1", name="edit", inp={"path": "x.txt"})
    round1 = _make_response([bad_edit], stop_reason="tool_use")
    final = _make_response([_text_block("Recovered")])
    responses = iter([round1, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    with _mock_anthropic(mock_client):
        asyncio.run(_drain(_run(context=ctx)))

    history = _read_history(ctx)
    use_ids, result_ids = _history_tool_ids(history)
    assert use_ids == result_ids


def test_tool_result_present_after_bash_timeout(agent_env):
    """Simulates a bash timeout. The tool_result with the timeout error
    must be saved so follow-up messages don't trigger 400 errors."""
    ws, ctx = agent_env

    bash_block = _tool_use_block("timeout-1", name="bash",
                                  inp={"command": "pip install heavy-package"})
    round1 = _make_response([bash_block], stop_reason="tool_use")
    final = _make_response([_text_block("Sorry about the timeout")])
    responses = iter([round1, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))

    with _mock_anthropic(mock_client), \
         patch("cycls.agent.harness.tools._exec_bash",
               new_callable=lambda: AsyncMock(return_value="Error: Command timed out after 300s")):
        asyncio.run(_drain(_run(context=ctx)))

    history = _read_history(ctx)
    use_ids, result_ids = _history_tool_ids(history)
    assert use_ids == result_ids
    timeout_result = [b for m in history for b in (m.get("content") or [])
                      if isinstance(b, dict) and b.get("tool_use_id") == "timeout-1"]
    assert len(timeout_result) == 1
    assert "timed out" in timeout_result[0]["content"]


def test_multiple_tool_calls_all_get_results(agent_env):
    """When the LLM issues multiple parallel tool calls and one fails,
    ALL tool_use ids must still have matching tool_results."""
    ws, ctx = agent_env

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
         patch("cycls.agent.harness.tools._exec_bash", side_effect=mock_bash):
        asyncio.run(_drain(_run(context=ctx)))

    history = _read_history(ctx)
    use_ids, result_ids = _history_tool_ids(history)
    assert sorted(use_ids) == sorted(result_ids)


# ---------------------------------------------------------------------------
# Bash timeout tests (_exec_bash directly)
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
# Bash output truncation tests
# ---------------------------------------------------------------------------

def test_exec_bash_truncates_large_output(tmp_path):
    """Output exceeding MAX_OUTPUT chars must be truncated with marker."""
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()

    big_output = ("x" * (MAX_OUTPUT + 10000)).encode()
    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(return_value=(big_output, b""))
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    async def run():
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            return await _exec_bash("echo big", ws)

    result = asyncio.run(run())
    assert len(result) < MAX_OUTPUT + 1000
    assert "truncated" in result


# ---------------------------------------------------------------------------
# API error recovery tests
# ---------------------------------------------------------------------------

def test_api_400_after_tool_results_shows_error(agent_env):
    """When the API rejects tool_results (e.g. oversized content), and the last
    message is tool_results (not unresolved tool_use), the error is shown to the
    user since recovery only handles unresolved tool_use blocks."""
    ws, ctx = agent_env

    read_block = _tool_use_block("v1", name="read", inp={"path": "big.pdf"})
    round1 = _make_response([read_block], stop_reason="tool_use")

    call_count = 0

    def stream_side_effect(**kw):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeStream(round1)
        # After tool_results are appended, API rejects them
        raise Exception("messages.1.content.0.tool_result: content too large")

    mock_client = MagicMock()
    mock_client.messages.stream = stream_side_effect

    (Path(ws) / "big.pdf").write_bytes(b"%PDF-1.4" + b"\x00" * 20)

    with _mock_anthropic(mock_client):
        items = asyncio.run(_drain(_run(context=ctx)))

    # Error should surface since recovery doesn't handle post-tool_result errors
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert len(callouts) == 1
    assert "content too large" in callouts[0]["callout"]


# ---------------------------------------------------------------------------
# Ingest tests (attachment resolution)
# ---------------------------------------------------------------------------

def test_ingest_plain_string_passthrough(tmp_path):
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()
    result = asyncio.run(_ingest("just a string", ws))
    assert result == "just a string"


def test_ingest_image_becomes_content_block(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    parts = [
        {"type": "text", "text": "what is this?"},
        {"type": "image", "image": "photo.png"},
    ]
    result = asyncio.run(_ingest(parts, str(ws)))
    assert len(result) == 2
    assert result[0] == {"type": "text", "text": "what is this?"}
    assert result[1]["type"] == "image"
    assert result[1]["source"]["media_type"] == "image/png"


def test_ingest_missing_file_becomes_text_hint(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    parts = [{"type": "file", "file": "nope.txt"}]
    result = asyncio.run(_ingest(parts, str(ws)))
    assert len(result) == 1
    assert result[0]["type"] == "text"
    assert "Error" in result[0]["text"] or "does not exist" in result[0]["text"]


def test_ingest_empty_file_ref_passes_through(tmp_path):
    ws = str(tmp_path / "workspace")
    Path(ws).mkdir()
    parts = [{"type": "file"}]  # no fname
    result = asyncio.run(_ingest(parts, ws))
    assert result == parts


# ---------------------------------------------------------------------------
# Context compaction tests
# ---------------------------------------------------------------------------

def test_compaction_triggers_when_approaching_window(agent_env):
    """When input tokens approach context window and enough messages exist, compaction fires."""
    ws, ctx = agent_env

    window = context_window("claude-sonnet-4-20250514")
    high_usage = _usage(inp=window - COMPACT_BUFFER + 1)

    # Build enough tool rounds to exceed KEEP_RECENT messages
    rounds = []
    for i in range(KEEP_RECENT // 2 + 2):
        rounds.append(_make_response([_tool_use_block(f"t{i}")], stop_reason="tool_use", usage=high_usage))
    rounds.append(_make_response([_text_block("Done")], usage=high_usage))
    responses = iter(rounds)

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))
    mock_client.messages.create = AsyncMock(return_value=MagicMock(
        content=[MagicMock(text="<analysis>thinking</analysis><summary>Summary here</summary>")]))

    with _mock_anthropic(mock_client), \
         patch("cycls.agent.harness.tools._exec_bash", new_callable=lambda: AsyncMock(return_value="ok")):
        items = asyncio.run(_drain(_run(context=ctx)))

    steps = [i for i in items if isinstance(i, dict) and i.get("step") == "Compacting context..."]
    assert len(steps) >= 1


def test_no_compaction_when_under_threshold(agent_env):
    """When input tokens are well under window, no compaction happens."""
    ws, ctx = agent_env

    low_usage = _usage(inp=1000)
    final = _make_response([_text_block("Done")], usage=low_usage)

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(final)

    with _mock_anthropic(mock_client):
        items = asyncio.run(_drain(_run(context=ctx)))

    steps = [i for i in items if isinstance(i, dict) and i.get("step") == "Compacting context..."]
    assert len(steps) == 0

    history = _read_history(ctx)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"]


def test_compaction_failure_still_saves_history(agent_env):
    """If compaction API call fails, the conversation must still be saved."""
    ws, ctx = agent_env

    window = context_window("claude-sonnet-4-20250514")
    high_usage = _usage(inp=window - COMPACT_BUFFER + 1)

    round1 = _make_response([_tool_use_block("t1")], stop_reason="tool_use", usage=high_usage)
    final = _make_response([_text_block("Important answer")])
    responses = iter([round1, final])

    mock_client = MagicMock()
    mock_client.messages.stream = lambda **kw: FakeStream(next(responses))
    mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

    with _mock_anthropic(mock_client), \
         patch("cycls.agent.harness.tools._exec_bash", new_callable=lambda: AsyncMock(return_value="ok")):
        asyncio.run(_drain(_run(context=ctx)))

    history = _read_history(ctx)
    assert len(history) >= 2
    # The actual answer must not be lost
    last = history[-1]["content"]
    text = last[0]["text"] if isinstance(last, list) else last
    assert "Important answer" in text


# ---------------------------------------------------------------------------
# Microcompact tests
# ---------------------------------------------------------------------------

def test_microcompact_clears_old_tool_results():
    """Old tool results should be replaced with stub, recent ones preserved."""
    messages = []
    for i in range(KEEP_RECENT + 5):
        messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}"}]})
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": f"result {i} " * 100}
        ]})

    microcompact(messages)

    # Old user messages (tool_results) should be cleared — index 1 is the first user message
    old_user_msg = messages[1]  # first user message with tool_result
    assert old_user_msg["content"][0]["content"] == "[Old tool result cleared]"

    # Recent user messages should be preserved — last message is a user message
    recent_user_msg = messages[-1]
    assert "result" in recent_user_msg["content"][0]["content"]
    assert recent_user_msg["content"][0]["content"] != "[Old tool result cleared]"


# ---------------------------------------------------------------------------
# Auto-retry tests
# ---------------------------------------------------------------------------

def test_is_retryable_detects_status_codes():
    """Status code-based detection should work."""
    e429 = MagicMock()
    e429.status_code = 429
    assert _is_retryable(e429)

    e529 = MagicMock()
    e529.status_code = 529
    assert _is_retryable(e529)


def test_is_retryable_detects_string_fallback():
    """String-based fallback should still work."""
    assert _is_retryable(Exception("overloaded"))
    assert _is_retryable(Exception("rate limit exceeded"))
    assert not _is_retryable(Exception("invalid api key"))


def test_auto_retry_on_overloaded(agent_env):
    """Transient API errors should be retried, not shown as errors."""
    ws, ctx = agent_env

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
        items = asyncio.run(_drain(_run(context=ctx)))

    # No error callouts — retries handled it
    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert not callouts
    assert call_count == 3


def test_auto_retry_exhausted_shows_error(agent_env):
    """After MAX_RETRIES, the error should surface to the user."""
    ws, ctx = agent_env

    mock_client = MagicMock()
    mock_client.messages.stream = MagicMock(side_effect=Exception("overloaded"))

    with _mock_anthropic(mock_client), \
         patch("asyncio.sleep", new_callable=lambda: AsyncMock(return_value=None)):
        items = asyncio.run(_drain(_run(context=ctx)))

    callouts = [i for i in items if isinstance(i, dict) and i.get("type") == "callout"]
    assert len(callouts) == 1
    assert "overloaded" in callouts[0]["callout"]


# ---------------------------------------------------------------------------
# Recovery function tests
# ---------------------------------------------------------------------------

def test_recover_patches_unresolved_tool_use():
    """_recover should inject error tool_results for unresolved tool_use blocks."""
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1"},
            {"type": "tool_use", "id": "t2"},
        ]}
    ]
    assert _recover(Exception("API error"), messages) is True
    assert len(messages) == 2
    results = messages[1]["content"]
    assert all(r["type"] == "tool_result" for r in results)
    assert {r["tool_use_id"] for r in results} == {"t1", "t2"}


def test_recover_returns_false_on_non_recoverable():
    """_recover should return False when messages can't be patched."""
    messages = [{"role": "user", "content": "hello"}]
    assert _recover(Exception("bad"), messages) is False


# ---------------------------------------------------------------------------
# Context window tests
# ---------------------------------------------------------------------------

def test_context_window_family_models():
    assert context_window("claude-sonnet-4-20250514") == 200_000
    assert context_window("claude-opus-4-20250514") == 200_000
    assert context_window("claude-haiku-3-5-20241022") == 200_000


def test_context_window_1m_variants():
    assert context_window("claude-opus-4-6[1m]") == 1_000_000
    assert context_window("claude-sonnet-4-6[1m]") == 1_000_000


def test_context_window_unknown_model():
    assert context_window("gpt-4o") == 200_000

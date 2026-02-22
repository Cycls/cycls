import pytest
import json
import asyncio
import importlib.resources
from cycls.web import web, Config, Messages, sse, encoder, openai_encoder

# To run these tests:
# poetry run pytest tests/web_test.py -v -s

# Use actual default theme
THEME_PATH = str(importlib.resources.files('cycls').joinpath('themes/dev'))


# =============================================================================
# Messages Class Tests
# =============================================================================

def test_messages_extracts_text_content():
    """Tests that Messages extracts text-only content from raw messages."""
    print("\n--- Running test: test_messages_extracts_text_content ---")

    raw = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"}
    ]
    messages = Messages(raw)

    assert len(messages) == 2
    assert messages[0] == {"role": "user", "content": "Hello"}
    assert messages[1] == {"role": "assistant", "content": "Hi there"}
    print("✅ Test passed.")


def test_messages_extracts_from_parts():
    """Tests that Messages extracts text from parts when content is empty."""
    print("\n--- Running test: test_messages_extracts_from_parts ---")

    raw = [
        {
            "role": "assistant",
            "content": "",
            "parts": [
                {"type": "thinking", "thinking": "Let me think..."},
                {"type": "text", "text": "Here is "},
                {"type": "text", "text": "the answer."}
            ]
        }
    ]
    messages = Messages(raw)

    assert messages[0]["content"] == "Here is the answer."
    print("✅ Test passed.")


def test_messages_raw_preserves_original():
    """Tests that Messages.raw returns original raw messages."""
    print("\n--- Running test: test_messages_raw_preserves_original ---")

    raw = [
        {"role": "user", "content": "test", "extra_field": "preserved"}
    ]
    messages = Messages(raw)

    assert messages.raw == raw
    assert messages.raw[0]["extra_field"] == "preserved"
    print("✅ Test passed.")


# =============================================================================
# SSE Encoder Tests
# =============================================================================

def test_sse_converts_string_to_text_type():
    """Tests that sse() converts plain strings to text type."""
    print("\n--- Running test: test_sse_converts_string_to_text_type ---")

    result = sse("hello")
    expected = 'data: {"type": "text", "text": "hello"}\n\n'

    assert result == expected
    print("✅ Test passed.")


def test_sse_passes_dict_through():
    """Tests that sse() passes dict items through unchanged."""
    print("\n--- Running test: test_sse_passes_dict_through ---")

    item = {"type": "thinking", "thinking": "processing..."}
    result = sse(item)

    assert result == f'data: {json.dumps(item)}\n\n'
    print("✅ Test passed.")


def test_sse_returns_none_for_empty():
    """Tests that sse() returns None for empty/falsy items."""
    print("\n--- Running test: test_sse_returns_none_for_empty ---")

    assert sse(None) is None
    assert sse("") is None
    assert sse({}) is None
    print("✅ Test passed.")


# =============================================================================
# Async Encoder Tests
# =============================================================================

def test_encoder_async_stream():
    """Tests encoder with async generator."""
    print("\n--- Running test: test_encoder_async_stream ---")

    async def stream():
        yield "hello"
        yield {"type": "thinking", "thinking": "..."}

    async def run():
        results = []
        async for item in encoder(stream()):
            results.append(item)
        return results

    results = asyncio.run(run())

    assert results[0] == 'data: {"type": "text", "text": "hello"}\n\n'
    assert results[1] == 'data: {"type": "thinking", "thinking": "..."}\n\n'
    assert results[2] == "data: [DONE]\n\n"
    print("✅ Test passed.")


def test_encoder_sync_stream():
    """Tests encoder with sync generator."""
    print("\n--- Running test: test_encoder_sync_stream ---")

    def stream():
        yield "sync"
        yield "response"

    async def run():
        results = []
        async for item in encoder(stream()):
            results.append(item)
        return results

    results = asyncio.run(run())

    assert len(results) == 3  # 2 items + DONE
    assert "sync" in results[0]
    assert "response" in results[1]
    assert results[2] == "data: [DONE]\n\n"
    print("✅ Test passed.")


def test_openai_encoder_format():
    """Tests that openai_encoder produces OpenAI-compatible format."""
    print("\n--- Running test: test_openai_encoder_format ---")

    async def stream():
        yield "Hello"
        yield " world"

    async def run():
        results = []
        async for item in openai_encoder(stream()):
            results.append(item)
        return results

    results = asyncio.run(run())

    # Check OpenAI format
    parsed = json.loads(results[0].replace("data: ", ""))
    assert parsed == {"choices": [{"delta": {"content": "Hello"}}]}

    assert results[-1] == "data: [DONE]\n\n"
    print("✅ Test passed.")


# =============================================================================
# FastAPI Web App Tests
# =============================================================================

def test_config_endpoint():
    """Tests the /config endpoint returns configuration."""
    print("\n--- Running test: test_config_endpoint ---")
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    config = Config(
        public_path=THEME_PATH,
        header="Test Header",
        intro="Test Intro",
        title="Test Title",
        plan="free",
        auth=False
    )

    app = web(dummy_agent, config)
    client = TestClient(app)

    response = client.get("/config")
    assert response.status_code == 200

    data = response.json()
    assert data["header"] == "Test Header"
    assert data["intro"] == "Test Intro"
    assert data["title"] == "Test Title"
    assert data["plan"] == "free"
    print("✅ Test passed.")


def test_chat_cycls_endpoint_streams():
    """Tests that /chat/cycls returns streaming SSE response."""
    print("\n--- Running test: test_chat_cycls_endpoint_streams ---")
    from fastapi.testclient import TestClient

    async def echo_agent(context):
        yield f"You said: {context.messages[0]['content']}"

    config = Config(public_path=THEME_PATH, auth=False)
    app = web(echo_agent, config)
    client = TestClient(app)

    response = client.post(
        "/chat/cycls",
        json={"messages": [{"role": "user", "content": "hello"}]}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    # Parse SSE response
    lines = response.text.strip().split("\n\n")
    data_line = lines[0]
    assert data_line.startswith("data: ")

    parsed = json.loads(data_line.replace("data: ", ""))
    assert parsed["type"] == "text"
    assert "You said: hello" in parsed["text"]
    print("✅ Test passed.")


def test_chat_completions_endpoint_openai_format():
    """Tests that /chat/completions returns OpenAI-compatible format."""
    print("\n--- Running test: test_chat_completions_endpoint_openai_format ---")
    from fastapi.testclient import TestClient

    async def simple_agent(context):
        yield "response"

    config = Config(public_path=THEME_PATH, auth=False)
    app = web(simple_agent, config)
    client = TestClient(app)

    response = client.post(
        "/chat/completions",
        json={"messages": [{"role": "user", "content": "test"}]}
    )

    assert response.status_code == 200

    lines = response.text.strip().split("\n\n")
    data_line = lines[0]
    parsed = json.loads(data_line.replace("data: ", ""))

    assert "choices" in parsed
    assert parsed["choices"][0]["delta"]["content"] == "response"
    print("✅ Test passed.")


def test_sync_agent_function():
    """Tests that sync generator functions work with web app."""
    print("\n--- Running test: test_sync_agent_function ---")
    from fastapi.testclient import TestClient

    def sync_agent(context):
        yield "sync "
        yield "works"

    config = Config(public_path=THEME_PATH, auth=False)
    app = web(sync_agent, config)
    client = TestClient(app)

    response = client.post(
        "/chat/cycls",
        json={"messages": [{"role": "user", "content": "test"}]}
    )

    assert response.status_code == 200
    assert "sync" in response.text
    assert "works" in response.text
    print("✅ Test passed.")


def test_async_agent_function():
    """Tests that async generator functions work with web app."""
    print("\n--- Running test: test_async_agent_function ---")
    from fastapi.testclient import TestClient

    async def async_agent(context):
        yield "async "
        yield "works"

    config = Config(public_path=THEME_PATH, auth=False)
    app = web(async_agent, config)
    client = TestClient(app)

    response = client.post(
        "/chat/cycls",
        json={"messages": [{"role": "user", "content": "test"}]}
    )

    assert response.status_code == 200
    assert "async" in response.text
    assert "works" in response.text
    print("✅ Test passed.")


def test_context_has_messages():
    """Tests that context.messages is properly populated."""
    print("\n--- Running test: test_context_has_messages ---")
    from fastapi.testclient import TestClient

    received_context = None

    async def capture_agent(context):
        nonlocal received_context
        received_context = context
        yield "captured"

    config = Config(public_path=THEME_PATH, auth=False)
    app = web(capture_agent, config)
    client = TestClient(app)

    client.post(
        "/chat/cycls",
        json={"messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"}
        ]}
    )

    assert received_context is not None
    assert len(received_context.messages) == 3
    assert received_context.messages[0]["content"] == "first"
    assert received_context.messages[2]["content"] == "second"
    print("✅ Test passed.")


def test_streaming_multiple_yields():
    """Tests that multiple yields are properly streamed."""
    print("\n--- Running test: test_streaming_multiple_yields ---")
    from fastapi.testclient import TestClient

    async def multi_yield_agent(context):
        yield "one"
        yield {"type": "thinking", "thinking": "processing"}
        yield "two"
        yield {"type": "callout", "callout": "done", "style": "success"}

    config = Config(public_path=THEME_PATH, auth=False)
    app = web(multi_yield_agent, config)
    client = TestClient(app)

    response = client.post(
        "/chat/cycls",
        json={"messages": [{"role": "user", "content": "test"}]}
    )

    lines = [l for l in response.text.split("\n\n") if l.startswith("data:")]

    # Should have 4 data items + DONE
    assert len(lines) == 5

    # Check each type
    assert '"type": "text"' in lines[0]
    assert '"type": "thinking"' in lines[1]
    assert '"type": "text"' in lines[2]
    assert '"type": "callout"' in lines[3]
    assert "[DONE]" in lines[4]
    print("✅ Test passed.")


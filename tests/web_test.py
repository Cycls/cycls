import pytest
import json
import asyncio
import importlib.resources
from cycls.agent.web import web, Config, Messages, sse, encoder, openai_encoder

# To run these tests:
# poetry run pytest tests/web_test.py -v -s

# Use actual default theme
THEME_PATH = str(importlib.resources.files('cycls').joinpath('agent/web/themes/dev'))


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
        title="Test Title",
        plan="free",
        auth=False
    )

    app = web(dummy_agent, config)
    client = TestClient(app)

    response = client.get("/config")
    assert response.status_code == 200

    data = response.json()
    assert data["title"] == "Test Title"
    assert data["cms"] is None
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
        "/",
        json={"messages": [{"role": "user", "content": "hello"}]}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    # Parse SSE response
    lines = response.text.strip().split("\n\n")
    # First event is chat_id
    first = json.loads(lines[0].replace("data: ", ""))
    assert first["type"] == "chat_id"
    assert "chat_id" in first

    # Second event is the actual text
    parsed = json.loads(lines[1].replace("data: ", ""))
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


# =============================================================================
# Signed-URL share flow (live shares, no frozen snapshot)
# =============================================================================

def _share_test_app(tmp_path):
    """Mount POST /share + GET /shared/data on a FastAPI app, with a fixed
    in-process User and a real cycls.App for signing. No live JWT verification."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls.app.auth import User
    from cycls.app.db import workspace_for
    from cycls.agent.web.routers import share_router

    import cycls

    @cycls.app(image={"volume": str(tmp_path)})
    def svc():
        return None

    user = User(id="user_test")
    user_dep = Depends(lambda: user)
    ws_dep = Depends(lambda: workspace_for(user, tmp_path))

    fapp = FastAPI()
    fapp.include_router(share_router(svc, ws_dep, user_dep, tmp_path, None))
    return svc, user, TestClient(fapp)


def test_share_router_mint_and_resolve(tmp_path):
    """POST /share mints a signed URL; GET /shared/data?... returns the chat."""
    from cycls.agent import chat
    from cycls.app.db import workspace_for
    from cycls.app.auth import User
    import asyncio

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace_for(user, tmp_path)

    async def seed():
        await chat.put_meta(ws, "c1", {"id": "c1", "title": "First chat"})
        await chat.append_messages(ws, "c1", [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello there"},
        ], 0)
    asyncio.run(seed())

    r = client.post("/share", json={"chat_id": "c1", "title": "Shared chat"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "c1"
    assert body["url"].startswith("/shared?")

    # The page URL is /shared?...; the SPA derives the data URL by inserting /data.
    data_url = body["url"].replace("/shared?", "/shared/data?")
    r2 = client.get(data_url)
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["id"] == "c1"
    assert data["title"] == "Shared chat"
    assert [m["content"] for m in data["messages"]] == ["hi", "hello there"]


def test_share_router_rejects_tampered_url(tmp_path):
    from cycls.agent import chat
    from cycls.app.db import workspace_for
    from cycls.app.auth import User
    import asyncio

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace_for(user, tmp_path)
    asyncio.run(chat.put_meta(ws, "c1", {"id": "c1", "title": "T"}))

    url = client.post("/share", json={"chat_id": "c1"}).json()["url"]
    data_url = url.replace("/shared?", "/shared/data?")
    # Swap chat path — sig no longer matches
    bad = data_url.replace("path=chat%2Fc1", "path=chat%2Fother")
    assert client.get(bad).status_code == 403


def test_share_router_unknown_chat_404(tmp_path):
    svc, user, client = _share_test_app(tmp_path)
    r = client.post("/share", json={"chat_id": "missing"})
    assert r.status_code == 404


def test_share_router_list_and_delete(tmp_path):
    from cycls.agent import chat
    from cycls.app.db import workspace_for
    import asyncio

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace_for(user, tmp_path)
    asyncio.run(chat.put_meta(ws, "c1", {"id": "c1", "title": "T"}))

    client.post("/share", json={"chat_id": "c1", "title": "T"})
    listed = client.get("/share").json()
    assert [s["id"] for s in listed] == ["c1"]

    client.delete("/share/c1")
    assert client.get("/share").json() == []


def test_files_sign_mints_signed_url(tmp_path):
    """POST /files/sign mints a signed URL to /shared/file/<path>; the URL serves
    the actual file bytes when GET-ed back."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls.app.auth import User
    from cycls.app.db import workspace_for
    from cycls.agent.web.routers import files_router, share_router
    import cycls

    @cycls.app(image={"volume": str(tmp_path)})
    def svc():
        return None

    user = User(id="user_test")
    user_dep = Depends(lambda: user)
    ws_dep = Depends(lambda: workspace_for(user, tmp_path))

    # Seed a file in the user's workspace root
    ws = workspace_for(user, tmp_path)
    ws.root.mkdir(parents=True, exist_ok=True)
    (ws.root / "doc.md").write_text("hello world")

    fapp = FastAPI()
    fapp.include_router(files_router(svc, ws_dep, user_dep))
    fapp.include_router(share_router(svc, ws_dep, user_dep, tmp_path, None))
    client = TestClient(fapp)

    r = client.post("/files/sign", json={"path": "doc.md"})
    assert r.status_code == 200
    url = r.json()["url"]
    assert url.startswith("/shared?path=file%2Fdoc.md")

    # /shared/file/<path> is the actual binary endpoint; SPA strips the prefix
    file_url = url.replace("/shared?", "/shared/file/doc.md?", 1)
    # Drop the path= param since file path is already in the URL path
    import re
    file_url = re.sub(r"path=file%2F[^&]+&?", "", file_url)
    r2 = client.get(file_url)
    assert r2.status_code == 200
    assert r2.content == b"hello world"


def test_make_validate_rejects_query_token(tmp_path):
    """Regression: `?token=` in the query MUST NOT authenticate (Codespace proxy
    can inject stray Bearers; URL tokens leak via logs/Referer). Bearer header only."""
    from cycls.app.auth import make_validate
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    validate = make_validate(lambda: "https://example.invalid/jwks")
    fapp = FastAPI()

    @fapp.get("/me")
    def me(user=Depends(validate)):
        return {"id": user.id}

    client = TestClient(fapp)
    # Anything in ?token= must be ignored — without an Authorization header, 401.
    r = client.get("/me?token=anything")
    assert r.status_code == 401


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
        "/",
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
        "/",
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
        "/",
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
        "/",
        json={"messages": [{"role": "user", "content": "test"}]}
    )

    lines = [l for l in response.text.split("\n\n") if l.startswith("data:")]

    # Should have chat_id + 4 data items + DONE
    assert len(lines) == 6

    # Check each type
    assert '"type": "chat_id"' in lines[0]
    assert '"type": "text"' in lines[1]
    assert '"type": "thinking"' in lines[2]
    assert '"type": "text"' in lines[3]
    assert '"type": "callout"' in lines[4]
    assert "[DONE]" in lines[5]
    print("✅ Test passed.")


# =============================================================================
# Context.workspace() wiring — Image.volume() threaded from Config to Workspace.
# Org path nesting is covered in tests/data_test.py::test_user_id_produces_nested_path.
# =============================================================================

def test_context_workspace_uses_config_volume():
    """Config.volume threads into Context.workspace() at per-request construction."""
    from fastapi.testclient import TestClient
    from pathlib import Path
    from cycls.app.db import Workspace

    captured = {}
    async def handler(context):
        captured["ws"] = context.workspace
        yield "ok"

    config = Config(public_path=THEME_PATH, auth=False, volume="/tmp/cycls-test-vol")
    client = TestClient(web(handler, config))
    client.post("/", json={"messages": [{"role": "user", "content": "hi"}]})

    assert isinstance(captured["ws"], Workspace)
    assert captured["ws"].root == Path("/tmp/cycls-test-vol/local")  # no auth → 'local'


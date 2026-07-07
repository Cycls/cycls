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
# Token-based share flow (RFC003)
# =============================================================================

def _share_test_app(tmp_path):
    """Mount the token-based share router with a fixed in-process User."""
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls.app.auth import User
    from cycls.app.db import workspace
    from cycls.agent.web.routers import share_router
    import cycls

    @cycls.app(image={"volume": str(tmp_path)})
    def svc():
        return None

    user = User(id="user_test")
    user_dep = Depends(lambda: user)
    ws_dep = Depends(lambda: workspace(user, tmp_path, base=f"file://{tmp_path}"))

    fapp = FastAPI()
    fapp.include_router(share_router(svc, ws_dep, user_dep, tmp_path, f"file://{tmp_path}"))
    return svc, user, TestClient(fapp)


def test_share_router_mint_and_resolve(tmp_path):
    """POST /share mints a token; GET /share/<user>/<token>/data returns the chat."""
    from cycls.agent import state as chat
    from cycls.app.db import workspace
    import asyncio

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")

    async def seed():
        await chat.put_meta(ws, "c1", {"id": "c1", "title": "First chat"})
        await chat.append_messages(ws, "c1", [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello there"},
        ], 0)
    asyncio.run(seed())

    r = client.post("/share", json={
        "path": "chat/c1",
        "author_name": "Alice", "author_image_url": "https://example.com/a.png",
        "author_org_name": "Acme",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == "chat/c1"
    assert body["audience"] == "public"
    assert body["url"].startswith("/shared/user_test/")
    assert body["author_name"] == "Alice"
    assert body["author_image_url"] == "https://example.com/a.png"
    assert body["author_org_name"] == "Acme"
    assert "shared_at" in body

    r2 = client.get(f"/share/user_test/{body['token']}/data")
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["type"] == "chat"
    assert data["id"] == "c1"
    assert data["title"] == "First chat"
    assert data["author_name"] == "Alice"
    assert data["author_image_url"] == "https://example.com/a.png"
    assert data["author_org_name"] == "Acme"
    assert [m["content"] for m in data["messages"]] == ["hi", "hello there"]


def test_share_router_rejects_bogus_token(tmp_path):
    svc, user, client = _share_test_app(tmp_path)
    assert client.get("/share/user_test/bogus_token/data").status_code == 403


def test_share_router_unknown_chat_404(tmp_path):
    svc, user, client = _share_test_app(tmp_path)
    r = client.post("/share", json={"path": "chat/missing"})
    assert r.status_code == 404


def test_share_router_list_and_delete(tmp_path):
    from cycls.agent import state as chat
    from cycls.app.db import workspace
    import asyncio

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    asyncio.run(chat.put_meta(ws, "c1", {"id": "c1", "title": "T"}))

    body = client.post("/share", json={"path": "chat/c1"}).json()
    token = body["token"]

    listed = client.get("/share").json()
    assert [s["token"] for s in listed] == [token]
    assert listed[0]["path"] == "chat/c1"

    assert client.delete(f"/share/{token}").status_code == 200
    assert client.get("/share").json() == []
    # Revoke is real — token stops resolving.
    assert client.get(f"/share/user_test/{token}/data").status_code == 403


def test_share_router_file_share(tmp_path):
    """File shares: /data returns metadata pointing at /file/<path>; /file/<path> serves bytes."""
    from cycls.app.db import workspace

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    ws.root.mkdir(parents=True, exist_ok=True)
    (ws.root / "doc.md").write_text("hello world")

    body = client.post("/share", json={"path": "file/doc.md"}).json()
    meta = client.get(f"/share/user_test/{body['token']}/data").json()
    assert meta["type"] == "file"
    assert meta["path"] == "doc.md"
    r = client.get(meta["url"])
    assert r.status_code == 200
    assert r.content == b"hello world"


def test_validator_rejects_query_token(tmp_path):
    """Regression: `?token=` in the query MUST NOT authenticate (Codespace proxy
    can inject stray Bearers; URL tokens leak via logs/Referer). Bearer header only."""
    from cycls.app.auth import JWT, validator
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    validate = validator(JWT("https://example.invalid/jwks"), prod=True)
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



# =============================================================================
# Web router path-guard tests (state files / resolve_path)
# =============================================================================

from cycls.agent.web.routers import resolve_path


def test_state_resolve_path_rejects_cycls(tmp_path):
    (tmp_path / ".db").mkdir()
    with pytest.raises(ValueError, match="Reserved path"):
        resolve_path(tmp_path, ".db")
    with pytest.raises(ValueError, match="Reserved path"):
        resolve_path(tmp_path, ".db/usage.json")


def test_state_resolve_path_rejects_cycls_nested(tmp_path):
    (tmp_path / ".db" / "sub").mkdir(parents=True)
    with pytest.raises(ValueError, match="Reserved path"):
        resolve_path(tmp_path, ".db/sub/file.json")


def test_state_resolve_path_allows_normal(tmp_path):
    out = resolve_path(tmp_path, "notes.md")
    assert out == (tmp_path / "notes.md").resolve()


# =============================================================================
# Multi-workspace mode (docs/workspaces.md)
# =============================================================================

from cycls.agent.web.routers import resolve_ws_id, personal_ws


def _resolve(user, header, mode, tmp_path):
    return asyncio.run(resolve_ws_id(user, header, mode, tmp_path, f"file://{tmp_path}"))


def test_resolve_ws_id_legacy_mode_ignores_header(tmp_path):
    from cycls.app.auth import User
    user = User(id="user_1", org_id="org_1")
    assert _resolve(user, None, None, tmp_path) is None
    assert _resolve(user, "u-user_1", None, tmp_path) is None      # mode off → header ignored
    assert _resolve(None, None, "member", tmp_path) is None        # no user → legacy


def test_resolve_ws_id_defaults_to_personal(tmp_path):
    from cycls.app.auth import User
    user = User(id="user_1", org_id="org_1")
    assert _resolve(user, None, "member", tmp_path) == "u-user_1"
    assert _resolve(user, "", "member", tmp_path) == "u-user_1"
    assert _resolve(user, "u-user_1", "member", tmp_path) == "u-user_1"


def test_resolve_ws_id_foreign_ids_404(tmp_path):
    from fastapi import HTTPException
    from cycls.app.auth import User
    user = User(id="user_1", org_id="org_1")
    for header in ("u-user_2", "t-unknown", "../evil", "garbage"):
        with pytest.raises(HTTPException) as exc:
            _resolve(user, header, "member", tmp_path)
        assert exc.value.status_code == 404


def test_personal_ws_from_subject():
    assert personal_ws("org_1:user_1") == "u-user_1"
    assert personal_ws("user_1") == "u-user_1"


def _ws_routers_client(tmp_path, workspaces="member"):
    """Mount the real state routers behind a stub app + fixed user."""
    from types import SimpleNamespace
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls.app.auth import User
    from cycls.agent.web.routers import install_routers

    user = User(id="user_1", org_id="org_1")
    stub = SimpleNamespace(prod=False, _auth_provider=None,
                           config=SimpleNamespace(workspaces=workspaces, max_upload=512))
    fapp = FastAPI()
    install_routers(stub, fapp, Depends(lambda: user), tmp_path, f"file://{tmp_path}")
    return TestClient(fapp)


def test_ws_mode_chats_land_in_personal_workspace(tmp_path):
    client = _ws_routers_client(tmp_path)
    r = client.put("/chats/c1", json={"title": "hello"})
    assert r.status_code == 200
    index = tmp_path / "org_1" / "ws" / "u-user_1" / ".db" / "user_1" / "chat" / "c1" / "index.json"
    assert index.exists()
    # explicit personal header hits the same store
    r = client.get("/chats", headers={"X-Workspace": "u-user_1"})
    assert [c["id"] for c in r.json()] == ["c1"]


def test_ws_mode_foreign_workspace_is_404(tmp_path):
    client = _ws_routers_client(tmp_path)
    for header in ("u-user_2", "t-team1"):
        assert client.get("/chats", headers={"X-Workspace": header}).status_code == 404


def test_ws_mode_files_land_in_personal_workspace(tmp_path):
    client = _ws_routers_client(tmp_path)
    r = client.put("/files/notes.txt", files={"file": ("notes.txt", b"hi")})
    assert r.status_code == 200
    assert (tmp_path / "org_1" / "ws" / "u-user_1" / "notes.txt").read_bytes() == b"hi"


def test_legacy_mode_files_land_in_org_root(tmp_path):
    client = _ws_routers_client(tmp_path, workspaces=None)
    r = client.put("/files/notes.txt", files={"file": ("notes.txt", b"hi")})
    assert r.status_code == 200
    assert (tmp_path / "org_1" / "notes.txt").read_bytes() == b"hi"


def test_web_builder_workspaces_option():
    from cycls.agent.web import Web
    assert Web()._workspaces is None
    assert Web().workspaces()._workspaces == "member"
    assert Web().workspaces(create="admin")._workspaces == "admin"
    with pytest.raises(ValueError):
        Web().workspaces(create="anyone")


def test_agent_workspaces_requires_auth(tmp_path):
    import cycls

    with pytest.raises(ValueError, match="requires"):
        @cycls.agent(web=cycls.Web().workspaces())
        async def my_agent(context):
            yield "hi"


def test_agent_workspaces_config_wiring():
    import cycls

    @cycls.agent(web=cycls.Web().auth(cycls.Clerk()).workspaces(create="admin"))
    async def my_agent(context):
        yield "hi"

    assert my_agent.config.workspaces == "admin"


# =============================================================================
# Branding / SEO / Explore
# =============================================================================

def _branded_config(public_path=THEME_PATH, **kw):
    from cycls.agent.web.server import PassMetadata
    return Config(
        public_path=public_path, name="super",
        pass_metadata={"en": PassMetadata(name="Super", description="Gets things done", logo="<svg/>")},
        **kw,
    )


def _seo_theme(tmp_path):
    (tmp_path / "index.html").write_text(
        '<html><head><title>__TITLE__</title>'
        '<meta name="description" content="__DESC__" />'
        '<meta property="og:image" content="/og.png" /></head>'
        '<body><div id="root"></div></body></html>')
    return str(tmp_path)


def test_seo_derives_from_brand(tmp_path):
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    client = TestClient(web(dummy_agent, _branded_config(_seo_theme(tmp_path))))
    html = client.get("/").text
    assert "<title>Super</title>" in html
    assert 'content="Gets things done"' in html
    assert "application/ld+json" in html
    assert "<h1>Super</h1>" in html  # crawlable hero before JS runs


def test_seo_overrides_brand(tmp_path):
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    config = _branded_config(_seo_theme(tmp_path), seo={"title": "Super — AI agent", "description": "Custom copy"},
                             head='<meta name="verify" content="x">')
    client = TestClient(web(dummy_agent, config))
    html = client.get("/").text
    assert "<title>Super — AI agent</title>" in html
    assert 'content="Custom copy"' in html
    assert '<meta name="verify" content="x">' in html


def test_explore_static_and_disabled():
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    entries = [{"slug": "coder", "title": "Coder", "link": "https://coder.cycls.ai"}]
    client = TestClient(web(dummy_agent, _branded_config(explore=entries)))
    assert client.get("/explore").json() == {"agents": entries}

    client = TestClient(web(dummy_agent, _branded_config()))
    assert client.get("/explore").json() == {"agents": []}


def test_custom_og_and_favicon_and_llms():
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    config = _branded_config(favicon="<svg>fav</svg>")
    config._og_image = b"\x89PNGfake"
    client = TestClient(web(dummy_agent, config))
    assert client.get("/og.png").content == b"\x89PNGfake"
    assert client.get("/favicon.svg").text == "<svg>fav</svg>"
    assert "Gets things done" in client.get("/llms.txt").text
    assert "Sitemap:" in client.get("/robots.txt").text


def test_theme_colors_injected(tmp_path):
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    config = _branded_config(_seo_theme(tmp_path),
                             colors={"primary": "#7c3aed", "secondary": "#f3e8ff", "primary_dark": "#a78bfa"})
    html = TestClient(web(dummy_agent, config)).get("/").text
    assert ":root{--color-accent:#7c3aed;--color-secondary:#f3e8ff;}" in html
    assert ".dark{--color-accent:#a78bfa;--color-secondary:#f3e8ff;}" in html


def test_web_builder_brand_and_explore():
    from cycls.agent.web.builder import Web

    w = (Web().brand(name="Super", description="d", logo="<svg/>")
              .brand(locale="ar", name="سوبر")
              .explore({"name": "Coder", "url": "https://c.ai"})
              .cms(brand="https://cms.x/agents/super", token="t"))
    assert w._brand["en"]["name"] == "Super" and w._brand["ar"]["name"] == "سوبر"
    assert w._explore[0]["title"] == "Coder" and w._explore[0]["link"] == "https://c.ai"
    assert w._cms == {"brand": "https://cms.x/agents/super", "token": "t"}

    import pytest as _pytest
    with _pytest.raises(ValueError):
        Web().brand(logo="missing/logo.svg")

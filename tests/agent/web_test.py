import pytest
import json
import asyncio
import os
import importlib.resources
from cycls._agent.web import web, Config, Messages, sse, encoder, openai_encoder

# To run these tests:
# poetry run pytest tests/web_test.py -v -s

# Use actual default theme
THEME_PATH = str(importlib.resources.files('cycls').joinpath('_agent/web/themes/dev'))


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
    assert "cms" not in data
    print("✅ Test passed.")


def test_cms_brand_merges_piece_by_piece(monkeypatch):
    """Static .brand() wins piece by piece; the CMS fills what's unset — a
    static name/description must not skip the fetch and lose the CMS icon."""
    from cycls._agent.web.server import PassMetadata

    class _Resp:
        status_code = 200
        def json(self):
            return {"title": "Super", "title_ar": "سوبر",
                    "description": "cms desc", "description_ar": "cms desc ar",
                    "icon_svg": "<svg id='cms-icon'/>"}
    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp())

    async def dummy_agent(context):
        yield "test"

    config = Config(public_path=THEME_PATH, auth=False,
                    cms={"brand": "https://cms.example/agents/super"},
                    pass_metadata={"en": PassMetadata(name="Super New", description="testbed")})
    web(dummy_agent, config)

    en, ar = config.pass_metadata["en"], config.pass_metadata["ar"]
    assert en.name == "Super New"                 # static wins
    assert en.description == "testbed"            # static wins
    assert en.logo == "<svg id='cms-icon'/>"      # CMS fills the icon
    assert ar.name == "سوبر"                      # CMS fills the missing locale
    assert ar.logo == "<svg id='cms-icon'/>"


def test_cms_brand_fetch_failure_keeps_static(monkeypatch):
    """A dead CMS must not clobber static branding."""
    from cycls._agent.web.server import PassMetadata

    def boom(*a, **k): raise OSError("down")
    monkeypatch.setattr("httpx.get", boom)

    async def dummy_agent(context):
        yield "test"

    config = Config(public_path=THEME_PATH, auth=False,
                    cms={"brand": "https://cms.example/agents/super"},
                    pass_metadata={"en": PassMetadata(name="Super New")})
    web(dummy_agent, config)
    assert config.pass_metadata == {"en": PassMetadata(name="Super New")}


def test_config_keeps_secrets_server_side():
    """cms (bearer token) and volume never reach /config or the page HTML."""
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    config = Config(public_path=THEME_PATH, auth=False,
                    cms={"explore": "https://cms.example/agents", "token": "sekrit-bearer"},
                    volume="/internal/mount")
    client = TestClient(web(dummy_agent, config))

    data = client.get("/config").json()
    assert "cms" not in data
    assert "volume" not in data

    html = client.get("/").text
    assert "sekrit-bearer" not in html
    assert "/internal/mount" not in html
    assert "window.__CONFIG__" in html


def test_embedded_json_cannot_close_script_tag(tmp_path):
    """CMS/SEO text containing </script> must not break out of the inline JSON."""
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    config = Config(public_path=THEME_PATH, auth=False,
                    seo={"title": "T", "description": 'x</script><script>alert(1)</script>'})
    client = TestClient(web(dummy_agent, config))
    html = client.get("/").text
    assert "<script>alert(1)</script>" not in html


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
    from cycls._app.auth import User
    from cycls._app.db import workspace
    from cycls._agent.web.routers import share_router
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
    from cycls._agent import state as chat
    from cycls._app.db import workspace
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
    # 404, not 403: no such row. 403 is reserved for "exists, not yours".
    assert client.get("/share/user_test/bogus_token/data").status_code == 404


def test_org_share_401_when_anonymous_403_when_wrong_org(tmp_path):
    """An org-scoped share separates 'we don't know you' from 'not for you' —
    401 is recoverable by signing in, 403 never is. Collapsing both into 403
    is what left viewers staring at a dead link with no way forward."""
    from cycls._agent import state as chat
    from cycls._app.db import workspace
    import asyncio

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    asyncio.run(chat.put_meta(ws, "c1", {"id": "c1", "title": "T"}))
    token = client.post("/share", json={"path": "chat/c1",
                                        "audience": "org:org_acme"}).json()["token"]

    # Anonymous: no bearer at all → sign in.
    assert client.get(f"/share/user_test/{token}/data").status_code == 401

    # Authenticated but in another org → never allowed, no prompt.
    from cycls._app.auth import User
    import cycls._agent.state as state
    assert state.share_allows({"audience": "org:org_acme"}, User(id="u", org_id="org_other")) is False
    assert state.share_allows({"audience": "org:org_acme"}, User(id="u", org_id="org_acme")) is True
    assert state.share_allows({"audience": "public"}, None) is True


def test_share_router_unknown_chat_404(tmp_path):
    svc, user, client = _share_test_app(tmp_path)
    r = client.post("/share", json={"path": "chat/missing"})
    assert r.status_code == 404


def test_share_router_list_and_delete(tmp_path):
    from cycls._agent import state as chat
    from cycls._app.db import workspace
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
    # Revoke is real — the row is gone, so the link reads as nonexistent.
    assert client.get(f"/share/user_test/{token}/data").status_code == 404


def test_share_router_file_share(tmp_path):
    """File shares: /data returns metadata pointing at /file/<path>; /file/<path> serves bytes."""
    from cycls._app.db import workspace

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
    assert r.headers["cache-control"] == "no-cache"


def _seed_canvas_chat(ws, chat_id="c1", title="Site build"):
    """A chat that produced a canvas artifact (site.html), plus one canvas
    call that errored (broken.html) — the shareable surface is only the
    successful one."""
    from cycls._agent import state as chat
    import asyncio

    async def seed():
        await chat.put_meta(ws, chat_id, {"id": chat_id, "title": title})
        await chat.append_messages(ws, chat_id, [
            {"role": "user", "content": "make a site"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "canvas", "input": {"path": "site.html"}},
                {"type": "tool_use", "id": "t2", "name": "canvas", "input": {"path": "broken.html"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "opened"},
                {"type": "tool_result", "tool_use_id": "t2", "content": "Error: no such file", "is_error": True},
            ]},
            {"role": "assistant", "content": "done"},
        ], 0)
    asyncio.run(seed())
    ws.root.mkdir(parents=True, exist_ok=True)
    (ws.root / "site.html").write_text("<h1>site</h1>")
    (ws.root / "broken.html").write_text("half-written")
    (ws.root / "secret.txt").write_text("not shared")


def test_chat_share_serves_canvas_files(tmp_path):
    """A chat share's file route covers the canvas artifacts the conversation
    produced — the shared page shows the chat WITH its output on one token.
    Errored canvas calls and unrelated workspace files stay off-limits."""
    from cycls._app.db import workspace

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    _seed_canvas_chat(ws)

    token = client.post("/share", json={"path": "chat/c1"}).json()["token"]
    r = client.get(f"/share/user_test/{token}/file/site.html")
    assert r.status_code == 200 and r.content == b"<h1>site</h1>"
    assert client.get(f"/share/user_test/{token}/file/broken.html").status_code == 403
    assert client.get(f"/share/user_test/{token}/file/secret.txt").status_code == 403


def test_examples_resolves_cards(tmp_path):
    """/examples turns configured share URLs into gallery cards — title,
    first prompt, final artifact — with author fields stripped and dead
    tokens skipped."""
    from types import SimpleNamespace
    from cycls._app.db import workspace

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    _seed_canvas_chat(ws)

    url = client.post("/share", json={"path": "chat/c1", "author_name": "Alice"}).json()["url"]
    svc.config = SimpleNamespace(examples=[
        {"label": "Sites", "label_ar": "مواقع", "urls": [url, "/shared/user_test/dead_token"]}])

    data = client.get("/examples").json()
    assert [c["label"] for c in data["categories"]] == ["Sites"]
    assert data["categories"][0]["label_ar"] == "مواقع"
    (item,) = data["categories"][0]["items"]
    assert item["title"] == "Site build"
    assert item["prompt"] == "make a site"
    assert item["file"]["path"] == "site.html"
    assert "author_name" not in item
    assert item["share"].endswith("example=1")
    # The card's pieces are live: the file URL serves and the share resolves.
    assert client.get(item["file"]["url"]).status_code == 200
    assert client.get(item["share"].replace("/shared/", "/share/").split("?")[0] + "/data").status_code == 200


def test_examples_empty_without_config(tmp_path):
    svc, user, client = _share_test_app(tmp_path)
    assert client.get("/examples").json() == {"categories": []}


def test_examples_builder_normalizes_labels():
    """String keys are the label for both locales; a (en, ar) tuple key gives
    the pill an Arabic label, mirroring explore's title/title_ar."""
    import cycls
    w = cycls.Web().examples({"A": ["u1"], ("B", "ب"): ["u2"]})
    assert w._examples == [{"label": "A", "label_ar": None, "urls": ["u1"]},
                           {"label": "B", "label_ar": "ب", "urls": ["u2"]}]
    assert cycls.Web().examples(["u"])._examples == [{"label": "", "label_ar": None, "urls": ["u"]}]


def test_examples_skips_non_public_shares(tmp_path):
    """Org-scoped shares never leak through the public gallery."""
    from types import SimpleNamespace
    from cycls._app.db import workspace

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    _seed_canvas_chat(ws)

    url = client.post("/share", json={"path": "chat/c1", "audience": "org:org_acme"}).json()["url"]
    svc.config = SimpleNamespace(examples=[{"label": "Sites", "urls": [url]}])
    assert client.get("/examples").json() == {"categories": []}


def test_validator_rejects_query_token(tmp_path):
    """Regression: `?token=` in the query MUST NOT authenticate (Codespace proxy
    can inject stray Bearers; URL tokens leak via logs/Referer). Bearer header only."""
    from cycls._app.auth import JWT, validator
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
    from cycls._app.db import Workspace

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

from cycls._agent.web.routers import resolve_path


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


def test_state_resolve_path_rejects_agent_kv(tmp_path):
    (tmp_path / ".database").mkdir()
    with pytest.raises(ValueError, match="Reserved path"):
        resolve_path(tmp_path, ".database")
    with pytest.raises(ValueError, match="Reserved path"):
        resolve_path(tmp_path, ".database/store.json")


def test_state_resolve_path_allows_normal(tmp_path):
    out = resolve_path(tmp_path, "notes.md")
    assert out == (tmp_path / "notes.md").resolve()


# =============================================================================
# Multi-workspace mode (docs/workspaces.md)
# =============================================================================

from cycls._agent.web.routers import resolve_ws_id, personal_ws


def _resolve(user, header, mode, tmp_path):
    return asyncio.run(resolve_ws_id(user, header, mode, tmp_path, f"file://{tmp_path}"))


def test_resolve_ws_id_legacy_mode_ignores_header(tmp_path):
    from cycls._app.auth import User
    user = User(id="user_1", org_id="org_1")
    assert _resolve(user, None, None, tmp_path) is None
    assert _resolve(user, "u-user_1", None, tmp_path) is None      # mode off → header ignored
    assert _resolve(None, None, "member", tmp_path) is None        # no user → legacy


def test_resolve_ws_id_defaults_to_personal(tmp_path):
    from cycls._app.auth import User
    user = User(id="user_1", org_id="org_1")
    assert _resolve(user, None, "member", tmp_path) == "u-user_1"
    assert _resolve(user, "", "member", tmp_path) == "u-user_1"
    assert _resolve(user, "u-user_1", "member", tmp_path) == "u-user_1"


def test_resolve_ws_id_foreign_ids_404(tmp_path):
    from fastapi import HTTPException
    from cycls._app.auth import User
    user = User(id="user_1", org_id="org_1")
    for header in ("u-user_2", "t-unknown", "../evil", "garbage"):
        with pytest.raises(HTTPException) as exc:
            _resolve(user, header, "member", tmp_path)
        assert exc.value.status_code == 404


def test_personal_ws_from_subject():
    assert personal_ws("org_1:user_1") == "u-user_1"
    assert personal_ws("user_1") == "u-user_1"


def _ws_routers_client(tmp_path, workspaces="member", max_upload=512):
    """Mount the real state routers behind a stub app + fixed user."""
    from types import SimpleNamespace
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls._app.auth import User
    from cycls._agent.web.routers import install_routers

    user = User(id="user_1", org_id="org_1")
    stub = SimpleNamespace(prod=False, _auth_provider=None,
                           config=SimpleNamespace(workspaces=workspaces, max_upload=max_upload))
    fapp = FastAPI()
    install_routers(stub, fapp, Depends(lambda: user), tmp_path, f"file://{tmp_path}")
    return TestClient(fapp)


def _zip_bytes(members):
    """{name: bytes} → in-memory zip."""
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_file_get_forces_revalidation(tmp_path):
    """Every file GET carries no-cache: FileResponse alone has no Cache-Control,
    so browsers/iOS apply heuristic freshness off Last-Modified and previews
    show stale bytes after a write (downloads escaped only because ?download is
    a different cache key)."""
    client = _ws_routers_client(tmp_path)
    client.put("/files/docs/doc.txt", content=b"v1")
    for url in ("/files/docs/doc.txt", "/files/docs/doc.txt?download", "/files/docs"):
        r = client.get(url)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache"


def test_raw_body_upload_streams_to_disk(tmp_path):
    """Raw (non-multipart) PUT: body streams to the target; content preserved."""
    client = _ws_routers_client(tmp_path)
    r = client.put("/files/docs/big.bin", content=b"\x00\x01" * 1000)
    assert r.status_code == 200
    dest = tmp_path / "org_1" / "ws" / "u-user_1" / "docs" / "big.bin"
    assert dest.read_bytes() == b"\x00\x01" * 1000
    assert not dest.with_name("big.bin.part").exists()


def test_raw_body_upload_over_cap_413(tmp_path):
    client = _ws_routers_client(tmp_path, max_upload=1)
    r = client.put("/files/big.bin", content=b"\0" * (1024 * 1024 + 1))
    assert r.status_code == 413
    assert not list(tmp_path.glob("**/big.bin*"))   # no .part left behind


def test_multipart_upload_missing_field_400(tmp_path):
    client = _ws_routers_client(tmp_path)
    r = client.put("/files/x.txt", files={"wrong": ("x.txt", b"hi")})
    assert r.status_code == 400


def test_batch_upload_extracts_zip(tmp_path):
    client = _ws_routers_client(tmp_path)
    body = _zip_bytes({"a.txt": b"aaa", "sub/deep/b.txt": b"bbb", "ملف.txt": "عربي".encode()})
    r = client.post("/files-batch/docs", content=body)
    assert r.status_code == 200
    assert r.json()["files"] == 3
    root = tmp_path / "org_1" / "ws" / "u-user_1" / "docs"
    assert (root / "a.txt").read_bytes() == b"aaa"
    assert (root / "sub" / "deep" / "b.txt").read_bytes() == b"bbb"
    assert (root / "ملف.txt").read_text() == "عربي"


def test_batch_upload_rejects_traversal_member(tmp_path):
    """One hostile member poisons the whole batch — nothing gets written."""
    client = _ws_routers_client(tmp_path)
    body = _zip_bytes({"ok.txt": b"fine", "../evil.txt": b"nope"})
    r = client.post("/files-batch/", content=body)
    assert r.status_code == 403
    ws_root = tmp_path / "org_1" / "ws" / "u-user_1"
    assert not (ws_root / "ok.txt").exists()          # validated before any write
    assert not list(tmp_path.glob("**/evil.txt"))


def test_batch_upload_rejects_reserved_and_non_zip(tmp_path):
    client = _ws_routers_client(tmp_path)
    r = client.post("/files-batch/", content=_zip_bytes({".db/kv.json": b"x"}))
    assert r.status_code == 403
    assert client.post("/files-batch/", content=b"not a zip").status_code == 400


def test_batch_upload_zip_bomb_413(tmp_path):
    """Uncompressed total obeys the cap even when the compressed body is tiny."""
    client = _ws_routers_client(tmp_path, max_upload=1)
    body = _zip_bytes({"bomb.txt": b"\0" * (2 * 1024 * 1024)})   # 2MB → ~2KB zipped
    assert len(body) < 1024 * 1024
    r = client.post("/files-batch/", content=body)
    assert r.status_code == 413
    assert not list(tmp_path.glob("**/bomb.txt"))


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
    from cycls._agent.web import Web
    assert Web()._workspaces is None
    assert Web().workspaces()._workspaces == "member"
    assert Web().workspaces(create="admin")._workspaces == "admin"
    with pytest.raises(ValueError):
        Web().workspaces(create="anyone")


def test_agent_workspaces_requires_auth(tmp_path):
    import cycls

    with pytest.raises(ValueError, match="requires"):
        @cycls.agent(web=cycls.Web().workspaces(),
                     volumes={"/workspace": cycls.Volume("test-chats")})
        async def my_agent(context):
            yield "hi"


def test_agent_workspaces_config_wiring():
    import cycls

    @cycls.agent(web=cycls.Web().auth(cycls.Clerk()).workspaces(create="admin"),
                 volumes={"/workspace": cycls.Volume("test-chats")})
    async def my_agent(context):
        yield "hi"

    assert my_agent.config.workspaces == "admin"


# =============================================================================
# Branding / SEO / Explore
# =============================================================================

def _branded_config(public_path=THEME_PATH, **kw):
    from cycls._agent.web.server import PassMetadata
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
    assert "<h1>" not in html  # no server-rendered body — nothing to flash before React mounts


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
    from cycls._agent.web.builder import Web

    w = (Web().brand(name="Super", description="d", logo="<svg>icon</svg>", brand="<svg>nav</svg>")
              .brand(locale="ar", name="سوبر")
              .explore({"name": "Coder", "url": "https://c.ai"})
              .cms(brand="https://cms.x/agents/super", token="t"))
    assert w._brand["en"]["name"] == "Super" and w._brand["ar"]["name"] == "سوبر"
    # logo (agent icon) and brand (nav wordmark) are distinct per-locale fields
    assert w._brand["en"]["logo"] == "<svg>icon</svg>"
    assert w._brand["en"]["brand"] == "<svg>nav</svg>"
    assert w._explore[0]["title"] == "Coder" and w._explore[0]["link"] == "https://c.ai"
    assert w._cms == {"brand": "https://cms.x/agents/super", "token": "t"}

    with pytest.raises(ValueError):
        Web().brand(logo="missing/logo.svg")


# ---- Files: catalog cache, @-search, kind, sort ----

def _seed(tmp_path, tree):
    """{relpath: bytes} → files under the fixed test workspace root."""
    root = tmp_path / "org_1" / "ws" / "u-user_1"
    for rel, data in tree.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def test_search_matches_tokens_in_any_order(tmp_path):
    """A filename with spaces is findable by fragments typed in any order —
    the whole point of allowing spaces in the @ query."""
    _seed(tmp_path, {"docs/سياسات التحول الرقمي.docx": b"x", "docs/other.txt": b"y"})
    client = _ws_routers_client(tmp_path)

    hits = client.get("/files", params={"recursive": 1, "search": "سياسات الرقمي"}).json()
    assert [h["name"] for h in hits] == ["سياسات التحول الرقمي.docx"]

    # first token alone still works, and a trailing space is a no-op
    assert client.get("/files", params={"search": "سياسات "}).json()[0]["name"].startswith("سياسات")


def test_search_is_files_only_and_capped(tmp_path):
    _seed(tmp_path, {f"notes/note-{i}.md": b"x" for i in range(20)})
    client = _ws_routers_client(tmp_path)
    hits = client.get("/files", params={"search": "note"}).json()
    assert len(hits) == 12                                  # _SEARCH_CAP
    assert all(h["type"] == "file" for h in hits)           # a mention resolves to a file
    # A bare "@" sends a blank query and must browse, not come back empty — an
    # empty result there latches the picker shut for the rest of the session.
    assert len(client.get("/files", params={"search": ""}).json()) == 12
    assert len(client.get("/files", params={"search": "   "}).json()) == 12


def test_search_ranks_name_matches_over_folder_matches(tmp_path):
    _seed(tmp_path, {"report/a.txt": b"x", "misc/report.txt": b"y"})
    client = _ws_routers_client(tmp_path)
    hits = client.get("/files", params={"search": "report"}).json()
    assert hits[0]["path"] == "misc/report.txt"     # hit in the filename beats hit in the folder


def test_kind_classifies_the_union_of_both_clients(tmp_path):
    """heic used to preview on mobile and not on web, because each client kept
    its own extension table. One table now, server-side."""
    _seed(tmp_path, {"a.heic": b"x", "b.xlsx": b"x", "c.mp3": b"x",
                     "d.glb": b"x", "e.py": b"x", "f.zip": b"x", "g.csv": b"x"})
    client = _ws_routers_client(tmp_path)
    kinds = {e["name"]: e["kind"] for e in client.get("/files").json()}
    # csv is split from sheet: mobile renders delimited text but not a binary workbook
    assert kinds == {"a.heic": "image", "b.xlsx": "sheet", "c.mp3": "audio",
                     "d.glb": "model3d", "e.py": "code", "f.zip": "opaque",
                     "g.csv": "csv"}


def test_listing_sorts_folders_first_and_honours_sort_key(tmp_path):
    root = _seed(tmp_path, {"big.txt": b"x" * 100, "small.txt": b"x"})
    (root / "zzz-folder").mkdir()
    client = _ws_routers_client(tmp_path)

    by_name = client.get("/files").json()
    assert [e["name"] for e in by_name] == ["zzz-folder", "big.txt", "small.txt"]

    by_size = client.get("/files", params={"sort": "size", "desc": 1}).json()
    assert [e["name"] for e in by_size if e["type"] == "file"] == ["big.txt", "small.txt"]
    assert by_size[0]["name"] == "zzz-folder"      # desc never floats files above folders

    # an unknown sort key falls back to name rather than erroring
    assert client.get("/files", params={"sort": "nonsense"}).json() == by_name


def test_folder_time_comes_from_newest_child_without_rescanning(tmp_path):
    """Folder mtime is derived from the walk that already visited the folder."""
    root = _seed(tmp_path, {"docs/old.txt": b"x", "docs/new.txt": b"y"})
    os.utime(root / "docs" / "old.txt", (1_600_000_000, 1_600_000_000))
    os.utime(root / "docs" / "new.txt", (1_700_000_000, 1_700_000_000))
    client = _ws_routers_client(tmp_path)
    docs = next(e for e in client.get("/files").json() if e["name"] == "docs")
    assert docs["modified"].startswith("2023-11-14")     # 1_700_000_000 UTC
    assert docs["size"] == 0


def test_write_routes_invalidate_the_catalog(tmp_path):
    """An upload is visible on the next listing, not after the TTL."""
    _seed(tmp_path, {"a.txt": b"x"})
    client = _ws_routers_client(tmp_path)
    assert [e["name"] for e in client.get("/files").json()] == ["a.txt"]

    client.put("/files/b.txt", content=b"y")
    assert [e["name"] for e in client.get("/files").json()] == ["a.txt", "b.txt"]

    client.post("/files/sub")
    assert "sub" in [e["name"] for e in client.get("/files").json()]

    client.delete("/files/a.txt")
    assert "a.txt" not in [e["name"] for e in client.get("/files").json()]


def test_fresh_bypasses_a_warm_cache(tmp_path):
    """Writes that never reach these routes — another instance, or the agent's
    sandbox — are invisible until the TTL, so clients can force a walk."""
    from cycls._agent.web import routers

    root = _seed(tmp_path, {"a.txt": b"x"})
    client = _ws_routers_client(tmp_path)
    client.get("/files")                                  # warm it

    (root / "agent-made.txt").write_bytes(b"z")            # bypasses the write routes
    assert "agent-made.txt" not in [e["name"] for e in client.get("/files").json()]

    fresh = client.get("/files", params={"fresh": 1}).json()
    assert "agent-made.txt" in [e["name"] for e in fresh]


def test_catalog_is_bounded_per_instance(tmp_path):
    """One serverless instance serves many workspaces; the cache must not grow
    without bound across them."""
    from cycls._agent.web import routers

    async def warm_many():
        for i in range(routers._CATALOG_WORKSPACES + 4):
            root = tmp_path / f"ws{i}"
            root.mkdir()
            await routers._catalog_get(root)

    routers._catalog.clear()
    asyncio.run(warm_many())
    assert len(routers._catalog) <= routers._CATALOG_WORKSPACES


def test_concurrent_misses_share_one_walk(tmp_path):
    """The stampede this cache exists to stop is a burst of requests for the
    same tree, so arriving mid-walk must join it rather than start another."""
    from cycls._agent.web import routers

    root = _seed(tmp_path, {"a.txt": b"x"})
    walks = 0
    real = routers._walk_catalog

    def counting(r):
        nonlocal walks
        walks += 1
        return real(r)

    async def race():
        return await asyncio.gather(*(routers._catalog_get(root) for _ in range(8)))

    routers._catalog.clear()
    routers._walk_catalog = counting
    try:
        results = asyncio.run(race())
    finally:
        routers._walk_catalog = real
    assert walks == 1
    assert all(r[0] == results[0][0] for r in results)


def test_failed_walk_is_not_cached(tmp_path):
    """A cached exception would keep failing for the rest of the TTL."""
    from cycls._agent.web import routers

    root = _seed(tmp_path, {"a.txt": b"x"})
    real = routers._walk_catalog
    routers._catalog.clear()
    routers._walk_catalog = lambda r: (_ for _ in ()).throw(OSError("mount gone"))
    try:
        with pytest.raises(OSError):
            asyncio.run(routers._catalog_get(root))
        assert str(root) not in routers._catalog
    finally:
        routers._walk_catalog = real


def test_recursive_and_search_stay_scoped_to_path(tmp_path):
    """?path= scopes the flat listing and the search, as it did before the
    catalog — the tree is cached from the root either way."""
    _seed(tmp_path, {"a/keep.txt": b"x", "b/skip.txt": b"y"})
    client = _ws_routers_client(tmp_path)

    flat = client.get("/files", params={"recursive": 1, "path": "a"}).json()
    assert [e["path"] for e in flat] == ["a/keep.txt"]

    hits = client.get("/files", params={"search": "txt", "path": "a"}).json()
    assert [e["path"] for e in hits] == ["a/keep.txt"]

    assert len(client.get("/files", params={"search": "txt"}).json()) == 2

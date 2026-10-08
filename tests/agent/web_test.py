import pytest
import base64
import json
import asyncio
import os
import time
import importlib.resources
from cycls._agent.web import web, Config, Messages, sse, encoder, openai_encoder

# To run these tests:
# poetry run pytest tests/web_test.py -v -s

# Use actual default theme
THEME_PATH = str(importlib.resources.files('cycls').joinpath('_agent/web/themes/dev'))


# =============================================================================
# Messages Class Tests
# =============================================================================

def test_stopping_a_finished_run_answers_202_not_404(tmp_path, monkeypatch):
    """A person can press Stop in the ~2s poll window after a run ends — seen in
    production, 466ms after the record said done, surfacing as an HTTP error.
    A terminal record means there is nothing to do, not that something broke.
    A chat with no record at all is still a real 404."""
    import asyncio
    from fastapi.testclient import TestClient
    from cycls._app.auth import User
    from cycls._app.db import workspace
    from cycls._agent import state
    import cycls._agent.web.server as server

    user = User(id="user_test")
    monkeypatch.setattr(server, "validator", lambda *a, **k: (lambda: user))

    async def dummy_agent(context):
        yield "hi"

    # storage is derived: file://{volume} when not prod
    config = Config(public_path=THEME_PATH, auth=True, plan="free", volume=str(tmp_path))
    client = TestClient(server.web(dummy_agent, config))

    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    asyncio.run(state.put_run(ws, "finished", {"status": "done", "run": "r1",
                                               "heartbeat": "2026-01-01T00:00:00+00:00"}))

    r = client.post("/chats/finished/stop")
    assert r.status_code == 202, r.text
    assert r.json()["stopping"] is False and r.json()["status"] == "done"

    assert client.post("/chats/never-ran/stop").status_code == 404


def test_a_handled_stream_error_is_a_failed_run():
    """The encoder turns an exception into a callout so the stream stays
    well-formed. Without a flag the task then ends clean and the run records
    `done` — and a finished-run hook announces a turn that actually raised."""
    import asyncio
    from cycls._agent.web.server import Run, encoder

    async def boom():
        yield {"type": "text", "text": "partial"}
        raise RuntimeError("provider went away")

    run = Run(detach=False, chat_id="c1")

    async def go():
        out = [chunk async for chunk in encoder(boom(), chat_id="c1", run=run)]
        return out

    out = asyncio.run(go())
    assert any("[DONE]" in c for c in out), "stream must still terminate cleanly"
    assert any("callout" in c for c in out), "the person must still see the error"
    assert run.failed is True, "a handled error must still mark the run failed"


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


def test_shared_office_file_previews_as_pdf(tmp_path, monkeypatch):
    """A shared Office file previews as PDF over the share transport (?as=pdf,
    read-only); without it, the raw bytes still download."""
    from cycls._app.db import workspace
    from cycls._agent.web import office

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    ws.root.mkdir(parents=True, exist_ok=True)
    (ws.root / "deck.pptx").write_bytes(b"raw-pptx")

    async def fake(data, name, user_id=None):
        return b"%PDF-shared"
    monkeypatch.setattr(office, "to_pdf", fake)

    body = client.post("/share", json={"path": "file/deck.pptx"}).json()
    url = client.get(f"/share/user_test/{body['token']}/data").json()["url"]

    pdf = client.get(url, params={"as": "pdf"})
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content == b"%PDF-shared"

    raw = client.get(url)                       # no ?as=pdf → the original bytes (download)
    assert raw.status_code == 200 and raw.content == b"raw-pptx"


def test_a_shared_design_shows_as_its_picture(tmp_path, monkeypatch):
    """The shared page of a .fig said "Preview isn't available": a visitor has no editor.
    Over the share transport it gets the design's slide manifest (?as=slides) and its
    first frame as a PNG (?as=png) — rendered on demand, for the share's file only."""
    from cycls._app.db import workspace
    from cycls._agent import design

    svc, user, client = _share_test_app(tmp_path)
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}")
    (ws.root / "designs").mkdir(parents=True, exist_ok=True)
    (ws.root / "designs" / "launch.fig").write_bytes(b"FIG")
    (ws.root / "designs" / "other.fig").write_bytes(b"OTHER")

    async def slides(fig, scale=1, fmt="jpg", user_id=None, page=None):
        return {"images": [b"\xff\xd8one"], "sizes": [[1080, 1080]], "format": "jpg", "meta": [{"name": "slide-1"}]}

    async def export(fig, fmt="png", scale=2, width=None, user_id=None, every=False, page=None):
        return b"PNG:" + fig + (f":{page}".encode() if page else b"")
    monkeypatch.setattr(design, "slides", slides)
    monkeypatch.setattr(design, "export", export)

    body = client.post("/share", json={"path": "file/designs/launch.fig"}).json()
    url = client.get(f"/share/user_test/{body['token']}/data").json()["url"]
    shown = client.get(url, params={"as": "slides"})
    assert shown.status_code == 200 and shown.json()["count"] == 1
    assert shown.json()["slides"][0].startswith("data:image/jpeg;base64,")
    png = client.get(url, params={"as": "png"})
    assert png.content == b"PNG:FIG" and 'filename="launch.png"' in png.headers["content-disposition"]
    assert client.get(url, params={"as": "png", "page": "Story"}).content == b"PNG:FIG:Story"   # a visitor sees any page
    assert client.get(url).content == b"FIG"                                  # the design itself still downloads
    other = url.replace("launch.fig", "other.fig")
    assert client.get(other, params={"as": "slides"}).status_code == 403      # the share is of one file


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
    assert "video" not in data["categories"][0]["items"][0]
    (item,) = data["categories"][0]["items"]
    assert item["title"] == "Site build"
    assert item["prompt"] == "make a site"
    assert item["file"]["path"] == "site.html"
    assert "author_name" not in item
    assert item["share"].endswith("example=1")
    # The card's pieces are live: the file URL serves and the share resolves.
    assert client.get(item["file"]["url"]).status_code == 200
    assert client.get(item["share"].replace("/shared/", "/share/").split("?")[0] + "/data").status_code == 200


def test_examples_video_entry_is_a_tutorial_card(tmp_path):
    """A {video, title} entry needs no share resolution — it becomes a
    tutorial card the FE previews and plays in-page (Watch)."""
    from types import SimpleNamespace

    svc, user, client = _share_test_app(tmp_path)
    svc.config = SimpleNamespace(examples=[
        {"label": "Tutorials", "urls": [
            {"video": "https://youtu.be/abc123xyz", "title": "Getting started"}]}])

    (item,) = client.get("/examples").json()["categories"][0]["items"]
    assert item == {"video": "https://youtu.be/abc123xyz", "title": "Getting started"}


def test_first_use_marker_fires_once_per_account(tmp_path):
    """first_agent_use is per account, not per device or per workspace: the
    marker lives in the personal workspace, so a team-workspace first use and
    a later personal one count as one."""
    from cycls._agent import state as chat
    from cycls._app.auth import User
    import asyncio

    user = User(id="user_1", org_id="org_1")
    base = f"file://{tmp_path}"
    assert asyncio.run(chat.mark_first_use(user, tmp_path, base, "member")) is True
    assert asyncio.run(chat.mark_first_use(user, tmp_path, base, "member")) is False
    # legacy (no workspaces) mode: same contract on the single workspace
    solo = User(id="solo")
    assert asyncio.run(chat.mark_first_use(solo, tmp_path, base, None)) is True
    assert asyncio.run(chat.mark_first_use(solo, tmp_path, base, None)) is False


def test_examples_empty_without_config(tmp_path):
    svc, user, client = _share_test_app(tmp_path)
    assert client.get("/examples").json() == {"categories": []}


def test_examples_builder_normalizes_labels():
    """String keys are the label for both locales; a (en, ar) tuple key gives
    the pill an Arabic label, mirroring explore's title/title_ar."""
    import cycls
    w = cycls.Web().examples({"A": ["u1"], ("B", "ب"): ["u2"]})
    assert w._examples == [{"label": "A", "label_ar": None, "urls": [{"share": "u1"}]},
                           {"label": "B", "label_ar": "ب", "urls": [{"share": "u2"}]}]
    assert cycls.Web().examples(["u"])._examples == [{"label": "", "label_ar": None, "urls": [{"share": "u"}]}]
    # Tutorial entries: {"video", "title"} — their own card kind (Watch),
    # no share involved. share+video in one entry is ambiguous → rejected.
    w = cycls.Web().examples({"A": [{"video": "/public/tour.mp4", "title": "Getting started"}]})
    assert w._examples == [{"label": "A", "label_ar": None,
                            "urls": [{"video": "/public/tour.mp4", "title": "Getting started"}]}]
    import pytest
    with pytest.raises(TypeError):
        cycls.Web().examples({"A": [{"share": "u1", "video": "clip.mp4"}]})
    with pytest.raises(TypeError):
        cycls.Web().examples({"A": [{"title": "no url at all"}]})


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

def test_context_carries_the_persons_tool_switches():
    """Settings switches ride the request as disabled_tools; the handler
    keeps only strings, a bounded few, and Context defaults to none."""
    from fastapi.testclient import TestClient

    captured = {}
    async def handler(context):
        captured["off"] = context.disabled_tools
        yield "ok"

    client = TestClient(web(handler, Config(public_path=THEME_PATH, auth=False)))
    client.post("/", json={"messages": [{"role": "user", "content": "hi"}]})
    assert captured["off"] == []
    client.post("/", json={"messages": [{"role": "user", "content": "hi"}],
                           "disabled_tools": ["WebSearch", 7, {"x": 1}]})
    assert captured["off"] == ["WebSearch"]


def test_context_carries_an_attached_design_selection_capped():
    """"Add selection" rides the request: a .fig in the workspace and its nodes by
    name, capped; anything else is no selection."""
    from fastapi.testclient import TestClient

    captured = {}
    async def handler(context):
        captured["sel"] = context.selection
        yield "ok"

    client = TestClient(web(handler, Config(public_path=THEME_PATH, auth=False)))
    send = lambda sel: client.post("/", json={"messages": [{"role": "user", "content": "hi"}], "selection": sel})
    send({"path": "designs/a.fig", "frame": "slide-1",
          "nodes": [{"name": "headline", "type": "TEXT", "text": "x" * 200}, {"type": "RECT"}] + [{"name": "n", "type": "RECT"}] * 30})
    sel = captured["sel"]
    assert sel["path"] == "designs/a.fig" and sel["frame"] == "slide-1"
    assert len(sel["nodes"]) == 19 and len(sel["nodes"][0]["text"]) == 80   # the first 20, less the nameless one; text capped
    for bad in ({"path": "../x.fig", "nodes": [{"name": "a", "type": "T"}]}, {"path": "notes.md", "nodes": [{"name": "a", "type": "T"}]},
                {"path": "designs/a.fig", "nodes": []}, "designs/a.fig", None):
        send(bad)
        assert captured["sel"] is None, bad


def test_an_attached_selection_shows_as_a_chip_not_a_line():
    from cycls._agent.web.routers import to_ui_messages
    sel = {"path": "designs/a.fig", "frame": None, "nodes": [{"name": "headline", "type": "TEXT"}]}
    raw = [{"role": "user", "selection": sel, "content": [
        {"type": "text", "text": "make this bigger"}, {"type": "text", "text": "[Selected in designs/a.fig: headline (TEXT)]"}]}]
    [ui] = to_ui_messages(raw)
    assert ui["content"] == "make this bigger" and ui["selection"] == sel


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


def test_put_schedules_a_design_reexport(tmp_path, monkeypatch):
    """The design editor saves an edited .fig with a PUT — that must schedule the
    re-export of the image beside it (the refresh module filters to designs/*.fig)."""
    from cycls._agent.design import refresh
    seen = []
    monkeypatch.setattr(refresh, "schedule", lambda root, rel, user_id=None, ensure=False: seen.append((rel, user_id)))
    client = _ws_routers_client(tmp_path)
    assert client.put("/files/designs/launch.fig", content=b"FIG").status_code == 200
    assert seen and seen[-1][0] == "designs/launch.fig"


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
    assert (root / "ملف.txt").read_text(encoding="utf-8") == "عربي"


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


def test_ws_mode_fork_lands_in_the_active_workspace(tmp_path):
    """The client opens the fork with the header it sent. A fork that always
    went to personal 204'd from a team workspace and read as a dead share link."""
    client = _ws_routers_client(tmp_path)
    assert client.put("/chats/c1", json={"title": "t"}).status_code == 200
    share = client.post("/share", json={"path": "chat/c1"}).json()
    team = client.post("/workspaces", json={"name": "Team"}).json()["id"]
    h = {"X-Workspace": team}
    path = share["url"].replace("/shared/", "/share/").split("?")[0]
    r = client.post(f"{path}/fork?ws=u-user_1", headers=h)
    assert r.status_code == 200, r.text
    assert client.get(f"/chats/{r.json()['id']}", headers=h).status_code == 200


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


def test_agent_md_has_its_own_row_not_a_files_entry(tmp_path):
    """The root AGENT.md is the workspace's instructions, opened from its own row — not a file
    in the list. It still reads by path; another folder's AGENT.md is just a file."""
    client = _ws_routers_client(tmp_path)
    client.put("/files/AGENT.md", content=b"Formal Arabic.")
    client.put("/files/docs/AGENT.md", content=b"a doc")
    listed = {e["path"] for e in client.get("/files", params={"recursive": 1}).json()}
    assert "AGENT.md" not in listed and "docs/AGENT.md" in listed
    assert "AGENT.md" not in {e["path"] for e in client.get("/files").json()}
    assert client.get("/files/AGENT.md").text == "Formal Arabic."


def test_memory_is_listed_edited_and_deleted_from_settings(tmp_path):
    client = _ws_routers_client(tmp_path)
    assert client.get("/memory").json() == []
    client.put("/memory/prefs/tone", json={"value": "formal"})
    client.put("/memory/family", json={"value": {"daughter": "Sara"}})
    assert client.get("/memory").json() == [{"key": "family", "value": {"daughter": "Sara"}},
                                            {"key": "prefs/tone", "value": "formal"}]
    client.put("/memory/prefs/tone", json={"value": "casual"})
    assert client.delete("/memory/family").status_code == 200
    assert client.get("/memory").json() == [{"key": "prefs/tone", "value": "casual"}]
    assert client.put("/memory/a//b", json={"value": 1}).status_code == 400


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


def test_brand_refresh_reaches_every_surface(tmp_path, monkeypatch):
    """A published CMS edit must reach the whole page, not just the chat header: the boot value is
    served until the TTL, then a background re-read replaces the title, the meta description, the
    JSON-LD, the OG copy and window.__CONFIG__ together. Nothing waits on the CMS."""
    import time as _time
    from fastapi.testclient import TestClient
    from cycls._agent.web import server

    live = {"description": "old copy"}

    class _Resp:
        status_code = 200
        def json(self): return {"title": "Super", **live}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp())
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _Client())

    async def dummy_agent(context):
        yield "test"

    cfg = Config(public_path=_seo_theme(tmp_path), name="super",
                 cms={"brand": "https://cms.example/agents/super"})
    client = TestClient(web(dummy_agent, cfg))
    assert "old copy" in client.get("/").text

    live["description"] = "new copy"
    assert "old copy" in client.get("/").text          # inside the TTL, still the boot value

    monkeypatch.setattr(server, "BRAND_TTL", 0)        # the next request finds it stale
    for _ in range(50):                                # the re-read runs in the background, so give it a tick
        html = client.get("/").text
        if "new copy" in html:
            break
        _time.sleep(0.02)
    assert "new copy" in html                          # meta description
    assert '"description": "new copy"' in html         # JSON-LD
    assert "new copy" in html.split("window.__CONFIG__")[1]
    assert "new copy" in client.get("/llms.txt").text
    assert "new copy" in str(client.get("/config").json())


def test_boot_timeout_heals_on_the_next_request(tmp_path, monkeypatch):
    """The CMS scales to zero and the boot read is usually what wakes it, so that read routinely
    times out and the agent has no static brand to fall back on. It must not then serve a nameless
    page for a whole TTL: the very next request re-reads, by which point the CMS is warm."""
    import time as _time
    from fastapi.testclient import TestClient

    class _Resp:
        status_code = 200
        def json(self): return {"title": "Super", "description": "Gets things done",
                                "icon_svg": "<svg id='super'/>"}

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()

    def cold(*a, **k): raise TimeoutError("cms cold start exceeded the 5s boot timeout")
    monkeypatch.setattr("httpx.get", cold)              # boot loses the race
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _Client())   # by now the CMS is warm

    async def dummy_agent(context):
        yield "test"

    cfg = Config(public_path=_seo_theme(tmp_path), name="super", title="fallback title",
                 cms={"brand": "https://cms.example/agents/super"})
    client = TestClient(web(dummy_agent, cfg))
    assert cfg.pass_metadata is None                    # the boot read failed, as it does in prod
    assert "<title>Super | Cycls Pass</title>" in client.get("/").text

    for _ in range(50):                                 # no TTL wait: the next request re-reads
        html = client.get("/").text
        if "Gets things done" in html:
            break
        _time.sleep(0.02)
    assert "<title>Super</title>" in html
    assert "Gets things done" in html
    assert "<svg id='super'/>" in cfg.pass_metadata["en"].logo   # the icon the page was missing


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


def test_gtm_provider_injects_snippet(tmp_path):
    """A gtm entry in the analytics plugin list puts the container script on
    every page; without one no marketing bytes ship at all."""
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    cfg = _branded_config(_seo_theme(tmp_path),
                          analytics=[{"provider": "posthog"}, {"provider": "gtm", "id": "GTM-ABC123"}])
    html = TestClient(web(dummy_agent, cfg)).get("/").text
    assert "googletagmanager.com/gtm.js" in html
    assert "'GTM-ABC123'" in html
    plain = TestClient(web(dummy_agent, _branded_config(_seo_theme(tmp_path)))).get("/").text
    assert "googletagmanager" not in plain


def test_analytics_providers_are_plugins():
    """One pipe, providers as config objects: True is PostHog shorthand,
    provider objects normalize to specs, GTM validates its id (it's inlined
    into a script tag — the shape check is the injection guard)."""
    import pytest
    import cycls
    assert cycls.Web().analytics(True)._analytics == [{"provider": "posthog"}]
    assert cycls.Web().analytics(False)._analytics is None
    w = cycls.Web().analytics(
        cycls.PostHog(events=["sign_up"]),
        cycls.GTM("GTM-ABC123", events=["purchase"]))
    assert w._analytics == [{"provider": "posthog", "events": ["sign_up"]},
                            {"provider": "gtm", "id": "GTM-ABC123", "events": ["purchase"]}]
    for bad in ("javascript:alert(1)", "gtm-abc123", "GTM-", "GTM-abc123'"):
        with pytest.raises(ValueError):
            cycls.GTM(bad)


def test_clerk_one_tap_reaches_the_page_config():
    """One Tap is opt-in on the provider (it needs the operator's own Google
    credentials in Clerk) and rides the public config as a plain flag."""
    import cycls
    assert cycls.Clerk().resolve(True)["one_tap"] is False
    assert cycls.Clerk(one_tap=True).resolve(False)["one_tap"] is True
    assert Config(public_path=THEME_PATH).public()["one_tap"] is False


def test_notifications_providers_are_plugins():
    """Push, same shape as analytics: provider objects normalize to specs and
    the app id must look like one — it is inlined into the page config."""
    import pytest
    import cycls
    aid = "12345678-1234-1234-1234-123456789abc"
    assert cycls.Web().notifications()._notifications is None
    assert cycls.Web().notifications(cycls.OneSignal(aid))._notifications == \
        [{"provider": "onesignal", "app_id": aid}]
    for bad in ("not-an-id", "<script>", ""):
        with pytest.raises(ValueError):
            cycls.OneSignal(bad)


def test_onesignal_worker_route(tmp_path):
    """The service worker only exists when OneSignal is configured — and it is
    a one-line import of the vendor worker, served from our origin."""
    from fastapi.testclient import TestClient

    async def dummy_agent(context):
        yield "test"

    cfg = _branded_config(_seo_theme(tmp_path),
                          notifications=[{"provider": "onesignal", "app_id": "x"}])
    c = TestClient(web(dummy_agent, cfg))
    r = c.get("/push/onesignal/OneSignalSDKWorker.js")
    assert r.status_code == 200 and "OneSignalSDK.sw.js" in r.text
    assert "javascript" in r.headers["content-type"]
    assert '"notifications":[{"provider":"onesignal"' in c.get("/").text.replace(" ", "")
    plain = TestClient(web(dummy_agent, _branded_config(_seo_theme(tmp_path))))
    assert plain.get("/push/onesignal/OneSignalSDKWorker.js").status_code == 404


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
                     "d.glb": b"x", "e.py": b"x", "f.zip": b"x", "g.csv": b"x",
                     "h.docx": b"x", "i.pptx": b"x"})
    client = _ws_routers_client(tmp_path)
    kinds = {e["name"]: e["kind"] for e in client.get("/files").json()}
    # Office docs — incl. binary spreadsheets (xlsx) — convert to PDF on demand,
    # so they share one `office` kind. csv stays delimited-text; zip stays opaque.
    assert kinds == {"a.heic": "image", "b.xlsx": "office", "c.mp3": "audio",
                     "d.glb": "model3d", "e.py": "code", "f.zip": "opaque",
                     "g.csv": "csv", "h.docx": "office", "i.pptx": "office"}


def test_office_preview_converts_caches_and_hides(tmp_path, monkeypatch):
    """?as=pdf renders an Office doc to PDF once, serves it inline, then serves
    the cached copy — and the cache never leaks into the listing."""
    from cycls._agent.web import office
    _seed(tmp_path, {"deck.pptx": b"raw-pptx-bytes"})
    calls = []
    async def fake(data, name, user_id=None):
        calls.append((data, name, user_id))
        return b"%PDF-1.7 rendered"
    monkeypatch.setattr(office, "to_pdf", fake)
    client = _ws_routers_client(tmp_path)

    r = client.get("/files/deck.pptx", params={"as": "pdf"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert "attachment" not in r.headers.get("content-disposition", "")   # inline, not a download
    assert r.content == b"%PDF-1.7 rendered"
    assert calls == [(b"raw-pptx-bytes", "deck.pptx", "org_1:user_1")]     # bytes+name+attribution

    r2 = client.get("/files/deck.pptx", params={"as": "pdf"})              # served from cache
    assert r2.status_code == 200 and r2.content == b"%PDF-1.7 rendered"
    assert len(calls) == 1                                                 # not re-converted

    assert [e["name"] for e in client.get("/files").json()] == ["deck.pptx"]  # .cache hidden


def test_office_preview_reconverts_when_source_changes(tmp_path, monkeypatch):
    """The cache key carries the source size+mtime, so an edited document is a
    fresh render rather than a stale hit."""
    from cycls._agent.web import office
    _seed(tmp_path, {"doc.docx": b"one"})
    async def fake(data, name, user_id=None):
        return b"PDF:" + data
    monkeypatch.setattr(office, "to_pdf", fake)
    client = _ws_routers_client(tmp_path)
    assert client.get("/files/doc.docx", params={"as": "pdf"}).content == b"PDF:one"
    client.put("/files/doc.docx", content=b"two-longer")
    assert client.get("/files/doc.docx", params={"as": "pdf"}).content == b"PDF:two-longer"


def test_office_preview_unavailable_returns_415(tmp_path, monkeypatch):
    """A converter miss is a 415 the client turns into the download card, not a
    500."""
    from cycls._agent.web import office
    _seed(tmp_path, {"doc.docx": b"x"})
    async def boom(data, name, user_id=None):
        raise office.Unavailable("office-render not configured")
    monkeypatch.setattr(office, "to_pdf", boom)
    client = _ws_routers_client(tmp_path)
    assert client.get("/files/doc.docx", params={"as": "pdf"}).status_code == 415


def test_as_pdf_ignored_for_non_office(tmp_path, monkeypatch):
    """?as=pdf on a file LibreOffice can't convert just serves the file — the
    converter is never touched."""
    from cycls._agent.web import office
    _seed(tmp_path, {"a.txt": b"hello"})
    def tripwire(*a, **k):
        raise AssertionError("converter must not run for a non-office file")
    monkeypatch.setattr(office, "to_pdf", tripwire)
    client = _ws_routers_client(tmp_path)
    r = client.get("/files/a.txt", params={"as": "pdf"})
    assert r.status_code == 200 and r.content == b"hello"


def test_office_slides_renders_caches_and_hides(tmp_path, monkeypatch):
    """?as=slides renders a presentation to per-slide PNG data-URIs once, serves
    the JSON manifest, then serves the cached copy — cache stays out of the list."""
    from cycls._agent.web import office
    _seed(tmp_path, {"deck.pptx": b"raw-pptx-bytes"})
    calls = []
    async def fake(data, name, user_id=None):
        calls.append((data, name, user_id))
        return [b"\x89PNG-slide-1", b"\x89PNG-slide-2"]
    monkeypatch.setattr(office, "to_slides", fake)
    client = _ws_routers_client(tmp_path)

    r = client.get("/files/deck.pptx", params={"as": "slides"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["count"] == 2
    assert body["slides"][0].startswith("data:image/png;base64,")
    assert base64.b64decode(body["slides"][0].split(",", 1)[1]) == b"\x89PNG-slide-1"
    assert calls == [(b"raw-pptx-bytes", "deck.pptx", "org_1:user_1")]

    r2 = client.get("/files/deck.pptx", params={"as": "slides"})     # cache hit
    assert r2.status_code == 200 and r2.json()["count"] == 2
    assert len(calls) == 1                                           # not re-rendered
    assert [e["name"] for e in client.get("/files").json()] == ["deck.pptx"]   # .cache hidden


def test_office_slides_only_for_presentations(tmp_path, monkeypatch):
    """?as=slides on a non-presentation office file (a spreadsheet) never calls
    the render service — it just serves the raw bytes."""
    from cycls._agent.web import office
    _seed(tmp_path, {"book.xlsx": b"xlsx-bytes"})
    async def tripwire(*a, **k):
        raise AssertionError("render must not run for a non-presentation")
    monkeypatch.setattr(office, "to_slides", tripwire)
    client = _ws_routers_client(tmp_path)
    r = client.get("/files/book.xlsx", params={"as": "slides"})
    assert r.status_code == 200 and r.content == b"xlsx-bytes"


def test_office_slides_unavailable_returns_415(tmp_path, monkeypatch):
    """A render miss is a 415 the client turns into the download card."""
    from cycls._agent.web import office
    _seed(tmp_path, {"deck.pptx": b"x"})
    async def boom(data, name, user_id=None):
        raise office.Unavailable("office-render down")
    monkeypatch.setattr(office, "to_slides", boom)
    client = _ws_routers_client(tmp_path)
    assert client.get("/files/deck.pptx", params={"as": "slides"}).status_code == 415


# ---- design decks: ?as=slides|pptx|pdf|images on a deck document or a .fig ----

_DECK_DOC = json.dumps({"type": "cycls.deck", "version": 1, "fig": "designs/pitch.fig",
                        "size": [1920, 1080], "slides": 2, "exports": ["designs/pitch.pptx"]}).encode()


def _fake_design(monkeypatch):
    from cycls._agent import design
    calls = []

    async def slides(fig, scale=1, fmt="jpg", user_id=None, page=None):
        calls.append(("slides", fig, scale, user_id, page) if page else ("slides", fig, scale, user_id))
        return {"images": [b"\xff\xd8one", b"\xff\xd8two"], "sizes": [[1920, 1080]] * 2, "format": "jpg",
                "pages": _PAGES, "page": page or "Post",
                "meta": [{"name": "cover", "title": "Cover", "notes": "Hello", "transition": "fade"},
                         {"name": "slide-2", "poll": json.dumps({"question": "Tea or coffee?", "options": ["Tea", "Coffee"],
                                                                "tracks": [], "dir": "ltr"})}]}

    async def export(fig, fmt="png", scale=2, width=None, user_id=None, every=False, page=None):
        calls.append((fmt, fig, user_id, page) if page else (fmt, fig, user_id))
        if every:
            return [b"PNG-one", b"PNG-two"]
        return (b"%PDF-deck" if fmt == "pdf" else b"PK-deck") + (f":{page}".encode() if page else b"")

    async def export_page(fig, page, fmt="png", scale=2, width=None, user_id=None):
        calls.append(("page", page, fmt, fig))
        if page not in [p["name"] for p in _PAGES]:
            raise RuntimeError(f'there is no page "{page}" — this design\'s pages: Post, Story')
        return f"{fmt}:{page}".encode(), _PAGES, page
    monkeypatch.setattr(design, "slides", slides)
    monkeypatch.setattr(design, "export", export)
    monkeypatch.setattr(design, "export_page", export_page)
    return calls


_PAGES = [{"name": "Post", "frames": 1}, {"name": "Story", "frames": 2}]


def test_a_designs_pages_preview_and_download_one_at_a_time(tmp_path, monkeypatch):
    """A design's pages are its variants: `&page=<name>` is whose slides, PDF or images
    come back (the first page's without it), each cached by itself, the download named
    for its page; the manifest lists them all."""
    import io, zipfile
    root = _seed(tmp_path, {"designs/launch.fig": b"FIG"})
    calls = _fake_design(monkeypatch)
    client = _ws_routers_client(tmp_path)
    get = lambda as_, page=None: client.get("/files/designs/launch.fig", params={"as": as_, **({"page": page} if page else {})})

    first = get("slides").json()
    assert first["pages"] == _PAGES and first["page"] == "Post"
    story = get("slides", "Story").json()
    assert story["page"] == "Story" and calls[-1] == ("slides", b"FIG", 1, "org_1:user_1", "Story")
    get("slides"); get("slides", "Story")                                     # both stay cached, side by side
    assert len(calls) == 2

    pdf = get("pdf", "Story")
    assert pdf.content == b"%PDF-deck:Story" and 'filename="launch-Story.pdf"' in pdf.headers["content-disposition"]
    assert get("pdf").content == b"%PDF-deck" and 'filename="launch.pdf"' in get("pdf").headers["content-disposition"]
    assert get("pdf", "Story").content == b"%PDF-deck:Story"                  # the first page's didn't replace it
    assert [c for c in calls if c[0] == "pdf"] == [("pdf", b"FIG", "org_1:user_1", "Story"), ("pdf", b"FIG", "org_1:user_1")]
    with zipfile.ZipFile(io.BytesIO(get("images", "Story").content)) as zf:
        assert zf.namelist() == ["launch-Story-slide-1.png", "launch-Story-slide-2.png"]

    (root / "designs/launch.fig").write_bytes(b"EDITED")                      # an edit: every page's render is fresh
    get("slides", "Story")
    assert calls[-1][1] == b"EDITED"
    assert len(list((root / ".cache/design").glob("*.slides.json"))) == 1     # what the old save left is gone


def test_a_documents_manifest_says_it_is_one(tmp_path, monkeypatch):
    """A document's deck (kind "document") tells the viewer so — pages, PDF first. The
    same pages asked for through the .fig, or through a deck that isn't one, carry no
    kind; each is cached by itself, so neither answers for the other."""
    doc = json.dumps({"type": "cycls.deck", "version": 1, "kind": "document", "fig": "designs/report.fig",
                      "size": [1240, 1754], "slides": 2, "exports": ["designs/report.pdf"]}).encode()
    _seed(tmp_path, {"designs/report.fig": b"FIG", "designs/report.deck.json": doc,
                     "designs/pitch.fig": b"FIG2", "designs/pitch.deck.json": _DECK_DOC})
    calls = _fake_design(monkeypatch)
    client = _ws_routers_client(tmp_path)
    slides = lambda path: client.get(f"/files/{path}", params={"as": "slides"}).json()
    assert slides("designs/report.deck.json")["kind"] == "document"
    assert "kind" not in slides("designs/report.fig")                         # asked for as a design: its frames
    assert slides("designs/report.deck.json")["kind"] == "document"           # …and the deck's answer is still its own
    assert "kind" not in slides("designs/pitch.deck.json")
    assert client.get("/files/designs/report.deck.json", params={"as": "pdf"}).content == b"%PDF-deck"
    assert [c[0] for c in calls].count("slides") == 3                         # report (deck), report (.fig), pitch


def test_a_page_that_is_gone_is_a_404(tmp_path, monkeypatch):
    from cycls._agent import design
    _seed(tmp_path, {"designs/launch.fig": b"FIG"})
    _fake_design(monkeypatch)

    async def gone(fig, **kw):
        raise RuntimeError('there is no page "Old" — this design\'s pages: Post, Story')
    monkeypatch.setattr(design, "slides", gone)
    client = _ws_routers_client(tmp_path)
    r = client.get("/files/designs/launch.fig", params={"as": "slides", "page": "Old"})
    assert r.status_code == 404 and "there is no page" in r.json()["detail"]


def test_a_page_exports_to_its_own_file(tmp_path, monkeypatch):
    """Export PDF from inside the editor, on the page in view: the first page is the
    design's own file, a later one `<name>-page-<its place>` — kept in step from then on."""
    root = _seed(tmp_path, {"designs/launch.fig": b"FIG", "notes/logo.fig": b"LOGO"})
    calls = _fake_design(monkeypatch)
    client = _ws_routers_client(tmp_path)
    export = lambda **body: client.post("/design/export", json=body)
    assert export(path="designs/launch.fig", format="pdf", page="Story").json() == {"path": "designs/launch-page-2.pdf"}
    assert (root / "designs/launch-page-2.pdf").read_bytes() == b"pdf:Story" and calls[-1] == ("page", "Story", "pdf", b"FIG")
    assert export(path="designs/launch.fig", format="png", page="Post").json() == {"path": "designs/launch.png"}
    assert export(path="notes/logo.fig", format="png", page="Story").json() == {"path": "notes/logo-page-2.png"}
    assert export(path="designs/launch.fig", page="Nope").status_code == 404
    assert not list((root / "designs").glob(".*.part"))


def test_kinds_for_designs_and_decks(tmp_path):
    _seed(tmp_path, {"designs/pitch.fig": b"FIG", "designs/pitch.deck.json": _DECK_DOC, "a.json": b"{}"})
    client = _ws_routers_client(tmp_path)
    kinds = {e["name"]: e["kind"] for e in client.get("/files", params={"path": "designs"}).json()}
    assert kinds == {"pitch.fig": "design", "pitch.deck.json": "deck"}   # a .fig no longer downloads on click
    assert {e["name"]: e["kind"] for e in client.get("/files").json()}["a.json"] == "code"


def test_deck_slides_render_once_and_carry_the_notes(tmp_path, monkeypatch):
    root = _seed(tmp_path, {"designs/pitch.fig": b"FIG", "designs/pitch.deck.json": _DECK_DOC})
    calls = _fake_design(monkeypatch)
    client = _ws_routers_client(tmp_path)
    r = client.get("/files/designs/pitch.deck.json", params={"as": "slides"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["count"] == 2 and body["fig"] == "designs/pitch.fig"
    assert base64.b64decode(body["slides"][1].split(",", 1)[1]) == b"\xff\xd8two"
    assert body["slides"][0].startswith("data:image/jpeg;base64,")
    assert body["notes"] == ["Hello", ""] and body["titles"] == ["Cover", ""] and body["transitions"] == ["fade", ""]
    assert body["polls"][0] is None and body["polls"][1]["question"] == "Tea or coffee?"   # a poll slide's poll
    assert calls == [("slides", b"FIG", 1, "org_1:user_1")]                 # 1920 wide → @1x
    client.get("/files/designs/pitch.deck.json", params={"as": "slides"})
    client.get("/files/designs/pitch.fig", params={"as": "slides"})          # the .fig itself: same cache
    assert len(calls) == 1
    (root / "designs" / "pitch.fig").write_bytes(b"EDITED-FIG")          # an edit → a fresh render
    client.get("/files/designs/pitch.deck.json", params={"as": "slides"})
    assert calls[-1][1] == b"EDITED-FIG"


def test_deck_downloads_export_on_demand(tmp_path, monkeypatch):
    _seed(tmp_path, {"designs/pitch.fig": b"FIG", "designs/pitch.deck.json": _DECK_DOC})
    calls = _fake_design(monkeypatch)
    client = _ws_routers_client(tmp_path)
    r = client.get("/files/designs/pitch.deck.json", params={"as": "pdf"})
    assert r.status_code == 200 and r.content == b"%PDF-deck"
    assert 'filename="pitch.pdf"' in r.headers["content-disposition"]
    r = client.get("/files/designs/pitch.deck.json", params={"as": "pptx"})
    assert r.content == b"PK-deck" and 'filename="pitch.pptx"' in r.headers["content-disposition"]
    client.get("/files/designs/pitch.deck.json", params={"as": "pdf"})       # cached
    assert [c[0] for c in calls] == ["pdf", "pptx"]
    assert client.get("/files/designs/pitch.deck.json").content == _DECK_DOC   # no ?as: the document itself


def test_a_decks_images_download_as_a_zip(tmp_path, monkeypatch):
    """A carousel is posted as images: the deck viewer's Download had only PowerPoint
    and PDF. `?as=images` is every slide as a PNG, named as a carousel render names them."""
    import io, zipfile
    _seed(tmp_path, {"designs/pitch.fig": b"FIG", "designs/pitch.deck.json": _DECK_DOC})
    calls = _fake_design(monkeypatch)
    client = _ws_routers_client(tmp_path)
    r = client.get("/files/designs/pitch.deck.json", params={"as": "images"})
    assert r.status_code == 200 and 'filename="pitch.zip"' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == ["pitch-slide-1.png", "pitch-slide-2.png"]
        assert zf.read("pitch-slide-2.png") == b"PNG-two"
    client.get("/files/designs/pitch.fig", params={"as": "images"})          # the .fig itself: same cache
    assert calls == [("png", b"FIG", "org_1:user_1")]


def test_a_design_exports_to_a_file_beside_it(tmp_path, monkeypatch):
    """The editor's File › Export › PDF: Cycls renders the design through the service
    and writes `designs/<name>.pdf` — the design's own image, replaced by the next one."""
    from cycls._agent import design
    root = _seed(tmp_path, {"designs/launch.fig": b"FIG", "notes/logo.fig": b"LOGO", "notes/logo.pdf": b"MINE",
                            "notes/a.txt": b"x"})
    calls = _fake_design(monkeypatch)
    client = _ws_routers_client(tmp_path)
    export = lambda **body: client.post("/design/export", json=body)

    r = export(path="designs/launch.fig", format="pdf")
    assert r.status_code == 200 and r.json() == {"path": "designs/launch.pdf"}
    assert (root / "designs/launch.pdf").read_bytes() == b"%PDF-deck" and calls == [("pdf", b"FIG", "org_1:user_1")]
    (root / "designs/launch.fig").write_bytes(b"EDITED")                      # an edit, then again: replaced
    assert export(path="designs/launch.fig").json() == {"path": "designs/launch.pdf"}     # pdf is the default
    assert calls[-1] == ("pdf", b"EDITED", "org_1:user_1")
    assert "launch.pdf" in [e["name"] for e in client.get("/files", params={"path": "designs"}).json()]
    assert not list((root / "designs").glob(".*.part"))

    # Outside designs/ a file that's there is the person's own: the export takes a free name.
    assert export(path="notes/logo.fig", format="pdf").json() == {"path": "notes/logo-2.pdf"}
    assert (root / "notes/logo.pdf").read_bytes() == b"MINE"

    assert export(path="designs/launch.fig", format="exe").status_code == 400
    assert export(path="notes/a.txt").status_code == 404
    assert export(path="designs/nope.fig").status_code == 404
    assert export(path="../outside.fig").status_code == 403

    async def down(*a, **k):
        raise design.Unavailable("design not configured (DESIGN_URL)")
    monkeypatch.setattr(design, "export", down)
    (root / "designs/launch.fig").write_bytes(b"AGAIN")
    assert export(path="designs/launch.fig").status_code == 415


def test_deck_errors(tmp_path, monkeypatch):
    from cycls._agent import design
    root = _seed(tmp_path, {"designs/pitch.deck.json": _DECK_DOC,
                     "designs/evil.deck.json": json.dumps({"fig": "../../outside.fig"}).encode(),
                     "designs/bare.deck.json": b"{}"})
    client = _ws_routers_client(tmp_path)
    assert client.get("/files/designs/pitch.deck.json", params={"as": "slides"}).status_code == 404   # no .fig
    assert client.get("/files/designs/evil.deck.json", params={"as": "slides"}).status_code == 422    # stays inside
    assert client.get("/files/designs/bare.deck.json", params={"as": "slides"}).status_code == 422
    (root / "designs" / "pitch.fig").write_bytes(b"FIG")

    async def down(*a, **k):
        raise design.Unavailable("design not configured (DESIGN_URL)")
    monkeypatch.setattr(design, "slides", down)
    assert client.get("/files/designs/pitch.deck.json", params={"as": "slides"}).status_code == 415   # → download card


def test_deck_route_moves_duplicates_and_deletes_slides(tmp_path, monkeypatch):
    """The deck viewer's own slide changes go through the same service op as the agent's."""
    from cycls._agent import design
    from cycls._agent.design import refresh
    root = _seed(tmp_path, {"designs/pitch.fig": b"FIG", "designs/pitch.deck.json": _DECK_DOC})
    seen = []

    async def apply(fig, script=None, user_id=None, ops=None, preview=False):
        seen.append(ops)
        return {"fig": b"NEW", "lint": [], "script": "S", "preview": None, "previews": [], "touched": [], "slides": [{}] * 3}
    monkeypatch.setattr(design, "apply", apply)
    monkeypatch.setattr(refresh, "schedule", lambda *a, **k: None)
    client = _ws_routers_client(tmp_path)
    r = client.post("/deck/designs/pitch.deck.json", json={"op": "move", "number": 3, "to": 1})
    assert r.status_code == 200 and r.json() == {"ok": True, "slides": 3}
    assert seen[-1] == [{"op": "slide_move", "index": 2, "to": 0}]
    assert (root / "designs" / "pitch.fig").read_bytes() == b"NEW"
    client.post("/deck/designs/pitch.fig", json={"op": "duplicate", "number": 1})
    assert seen[-1] == [{"op": "slide_duplicate", "index": 0}]
    assert client.post("/deck/designs/pitch.deck.json", json={"op": "move", "number": 2}).status_code == 400   # no `to`
    assert client.post("/deck/designs/pitch.deck.json", json={"op": "explode", "number": 1}).status_code == 400
    assert client.post("/deck/notes/pitch.deck.json", json={"op": "delete", "number": 1}).status_code == 404   # outside designs/


def test_deck_route_adds_a_slide_and_keeps_a_slides_notes(tmp_path, monkeypatch):
    """The deck viewer's "Add slide" and its notes box. A deck made of layouts gets a slide
    laid out like its own (its theme, its size); a hand-built one gets a blank slide the
    colour of the slide before it, titled in a colour that shows on it. Notes are the
    slide's, as the agent's `update_slide` writes them."""
    from cycls._agent import design
    from cycls._agent.design import refresh
    laid = json.dumps({"type": "cycls.deck", "version": 1, "fig": "designs/pitch.fig", "size": [1920, 1080], "slides": 3,
                       "exports": [], "settings": {"theme": "editorial", "size": [1920, 1080]}}).encode()
    root = _seed(tmp_path, {"designs/pitch.fig": b"FIG", "designs/pitch.deck.json": laid,
                            "designs/hand.fig": b"FIG", "designs/hand.deck.json": _DECK_DOC})
    seen = []

    async def apply(fig, script=None, user_id=None, ops=None, preview=False):
        seen.append(ops)
        return {"fig": b"NEW", "lint": [], "script": "S", "preview": None, "previews": [], "touched": [], "slides": [{}] * 4}

    async def inspect(fig, user_id=None, page=None):
        return [{"slide": 1, "size": [1920, 1080], "fill": "#ffffff", "nodes": []},
                {"slide": 2, "size": [1920, 1080], "fill": "#0f172a", "nodes": []}]
    monkeypatch.setattr(design, "apply", apply)
    monkeypatch.setattr(design, "inspect", inspect)
    monkeypatch.setattr(refresh, "schedule", lambda *a, **k: None)
    client = _ws_routers_client(tmp_path)

    r = client.post("/deck/designs/pitch.deck.json", json={"op": "add", "number": 2, "title": "شريحة جديدة", "text": "أضف نصك"})
    assert r.status_code == 200 and r.json() == {"ok": True, "slides": 4, "added": 3}
    [op] = seen[-1]
    assert op["op"] == "slide_add" and op["at"] == 2
    assert op["slide"]["layout"] == "bullets" and op["slide"]["title"] == "شريحة جديدة" and op["slide"]["bullets"] == ["أضف نصك"]
    assert op["deck"]["theme"] == "editorial"                         # laid out as the deck's own slides are
    # No place said: at the end, with words of its own.
    assert client.post("/deck/designs/pitch.fig", json={"op": "add"}).json() == {"ok": True, "slides": 4, "added": 4}
    [op] = seen[-1]
    assert "at" not in op and op["slide"]["title"] == "New slide" and op["slide"]["bullets"] == ["Add your text"]

    # A hand-built deck: a blank slide the colour of the one it comes after, its title readable on it.
    r = client.post("/deck/designs/hand.deck.json", json={"op": "add", "number": 2, "title": "Next"})
    assert r.status_code == 200
    [op] = seen[-1]
    assert op["at"] == 2 and op["slide"]["fill"] == "#0f172a" and "layout" not in op["slide"]
    [title] = [n for n in op["slide"]["nodes"] if n.get("type") == "text"]
    assert title["text"] == "Next" and title["color"].lower() == "#ffffff"

    # Notes: the slide's own, trimmed; emptied when cleared.
    r = client.post("/deck/designs/pitch.deck.json", json={"op": "notes", "number": 2, "notes": "  Say hello  "})
    assert r.status_code == 200 and seen[-1] == [{"op": "slide_meta", "index": 1, "notes": "Say hello"}]
    client.post("/deck/designs/pitch.deck.json", json={"op": "notes", "number": 1, "notes": ""})
    assert seen[-1] == [{"op": "slide_meta", "index": 0, "notes": ""}]
    count = len(seen)
    for bad in ({"op": "notes", "number": 0, "notes": "x"}, {"op": "notes", "number": 1}, {"op": "notes", "number": 1, "notes": "x" * 20001},
                {"op": "add", "number": -1}, {"op": "add", "number": "2"}, {"op": "add", "title": "t" * 301}):
        assert client.post("/deck/designs/pitch.deck.json", json=bad).status_code == 400, bad
    assert len(seen) == count                                           # nothing was sent for any of them


def test_new_design_route_makes_a_blank_design(tmp_path, monkeypatch):
    """Cycls's "New design": one blank frame of a size preset (or [w, h]), saved as
    designs/<name>.fig with its .png like a render, never over another design."""
    from types import SimpleNamespace
    from cycls._agent import design
    root = _seed(tmp_path, {"designs/.keep": b""})
    seen = []

    async def render(spec, fmt="png", scale=2, user_id=None, every=False):
        seen.append((spec, fmt, scale))
        return SimpleNamespace(image=b"PNG", fig=b"FIG")
    monkeypatch.setattr(design, "configured", lambda: True)
    monkeypatch.setattr(design, "render", render)
    client = _ws_routers_client(tmp_path)

    r = client.post("/design/new", json={"name": "Launch", "size": "story"})
    assert r.status_code == 200 and r.json() == {"path": "designs/Launch.fig", "name": "Launch", "size": [1080, 1920]}
    assert seen[-1] == ({"size": [1080, 1920], "fill": "#ffffff", "nodes": []}, "png", 1)
    assert (root / "designs/Launch.fig").read_bytes() == b"FIG" and (root / "designs/Launch.png").read_bytes() == b"PNG"
    assert client.post("/design/new", json={"name": "Launch"}).json()["path"] == "designs/Launch-2.fig"   # never over one
    assert client.post("/design/new").json() == {"path": "designs/untitled.fig", "name": "untitled", "size": [1080, 1080]}
    assert client.post("/design/new", json={"name": "../x/حملة الإطلاق.fig"}).json()["name"] == "حملة الإطلاق"
    r = client.post("/design/new", json={"size": [800, 600], "background": "#0F172A"})
    assert r.json()["size"] == [800, 600] and seen[-1][0]["fill"] == "#0f172a"
    for bad in ({"size": "huge"}, {"size": [5, 5]}, {"size": [800, "600"]}, {"background": "red"}):
        assert client.post("/design/new", json=bad).status_code == 400, bad
    monkeypatch.setattr(design, "configured", lambda: False)
    assert client.post("/design/new").status_code == 503


def test_put_dedupe_writes_a_new_file(tmp_path, monkeypatch):
    """`?dedupe=1` — an export or a copy from the editor — takes the next free name:
    never an existing file, never an image the design refresh keeps beside a .fig,
    and a .fig copy keeps clear of another design's images."""
    from cycls._agent.design import refresh
    monkeypatch.setattr(refresh, "schedule", lambda *a, **k: None)
    root = _seed(tmp_path, {"designs/launch.fig": b"FIG", "designs/launch.png": b"PNG", "designs/draft-2.png": b"P"})
    client = _ws_routers_client(tmp_path)
    put = lambda path, data=b"X": client.put(f"/files/{path}?dedupe=1", content=data).json()["path"]

    assert put("designs/launch-hero@2x.png") == "designs/launch-hero@2x.png"
    assert put("designs/launch-hero@2x.png") == "designs/launch-hero@2x-2.png"
    assert put("designs/launch.svg") == "designs/launch-2.svg"             # the refresh's name for launch.fig's SVG
    assert put("designs/launch-slide-1.png") == "designs/launch-slide-1-2.png"
    assert put("designs/launch.fig", b"COPY") == "designs/launch-2.fig"
    assert put("designs/draft.fig") == "designs/draft.fig"
    assert put("designs/draft.fig") == "designs/draft-3.fig"                 # draft-2.png is another design's
    assert (root / "designs/launch.fig").read_bytes() == b"FIG"               # the original stands
    from cycls._agent.design.store import version_of
    assert client.put("/files/designs/launch.fig", content=b"NEW").json() == {
        "ok": True, "path": "designs/launch.fig", "version": version_of(b"NEW")}
    assert client.put("/files/my%20docs/a%23b.txt", content=b"hi").json()["path"] == "my docs/a#b.txt"
    assert (root / "my docs" / "a#b.txt").read_bytes() == b"hi"


def test_a_new_design_file_is_left_with_an_image(tmp_path, monkeypatch):
    """A copy from the editor (`?dedupe=1`) asks the refresh for its `.png`; an ordinary
    save only keeps up the images already beside the design."""
    from cycls._agent.design import refresh
    asked = []
    monkeypatch.setattr(refresh, "schedule", lambda root, rel, user_id=None, ensure=False: asked.append((rel, ensure)))
    _seed(tmp_path, {"designs/launch.fig": b"FIG", "designs/launch.png": b"PNG"})
    client = _ws_routers_client(tmp_path)
    assert client.put("/files/designs/launch copy.fig?dedupe=1", content=b"COPY").json()["path"] == "designs/launch copy.fig"
    client.put("/files/designs/launch copy.fig", content=b"EDITED")
    assert asked == [("designs/launch copy.fig", True), ("designs/launch copy.fig", False)]


def test_refresh_managed_names_the_images_beside_a_design(tmp_path):
    from cycls._agent.design import refresh
    root = _seed(tmp_path, {"designs/launch.fig": b"FIG", "designs/sub/deck.fig": b"FIG"})
    assert refresh.managed(root, "designs/launch.png") and refresh.managed(root, "designs/launch.pdf")
    assert refresh.managed(root, "designs/launch-slide-2.webp")
    assert refresh.managed(root, "designs/sub/deck.pptx")
    assert not refresh.managed(root, "designs/launch-hero.png")
    assert not refresh.managed(root, "designs/other.png")
    assert not refresh.managed(root, "designs/launch.txt")
    assert not refresh.managed(root, "notes/launch.png")


def test_brand_route_reads_the_brand_kit(tmp_path):
    """The design editor's Brand variables and fonts: the brand kit's named colours
    (only those it names — nothing inferred) and its fonts, or null without a kit."""
    client = _ws_routers_client(tmp_path)
    assert client.get("/brand").json() == {"brand": None}
    root = _seed(tmp_path, {"brand/brand.yaml": (
        'primary_color: "#0C2340"\nsecondary_color: \'#abc\'\nfont_heading: "Playfair Display"\n').encode()})
    assert client.get("/brand").json() == {"brand": {
        "colors": {"primary": "#0c2340", "secondary": "#aabbcc"},
        "fonts": {"heading": "Playfair Display", "body": None}}}
    (root / "brand/brand.yaml").write_text(
        'colors:\n  primary: "#112233"\n  accent: "#445566"\nfonts:\n  body: Inter\n', encoding="utf-8")
    assert client.get("/brand").json() == {"brand": {
        "colors": {"primary": "#112233", "accent": "#445566"}, "fonts": {"heading": None, "body": "Inter"}}}


# ---- office module: the office-render /v1/convert client ----

def test_office_convertible_and_configured(monkeypatch):
    from cycls._agent.web import office
    assert office.convertible("a.docx") and office.convertible("B.PPTX") and office.convertible("c.xlsx")
    assert not office.convertible("d.pdf") and not office.convertible("e.csv") and not office.convertible("f")
    monkeypatch.delenv("OFFICE_RENDER_URL", raising=False)
    monkeypatch.delenv("OFFICE_RENDER_SECRET", raising=False)
    assert office.configured() is False
    monkeypatch.setenv("OFFICE_RENDER_URL", "https://x")
    assert office.configured() is False          # needs both halves
    monkeypatch.setenv("OFFICE_RENDER_SECRET", "s")
    assert office.configured() is True


def test_office_to_pdf_unavailable_paths(monkeypatch):
    from cycls._agent.web import office
    monkeypatch.delenv("OFFICE_RENDER_URL", raising=False)
    monkeypatch.delenv("OFFICE_RENDER_SECRET", raising=False)
    with pytest.raises(office.Unavailable):       # not configured
        asyncio.run(office.to_pdf(b"x", "a.docx"))
    monkeypatch.setenv("OFFICE_RENDER_URL", "https://x")
    monkeypatch.setenv("OFFICE_RENDER_SECRET", "s")
    with pytest.raises(office.Unavailable):       # not a convertible type
        asyncio.run(office.to_pdf(b"x", "a.pdf"))


def test_office_to_pdf_posts_to_v1_convert(monkeypatch):
    """to_pdf hits {URL}/v1/convert with the file, to=pdf, the service bearer,
    and X-User-Id — matching the office-render contract."""
    from cycls._agent.web import office
    monkeypatch.setenv("OFFICE_RENDER_URL", "https://office-render.cycls.ai/")   # trailing slash
    monkeypatch.setenv("OFFICE_RENDER_SECRET", "sekret")
    seen = {}

    class FakeResp:
        status_code = 200
        content = b"%PDF-rendered"
        text = ""

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, files=None, data=None, headers=None):
            seen.update(url=url, files=files, data=data, headers=headers)
            return FakeResp()

    monkeypatch.setattr(office.httpx, "AsyncClient", FakeClient)
    out = asyncio.run(office.to_pdf(b"raw", "deck.pptx", user_id="org:u"))
    assert out == b"%PDF-rendered"
    assert seen["url"] == "https://office-render.cycls.ai/v1/convert"   # one slash, /v1/convert
    assert seen["data"] == {"to": "pdf"}
    assert seen["files"]["file"][0] == "deck.pptx"                      # filename carries the ext
    assert seen["headers"]["Authorization"] == "Bearer sekret"
    assert seen["headers"]["X-User-Id"] == "org:u"


def test_office_to_pdf_maps_service_error_to_unavailable(monkeypatch):
    from cycls._agent.web import office
    monkeypatch.setenv("OFFICE_RENDER_URL", "https://x")
    monkeypatch.setenv("OFFICE_RENDER_SECRET", "s")

    class FakeResp:
        status_code = 422
        content = b""
        text = "convert failed"

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return FakeResp()

    monkeypatch.setattr(office.httpx, "AsyncClient", FakeClient)
    with pytest.raises(office.Unavailable):
        asyncio.run(office.to_pdf(b"x", "a.docx"))


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


def test_folder_time_comes_from_its_newest_child(tmp_path):
    """A folder's own mtime means nothing on the gcsfuse mount; its newest file's does."""
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
    sandbox — are invisible to a search until the TTL, so clients can force a walk.
    A folder listing reads the folder, and shows them at once."""
    root = _seed(tmp_path, {"a.txt": b"x"})
    client = _ws_routers_client(tmp_path)
    names = lambda **params: [e["name"] for e in client.get("/files", params=params).json()]
    assert names(search="") == ["a.txt"]                   # warm it

    (root / "agent-made.txt").write_bytes(b"z")            # bypasses the write routes
    assert "agent-made.txt" not in names(search="")
    assert "agent-made.txt" in names(search="", fresh=1)
    assert "agent-made.txt" in names()


def test_a_folder_listing_does_not_depend_on_the_walk(tmp_path, monkeypatch):
    """The Files panel took 30–40 s on a large workspace: every listing, even of one
    folder, waited for a walk of the whole tree. It reads the folder it shows."""
    from cycls._agent.web import routers

    _seed(tmp_path, {"designs/launch.fig": b"FIG", "designs/launch.png": b"PNG", "notes/a.md": b"x"})

    def no_walk(root):
        raise OSError("the walk is not what a folder listing reads")
    monkeypatch.setattr(routers, "_walk_catalog", no_walk)
    client = _ws_routers_client(tmp_path)
    assert [e["name"] for e in client.get("/files").json()] == ["designs", "notes"]
    listed = client.get("/files", params={"path": "designs"}).json()
    assert [(e["name"], e["path"], e["kind"]) for e in listed] == [
        ("launch.fig", "designs/launch.fig", "design"), ("launch.png", "designs/launch.png", "image")]


def test_a_search_right_after_a_write_sees_it(tmp_path):
    _seed(tmp_path, {"a.txt": b"x"})
    client = _ws_routers_client(tmp_path)
    found = lambda q: [e["path"] for e in client.get("/files", params={"search": q}).json()]
    assert found("txt") == ["a.txt"]
    client.put("/files/docs/b.txt", content=b"y")
    assert found("txt") == ["a.txt", "docs/b.txt"]
    client.delete("/files/a.txt")
    assert found("txt") == ["docs/b.txt"]


def _slow_walks(monkeypatch):
    """`_walk_catalog` behind a gate the test opens → (gate, how many walks began)."""
    import threading
    from cycls._agent.web import routers
    real, gate, began = routers._walk_catalog, threading.Event(), []

    def gated(root):
        began.append(root)
        gate.wait(5)
        return real(root)
    monkeypatch.setattr(routers, "_walk_catalog", gated)
    return gate, began


def test_a_slow_rewalk_is_not_waited_for(tmp_path, monkeypatch):
    """The + popover's search took 39 s: the cache lasted 5 s from when a walk BEGAN,
    and that workspace's walk takes longer — every search walked the tree again and
    waited. Now the last tree is served while the new one finishes behind it."""
    from cycls._agent.web import routers
    root = _seed(tmp_path, {"a.txt": b"x"})
    names = lambda tree: sorted(e["name"] for e in tree[0])
    monkeypatch.setattr(routers, "_CATALOG_WAIT", 0.05)

    async def go():
        first = await routers._catalog_get(root)
        (root / "b.txt").write_bytes(b"y")
        routers._catalog_drop(root)                            # a write here
        gate, began = _slow_walks(monkeypatch)
        t0 = time.monotonic()
        served = await routers._catalog_get(root)
        waited = time.monotonic() - t0
        again = await routers._catalog_get(root)               # joins the walk under way
        gate.set()
        await routers._catalog[str(root)]["walk"]
        return names(first), names(served), waited, names(again), len(began), names(await routers._catalog_get(root))

    first, served, waited, again, walks, landed = asyncio.run(go())
    assert first == served == again == ["a.txt"] and waited < 2
    assert walks == 1
    assert landed == ["a.txt", "b.txt"]


def test_a_walk_is_reused_from_when_it_ended(tmp_path, monkeypatch):
    from cycls._agent.web import routers
    root = _seed(tmp_path, {"a.txt": b"x"})
    real, walks = routers._walk_catalog, []

    def slow(r):
        walks.append(r)
        time.sleep(0.3)                                        # longer than the TTL
        return real(r)
    monkeypatch.setattr(routers, "_walk_catalog", slow)
    monkeypatch.setattr(routers, "_CATALOG_TTL", 0.2)

    async def go():
        await routers._catalog_get(root)
        await routers._catalog_get(root)
    asyncio.run(go())
    assert len(walks) == 1


def test_a_walk_begun_before_a_write_is_walked_again(tmp_path, monkeypatch):
    from cycls._agent.web import routers
    root = _seed(tmp_path, {"a.txt": b"x"})
    gate, began = _slow_walks(monkeypatch)

    async def go():
        walking = asyncio.ensure_future(routers._catalog_get(root))
        while not began:
            await asyncio.sleep(0.01)
        (root / "b.txt").write_bytes(b"y")
        routers._catalog_drop(root)                            # lands mid-walk
        gate.set()
        await walking
        return sorted(e["name"] for e in (await routers._catalog_get(root))[0])
    assert asyncio.run(go()) == ["a.txt", "b.txt"] and len(began) == 2


def test_fresh_waits_for_a_new_walk(tmp_path, monkeypatch):
    from cycls._agent.web import routers
    root = _seed(tmp_path, {"a.txt": b"x"})
    monkeypatch.setattr(routers, "_CATALOG_WAIT", 0.01)

    async def go():
        await routers._catalog_get(root)
        (root / "agent-made.txt").write_bytes(b"z")
        real = routers._walk_catalog
        monkeypatch.setattr(routers, "_walk_catalog", lambda r: (time.sleep(0.2), real(r))[1])
        return sorted(e["name"] for e in (await routers._catalog_get(root, fresh=True))[0])
    assert asyncio.run(go()) == ["a.txt", "agent-made.txt"]


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


# ---- DELETE /chats/{id}/last-exchange (the persistence half of regenerate) ----

def test_last_exchange_route_rewinds_the_chat(tmp_path):
    import asyncio
    from cycls._agent import state
    from cycls._app.db import workspace

    from cycls._app.auth import User

    client = _ws_routers_client(tmp_path)
    client.put("/chats/c1", json={"title": "hello"})
    # Same resolution the routers do: personal workspace of the fixed user.
    ws = workspace(User(id="user_1", org_id="org_1"), tmp_path,
                   base=f"file://{tmp_path}", ws="u-user_1")
    asyncio.run(state.append_messages(ws, "c1", [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "one"}]},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": [{"type": "text", "text": "two"}]},
    ], 0))

    r = client.delete("/chats/c1/last-exchange")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert [m["content"] for m in client.get("/chats/c1").json()["messages"]] == ["first", "one"]

    # Nothing left to rewind past — the route reports it rather than erroring.
    client.delete("/chats/c1/last-exchange")
    assert client.delete("/chats/c1/last-exchange").json() == {"ok": False}


def test_retry_drops_only_the_turn_it_is_about_to_resend(tmp_path):
    """`?expect=<sha256 of the text>` — retry's form. A stopped or failed turn keeps its
    user message on disk; re-sending without dropping it stored the message twice."""
    import asyncio, hashlib
    from cycls._agent import state
    from cycls._app.db import workspace
    from cycls._app.auth import User

    client = _ws_routers_client(tmp_path)
    client.put("/chats/c1", json={"title": "hello"})
    ws = workspace(User(id="user_1", org_id="org_1"), tmp_path, base=f"file://{tmp_path}", ws="u-user_1")
    sha = lambda text: hashlib.sha256(text.encode()).hexdigest()
    shown = lambda: [m["content"] for m in client.get("/chats/c1").json()["messages"]]
    put_run = lambda status: asyncio.run(state.put_run(ws, "c1", {"run": "r", "status": status}))
    asyncio.run(state.append_messages(ws, "c1", [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": [{"type": "text", "text": "one"}]},
        {"role": "user", "content": [{"type": "text", "text": "[Selected in designs/a.fig: cta]"},
                                     {"type": "text", "text": "make a deck"}],
         "selection": {"path": "designs/a.fig", "nodes": [{"name": "cta"}]}},
        {"role": "assistant", "content": [{"type": "text", "text": "half an ans"}]},
    ], 0))

    # Another message: the failed request never arrived, and what is here stays.
    put_run("stopped")
    assert client.delete(f"/chats/c1/last-exchange?expect={sha('something else')}").json() == {"ok": False}
    assert shown() == ["first", "one", "make a deck", "half an ans"]

    # The same text, but that turn ended well: it is not the one being retried.
    put_run("done")
    assert client.delete(f"/chats/c1/last-exchange?expect={sha('make a deck')}").json() == {"ok": False}
    assert shown() == ["first", "one", "make a deck", "half an ans"]

    # The stopped turn, named by what the person typed (the selection line is the model's).
    put_run("stopped")
    assert client.delete(f"/chats/c1/last-exchange?expect={sha('make a deck')}").json() == {"ok": True}
    assert shown() == ["first", "one"]


def test_last_exchange_route_404s_on_unknown_chat(tmp_path):
    client = _ws_routers_client(tmp_path)
    assert client.delete("/chats/nope/last-exchange").status_code == 404


def test_last_exchange_route_does_not_shadow_chat_delete(tmp_path):
    """`/chats/{id}` is registered after the more specific path — make sure a
    plain delete still wipes the chat rather than matching the sub-route."""
    client = _ws_routers_client(tmp_path)
    client.put("/chats/c1", json={"title": "hello"})
    assert client.delete("/chats/c1").status_code == 200
    assert client.get("/chats").json() == []


# =============================================================================
# One run per chat (docs/notes/runs.md)
# =============================================================================

class _FakeTask:
    """`_claim` only ever asks a task whether it is done."""
    def __init__(self, done=False): self._done = done
    def done(self): return self._done


def test_claim_scopes_the_slot_to_a_workspace():
    """`?id=` is client-supplied text. A flat key would let one tenant lock
    another's chat by guessing an id."""
    from cycls._agent.web.server import _claim
    runs = {}
    assert _claim(runs, ("orgA/.db/u1", "c1"), _FakeTask())
    assert _claim(runs, ("orgB/.db/u2", "c1"), _FakeTask())


def test_claim_refuses_a_live_run_and_keeps_the_holder():
    from cycls._agent.web.server import _claim
    runs, holder, key = {}, _FakeTask(), ("ws", "c1")
    assert _claim(runs, key, holder)
    assert not _claim(runs, key, _FakeTask())
    assert runs[key] is holder, "the loser overwrote the winner"


def test_claim_treats_a_finished_run_as_stale():
    """A release that never ran must not lock the chat forever."""
    from cycls._agent.web.server import _claim
    runs, key = {}, ("ws", "c1")
    runs[key] = _FakeTask(done=True)
    assert _claim(runs, key, _FakeTask())


def test_a_send_to_a_busy_chat_is_refused_and_a_new_chat_is_not():
    """The duplicate-POST case that interleaved writes in production."""
    from fastapi.testclient import TestClient

    keys = []
    async def handler(context):
        keys.extend(app.state.runs)
        yield "ok"

    app = web(handler, Config(public_path=THEME_PATH, auth=False))
    client = TestClient(app)
    body = {"messages": [{"role": "user", "content": "hi"}]}

    assert client.post("/chat?id=c1", json=body).status_code == 200
    assert len(keys) == 1, "the run never claimed a slot"
    assert app.state.runs == {}, "the slot was not released"

    app.state.runs[keys[0]] = _FakeTask()          # a run still in flight
    busy = client.post("/chat?id=c1", json=body)
    assert busy.status_code == 409
    assert busy.json()["error"] == "run_in_progress"
    assert busy.headers["retry-after"] == "2"
    assert isinstance(busy.json()["detail"], str)  # reasonOf() only reads a string
    assert client.post("/chat", json=body).status_code == 200, "a new chat is never refused"


def test_a_failing_run_still_releases_its_slot():
    from fastapi.testclient import TestClient

    async def handler(context):
        raise RuntimeError("boom")
        yield "unreachable"

    app = web(handler, Config(public_path=THEME_PATH, auth=False))
    client = TestClient(app)
    client.post("/chat?id=c1", json={"messages": [{"role": "user", "content": "hi"}]})
    assert app.state.runs == {}


# =============================================================================
# Detachment (docs/notes/runs.md §2c)
# =============================================================================

def _drive_run(detach):
    """Start a run, read one chunk, then drop the reader. Returns
    (reached_the_end, slot_released)."""
    from cycls._agent.web.server import Run, _supervise, _forward

    async def go():
        started, release, end = asyncio.Event(), asyncio.Event(), []

        async def stream():
            yield "a"
            started.set()
            await release.wait()
            end.append(True)
            yield "b"

        runs, key = {}, ("ws", "c1")
        run = Run(detach=detach)
        runs[key] = run
        run.task = asyncio.create_task(_supervise(run, stream(), runs, key, None))

        fwd = _forward(run)
        assert await fwd.__anext__() == "a"
        await started.wait()
        await fwd.aclose()                       # the connection drops
        await asyncio.sleep(0)                   # let a cancel land
        release.set()
        await asyncio.wait({run.task}, timeout=2)
        return bool(end), runs == {}

    return asyncio.run(go())


def test_a_dropped_connection_ends_a_run_that_did_not_opt_in():
    """Today's behaviour, kept for clients that will not poll."""
    reached_end, released = _drive_run(detach=False)
    assert not reached_end, "the run kept going for a client that cannot come back"
    assert released


def test_a_dropped_connection_leaves_a_detached_run_working():
    """The whole point: the loop outlives the request."""
    reached_end, released = _drive_run(detach=True)
    assert reached_end, "the run died with its reader"
    assert released, "the supervisor did not release the slot"


def test_the_supervisor_releases_the_slot_not_the_reader():
    """The reader ending must not free the chat — the run still owns it."""
    from cycls._agent.web.server import Run, _supervise, _forward

    async def go():
        release = asyncio.Event()
        async def stream():
            yield "a"
            await release.wait()

        runs, key = {}, ("ws", "c1")
        run = Run(detach=True)
        runs[key] = run
        run.task = asyncio.create_task(_supervise(run, stream(), runs, key, None))
        fwd = _forward(run)
        await fwd.__anext__()
        await fwd.aclose()
        await asyncio.sleep(0)
        held = key in runs                       # still running, still held
        release.set()
        await asyncio.wait({run.task}, timeout=2)
        return held, runs == {}

    held, released = asyncio.run(go())
    assert held, "the reader released a slot it does not own"
    assert released


def test_a_slow_reader_is_dropped_rather_than_stalling_the_run():
    """emit never awaits: a queue nobody drains must not hang the loop."""
    from cycls._agent.web.server import Run, QUEUE_MAX
    run = Run(detach=True)
    for i in range(QUEUE_MAX + 50):
        run.emit(i)
    assert not run.attached, "the run would have blocked on a full queue"


def test_a_finished_run_stamps_its_record_and_fires_the_hook(tmp_path):
    from cycls._agent.web.server import Run, _supervise
    from cycls._app.db import workspace as mkws
    from cycls._agent import state

    fired = []
    ws = mkws("tenant", tmp_path, base=f"file://{tmp_path}")

    async def go(boom):
        async def stream():
            yield "a"
            if boom: raise RuntimeError("boom")

        runs, key = {}, ("ws", "c1")
        run = Run(detach=True, workspace=ws, chat_id="c1", user=None)
        runs[key] = run
        run.task = asyncio.create_task(_supervise(run, stream(), runs, key, fired.append))
        await asyncio.wait({run.task}, timeout=2)
        return state.run_status(await state.get_run(ws, "c1"))

    assert asyncio.run(go(boom=False)) == "done"
    assert asyncio.run(go(boom=True)) == "failed"
    assert [f["status"] for f in fired] == ["done", "failed"]
    assert fired[0]["chat_id"] == "c1" and "ms" in fired[0]


def test_a_hook_that_raises_never_reaches_the_run(tmp_path):
    from cycls._agent.web.server import Run, _supervise
    from cycls._app.db import workspace as mkws

    async def go():
        async def stream():
            yield "a"
        def bad(row): raise RuntimeError("the deployment's webhook is down")

        runs, key = {}, ("ws", "c1")
        run = Run(detach=True, workspace=mkws("t", tmp_path, base=f"file://{tmp_path}"),
                  chat_id="c1", user=None)
        runs[key] = run
        run.task = asyncio.create_task(_supervise(run, stream(), runs, key, bad))
        await asyncio.wait({run.task}, timeout=2)
        return run.task.exception(), runs

    exc, runs = asyncio.run(go())
    assert exc is None, "a deployment's hook failed the run"
    assert runs == {}, "the slot was not released"


def test_regenerate_is_refused_while_a_run_is_live(tmp_path):
    """DELETE last-exchange deletes and renumbers every turn file. Under a live
    run that moves the slots it is appending to."""
    from cycls._agent import state
    from cycls._app.db import workspace as mkws
    from datetime import datetime, timezone

    ws = mkws("tenant", tmp_path, base=f"file://{tmp_path}")

    async def go():
        await state.put_meta(ws, "c1", {"id": "c1", "title": "t"})
        await state.append_messages(ws, "c1", [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": [{"type": "text", "text": "1"}]}], 0)
        await state.put_run(ws, "c1", {"run": "r", "status": "running",
                                       "heartbeat": datetime.now(timezone.utc).isoformat()})
        live = state.run_status(await state.get_run(ws, "c1"))
        await state.put_run(ws, "c1", {"run": "r", "status": "done"})
        return live, state.run_status(await state.get_run(ws, "c1"))

    live, after = asyncio.run(go())
    assert live == "running" and after == "done"



# ---- live polls: the presenter opens, the audience votes through the share link ----

def _poll_setup(tmp_path, audience="public", path="file/designs/pitch.deck.json"):
    svc, user, client = _share_test_app(tmp_path)
    token = client.post("/share", json={"path": path, "audience": audience}).json()["token"]
    return client, f"/share/user_test/{token}/poll"


def test_a_poll_opens_takes_one_vote_per_voter_and_tallies(tmp_path):
    client, base = _poll_setup(tmp_path)
    assert client.get(base).json() == {"open": False}                                   # nothing open yet
    opened = client.post("/polls", json={"deck": "designs/pitch.deck.json", "slide": 3, "question": "Tea or coffee?",
                                         "options": ["Tea", "Coffee", "Neither"]}).json()
    session = opened["session"]
    seen = client.get(base).json()
    assert seen == {"open": True, "session": session, "question": "Tea or coffee?", "options": ["Tea", "Coffee", "Neither"], "slide": 3}
    a, b = "a" * 32, "b" * 32
    assert client.post(f"{base}/vote", json={"session": session, "option": 1, "voter": a}).json()["counts"] == [0, 1, 0]
    assert client.post(f"{base}/vote", json={"session": session, "option": 1, "voter": b}).json()["total"] == 2
    assert client.post(f"{base}/vote", json={"session": session, "option": 0, "voter": a}).status_code == 409   # once
    assert client.get("/polls/results", params={"deck": "designs/pitch.deck.json", "session": session}).json()["counts"] == [0, 2, 0]
    assert client.get(f"{base}/results", params={"session": session}).json()["counts"] == [0, 2, 0]


def test_a_vote_is_checked(tmp_path):
    client, base = _poll_setup(tmp_path)
    session = client.post("/polls", json={"deck": "designs/pitch.deck.json", "question": "Q?", "options": ["A", "B"]}).json()["session"]
    v = "c" * 32
    assert client.post(f"{base}/vote", json={"session": "old", "option": 0, "voter": v}).status_code == 409   # another session
    assert client.post(f"{base}/vote", json={"session": session, "option": 2, "voter": v}).status_code == 400
    assert client.post(f"{base}/vote", json={"session": session, "option": True, "voter": v}).status_code == 400
    assert client.post(f"{base}/vote", json={"session": session, "option": 0, "voter": "../x"}).status_code == 400
    # A restart is a fresh session: earlier votes don't count; a closed poll takes none.
    client.post(f"{base}/vote", json={"session": session, "option": 0, "voter": v})
    fresh = client.post("/polls", json={"deck": "designs/pitch.deck.json", "question": "Q?", "options": ["A", "B"]}).json()["session"]
    assert client.post(f"{base}/vote", json={"session": fresh, "option": 1, "voter": v}).json()["counts"] == [0, 1]
    client.post("/polls/close", json={"deck": "designs/pitch.deck.json"})
    assert client.get(base).json() == {"open": False}
    assert client.post(f"{base}/vote", json={"session": fresh, "option": 0, "voter": "d" * 32}).status_code == 409
    assert client.post("/polls", json={"deck": "designs/pitch.deck.json", "question": "Q?", "options": ["only"]}).status_code == 400
    assert client.post("/polls", json={"deck": "../etc/x.deck.json", "question": "Q?", "options": ["A", "B"]}).status_code == 400


def test_polls_only_through_a_deck_share_its_audience_can_see(tmp_path):
    client, base = _poll_setup(tmp_path, path="file/notes.md")
    assert client.get(base).status_code == 404                                           # not a deck
    client, base = _poll_setup(tmp_path, audience="org:org_other")
    assert client.get(base).status_code == 401                                           # an org's link, anonymous
    assert client.get("/share/user_test/nope/poll").status_code == 404


def test_votes_are_throttled_per_address(tmp_path, monkeypatch):
    from cycls._agent.web import routers
    monkeypatch.setattr(routers, "POLL_VOTES_PER_MINUTE", 2)
    monkeypatch.setattr(routers, "_poll_hits", {})
    client, base = _poll_setup(tmp_path)
    session = client.post("/polls", json={"deck": "designs/pitch.deck.json", "question": "Q?", "options": ["A", "B"]}).json()["session"]
    codes = [client.post(f"{base}/vote", json={"session": session, "option": 0, "voter": f"{i:032x}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_renaming_a_design_takes_its_images_and_its_deck_document_with_it(tmp_path, monkeypatch):
    """A design is its .fig and what is kept beside it — its image, its slides' and pages'
    images, its PDF, its deck document. Renamed alone, the .fig left them behind under the
    old name: stale pictures, and a deck document pointing at a file that was gone."""
    deck = json.dumps({"type": "cycls.deck", "version": 1, "kind": "document", "fig": "designs/launch.fig",
                       "size": [1240, 1754], "slides": 2, "exports": ["designs/launch.pdf"]}).encode()
    root = _seed(tmp_path, {"designs/launch.fig": b"FIG", "designs/launch.png": b"PNG", "designs/launch-slide-2.png": b"S2",
                            "designs/launch-page-2.jpg": b"P2", "designs/launch.pdf": b"%PDF", "designs/launch.deck.json": deck,
                            "designs/launch-notes.txt": b"mine", "designs/launchpad.png": b"other", "designs/summer.pdf": b"KEEP"})
    client = _ws_routers_client(tmp_path)
    assert client.patch("/files/designs/launch.fig", json={"to": "designs/summer.fig"}).status_code == 200
    names = sorted(p.name for p in (root / "designs").iterdir())
    assert names == ["launch-notes.txt", "launch.pdf", "launchpad.png", "summer-page-2.jpg", "summer-slide-2.png",
                     "summer.deck.json", "summer.fig", "summer.pdf", "summer.png"]
    assert (root / "designs/summer.pdf").read_bytes() == b"KEEP"              # what was already there is not written over
    moved = json.loads((root / "designs/summer.deck.json").read_text())
    assert moved["fig"] == "designs/summer.fig" and moved["exports"] == ["designs/summer.pdf"] and moved["kind"] == "document"
    # Moved to another folder, they go there too; a file that isn't a design moves alone.
    assert client.patch("/files/designs/summer.fig", json={"to": "designs/2026/summer.fig"}).status_code == 200
    assert sorted(p.name for p in (root / "designs/2026").iterdir()) == ["summer-page-2.jpg", "summer-slide-2.png", "summer.deck.json",
                                                                          "summer.fig", "summer.pdf", "summer.png"]
    assert json.loads((root / "designs/2026/summer.deck.json").read_text())["fig"] == "designs/2026/summer.fig"
    assert client.patch("/files/designs/launch-notes.txt", json={"to": "designs/notes.txt"}).status_code == 200
    assert (root / "designs/launchpad.png").is_file()


# ---- together: a design written anew is told to the people who have it open ----

def _room_said(monkeypatch):
    from cycls._agent.design import live
    said = []

    async def notify(root, rel, body):
        said.append((rel, body))
        return {"ok": True, "peers": 2, "delivered": 2}
    monkeypatch.setattr(live, "notify", notify)
    return said


def test_restoring_a_version_tells_the_room_to_open_the_file_again(tmp_path, monkeypatch):
    from cycls._agent.design import refresh
    monkeypatch.setattr(refresh, "schedule", lambda *a, **k: None)
    said = _room_said(monkeypatch)
    client = _ws_routers_client(tmp_path)
    assert client.put("/files/designs/launch.fig", content=b"ONE").status_code == 200
    two = client.put("/files/designs/launch.fig", content=b"TWO").json()["version"]
    [kept] = client.get("/versions/designs/launch.fig").json()["versions"]
    assert said == []                                   # an editor's own save is not news to its room
    back = client.post(f"/versions/designs/launch.fig?restore={kept['id']}").json()
    assert back["version"] != two
    assert said == [("designs/launch.fig", {"kind": "reload", "version": back["version"]})]


def test_a_version_is_shown_as_a_picture_before_it_is_restored(tmp_path, monkeypatch):
    """`?id=…&as=png` on a design's versions: a picture of THAT version — made by the design
    service from the version's own bytes, not from the file as it is now — small enough for
    the versions panel. A version that isn't there is a 404; no service, a 415."""
    from cycls._agent import design
    from cycls._agent.design import refresh
    monkeypatch.setattr(refresh, "schedule", lambda *a, **k: None)
    asked = []

    async def export(fig, fmt="png", scale=2, width=None, user_id=None, every=False, page=None):
        asked.append((fig, fmt, width, every))
        return b"\x89PNG picture of " + fig
    monkeypatch.setattr(design, "export", export)
    client = _ws_routers_client(tmp_path)
    assert client.put("/files/designs/launch.fig", content=b"ONE").status_code == 200
    assert client.put("/files/designs/launch.fig", content=b"TWO").status_code == 200
    [kept] = client.get("/versions/designs/launch.fig").json()["versions"]
    r = client.get(f"/versions/designs/launch.fig?id={kept['id']}&as=png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content == b"\x89PNG picture of ONE"                       # the version, not the file now
    assert asked == [(b"ONE", "png", 640, False)]
    assert client.get(f"/versions/designs/launch.fig?id={kept['id']}").content == b"ONE"   # its bytes, as before
    assert client.get("/versions/designs/launch.fig?id=20200101T000000-abcdef&as=png").status_code == 404

    async def down(*a, **k):
        raise design.Unavailable("design not configured (DESIGN_URL)")
    monkeypatch.setattr(design, "export", down)
    assert client.get(f"/versions/designs/launch.fig?id={kept['id']}&as=png").status_code == 415


def test_a_change_made_in_the_deck_viewer_is_the_persons_in_the_version_history(tmp_path, monkeypatch):
    """What a slide change replaced is kept as a version. Made in the deck viewer it was
    listed as the agent's ("Before an agent edit · Agent") — the person had done it."""
    from cycls._agent import design
    from cycls._agent.design import deck as decks, refresh
    root = _seed(tmp_path, {"designs/pitch.fig": b"FIG", "designs/pitch.deck.json": _DECK_DOC})
    monkeypatch.setattr(refresh, "schedule", lambda *a, **k: None)
    turn = iter([b"ONE", b"TWO"])

    async def apply(fig, script=None, user_id=None, ops=None, preview=False):
        return {"fig": next(turn), "lint": [], "script": "S", "preview": None, "previews": [], "touched": [], "slides": [{}] * 2}
    monkeypatch.setattr(design, "apply", apply)
    client = _ws_routers_client(tmp_path)
    assert client.post("/deck/designs/pitch.fig", json={"op": "notes", "number": 2, "notes": "Say hello"}).status_code == 200
    [mine] = client.get("/versions/designs/pitch.fig").json()["versions"]
    assert (mine["by"], mine["reason"], mine["intent"]) == ("user", "change", "slide 2's notes")
    # The agent's own slide change is still the agent's.
    asyncio.run(decks.apply_ops(root, "pitch", [{"op": "slide_move", "index": 0, "to": 1}], user_id="u"))
    newest = client.get("/versions/designs/pitch.fig").json()["versions"][0]
    assert (newest["by"], newest["reason"], newest["intent"]) == ("agent", "agent", "move slide 1")


def test_a_slide_moved_in_the_deck_viewer_tells_the_room_to_open_the_file_again(tmp_path, monkeypatch):
    from cycls._agent.design import deck as decks
    from cycls._agent.design.store import version_of
    said = _room_said(monkeypatch)

    async def apply_ops(root, name, ops, user_id=None, preview=False, by="agent"):
        return {"slides": [{}, {}], "version": version_of(b"MOVED")}
    monkeypatch.setattr(decks, "apply_ops", apply_ops)
    client = _ws_routers_client(tmp_path)
    client.put("/files/designs/pitch.fig", content=b"DECK")
    r = client.post("/deck/designs/pitch.fig", json={"op": "move", "number": 1, "to": 2})
    assert r.status_code == 200
    assert said == [("designs/pitch.fig", {"kind": "reload", "version": version_of(b"MOVED")})]


def test_the_design_routes_are_a_router_of_their_own(tmp_path):
    """The routes that act on a design — and the helpers that serve one — are in
    web/design_routes.py; the files router keeps the file routes. Mounted together they
    answer as before, and the names the routes file used to define are still its."""
    from fastapi import Depends
    from cycls._agent.web import design_routes, routers, shared
    paths = lambda router: {route.path for route in router.routes}
    design = paths(design_routes.design_router(Depends(lambda: None), Depends(lambda: None), lambda root: None))
    assert design == {"/deck/{path:path}", "/design/new", "/design/export", "/design/live", "/brand", "/versions/{path:path}"}
    from types import SimpleNamespace
    files = paths(routers.files_router(SimpleNamespace(config=None), Depends(lambda: None), Depends(lambda: None), tmp_path, ""))
    assert not design & files and "/files/{path:path}" in files
    assert routers.resolve_path is shared.resolve_path and routers._NO_CACHE is shared._NO_CACHE
    assert routers._design_response is design_routes._design_response
    # Mounted: a design route answers through the app the routers are installed on.
    client = _ws_routers_client(tmp_path)
    assert client.get("/brand").json() == {"brand": None}
    assert client.get("/versions/designs/none.fig").json() == {"versions": []}

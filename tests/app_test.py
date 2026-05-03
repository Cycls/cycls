"""Tests for the bare @cycls.app decorator: user function returns an ASGI app."""
from urllib.parse import parse_qs, urlparse

import cycls
from cycls.app import App
from cycls.app.auth import User
from cycls.app.tenancy import workspace_at, subject_for


def test_app_decorator_returns_app():
    @cycls.app()
    def my_service():
        from fastapi import FastAPI
        return FastAPI()

    assert isinstance(my_service, App)
    assert my_service.name == "my-service"


def test_app_custom_name():
    @cycls.app(name="custom-name")
    def my_service():
        return object()

    assert my_service.name == "custom-name"


def test_app_is_callable():
    @cycls.app()
    def simple():
        return "asgi-app-sentinel"

    assert simple() == "asgi-app-sentinel"


def test_app_pip_merged_with_base():
    @cycls.app(image=cycls.Image().pip("httpx"))
    def svc():
        return None

    assert "httpx" in svc.pip
    assert any("uvicorn" in p for p in svc.pip)


def test_app_rejects_non_jwt_auth():
    """App.auth must be a cycls.JWT instance (e.g. Clerk) or None."""
    import pytest
    with pytest.raises(TypeError):
        @cycls.app(auth=True)
        def svc():
            return None


def test_app_accepts_jwt_auth_and_exposes_deps():
    """auth=cycls.Clerk(...) wires app.auth and app.workspace as FastAPI Depends."""
    @cycls.app(auth=cycls.Clerk())
    def svc():
        from fastapi import FastAPI
        return FastAPI()

    # Both deps are FastAPI Depends instances, lazily built.
    from fastapi.params import Depends as DependsParam
    assert isinstance(svc.auth, DependsParam)
    assert isinstance(svc.workspace, DependsParam)


def test_app_no_auth_means_deps_raise():
    """Accessing .auth or .workspace without configuring auth raises."""
    import pytest
    @cycls.app()
    def svc():
        return object()

    with pytest.raises(RuntimeError, match="auth=..."):
        _ = svc.auth
    with pytest.raises(RuntimeError, match="auth=..."):
        _ = svc.workspace


# ---- Signed-URL surface ----

def _app(tmp_path):
    @cycls.app(image={"volume": str(tmp_path)})
    def svc():
        return None
    return svc


def test_subject_personal_user():
    assert subject_for(User(id="user_abc")) == "user_abc"


def test_subject_org_member():
    assert subject_for(User(id="user_abc", org_id="org_xyz")) == "org_xyz/user_abc"


def test_workspace_for_subject_inverse(tmp_path):
    """`workspace_at(subject_for(u))` reproduces `workspace_for(u)`."""
    from cycls.app.tenancy import workspace_for
    for u in [User(id="user_abc"), User(id="user_abc", org_id="org_xyz")]:
        ws_a = workspace_for(u, tmp_path)
        ws_b = workspace_at(subject_for(u), tmp_path)
        assert ws_a == ws_b


def test_signed_url_roundtrip_personal(tmp_path):
    app = _app(tmp_path)
    user = User(id="user_abc")
    url = app.signed_url("chat/c1", user, ttl=3600)
    q = parse_qs(urlparse(url).query)
    assert q["user"] == ["user_abc"]
    assert q["path"] == ["chat/c1"]
    assert app.verify_signed(q["path"][0], q["user"][0], int(q["exp"][0]), q["sig"][0])


def test_signed_url_roundtrip_org_member(tmp_path):
    """File paths live in the URL path (so the browser hits the binary route);
    signature still binds the literal `file/<path>` string."""
    app = _app(tmp_path)
    user = User(id="user_abc", org_id="org_xyz")
    url = app.signed_url("file/notes.md", user, ttl=3600)
    parsed = urlparse(url)
    assert parsed.path == "/shared/file/notes.md"
    q = parse_qs(parsed.query)
    assert q["user"] == ["org_xyz/user_abc"]
    assert "path" not in q
    assert app.verify_signed("file/notes.md", q["user"][0], int(q["exp"][0]), q["sig"][0])


def test_signed_url_tampering_fails(tmp_path):
    app = _app(tmp_path)
    url = app.signed_url("chat/c1", User(id="u"), ttl=3600)
    q = parse_qs(urlparse(url).query)
    assert not app.verify_signed("chat/other", q["user"][0], int(q["exp"][0]), q["sig"][0])
    assert not app.verify_signed(q["path"][0], "imposter", int(q["exp"][0]), q["sig"][0])


def test_signed_url_expired(tmp_path):
    app = _app(tmp_path)
    url = app.signed_url("chat/c1", User(id="u"), ttl=-10)  # already expired
    q = parse_qs(urlparse(url).query)
    assert not app.verify_signed(q["path"][0], q["user"][0], int(q["exp"][0]), q["sig"][0])


def test_signing_key_persists_across_property_access(tmp_path):
    app = _app(tmp_path)
    k1 = app.signing_key
    # cached_property — same instance returns same bytes
    assert app.signing_key is k1
    # And on a fresh App instance pointed at the same volume, the file persists
    app2 = _app(tmp_path)
    assert app2.signing_key == k1

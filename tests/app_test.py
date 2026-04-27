"""Tests for the bare @cycls.app decorator: user function returns an ASGI app."""
import cycls
from cycls.app import App


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
    @cycls.app(auth=cycls.Clerk("cycls.ai"))
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

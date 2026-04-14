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


def test_app_build_asgi_delegates_to_user_func():
    sentinel = object()

    @cycls.app()
    def svc():
        return sentinel

    assert svc._build_asgi() is sentinel


def test_app_pip_merged_with_base():
    @cycls.app(pip=["httpx"])
    def svc():
        return None

    assert "httpx" in svc.pip
    assert any("uvicorn" in p for p in svc.pip)


def test_app_no_chat_kwargs():
    """App should not accept chat-product kwargs — those live on @cycls.agent."""
    import pytest
    with pytest.raises(TypeError):
        @cycls.app(auth=True)
        def svc():
            return None

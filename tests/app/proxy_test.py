"""Behind Cloud Run the app must see https:// — an OAuth redirect_uri built
from request.base_url otherwise never matches what the provider registered."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from cycls._app.main import _behind_proxy

pytest.importorskip("uvicorn")


def test_forwarded_proto_reaches_the_app():
    app = FastAPI()

    @app.get("/")
    def base(request: Request):
        return {"base": str(request.base_url)}

    client = TestClient(_behind_proxy(app))
    assert client.get("/").json()["base"] == "http://testserver/"
    assert client.get("/", headers={"x-forwarded-proto": "https"}).json()["base"] == "https://testserver/"

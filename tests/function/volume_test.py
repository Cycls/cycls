import json

import pytest

import cycls
from cycls.function.volume import to_wire


def test_volume_wire_form():
    assert cycls.Volume("data")._wire() == {"name": "data"}
    v = cycls.Volume("data").read_only().sub_path("users/123")
    assert v._wire() == {"name": "data", "read_only": True, "sub_path": "users/123"}


def test_volume_builders_are_immutable():
    base = cycls.Volume("data")
    ro = base.read_only()
    assert base._wire() == {"name": "data"}
    assert ro._wire() == {"name": "data", "read_only": True}


def test_to_wire_requires_volume_objects():
    wire = to_wire({"/scratch": cycls.Volume("scratch"), "/models": cycls.Volume("ml").read_only()})
    assert json.loads(wire) == {
        "/scratch": {"name": "scratch"},
        "/models": {"name": "ml", "read_only": True},
    }
    with pytest.raises(TypeError, match="cycls.Volume\\('shared'\\)"):
        to_wire({"/data": "shared"})


def test_function_spec_carries_volumes_only_when_set():
    @cycls.function(volumes={"/data": cycls.Volume("shared")})
    def with_volumes():
        pass

    @cycls.function()
    def without_volumes():
        pass

    @cycls.function(volumes={})
    def no_storage():
        pass

    assert json.loads(with_volumes.spec["volumes"]) == {"/data": {"name": "shared"}}
    assert "volumes" not in without_volumes.spec
    assert no_storage.spec["volumes"] == "{}"


def test_app_storage_resolves_through_platform_mapping(monkeypatch):
    app = cycls.App(func=lambda: None, name="myapp",
                    volumes={"/workspace": cycls.Volume("myapp-data")})
    app.prod = True

    monkeypatch.setenv("CYCLS_VOLUMES", json.dumps({"/workspace": "cycls-vol-ab12-myapp-data-9f9f9f"}))
    assert app.storage == "gs://cycls-vol-ab12-myapp-data-9f9f9f"

    monkeypatch.setenv("CYCLS_VOLUMES", json.dumps({"/data": "cycls-vol-ab12-other-111111"}))
    with pytest.raises(RuntimeError, match="No volume mounted at /workspace"):
        app.storage

    monkeypatch.delenv("CYCLS_VOLUMES")
    with pytest.raises(RuntimeError, match="No volume mounted at /workspace"):
        app.storage

    app.prod = False
    assert app.storage == "file:///workspace"


def test_agent_config_storage_resolves_through_platform_mapping(monkeypatch):
    from cycls.agent.web.server import Config

    config = Config(name="bot")
    config.set_prod(True)

    monkeypatch.setenv("CYCLS_VOLUMES", json.dumps({"/workspace": "cycls-vol-ab12-bot-chats-9f9f9f"}))
    assert config.storage == "gs://cycls-vol-ab12-bot-chats-9f9f9f"

    monkeypatch.delenv("CYCLS_VOLUMES")
    with pytest.raises(RuntimeError, match="agent state needs one"):
        config.storage


def test_agent_requires_an_explicit_workspace_volume():
    with pytest.raises(ValueError, match="chat state"):
        cycls.Agent(func=lambda: None, name="bot")

    with pytest.raises(ValueError, match="chat state"):
        cycls.Agent(func=lambda: None, name="bot", volumes={"/data": cycls.Volume("d")})

    agent = cycls.Agent(func=lambda: None, name="bot",
                        volumes={"/workspace": cycls.Volume("bot-chats"),
                                 "/data": cycls.Volume("shared").read_only()})
    assert json.loads(agent.spec["volumes"]) == {
        "/workspace": {"name": "bot-chats"},
        "/data": {"name": "shared", "read_only": True},
    }

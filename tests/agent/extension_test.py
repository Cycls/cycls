"""cycls.Extension — a package's tool and routes, declared once on the agent's Web."""
import asyncio

import pytest

import cycls
from cycls._agent import extension, tools
from cycls._app.db import workspace


class Lamp(cycls.Extension):
    """A small extension: one tool, one route, configured by a flag."""
    name = "Lamp"
    on = True

    def configured(self):
        return self.on

    def tools(self):
        schema = {"type": "custom", "name": "lamp", "description": "Switch the lamp.",
                  "input_schema": {"type": "object", "properties": {"state": {"type": "string"}}}}

        async def run(inp, ws, **_):
            (ws.root / "lamp.txt").write_text(inp.get("state", "on"))
            return {"_model": f"lamp {inp.get('state', 'on')}", "_ui": {"type": "ui", "action": "app_command",
                                                                      "path": "apps/lamp/index.html", "command": {}}}
        return {"lamp": (schema, extension.Tool(run, lambda inp: {"tool_name": "Lamp", "step": inp.get("state", "")},
                                                prompt="## Lamp\nSwitch it off at night.",
                                                interrupted="The lamp may have switched."))}

    def router(self, workspace, user):
        from fastapi import APIRouter
        r = APIRouter()

        @r.get("/apps/lamp/state")
        async def state(ws=workspace, who=user):
            p = ws.root / "lamp.txt"
            return {"state": p.read_text() if p.exists() else None, "user": who}
        return r


@pytest.fixture(autouse=True)
def clean():
    yield
    for name, owner in list(extension._owners.items()):
        tools._TOOLS.pop(name, None)
    extension._owners.clear()
    extension._registered.clear()


def _ws(tmp_path):
    return workspace(tmp_path.name, tmp_path.parent, base=f"file://{tmp_path}")


def test_registered_tools_are_offered_while_configured():
    lamp = Lamp()
    extension.register(lamp)
    assert [t["name"] for t in tools.build_tools(["Lamp"], [])] == ["lamp"]
    lamp.on = False
    assert tools.build_tools(["Lamp"], []) == []
    assert tools.build_tools(["Nope"], []) == []                  # an unknown name stays silent


def test_a_row_like_a_builtins(tmp_path):
    extension.register(Lamp())
    ws = _ws(tmp_path)
    step, aw = tools.dispatch({"id": "t1", "name": "lamp", "input": {"state": "off"}}, ws, 10)
    assert step == {"type": "step", "id": "t1", "tool_name": "Lamp", "step": "off"}
    assert asyncio.run(aw)["_model"] == "lamp off" and (ws.root / "lamp.txt").read_text() == "off"
    assert "## Lamp" in "\n".join(tools.tool_prompts([{"name": "lamp"}]))
    assert tools.interrupted_note("lamp", "stopped").endswith("The lamp may have switched.")


def test_names_are_its_own():
    class Thief(Lamp):
        name = "Thief"
    extension.register(Lamp())
    extension.register(Lamp())                                     # again: fine
    with pytest.raises(ValueError, match="taken"):
        extension.register(Thief())
    with pytest.raises(ValueError, match="taken"):
        class Bash(Lamp):
            name = "Shell"

            def tools(self):
                return {"bash": ({"name": "bash"}, extension.Tool(None, None))}
        extension.register(Bash())


def test_every_run_offers_it_unless_switched_off():
    extension.register(Lamp())
    seen = []

    async def loop(**kw):
        seen.append(kw["allowed_tools"])
        yield "done"

    class Ctx:
        disabled_tools = []

    llm = cycls.LLM().model("anthropic/x").allowed_tools(["Bash"]).loop(loop)

    async def drain(ctx):
        return [e async for e in llm.run(context=ctx)]
    asyncio.run(drain(Ctx()))
    Ctx.disabled_tools = ["Lamp"]
    asyncio.run(drain(Ctx()))
    assert seen == [["Bash", "Lamp"], ["Bash"]]


def test_web_use_and_auth():
    with pytest.raises(TypeError):
        cycls.Web().use(object())
    web = cycls.Web().use(Lamp(), Lamp())
    assert [e.name for e in web._extensions] == ["Lamp"]
    with pytest.raises(ValueError, match="auth"):
        cycls.Agent(lambda c: None, "lamp-agent", web=web, volumes={"/workspace": cycls.Volume("x")})


def test_server_registers_and_mounts(tmp_path):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls._agent.web import routers

    class _App:
        config = None
        connectors = None
        extensions = [Lamp()]

    def user():
        return cycls.User(id="u1")
    app = FastAPI()
    routers.install_routers(_App(), app, Depends(user), tmp_path, f"file://{tmp_path}")
    assert extension.names() == ["Lamp"]
    r = TestClient(app).get("/apps/lamp/state").json()
    assert r["state"] is None and r["user"]["id"] == "u1"

    class _Off(_App):
        extensions = [type("Off", (Lamp,), {"on": False})()]
    app = FastAPI()
    routers.install_routers(_Off(), app, Depends(user), tmp_path, f"file://{tmp_path}")
    assert "/apps/lamp/state" not in app.openapi()["paths"]


def test_build_app_leaves_an_extensions_app_alone(tmp_path):
    (tmp_path / "apps/lamp").mkdir(parents=True)
    (tmp_path / "apps/lamp/app.json").write_text('{"extension": "Lamp"}')
    out = asyncio.run(tools._exec_build_app({"slug": "lamp", "source": "src"}, _ws(tmp_path)))
    assert out.startswith("Error: apps/lamp is the Lamp app")


def test_app_data_helpers(tmp_path):
    from cycls._agent.state import actor_of, app_shelf, apps_db
    ws = _ws(tmp_path)

    async def go():
        db = apps_db(ws)
        await db.put(app_shelf("lamp", "view", user=actor_of(ws.subject)), {"selection": ["a"]})
        await db.put(app_shelf("lamp", "shared"), 1)
        mine = await extension.app_get(ws, "lamp", "view", mine=True)
        shared = await extension.app_get(ws, "lamp", "shared")
        await extension.app_reset(ws, "lamp")
        return mine, shared, await extension.app_get(ws, "lamp", "shared")
    assert asyncio.run(go()) == ({"selection": ["a"]}, 1, None)
    with pytest.raises(ValueError):
        extension.resolve_path("../x", tmp_path)

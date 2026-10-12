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

    def opens(self):
        return ("lamp", "PDF")                                    # a pdf is the canvas's own: not claimed

    async def open(self, workspace, path):
        if path.endswith("broken.lamp"):
            raise ValueError("that lamp is broken")
        (workspace.root / "apps/lamp").mkdir(parents=True, exist_ok=True)
        return {"app": "apps/lamp/index.html", "command": {"type": "open_file", "path": path}}


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


def test_a_file_its_app_opens(tmp_path):
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
    assert extension.openers() == {"lamp": "Lamp", "pdf": "Lamp"} and extension.opener("a/Desk.LAMP").name == "Lamp"
    assert extension.opener("notes.txt") is None and extension.opener("lamp") is None
    root = workspace(cycls.User(id="u1"), tmp_path, base=f"file://{tmp_path}").root
    (root / "models").mkdir(parents=True)
    for name in ("desk.lamp", "broken.lamp", "paper.pdf", "notes.bin"):
        (root / "models" / name).write_text("x")
    c = TestClient(app)

    # The browser is told which files open in an app: those no canvas shows. A pdf stays the canvas's.
    from cycls._agent.web.server import Config
    assert routers.app_opens() == {"lamp": "Lamp"} and Config().public()["opens"] == {"lamp": "Lamp"}

    r = c.post("/apps/open", json={"path": "models/desk.lamp"})
    assert r.status_code == 200 and r.json() == {
        "app": "apps/lamp/index.html", "name": "Lamp", "changed": False,
        "command": {"type": "open_file", "path": "models/desk.lamp"}}
    assert (root / "apps/lamp").is_dir()
    assert c.post("/apps/open", json={"path": "models/broken.lamp"}).json() == {"detail": "that lamp is broken"}
    for path in ("models/notes.bin", "models/paper.pdf", "models/gone.lamp", "../desk.lamp", ""):
        assert c.post("/apps/open", json={"path": path}).status_code in (400, 404), path

    # Switched off (unconfigured), it claims nothing.
    _App.extensions[0].on = False
    assert extension.openers() == {} and "opens" not in Config().public()
    assert c.post("/apps/open", json={"path": "models/desk.lamp"}).status_code == 404


def test_an_app_it_names_is_an_app(tmp_path):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls._agent.web import routers

    class Elsewhere(Lamp):
        async def open(self, workspace, path):
            return {"app": "AGENT.md", "command": {}}

    class _App:
        config = None
        connectors = None
        extensions = [Elsewhere()]
    app = FastAPI()
    routers.install_routers(_App(), app, Depends(lambda: cycls.User(id="u1")), tmp_path, f"file://{tmp_path}")
    root = workspace(cycls.User(id="u1"), tmp_path, base=f"file://{tmp_path}").root
    root.mkdir(parents=True, exist_ok=True)
    (root / "desk.lamp").write_text("x")
    assert TestClient(app).post("/apps/open", json={"path": "desk.lamp"}).status_code == 404


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

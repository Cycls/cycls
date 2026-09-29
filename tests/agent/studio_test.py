"""The `studio` tool and its plumbing, with the Blender engine faked."""
import asyncio
import base64
import json
import pathlib

import cycls
import pytest

from cycls._agent import tools
from cycls._agent.studio import install, store, tool
from cycls._agent.studio import scene as S
from cycls._app.db import workspace

PNG = b"\x89PNG\r\n\x1a\nfake"
JPG = b"\xff\xd8\xff\xe0fake-jpeg"


def _ws(root):
    return workspace(root.name, root.parent, base=f"file://{root}")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("CYCLS_STUDIO_ENGINE", "cycls-render")
    monkeypatch.setenv("CYCLS_API_KEY", "test-key")
    monkeypatch.delenv("CYCLS_STUDIO_RENDERER", raising=False)
    monkeypatch.setattr(tool, "_view", _no_view)


async def _no_view(ws):
    return {}


def _viewing(monkeypatch, view):
    async def fake(ws):
        return view
    monkeypatch.setattr(tool, "_view", fake)


@pytest.fixture
def root(tmp_path):
    return tmp_path


class FakeEngine:
    """Records calls; answers each op the way cycls-render does."""

    def __init__(self):
        self.calls = []
        self.fail = None

    def __call__(self, name, timeout=None):
        def fn(**kw):
            self.calls.append({"name": name, **kw})
            if self.fail:
                return {"ok": False, "error": self.fail}
            op = kw["op"]
            if op == "snapshot":
                return {"ok": True, "result": {"preview": "preview.jpg", "resolution": [640, 360]},
                        "files": {"preview.jpg": JPG}}
            if op == "render":
                return {"ok": True, "result": {"png": "render.png", "preview": "preview.jpg",
                                               "render_seconds": 23.4, "resolution": [1280, 720], "samples": 32},
                        "files": {"render.png": PNG, "preview.jpg": JPG}}
            if op == "apply":
                return {"ok": True, "result": {"mesh_id": "m-0123456789ab", "mesh": "mesh.json", "verts": 12,
                                               "faces": 10, "bbox": [[-1, -1, -1], [1, 1, 1]],
                                               "modifiers": [] if kw["params"]["op"] == "modifier_apply" else None,
                                               "removed": kw["params"].get("others", []),
                                               **({"selection": {"faces": [2, 3]}} if kw["params"]["op"] == "bevel" else {})},
                        "files": {"mesh.json": b'{"format": "cycls.mesh"}'}}
            if op == "script":
                doc, _ = S.apply_ops(kw["scene"], [{"op": "add", "id": "scripted", "type": "empty"}])
                return {"ok": True, "result": {"scene": doc, "notes": ["curve baked"], "stdout": "hello\n"},
                        "files": {}}
            if op == "import":
                frag = S.normalize({"objects": {"cube": {"type": "mesh", "mesh": "m-aaaaaaaaaaaa"}},
                                    "meshes": {"m-aaaaaaaaaaaa": {"data": "meshes/m-aaaaaaaaaaaa.json"}}})
                return {"ok": True, "result": {"scene": frag, "notes": []},
                        "files": {"meshes_out/m-aaaaaaaaaaaa.json": b'{"format": "cycls.mesh"}'}}
            if op == "export":
                ext = kw["params"]["format"]
                return {"ok": True, "result": {"file": f"export.{ext}", "format": ext},
                        "files": {f"export.{ext}": b"model-bytes"}}
            raise AssertionError(op)
        return fn


@pytest.fixture
def engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(cycls, "remote", fake)
    return fake


def run(inp, root):
    return asyncio.run(tool.run(inp, _ws(root)))


def scene(root):
    return json.loads((root / "apps/studio/data/scene.json").read_text())


def _text(out):
    if isinstance(out, str):
        return out
    m = out["_model"]
    return m if isinstance(m, str) else " ".join(b.get("text", "") for b in m)


def _uis(out):
    ui = out.get("_ui") if isinstance(out, dict) else None
    return ui if isinstance(ui, list) else [ui] if ui else []


# ─── gate + registry ────────────────────────────────────────────────────────

def test_build_tools_gates_on_engine_and_key(monkeypatch):
    assert [t["name"] for t in tools.build_tools(["Studio"], [], vendor="openai")] == ["studio"]
    monkeypatch.delenv("CYCLS_STUDIO_ENGINE")
    assert tools.build_tools(["Studio"], [], vendor="openai") == []
    monkeypatch.setenv("CYCLS_STUDIO_ENGINE", "cycls-render")
    monkeypatch.delenv("CYCLS_API_KEY")
    monkeypatch.setattr(cycls, "api_key", None, raising=False)
    assert tools.build_tools(["Studio"], [], vendor="openai") == []


def test_registered_with_guidance_and_label():
    assert "studio" in tools._TOOLS
    assert "## Studio (3D)" in "\n".join(tools.tool_prompts([tool.STUDIO_TOOL]))
    assert tools.tool_step("studio", {"action": "edit", "intent": "gold ring"}) == \
        {"tool_name": "Studio", "step": "edit gold ring"}
    assert tools.tool_step("studio", {"action": "edit", "ops": [{}, {}]})["step"] == "edit 2 op(s)"
    assert tools.risk("studio", {"action": "edit"}) is None


# ─── installer ──────────────────────────────────────────────────────────────

class TestInstall:
    def test_fresh_install(self, root):
        assert asyncio.run(install.ensure_installed(_ws(root))) == "installed"
        app = root / "apps/studio"
        assert (app / "index.html").read_text().startswith("<!doctype html>")
        manifest = json.loads((app / "app.json").read_text())
        assert manifest["name"] == "Studio" and manifest["studio"]["version"] == install.bundle()[1]
        assert "Change it with the `studio`" in (app / "README.md").read_text().replace("**", "")
        assert S.normalize(scene(root)) == S.new_scene()

    def test_idempotent_and_upgrades_the_bundle_only(self, root, tmp_path, monkeypatch):
        ws = _ws(root)
        asyncio.run(install.ensure_installed(ws))
        (root / "apps/studio/data/scene.json").write_text(json.dumps({**S.new_scene(), "rev": 7}))
        (root / "apps/studio/data/mine.json").write_text("{}")
        assert asyncio.run(install.ensure_installed(ws)) is None
        newer = tmp_path / "bundle.html"
        newer.write_text("<!doctype html><p>v2</p>")
        monkeypatch.setattr(install, "BUNDLE", newer)
        assert asyncio.run(install.ensure_installed(ws)) == "upgraded"
        assert (root / "apps/studio/index.html").read_text() == "<!doctype html><p>v2</p>"
        assert list(root.glob(".trash/**/index.html")), "the old bundle goes to the trash"
        assert scene(root)["rev"] == 7 and (root / "apps/studio/data/mine.json").exists()

    def test_refuses_someone_elses_app(self, root):
        app = root / "apps/studio"
        app.mkdir(parents=True)
        (app / "index.html").write_text("<h1>mine</h1>")
        with pytest.raises(install.InstallError, match="another app"):
            asyncio.run(install.ensure_installed(_ws(root)))
        assert "Error: apps/studio/ is another app" in run({"action": "inspect"}, root)

    def test_build_app_will_not_overwrite_studio(self, root, monkeypatch):
        asyncio.run(install.ensure_installed(_ws(root)))
        src = root / "src"
        src.mkdir()
        (src / "index.html").write_text("<h1>x</h1>")
        monkeypatch.setattr(cycls, "remote", lambda name, **_: (lambda **kw: {"ok": True, "html": "<h1>built</h1>"}))
        out = asyncio.run(tools._exec_build_app({"slug": "studio", "source": "src"}, _ws(root)))
        assert out.startswith("Error: apps/studio is the built-in Studio")


# ─── document actions ───────────────────────────────────────────────────────

class TestEdit:
    OPS = [{"op": "add", "id": "ring", "primitive": "torus", "material": "gold", "on_floor": True},
           {"op": "preset", "studio": {"lighting": "dramatic"}}]

    def test_edit_saves_pushes_a_patch_and_keeps_history(self, root):
        out = run({"action": "edit", "ops": self.OPS, "intent": "gold ring"}, root)
        assert "Saved rev 1" in _text(out) and "objects.ring" in _text(out)
        doc = scene(root)
        assert doc["rev"] == 1 and doc["by"] == "agent" and "ring" in doc["objects"]
        (ui,) = _uis(out)
        assert ui["action"] == "app_command" and ui["path"] == "apps/studio/index.html"
        cmd = ui["command"]
        assert cmd["type"] == "patch" and cmd["base"] == 0 and cmd["rev"] == 1 and cmd["label"] == "gold ring"
        assert "objects.ring" in cmd["set"] and "objects.studio_key" in cmd["set"]
        assert (root / "apps/studio/data/history/0.json").exists()

    def test_a_bad_op_names_the_field_and_saves_nothing(self, root):
        out = run({"action": "edit", "ops": [{"op": "add", "primitive": "teapot"}]}, root)
        assert out.startswith("Error: ops[0]") and "meshes.teapot.primitive" in out
        assert scene(root)["rev"] == 0

    def test_no_change(self, root):
        run({"action": "edit", "ops": [{"op": "set", "id": "cube", "location": [0, 0, 3]}]}, root)
        out = run({"action": "edit", "ops": [{"op": "set", "id": "cube", "location": [0, 0, 3]}]}, root)
        assert out.startswith("No change")

    def test_selected_is_the_viewers_selection(self, root, monkeypatch):
        _viewing(monkeypatch, {"selection": ["cube"], "mode": "object"})
        run({"action": "edit", "ops": [{"op": "material", "preset": "chrome", "assign": "selected"}]}, root)
        assert scene(root)["objects"]["cube"]["material"] == "chrome"
        assert "[selected]" in run({"action": "inspect"}, root)

    def test_parallel_edits_serialize(self, root):
        ws = _ws(root)

        async def both():
            await install.ensure_installed(ws)
            await asyncio.gather(*[tool.run({"action": "edit", "ops": [
                {"op": "add", "id": f"c{i}", "primitive": "cube", "location": [i, 0, 0]}]}, ws) for i in range(6)])
        asyncio.run(both())
        doc = scene(root)
        assert doc["rev"] == 6 and all(f"c{i}" in doc["objects"] for i in range(6))

    def test_revert(self, root):
        run({"action": "edit", "ops": self.OPS}, root)
        out = run({"action": "revert", "rev": 0}, root)
        assert "rev 0" in _text(out) and "ring" not in scene(root)["objects"] and scene(root)["rev"] == 2

    def test_inspect_and_open(self, root):
        assert "Scene rev 0" in run({"action": "inspect"}, root)
        run({"action": "edit", "ops": self.OPS}, root)
        out = run({"action": "open"}, root)
        assert out["action"] == "open_canvas" and out["path"] == "apps/studio/index.html"
        assert "Scene rev 1" in out["ack"] and "- ring (mesh torus" in out["ack"]     # not "empty"


# ─── engine actions ─────────────────────────────────────────────────────────

class TestEngine:
    def test_snapshot_sends_the_scene_and_returns_the_image(self, root, engine):
        out = run({"action": "snapshot"}, root)
        call = engine.calls[-1]
        assert call["name"] == "cycls-render" and call["op"] == "snapshot" and call["scene"]["format"] == S.FORMAT
        assert out["_model"][0]["source"]["data"] == base64.b64encode(JPG).decode()
        assert _uis(out)[0]["command"]["preview"].startswith("data:image/jpeg;base64,")

    def test_edit_with_snapshot(self, root, engine):
        out = run({"action": "edit", "ops": [{"op": "delete", "id": "light"}], "snapshot": True}, root)
        assert out["_model"][0]["type"] == "image" and len(_uis(out)) == 2

    def test_render_saves_logs_and_opens(self, root, engine, monkeypatch):
        monkeypatch.setenv("CYCLS_STUDIO_RENDERER", "cycls-render-big")
        out = run({"action": "render", "name": "Gold Ring"}, root)
        assert engine.calls[-1]["name"] == "cycls-render-big"
        assert (root / "renders/gold-ring.png").read_bytes() == PNG
        log = json.loads((root / "apps/studio/data/renders.json").read_text())
        assert log[-1]["path"] == "renders/gold-ring.png" and log[-1]["samples"] == 32
        opened, done = _uis(out)
        assert opened["action"] == "open_canvas" and done["command"]["type"] == "render_done"
        run({"action": "render", "name": "Gold Ring"}, root)
        assert (root / "renders/gold-ring-2.png").exists()

    def test_apply_writes_the_mesh_and_rewires_the_object(self, root, engine):
        out = run({"action": "apply", "id": "cube", "operation": "bevel",
                   "params": {"selection": "all", "width": 0.1}}, root)
        assert "Applied bevel to cube" in _text(out)
        assert engine.calls[-1]["params"] == {"id": "cube", "op": "bevel", "selection": "all", "width": 0.1}
        doc = scene(root)
        assert doc["objects"]["cube"]["mesh"] == "m-0123456789ab"
        assert doc["meshes"] == {"m-0123456789ab": {"data": "meshes/m-0123456789ab.json", "verts": 12,
                                                    "faces": 10, "bbox": [[-1, -1, -1], [1, 1, 1]]}}
        assert (root / "apps/studio/data/meshes/m-0123456789ab.json").exists()
        # The next engine call carries the mesh file with the scene.
        run({"action": "snapshot"}, root)
        assert list(engine.calls[-1]["blobs"]) == ["meshes/m-0123456789ab.json"]

    def test_apply_on_the_viewers_edit_selection(self, root, engine, monkeypatch):
        edit = {"object": "cube", "mesh": "cube", "mode": "face", "items": [5, 2], "count": 2}
        _viewing(monkeypatch, {"selection": ["cube"], "mode": "edit", "edit": edit})
        assert "Edit mode on cube: 2 faces selected" in run({"action": "inspect"}, root)
        run({"action": "apply", "id": "selected", "operation": "bevel", "params": {"selection": "selected"}}, root)
        assert engine.calls[-1]["params"] == {"id": "cube", "op": "bevel", "selection": {"faces": [5, 2]}}

    def test_edit_selection_on_another_mesh_is_refused(self, root, engine, monkeypatch):
        # The app hasn't saved its mesh yet: its indices are about geometry the scene doesn't have.
        edit = {"object": "cube", "mesh": "m-ffffffffffff", "mode": "vert", "items": [0], "count": 1}
        _viewing(monkeypatch, {"selection": ["cube"], "mode": "edit", "edit": edit})
        assert "Edit mode" not in run({"action": "inspect"}, root)
        out = run({"action": "apply", "id": "cube", "operation": "subdivide", "params": {"selection": "selected"}}, root)
        assert out.startswith("Error: nothing is selected in Edit mode on cube") and not engine.calls

    def test_edit_selection_too_big_to_pass_on(self, root, engine, monkeypatch):
        edit = {"object": "cube", "mesh": "cube", "mode": "vert", "items": None, "count": 90000}
        _viewing(monkeypatch, {"selection": ["cube"], "mode": "edit", "edit": edit})
        assert "too many to pass on" in run({"action": "inspect"}, root)
        out = run({"action": "apply", "id": "cube", "operation": "bevel", "params": {"selection": "selected"}}, root)
        assert out.startswith("Error: too many elements") and not engine.calls

    def test_a_save_sweeps_old_mesh_files_nothing_uses(self, root, engine):
        import os
        import time
        run({"action": "apply", "id": "cube", "operation": "convert"}, root)        # the scene uses m-0123456789ab
        meshes = root / "apps/studio/data/meshes"
        used, stale, fresh = meshes / "m-0123456789ab.json", meshes / "m-aaaaaaaaaaaa.json", meshes / "m-bbbbbbbbbbbb.json"
        stale.write_text("{}")
        fresh.write_text("{}")                                                      # an open app's, maybe
        day_ago = time.time() - 2 * 86400
        for p in (used, stale):
            os.utime(p, (day_ago, day_ago))
        run({"action": "edit", "ops": [{"op": "set", "id": "cube", "location": [0, 0, 2]}]}, root)
        assert used.exists() and fresh.exists() and not stale.exists()

    def test_apply_join_removes_the_others(self, root, engine):
        run({"action": "edit", "ops": [{"op": "add", "id": "b", "primitive": "cube", "location": [3, 0, 0]}]}, root)
        out = run({"action": "apply", "id": "cube", "operation": "join", "params": {"others": ["b"]}}, root)
        assert "removed: b" in _text(out) and "b" not in scene(root)["objects"]

    def test_script_replaces_the_scene_and_reports(self, root, engine):
        out = run({"action": "script", "code": "print('hello')"}, root)
        assert "scripted" in scene(root)["objects"]
        assert "curve baked" in _text(out) and "hello" in _text(out)

    def test_import_merges_with_renamed_ids(self, root, engine):
        (root / "model.glb").write_bytes(b"glTF")
        out = run({"action": "import", "path": "model.glb"}, root)
        assert engine.calls[-1]["blobs"] == {"import.glb": b"glTF"}
        doc = scene(root)
        assert "cube_2" in doc["objects"] and doc["objects"]["cube_2"]["mesh"] == "m-aaaaaaaaaaaa"
        assert "cube_2" in _text(out)
        assert (root / "apps/studio/data/meshes/m-aaaaaaaaaaaa.json").exists()
        assert run({"action": "import", "path": "notes.txt"}, root).startswith("Error:")

    def test_export(self, root, engine):
        out = run({"action": "export", "format": "glb", "name": "scene"}, root)
        assert (root / "exports/scene.glb").read_bytes() == b"model-bytes"
        assert _uis(out)[0]["action"] == "open_canvas"
        assert run({"action": "export", "format": "blend"}, root).startswith("Exported the scene to exports/scene")

    def test_engine_errors_are_plain_sentences(self, root, engine):
        engine.fail = "the scene has no render camera — add one (render.camera)"
        assert run({"action": "render"}, root) == "Error: the scene has no render camera — add one (render.camera)"

    def test_engine_unreachable(self, root, monkeypatch):
        def boom(name, timeout=None):
            def fn(**kw):
                raise ConnectionError("down")
            return fn
        monkeypatch.setattr(cycls, "remote", boom)
        assert "unavailable" in run({"action": "snapshot"}, root)


# ─── the app's engine route ─────────────────────────────────────────────────

class TestRoute:
    @pytest.fixture
    def client(self, root, engine):
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient
        from cycls._agent.studio import route
        route._calls.clear(); route._renders.clear(); route._rendering.clear()
        ws = _ws(root)
        app = FastAPI()
        app.include_router(route.studio_router(Depends(lambda: ws), Depends(lambda: object())))
        asyncio.run(install.ensure_installed(ws))
        return TestClient(app)

    def test_only_the_installed_studio(self, client, root):
        assert client.post("/apps/other/engine", json={"op": "snapshot"}).status_code == 404
        (root / "apps/studio/app.json").write_text("{}")
        assert client.post("/apps/studio/engine", json={"op": "snapshot"}).status_code == 404

    def test_only_app_ops(self, client):
        for op in ("script", "import", "selftest", "nope"):
            r = client.post("/apps/studio/engine", json={"op": op})
            assert r.status_code == 400 and "op: one of" in r.json()["detail"]

    def test_snapshot_uses_the_apps_scene(self, client, engine):
        doc, _ = S.apply_ops(S.new_scene(), [{"op": "add", "id": "unsaved", "primitive": "cube"}])
        r = client.post("/apps/studio/engine", json={"op": "snapshot", "scene": doc})
        assert r.json()["preview"].startswith("data:image/jpeg;base64,")
        assert "unsaved" in engine.calls[-1]["scene"]["objects"]

    def test_render_is_saved_before_the_answer(self, client, root):
        r = client.post("/apps/studio/engine", json={"op": "render", "name": "Hero"}).json()
        assert r["path"] == "renders/hero.png" and (root / "renders/hero.png").read_bytes() == PNG
        assert json.loads((root / "apps/studio/data/renders.json").read_text())[-1]["by"] == "app"

    def test_apply_writes_the_mesh_the_app_then_references(self, client, root):
        r = client.post("/apps/studio/engine", json={"op": "apply", "params": {"id": "cube", "op": "bevel"}}).json()
        assert r["data"] == "meshes/m-0123456789ab.json"
        assert (root / "apps/studio/data/meshes/m-0123456789ab.json").exists()
        assert r["selection"] == {"faces": [2, 3]}                  # what Blender left selected, for Edit mode

    def test_bad_scene_or_missing_mesh_is_a_400(self, client):
        r = client.post("/apps/studio/engine", json={"op": "snapshot", "scene": {"objects": {"x": {"type": "teapot"}}}})
        assert r.status_code == 400 and "objects.x.type" in r.json()["detail"]
        doc = S.normalize({"objects": {"m": {"type": "mesh", "mesh": "q"}},
                           "meshes": {"q": {"data": "meshes/m-ffffffffffff.json"}}})
        r = client.post("/apps/studio/engine", json={"op": "snapshot", "scene": doc})
        assert r.status_code == 400 and "missing" in r.json()["detail"]

    def test_engine_failure_is_an_answer_not_an_error(self, client, engine):
        engine.fail = "the scene has no render camera"
        assert client.post("/apps/studio/engine", json={"op": "render"}).json() == \
            {"ok": False, "error": "the scene has no render camera"}

    def test_budget(self, client, monkeypatch):
        from cycls._agent.studio import route
        monkeypatch.setattr(route, "CALLS_PER_MINUTE", 3)
        codes = [client.post("/apps/studio/engine", json={"op": "snapshot"}).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]


def test_route_mounts_only_when_configured(monkeypatch):
    from fastapi import FastAPI
    from cycls._agent.web import routers

    class _App:
        config = None
        connectors = None

    def paths(app):
        return set(app.openapi()["paths"])
    app = FastAPI()
    routers.install_routers(_App(), app, None, "/tmp/vol", "file:///tmp/vol")
    assert "/apps/{slug}/engine" in paths(app)
    monkeypatch.delenv("CYCLS_STUDIO_ENGINE")
    app = FastAPI()
    routers.install_routers(_App(), app, None, "/tmp/vol", "file:///tmp/vol")
    assert "/apps/{slug}/engine" not in paths(app)


def test_bundle_carries_its_own_csp():
    html = install.bundle()[0]
    assert "connect-src 'none'" in html and "Content-Security-Policy" in html

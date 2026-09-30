"""The Studio engine is a separate deployment (cycls-render), so the only thing that
catches a drift between it and this caller is a call. The tool, end to end, against
the real Blender — no model involved.

    set -a && source .env && set +a        # CYCLS_API_KEY; CYCLS_STUDIO_ENGINE defaults to cycls-render
    uv run pytest tests/agent/scenarios/test_studio_live.py --live -v
"""
import asyncio
import json
import os

import pytest

from cycls._agent.studio import engine, store, tool, video
from cycls._app.db import workspace

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    if not os.environ.get("CYCLS_API_KEY"):
        pytest.skip("CYCLS_API_KEY is unset")
    os.environ.setdefault("CYCLS_STUDIO_ENGINE", "cycls-render")
    return tmp_path_factory.mktemp("studio")


def ws(root):
    return workspace(root.name, root.parent, base=f"file://{root}")


def run(root, inp):
    out = asyncio.run(tool.run(inp, ws(root)))
    text = out if isinstance(out, str) else out["_model"] if isinstance(out["_model"], str) else \
        " ".join(b.get("text", "") for b in out["_model"])
    assert not text.startswith("Error"), text
    return out, text


def scene(root):
    return json.loads((root / "apps/studio/data/scene.json").read_text())


def test_a_scene_builds_in_one_edit(root):
    _, text = run(root, {"action": "edit", "intent": "gold ring on a pedestal", "ops": [
        {"op": "delete", "id": "cube"},
        {"op": "add", "id": "ped", "primitive": "cylinder", "params": {"radius": 1, "depth": 0.5},
         "material": "ceramic", "on_floor": True},
        {"op": "add", "id": "ring", "primitive": "torus", "params": {"minor_radius": 0.25},
         "rotation": [90, 0, 0], "location": [0, 0, 1.75], "material": "gold"},
        {"op": "modifier", "object": "ring", "type": "subsurf", "params": {"levels": 1}},
        {"op": "preset", "studio": {"lighting": "softbox", "camera": "front-3/4"}},
    ]})
    doc = scene(root)
    assert {"ped", "ring"} <= set(doc["objects"]) and doc["rev"] >= 1
    assert "Layout check" in text or "rev" in text


def test_evaluate_answers_display_meshes(root):
    doc = scene(root)
    r = asyncio.run(engine.call("evaluate", doc, blobs=store.blobs(ws(root), doc), params={"ids": ["ring"]}))
    m = r["result"]["meshes"]["ring"]
    assert m["tris"] > 500 and len(r["files"][m["index"]]) == m["tris"] * 12


def test_snapshot_is_a_jpeg(root):
    out, _ = run(root, {"action": "snapshot"})
    assert out["_model"][0]["type"] == "image"


def test_apply_makes_an_explicit_mesh_the_next_call_carries(root):
    run(root, {"action": "apply", "id": "ped", "operation": "convert"})
    _, text = run(root, {"action": "apply", "id": "ped", "operation": "bevel",
                         "params": {"selection": "all", "width": 0.03, "segments": 2}})
    doc = scene(root)
    mesh = doc["meshes"][doc["objects"]["ped"]["mesh"]]
    assert mesh["data"].startswith("meshes/m-") and (root / "apps/studio/data" / mesh["data"]).exists()
    assert "Applied bevel to ped" in text


def test_script_round_trips_into_the_document(root):
    _, text = run(root, {"action": "script", "code": (
        "for i in range(3):\n"
        "    bpy.ops.mesh.primitive_cube_add(size=0.3, location=(2 + i * 0.5, 0, 0.15))\n"
        "    bpy.context.active_object.name = f'Block {i}'\n")})
    names = {o["name"] for o in scene(root)["objects"].values()}
    assert {"Block 0", "Block 1", "Block 2"} <= names, text


def test_export_glb(root):
    out, text = run(root, {"action": "export", "format": "glb", "name": "ring"})
    assert (root / "exports/ring.glb").read_bytes()[:4] == b"glTF", text


def test_render_saves_logs_and_opens(root):
    out, _ = run(root, {"action": "render", "name": "live", "resolution": [320, 180], "samples": 8})
    assert (root / "renders/live.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    log = json.loads((root / "apps/studio/data/renders.json").read_text())
    assert log[-1]["path"] == "renders/live.png" and log[-1]["resolution"] == [320, 180]


def test_a_turntable_poses_and_renders_as_a_video(root):
    """Keys through the real build: a snapshot at another frame is another picture. Then a tiny
    video, driven the way the app drives it — chunks, then the join."""
    run(root, {"action": "edit", "ops": [{"op": "turntable", "target": "ring", "seconds": 1, "fps": 12},
                                          {"op": "render", "resolution": [160, 90], "samples": 2}]})
    first, _ = run(root, {"action": "snapshot", "samples": 2})
    turned, _ = run(root, {"action": "snapshot", "samples": 2, "frame": 4})
    assert first["_model"][0]["source"]["data"] != turned["_model"][0]["source"]["data"]

    async def drive():
        w = ws(root)
        job = await video.start(w, await store.load(w), {"name": "spin"})
        for _ in range(8):
            r = await video.chunk(w, job["id"])
            assert "error" not in r, r
            if r.get("wait") == 0 and r["job"]["done"] == r["job"]["total"]:
                return await video.finish(w, job["id"])
        raise AssertionError(r)
    done = asyncio.run(drive())
    assert done["path"] == "renders/spin.mp4" and done["poster"].startswith("data:image/jpeg")
    mp4 = (root / "renders/spin.mp4").read_bytes()
    assert mp4[4:8] == b"ftyp" and len(mp4) > 1000
    log = json.loads((root / "apps/studio/data/renders.json").read_text())
    assert log[-1]["video"] is True and log[-1]["frames"] == 12

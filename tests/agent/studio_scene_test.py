import copy
import math
import pathlib

import pytest

from cycls._agent.studio import scene as S


def _studio(doc=None, **spec):
    doc = doc or S.new_scene()
    return S.apply_ops(doc, [{"op": "preset", "studio": spec or {"lighting": "studio-3point"}}])[0]


def _ring_scene():
    doc, _ = S.apply_ops(S.new_scene(), [
        {"op": "delete", "id": "cube"},
        {"op": "add", "id": "ring", "primitive": "torus", "params": {"minor_radius": 0.36},
         "rotation": [90, 0, 0], "material": "gold", "on_floor": True},
        {"op": "add", "id": "pedestal", "primitive": "cylinder", "params": {"radius": 1.2, "depth": 0.4},
         "material": {"name": "marble", "base_color": "#f1efe9", "roughness": 0.2}, "on_floor": True},
        {"op": "modifier", "object": "ring", "type": "bevel", "params": {"width": 0.01}},
    ])
    return doc


# ─── normalize ──────────────────────────────────────────────────────────────

class TestNormalize:
    def test_new_scene_is_blenders_startup_scene(self):
        doc = S.new_scene()
        assert set(doc["objects"]) == {"cube", "light", "camera"}
        assert doc["render"]["camera"] == "camera"
        assert doc["format"] == S.FORMAT and doc["version"] == S.VERSION and doc["up"] == "Z"

    @pytest.mark.parametrize("build", [S.new_scene, _ring_scene, _studio])
    def test_idempotent(self, build):
        doc = build()
        assert S.normalize(copy.deepcopy(doc)) == doc
        assert S.normalize(S.normalize(doc)) == doc

    def test_fills_defaults(self):
        doc = S.normalize({"objects": {"s": {"type": "mesh", "mesh": "m"}}, "meshes": {"m": {"primitive": "uv_sphere"}}})
        assert doc["meshes"]["m"] == {"primitive": "uv_sphere", "segments": 32, "ring_count": 16, "radius": 1.0}
        assert doc["objects"]["s"]["scale"] == [1, 1, 1] and doc["objects"]["s"]["modifiers"] == []
        assert doc["render"]["resolution"] == [1280, 720] and doc["render"]["samples"] == 32

    def test_colours_normalize_to_hex(self):
        doc = S.normalize({"materials": {"a": {"base_color": "F00"}, "b": {"base_color": [255, 128, 0]}}})
        assert doc["materials"]["a"]["base_color"] == "#ff0000"
        assert doc["materials"]["b"]["base_color"] == "#ff8000"

    @pytest.mark.parametrize("bad, field", [
        ({"objects": {"x": {"type": "teapot"}}}, "objects.x.type"),
        ({"objects": {"x": {"type": "mesh"}}}, "objects.x.mesh"),
        ({"objects": {"x": {"type": "mesh", "mesh": "nope"}}}, "objects.x.mesh: no mesh"),
        ({"objects": {"x": {"type": "light", "light": {"kind": "laser"}}}}, "objects.x.light.kind"),
        ({"objects": {"x": {"type": "light", "light": {"energy": -1}}}}, "objects.x.light.energy"),
        ({"objects": {"x": {"type": "light", "material": "m"}}}, "objects.x.material: not valid on a light"),
        ({"objects": {"x": {"type": "empty", "parent": "x"}}}, "loops back"),
        ({"objects": {"x": {"type": "empty", "colour": 1}}}, "objects.x: unknown colour"),
        ({"objects": {"bad id": {"type": "empty"}}}, "not a valid id"),
        ({"meshes": {"m": {"primitive": "teapot"}}}, "meshes.m.primitive"),
        ({"meshes": {"m": {"primitive": "torus", "minor_radius": 0}}}, "meshes.m.minor_radius"),
        ({"meshes": {"m": {"data": "../../etc/passwd"}}}, "meshes.m.data"),
        ({"materials": {"m": {"preset": "unobtainium"}}}, "materials.m.preset"),
        ({"materials": {"m": {"base_color": "#zz0000"}}}, "materials.m.base_color"),
        ({"materials": {"m": {"metallic": 2}}}, "materials.m.metallic: 2 is outside 0–1"),
        ({"render": {"resolution": [4096, 4096]}}, "pixel cap"),
        ({"render": {"camera": "ghost"}}, "render.camera"),
        ({"world": {"hdri": "mars"}}, "world.hdri"),
        ({"version": 99}, "newer than this Studio"),
        ({"format": "fig"}, "not a Studio scene"),
        ({"extra": 1}, "scene: unknown extra"),
    ])
    def test_errors_name_the_field(self, bad, field):
        with pytest.raises(S.SceneError, match=field.replace(".", r"\.").replace("(", r"\(")):
            S.normalize(bad)

    def test_boolean_needs_a_cutter(self):
        base = {"objects": {"a": {"type": "mesh", "mesh": "m", "modifiers": [{"type": "boolean"}]}},
                "meshes": {"m": {"primitive": "cube"}}}
        with pytest.raises(S.SceneError, match="cutter"):
            S.normalize(base)
        base["objects"]["a"]["modifiers"][0]["object"] = "a"
        with pytest.raises(S.SceneError, match="no other object"):
            S.normalize(base)

    def test_runs_standalone_like_the_engine(self):
        # The engine execs this file's source with no package around it.
        src = pathlib.Path(S.__file__).read_text(encoding="utf-8")
        ns = {"__name__": "studio_scene"}
        exec(compile(src, "scene.py", "exec"), ns)
        assert ns["normalize"](ns["new_scene"]())["objects"]["cube"]["mesh"] == "cube"


# ─── transforms ─────────────────────────────────────────────────────────────

class TestTransforms:
    def test_euler_matches_blender(self):
        # Blender 5.2's Euler((30°,45°,60°),'XYZ').to_matrix() — spike S3 (== three.js order 'ZYX').
        golden = [[0.3535534, -0.5732233, 0.7391989], [0.6123724, 0.7391989, 0.2803301],
                  [-0.7071068, 0.3535534, 0.6123724]]
        got = S.euler_matrix([30, 45, 60])
        assert max(abs(got[i][j] - golden[i][j]) for i in range(3) for j in range(3)) < 1e-6

    @pytest.mark.parametrize("rot", [[30, 45, 60], [-45, 5, 90], [0, 89.9, 0], [170, -20, 300]])
    def test_matrix_euler_inverts(self, rot):
        m = S.euler_matrix(rot)
        back = S.euler_matrix(S.matrix_euler(m))
        assert max(abs(m[i][j] - back[i][j]) for i in range(3) for j in range(3)) < 1e-9

    def test_compose_decompose_and_invert(self):
        m = S.compose([1, 2, 3], [10, 20, 30], [1, 2, 0.5])
        loc, rot, scl = S.decompose(m)
        assert loc == pytest.approx([1, 2, 3]) and scl == pytest.approx([1, 2, 0.5])
        again = S.compose(loc, rot, scl)
        ident = S.matmul(m, S.invert(m))
        assert all(abs(again[i][j] - m[i][j]) < 1e-9 for i in range(4) for j in range(4))
        assert all(abs(ident[i][j] - (i == j)) < 1e-9 for i in range(4) for j in range(4))

    def test_look_rotation_is_blenders_track_to(self):
        # A camera at -Y looking at the origin is Blender's (90°, 0, 0).
        assert S.look_rotation([0, -10, 0], [0, 0, 0]) == pytest.approx([90, 0, 0], abs=1e-9)
        # Looking straight down stays well-defined.
        r = S.euler_matrix(S.look_rotation([0, 0, 10], [0, 0, 0]))
        assert [r[i][2] for i in range(3)] == pytest.approx([0, 0, 1], abs=1e-9)   # +Z points back up

    def test_frame_fits_the_subjects(self):
        doc, touched = S.apply_ops(_ring_scene(), [{"op": "frame", "angle": "front-3/4"}])
        assert touched == ["objects.camera"]
        cam = doc["objects"]["camera"]
        r = S.euler_matrix(cam["rotation"])
        view = [-r[0][2], -r[1][2], -r[2][2]]
        half = S._fov_short(doc, "camera")
        for oid in S.subject_ids(doc):
            b = S.world_bounds(doc, oid)
            for x in (b[0][0], b[1][0]):
                for y in (b[0][1], b[1][1]):
                    for z in (b[0][2], b[1][2]):
                        d = S._norm(S._sub([x, y, z], cam["location"]))
                        assert math.degrees(math.acos(max(-1, min(1, S._dot(d, view))))) <= math.degrees(half) + 1e-6


# ─── ops ────────────────────────────────────────────────────────────────────

class TestOps:
    def test_add_primitive_with_material_preset(self):
        doc, touched = S.apply_ops(S.new_scene(), [
            {"op": "add", "primitive": "torus", "name": "Ring", "material": "gold", "on_floor": True}])
        assert touched == ["objects.ring", "meshes.ring"]
        ring = doc["objects"]["ring"]
        assert ring["materials"] == ["gold"] and doc["materials"]["gold"]["metallic"] == 1.0
        assert S.world_bounds(doc, "ring")[0][2] == pytest.approx(0, abs=1e-9)

    def test_add_existing_id_is_refused(self):
        with pytest.raises(S.SceneError, match=r"ops\[0\].id: 'cube' already exists"):
            S.apply_ops(S.new_scene(), [{"op": "add", "id": "cube", "primitive": "cube"}])

    def test_diff_touches_exactly_what_each_op_touched(self):
        base = _ring_scene()
        cases = [
            [{"op": "set", "id": "ring", "location": [0, 0, 3]}],
            [{"op": "set", "id": "pedestal", "params": {"radius": 2}}],
            [{"op": "material", "id": "gold", "roughness": 0.4}],
            [{"op": "material", "name": "red", "base_color": "#ff0000", "assign": "pedestal"}],
            [{"op": "modifier", "object": "ring", "action": "set", "type": "bevel", "params": {"segments": 5}}],
            [{"op": "duplicate", "id": "ring", "offset": [3, 0, 0]}],
            [{"op": "delete", "id": "pedestal"}],
            [{"op": "world", "strength": 1.2}],
            [{"op": "render", "samples": 64}],
            [{"op": "look_at", "id": "light", "target": "ring"}],
        ]
        for ops in cases:
            doc, touched = S.apply_ops(base, ops)
            d = S.diff(base, doc)
            changed = set(d["set"]) | set(d["delete"])
            assert changed == set(touched), (ops, changed, touched)
            assert S.patch(base, d) == doc

    def test_errors_name_the_op_and_field(self):
        base = _ring_scene()
        for ops, match in [
            ([{"op": "explode"}], r"ops\[0\].op"),
            ([{"op": "set", "id": "ghost", "location": [0, 0, 0]}], r"ops\[0\].id: no object 'ghost'"),
            ([{"op": "set", "id": "ring", "location": [0, 0]}], r"ops\[0\] \(set\): objects.ring.location"),
            ([{"op": "modifier", "object": "ring", "type": "melt"}], r"modifiers\[1\].type"),
            ([{"op": "modifier", "object": "light", "type": "bevel"}], "it takes no modifiers"),
            ([{"op": "material", "assign": "light", "preset": "gold"}], "takes no material"),
            ([{"op": "add", "primitive": "cube"}, {"op": "set", "id": "cube", "scale": "big"}], r"ops\[1\]"),
            ([{"op": "preset", "studio": {"lighting": "disco"}}], r"studio.lighting"),
        ]:
            with pytest.raises(S.SceneError, match=match):
                S.apply_ops(base, ops)

    def test_failed_ops_leave_the_document_alone(self):
        base = _ring_scene()
        snapshot = copy.deepcopy(base)
        with pytest.raises(S.SceneError):
            S.apply_ops(base, [{"op": "set", "id": "ring", "location": [9, 9, 9]}, {"op": "explode"}])
        assert base == snapshot

    def test_selected_resolves_to_the_viewers_selection(self):
        doc, touched = S.apply_ops(_ring_scene(), [{"op": "material", "preset": "chrome", "assign": "selected"}],
                                   selection=["ring", "pedestal"])
        assert doc["objects"]["ring"]["materials"] == doc["objects"]["pedestal"]["materials"] == ["chrome"]
        with pytest.raises(S.SceneError, match="nothing is selected"):
            S.apply_ops(_ring_scene(), [{"op": "delete", "id": "selected"}], selection=[])

    def test_delete_keeps_childrens_world_transform(self):
        doc, _ = S.apply_ops(S.new_scene(), [
            {"op": "add", "id": "arm", "type": "empty", "location": [1, 2, 3], "rotation": [0, 0, 45], "scale": [2, 2, 2]},
            {"op": "add", "id": "hand", "type": "empty", "parent": "arm", "location": [1, 0, 0], "rotation": [30, 0, 0]},
        ])
        before = S.world_matrix(doc, "hand")
        doc, touched = S.apply_ops(doc, [{"op": "delete", "id": "arm"}])
        assert doc["objects"]["hand"]["parent"] is None and "objects.hand" in touched
        after = S.world_matrix(doc, "hand")
        assert all(abs(before[i][j] - after[i][j]) < 1e-9 for i in range(4) for j in range(4))

    def test_delete_drops_orphan_meshes_and_clears_camera(self):
        doc, touched = S.apply_ops(S.new_scene(), [{"op": "delete", "id": "cube"}, {"op": "delete", "id": "camera"}])
        assert "cube" not in doc["meshes"] and doc["render"]["camera"] is None
        assert {"objects.cube", "meshes.cube", "objects.camera"} <= set(touched)

    def test_delete_refuses_a_boolean_cutter_in_use(self):
        doc, _ = S.apply_ops(_ring_scene(), [
            {"op": "modifier", "object": "pedestal", "type": "boolean", "params": {"object": "ring"}}])
        with pytest.raises(S.SceneError, match="used by a modifier"):
            S.apply_ops(doc, [{"op": "delete", "id": "ring"}])

    def test_modifier_move_and_remove(self):
        doc, _ = S.apply_ops(_ring_scene(), [
            {"op": "modifier", "object": "ring", "type": "subsurf"},
            {"op": "modifier", "object": "ring", "action": "move", "type": "subsurf", "to": 0},
        ])
        assert [m["type"] for m in doc["objects"]["ring"]["modifiers"]] == ["subsurf", "bevel"]
        doc, _ = S.apply_ops(doc, [{"op": "modifier", "object": "ring", "action": "remove", "index": 1}])
        assert [m["type"] for m in doc["objects"]["ring"]["modifiers"]] == ["subsurf"]


# ─── studio presets (ported from cycls-render's scenes.py) ──────────────────

class TestPresets:
    def test_rig_matches_scenes_py_for_a_two_unit_subject(self):
        doc = _studio()                                  # the startup cube: 2 units, standing on the floor
        key = doc["objects"]["studio_key"]
        # scenes.py: key at _orbit(target, 6, -45, 35), 900 W, 3 m, aimed at target.
        assert key["location"] == pytest.approx(S.orbit([0, 0, 1], 6, -45, 35))
        assert key["light"]["energy"] == pytest.approx(900) and key["light"]["size"] == pytest.approx(3)
        assert doc["world"]["strength"] == pytest.approx(0.35)
        assert doc["materials"]["studio_backdrop"]["base_color"] == "#d6d6db"

    def test_dark_rigs_get_a_dark_backdrop_and_rerun_replaces(self):
        doc = _studio(lighting="rim")
        assert doc["materials"]["studio_backdrop"]["base_color"] == "#141417"
        assert {k for k in doc["objects"] if k.startswith("studio_")} == {
            "studio_backdrop", "studio_key", "studio_fill", "studio_rim"}
        doc = _studio(doc, lighting="dramatic")
        assert {k for k in doc["objects"] if k.startswith("studio_")} == {"studio_backdrop", "studio_key", "studio_fill"}

    def test_material_presets_carry_scenes_py_reflectance(self):
        gold = S.hex_to_linear(S.MATERIAL_PRESETS["gold"]["base_color"])
        assert gold == pytest.approx([1.0, 0.766, 0.336], abs=0.01)
        neon = S.MATERIAL_PRESETS["neon"]
        assert neon["emission"] == 2.0

    def test_hero_angle_uses_85mm(self):
        assert _studio(camera="hero")["objects"]["camera"]["camera"]["lens"] == 85.0

    def test_the_studio_floor_is_z0_whatever_is_in_the_scene(self):
        doc, _ = S.apply_ops(S.new_scene(), [{"op": "set", "id": "cube", "location": [0, 0, -3]}])
        doc = _studio(doc)
        assert S.world_bounds(doc, "studio_backdrop")[0][2] == pytest.approx(0)


# ─── layout check ───────────────────────────────────────────────────────────

class TestLayout:
    def test_a_clean_scene(self):
        assert S.layout_check(_studio(_ring_scene())) == []
        assert S.layout_check(S.new_scene()) == []
        assert S.world_bounds(S.new_scene(), "cube")[0][2] == pytest.approx(0)   # startup cube on the floor

    def test_floating_and_sunk(self):
        doc, _ = S.apply_ops(_ring_scene(), [
            {"op": "add", "id": "hover", "primitive": "cube", "location": [6, 0, 3]},
            {"op": "add", "id": "sunk", "primitive": "cube", "location": [-6, 0, 0]}])
        issues = S.layout_check(doc)
        assert any(i.startswith("hover floats") for i in issues)
        assert any(i.startswith("sunk dips 1.00 below the floor") for i in issues)

    def test_resting_on_or_sunk_into_another_object_is_supported(self):
        doc, _ = S.apply_ops(S.new_scene(), [
            {"op": "delete", "id": "cube"},
            {"op": "add", "id": "disc", "primitive": "cylinder", "params": {"radius": 1, "depth": 0.1}, "on_floor": True},
            {"op": "add", "id": "ped", "primitive": "cylinder", "params": {"radius": 0.5, "depth": 1},
             "location": [0, 0, 0.55]},                                # bottom at 0.05: sunk into the disc
            {"op": "add", "id": "top", "primitive": "uv_sphere", "params": {"radius": 0.3}, "location": [0, 0, 1.35]}])
        assert S.layout_check(doc) == []

    def test_cut_off_by_the_frame(self):
        doc = _studio(_ring_scene())
        assert S.out_of_frame(doc) == []
        cam = doc["objects"]["camera"]
        cam["location"] = [c * 0.35 for c in cam["location"]]          # push in too close
        doc["objects"]["camera"]["rotation"] = S.look_rotation(cam["location"], [0, 0, 0.8])
        assert "ring" in S.out_of_frame(doc) or "pedestal" in S.out_of_frame(doc)
        assert any("outside the camera's frame" in i for i in S.layout_check(doc))

    def test_a_ground_plane_is_set_dressing_not_a_subject(self):
        doc, _ = S.apply_ops(_ring_scene(), [
            {"op": "add", "id": "floor", "primitive": "plane", "params": {"size": 40}}])
        assert "floor" not in S.subject_ids(doc)
        framed, _ = S.apply_ops(doc, [{"op": "frame"}])
        assert S.out_of_frame(framed) == [] and S.layout_check(framed) == []
        assert math.dist(framed["objects"]["camera"]["location"], [0, 0, 0]) < 20   # didn't back off to fit the floor

    def test_a_studio_floor_off_zero_is_flagged(self):
        doc = _studio()
        doc["objects"]["studio_backdrop"]["location"][2] = -1
        assert any("studio floor is at z = -1.00" in i for i in S.layout_check(doc))


# ─── textures ───────────────────────────────────────────────────────────────

LOGO = {"op": "texture", "id": "logo", "name": "Logo", "data": "textures/t-0123456789ab.json",
        "width": 800, "height": 400, "alpha": True}


class TestTextures:
    def test_a_material_uses_an_image_and_the_scene_keeps_it(self):
        doc, touched = S.apply_ops(S.new_scene(), [LOGO, {"op": "material", "id": "material",
                                                           "base_color_texture": "logo", "texture_scale": [2, 2]}])
        assert doc["textures"]["logo"] == {"name": "Logo", "data": "textures/t-0123456789ab.json",
                                           "width": 800, "height": 400, "alpha": True}
        assert doc["materials"]["material"]["base_color_texture"] == "logo"
        assert doc["materials"]["material"]["texture_scale"] == [2.0, 2.0]
        assert "textures.logo" in touched and S.normalize(copy.deepcopy(doc)) == doc

    def test_an_image_no_material_uses_is_dropped_at_the_end_of_the_batch(self):
        doc, touched = S.apply_ops(S.new_scene(), [LOGO])
        assert doc["textures"] == {} and "textures.logo" not in touched

    def test_bad_references_and_files_name_the_field(self):
        with pytest.raises(S.SceneError, match=r"materials.material.base_color_texture: no texture 'nope'"):
            S.apply_ops(S.new_scene(), [{"op": "material", "id": "material", "base_color_texture": "nope"}])
        with pytest.raises(S.SceneError, match=r"textures.logo.data"):
            S.apply_ops(S.new_scene(), [{**LOGO, "data": "../secrets.json"}])
        with pytest.raises(S.SceneError, match=r"texture_scale: needs 2 values"):
            S.apply_ops(S.new_scene(), [{"op": "material", "id": "material", "texture_scale": 2}])

    def test_an_image_plane_stands_up_at_the_images_aspect(self):
        doc, _ = S.apply_ops(S.new_scene(), [LOGO, {"op": "add", "id": "sign", "image": "logo", "height": 0.5}])
        o = doc["objects"]["sign"]
        assert o["type"] == "mesh" and doc["meshes"][o["mesh"]] == {"primitive": "plane", "size": 0.5}
        assert o["rotation"] == [90, 0, 0] and o["scale"] == [2.0, 1, 1]
        assert doc["materials"][o["materials"][0]]["base_color_texture"] == "logo"
        with pytest.raises(S.SceneError, match=r"image: no texture"):
            S.apply_ops(S.new_scene(), [{"op": "add", "image": "logo"}])

    def test_a_preset_keeps_the_image_and_its_placement(self):
        doc, _ = S.apply_ops(S.new_scene(), [LOGO, {"op": "material", "id": "material", "base_color_texture": "logo",
                                                   "texture_rotation": 30, "roughness": 0.9}])
        doc, _ = S.apply_ops(doc, [{"op": "material", "id": "material", "preset": "plastic"}])
        m = doc["materials"]["material"]
        assert m["base_color_texture"] == "logo" and m["texture_rotation"] == 30
        assert m["roughness"] == S.MATERIAL_PRESETS["plastic"]["roughness"]

    def test_an_import_brings_its_images_along_renamed(self):
        doc, _ = S.apply_ops(S.new_scene(), [LOGO, {"op": "material", "id": "material", "base_color_texture": "logo"}])
        frag = copy.deepcopy(doc)
        merged, _ = S.merge_fragment(doc, frag)
        assert set(merged["textures"]) == {"logo", "logo_2"}
        assert merged["materials"]["material_2"]["base_color_texture"] == "logo_2"

    def test_merge_and_summary_see_textures(self):
        base = S.new_scene()
        local, _ = S.apply_ops(base, [LOGO, {"op": "material", "id": "material", "base_color_texture": "logo"}])
        merged, conflicts = S.merge3(base, local, base)
        assert merged["textures"]["logo"]["width"] == 800 and not conflicts
        text = S.summary(local)
        assert "base color image logo" in text and "Textures: logo 800x400 with alpha" in text


# ─── material slots (version 2) ─────────────────────────────────────────────

class TestSlots:
    def test_a_version_1_scene_reads_as_the_current_one(self):
        v1 = {"version": 1, "objects": {"cube": {"type": "mesh", "mesh": "cube", "material": "m"},
                                        "bare": {"type": "mesh", "mesh": "cube", "material": None}},
              "meshes": {"cube": {"primitive": "cube"}}, "materials": {"m": {}}}
        doc = S.normalize(v1)
        assert doc["version"] == S.VERSION
        assert doc["objects"]["cube"]["materials"] == ["m"] and doc["objects"]["bare"]["materials"] == []
        assert "material" not in doc["objects"]["cube"]
        assert S.normalize(copy.deepcopy(doc)) == doc

    def test_material_still_means_slot_0(self):
        doc, _ = S.apply_ops(S.new_scene(), [{"op": "material", "id": "red", "base_color": "#ff0000"},
                                            {"op": "material", "id": "blue", "base_color": "#0000ff",
                                             "assign": "cube", "slot": 1},
                                            {"op": "set", "id": "cube", "material": "red"}])
        assert doc["objects"]["cube"]["materials"] == ["red", "blue"]
        assert "materials [red, blue] (slot per face)" in S.summary(doc)

    def test_a_slot_past_the_end_is_named(self):
        with pytest.raises(S.SceneError, match=r"slot: 'cube' has 1 slot\(s\) — use 1 to add one"):
            S.apply_ops(S.new_scene(), [{"op": "material", "id": "x", "assign": "cube", "slot": 3}])
        with pytest.raises(S.SceneError, match=r"materials\[1\]: no material 'nope'"):
            S.normalize({**S.new_scene(), "objects": {**S.new_scene()["objects"],
                                                      "cube": {**S.new_scene()["objects"]["cube"],
                                                               "materials": ["material", "nope"]}}})

    def test_an_import_renames_every_slot(self):
        doc, _ = S.apply_ops(S.new_scene(), [{"op": "material", "id": "blue", "assign": "cube", "slot": 1}])
        merged, _ = S.merge_fragment(doc, copy.deepcopy(doc))
        assert merged["objects"]["cube_2"]["materials"] == ["material_2", "blue_2"]


def test_add_infers_light_camera_and_text_types():
    doc, _ = S.apply_ops(S.new_scene(), [
        {"op": "add", "id": "l", "light": {"kind": "area", "energy": 50}},
        {"op": "add", "id": "c", "camera": {"lens": 35}},
        {"op": "add", "id": "t", "text": {"body": "Hi"}}])
    assert [doc["objects"][k]["type"] for k in "lct"] == ["light", "camera", "text"]
    with pytest.raises(S.SceneError, match=r'not valid on an empty object — set "type": "light"'):
        S.normalize({"objects": {"x": {"type": "empty", "light": {}}}})

# ─── animation (version 3) ──────────────────────────────────────────────────

class TestAnimation:
    def test_a_version_2_scene_reads_with_a_still_timeline(self):
        v2 = {**S.new_scene(), "version": 2}
        v2.pop("animation")
        doc = S.normalize(v2)
        assert doc["version"] == 3 and doc["animation"] == {"fps": 24, "frame_start": 1, "frame_end": 120}
        assert not S.animated(doc) and all("keys" not in o for o in doc["objects"].values())

    def test_keys_normalize_sorted_one_per_frame(self):
        doc = S.new_scene()
        doc["objects"]["cube"]["keys"] = {"location": [[30, [0, 0, 3]], {"frame": 1, "value": [0, 0, 1]},
                                                       [30, [0, 0, 2], "linear"]], "scale": []}
        out = S.normalize(doc)
        assert out["objects"]["cube"]["keys"] == {"location": [[1, [0, 0, 1], "bezier"], [30, [0, 0, 2], "linear"]]}
        bad = copy.deepcopy(doc)
        bad["objects"]["cube"]["keys"] = {"color": [[1, [0, 0, 0]]]}
        with pytest.raises(S.SceneError, match=r"keys: unknown color"):
            S.normalize(bad)
        bad["objects"]["cube"]["keys"] = {"location": [[1, [0, 0, 1], "ease"]]}
        with pytest.raises(S.SceneError, match=r"interpolation: 'ease'"):
            S.normalize(bad)

    def test_a_channel_rests_where_its_keys_put_the_first_frame(self):
        doc, _ = S.apply_ops(S.new_scene(), [{"op": "animation", "frame_start": 10},
                                            {"op": "keyframe", "id": "cube", "frame": 20, "location": [0, 0, 5]},
                                            {"op": "keyframe", "id": "cube", "frame": 40, "location": [4, 0, 5]}])
        assert doc["objects"]["cube"]["location"] == [0, 0, 5]          # before the first key: its value
        assert S.normalize(copy.deepcopy(doc)) == doc

    def test_linear_constant_and_the_ends(self):
        ks = [[1, [0, 0, 0], "linear"], [11, [10, -10, 5], "constant"], [21, [0, 0, 0], "linear"]]
        assert S.sample(ks, -5) == [0, 0, 0] and S.sample(ks, 99) == [0, 0, 0]
        assert S.sample(ks, 6) == [5, -5, 2.5]
        assert S.sample(ks, 11) == [10, -10, 5] and S.sample(ks, 20.9) == [10, -10, 5]

    def test_bezier_eases_and_holds_its_extremes(self):
        ks = [[1, [0, 0, 0], "bezier"], [31, [0, 0, 2], "bezier"], [61, [0, 0, 1], "bezier"]]
        z = [S.sample(ks, f)[2] for f in range(1, 62)]
        assert z[0] == 0 and z[30] == 2 and z[60] == 1
        assert max(z) == 2                                    # auto-clamped: no overshoot past a key
        assert z[1] - z[0] < z[15] - z[14]                    # eases out of the first key
        assert all(b >= a for a, b in zip(z[:31], z[1:31]))   # rises monotonically to the peak

    def test_keyframe_keys_the_pose_there_and_unkey_leaves_it(self):
        doc, touched = S.apply_ops(S.new_scene(), [{"op": "keyframe", "id": "cube", "frame": 1},
                                                  {"op": "keyframe", "id": "cube", "frame": 50,
                                                   "rotation": [0, 0, 90], "interpolation": "linear"}])
        keys = doc["objects"]["cube"]["keys"]
        assert set(keys) == {"location", "rotation", "scale"} and len(keys["rotation"]) == 2
        assert touched == ["objects.cube"]
        doc, _ = S.apply_ops(doc, [{"op": "keyframe", "id": "cube", "frame": 1, "rotation": [0, 0, 0],
                                    "interpolation": "linear"}])
        assert S.pose(doc, "cube", 25.5)["rotation"] == [0, 0, 45]
        doc, _ = S.apply_ops(doc, [{"op": "unkey", "id": "cube", "frame": 50}])
        assert all(len(ks) == 1 for ks in doc["objects"]["cube"]["keys"].values())
        doc, _ = S.apply_ops(doc, [{"op": "unkey", "id": "cube"}])
        assert "keys" not in doc["objects"]["cube"] and doc["objects"]["cube"]["location"] == [0, 0, 1]

    def test_set_refuses_an_animated_channel_but_moves_a_still_one(self):
        doc, _ = S.apply_ops(S.new_scene(), [{"op": "keyframe", "id": "cube", "frame": 1, "location": [0, 0, 1]}])
        with pytest.raises(S.SceneError, match=r"cube.location is animated .*`keyframe"):
            S.apply_ops(doc, [{"op": "set", "id": "cube", "location": [1, 1, 1]}])
        doc, _ = S.apply_ops(doc, [{"op": "set", "id": "cube", "rotation": [0, 0, 45]}])
        assert doc["objects"]["cube"]["rotation"] == [0, 0, 45]

    def test_duplicate_and_on_floor_carry_the_keys(self):
        doc, _ = S.apply_ops(S.new_scene(), [
            {"op": "keyframe", "id": "cube", "frame": 1, "location": [0, 0, 3]},
            {"op": "keyframe", "id": "cube", "frame": 20, "location": [2, 0, 3]},
            {"op": "set", "id": "cube", "on_floor": True},
            {"op": "duplicate", "id": "cube", "new_id": "twin", "offset": [0, 5, 0]}])
        assert doc["objects"]["cube"]["keys"]["location"] == [[1, [0, 0, 1], "bezier"], [20, [2, 0, 1], "bezier"]]
        assert doc["objects"]["twin"]["keys"]["location"] == [[1, [0, 5, 1], "bezier"], [20, [2, 5, 1], "bezier"]]

    def test_turntable_loops_seamlessly_round_the_subjects_base(self):
        doc, touched = S.apply_ops(_ring_scene(), [{"op": "turntable", "seconds": 4, "turns": 1}])
        a, t = doc["animation"], doc["objects"]["turntable"]
        assert a["frame_end"] - a["frame_start"] + 1 == 96
        assert t["location"][2] == pytest.approx(0) and t["keys"]["rotation"] == [
            [1, [0, 0, 0], "linear"], [97, [0, 0, 360], "linear"]]
        assert doc["objects"]["ring"]["parent"] == "turntable" and doc["objects"]["pedestal"]["parent"] == "turntable"
        step = S.pose(doc, "turntable", 2)["rotation"][2]
        assert S.pose(doc, "turntable", 96)["rotation"][2] + step == pytest.approx(360)   # frame 96 → 1 is one step
        # nothing moved in the world at the first frame
        flat = lambda b: [v for corner in b for v in corner]      # noqa: E731
        assert flat(S.world_bounds(doc, "ring")) == pytest.approx(flat(S.world_bounds(_ring_scene(), "ring")))
        assert "Animation: frames 1–96 at 24 fps (4.0 s)" in S.summary(doc)
        assert S.layout_check(doc) == S.layout_check(_ring_scene())
        with pytest.raises(S.SceneError, match="parented to 'turntable'"):
            S.apply_ops(doc, [{"op": "turntable", "target": "ring"}])

    def test_an_animated_camera_is_not_reframed_behind_its_keys(self):
        doc, _ = S.apply_ops(S.new_scene(), [{"op": "keyframe", "id": "camera", "frame": 1}])
        with pytest.raises(S.SceneError, match="camera.location is animated"):
            S.apply_ops(doc, [{"op": "frame"}])

    def test_the_timeline_merges_like_any_entry(self):
        base = S.new_scene()
        local, _ = S.apply_ops(base, [{"op": "animation", "fps": 30}])
        remote, _ = S.apply_ops(base, [{"op": "keyframe", "id": "cube", "frame": 1}])
        merged, conflicts = S.merge3(base, local, remote)
        assert conflicts == [] and merged["animation"]["fps"] == 30 and "keys" in merged["objects"]["cube"]
        assert S.diff(base, local) == {"set": {"animation": local["animation"]}, "delete": []}


# ─── big scenes ─────────────────────────────────────────────────────────────

def _venue(n=5100, roots=40):
    """A kitbashed site: thousands of objects sharing a few hundred meshes, mostly top-level."""
    doc = S.new_scene()
    doc["meshes"].update({f"m{j}": {"primitive": "cube"} for j in range(300)})
    doc["materials"].update({f"mat{j}": {"name": f"M{j}"} for j in range(60)})
    for i in range(roots):
        doc["objects"][f"root{i}"] = {"type": "empty", "location": [i * 3, 0, 0]}
    for i in range(n):
        doc["objects"][f"o{i}"] = {"type": "mesh", "mesh": f"m{i % 300}", "materials": [f"mat{i % 60}"],
                                   "parent": f"root{i % roots}" if i % 2 else None, "location": [i * 0.1, 0, 0.5]}
    return S.normalize(doc)


class TestBigScenes:
    def test_thousands_of_objects_are_a_scene(self):
        doc = _venue()
        assert len(doc["objects"]) == 5143
        with pytest.raises(S.SceneError, match="at most 10000"):
            S.normalize({**doc, "objects": {**doc["objects"],
                                            **{f"x{i}": {"type": "empty"} for i in range(S.MAX_OBJECTS)}}})

    def test_the_summary_lists_the_top_level_and_counts_the_rest(self):
        doc = _venue()
        text = S.summary(doc, selection=["o1"])
        lines = text.splitlines()
        assert len(text) < 12_000 and sum(ln.startswith("- ") for ln in lines) == S.SUMMARY_OBJECTS
        assert "- o1 (mesh cube)" in text                            # the selection first, parented or not
        assert "… and 5063 more objects (5063 mesh) not listed" in text
        assert "; … and 21 more" in text                              # 61 materials (the default too), 40 named

    def test_an_evaluate_carries_only_what_its_objects_need(self):
        doc = _venue()
        doc["objects"]["o3"]["modifiers"] = [{"type": "boolean", "object": "o4"}]
        doc = S.normalize(doc)
        sub = S.subset(doc, ["o3", "o1"])
        assert set(sub["objects"]) == {"o3", "o4", "o1", "root1", "root3"}   # its cutter, and their parents
        assert set(sub["meshes"]) == {"m1", "m3", "m4"} and set(sub["materials"]) == {"mat1", "mat3", "mat4"}
        assert sub["render"]["camera"] is None and S.normalize(sub) == sub

    def test_layout_checks_step_aside_for_thousands_of_parts(self):
        doc = _venue()
        doc["objects"]["o0"]["location"] = [0, 0, 50]                 # floating — but not worth 25M comparisons
        assert S.layout_check(doc) == []


# ─── diff / merge ───────────────────────────────────────────────────────────

class TestMerge:
    def test_one_sided_changes_both_land(self):
        base = _ring_scene()
        local, _ = S.apply_ops(base, [{"op": "set", "id": "ring", "location": [0, 0, 2]}])
        remote, _ = S.apply_ops(base, [{"op": "material", "id": "gold", "roughness": 0.5},
                                       {"op": "add", "id": "extra", "primitive": "cube"}])
        remote["rev"] = 9
        merged, conflicts = S.merge3(base, local, remote)
        assert conflicts == []
        assert merged["objects"]["ring"]["location"] == [0, 0, 2]
        assert merged["materials"]["gold"]["roughness"] == 0.5 and "extra" in merged["objects"]
        assert merged["rev"] == 9
        assert S.normalize(merged) == merged

    def test_a_both_sided_change_keeps_local_and_reports(self):
        base = _ring_scene()
        local, _ = S.apply_ops(base, [{"op": "set", "id": "ring", "location": [0, 0, 2]}])
        remote, _ = S.apply_ops(base, [{"op": "set", "id": "ring", "location": [5, 0, 0]}])
        merged, conflicts = S.merge3(base, local, remote)
        assert conflicts == ["objects.ring"] and merged["objects"]["ring"]["location"] == [0, 0, 2]

    def test_deletes_merge(self):
        base = _ring_scene()
        local, _ = S.apply_ops(base, [{"op": "delete", "id": "pedestal"}])
        merged, conflicts = S.merge3(base, local, base)
        assert "pedestal" not in merged["objects"] and conflicts == []


# ─── summary / schema ───────────────────────────────────────────────────────

def test_summary_is_compact_and_names_the_selection():
    text = S.summary(_ring_scene(), selection=["ring"])
    assert "ring (mesh torus)" in text and "[selected]" in text and 'id "selected"' in text
    assert "material gold" in text and "mods bevel" in text
    assert len(text) < 2000


def test_the_apps_schema_json_is_current():
    """studio/src/schema.json is generated from this module; the app builds its
    entries from it. Regenerate: cd studio && python scripts/schema.py"""
    import json
    path = pathlib.Path(S.__file__).resolve().parents[3] / "studio" / "src" / "schema.json"
    if not path.exists():
        pytest.skip("studio/ source isn't in this checkout")
    expected = S.json_schema()
    expected.update(material_presets=S.MATERIAL_PRESETS, light_rigs=sorted(S.LIGHT_RIGS), new_scene=S.new_scene())
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(json.dumps(expected))


def test_json_schema_covers_the_vocabulary():
    js = S.json_schema()
    assert set(js["primitives"]) == set(S.PRIMITIVES) and set(js["modifiers"]) == set(S.MODIFIERS)
    assert js["modifiers"]["subsurf"]["properties"]["levels"]["maximum"] == 6
    assert "preset" in js["ops"] and "gold" in js["material_presets"]

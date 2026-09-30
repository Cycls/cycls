# The config contract, outside Blender:  uv run --with pytest pytest test_scenes.py
import pytest

import scenes


def test_defaults_fill_every_field():
    cfg = scenes.normalize({})
    assert cfg["object"] == "sphere" and cfg["lighting"] == "studio-3point"
    assert cfg["resolution"] == list(scenes.DEFAULT_RESOLUTION)
    assert cfg["samples"] == scenes.DEFAULT_SAMPLES and cfg["glb"] is True
    assert cfg["camera"] == {"angle": "front-3/4", "focal_mm": 50.0}


def test_the_plans_own_example_config_is_accepted():
    cfg = scenes.normalize({
        "preset": "product-shot", "object": "ico-sphere",
        "material": {"base_color": [0.8, 0.1, 0.1], "metallic": 0.9, "roughness": 0.2},
        "lighting": "studio-3point", "camera": {"angle": "front-3/4", "focal_mm": 50},
        "resolution": [1920, 1080], "samples": 128, "engine": "CYCLES"})
    assert cfg["material"]["metallic"] == 0.9 and cfg["resolution"] == [1920, 1080]


def test_colors_arrive_srgb_and_leave_linear():
    assert scenes._color("#ffffff", "c") == (1.0, 1.0, 1.0)
    r, g, b = scenes._color("#808080", "c")
    assert r == g == b and 0.21 < r < 0.22            # sRGB mid-grey is ~0.216 linear
    assert scenes._color([255, 0, 0], "c") == (1.0, 0.0, 0.0)   # 0–255 tolerated
    assert scenes._color("#f00", "c") == (1.0, 0.0, 0.0)


def test_preset_then_overrides():
    m = scenes.normalize({"material": {"preset": "gold", "roughness": 0.5}})["material"]
    assert m["metallic"] == 1.0 and m["roughness"] == 0.5
    assert scenes.normalize({"material": "glass"})["material"]["transmission"] == 1.0


def test_dark_rigs_default_to_a_dark_backdrop():
    light = scenes.normalize({"lighting": "softbox"})["backdrop"]
    dark = scenes.normalize({"lighting": "dramatic"})["backdrop"]
    assert dark[0] < 0.01 < light[0]
    assert scenes.normalize({"camera": "hero"})["camera"]["focal_mm"] == 85.0


@pytest.mark.parametrize("bad, field", [
    ({"object": "teapot"}, "object"),
    ({"obj": "cube"}, "unknown keys"),
    ({"resolution": [4000, 4000]}, "resolution"),
    ({"resolution": [2048, 2048]}, "pixel cap"),
    ({"resolution": 1080}, "resolution"),
    ({"samples": 9999}, "samples"),
    ({"engine": "EEVEE"}, "GPU"),
    ({"preset": "portrait"}, "preset"),
    ({"object": "text"}, "text"),
    ({"object": "text", "text": "x" * 25}, "at most"),
    ({"object": "text", "text": "مرحبا"}, "Latin"),
    ({"material": {"color": "#zz0000"}}, "hex"),
    ({"material": {"shininess": 1}}, "unknown keys"),
    ({"material": {"roughness": 2}}, "roughness"),
    ({"camera": {"angle": "drone"}}, "camera.angle"),
    ("torus", "object"),
])
def test_bad_configs_name_the_field(bad, field):
    with pytest.raises(ValueError, match=field):
        scenes.normalize(bad)

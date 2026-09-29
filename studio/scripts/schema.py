"""Write src/schema.json from the SDK's scene.py — the one source of truth.
Run from studio/: python scripts/schema.py (with the SDK checkout on PYTHONPATH)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from cycls._agent.studio import scene as S  # noqa: E402

out = S.json_schema()
out["material_presets"] = S.MATERIAL_PRESETS
out["light_rigs"] = sorted(S.LIGHT_RIGS)
out["new_scene"] = S.new_scene()
path = pathlib.Path(__file__).resolve().parents[1] / "src" / "schema.json"
path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print("wrote", path)

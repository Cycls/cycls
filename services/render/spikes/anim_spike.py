# Phase D spike: what Blender 5.2 on the engine offers for animation, and what a turntable
# frame costs. Runs bpy through the deployed engine's `script` op (120 s a call).
#
#   PYTHONPATH=E:/Cycls/cycls-sdk-studio python spikes/anim_spike.py [api] [video] [t16] [t32] [t540]
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cycls  # noqa: E402

from studio_try import product  # noqa: E402

API = r'''
import os
sc = bpy.context.scene; r = sc.render
print("version", bpy.app.version_string)
ff = getattr(bpy.app, "ffmpeg", None)
print("ffmpeg supported", ff and ff.supported, "libav", ff and ff.avcodec_version_string)
props = r.image_settings.bl_rna.properties
print("media_type", [i.identifier for i in props["media_type"].enum_items] if "media_type" in props else "absent")
print("file_format", [i.identifier for i in props["file_format"].enum_items])
print("ffmpeg enums", {p.identifier: [i.identifier for i in p.enum_items] for p in r.ffmpeg.bl_rna.properties if p.type == "ENUM"})
ob = bpy.data.objects.new("probe", None); sc.collection.objects.link(ob)
ob.rotation_euler = (0, 0, 0); ob.keyframe_insert("rotation_euler", index=2, frame=1)
ob.rotation_euler = (0, 0, 6.283185307179586); ob.keyframe_insert("rotation_euler", index=2, frame=121)
ob.location = (0, 0, 0); ob.keyframe_insert("location", frame=1)
ob.location = (0, 0, 2); ob.keyframe_insert("location", frame=31)
ob.location = (1, 0, 1); ob.keyframe_insert("location", frame=61)
act = ob.animation_data.action
print("action attrs", [a for a in ("fcurves", "layers", "slots", "fcurve_ensure_for_datablock") if hasattr(act, a)])
print("anim slot", ob.animation_data.action_slot and ob.animation_data.action_slot.identifier)
from bpy_extras import anim_utils
print("anim_utils", [n for n in dir(anim_utils) if "channelbag" in n or "fcurve" in n])
cb = anim_utils.action_get_channelbag_for_slot(act, ob.animation_data.action_slot)
print("channelbag fcurves", [(f.data_path, f.array_index, len(f.keyframe_points)) for f in cb.fcurves])
for f in cb.fcurves:
    k = f.keyframe_points
    print(" ", f.data_path, f.array_index, "interp", [p.interpolation for p in k], "handles", [p.handle_left_type for p in k],
          "extrap", f.extrapolation)
z = [f for f in cb.fcurves if f.data_path == "location" and f.array_index == 2][0]
print("loc.z at", {fr: round(z.evaluate(fr), 6) for fr in (1, 10, 20, 31, 40, 50, 61, 70)})
print("loc.z handles", [(tuple(round(v, 4) for v in p.handle_left), tuple(round(v, 4) for v in p.co), tuple(round(v, 4) for v in p.handle_right)) for p in z.keyframe_points])
se = sc.sequence_editor_create()
print("vse attrs", [a for a in ("strips", "sequences", "strips_all", "sequences_all") if hasattr(se, a)])
print("strips.new_movie", hasattr(getattr(se, "strips", None), "new_movie"))
print("cpu", os.cpu_count(), "threads", r.threads_mode, r.threads)
'''

VIDEO = r'''
import os, time, glob
os.makedirs("/tmp/spike", exist_ok=True)
sc = bpy.context.scene; r = sc.render
r.engine = "CYCLES"; sc.cycles.device = "CPU"
r.resolution_x, r.resolution_y, r.resolution_percentage = 320, 180, 100
sc.cycles.samples = 1; sc.cycles.use_denoising = False
r.fps = 24
try:
    r.image_settings.media_type = "VIDEO"
except Exception as e:
    print("media_type", e)
r.image_settings.file_format = "FFMPEG"
r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"; r.ffmpeg.ffmpeg_preset = "GOOD"
for i, (a, b) in enumerate([(1, 12), (13, 24)]):
    sc.frame_start, sc.frame_end = a, b
    r.filepath = f"/tmp/spike/seg{i}_"
    t = time.time(); bpy.ops.render.render(animation=True); print("segment", i, "secs", round(time.time() - t, 2))
files = sorted(glob.glob("/tmp/spike/*"))
print({os.path.basename(f): os.path.getsize(f) for f in files})
# concatenate through the sequencer, no re-render
cat = bpy.data.scenes.new("cat")
cat.render.resolution_x, cat.render.resolution_y, cat.render.fps = 320, 180, 24
cat.render.image_settings.media_type = "VIDEO"
cat.render.image_settings.file_format = "FFMPEG"
cat.render.ffmpeg.format = "MPEG4"; cat.render.ffmpeg.codec = "H264"; cat.render.ffmpeg.constant_rate_factor = "HIGH"
cat.render.use_sequencer = True
se = cat.sequence_editor_create()
at = 1
for f in files:
    s = se.strips.new_movie(os.path.basename(f), f, channel=1, frame_start=at)
    print("strip", s.name, "frames", s.frame_final_duration)
    at += s.frame_final_duration
cat.frame_start, cat.frame_end = 1, at - 1
cat.render.filepath = "/tmp/spike/whole_"
t = time.time()
with bpy.context.temp_override(scene=cat):
    bpy.ops.render.render(animation=True)
print("concat secs", round(time.time() - t, 2))
out = sorted(glob.glob("/tmp/spike/whole_*"))
print({os.path.basename(f): os.path.getsize(f) for f in out})
chk = bpy.data.scenes.new("chk").sequence_editor_create()
m = chk.strips.new_movie("w", out[0], channel=1, frame_start=1)
print("whole frames", m.frame_final_duration, "fps", m.fps if hasattr(m, "fps") else None)
'''

TIMING = r'''
import time, math
sc = bpy.context.scene; r = sc.render
r.engine = "CYCLES"; cy = sc.cycles; cy.device = "CPU"
r.resolution_x, r.resolution_y, r.resolution_percentage = {w}, {h}, 100
cy.samples = {samples}; cy.use_adaptive_sampling = True
cy.use_denoising = True; cy.denoiser = "OPENIMAGEDENOISE"
cy.max_bounces, cy.glossy_bounces, cy.transmission_bounces = 10, 6, 10
cy.caustics_reflective = cy.caustics_refractive = False; cy.sample_clamp_indirect = 8.0
r.use_persistent_data = {persistent}
r.image_settings.file_format = "PNG"; r.filepath = "/tmp/f.png"
subjects = [o for o in sc.objects if o.type == "MESH" and o.get("cycls_id") in ("ring", "ped")]
pivot = bpy.data.objects.new("turntable", None); sc.collection.objects.link(pivot)
for o in subjects:
    m = o.matrix_world.copy(); o.parent = pivot; o.matrix_world = m
pivot.rotation_euler = (0, 0, 0); pivot.keyframe_insert("rotation_euler", index=2, frame=1)
pivot.rotation_euler = (0, 0, 2 * math.pi); pivot.keyframe_insert("rotation_euler", index=2, frame=121)
secs = []
for fr in {frames}:
    sc.frame_set(fr)
    t = time.perf_counter(); bpy.ops.render.render(write_still=True); secs.append(round(time.perf_counter() - t, 2))
print("{tag}", "frames", {frames}, "secs", secs)
'''


def main(steps):
    call = cycls.remote("cycls-render", timeout=900)
    doc = product()

    def script(tag, code):
        t = time.monotonic()
        r = call(op="script", scene=doc, params={"code": code})
        wall = round(time.monotonic() - t, 1)
        if not r.get("ok"):
            print(tag, "FAILED", wall, r.get("error"), (r.get("trace") or "")[-1500:])
            return
        print(f"--- {tag} (wall {wall}s)")
        print(r["result"].get("stdout", ""))

    for step in steps:
        if step == "api":
            script("api", API)
        elif step == "video":
            script("video", VIDEO)
        elif step.startswith("t"):
            spec = {"t16": (1280, 720, 16, [1, 2, 3], True), "t32": (1280, 720, 32, [1, 2], True),
                    "t540": (960, 540, 16, [1, 2, 3, 4], True), "t16np": (1280, 720, 16, [1, 2, 3], False),
                    "t8": (1280, 720, 8, [1, 2, 3, 4], True)}[step]
            w, h, s, frames, pers = spec
            script(step, TIMING.format(w=w, h=h, samples=s, frames=frames, persistent=pers, tag=step))


if __name__ == "__main__":
    main(sys.argv[1:] or ["api"])

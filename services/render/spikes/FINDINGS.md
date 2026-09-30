# Studio Phase 0: spike findings (2026-09-28)

These are the go/no-go spikes for Cycls Studio, a Blender-style mini-app backed by a real Blender engine. **All three pass.** The plan is at `~/.claude/plans/what-do-u-think-fuzzy-pelican.md`.

## S1: a three.js viewport inside the app sandbox (`s1_viewport/`)

**Setup.** A hand-written single-file app (Vite + `vite-plugin-singlefile`, three.js 0.186 and Preact 10.29) was installed at `apps/spike3d/`. It ran in the real canvas (local agent, desktop Chrome 154, Intel UHD 630 integrated GPU).

**Bundle size.** 863 KB raw, 260 KB gzip, including three.js, its add-ons and Preact. That's under the 1.2 MB budget.

**Our own CSP meta works.** It has `connect-src 'none'` and sits after the injected shim. There were **no violations** and no errors.

**Environment in the frame.** WebGL2 on ANGLE/D3D11. PMREM (a reflection map built from RoomEnvironment), RectAreaLight and NeutralToneMapping all work. `isSecureContext` is true, `crypto.subtle` is available, and the origin is `null`.

**GPU cost.** Measured synchronously, with a 1-pixel readPixels after each frame to force completion:

| Scene | Frame time |
|---|---|
| Everything: 232k triangles, a glass (transmission) material, PMREM, an area light | 17.3 ms (~58 fps) |
| Without the glass | 9.1 ms |
| Without the 100k-triangle sphere | 13.4 ms |
| Minimal | 6.6 ms |

- Transmission is the most expensive material. Keep it to Material Preview.
- The "1-2 fps" seen earlier was Chrome throttling the unfocused automation window, not the app. **The real app must render on demand**, only when something changes. A continuous render loop saturated the renderer and timed out screenshots.

**Input.** Click-select via the raycaster works. Keyboard focus reaches the sandboxed frame (G and R arrived). A TransformControls drag works, and pointer capture is true. Autosave through `cycls.write` works.

**Found and fixed a real SDK bug in `client/src/components/app-bridge.ts`.**
- **Cause.** Every `cycls:ready` minted a new MessageChannel and overwrote `port`. A heavy app delays its first `init`, so the shim announces several times but keeps only the **first** port.
- **Effect.** All replies went to an orphaned channel. Reads hung forever, and writes took effect but never resolved.
- **Fix.** Reply on the channel the request arrived on. `port` becomes whichever channel the app last spoke on. Close every channel on detach.
- **Regression test.** "answers on the channel a request arrived on…" in `client/tests/app-bridge.test.ts`, on branch `feat/studio` (worktree `E:\Cycls\cycls-sdk-studio`). It failed before the fix and passes after. Live, with the fix, reads settle in ~20 ms and every write resolves.
- **Pre-existing, unrelated.** The two "write limit counts bytes" tests time out on this machine, identically on the untouched branch.

**Not tested.** Safari, Firefox, Android and iOS. They need real devices.

**Local environment note.** The machine's clock runs ~22 s behind. With the server's 10 s JWT leeway, each Clerk token is rejected for its first ~12 s. That produced intermittent "token is not yet valid (iat)" errors, "No apps yet" and "Couldn't load this file". It's a local artifact only.

## S2: a warm, sandboxed Blender worker (`s2_worker/`)

The worker handle is kept on `sys._cycls_blender` and keyed by a hash of the worker source plus the sandbox mode. It survives across calls on the dev executor. The protocol is JSON jobs on stdin and a dedicated response fd, and **only JSON and raw bytes come back to the parent**, never pickles.

**The platform is gVisor.** The executor reports `Linux 4.19.0-gvisor`. Agents are documented as Gen2 microVMs (kernel 6.9), so plain functions and executors are not the same runtime.
- Under gVisor, bwrap's `--unshare-net` **fails** with `loopback: Failed RTM_NEWADDR`.
- **Working isolation:** `unshare --net -- bwrap <SDK defaults + --unshare-pid/ipc/uts + --uid 65534 + --tmpfs /app + --new-session> -- blender …`

**What a script sees:**

| | Unsandboxed | Sandboxed |
|---|---|---|
| Internet | open | blocked |
| **Metadata server (169.254.169.254)** | **OPEN** | blocked |
| uid | 0 | 65534 |
| `/etc` | writable | read-only |
| Processes visible | 8 | 2 |
| `/app` | readable | masked |

This confirms the risk: unsandboxed bpy can reach the metadata server and fetch a service-account token.

**Plan for the engine:** use `unshare --net` wrapping bwrap. If `unshare` itself is refused (possible on Gen2), fall back to bwrap's own `--unshare-net`, which the SDK already relies on under Gen2.

**Performance** (8 vCPU):
- Worker boot: **1.0 s**, both unsandboxed and sandboxed.
- Warm `evaluate` of a cube with subsurf level 5 (12k triangles), extracting positions and indices as raw buffers: server round trip **p50 6.5–7.4 ms**, p95 10 ms.
- End to end from Egypt through the dev executor: **p50 ~555 ms**, which is mostly network plus per-call unpickling.
- Scene reset: `bpy.data.batch_remove` takes ~1 ms; `read_factory_settings(use_empty=True)` takes 180 ms. **Use batch_remove.**

**Memory.** 350 MB rising to 355 MB resident over 200 evaluates, on the same pid with no respawns.

**Recovery.**
- A hung op (30 s sleep with a 3 s timeout) gets its process group killed at 3 s. The next call respawns in 1.04 s.
- An explicit kill respawns in 1.0 s.

**Cross-job state persists** in a warm worker: job B read what job A stored. This is expected, and it is why **tainted ops (`script`, `import`) must recycle the worker**.

**Open:** whether `spec["min_instances"]` is accepted. Check at the Phase 2 deploy. Cold start looks modest: wall time minus call time was ~2–3 s, plus a ~1 s worker boot.

## S3: fidelity (the `fidelity` op in `s2_worker/worker.py`)

- **Euler order.** A Blender `'XYZ'` Euler (30°, 45°, 60°) matrix equals three.js `Euler(…, 'ZYX')` to within 1e-7. It does **not** equal three.js `'XYZ'`.
- **Parent-chain round trip.** Three levels, each with a rotation and a non-uniform scale, go document → bpy (`matrix_parent_inverse = I`) → document via `parent.matrix_world⁻¹ @ matrix_world` and decompose. Max error is 8.3e-7, from Blender's float32 math. Compare rotations as matrices, because Euler triples aren't unique.
- **Explicit n-gon meshes.** `vertices/loops/polygons.add` plus `foreach_set("co"/"vertex_index"/"loop_start")` works in 5.2; `loop_total` is derived. A pentagon plus a triangle gave `validate()` no changes.
- **Primitive topology** (`bmesh.ops.create_*`), as (verts, edges, faces):

| Primitive | Verts | Edges | Faces |
|---|---|---|---|
| cube | 8 | 12 | 6 |
| UV sphere 32×16 | 482 | 992 | 512 |
| ico sphere, 2 subdivisions | 42 | 120 | 80 |
| cylinder, 32 segments | 64 | 96 | 34 |
| cone, 32 segments | 33 | 64 | 33 |
| grid 10×10 | 121 | 220 | 100 |
| circle, 32 segments | 32 | 32 | 0 |
| monkey | 507 | 1005 | 500 |

  The app's client-side primitives must match these counts.

## Studio v2, Phase D: animation and video (`spikes/anim_spike.py`, 2026-09-29)

Run through the deployed engine's `script` op on the `product()` scene (gold ring on a marble
pedestal, dramatic rig), 8 CPUs.

- **Blender 5.2.2 LTS.** `bpy.app.ffmpeg.supported` is True (libav 62). `image_settings.media_type`
  takes `IMAGE`, `MULTI_LAYER_IMAGE` or `VIDEO`, and `file_format = "FFMPEG"` goes with `VIDEO`.
  MPEG4 container, H264 codec, `constant_rate_factor` HIGH and `ffmpeg_preset` GOOD all work.
- **Actions are layered only.** An action has `layers` and `slots`; there's no `action.fcurves`.
  Reach the curves through `bpy_extras.anim_utils.action_get_channelbag_for_slot(action,
  ob.animation_data.action_slot)` (or `action_ensure_channelbag_for_slot`). `keyframe_insert`
  still works and makes BEZIER keys with AUTO_CLAMPED handles and CONSTANT extrapolation.
- **New F-curves smooth their handles** (Continuous Acceleration): handles are 1/3 of the key
  interval, and a smoothing pass moves them. Set `fcurve.auto_smoothing = "NONE"` for the
  classic auto-clamped formula, which is what a JS and Python twin can match exactly.
- **The sequencer is `strips`** (`sequence_editor.strips`, `strips_all`; `strips.new_movie`).
  Two 12-frame mp4 segments joined into one 24-frame mp4 in 0.1 s at 320×180, and loading the
  result back as a movie strip reports 24 frames at 24 fps.
- **Per-frame cost** (steady state, persistent data, OIDN, adaptive sampling; the first frame
  of a call costs 2–3 s more):

| Resolution | Samples | s/frame | 120 frames on one instance |
|---|---|---|---|
| 1280×720 | 32 | 21.5 | 43 min |
| 1280×720 | 16 | 15.3 | 31 min |
| 1280×720 | 8 | 9.0 | 18 min |
| 960×540 | 16 | 8.8 | 18 min |

  Without persistent data, 720p at 16 samples takes 16.7–18.2 s. At 320×180 and 1 sample a
  frame still costs about 1.1 s, which is the floor from scene sync and file writes.
- **Decision.** No useful setting fits 120 frames in one 600 s call. Render in chunks of mp4
  segments, sized to about 5 minutes each, then an `encode` op joins them through the
  sequencer. A chunk is one request, so no request is held open for the whole video.

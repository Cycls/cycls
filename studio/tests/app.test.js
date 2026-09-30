// The controller against a fake host bridge and a fake viewport: agent patches
// merging into local edits, saves, and edit mode's mesh files.
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from "vitest";

let createApp, SCHEMA, clone, M;

beforeAll(async () => {
  globalThis.window = globalThis;
  globalThis.addEventListener ||= () => {};
  ({ createApp } = await import("../src/app.js"));
  ({ SCHEMA, clone } = await import("../src/doc.js"));
  M = await import("../src/mesh.js");
});

const cubeMesh = () => ({
  co: [-1, -1, -1, -1, -1, 1, -1, 1, -1, -1, 1, 1, 1, -1, -1, 1, -1, 1, 1, 1, -1, 1, 1, 1],
  faces: [[0, 1, 3, 2], [2, 3, 7, 6], [6, 7, 5, 4], [4, 5, 1, 0], [2, 6, 4, 0], [7, 3, 1, 5]],
  smooth: [false, false, false, false, false, false], uv: null, loose: [],
});
const TOP = 5;

function host(scene, extra = {}) {
  const files = new Map([["data/scene.json", JSON.stringify(scene)], ...Object.entries(extra)]);
  const writes = [], engineCalls = [];
  let command = null, engineImpl = null;
  window.cycls = {
    ready: Promise.resolve(),
    read: async (p) => { if (!files.has(p)) throw new Error(`no ${p}`); return files.get(p); },
    write: async (p, text) => { writes.push(p); files.set(p, text); },
    engine: async (op, payload) => {
      // Every start asks for a video left running; that's `jobs`, not an engine call.
      if (op === "video_jobs" && !engineImpl) return { jobs: [] };
      engineCalls.push({ op, payload: clone(payload) });
      return engineImpl(op, payload, files);
    },
    onCommand: (fn) => { command = fn; return () => {}; },
    me: { set: () => {} },
  };
  return { files, writes, engineCalls, send: (c) => command(c), onEngine: (f) => { engineImpl = f; },
           disk: () => JSON.parse(files.get("data/scene.json")) };
}

function fakeViewport() {
  const vp = {
    edit: null, calls: [],
    sync() {}, frame() {}, throughCamera: () => false, invalidate() {}, clearEvaluated() {},
    setEvaluated(id, key, data) { vp.evaluated = { ...(vp.evaluated || {}), [id]: data }; },
    setGizmoMode() {}, worldTRS: () => ({ location: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1] }),
    enterEdit(id, mesh, sel) { vp.edit = { id, mesh, sel }; vp.calls.push("enter"); },
    setEdit(mesh, sel, opts) { vp.edit = { ...vp.edit, mesh, sel, normal: opts?.normal ?? null }; },
    leaveEdit() { vp.edit = null; vp.calls.push("leave"); },
    setTool(t) { vp.tool = t; }, setSnap() {}, setProportional() {},
    knifeCrossings: () => vp.crossings || [],
    isGround: () => false,
    pose(doc) { vp.posed = doc; }, draw() {},
  };
  return vp;
}

async function started(scene, extra) {
  const h = host(scene, extra);
  const vp = fakeViewport();
  const app = createApp((el, hooks) => { vp.hooks = hooks; return vp; });
  await app.start({});
  // What the viewport reports for a click on an element / the end of a gizmo drag.
  const pick = (item, shift = false) => vp.hooks.onEditPick(item, shift);
  return { h, vp, app, a: app.actions, s: app.state, pick };
}

const scene = () => ({ ...clone(SCHEMA.new_scene), rev: 1, by: "agent" });
const flush = () => vi.advanceTimersByTimeAsync(1500);

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); delete window.cycls; });

describe("agent patches merge into local edits", () => {
  it("keeps the user's move and takes the agent's additions — on screen and on disk", async () => {
    const { h, a, s } = await started(scene());
    a.update((d) => { d.objects.cube.location = [2, 0, 1]; }, "move");
    const sphere = { ...clone(s.doc.objects.cube), name: "Sphere", mesh: "sphere", location: [-2, 0, 1] };
    h.send({ type: "patch", base: 1, rev: 2, label: "add a sphere, brighter light",
             set: { "objects.sphere": sphere, "meshes.sphere": { primitive: "uv_sphere", radius: 1, segments: 32, ring_count: 16 },
                    "objects.light": { ...clone(s.doc.objects.light), light: { ...s.doc.objects.light.light, energy: 2000 } } },
             delete: [] });
    expect(s.doc.objects.cube.location).toEqual([2, 0, 1]);
    expect(s.doc.objects.sphere.location).toEqual([-2, 0, 1]);
    expect(s.doc.objects.light.light.energy).toBe(2000);
    expect(s.undo.at(-1).label).toBe("Agent: add a sphere, brighter light");
    // The disk here still has rev 1 (older than the patch): the save must not take it as news.
    await flush();
    const disk = h.disk();
    expect(disk.rev).toBe(3);
    expect(disk.by).toMatch(/^app:/);
    expect(disk.objects.cube.location).toEqual([2, 0, 1]);
    expect(disk.objects.light.light.energy).toBe(2000);
    expect(disk.objects.sphere).toBeTruthy();
  });

  it("an entry both changed keeps the user's version, says so, and takes the rest", async () => {
    const { h, a, s } = await started(scene());
    a.update((d) => { d.objects.cube.location = [2, 0, 1]; }, "move");
    h.send({ type: "patch", base: 1, rev: 2, label: "recolour",
             set: { "objects.cube": { ...clone(s.base.objects.cube), location: [0, 3, 1] },
                    "world": { ...clone(s.base.world), strength: 0.9 } }, delete: [] });
    expect(s.doc.objects.cube.location).toEqual([2, 0, 1]);
    expect(s.doc.world.strength).toBe(0.9);
    expect(s.toast).toMatchObject({ kind: "warn" });
    expect(s.toast.text).toContain("objects.cube");
  });

  it("the agent deleting what the user didn't touch deletes it", async () => {
    const { h, a, s } = await started(scene());
    a.update((d) => { d.objects.cube.location = [2, 0, 1]; }, "move");
    h.send({ type: "patch", base: 1, rev: 2, set: {}, delete: ["objects.light"] });
    expect(s.doc.objects.light).toBeUndefined();
    expect(s.doc.objects.cube.location).toEqual([2, 0, 1]);
  });

  it("a missed step reads the disk and merges from there", async () => {
    const { h, a, s } = await started(scene());
    a.update((d) => { d.objects.cube.location = [2, 0, 1]; }, "move");
    const agent = { ...scene(), rev: 3 };
    agent.world.strength = 0.8;
    h.files.set("data/scene.json", JSON.stringify(agent));
    h.send({ type: "patch", base: 2, rev: 3, set: {}, delete: [] });            // base isn't ours
    await vi.advanceTimersByTimeAsync(0);
    expect(s.doc.world.strength).toBe(0.8);
    expect(s.doc.objects.cube.location).toEqual([2, 0, 1]);
  });

  it("a save finds the agent's newer scene on disk and merges before writing", async () => {
    const { h, a } = await started(scene());
    a.update((d) => { d.objects.cube.location = [2, 0, 1]; }, "move");
    const agent = { ...scene(), rev: 2 };
    agent.render.samples = 256;
    h.files.set("data/scene.json", JSON.stringify(agent));                       // no command reached us
    await flush();
    const disk = h.disk();
    expect(disk.rev).toBe(3);
    expect(disk.render.samples).toBe(256);
    expect(disk.objects.cube.location).toEqual([2, 0, 1]);
  });

  it("the turn's end re-reads the disk", async () => {
    const { h, s } = await started(scene());
    const agent = { ...scene(), rev: 2 };
    agent.world.color = "#112233";
    h.files.set("data/scene.json", JSON.stringify(agent));
    h.send({ type: "turn_end" });
    await vi.advanceTimersByTimeAsync(0);
    expect(s.doc.world.color).toBe("#112233");
  });
});

describe("images", () => {
  it("a textured primitive is drawn from Blender's mesh, UVs and all", async () => {
    const doc = scene();
    doc.textures = { wood: { name: "wood", data: "textures/t-0123456789ab.json", width: 4, height: 4, alpha: false } };
    doc.materials.material = { ...doc.materials.material, base_color_texture: "wood" };
    const { h, vp } = await started(doc);
    const f32 = (a) => btoa(String.fromCharCode(...new Uint8Array(new Float32Array(a).buffer)));
    const u32 = (a) => btoa(String.fromCharCode(...new Uint8Array(new Uint32Array(a).buffer)));
    h.onEngine((op, payload) => {
      expect(op).toBe("evaluate");
      expect(payload.params.ids).toEqual(["cube"]);
      return { ok: true, meshes: { cube: { positions: f32([0, 0, 0, 1, 0, 0, 0, 1, 0]), normals: f32([0, 0, 1, 0, 0, 1, 0, 0, 1]),
                                           uv: f32([0, 0, 1, 0, 0, 1]), index: u32([0, 1, 2]) } } };
    });
    await vi.advanceTimersByTimeAsync(400);
    expect([...vp.evaluated.cube.uv]).toEqual([0, 0, 1, 0, 0, 1]);
  });

  it("an untextured primitive stays on the fast path", async () => {
    const { h } = await started(scene());
    await vi.advanceTimersByTimeAsync(400);
    expect(h.engineCalls).toEqual([]);
  });
});

describe("material slots", () => {
  it("an app that opens a version 1 scene works on slots", async () => {
    const v1 = clone(scene());
    v1.version = 1;
    for (const o of Object.values(v1.objects)) if (o.materials) { o.material = o.materials[0] || null; delete o.materials; }
    const { s } = await started(v1);
    expect(s.doc.version).toBe(3);
    expect(s.doc.objects.cube.materials).toEqual(["material"]);
  });
});

describe("edit mode", () => {
  const explicit = () => {
    const side = M.toSidecar(cubeMesh());
    const doc = scene();
    doc.meshes = { ...doc.meshes, cube: { data: "meshes/m-aaaaaaaaaaaa.json", verts: 8, faces: 6, bbox: side.bbox } };
    return { doc, files: { "data/meshes/m-aaaaaaaaaaaa.json": JSON.stringify(side) } };
  };

  it("extrudes, writes the new mesh file before the scene, and undoes", async () => {
    const { doc, files } = explicit();
    const { h, a, s, vp, pick } = await started(doc, files);
    a.select(["cube"]);
    await a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    expect(s.mode).toBe("edit");
    expect(vp.edit.mesh.faces.length).toBe(6);
    a.edit.setMode("face");
    pick(TOP);
    expect(s.edit.items).toEqual([TOP]);
    a.edit.extrude();
    expect(s.editMesh.faces.length).toBe(10);
    expect(vp.edit.normal).toEqual([0, 0, 1]);
    const mid = s.doc.objects.cube.mesh;
    expect(mid).toMatch(/^m-[0-9a-f]{12}$/);
    expect(s.doc.meshes[mid]).toMatchObject({ data: `meshes/${mid}.json`, verts: 12, faces: 10 });
    expect(s.doc.meshes.cube).toBeUndefined();                                 // pruned
    await flush();
    const iMesh = h.writes.indexOf(`data/meshes/${mid}.json`), iScene = h.writes.lastIndexOf("data/scene.json");
    expect(iMesh).toBeGreaterThanOrEqual(0);
    expect(iMesh).toBeLessThan(iScene);
    expect(h.disk().objects.cube.mesh).toBe(mid);
    expect(M.fromSidecar(JSON.parse(h.files.get(`data/meshes/${mid}.json`))).faces.length).toBe(10);
    a.undo();
    await vi.advanceTimersByTimeAsync(0);
    expect(s.doc.objects.cube.mesh).toBe("cube");
    expect(s.editMesh.faces.length).toBe(6);
    expect(s.mode).toBe("edit");
  });

  it("a gizmo move commits the moved mesh as one step", async () => {
    const { doc, files } = explicit();
    const { a, s, vp, pick } = await started(doc, files);
    a.select(["cube"]);
    a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    a.edit.setMode("vert");
    pick(7);
    pick(3, true);
    pick(3, true);                                           // shift-click again: off
    expect(s.edit.items).toEqual([7]);
    const moved = M.moveVerts(s.editMesh, [7], (x, y, z) => [x, y, z + 1]);
    const before = s.undo.length;
    vp.hooks.onEditTransformEnd(moved);
    expect(s.undo.length).toBe(before + 1);
    expect(s.undo.at(-1).label).toBe("move");
    expect(s.doc.meshes[s.doc.objects.cube.mesh].bbox[1][2]).toBe(2);
    expect(s.edit.items).toEqual([7]);
  });

  it("a Blender op sends the selection and a mesh the engine can read, then shows the result", async () => {
    const { doc, files } = explicit();
    const { h, a, s, pick } = await started(doc, files);
    a.select(["cube"]);
    a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    a.edit.setMode("face");
    pick(TOP);
    a.edit.extrude();                                        // an unsaved mesh the engine must still find
    const pending = s.doc.meshes[s.doc.objects.cube.mesh].data;
    const bevelled = M.toSidecar(M.extrudeFaces(cubeMesh(), [0]).mesh);
    h.onEngine((op, payload, disk) => {
      expect(disk.has(`data/${pending}`)).toBe(true);        // flushed before the call
      disk.set("data/meshes/m-bbbbbbbbbbbb.json", JSON.stringify(bevelled));
      return { ok: true, mesh_id: "m-bbbbbbbbbbbb", data: "meshes/m-bbbbbbbbbbbb.json", verts: 12, faces: 10,
               bbox: bevelled.bbox, modifiers: null, removed: [] };
    });
    await a.edit.blender("bevel", "bevel");
    const call = h.engineCalls.at(-1);
    expect(call.op).toBe("apply");
    expect(call.payload.params).toMatchObject({ id: "cube", op: "bevel", selection: { faces: [TOP] }, width: 0.05, segments: 2 });
    expect(s.doc.objects.cube.mesh).toBe("m-bbbbbbbbbbbb");
    expect(s.editMesh.faces.length).toBe(10);
    expect(s.edit.items).toEqual([]);
    expect(s.mode).toBe("edit");
  });

  it("bisect sends the drawn plane, the side to drop and the fill, on everything when nothing is selected", async () => {
    const { doc, files } = explicit();
    const { h, a, s, vp } = await started(doc, files);
    a.select(["cube"]);
    a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    vp.bisectPlane = (points) => (points.length === 2 ? { plane_co: [0, 0, 5], plane_no: [0, 0, 1] } : null);
    const half = M.toSidecar(cubeMesh());
    h.onEngine((op, payload, disk) => {
      disk.set("data/meshes/m-cccccccccccc.json", JSON.stringify(half));
      return { ok: true, mesh_id: "m-cccccccccccc", data: "meshes/m-cccccccccccc.json", verts: 8, faces: 6,
               bbox: half.bbox, modifiers: null, removed: [], selection: { edges: [[0, 1], [1, 3]] } };
    });
    a.edit.startTool("bisect");
    expect(s.tool).toEqual({ kind: "bisect", points: [] });
    a.setTool("bisect_clear", "left");
    a.setTool("bisect_fill", true);
    await vp.hooks.onToolCommit({ kind: "bisect", points: [[10, 10], [200, 40]] });
    await vi.advanceTimersByTimeAsync(0);
    const call = h.engineCalls.at(-1);
    expect(call.payload.params).toMatchObject({ op: "bisect", selection: "all", plane_co: [0, 0, 5], plane_no: [0, 0, 1],
                                                clear_outer: true, clear_inner: false, fill: true });
    expect(s.tool).toBeNull();
    expect(s.doc.objects.cube.mesh).toBe("m-cccccccccccc");
    expect(s.edit.mode).toBe("vert");
    expect(s.edit.items.length).toBeGreaterThan(0);                 // the cut, selected
  });

  it("picking what moves snap to turns snapping on", async () => {
    const { a, s, vp } = await started(scene());
    let target = null;
    vp.setSnapTarget = (t) => { target = t; };
    a.edit.setSnapTarget("surface");
    expect([s.snap, s.snapTarget, target]).toEqual([true, "surface", "surface"]);
  });

  it("keeps what Blender left selected, in the current element mode — inset, then extrude", async () => {
    const { doc, files } = explicit();
    const { h, a, s, pick } = await started(doc, files);
    a.select(["cube"]);
    a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    a.edit.setMode("face");
    pick(TOP);
    const inset = M.toSidecar(M.extrudeFaces(cubeMesh(), [TOP]).mesh);   // any 10-face mesh will do
    h.onEngine((op, payload, disk) => {
      disk.set("data/meshes/m-cccccccccccc.json", JSON.stringify(inset));
      return { ok: true, mesh_id: "m-cccccccccccc", data: "meshes/m-cccccccccccc.json", verts: 12, faces: 10,
               bbox: inset.bbox, modifiers: null, removed: [], selection: { faces: [TOP] } };
    });
    await a.edit.blender("inset", "inset");
    expect(s.edit.items).toEqual([TOP]);
    a.edit.extrude();                                        // carries on without a new pick
    expect(s.editMesh.faces.length).toBe(14);
    a.edit.setMode("vert");
    await a.edit.blender("inset", "inset");
    expect(s.edit.items).toEqual(M.selectedVerts(M.fromSidecar(inset), { mode: "face", items: [TOP] }).sort((x, y) => x - y));
  });

  it("Assign puts the selected faces in a slot, as a new mesh file", async () => {
    const { doc, files } = explicit();
    const { a, s, pick } = await started(doc, files);
    a.select(["cube"]);
    a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    a.edit.setMode("face");
    pick(TOP);
    a.edit.assignSlot(1);
    expect(s.editMesh.mi[TOP]).toBe(1);
    expect(s.doc.objects.cube.mesh).not.toBe("cube");
    expect(s.undo.at(-1).label).toBe("assign material");
  });

  it("loop cut: a ring cut as one step, then adjusted in place", async () => {
    const { doc, files } = explicit();
    const { a, s } = await started(doc, files);
    a.select(["cube"]);
    a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    const steps = s.undo.length;
    a.edit.loopCut([0, 1], 1);
    expect(s.editMesh.faces.length).toBe(10);
    expect(s.undo.length).toBe(steps + 1);
    expect(s.undo.at(-1).label).toBe("loop cut");
    a.edit.adjustLoopCut({ cuts: 3 });
    expect(s.editMesh.faces.length).toBe(18);
    expect(s.undo.length).toBe(steps + 1);                   // replaced, not stacked
    expect(s.lastCut.cuts).toBe(3);
  });

  it("knife cuts where the viewport says the path crosses; J joins two vertices", async () => {
    const { doc, files } = explicit();
    const { a, s, vp, pick } = await started(doc, files);
    a.select(["cube"]);
    a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    a.edit.startTool("knife");
    expect(vp.tool.kind).toBe("knife");
    vp.crossings = [{ edge: [7, 3], t: 0.5 }, { edge: [1, 5], t: 0.5 }];
    a.edit.knife();
    expect(s.editMesh.faces.length).toBe(7);
    expect(s.undo.at(-1).label).toBe("knife");
    a.edit.setMode("vert");
    pick(0); pick(3, true);                                  // two corners of the x = −1 face
    await a.edit.connect();
    expect(s.editMesh.faces.length).toBe(8);
    expect(s.undo.at(-1).label).toBe("connect");
  });

  it("a primitive becomes an explicit mesh (with Blender) before editing", async () => {
    const { h, a, s } = await started(scene());
    const side = M.toSidecar(cubeMesh());
    h.onEngine((op, payload, disk) => {
      disk.set("data/meshes/m-cccccccccccc.json", JSON.stringify(side));
      return { ok: true, mesh_id: "m-cccccccccccc", data: "meshes/m-cccccccccccc.json", verts: 8, faces: 6,
               bbox: side.bbox, modifiers: null, removed: [] };
    });
    a.select(["cube"]);
    await a.edit.toggle();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.engineCalls[0].payload.params).toEqual({ id: "cube", op: "convert" });
    expect(s.doc.objects.cube.mesh).toBe("m-cccccccccccc");
    expect(s.doc.objects.cube.material).toBe(scene().objects.cube.material);    // kept
    expect(s.doc.meshes.cube).toBeUndefined();
    expect(s.mode).toBe("edit");
  });

  it("exports the scene through the engine route", async () => {
    const { h, a, s } = await started(scene());
    h.onEngine(() => ({ ok: true, path: "exports/scene.glb" }));
    await a.exportAs("glb");
    expect(h.engineCalls.at(-1)).toMatchObject({ op: "export", payload: { params: { format: "glb" }, name: "scene" } });
    expect(s.toast.text).toBe("Saved exports/scene.glb");
  });

  it("applying a modifier keeps the rest of the stack from Blender's answer", async () => {
    const doc = scene();
    doc.objects.cube.modifiers = [{ type: "bevel", width: 0.1, segments: 3, limit_method: "angle", angle_limit: 30, show: true },
                                  { type: "subsurf", levels: 1, render_levels: 2, show: true }];
    const { h, a, s } = await started(doc);
    const side = M.toSidecar(cubeMesh());
    h.onEngine(() => ({ ok: true, mesh_id: "m-dddddddddddd", data: "meshes/m-dddddddddddd.json", verts: 8, faces: 6,
                        bbox: side.bbox, modifiers: [doc.objects.cube.modifiers[1]], removed: [] }));
    a.select(["cube"]);
    await a.applyModifier(0);
    await vi.advanceTimersByTimeAsync(0);
    expect(h.engineCalls.find((c) => c.op === "apply").payload.params).toEqual({ id: "cube", op: "modifier_apply", index: 0 });
    expect(s.doc.objects.cube.modifiers.map((m) => m.type)).toEqual(["subsurf"]);
  });
});


describe("animation in the app", () => {
  const spinning = () => {
    const d = scene();
    d.objects.cube.keys = { location: [[1, [0, 0, 1], "bezier"], [60, [4, 0, 1], "bezier"]] };
    return d;
  };

  it("draws the frame it's on, keys a move of an animated channel there, and moves a still one", async () => {
    const { a, s, vp } = await started(spinning());
    expect(s.frame).toBe(1);
    a.setFrame(60);
    expect(vp.posed.objects.cube.location).toEqual([4, 0, 1]);
    a.setFrame(30);
    a.setTransform("cube", { location: [2, 3, 1], rotation: [0, 0, 45], scale: [1, 1, 1] });
    const cube = s.doc.objects.cube;
    expect(cube.keys.location.map((k) => k[0])).toEqual([1, 30, 60]);
    expect(cube.keys.location[1][1]).toEqual([2, 3, 1]);
    expect(cube.rotation).toEqual([0, 0, 45]);                   // still: it just turns
    expect(cube.keys.rotation).toBeUndefined();
    expect(cube.location).toEqual([0, 0, 1]);                    // an animated channel rests at the first frame
    expect(s.undo.at(-1).label).toBe("transform");
  });

  it("auto-key keys a still channel too, and a turn keeps counting past 180°", async () => {
    const { a, s } = await started(spinning());
    a.setAutokey(true);
    a.setFrame(10);
    a.setTransform("cube", { rotation: [0, 0, 170] });
    a.setFrame(20);
    a.setTransform("cube", { rotation: [0, 0, -170] });          // the gizmo's Euler wraps; the key doesn't
    expect(s.doc.objects.cube.keys.rotation.map((k) => k[1][2])).toEqual([170, 190]);
  });

  it("I keys the selection where it is, Alt+I takes this frame's keys away", async () => {
    const { a, s } = await started(scene());
    a.select(["cube"]);
    a.setFrame(12);
    a.insertKeys();
    expect(Object.keys(s.doc.objects.cube.keys)).toEqual(["location", "rotation", "scale"]);
    expect(s.doc.objects.cube.keys.location).toEqual([[12, [0, 0, 1], "bezier"]]);
    a.setInterpolation("linear");
    expect(s.doc.objects.cube.keys.scale[0][2]).toBe("linear");
    a.deleteKeys();
    expect(s.doc.objects.cube.keys).toBeUndefined();
  });

  it("the timeline's range pins what rests where the keys put its first frame", async () => {
    const { a, s } = await started(spinning());
    a.setAnimation("frame_start", 60);
    expect(s.doc.objects.cube.location).toEqual([4, 0, 1]);
    a.setAnimation("frame_end", 20);                              // before the start: the start follows
    expect([s.doc.animation.frame_start, s.doc.animation.frame_end]).toEqual([20, 20]);
  });

  it("drives a video a chunk at a time, waits when told to, then joins it", async () => {
    const { h, a, s } = await started(spinning());
    const job = { id: "v-0000abcd", status: "running", done: 0, total: 60, seconds_left: 300, by: "app" };
    let chunks = 0;
    h.onEngine((op) => {
      if (op === "video_start") return { job };
      if (op === "video_chunk") {
        chunks++;
        if (chunks === 2) return { job: { ...job, done: 6 }, wait: 5, reason: "the Studio engine is busy" };
        const done = Math.min(60, chunks * 30);
        return { job: { ...job, done }, chunk: chunks, wait: done === 60 ? 0 : undefined };
      }
      if (op === "video_finish") return { job: { ...job, status: "done", done: 60 }, path: "renders/animation.mp4", poster: "data:image/jpeg;base64,x" };
      throw new Error(op);
    });
    await a.renderVideo();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.engineCalls.find((c) => c.op === "video_start").payload.scene.objects.cube.keys).toBeTruthy();
    await vi.advanceTimersByTimeAsync(6000);                      // the busy wait
    await vi.advanceTimersByTimeAsync(1);
    expect(h.engineCalls.filter((c) => c.op === "video_chunk")).toHaveLength(3);
    expect(h.engineCalls.at(-1).op).toBe("video_finish");
    expect(s.preview).toMatchObject({ kind: "Video", path: "renders/animation.mp4" });
    expect(s.video).toBeNull();
  });

  it("an agent's video, or one left running, is picked up; Cancel stops it", async () => {
    const d = spinning();
    const h = host(d);
    const job = { id: "v-0000beef", status: "running", done: 30, total: 60, seconds_left: 100 };
    let release;
    h.onEngine((op) => {
      if (op === "video_jobs") return { jobs: [job] };
      if (op === "video_chunk") return new Promise((r) => { release = r; });
      if (op === "video_cancel") return { job: { ...job, status: "cancelled" } };
      throw new Error(op);
    });
    const vp = fakeViewport();
    const app = createApp((el, hooks) => { vp.hooks = hooks; return vp; });
    await app.start({});
    await vi.advanceTimersByTimeAsync(1);
    expect(app.state.video).toMatchObject({ id: "v-0000beef", done: 30 });
    await app.actions.cancelVideo();
    expect(app.state.video).toBeNull();
    release({ job: { ...job, done: 60 }, chunk: 2, wait: 0 });   // the chunk in flight comes back: dropped
    await vi.advanceTimersByTimeAsync(1);
    expect(h.engineCalls.map((c) => c.op)).toEqual(["video_jobs", "video_chunk", "video_cancel"]);
    expect(app.state.video).toBeNull();
  });
});

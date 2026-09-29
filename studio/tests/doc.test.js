import { describe, it, expect } from "vitest";
import { SCHEMA, clone, deepEqual, diff, patch, merge3, make, addObject, duplicate, remove, decodeSidecar, newId, isBackdrop, pruneTextures, hasTexture } from "../src/doc.js";

const scene = () => clone(SCHEMA.new_scene);

describe("entries the app makes are already normalized (as scene.py would write them)", () => {
  it("a mesh object and its primitive", () => {
    const py = SCHEMA.new_scene;
    expect(deepEqual(make.mesh("Cube", "cube", { material: "material", location: [0, 0, 1] }), py.objects.cube)).toBe(true);
    expect(deepEqual(make.primitive("cube"), py.meshes.cube)).toBe(true);
  });
  it("a light, a camera and a material", () => {
    const py = SCHEMA.new_scene;
    const light = make.light("Light", "point", { location: py.objects.light.location, rotation: py.objects.light.rotation });
    expect(deepEqual(light, py.objects.light)).toBe(true);
    const cam = make.camera("Camera", { location: py.objects.camera.location, rotation: py.objects.camera.rotation });
    expect(deepEqual(cam, py.objects.camera)).toBe(true);
    expect(deepEqual(make.material("Material", null, { base_color: "#cccccc", roughness: 0.5 }), py.materials.material)).toBe(true);
  });
  it("presets carry scene.py's values", () => {
    const gold = make.material("Gold", "gold");
    expect(gold.metallic).toBe(1);
    expect(gold.base_color).toBe(SCHEMA.material_presets.gold.base_color);
  });
});

describe("the set vs the subjects", () => {
  it("the studio rig and ground planes are the set; everything else is a subject", () => {
    let { doc } = addObject(scene(), "mesh:plane");
    doc.objects.studio_key = clone(doc.objects.light);
    expect(isBackdrop(doc, "plane")).toBe(true);
    expect(isBackdrop(doc, "studio_key")).toBe(true);
    expect(isBackdrop(doc, "cube")).toBe(false);
    expect(isBackdrop(doc, "light")).toBe(false);
    expect(isBackdrop(doc, "nope")).toBe(false);
  });
});

describe("add / duplicate / delete", () => {
  it("adds with fresh ids", () => {
    let { doc, id } = addObject(scene(), "mesh:torus");
    expect(id).toBe("torus");
    expect(doc.meshes[doc.objects.torus.mesh].primitive).toBe("torus");
    ({ doc, id } = addObject(doc, "mesh:torus"));
    expect(id).toBe("torus_2");
    ({ doc, id } = addObject(doc, "light:area"));
    expect(doc.objects[id].light.kind).toBe("area");
  });
  it("duplicates the mesh too", () => {
    const { doc, id } = duplicate(scene(), "cube");
    expect(doc.objects[id].mesh).not.toBe("cube");
    expect(deepEqual(doc.meshes[doc.objects[id].mesh], doc.meshes.cube)).toBe(true);
  });
  it("delete keeps children in place and drops orphan meshes", () => {
    const d = scene();
    d.objects.light.parent = "cube";
    const out = remove(d, ["cube"], () => ({ location: [9, 9, 9], rotation: [0, 0, 0], scale: [1, 1, 1] }));
    expect(out.objects.light.parent).toBe(null);
    expect(out.objects.light.location).toEqual([9, 9, 9]);
    expect(out.meshes.cube).toBeUndefined();
  });
  it("newId", () => {
    expect(newId({ a: 1 }, "A b!")).toBe("a_b");
    expect(newId({}, "")).toBe("object");
  });
});

describe("diff / patch / merge3 match scene.py", () => {
  it("patch(diff) reproduces the target", () => {
    const a = scene();
    const b = addObject(a, "mesh:cone").doc;
    b.world.strength = 1.5;
    delete b.objects.light;
    expect(deepEqual(patch(a, diff(a, b)), b)).toBe(true);
    expect(diff(a, b).delete).toEqual(["objects.light"]);
  });
  it("one-sided changes both land; both-sided keeps local and reports", () => {
    const base = scene();
    const local = clone(base); local.objects.cube.location = [0, 0, 5];
    const remote = clone(base); remote.materials.material.roughness = 0.9; remote.rev = 4;
    const m = merge3(base, local, remote);
    expect(m.conflicts).toEqual([]);
    expect(m.doc.objects.cube.location).toEqual([0, 0, 5]);
    expect(m.doc.materials.material.roughness).toBe(0.9);
    expect(m.doc.rev).toBe(4);
    const r2 = clone(base); r2.objects.cube.location = [1, 1, 1];
    expect(merge3(base, local, r2).conflicts).toEqual(["objects.cube"]);
  });
  it("deepEqual ignores key order and float noise", () => {
    expect(deepEqual({ a: 1, b: [1, 2] }, { b: [1, 2], a: 1.0000000001 })).toBe(true);
    expect(deepEqual({ a: 1 }, { a: 1, b: 2 })).toBe(false);
  });
});

describe("mesh sidecars", () => {
  it("fan-triangulates n-gons", () => {
    const b64 = (arr) => btoa(String.fromCharCode(...new Uint8Array(arr.buffer)));
    const side = { co: b64(new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0.5, 2, 0])),
                   loop_start: b64(new Uint32Array([0])), loops: b64(new Uint32Array([0, 1, 4, 2, 3])) };
    const { positions, index } = decodeSidecar(side);
    expect(positions.length).toBe(15);
    expect([...index]).toEqual([0, 1, 4, 0, 4, 2, 0, 2, 3]);
  });
});

describe("textures", () => {
  it("an image no material uses is dropped, one in use stays", () => {
    const doc = { ...scene(), textures: { a: { name: "a", data: "textures/t-000000000000.json", width: 1, height: 1, alpha: false },
                                          b: { name: "b", data: "textures/t-111111111111.json", width: 1, height: 1, alpha: false } } };
    doc.materials.material = { ...doc.materials.material, base_color_texture: "a" };
    pruneTextures(doc);
    expect(Object.keys(doc.textures)).toEqual(["a"]);
    expect(hasTexture(doc.materials.material)).toBe(true);
  });

  it("materials made here carry the image fields scene.py fills", () => {
    const m = make.material("Wood");
    expect(m).toMatchObject({ base_color_texture: null, roughness_texture: null, normal_texture: null,
                              texture_scale: [1, 1], texture_offset: [0, 0], texture_rotation: 0, normal_strength: 1 });
  });
});

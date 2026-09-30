import { describe, it, expect } from "vitest";
import { sample, posed, setKeys, removeKeys, keyFrames, turntable, pinStill } from "../src/anim.js";
import { SCHEMA, clone } from "../src/doc.js";
import twin from "./fixtures/anim_twin.json";
import golden from "./fixtures/anim_golden.json";

// scene.py sampled these (tests/fixtures/anim_twin.json, regenerated from scene.sample):
// the twin must land on the same numbers, or a save would read as a change.
describe("the evaluator is scene.py's", () => {
  for (const [name, { keys, samples }] of Object.entries(twin)) {
    it(name, () => {
      for (const [f, v] of samples) {
        const got = sample(keys, f);
        for (let c = 0; c < 3; c++) expect(Math.abs(got[c] - v[c])).toBeLessThan(1e-9);
      }
    });
  }
});

// Blender keyed these through the engine's real build and sampled them (cycls-render's
// `studio_try.py dev anim`): an empty's location, and another's rotation in degrees. float32.
describe("the evaluator lands on Blender's own samples", () => {
  for (const [name, c] of Object.entries(golden)) {
    it(name, () => {
      for (const ch of ["location", "rotation"]) {
        for (const [f, want] of c[ch]) {
          const got = sample(c.keys, f);
          for (let i = 0; i < 3; i++) expect(Math.abs(got[i] - want[i])).toBeLessThanOrEqual(1e-4 + 1e-6 * Math.abs(want[i]));
        }
      }
    });
  }
});

describe("keyframes in the app", () => {
  const scene = () => clone(SCHEMA.new_scene);

  it("keys the pose where the object is, and a still scene stays the same object", () => {
    const doc = scene();
    expect(posed(doc, 50)).toBe(doc);
    const o = doc.objects.cube;
    setKeys(o, 1);
    setKeys(o, 60, ["location"], { location: [4, 0, 1] });
    expect(keyFrames(o)).toEqual([1, 60]);
    expect(posed(doc, 60).objects.cube.location).toEqual([4, 0, 1]);
    expect(posed(doc, 60).objects.camera).toBe(doc.objects.camera);
    removeKeys(o, 60);
    expect(o.keys.location).toHaveLength(1);
    removeKeys(o);
    expect(o.keys).toBeUndefined();
  });

  it("a turntable loops round the objects' base, one step from the last frame to the first", () => {
    const doc = turntable(scene(), ["cube"], [0, 0, 0]);
    expect(doc.objects.cube.parent).toBe("turntable");
    const step = sample(doc.objects.turntable.keys.rotation, 2)[2];
    expect(sample(doc.objects.turntable.keys.rotation, doc.animation.frame_end)[2] + step).toBeCloseTo(360, 9);
    expect(pinStill(clone(doc))).toEqual(doc);
  });
});

import { describe, it, expect } from "vitest";
import { fit, estimateSeconds, workOf } from "../src/eta.js";

// The engine's own benchmark (cycls-render README): Blender seconds at 8 threads.
const BENCH = [[1280, 720, 32, 30], [1280, 720, 64, 52], [1280, 720, 128, 76], [1920, 1080, 32, 51]];
const log = (rows) => rows.map(([w, h, s, t]) => ({ resolution: [w, h], samples: s, seconds: t }));

describe("render time estimate", () => {
  it("starts from a prior with no history", () => {
    expect(estimateSeconds([], 1280, 720, 32)).toBe(Math.round(1 + 0.8 * workOf(1280, 720, 32) + 4));
  });

  it("one render sets the rate", () => {
    const f = fit(log([[1280, 720, 32, 60]]));
    expect(f.a).toBe(0);
    expect(f.b).toBeCloseTo(60 / workOf(1280, 720, 32));
  });

  it("with a few renders, fits the line — and lands within 25% of the benchmark", () => {
    const history = log(BENCH.slice(0, 3));
    const est = estimateSeconds(history, 1920, 1080, 32) - 4;        // Blender's part of it
    expect(Math.abs(est - 51) / 51).toBeLessThan(0.25);
  });

  it("ignores rows it can't read", () => {
    expect(fit([null, { resolution: "x" }, { resolution: [10, 10], samples: 0, seconds: 3 }])).toEqual({ a: 1, b: 0.8 });
  });
});

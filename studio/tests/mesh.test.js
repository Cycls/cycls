import { describe, it, expect } from "vitest";
import { fromSidecar, toSidecar, sidecarId, edges, remove, extrudeFaces, extrudeEdges, extrudeVerts, fill,
         mergeAtCenter, moveVerts, faceNormal, centroid, displayBuffers, selectedVerts, engineSelection } from "../src/mesh.js";
import { decodeSidecar } from "../src/doc.js";

// Blender's default cube: 8 vertices, 6 outward quads.
const cube = () => ({
  co: [-1, -1, -1, -1, -1, 1, -1, 1, -1, -1, 1, 1, 1, -1, -1, 1, -1, 1, 1, 1, -1, 1, 1, 1],
  faces: [[0, 1, 3, 2], [2, 3, 7, 6], [6, 7, 5, 4], [4, 5, 1, 0], [2, 6, 4, 0], [7, 3, 1, 5]],
  smooth: [false, false, false, false, false, false], uv: null, loose: [],
});
const TOP = 5;   // [7, 3, 1, 5]: z = +1

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const outward = (m, center = [0, 0, 0]) => m.faces.every((f) => {
  const c = centroid(m, f);
  return dot(faceNormal(m, f), [c[0] - center[0], c[1] - center[1], c[2] - center[2]]) > 0;
});
// Closed and consistently wound: every directed edge appears once, its reverse once.
const manifold = (m) => {
  const d = new Map();
  for (const f of m.faces) for (let i = 0; i < f.length; i++) {
    const k = `${f[i]}>${f[(i + 1) % f.length]}`;
    d.set(k, (d.get(k) || 0) + 1);
  }
  return [...d.entries()].every(([k, n]) => n === 1 && d.get(k.split(">").reverse().join(">")) === 1);
};

describe("the cycls.mesh codec matches the engine's", () => {
  it("round-trips a mesh", () => {
    const m = cube();
    const back = fromSidecar(toSidecar(m));
    expect(back.co).toEqual(m.co);
    expect(back.faces).toEqual(m.faces);
    expect(back.smooth).toEqual(m.smooth);
    expect(back.loose).toEqual([]);
  });
  it("writes what doc.js (and the engine) read", () => {
    const side = toSidecar(cube());
    expect(side).toMatchObject({ format: "cycls.mesh", version: 1, counts: { verts: 8, faces: 6, loops: 24 },
                                 bbox: [[-1, -1, -1], [1, 1, 1]] });
    expect(decodeSidecar(side).index.length).toBe(36);
  });
  it("keeps loose edges and per-corner uvs", () => {
    const m = { ...cube(), loose: [[0, 7]], uv: cube().faces.map(() => [0, 0, 1, 0, 1, 1, 0, 1]) };
    const back = fromSidecar(toSidecar(m));
    expect(back.loose).toEqual([[0, 7]]);
    expect(back.uv[2]).toEqual([0, 0, 1, 0, 1, 1, 0, 1]);
  });
  it("names a sidecar by its content", () => {
    const a = JSON.stringify(toSidecar(cube()));
    const b = JSON.stringify(toSidecar(moveVerts(cube(), [0], (x, y, z) => [x, y, z - 0.5])));
    expect(sidecarId(a)).toMatch(/^m-[0-9a-f]{12}$/);
    expect(sidecarId(a)).toBe(sidecarId(a));
    expect(sidecarId(a)).not.toBe(sidecarId(b));
  });
});

describe("edit-mode edits", () => {
  it("counts a cube's edges once each", () => {
    expect(edges(cube()).length).toBe(12);
  });
  it("the fixture is a closed outward cube", () => {
    expect(manifold(cube())).toBe(true);
    expect(outward(cube())).toBe(true);
  });
  it("deletes a vertex with its faces", () => {
    const m = remove(cube(), { mode: "vert", items: [7] });
    expect(m.co.length / 3).toBe(7);
    expect(m.faces.length).toBe(3);
  });
  it("deletes an edge with its two faces", () => {
    const m = remove(cube(), { mode: "edge", items: [[3, 7]] });
    expect(m.faces.length).toBe(4);
    expect(m.co.length / 3).toBe(8);
  });
  it("deletes a face, keeping its vertices while other faces use them", () => {
    const m = remove(cube(), { mode: "face", items: [TOP] });
    expect(m.faces.length).toBe(5);
    expect(m.co.length / 3).toBe(8);
  });
  it("extrudes the top face into a closed, outward solid", () => {
    const { mesh, selection } = extrudeFaces(cube(), [TOP]);
    expect(mesh.co.length / 3).toBe(12);
    expect(mesh.faces.length).toBe(10);
    expect(selection).toEqual({ mode: "face", items: [TOP] });
    const moved = moveVerts(mesh, selectedVerts(mesh, selection), (x, y, z) => [x, y, z + 1]);
    expect(manifold(moved)).toBe(true);
    expect(outward(moved, [0, 0, 0.5])).toBe(true);
    expect(centroid(moved, moved.faces[TOP])[2]).toBe(2);
  });
  it("extrudes two neighbouring faces as one region", () => {
    const { mesh } = extrudeFaces(cube(), [TOP, 1]);
    expect(mesh.faces.length).toBe(6 + 6);      // six boundary edges of the L-shaped region
    expect(manifold(mesh)).toBe(true);
  });
  it("extrudes edges into quads and vertices into edges", () => {
    const e = extrudeEdges(cube(), [[3, 7]]);
    expect(e.mesh.faces.length).toBe(7);
    expect(e.selection.items).toEqual([[8, 9]]);
    const v = extrudeVerts(cube(), [0]);
    expect(v.mesh.loose).toEqual([[0, 8]]);
  });
  it("fills a hole back, facing out", () => {
    const open = remove(cube(), { mode: "face", items: [TOP] });
    const { mesh, selection } = fill(open, [7, 3, 1, 5]);
    expect(mesh.faces.length).toBe(6);
    expect(manifold(mesh)).toBe(true);
    expect(outward(mesh)).toBe(true);
    expect(selection.items).toEqual([5]);
  });
  it("fills whatever order the vertices were picked in", () => {
    const open = remove(cube(), { mode: "face", items: [TOP] });
    expect(manifold(fill(open, [1, 7, 5, 3]).mesh)).toBe(true);
  });
  it("fills two vertices with an edge, and refuses an existing one", () => {
    expect(fill(cube(), [0, 7]).mesh.loose).toEqual([[0, 7]]);
    expect(() => fill(cube(), [0, 1])).toThrow(/already/);
  });
  it("merges an edge's two vertices at its centre", () => {
    const { mesh, selection } = mergeAtCenter(cube(), [3, 7]);
    expect(mesh.co.length / 3).toBe(7);
    expect(mesh.faces.length).toBe(6);
    expect(mesh.faces.filter((f) => f.length === 3).length).toBe(2);
    const v = selection.items[0];
    expect([mesh.co[v * 3], mesh.co[v * 3 + 1], mesh.co[v * 3 + 2]]).toEqual([0, 1, 1]);
  });
  it("merging a whole face's corners drops it", () => {
    const { mesh } = mergeAtCenter(cube(), [7, 3, 1, 5]);
    expect(mesh.faces.length).toBe(5);
    expect(mesh.faces.every((f) => f.length === 3 || f.length === 4)).toBe(true);
  });
});

describe("selection and display", () => {
  it("any mode resolves to vertices", () => {
    expect(selectedVerts(cube(), { mode: "face", items: [TOP] }).sort()).toEqual([1, 3, 5, 7]);
    expect(selectedVerts(cube(), { mode: "edge", items: [[3, 7]] })).toEqual([3, 7]);
  });
  it("speaks the engine's selection", () => {
    expect(engineSelection({ mode: "face", items: [] })).toBe("all");
    expect(engineSelection({ mode: "edge", items: [[1, 2]] })).toEqual({ edges: [[1, 2]] });
  });
  it("maps every display triangle back to its face", () => {
    const d = displayBuffers(cube());
    expect(d.index.length / 3).toBe(12);
    expect(d.triFace).toEqual([0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]);
  });
});

describe("display buffers", () => {
  it("carry each corner's UV, zeros where a face has none", () => {
    const m = cube();
    m.uv = m.faces.map((f, i) => (i === 0 ? null : f.flatMap((_, c) => [c / 4, i / 6])));
    const b = displayBuffers(m);
    expect(b.uv.length).toBe((b.positions.length / 3) * 2);
    expect([...b.uv.slice(0, 8)]).toEqual([0, 0, 0, 0, 0, 0, 0, 0]);          // face 0: none
    expect(b.uv[9]).toBeCloseTo(1 / 6);                                           // face 1, corner 0: v
    expect(displayBuffers(cube()).uv).toBe(null);
  });
});

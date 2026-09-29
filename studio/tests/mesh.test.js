import { describe, it, expect } from "vitest";
import { fromSidecar, toSidecar, sidecarId, edges, remove, extrudeFaces, extrudeEdges, extrudeVerts, fill, mergeAtCenter, moveVerts, faceNormal, centroid, displayBuffers, selectedVerts, engineSelection, assignSlot, edgeRing, loopCut, falloff, proportionalWeights, moveVertsWeighted, connectVerts, splitAlong } from "../src/mesh.js";
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

describe("material slots", () => {
  it("a face's slot survives the mesh file, and Assign sets it", () => {
    const m = assignSlot(cube(), [TOP], 2);
    expect(m.mi[TOP]).toBe(2);
    const back = fromSidecar(toSidecar(m));
    expect(back.mi).toEqual(m.mi);
    expect(toSidecar(cube()).material_index).toBeUndefined();          // all slot 0: nothing to write
  });

  it("extruded side faces take their face's slot; display triangles carry it", () => {
    const m = assignSlot(cube(), [TOP], 1);
    const r = extrudeFaces(m, [TOP]);
    expect(r.mesh.mi.slice(6)).toEqual([1, 1, 1, 1]);
    const b = displayBuffers(r.mesh);
    expect(b.triMat.length).toBe(b.index.length / 3);
    expect(b.triMat.filter((x) => x === 1).length).toBe(10);           // the top + 4 sides, 2 triangles each
  });
});

// A pentagonal prism: two n-gon caps and five side quads — rings end at the caps.
const prism = () => {
  const co = [];
  for (const z of [-1, 1]) for (let i = 0; i < 5; i++) { const a = (i / 5) * Math.PI * 2; co.push(Math.cos(a), Math.sin(a), z); }
  const faces = [[4, 3, 2, 1, 0], [5, 6, 7, 8, 9]];                        // bottom (outward −z), top (+z)
  for (let i = 0; i < 5; i++) { const j = (i + 1) % 5; faces.push([i, j, j + 5, i + 5]); }
  return { co, faces, smooth: faces.map(() => false), uv: null, mi: null, loose: [] };
};

describe("loop cut", () => {
  it("rings round a cube from a side edge and cuts it closed", () => {
    const m = cube();
    const ring = edgeRing(m, [0, 1]);                   // an x = −1 edge running along z
    expect(ring.closed).toBe(true);
    expect(ring.faces.length).toBe(4);
    const r = loopCut(m, ring, 1);
    expect(r.mesh.co.length / 3).toBe(12);
    expect(r.mesh.faces.length).toBe(10);
    expect(manifold(r.mesh)).toBe(true);
    expect(outward(r.mesh)).toBe(true);
    expect(r.selection.items.length).toBe(4);           // the new loop's four edges
  });

  it("stops at n-gons and gives them the new vertices, so the mesh stays closed", () => {
    const m = prism();
    const ring = edgeRing(m, [5, 6]);                   // a top rim edge: down one side quad
    expect(ring.closed).toBe(false);
    expect(ring.faces.length).toBe(1);
    expect(ring.ends.length).toBe(2);
    const r = loopCut(m, ring, 2);
    expect(r.mesh.faces.length).toBe(7 - 1 + 3);
    expect(r.mesh.faces.filter((f) => f.length === 7).length).toBe(2);   // each cap gained two vertices
    expect(manifold(r.mesh)).toBe(true);
    expect(outward(r.mesh)).toBe(true);
    const side = edgeRing(m, [0, 5]);                   // a side edge: round all five quads
    expect(side.closed).toBe(true);
    expect(manifold(loopCut(m, side, 3).mesh)).toBe(true);
  });

  it("slides the cut, and interpolates UVs", () => {
    const m = cube();
    m.uv = m.faces.map(() => [0, 0, 1, 0, 1, 1, 0, 1]);
    const ring = edgeRing(m, [0, 1]);
    const r = loopCut(m, ring, 1, 0.5);
    const zs = [];
    for (let v = 8; v < 12; v++) zs.push(r.mesh.co[v * 3 + 2]);
    expect(new Set(zs.map((z) => z.toFixed(3))).size).toBe(1);   // one flat loop…
    expect(Math.abs(zs[0])).toBeGreaterThan(0.4);                  // …slid off the middle
    expect(r.mesh.uv.every((u) => u && u.every((x) => x >= 0 && x <= 1))).toBe(true);
    expect(r.mesh.uv.filter((u) => u.some((x) => x > 0 && x < 1)).length).toBeGreaterThan(0);
  });
});

describe("proportional editing", () => {
  it("falls off from 1 at the selection to 0 at the radius", () => {
    for (const k of ["smooth", "sphere", "root", "sharp", "linear"]) {
      expect(falloff(k, 0, 2)).toBeCloseTo(1);
      expect(falloff(k, 2, 2)).toBe(0);
      expect(falloff(k, 1, 2)).toBeGreaterThan(0);
    }
    expect(falloff("constant", 1.9, 2)).toBe(1);
  });

  it("weighs unselected vertices by their distance to the nearest selected one", () => {
    const pos = [0, 0, 0, 1, 0, 0, 2, 0, 0, 5, 0, 0];
    const w = proportionalWeights(pos, [0], 3, "linear");
    expect(w.get(0)).toBe(1);
    expect(w.get(1)).toBeCloseTo(2 / 3);
    expect(w.get(2)).toBeCloseTo(1 / 3);
    expect(w.has(3)).toBe(false);
    const m = moveVertsWeighted({ co: pos, faces: [], smooth: [], uv: null, loose: [] }, w, (x, y, z) => [x, y, z + 3]);
    expect([m.co[2], m.co[5], m.co[8], m.co[11]]).toEqual([3, 2, 1, 0].map((z, i) => (i === 3 ? 0 : z)));
  });
});

describe("knife and connect", () => {
  it("J splits the face two vertices share", () => {
    const r = connectVerts(cube(), 7, 1);               // a diagonal of the top
    expect(r.mesh.faces.length).toBe(7);
    expect(manifold(r.mesh)).toBe(true);
    expect(() => connectVerts(cube(), 0, 7)).toThrow();   // opposite corners share no face
  });

  it("cuts across the top: two new vertices, the top split, the sides keep up", () => {
    // top is [7, 3, 1, 5]: cross edges 7–3 and 1–5 at their middles
    const r = splitAlong(cube(), [{ edge: [7, 3], t: 0.5 }, { edge: [1, 5], t: 0.5 }]);
    expect(r.mesh.co.length / 3).toBe(10);
    expect(r.mesh.faces.length).toBe(7);
    expect(r.mesh.faces.filter((f) => f.length === 5).length).toBe(2);   // the two sides that share those edges
    expect(manifold(r.mesh)).toBe(true);
    expect(outward(r.mesh)).toBe(true);
    expect(r.selection.items.length).toBe(1);
  });
});

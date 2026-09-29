// Edit mode's mesh: an explicit mesh as plain arrays, the cycls.mesh sidecar codec
// (the engine's write_sidecar/read_sidecar, in JS), and the edits that are simple
// enough to do here — move, delete, extrude, fill, merge. Bevel, inset, subdivide
// and the rest go to Blender (engine `apply`). Every edit returns a new mesh.
//
//   { co: number[] (x,y,z per vertex), faces: number[][] (vertex indices, CCW),
//     smooth: boolean[] (per face), uv: (number[] | null)[] | null (per face, u,v per
//     corner), loose: [a, b][] (edges no face uses) }

// ─── codec ───────────────────────────────────────────────────────────────────

function unb64(s, Kind) {
  if (!s) return new Kind(0);
  const bin = atob(s);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Kind(u8.buffer);
}

function b64(typed) {
  const u8 = new Uint8Array(typed.buffer, typed.byteOffset, typed.byteLength);
  let bin = "";
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(bin);
}

export function fromSidecar(side) {
  if (side?.format !== "cycls.mesh" || side.version !== 1) throw new Error("not a cycls.mesh v1 sidecar");
  const co = Array.from(unb64(side.co, Float32Array));
  const ls = unb64(side.loop_start, Uint32Array), lp = unb64(side.loops, Uint32Array);
  const sm = side.smooth ? unb64(side.smooth, Uint8Array) : null;
  const uv = side.uv ? unb64(side.uv, Float32Array) : null;
  const faces = [], smooth = [], fuv = uv ? [] : null;
  for (let f = 0; f < ls.length; f++) {
    const s = ls[f], e = f + 1 < ls.length ? ls[f + 1] : lp.length;
    faces.push(Array.from(lp.subarray(s, e)));
    smooth.push(!!(sm && sm[f]));
    if (fuv) fuv.push(Array.from(uv.subarray(s * 2, e * 2)));
  }
  const le = side.loose_edges ? Array.from(unb64(side.loose_edges, Uint32Array)) : [];
  const loose = [];
  for (let i = 0; i + 1 < le.length; i += 2) loose.push([le[i], le[i + 1]]);
  const mi = side.material_index ? Array.from(unb64(side.material_index, Uint16Array)) : null;
  return { co, faces, smooth, uv: fuv, mi, loose };
}

const r6 = (v) => Math.round(v * 1e6) / 1e6;

export function toSidecar(m) {
  const nv = m.co.length / 3;
  const loopStart = new Uint32Array(m.faces.length), loops = [];
  m.faces.forEach((f, i) => { loopStart[i] = loops.length; loops.push(...f); });
  const out = { format: "cycls.mesh", version: 1, counts: { verts: nv, faces: m.faces.length, loops: loops.length },
                co: b64(new Float32Array(m.co)), loop_start: b64(loopStart), loops: b64(new Uint32Array(loops)),
                smooth: b64(Uint8Array.from(m.smooth, (s) => (s ? 1 : 0))) };
  if (m.loose.length) out.loose_edges = b64(new Uint32Array(m.loose.flat()));
  if (m.uv && m.faces.length) {
    const uv = new Float32Array(loops.length * 2);
    m.faces.forEach((f, i) => { const u = m.uv[i]; if (u && u.length === f.length * 2) uv.set(u, loopStart[i] * 2); });
    out.uv = b64(uv);
  }
  if (m.mi && m.mi.some((x) => x)) out.material_index = b64(Uint16Array.from(m.mi));
  out.bbox = bbox(m).map((p) => p.map(r6));
  return out;
}

export function bbox(m) {
  if (!m.co.length) return [[0, 0, 0], [0, 0, 0]];
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < m.co.length; i += 3) {
    for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], m.co[i + k]); hi[k] = Math.max(hi[k], m.co[i + k]); }
  }
  return [lo, hi];
}

// A sidecar's id: 12 hex of its content, like the engine's (a different hash, but
// the same promise — the same geometry keeps its id, a change makes a new file).
export function sidecarId(text) {
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 2654435761);
    h2 = Math.imul(h2 ^ c, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return "m-" + ((h2 >>> 0).toString(16).padStart(8, "0") + (h1 >>> 0).toString(16).padStart(8, "0")).slice(0, 12);
}

// Display: per-face-corner positions and flat/smooth normals, fan-triangulated;
// `triFace[t]` is the face a triangle came from (face picking). `shading` is the
// object's: "flat"/"smooth" override the faces' own flags, as the engine does.
export function displayBuffers(m, shading = "auto") {
  const vn = smoothNormals(m);
  const pos = [], nor = [], uv = m.uv ? [] : null, index = [], triFace = [], triMat = m.mi ? [] : null;
  m.faces.forEach((f, fi) => {
    const fnorm = faceNormal(m, f);
    const base = pos.length / 3;
    const smooth = shading === "smooth" || (shading !== "flat" && m.smooth[fi]);
    const fuv = m.uv?.[fi];
    f.forEach((v, c) => {
      pos.push(m.co[v * 3], m.co[v * 3 + 1], m.co[v * 3 + 2]);
      const n = smooth ? vn.slice(v * 3, v * 3 + 3) : fnorm;
      nor.push(n[0], n[1], n[2]);
      if (uv) uv.push(fuv ? fuv[c * 2] : 0, fuv ? fuv[c * 2 + 1] : 0);
    });
    for (let i = 1; i + 1 < f.length; i++) {
      index.push(base, base + i, base + i + 1); triFace.push(fi);
      if (triMat) triMat.push(m.mi[fi] || 0);
    }
  });
  return { positions: new Float32Array(pos), normals: new Float32Array(nor), uv: uv && new Float32Array(uv),
           index: new Uint32Array(index), triFace, triMat };
}

// ─── geometry helpers ────────────────────────────────────────────────────────

export const vert = (m, i) => [m.co[i * 3], m.co[i * 3 + 1], m.co[i * 3 + 2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

// Newell's method: right for any planar-ish n-gon.
export function faceNormal(m, f) {
  const n = [0, 0, 0];
  for (let i = 0; i < f.length; i++) {
    const a = vert(m, f[i]), b = vert(m, f[(i + 1) % f.length]);
    n[0] += (a[1] - b[1]) * (a[2] + b[2]);
    n[1] += (a[2] - b[2]) * (a[0] + b[0]);
    n[2] += (a[0] - b[0]) * (a[1] + b[1]);
  }
  return norm(n);
}

function smoothNormals(m) {
  const out = new Float32Array(m.co.length);
  m.faces.forEach((f) => {
    const n = faceNormal(m, f);
    for (const v of f) { out[v * 3] += n[0]; out[v * 3 + 1] += n[1]; out[v * 3 + 2] += n[2]; }
  });
  for (let i = 0; i < out.length; i += 3) { const n = norm([out[i], out[i + 1], out[i + 2]]); out.set(n, i); }
  return out;
}

export function centroid(m, verts) {
  const c = [0, 0, 0];
  for (const v of verts) { c[0] += m.co[v * 3]; c[1] += m.co[v * 3 + 1]; c[2] += m.co[v * 3 + 2]; }
  const n = Math.max(1, verts.length);
  return [c[0] / n, c[1] / n, c[2] / n];
}

const ekey = (a, b) => (a < b ? `${a},${b}` : `${b},${a}`);

// Every edge once: [a, b] with a < b, face edges then loose ones.
export function edges(m) {
  const seen = new Map();
  for (const f of m.faces) {
    for (let i = 0; i < f.length; i++) {
      const a = f[i], b = f[(i + 1) % f.length], k = ekey(a, b);
      if (!seen.has(k)) seen.set(k, a < b ? [a, b] : [b, a]);
    }
  }
  for (const [a, b] of m.loose) { const k = ekey(a, b); if (!seen.has(k)) seen.set(k, a < b ? [a, b] : [b, a]); }
  return [...seen.values()];
}

// ─── selection, in any of the three element modes ────────────────────────────

// { mode: "vert" | "edge" | "face", items: number[] | [a,b][] } → the vertices it covers.
export function selectedVerts(m, sel) {
  if (!sel || !sel.items.length) return [];
  if (sel.mode === "vert") return [...new Set(sel.items)];
  if (sel.mode === "edge") return [...new Set(sel.items.flat())];
  return [...new Set(sel.items.flatMap((f) => m.faces[f] || []))];
}

// Switching vertex/edge/face mode keeps what was selected, as Blender does: going
// "up" keeps only elements whose every vertex was selected.
export function convertSelection(m, sel, mode) {
  if (sel.mode === mode) return sel;
  const vs = new Set(selectedVerts(m, sel));
  if (mode === "vert") return { mode, items: [...vs].sort((a, b) => a - b) };
  if (mode === "edge") {
    const items = sel.mode === "face"
      ? [...new Map(sel.items.flatMap((f) => (m.faces[f] || []).map((v, i, fv) => {
          const a = Math.min(v, fv[(i + 1) % fv.length]), b = Math.max(v, fv[(i + 1) % fv.length]);
          return [`${a},${b}`, [a, b]];
        }))).values()]
      : edges(m).filter(([a, b]) => vs.has(a) && vs.has(b));
    return { mode, items };
  }
  return { mode, items: m.faces.map((f, i) => (f.every((v) => vs.has(v)) ? i : -1)).filter((i) => i >= 0) };
}

export function allElements(m, mode) {
  if (mode === "vert") return { mode, items: Array.from({ length: m.co.length / 3 }, (_, i) => i) };
  if (mode === "edge") return { mode, items: edges(m) };
  return { mode, items: m.faces.map((_, i) => i) };
}

// What the engine's `_bm_selection` takes.
export function engineSelection(sel) {
  if (!sel || !sel.items.length) return "all";
  if (sel.mode === "vert") return { verts: sel.items };
  if (sel.mode === "edge") return { edges: sel.items };
  return { faces: sel.items };
}

// ─── edits ───────────────────────────────────────────────────────────────────

const copy = (m) => ({ co: [...m.co], faces: m.faces.map((f) => [...f]), smooth: [...m.smooth],
                       uv: m.uv ? m.uv.map((u) => (u ? [...u] : null)) : null, mi: m.mi ? [...m.mi] : null,
                       loose: m.loose.map((e) => [...e]) });

// A new face's material slot: that of the face it grew from (0 when there's none).
const slotOf = (m, fi) => (m.mi && fi != null ? m.mi[fi] || 0 : 0);
function faceWithEdge(m, a, b) {
  const i = m.faces.findIndex((f) => f.some((v, k) => { const w = f[(k + 1) % f.length]; return (v === a && w === b) || (v === b && w === a); }));
  return i < 0 ? null : i;
}

// Put the given faces in material slot `slot` (Blender's "Assign").
export function assignSlot(m, faceIds, slot) {
  const out = copy(m);
  out.mi = out.mi || new Array(m.faces.length).fill(0);
  for (const f of faceIds) out.mi[f] = slot;
  return out;
}

// Move vertices: fn(x, y, z) → [x, y, z], in the mesh's own space.
export function moveVerts(m, verts, fn) {
  const out = { ...m, co: [...m.co] };
  for (const v of verts) {
    const p = fn(m.co[v * 3], m.co[v * 3 + 1], m.co[v * 3 + 2]);
    out.co[v * 3] = p[0]; out.co[v * 3 + 1] = p[1]; out.co[v * 3 + 2] = p[2];
  }
  return out;
}

// Drop vertices nothing uses; renumber. Returns { mesh, map } (old index → new, or -1).
export function compact(m) {
  const used = new Uint8Array(m.co.length / 3);
  for (const f of m.faces) for (const v of f) used[v] = 1;
  for (const [a, b] of m.loose) { used[a] = 1; used[b] = 1; }
  const map = new Int32Array(used.length).fill(-1);
  const co = [];
  for (let i = 0; i < used.length; i++) if (used[i]) { map[i] = co.length / 3; co.push(m.co[i * 3], m.co[i * 3 + 1], m.co[i * 3 + 2]); }
  return { mesh: { co, faces: m.faces.map((f) => f.map((v) => map[v])), smooth: [...m.smooth],
                   uv: m.uv ? m.uv.map((u) => (u ? [...u] : null)) : null, mi: m.mi ? [...m.mi] : null,
                   loose: m.loose.map(([a, b]) => [map[a], map[b]]) },
           map };
}

function keepFaces(m, keep) {
  return { ...m, faces: m.faces.filter((_, i) => keep(i)), smooth: m.smooth.filter((_, i) => keep(i)),
           uv: m.uv ? m.uv.filter((_, i) => keep(i)) : null, mi: m.mi ? m.mi.filter((_, i) => keep(i)) : null };
}

// X: vertices take their faces and edges with them; edges their faces; faces only
// themselves (then any vertex left unused goes too, as Blender's "Delete Faces").
export function remove(m, sel) {
  if (!sel.items.length) return m;
  let out;
  if (sel.mode === "vert") {
    const gone = new Set(sel.items);
    out = keepFaces(m, (i) => !m.faces[i].some((v) => gone.has(v)));
    out.loose = m.loose.filter(([a, b]) => !gone.has(a) && !gone.has(b));
  } else if (sel.mode === "edge") {
    const gone = new Set(sel.items.map(([a, b]) => ekey(a, b)));
    out = keepFaces(m, (i) => !m.faces[i].some((v, k, f) => gone.has(ekey(v, f[(k + 1) % f.length]))));
    out.loose = m.loose.filter(([a, b]) => !gone.has(ekey(a, b)));
  } else {
    const gone = new Set(sel.items);
    out = keepFaces(m, (i) => !gone.has(i));
    out.loose = [...m.loose];
  }
  return compact(out).mesh;
}

// E on faces: extrude the region. The selected faces move to new vertices (still
// in place — the move comes next), boundary edges get side quads. Returns the mesh
// and the new selection (the moved faces).
export function extrudeFaces(m, faceIds) {
  const out = copy(m);
  const region = new Set(faceIds);
  const count = new Map();                          // edge → how many region faces use it, and its direction
  for (const fi of region) {
    const f = m.faces[fi];
    for (let i = 0; i < f.length; i++) {
      const a = f[i], b = f[(i + 1) % f.length], k = ekey(a, b);
      const e = count.get(k) || { n: 0, a, b, fi };
      e.n++;
      count.set(k, e);
    }
  }
  const dup = new Map();
  const twin = (v) => {
    if (!dup.has(v)) { dup.set(v, out.co.length / 3); out.co.push(m.co[v * 3], m.co[v * 3 + 1], m.co[v * 3 + 2]); }
    return dup.get(v);
  };
  for (const fi of region) out.faces[fi] = m.faces[fi].map(twin);
  for (const { n, a, b, fi } of count.values()) {
    if (n !== 1) continue;                         // interior edge of the region
    out.faces.push([a, b, twin(b), twin(a)]);      // follows the region face's winding: outward
    out.smooth.push(false);
    if (out.uv) out.uv.push(null);
    if (out.mi) out.mi.push(slotOf(m, fi));
  }
  return { mesh: out, selection: { mode: "face", items: [...region] } };
}

// E on edges: each edge grows a quad; E on vertices: each grows an edge.
export function extrudeEdges(m, edgeList) {
  const out = copy(m);
  const dup = new Map();
  const twin = (v) => {
    if (!dup.has(v)) { dup.set(v, out.co.length / 3); out.co.push(m.co[v * 3], m.co[v * 3 + 1], m.co[v * 3 + 2]); }
    return dup.get(v);
  };
  const made = [];
  for (const [a, b] of edgeList) {
    out.faces.push([a, b, twin(b), twin(a)]);
    out.smooth.push(false);
    if (out.uv) out.uv.push(null);
    if (out.mi) out.mi.push(slotOf(m, faceWithEdge(m, a, b)));
    made.push([twin(a), twin(b)].sort((x, y) => x - y));
  }
  return { mesh: out, selection: { mode: "edge", items: made } };
}

export function extrudeVerts(m, verts) {
  const out = copy(m);
  const made = [];
  for (const v of verts) {
    const n = out.co.length / 3;
    out.co.push(m.co[v * 3], m.co[v * 3 + 1], m.co[v * 3 + 2]);
    out.loose.push([v, n]);
    made.push(n);
  }
  return { mesh: out, selection: { mode: "vert", items: made } };
}

// F: two vertices make an edge; more make a face — in the order of the open
// boundary they sit on when they form one, else around their centre.
export function fill(m, verts) {
  const vs = [...new Set(verts)];
  if (vs.length < 2) throw new Error("Select at least 2 vertices to fill");
  const out = copy(m);
  if (vs.length === 2) {
    const k = ekey(vs[0], vs[1]);
    if (edges(m).some(([a, b]) => ekey(a, b) === k)) throw new Error("Those vertices already share an edge");
    out.loose.push(vs[0] < vs[1] ? [vs[0], vs[1]] : [vs[1], vs[0]]);
    return { mesh: out, selection: { mode: "edge", items: [[Math.min(...vs), Math.max(...vs)]] } };
  }
  let ring = boundaryRing(m, vs);
  if (!ring) {
    const c = centroid(m, vs);
    const n = bestNormal(m, vs, c);
    const u = norm(sub(vert(m, vs[0]), c)), w = cross(n, u);
    ring = [...vs].sort((a, b) => angle(m, a, c, u, w) - angle(m, b, c, u, w));
  }
  // Wind it the way its neighbours say: a shared edge runs the other way in each of
  // two consistent faces. With no shared edge, face the way the nearby faces do.
  const around = m.faces.filter((f) => f.some((v) => vs.includes(v)));
  const directed = new Set();
  for (const f of around) for (let i = 0; i < f.length; i++) directed.add(`${f[i]}>${f[(i + 1) % f.length]}`);
  let agree = 0, clash = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i], b = ring[(i + 1) % ring.length];
    if (directed.has(`${a}>${b}`)) clash++;
    if (directed.has(`${b}>${a}`)) agree++;
  }
  if (clash !== agree) {
    if (clash > agree) ring.reverse();
  } else if (around.length) {
    const want = around.map((f) => faceNormal(m, f)).reduce((a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]);
    const got = faceNormal(m, ring);
    if (got[0] * want[0] + got[1] * want[1] + got[2] * want[2] < 0) ring.reverse();
  }
  out.faces.push(ring);
  out.smooth.push(false);
  if (out.uv) out.uv.push(null);
  if (out.mi) out.mi.push(slotOf(m, faceWithEdge(m, ring[0], ring[1])));
  // Loose edges the new face now covers are its edges, not loose ones.
  const fe = new Set(ring.map((v, i) => ekey(v, ring[(i + 1) % ring.length])));
  out.loose = out.loose.filter(([a, b]) => !fe.has(ekey(a, b)));
  return { mesh: out, selection: { mode: "face", items: [out.faces.length - 1] } };
}

function angle(m, v, c, u, w) {
  const d = sub(vert(m, v), c);
  return Math.atan2(d[0] * w[0] + d[1] * w[1] + d[2] * w[2], d[0] * u[0] + d[1] * u[1] + d[2] * u[2]);
}

function bestNormal(m, vs, c) {
  const n = [0, 0, 0];
  for (let i = 0; i < vs.length; i++) {
    const a = sub(vert(m, vs[i]), c), b = sub(vert(m, vs[(i + 1) % vs.length]), c);
    const x = cross(a, b);
    // Keep a consistent hemisphere so opposite pairs don't cancel.
    const s = x[0] * n[0] + x[1] * n[1] + x[2] * n[2] < 0 ? -1 : 1;
    n[0] += s * x[0]; n[1] += s * x[1]; n[2] += s * x[2];
  }
  return Math.hypot(...n) < 1e-12 ? [0, 0, 1] : norm(n);
}

// The selected vertices in walking order, if they are exactly one closed chain of
// boundary edges (edges with one face) or loose edges.
function boundaryRing(m, vs) {
  const want = new Set(vs);
  const uses = new Map();
  for (const f of m.faces) for (let i = 0; i < f.length; i++) {
    const k = ekey(f[i], f[(i + 1) % f.length]);
    uses.set(k, (uses.get(k) || 0) + 1);
  }
  const adj = new Map();
  const link = (a, b) => { (adj.get(a) || adj.set(a, []).get(a)).push(b); };
  for (const [k, n] of uses) {
    const [a, b] = k.split(",").map(Number);
    if (n === 1 && want.has(a) && want.has(b)) { link(a, b); link(b, a); }
  }
  for (const [a, b] of m.loose) if (want.has(a) && want.has(b)) { link(a, b); link(b, a); }
  if (vs.some((v) => (adj.get(v) || []).length !== 2)) return null;
  const ring = [vs[0]];
  let prev = -1, cur = vs[0];
  for (;;) {
    const next = adj.get(cur).find((x) => x !== prev);
    if (next === vs[0]) break;
    if (ring.includes(next)) return null;
    ring.push(next);
    prev = cur; cur = next;
    if (ring.length > vs.length) return null;
  }
  return ring.length === vs.length ? ring : null;
}

// M → At Center: the selected vertices become one. Faces that shrink below three
// corners go; loose edges that shrink to a point go.
export function mergeAtCenter(m, verts) {
  const vs = [...new Set(verts)];
  if (vs.length < 2) throw new Error("Select at least 2 vertices to merge");
  const c = centroid(m, vs);
  const keep = vs[0];
  const gone = new Set(vs.slice(1));
  const out = copy(m);
  out.co[keep * 3] = c[0]; out.co[keep * 3 + 1] = c[1]; out.co[keep * 3 + 2] = c[2];
  const to = (v) => (gone.has(v) ? keep : v);
  const faces = [], smooth = [], uv = out.uv ? [] : null, mi = out.mi ? [] : null;
  m.faces.forEach((f, i) => {
    const g = [], gu = [];
    f.forEach((v, k) => {
      const w = to(v);
      if (g[g.length - 1] !== w) { g.push(w); if (m.uv?.[i]) gu.push(m.uv[i][k * 2], m.uv[i][k * 2 + 1]); }
    });
    while (g.length > 1 && g[0] === g[g.length - 1]) { g.pop(); gu.splice(-2); }
    if (new Set(g).size >= 3 && new Set(g).size === g.length) {
      faces.push(g); smooth.push(m.smooth[i]);
      if (uv) uv.push(m.uv[i] ? gu : null);
      if (mi) mi.push(m.mi[i]);
    }
  });
  out.faces = faces; out.smooth = smooth; out.uv = uv; out.mi = mi;
  const le = new Set();
  out.loose = m.loose.map(([a, b]) => [to(a), to(b)]).filter(([a, b]) => {
    const k = ekey(a, b);
    if (a === b || le.has(k)) return false;
    le.add(k);
    return true;
  });
  const { mesh, map } = compact(out);
  return { mesh, selection: { mode: "vert", items: map[keep] >= 0 ? [map[keep]] : [] } };
}

// ─── rings and loop cuts ─────────────────────────────────────────────────────

// Which faces use each edge: ekey → [face index, …].
export function edgeFaces(m) {
  const out = new Map();
  m.faces.forEach((f, fi) => f.forEach((v, i) => {
    const k = ekey(v, f[(i + 1) % f.length]);
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(fi);
  }));
  return out;
}

// The ring an edge starts (Blender's loop cut): across each quad to its opposite edge,
// both ways, until a face that isn't a quad, a border, or back to the start. Edges come
// oriented so each one's first vertex is on the same side; `ends` are the n-gons the ring
// runs into (they get the new vertices too, so the mesh stays closed).
export function edgeRing(m, [a0, b0]) {
  const ef = edgeFaces(m);
  const walk = (a, b, from) => {
    const edges = [], faces = [];
    let cur = [a, b], prev = from, end = null, closed = false;
    for (let guard = 0; guard <= m.faces.length; guard++) {
      const next = (ef.get(ekey(cur[0], cur[1])) || []).filter((fi) => fi !== prev);
      if (next.length !== 1) break;                      // a border, or more than two faces
      const fi = next[0], f = m.faces[fi];
      if (f.length !== 4) { end = fi; break; }
      const other = (v, not) => { const i = f.indexOf(v); const n = f[(i + 1) % 4]; return n === not ? f[(i + 3) % 4] : n; };
      const nxt = [other(cur[0], cur[1]), other(cur[1], cur[0])];
      faces.push(fi);
      if (ekey(nxt[0], nxt[1]) === ekey(a0, b0)) { closed = true; break; }
      edges.push(nxt);
      prev = fi;
      cur = nxt;
    }
    return { edges, faces, end, closed };
  };
  const around = ef.get(ekey(a0, b0)) || [];
  const fwd = walk(a0, b0, around[1] ?? -1);
  if (fwd.closed) return { edges: [[a0, b0], ...fwd.edges], faces: fwd.faces, closed: true, ends: [] };
  const back = walk(a0, b0, fwd.faces[0] ?? around[0] ?? -1);
  return { edges: [...[...back.edges].reverse(), [a0, b0], ...fwd.edges],
           faces: [...[...back.faces].reverse(), ...fwd.faces], closed: false,
           ends: [back.end, fwd.end].filter((x) => x != null) };
}

// Loop cut: `cuts` new edge loops across the ring's quads, evenly spaced, all slid toward
// one side by `slide` (−1…1). UVs follow; each new face keeps its slot. Selects the new loops.
export function loopCut(m, ring, cuts = 1, slide = 0) {
  if (!ring.faces.length) throw new Error("Loop cut needs quads on at least one side of the edge");
  const out = copy(m);
  const base = Array.from({ length: cuts }, (_, i) => (i + 1) / (cuts + 1));
  const shift = Math.max(-1, Math.min(1, slide)) * Math.min(base[0], 1 - base[cuts - 1]) * 0.98;
  const ts = base.map((t) => t + shift);
  const made = new Map();                                // ekey → {a, b, verts, ts}
  for (const [a, b] of ring.edges) {
    const verts = ts.map((t) => {
      out.co.push(...[0, 1, 2].map((k) => m.co[a * 3 + k] + (m.co[b * 3 + k] - m.co[a * 3 + k]) * t));
      return out.co.length / 3 - 1;
    });
    made.set(ekey(a, b), { a, b, verts, ts });
  }
  // The new vertices along u→w, with their distance along it (0…1).
  const along = (u, w) => {
    const e = made.get(ekey(u, w));
    if (!e) return [];
    return e.a === u ? e.verts.map((v, i) => [v, e.ts[i]]) : e.verts.map((v, i) => [v, 1 - e.ts[i]]).reverse();
  };
  const uvAt = (fi, v) => { const f = m.faces[fi], u = m.uv?.[fi], c = f.indexOf(v); return u ? [u[c * 2], u[c * 2 + 1]] : null; };
  const lerp2 = (p, q, t) => (p && q ? [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t] : null);
  const replaced = new Set(ring.faces);
  const added = [], loops = [];
  ring.faces.forEach((fi, k) => {
    const [p0, p1] = ring.edges[k], [q0, q1] = ring.edges[(k + 1) % ring.edges.length];
    const f = m.faces[fi];
    // winding: does the face run p0 → p1 (then q1, q0)?
    const fwd = f[(f.indexOf(p0) + 1) % 4] === p1;
    const L = [[p0, 0], ...along(p0, p1), [p1, 1]], R = [[q0, 0], ...along(q0, q1), [q1, 1]];
    for (let j = 0; j + 1 < L.length; j++) {
      const quad = [L[j][0], L[j + 1][0], R[j + 1][0], R[j][0]];
      const uvp0 = uvAt(fi, p0), uvp1 = uvAt(fi, p1), uvq0 = uvAt(fi, q0), uvq1 = uvAt(fi, q1);
      const uv = uvp0 && [lerp2(uvp0, uvp1, L[j][1]), lerp2(uvp0, uvp1, L[j + 1][1]),
                          lerp2(uvq0, uvq1, R[j + 1][1]), lerp2(uvq0, uvq1, R[j][1])];
      added.push({ face: fwd ? quad : [...quad].reverse(), uv: uv && (fwd ? uv : [...uv].reverse()).flat(),
                   smooth: m.smooth[fi], mi: m.mi ? m.mi[fi] : 0 });
      if (j + 1 < L.length - 1) loops.push([L[j + 1][0], R[j + 1][0]].sort((x, y) => x - y));
    }
  });
  // The n-gons the ring ran into take the new vertices on the edge they share with it.
  for (const gi of ring.ends || []) {
    const g = m.faces[gi], guv = m.uv?.[gi];
    const face = [], uv = guv ? [] : null;
    g.forEach((v, c) => {
      face.push(v);
      if (uv) uv.push(guv[c * 2], guv[c * 2 + 1]);
      const w = g[(c + 1) % g.length];
      for (const [nv, t] of along(v, w)) {
        face.push(nv);
        if (uv) uv.push(...lerp2([guv[c * 2], guv[c * 2 + 1]], [guv[((c + 1) % g.length) * 2], guv[((c + 1) % g.length) * 2 + 1]], t));
      }
    });
    out.faces[gi] = face;
    if (out.uv) out.uv[gi] = uv;
  }
  const keep = m.faces.map((_, i) => !replaced.has(i));
  const result = {
    co: out.co, loose: out.loose,
    faces: [...out.faces.filter((_, i) => keep[i]), ...added.map((a) => a.face)],
    smooth: [...out.smooth.filter((_, i) => keep[i]), ...added.map((a) => a.smooth)],
    uv: out.uv ? [...out.uv.filter((_, i) => keep[i]), ...added.map((a) => a.uv)] : null,
    mi: out.mi ? [...out.mi.filter((_, i) => keep[i]), ...added.map((a) => a.mi)] : null,
  };
  return { mesh: result, selection: { mode: "edge", items: loops } };
}

// ─── proportional editing ────────────────────────────────────────────────────

// Blender's falloffs: weight at distance d of radius r, 1 at the selection, 0 at r.
export const FALLOFFS = ["smooth", "sphere", "root", "sharp", "linear", "constant"];
export function falloff(kind, d, r) {
  if (d >= r) return 0;
  const f = 1 - d / r;
  switch (kind) {
    case "sphere": return Math.sqrt(2 * f - f * f);
    case "root": return Math.sqrt(f);
    case "sharp": return f * f;
    case "linear": return f;
    case "constant": return 1;
    default: return 3 * f * f - 2 * f * f * f;          // smooth
  }
}

// How much each vertex follows a transform of `selected`: 1 for them, the falloff of the
// distance to the nearest one for the rest within `radius`. `pos` is flat xyz — in the
// space the radius is measured in (world, so an object's scale doesn't change it).
export function proportionalWeights(pos, selected, radius, kind = "smooth") {
  const w = new Map(selected.map((v) => [v, 1]));
  if (!(radius > 0)) return w;
  const sel = [...new Set(selected)];
  const n = pos.length / 3;
  for (let v = 0; v < n; v++) {
    if (w.has(v)) continue;
    let best = Infinity;
    for (const s of sel) {
      const dx = pos[v * 3] - pos[s * 3], dy = pos[v * 3 + 1] - pos[s * 3 + 1], dz = pos[v * 3 + 2] - pos[s * 3 + 2];
      const d = dx * dx + dy * dy + dz * dz;
      if (d < best) best = d;
    }
    const k = falloff(kind, Math.sqrt(best), radius);
    if (k > 0) w.set(v, k);
  }
  return w;
}

// Move each vertex part of the way: fn gives where it would go at full weight.
export function moveVertsWeighted(m, weights, fn) {
  const out = { ...m, co: [...m.co] };
  for (const [v, k] of weights) {
    const x = m.co[v * 3], y = m.co[v * 3 + 1], z = m.co[v * 3 + 2];
    const p = fn(x, y, z);
    out.co[v * 3] = x + (p[0] - x) * k; out.co[v * 3 + 1] = y + (p[1] - y) * k; out.co[v * 3 + 2] = z + (p[2] - z) * k;
  }
  return out;
}

// ─── knife and connect ───────────────────────────────────────────────────────

// Split face `fi` of `out` between two of its corners (vertex ids), in place. Returns
// the two faces' indices, or null when they're neighbours (nothing to cut).
function splitFace(out, fi, a, b) {
  const f = out.faces[fi], i = f.indexOf(a), j = f.indexOf(b);
  if (i < 0 || j < 0 || i === j || (i + 1) % f.length === j || (j + 1) % f.length === i) return null;
  const run = (from, to) => { const r = []; for (let k = from; ; k = (k + 1) % f.length) { r.push(k); if (k === to) break; } return r; };
  const A = run(i, j), B = run(j, i);
  const u = out.uv?.[fi];
  const pick = (idx) => (u ? idx.flatMap((k) => [u[k * 2], u[k * 2 + 1]]) : null);
  out.faces[fi] = A.map((k) => f[k]);
  if (out.uv) out.uv[fi] = pick(A);
  out.faces.push(B.map((k) => f[k]));
  out.smooth.push(out.smooth[fi]);
  if (out.uv) out.uv.push(pick(B));
  if (out.mi) out.mi.push(out.mi[fi]);
  return [fi, out.faces.length - 1];
}

// J: connect two vertices with an edge across the face they share. Throws when none does
// (the engine's connect handles that case).
export function connectVerts(m, a, b) {
  const out = copy(m);
  const fi = m.faces.findIndex((f) => f.includes(a) && f.includes(b));
  if (fi < 0 || !splitFace(out, fi, a, b)) throw new Error("Those two vertices don't share a face — or they're already joined");
  return { mesh: out, selection: { mode: "edge", items: [[Math.min(a, b), Math.max(a, b)]] } };
}

// Knife: `points` are where a cut crosses edges, in order along it — {edge: [a, b], t}
// (t along a→b). Each becomes a vertex (every face using that edge gets it, so the mesh
// stays closed) and each face two consecutive points share is split between them.
export function splitAlong(m, points) {
  const out = copy(m);
  const made = new Map();                                   // "a,b|t" → vertex
  const ids = points.map(({ edge: [a, b], t }) => {
    if (t <= 1e-6) return a;
    if (t >= 1 - 1e-6) return b;
    const key = `${ekey(a, b)}|${(a < b ? t : 1 - t).toFixed(6)}`;
    if (!made.has(key)) {
      out.co.push(...[0, 1, 2].map((k) => m.co[a * 3 + k] + (m.co[b * 3 + k] - m.co[a * 3 + k]) * t));
      made.set(key, { v: out.co.length / 3 - 1, a, b, t });
    }
    return made.get(key).v;
  });
  // Insert the new vertices into every face using their edge, in order along it.
  const onEdge = new Map();                                 // ekey → [{v, t from the lower id}]
  for (const { v, a, b, t } of made.values()) {
    const k = ekey(a, b);
    if (!onEdge.has(k)) onEdge.set(k, []);
    onEdge.get(k).push({ v, t: a < b ? t : 1 - t });
  }
  out.faces = out.faces.map((f, fi) => {
    const u = out.uv?.[fi], face = [], uv = u ? [] : null;
    f.forEach((v, c) => {
      face.push(v);
      if (uv) uv.push(u[c * 2], u[c * 2 + 1]);
      const w = f[(c + 1) % f.length], list = onEdge.get(ekey(v, w));
      if (!list) return;
      const seq = [...list].sort((p, q) => p.t - q.t).map((x) => ({ v: x.v, t: v < w ? x.t : 1 - x.t }));
      if (v > w) seq.reverse();
      for (const x of seq) {
        face.push(x.v);
        if (uv) { const n = (c + 1) % f.length; uv.push(u[c * 2] + (u[n * 2] - u[c * 2]) * x.t, u[c * 2 + 1] + (u[n * 2 + 1] - u[c * 2 + 1]) * x.t); }
      }
    });
    if (out.uv) out.uv[fi] = uv;
    return face;
  });
  const cut = [];
  for (let i = 0; i + 1 < ids.length; i++) {
    const a = ids[i], b = ids[i + 1];
    const fi = out.faces.findIndex((f) => f.includes(a) && f.includes(b));
    if (fi >= 0 && splitFace(out, fi, a, b)) cut.push([Math.min(a, b), Math.max(a, b)]);
  }
  return { mesh: out, selection: { mode: "edge", items: cut } };
}

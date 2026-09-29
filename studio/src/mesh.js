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
  return { co, faces, smooth, uv: fuv, loose };
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
  const pos = [], nor = [], uv = m.uv ? [] : null, index = [], triFace = [];
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
    for (let i = 1; i + 1 < f.length; i++) { index.push(base, base + i, base + i + 1); triFace.push(fi); }
  });
  return { positions: new Float32Array(pos), normals: new Float32Array(nor), uv: uv && new Float32Array(uv),
           index: new Uint32Array(index), triFace };
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
                       uv: m.uv ? m.uv.map((u) => (u ? [...u] : null)) : null, loose: m.loose.map((e) => [...e]) });

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
                   uv: m.uv ? m.uv.map((u) => (u ? [...u] : null)) : null, loose: m.loose.map(([a, b]) => [map[a], map[b]]) },
           map };
}

function keepFaces(m, keep) {
  return { ...m, faces: m.faces.filter((_, i) => keep(i)), smooth: m.smooth.filter((_, i) => keep(i)),
           uv: m.uv ? m.uv.filter((_, i) => keep(i)) : null };
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
      const e = count.get(k) || { n: 0, a, b };
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
  for (const { n, a, b } of count.values()) {
    if (n !== 1) continue;                         // interior edge of the region
    out.faces.push([a, b, twin(b), twin(a)]);      // follows the region face's winding: outward
    out.smooth.push(false);
    if (out.uv) out.uv.push(null);
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
  const faces = [], smooth = [], uv = out.uv ? [] : null;
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
    }
  });
  out.faces = faces; out.smooth = smooth; out.uv = uv;
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

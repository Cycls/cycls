// The scene document, app side. Mirrors cycls/_agent/studio/scene.py: every entry
// this file makes is already in normalized form (same keys, same defaults from
// schema.json, generated from scene.py), so a save never reads as a change.
import schema from "./schema.json";

export const SCHEMA = schema;
export const clone = (x) => JSON.parse(JSON.stringify(x));

export function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null || typeof a !== "object") {
    return typeof a === "number" && typeof b === "number" ? Math.abs(a - b) < 1e-9 : false;
  }
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) return a.length === b.length && a.every((v, i) => deepEqual(v, b[i]));
  const ka = Object.keys(a), kb = Object.keys(b);
  return ka.length === kb.length && ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && deepEqual(a[k], b[k]));
}

export function defaultsOf(spec) {
  const out = {};
  for (const [k, p] of Object.entries(spec.properties)) out[k] = clone(p.default);
  return out;
}

const SINGULAR = { objects: "object", meshes: "mesh", materials: "material", textures: "texture" };
// The maps of id → entry (scene.py SECTIONS), and the one-entry sections (SINGLETONS).
export const SECTIONS = ["objects", "meshes", "materials", "textures"];
export const SINGLETONS = ["world", "render", "animation"];
export function newId(taken, base, section = "objects") {
  const fallback = SINGULAR[section] || "item";
  const b = String(base || fallback).toLowerCase().replace(/[^a-z0-9_.-]+/g, "_").replace(/^[_.-]+|[_.-]+$/g, "")
    .slice(0, 48) || fallback;
  if (!(b in taken)) return b;
  let n = 2;
  while (`${b}_${n}` in taken) n++;
  return `${b}_${n}`;
}

const base = () => ({ parent: null, location: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1], visible: true, renderable: true });
const title = (s) => String(s).replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const make = {
  mesh: (name, mesh, extra = {}) => ({ name, type: "mesh", ...base(), materials: [], shading: "auto", modifiers: [], mesh, ...extra }),
  light: (name, kind = "point", extra = {}) => ({ name, type: "light", ...base(),
    light: { kind, color: "#ffffff", ...defaultsOf(schema.lights[kind]) }, ...extra }),
  camera: (name, extra = {}) => ({ name, type: "camera", ...base(), camera: defaultsOf(schema.camera), dof_focus: null, ...extra }),
  text: (name, body = "Text", extra = {}) => ({ name, type: "text", ...base(), materials: [], shading: "auto", modifiers: [],
    text: { ...defaultsOf(schema.text), body }, ...extra }),
  empty: (name, extra = {}) => ({ name, type: "empty", ...base(), ...extra }),
  primitive: (p, params = {}) => ({ primitive: p, ...defaultsOf(schema.primitives[p]), ...params }),
  material: (name, preset = null, params = {}) => ({ name, preset, ...defaultsOf(schema.material),
    ...(preset ? schema.material_presets[preset] : {}), ...params }),
  modifier: (type, params = {}) => ({ type, ...defaultsOf(schema.modifiers[type]), ...params, show: true }),
};

// Add something the way the Add menu does: a primitive, a light kind, a camera, text or an empty.
export function addObject(doc, what, at = [0, 0, 0]) {
  const d = clone(doc);
  const [kind, sub] = what.split(":");
  const label = sub || kind;
  const id = newId(d.objects, label);
  if (kind === "mesh") {
    const mid = newId(d.meshes, id, "meshes");
    d.meshes[mid] = make.primitive(sub);
    d.objects[id] = make.mesh(title(label), mid, { location: [...at] });
  } else if (kind === "light") {
    d.objects[id] = make.light(title(`${sub} light`), sub, { location: [at[0], at[1], at[2] + 3] });
  } else if (kind === "camera") {
    d.objects[id] = make.camera("Camera", { location: [...at] });
  } else if (kind === "text") {
    d.objects[id] = make.text("Text", "Text", { location: [...at] });
  } else {
    d.objects[id] = make.empty("Empty", { location: [...at] });
  }
  return { doc: d, id };
}

export function duplicate(doc, id, offset = [0.5, 0.5, 0]) {
  const d = clone(doc);
  const o = clone(d.objects[id]);
  const nid = newId(d.objects, id);
  if (o.type === "mesh") {
    const mid = newId(d.meshes, nid, "meshes");
    d.meshes[mid] = clone(d.meshes[o.mesh]);
    o.mesh = mid;
  }
  o.name = `${o.name}.001`;
  o.location = o.location.map((v, i) => v + offset[i]);
  for (const k of o.keys?.location || []) k[1] = k[1].map((v, i) => v + offset[i]);     // its motion moves with it
  d.objects[nid] = o;
  return { doc: d, id: nid };
}

// Delete; children keep their world placement (worldOf: id -> {location, rotation, scale}).
export function remove(doc, ids, worldOf) {
  const d = clone(doc);
  const gone = new Set(ids);
  for (const [cid, c] of Object.entries(d.objects)) {
    if (!gone.has(cid) && c.parent && gone.has(c.parent)) {
      Object.assign(c, worldOf(cid), { parent: null });
    }
  }
  for (const id of gone) {
    for (const o of Object.values(d.objects)) {
      for (const m of o.modifiers || []) {
        if (m.object === id || m.mirror_object === id) throw new Error(`${id} is used by a modifier on another object`);
      }
      if (o.dof_focus === id) o.dof_focus = null;
    }
    if (d.render.camera === id) d.render.camera = null;
    delete d.objects[id];
  }
  const used = new Set(Object.values(d.objects).map((o) => o.mesh).filter(Boolean));
  for (const mid of Object.keys(d.meshes)) if (!used.has(mid)) delete d.meshes[mid];
  return d;
}

// ─── entry-level diff / patch / three-way merge (scene.py's, in JS) ─────────

export function entries(doc) {
  const out = {};
  for (const sec of SECTIONS) {
    for (const [k, v] of Object.entries(doc[sec] || {})) out[`${sec}.${k}`] = v;
  }
  for (const sec of SINGLETONS) if (doc[sec]) out[sec] = doc[sec];
  return out;
}

export function diff(a, b) {
  const ea = entries(a), eb = entries(b);
  const set = {};
  for (const [k, v] of Object.entries(eb)) if (!deepEqual(ea[k], v)) set[k] = clone(v);
  return { set, delete: Object.keys(ea).filter((k) => !(k in eb)).sort() };
}

export function patch(doc, p) {
  const out = clone(doc);
  for (const [key, val] of Object.entries(p.set || {})) {
    const dot = key.indexOf(".");
    if (dot > 0) (out[key.slice(0, dot)] ||= {})[key.slice(dot + 1)] = clone(val);
    else out[key] = clone(val);
  }
  for (const key of p.delete || []) {
    const dot = key.indexOf(".");
    if (dot > 0 && out[key.slice(0, dot)]) delete out[key.slice(0, dot)][key.slice(dot + 1)];
  }
  return out;
}

export function merge3(baseDoc, local, remote) {
  const eb = entries(baseDoc), el = entries(local), er = entries(remote);
  const keys = [...new Set([...Object.keys(eb), ...Object.keys(el), ...Object.keys(er)])];
  const merged = {}, conflicts = [];
  for (const k of keys) {
    const b = eb[k], l = el[k], r = er[k];
    let v;
    if (deepEqual(l, r)) v = l;
    else if (deepEqual(l, b)) v = r;
    else if (deepEqual(r, b)) v = l;
    else { v = l; conflicts.push(k); }
    if (v !== undefined) merged[k] = v;
  }
  const out = { ...clone(local), ...Object.fromEntries(SECTIONS.map((sec) => [sec, {}])) };
  out.rev = Math.max(local.rev || 0, remote.rev || 0);
  for (const [k, v] of Object.entries(merged)) {
    const dot = k.indexOf(".");
    if (dot > 0) out[k.slice(0, dot)][k.slice(dot + 1)] = clone(v);
    else out[k] = clone(v);
  }
  return { doc: out, conflicts };
}

// Base64 cycls.mesh sidecar → typed arrays (n-gons fan-triangulated for display).
export function decodeSidecar(side) {
  const bytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer;
  const co = new Float32Array(bytes(side.co));
  const loopStart = new Uint32Array(bytes(side.loop_start));
  const loops = new Uint32Array(bytes(side.loops));
  const tris = [];
  for (let f = 0; f < loopStart.length; f++) {
    const s = loopStart[f], e = f + 1 < loopStart.length ? loopStart[f + 1] : loops.length;
    for (let i = s + 1; i + 1 < e; i++) tris.push(loops[s], loops[i], loops[i + 1]);
  }
  return { positions: co, index: new Uint32Array(tris) };
}

// An older document as the current one (scene.py migrate): version 1 had one `material`
// per object; version 2 has slots (`materials`), a face's material_index picking one;
// version 3 has a timeline (`animation`) and an object's `keys`.
export function migrate(doc) {
  if (!doc || (doc.version ?? schema.version) >= schema.version) return doc;
  const out = clone(doc);
  if ((out.version ?? 1) < 2) {
    for (const o of Object.values(out.objects || {})) {
      if ("material" in o) { o.materials = o.material ? [o.material] : []; delete o.material; }
      else if ((o.type === "mesh" || o.type === "text") && !o.materials) o.materials = [];
    }
    out.textures ||= {};
  }
  out.animation ||= clone(schema.new_scene.animation);
  out.version = schema.version;
  return out;
}

// Material fields that name an image (scene.py TEXTURE_FIELDS).
export const TEXTURE_FIELDS = ["base_color_texture", "roughness_texture", "normal_texture"];
export const hasTexture = (m) => !!m && TEXTURE_FIELDS.some((f) => m[f]);

// Drop texture entries no material uses (scene.py prune_textures).
export function pruneTextures(doc) {
  const used = new Set(Object.values(doc.materials).flatMap((m) => TEXTURE_FIELDS.map((f) => m[f]).filter(Boolean)));
  for (const t of Object.keys(doc.textures || {})) if (!used.has(t)) delete doc.textures[t];
  return doc;
}

export function childrenOf(doc, id) {
  return Object.entries(doc.objects).filter(([, o]) => o.parent === id).map(([k]) => k);
}

// The set, not a subject: the studio sweep and its rig, or a ground plane.
export function isBackdrop(doc, id) {
  const o = doc.objects[id];
  return !!o && (id.startsWith("studio_")
    || (o.type === "mesh" && ["plane", "grid", "cyclorama"].includes(doc.meshes[o.mesh]?.primitive)));
}

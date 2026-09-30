import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { SCHEMA, make, TEXTURE_FIELDS } from "./doc.js";
import { FALLOFFS } from "./mesh.js";
import { pose, keyFrames, animated } from "./anim.js";

const PRIMS = ["cube", "uv_sphere", "ico_sphere", "cylinder", "cone", "torus", "plane", "grid", "circle", "monkey"];
const LIGHTS = ["point", "sun", "spot", "area"];
const TYPE_ICON = { mesh: "▲", light: "✹", camera: "▣", text: "T", empty: "✛" };
const label = (s) => String(s).replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function useApp(app) {
  const [, force] = useState(0);
  useEffect(() => app.subscribe(() => force((n) => n + 1)), [app]);
  return app.state;
}

// ─── inputs ──────────────────────────────────────────────────────────────────

function Num({ value, onChange, step = 0.1, min, max, digits = 3 }) {
  const [text, setText] = useState(null);
  const shown = text ?? (typeof value === "number" ? String(+value.toFixed(digits)) : "");
  const commit = () => {
    if (text === null) return;
    const v = Number(text);
    setText(null);
    if (Number.isFinite(v)) onChange(Math.min(max ?? Infinity, Math.max(min ?? -Infinity, v)));
  };
  return <input class="num" value={shown} step={step} inputMode="decimal"
    onInput={(e) => setText(e.currentTarget.value)} onBlur={commit}
    onKeyDown={(e) => { if (e.key === "Enter") { commit(); e.currentTarget.blur(); } if (e.key === "Escape") setText(null); }} />;
}

function Vec({ value, onChange, labels = ["X", "Y", "Z"], step }) {
  return <div class="vec">{value.map((v, i) => (
    <label key={i}><span class={`ax ax${i}`}>{labels[i]}</span>
      <Num value={v} step={step} onChange={(n) => { const next = [...value]; next[i] = n; onChange(next); }} /></label>))}</div>;
}

function Field({ name, spec, value, onChange }) {
  const p = spec;
  if (p.type === "boolean") return <label class="row"><span>{label(name)}</span>
    <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.currentTarget.checked)} /></label>;
  if (p.enum) return <label class="row"><span>{label(name)}</span>
    <select value={value} onChange={(e) => onChange(e.currentTarget.value)}>{p.enum.map((o) => <option key={o} value={o}>{label(o)}</option>)}</select></label>;
  if (p.type === "number" || p.type === "integer") return <label class="row"><span>{label(name)}</span>
    <Num value={value} min={p.minimum} max={p.maximum} step={p.type === "integer" ? 1 : 0.05} digits={p.type === "integer" ? 0 : 3}
      onChange={(v) => onChange(p.type === "integer" ? Math.round(v) : v)} /></label>;
  if (typeof value === "string" && p.pattern) return <label class="row"><span>{label(name)}</span>
    <input type="color" value={value} onInput={(e) => onChange(e.currentTarget.value)} /></label>;
  if (typeof value === "string") return <label class="row"><span>{label(name)}</span>
    <input value={value} onChange={(e) => onChange(e.currentTarget.value)} /></label>;
  if (Array.isArray(value) && value.length === 3 && typeof value[0] === "boolean") return <label class="row"><span>{label(name)}</span>
    <div class="vec">{value.map((v, i) => <label key={i}><span class={`ax ax${i}`}>{"XYZ"[i]}</span>
      <input type="checkbox" checked={v} onChange={(e) => { const n = [...value]; n[i] = e.currentTarget.checked; onChange(n); }} /></label>)}</div></label>;
  if (Array.isArray(value) && value.length === 3) return <div class="row col"><span>{label(name)}</span><Vec value={value} onChange={onChange} /></div>;
  if (Array.isArray(value)) return <div class="row col"><span>{label(name)}</span>
    <Vec value={value} labels={["W", "H"]} onChange={onChange} /></div>;
  return null;
}

function Fields({ spec, values, onChange, skip = [] }) {
  return Object.entries(spec.properties).filter(([k]) => !skip.includes(k)).map(([k, p]) => (
    <Field key={k} name={k} spec={p} value={values[k]} onChange={(v) => onChange(k, v)} />));
}

function Section({ title, children, open = true }) {
  const [o, setO] = useState(open);
  return <div class="section"><div class="section-h" onClick={() => setO(!o)}>{o ? "▾" : "▸"} {title}</div>{o && <div class="section-b">{children}</div>}</div>;
}

// ─── header ──────────────────────────────────────────────────────────────────

function Menu({ label: text, items, onPick, align }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const off = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    addEventListener("pointerdown", off);
    return () => removeEventListener("pointerdown", off);
  }, [open]);
  useEffect(() => {
    const k = (e) => { if (e.detail === text) setOpen(true); };
    addEventListener("studio:open-menu", k);
    return () => removeEventListener("studio:open-menu", k);
  }, [text]);
  return <div class="menu" ref={ref}>
    <button onClick={() => setOpen(!open)}>{text}</button>
    {open && <div class={`menu-pop ${align || ""}`}>{items.map((it, i) => it === "-" ? <hr key={i} /> :
      it.head ? <div key={i} class="menu-head">{it.head}</div> :
      <button key={i} onClick={() => { setOpen(false); onPick(it.id); }}>{it.label}</button>)}</div>}
  </div>;
}

// Blender's destructive mesh ops, by where they run: [id, label, key hint].
// UVs by projection, done by Blender (on the selection in Edit mode).
const UV_OPS = [{ head: "UVs" }, ["uv:cube", "Cube projection"], ["uv:cylinder", "Cylinder projection"],
                ["uv:sphere", "Sphere projection"], ["uv:reset", "Reset (one square a face)"]];
const OBJECT_OPS = [["convert", "Convert to mesh"], ["join", "Join selected", "Ctrl J"], "-",
                    ["triangulate", "Triangulate"], ["merge_by_distance", "Merge by distance"],
                    ["recalc_normals", "Recalculate normals"], "-", ["remesh", "Remesh (voxel)"], ["decimate", "Decimate"],
                    "-", ...UV_OPS];
const EDIT_OPS = [["extrude", "Extrude", "E"], ["fill", "Fill", "F"], ["merge", "Merge at center", "M"], ["delete", "Delete", "X"], "-",
                  ["loopcut", "Loop cut", "Ctrl R"], ["knife", "Knife", "K"], ["connect", "Connect vertices", "J"], "-",
                  { head: "With Blender" }, ["bevel", "Bevel", "Ctrl B"], ["inset", "Inset faces", "I"], ["subdivide", "Subdivide"],
                  ["triangulate", "Triangulate"], ["merge_by_distance", "Merge by distance"], ["recalc_normals", "Recalculate normals"],
                  "-", ...UV_OPS];
const EXPORTS = [{ head: "Into exports/" }, { id: "glb", label: "glTF binary (.glb)" }, { id: "blend", label: "Blender (.blend)" },
                 { id: "fbx", label: "FBX (.fbx)" }, { id: "obj", label: "Wavefront (.obj)" }, { id: "stl", label: "STL (.stl)" }];
const items = (ops) => ops.map((o) => (o === "-" || o.head ? o : { id: o[0], label: o[2] ? `${o[1]}  (${o[2]})` : o[1] }));

export function runEditOp(a, op) {
  if (op.startsWith("uv:")) { a.uv(op.slice(3)); return; }
  if (op === "loopcut" || op === "knife") { a.edit.startTool(op); return; }
  if (op === "connect") { a.edit.connect(); return; }
  const e = a.edit;
  const local = { extrude: e.extrude, fill: e.fill, merge: e.merge, delete: e.remove }[op];
  if (local) local();
  else e.blender(op, label(op).toLowerCase());
}

export function runObjectOp(a, op) {
  if (op.startsWith("uv:")) a.uv(op.slice(3));
  else if (op === "convert") a.convert();
  else if (op === "join") a.join();
  else a.meshOp(op, label(op).toLowerCase());
}

function Header({ s, a }) {
  const addItems = [{ head: "Mesh" }, ...PRIMS.map((p) => ({ id: `mesh:${p}`, label: label(p) })), "-",
                    { head: "Light" }, ...LIGHTS.map((l) => ({ id: `light:${l}`, label: label(l) })), "-",
                    { id: "camera", label: "Camera" }, { id: "text", label: "Text" }, { id: "empty", label: "Empty" }];
  const views = [{ id: "front", label: "Front  (1)" }, { id: "right", label: "Right  (3)" }, { id: "top", label: "Top  (7)" },
                 { id: "camera", label: "Camera  (0)" }, "-", { id: "frame-all", label: "Frame all  (Home)" },
                 { id: "frame-sel", label: "Frame selected  (.)" }, { id: "cam-to-view", label: "Camera to view" }, "-",
                 { id: "shadows", label: s.shadows ? "✓ Shadows" : "Shadows" }];
  const status = { saved: "Saved", saving: "Saving…", unsaved: "Unsaved", error: "Not saved", loading: "Loading…" }[s.status];
  const editing = s.mode === "edit";
  const sel = [{ id: "all", label: "All  (A)" }, { id: "none", label: "None  (Alt A)" }, { id: "invert", label: "Invert  (Ctrl I)" }];
  return <div class="header">
    <span class="brand">Studio</span>
    <button class={`mode-btn ${editing ? "on" : ""}`} title="Object / Edit mode (Tab)" disabled={!!s.busy} onClick={a.edit.toggle}>
      {editing ? "Edit Mode" : "Object Mode"}</button>
    {editing && <div class="seg">{[["vert", "Vertex", "1"], ["edge", "Edge", "2"], ["face", "Face", "3"]].map(([m, t, k]) =>
      <button key={m} class={s.edit?.mode === m ? "on" : ""} title={`${t} select (${k})`} onClick={() => a.edit.setMode(m)}>{t}</button>)}</div>}
    {editing
      ? <><Menu label="Select" items={sel} onPick={(v) => v === "invert" ? a.edit.invert() : a.edit.selectAll(v === "all")} />
          <Menu label="Mesh" items={items(EDIT_OPS)} onPick={(op) => runEditOp(a, op)} /></>
      : <><Menu label="Add" items={addItems} onPick={a.add} />
          <Menu label="Object" items={items(OBJECT_OPS)} onPick={(op) => runObjectOp(a, op)} /></>}
    <Menu label="View" items={views} onPick={(v) => v === "shadows" ? a.setShadows(!s.shadows) : v === "frame-all" ? a.frame(true) : v === "frame-sel" ? a.frame(false)
      : v === "cam-to-view" ? a.cameraToView() : a.view(v)} />
    <button class={`toggle ${s.snap ? "on" : ""}`} title="Snap to 0.1 m / 15° / 0.1 (Shift Tab; Ctrl while dragging flips it)"
      onClick={() => a.edit.toggleSnap()}>Snap</button>
    <div class="seg">{[["translate", "Move", "G"], ["rotate", "Rotate", "R"], ["scale", "Scale", "S"]].map(([m, t, k]) =>
      <button key={m} class={s.gizmo === m ? "on" : ""} title={`${t} (${k})`} onClick={() => a.setGizmo(m)}>{t}</button>)}</div>
    <div class="seg">{[["solid", "Solid"], ["material", "Material"]].map(([m, t]) =>
      <button key={m} class={s.shading === m ? "on" : ""} onClick={() => a.setShading(m)}>{t}</button>)}</div>
    <div class="grow" />
    <button disabled={!s.undo.length} title="Undo (Ctrl+Z)" onClick={a.undo}>↶</button>
    <button disabled={!s.redo.length} title="Redo (Ctrl+Shift+Z)" onClick={a.redo}>↷</button>
    <span class={`status ${s.status}`}>{status}{s.doc ? ` · rev ${s.doc.rev}` : ""}</span>
    {s.engine && <Menu label="Export" items={EXPORTS} onPick={a.exportAs} align="right" />}
    <button disabled={!s.engine || !!s.busy} onClick={() => a.render("snapshot")} title="A quick Blender preview">Snapshot</button>
    <button class="primary" disabled={!s.engine || !!s.busy} onClick={() => a.render("render")} title="Render with Blender (F12)">Render</button>
  </div>;
}

// ─── outliner ────────────────────────────────────────────────────────────────

// The tree as rows, [id, depth] — once per change of the objects, not per render.
function outlineRows(objects) {
  const kids = new Map(), roots = [];
  for (const [id, o] of Object.entries(objects)) {
    if (o.parent && o.parent in objects) {
      if (!kids.has(o.parent)) kids.set(o.parent, []);
      kids.get(o.parent).push(id);
    } else roots.push(id);
  }
  const byName = (x, y) => objects[x].name.localeCompare(objects[y].name);
  const out = [];
  const walk = (id, depth) => {
    out.push([id, depth]);
    for (const c of (kids.get(id) || []).sort(byName)) walk(c, depth + 1);
  };
  roots.sort(byName).forEach((id) => walk(id, 0));
  return out;
}

const ROW_H = 22;
// A windowed list: a scene of thousands of objects draws only the rows in view.
function Outliner({ s, a }) {
  const [editing, setEditing] = useState(null);
  const [view, setView] = useState({ top: 0, height: 900 });
  const box = useRef(null), list = useRef(null);
  const rows = useMemo(() => outlineRows(s.doc.objects), [s.doc.objects]);
  const selected = useMemo(() => new Set(s.selection), [s.selection]);
  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const on = () => setView({ top: el.scrollTop - (list.current?.offsetTop || 0), height: el.clientHeight });
    on();
    el.addEventListener("scroll", on, { passive: true });
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(on) : null;
    ro?.observe(el);
    return () => { el.removeEventListener("scroll", on); ro?.disconnect(); };
  }, []);
  const first = Math.max(0, Math.floor(view.top / ROW_H) - 15);
  const last = Math.min(rows.length, Math.ceil((view.top + view.height) / ROW_H) + 15);
  const row = (id, depth, top) => {
    const o = s.doc.objects[id];
    const sel = selected.has(id);
    const active = s.selection.at(-1) === id;
    return <div key={id} class={`orow ${sel ? "sel" : ""} ${active ? "active" : ""}`} style={{ top, paddingLeft: 6 + depth * 14 }}
      onClick={(e) => a.select([id], e.shiftKey)} onDblClick={() => setEditing(id)}>
      <span class={`ticon t-${o.type}`}>{TYPE_ICON[o.type]}</span>
      {editing === id
        ? <input class="rename" autoFocus value={o.name} onBlur={(e) => { a.update((d) => { d.objects[id].name = e.currentTarget.value.slice(0, 64) || o.name; }, "rename"); setEditing(null); }}
            onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setEditing(null); }} />
        : <span class="oname">{o.name}</span>}
      {s.doc.render.camera === id && <span class="badge">render</span>}
      <button class={`eye ${o.visible ? "" : "off"}`} title="Hide in viewport and render"
        onClick={(e) => { e.stopPropagation(); a.update((d) => { d.objects[id].visible = !o.visible; }, "visibility"); }}>{o.visible ? "◉" : "◯"}</button>
    </div>;
  };
  return <div class="outliner" ref={box}>
    <div class="panel-h">Scene{rows.length > 50 ? ` · ${rows.length} objects` : ""}</div>
    <div class="orows" ref={list} style={{ height: rows.length * ROW_H }}>
      {rows.slice(first, last).map(([id, depth], i) => row(id, depth, (first + i) * ROW_H))}
    </div>
  </div>;
}

// An object picker: a list for a scene of dozens, an id to type for one of thousands.
const PICK_MAX = 300;
function ObjectPick({ s, value, onChange, filter }) {
  const ids = Object.keys(s.doc.objects);
  if (ids.length > PICK_MAX) {
    return <input value={value || ""} placeholder="object id" title="An object's id (the outliner shows names)"
      onChange={(e) => { const v = e.currentTarget.value.trim(); if (!v || (v in s.doc.objects && filter(v, s.doc.objects[v]))) onChange(v || null); }} />;
  }
  return <select value={value || ""} onChange={(e) => onChange(e.currentTarget.value || null)}>
    <option value="">—</option>
    {ids.filter((k) => filter(k, s.doc.objects[k])).map((k) => <option key={k} value={k}>{s.doc.objects[k].name}</option>)}
  </select>;
}

// ─── properties ──────────────────────────────────────────────────────────────

// A channel's key at this frame, Blender's way: a filled diamond when there is one here, a
// hollow green one when the channel moves, grey when it's still. Click keys or unkeys here.
function KeyDot({ s, a, id, ch }) {
  const ks = s.doc.objects[id].keys?.[ch];
  const here = !!ks?.some((k) => k[0] === s.frame);
  const title = here ? `Delete the ${ch} key at frame ${s.frame}` : `Key ${ch} at frame ${s.frame}`;
  return <button class={`keydot ${here ? "here" : ks ? "moves" : ""}`} title={title}
    onClick={() => (here ? a.deleteKeys([ch], [id]) : a.insertKeys([ch], [id]))}>◆</button>;
}

function ObjectPanel({ s, a, id }) {
  const o = s.doc.objects[id];
  const at = pose(o, s.frame);                      // where it is at this frame
  const set = (k, v) => a.update((d) => { d.objects[id][k] = v; }, k);
  const move = (ch, v) => a.setTransform(id, { [ch]: v }, ch);
  return <Section title="Object">
    <label class="row"><span>Name</span><input value={o.name} onChange={(e) => set("name", e.currentTarget.value.slice(0, 64) || o.name)} /></label>
    <div class="row col"><span class="keyed">Location<KeyDot s={s} a={a} id={id} ch="location" /></span><Vec value={at.location} onChange={(v) => move("location", v)} /></div>
    <div class="row col"><span class="keyed">Rotation °<KeyDot s={s} a={a} id={id} ch="rotation" /></span><Vec value={at.rotation} step={5} onChange={(v) => move("rotation", v)} /></div>
    <div class="row col"><span class="keyed">Scale<KeyDot s={s} a={a} id={id} ch="scale" /></span><Vec value={at.scale} onChange={(v) => move("scale", v)} /></div>
    <label class="row"><span>Parent</span><ObjectPick s={s} value={o.parent} onChange={(v) => set("parent", v)}
      filter={(k) => k !== id} /></label>
    <label class="row"><span>Renders</span><input type="checkbox" checked={o.renderable} onChange={(e) => set("renderable", e.currentTarget.checked)} /></label>
  </Section>;
}

function DataPanel({ s, a, id }) {
  const o = s.doc.objects[id];
  if (o.type === "mesh") {
    const m = s.doc.meshes[o.mesh];
    return <Section title={m.primitive ? `Mesh · ${label(m.primitive)}` : `Mesh · ${m.verts} vertices`}>
      {m.primitive && <Fields spec={SCHEMA.primitives[m.primitive]} values={m}
        onChange={(k, v) => a.update((d) => { d.meshes[o.mesh][k] = v; }, `mesh ${k}`)} />}
      <label class="row"><span>Shading</span><select value={o.shading} onChange={(e) => a.update((d) => { d.objects[id].shading = e.currentTarget.value; }, "shading")}>
        {["auto", "smooth", "flat"].map((x) => <option key={x}>{x}</option>)}</select></label>
    </Section>;
  }
  if (o.type === "light") return <Section title={`Light · ${label(o.light.kind)}`}>
    <label class="row"><span>Kind</span><select value={o.light.kind} onChange={(e) => a.update((d) => {
      const kind = e.currentTarget.value;
      d.objects[id].light = { ...make.light("", kind).light, color: o.light.color, energy: o.light.energy };
    }, "light kind")}>{LIGHTS.map((k) => <option key={k} value={k}>{label(k)}</option>)}</select></label>
    <label class="row"><span>Color</span><input type="color" value={o.light.color} onInput={(e) => a.update((d) => { d.objects[id].light.color = e.currentTarget.value; }, "light color")} /></label>
    <Fields spec={SCHEMA.lights[o.light.kind]} values={o.light} onChange={(k, v) => a.update((d) => { d.objects[id].light[k] = v; }, `light ${k}`)} />
  </Section>;
  if (o.type === "camera") return <Section title="Camera">
    <Fields spec={SCHEMA.camera} values={o.camera} onChange={(k, v) => a.update((d) => { d.objects[id].camera[k] = v; }, `camera ${k}`)} />
    {s.doc.render.camera !== id && <button class="wide" onClick={() => a.setRenderCamera(id)}>Use for rendering</button>}
  </Section>;
  if (o.type === "text") return <Section title="Text">
    <Fields spec={SCHEMA.text} values={o.text} onChange={(k, v) => a.update((d) => { d.objects[id].text[k] = v; }, `text ${k}`)} />
  </Section>;
  return null;
}

function MaterialPanel({ s, a, id }) {
  const o = s.doc.objects[id];
  const [picked, setPicked] = useState(0);
  if (o.type !== "mesh" && o.type !== "text") return null;
  const slots = o.materials || [];
  const slot = Math.min(picked, Math.max(0, slots.length - 1));
  const mid = slots[slot] || null;
  const m = mid && s.doc.materials[mid];
  const setM = (k, v) => a.update((d) => { d.materials[mid][k] = v; }, `material ${k}`);
  return <Section title="Material">
    {slots.length > 1 && <div class="slots">{slots.map((x, i) => (
      <button key={i} class={`slot ${i === slot ? "on" : ""}`} onClick={() => setPicked(i)} title={`Slot ${i + 1}`}>
        <span class="swatch" style={{ background: x && s.doc.materials[x] ? s.doc.materials[x].base_color : "transparent" }} />
        {x ? s.doc.materials[x]?.name : "—"}</button>))}</div>}
    <label class="row"><span>{slots.length > 1 ? `Slot ${slot + 1}` : "Uses"}</span>
      <select value={mid || ""} onChange={(e) => a.setSlot(id, slot, e.currentTarget.value || null)}>
        <option value="">—</option>{Object.entries(s.doc.materials).map(([k, x]) => <option key={k} value={k}>{x.name}</option>)}</select>
      <button title="New material" onClick={() => a.addMaterial(id, slot)}>＋</button></label>
    <div class="row slot-tools"><span />
      <div><button title="Add a material slot" onClick={() => { a.addSlot(id); setPicked(slots.length); }}>＋ Slot</button>
        {slots.length > 1 && <button title="Remove this slot" onClick={() => { a.removeSlot(id, slot); setPicked(Math.max(0, slot - 1)); }}>− Slot</button>}
        {s.mode === "edit" && s.edit?.id === id && <button title="The selected faces use this slot" onClick={() => a.edit.assignSlot(slot)}>Assign</button>}</div></div>
    {m && <>
      <label class="row"><span>Preset</span><select value={m.preset || ""} onChange={(e) => {
        const p = e.currentTarget.value;
        a.update((d) => { d.materials[mid] = make.material(m.name, p || null); }, "material preset");
      }}><option value="">custom</option>{Object.keys(SCHEMA.material_presets).map((p) => <option key={p} value={p}>{label(p)}</option>)}</select></label>
      <Fields spec={SCHEMA.material} values={m} onChange={setM}
        skip={[...TEXTURE_FIELDS, ...MAPPING, ...(m.base_color_texture ? ["base_color"] : [])]} />
      <ImagesPanel s={s} a={a} mid={mid} m={m} setM={setM} />
    </>}
  </Section>;
}

const MAPPING = ["texture_scale", "texture_offset", "texture_rotation", "normal_strength"];
const IMAGE_LABEL = { base_color_texture: "Color image", roughness_texture: "Roughness image", normal_texture: "Normal map" };

function Thumb({ a, tid }) {
  const [src, setSrc] = useState(null);
  useEffect(() => { let live = true; a.textureURL(tid).then((u) => live && setSrc(u)).catch(() => {}); return () => { live = false; }; }, [tid]);
  return src ? <img class="thumb" src={src} alt="" /> : <span class="thumb" />;
}

function ImagesPanel({ s, a, mid, m, setM }) {
  const any = TEXTURE_FIELDS.some((f) => m[f]);
  return <>
    {TEXTURE_FIELDS.map((f) => <div class="row" key={f}><span>{IMAGE_LABEL[f]}</span>
      <div class="image-slot">
        {m[f] && <><Thumb a={a} tid={m[f]} /><span class="muted">{s.doc.textures?.[m[f]]?.name}</span></>}
        <label class="btn">{m[f] ? "Replace" : "Upload…"}
          <input type="file" accept="image/*" hidden onChange={(e) => {
            const file = e.currentTarget.files?.[0];
            e.currentTarget.value = "";
            if (file) a.uploadTexture(mid, f, file);
          }} /></label>
        {m[f] && <button title="Remove the image" onClick={() => a.clearTexture(mid, f)}>✕</button>}
      </div></div>)}
    {any && <>
      <div class="row col"><span>Image scale</span><Vec value={m.texture_scale} labels={["U", "V"]} onChange={(v) => setM("texture_scale", v)} /></div>
      <div class="row col"><span>Image offset</span><Vec value={m.texture_offset} labels={["U", "V"]} onChange={(v) => setM("texture_offset", v)} /></div>
      <label class="row"><span>Image rotation</span><Num value={m.texture_rotation} step={5} min={-360} max={360} onChange={(v) => setM("texture_rotation", v)} /></label>
      {m.normal_texture && <label class="row"><span>Normal strength</span><Num value={m.normal_strength} min={0} max={10} onChange={(v) => setM("normal_strength", v)} /></label>}
    </>}
  </>;
}

function ModifiersPanel({ s, a, id }) {
  const o = s.doc.objects[id];
  if (o.type !== "mesh" && o.type !== "text") return null;
  const setMods = (fn, what) => a.update((d) => { fn(d.objects[id].modifiers, d); }, what);
  return <Section title="Modifiers" open={o.modifiers.length > 0}>
    {o.modifiers.map((m, i) => <div key={i} class="mod">
      <div class="mod-h">
        <input type="checkbox" checked={m.show} title="Show" onChange={(e) => setMods((ms) => { ms[i].show = e.currentTarget.checked; }, "modifier show")} />
        <b>{label(m.type)}</b>
        <span class="grow" />
        <button disabled={!s.engine || !!s.busy} title="Apply: bake it into the mesh (Blender)" onClick={() => a.applyModifier(i)}>Apply</button>
        <button disabled={i === 0} onClick={() => setMods((ms) => ms.splice(i - 1, 0, ms.splice(i, 1)[0]), "modifier move")}>↑</button>
        <button onClick={() => setMods((ms) => ms.splice(i, 1), "remove modifier")}>✕</button>
      </div>
      <Fields spec={SCHEMA.modifiers[m.type]} values={m} skip={["object", "mirror_object"]}
        onChange={(k, v) => setMods((ms) => { ms[i][k] = v; }, `modifier ${k}`)} />
      {(m.type === "boolean" || m.type === "mirror") && <label class="row"><span>{m.type === "boolean" ? "Cutter" : "Mirror by"}</span>
        <ObjectPick s={s} value={m.type === "boolean" ? m.object : m.mirror_object} filter={(k, x) => k !== id && x.type === "mesh"}
          onChange={(v) => setMods((ms) => { ms[i][m.type === "boolean" ? "object" : "mirror_object"] = v; }, "modifier object")} /></label>}
    </div>)}
    <label class="row"><span>Add</span><select value="" onChange={(e) => {
      const t = e.currentTarget.value;
      if (t === "boolean") { a.toast("Pick the cutter object in the boolean's Cutter field"); }
      if (t) setMods((ms) => { ms.push(make.modifier(t)); }, `add ${t}`);
    }}><option value="">+ Modifier…</option>{Object.keys(SCHEMA.modifiers).map((t) => <option key={t} value={t}>{label(t)}</option>)}</select></label>
  </Section>;
}

function ScenePanel({ s, a }) {
  const cams = Object.entries(s.doc.objects).filter(([, o]) => o.type === "camera");
  return <>
    <Section title="World">
      <Fields spec={SCHEMA.world} values={s.doc.world} onChange={(k, v) => a.update((d) => { d.world[k] = v; }, `world ${k}`)} />
    </Section>
    <Section title="Render">
      <label class="row"><span>Camera</span><select value={s.doc.render.camera || ""} onChange={(e) => a.setRenderCamera(e.currentTarget.value || null)}>
        <option value="">—</option>{cams.map(([k, o]) => <option key={k} value={k}>{o.name}</option>)}</select></label>
      <Fields spec={SCHEMA.render} values={s.doc.render} skip={["camera"]}
        onChange={(k, v) => a.update((d) => { d.render[k] = v; }, `render ${k}`)} />
    </Section>
    <RendersPanel s={s} a={a} />
  </>;
}

// Elapsed against the estimate; past it, it just keeps honest time.
function Progress({ p }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 500); return () => clearInterval(t); }, []);
  const secs = (Date.now() - p.start) / 1000;
  const pct = Math.min(96, (secs / Math.max(p.eta, 1)) * 100);
  return <span class="progress"><span class="bar"><i style={{ width: `${pct}%` }} /></span>
    <span class="muted">{Math.round(secs)}s{secs < p.eta ? ` / ~${p.eta}s` : ""}</span></span>;
}

// The workspace's renders, newest first — opened full size on the chat's canvas.
function RendersPanel({ s, a }) {
  const [list, setList] = useState(null);
  const count = s.preview?.path;                 // a new render refreshes the list
  useEffect(() => { let live = true; a.renders().then((r) => live && setList(r)); return () => { live = false; }; }, [count]);
  if (!list?.length) return null;
  return <Section title="Renders">
    {list.slice(-8).reverse().map((r) => <div class="row render-row" key={r.path + r.at}>
      <span title={r.at}>{r.video ? "▶ " : ""}{r.path.replace(/^renders\//, "")}</span>
      <span class="muted">{r.video ? `${r.frames} frames · ${r.fps} fps` : `${r.resolution?.join("×")} · ${Math.round(r.seconds)}s`}</span>
      {s.engine && <button onClick={() => a.openFile(r.path)}>Open</button>}
    </div>)}
  </Section>;
}

// Edit mode: what's selected, and the settings the Mesh menu's ops use.
function EditPanel({ s, a }) {
  const m = s.editMesh, e = s.edit;
  if (!m || !e) return null;
  const nEdges = new Set(m.faces.flatMap((f) => f.map((v, i) => { const w = f[(i + 1) % f.length]; return v < w ? `${v},${w}` : `${w},${v}`; }))).size
    + m.loose.length;
  const total = { vert: m.co.length / 3, edge: nEdges, face: m.faces.length }[e.mode];
  const t = s.tools;
  // the last loop cut stays adjustable only while it is still the last thing done
  const cut = s.lastCut && s.lastCut.rev === s.undo.length && s.undo.at(-1)?.label === "loop cut" ? s.lastCut : null;
  const num = (k, name, opts = {}) => <label class="row"><span>{name}</span>
    <Num value={t[k]} step={opts.step ?? 0.01} min={opts.min ?? 0} max={opts.max} digits={opts.digits ?? 4}
      onChange={(v) => a.setTool(k, opts.int ? Math.max(1, Math.round(v)) : v)} /></label>;
  return <>
    <Section title="Edit Mode">
      <div class="muted">{e.items.length} of {total} {e.mode === "vert" ? "vertices" : e.mode === "edge" ? "edges" : "faces"} selected
        · {m.co.length / 3} verts · {m.faces.length} faces</div>
      <div class="muted">Click to select, Shift-click to add. G/R/S or the gizmo to move. E extrude, F fill, M merge, X delete,
        Ctrl R loop cut, K knife, J connect, O proportional.</div>
    </Section>
    {cut && <Section title="Loop cut">
      <label class="row"><span>Cuts</span><Num value={cut.cuts} step={1} min={1} max={32} digits={0}
        onChange={(v) => a.edit.adjustLoopCut({ cuts: Math.max(1, Math.round(v)) })} /></label>
      <label class="row"><span>Slide</span><Num value={cut.slide} step={0.1} min={-1} max={1} digits={2}
        onChange={(v) => a.edit.adjustLoopCut({ slide: v })} /></label>
    </Section>}
    <Section title="Proportional editing">
      <label class="row"><span>On (O)</span><input type="checkbox" checked={s.proportional.on}
        onChange={(ev) => a.edit.setProportional({ on: ev.currentTarget.checked })} /></label>
      {s.proportional.on && <>
        <label class="row"><span>Falloff</span><select value={s.proportional.falloff}
          onChange={(ev) => a.edit.setProportional({ falloff: ev.currentTarget.value })}>
          {FALLOFFS.map((f) => <option key={f} value={f}>{label(f)}</option>)}</select></label>
        <label class="row"><span>Radius</span><Num value={s.proportional.radius} step={0.1} min={0.01} max={100}
          onChange={(v) => a.edit.setProportional({ radius: v })} /></label>
        <div class="muted">The wheel sizes it while you drag.</div>
      </>}
    </Section>
    <Section title="Tool settings">
      {num("width", "Bevel width")}{num("segments", "Bevel segments", { step: 1, int: true, digits: 0, max: 32 })}
      {num("thickness", "Inset thickness")}{num("depth", "Inset depth", { min: -10 })}
      {num("cuts", "Subdivide cuts", { step: 1, int: true, digits: 0, max: 10 })}
      {num("distance", "Merge distance", { step: 0.0001, digits: 5 })}
    </Section>
  </>;
}

function ObjectToolsPanel({ s, a }) {
  const t = s.tools;
  return <Section title="Remesh & decimate" open={false}>
    <label class="row"><span>Voxel size</span><Num value={t.voxel_size} step={0.01} min={0.001} max={100} digits={4}
      onChange={(v) => a.setTool("voxel_size", v)} /></label>
    <label class="row"><span>Decimate ratio</span><Num value={t.ratio} step={0.05} min={0} max={1}
      onChange={(v) => a.setTool("ratio", v)} /></label>
  </Section>;
}

function Properties({ s, a }) {
  const id = s.selection.at(-1);
  if (!id || !s.doc.objects[id]) return <div class="props"><div class="panel-h">Scene</div><ScenePanel s={s} a={a} /></div>;
  const o = s.doc.objects[id];
  if (s.mode === "edit") return <div class="props"><div class="panel-h">{o.name} · Edit</div>
    <EditPanel s={s} a={a} /><MaterialPanel s={s} a={a} id={id} /><ModifiersPanel s={s} a={a} id={id} />
  </div>;
  return <div class="props"><div class="panel-h">{o.name}</div>
    <ObjectPanel s={s} a={a} id={id} /><DataPanel s={s} a={a} id={id} />
    <MaterialPanel s={s} a={a} id={id} /><ModifiersPanel s={s} a={a} id={id} />
    {o.type === "mesh" && <ObjectToolsPanel s={s} a={a} />}
  </div>;
}

// ─── time ────────────────────────────────────────────────────────────────────

const INTERPS = [["bezier", "Bézier"], ["linear", "Linear"], ["constant", "Constant"]];

// Blender's timeline, one row: transport, the frame, a scrub bar with the selection's keys,
// the range and rate, auto-key, and the key at this frame's interpolation.
function Timeline({ s, a }) {
  const an = s.doc.animation;
  const [f, setF] = useState(s.frame);                         // playback ticks here, not the whole app
  useEffect(() => a.onFrame(setF), [a]);
  useEffect(() => setF(s.frame), [s.frame]);
  const track = useRef(null);
  const sel = s.selection.filter((id) => s.doc.objects[id]);
  const keys = useMemo(() => [...new Set(sel.flatMap((id) => keyFrames(s.doc.objects[id])))].sort((x, y) => x - y),
                       [s.doc.objects, s.selection]);
  const lo = an.frame_start, hi = Math.max(an.frame_end, an.frame_start + 1);
  const pct = (x) => `${((Math.min(hi, Math.max(lo, x)) - lo) / (hi - lo)) * 100}%`;
  const at = (e) => { const r = track.current.getBoundingClientRect(); return lo + ((e.clientX - r.left) / r.width) * (hi - lo); };
  const scrub = (e) => {
    if (e.button !== 0) return;
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    if (s.playing) a.pause();
    a.setFrame(at(e), { quiet: true });
    const move = (ev) => a.setFrame(at(ev), { quiet: true });
    const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); a.settle(); };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
  };
  const here = keys.includes(f) && !s.playing;
  const interp = here ? sel.map((id) => Object.values(s.doc.objects[id].keys || {}).flat().find((k) => k[0] === f)?.[2])
    .find(Boolean) : null;
  const step = Math.max(1, Math.ceil((hi - lo) / 12 / 5) * 5);
  const ticks = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);
  return <div class="timeline">
    <div class="seg transport">
      <button title="First frame (Shift ←)" onClick={() => a.setFrame(an.frame_start)}>⏮</button>
      <button title="Previous key (↓)" onClick={() => a.jumpKey(-1)}>◂◆</button>
      <button class={s.playing ? "on" : ""} title="Play / pause (Space) — Esc stops where it began" onClick={a.play}>{s.playing ? "❚❚" : "▶"}</button>
      <button title="Next key (↑)" onClick={() => a.jumpKey(1)}>◆▸</button>
      <button title="Last frame (Shift →)" onClick={() => a.setFrame(an.frame_end)}>⏭</button>
    </div>
    <span class="tl-frame" title="The current frame"><Num value={f} step={1} min={0} max={100000} digits={0} onChange={(v) => a.setFrame(v)} /></span>
    <div class="tl-track" onPointerDown={scrub} title="Drag to scrub">
      <div class="tl-in" ref={track}>
        {ticks.map((t) => <span key={t} class="tick" style={{ left: pct(t) }}>{t}</span>)}
        {keys.filter((k) => k >= lo && k <= hi).map((k) => <i key={k} class={`kd ${k === f ? "on" : ""}`} style={{ left: pct(k) }} />)}
        <b class="playhead" style={{ left: pct(f) }} />
      </div>
    </div>
    <div class="tl-range">
      <label title="First frame">Start <Num value={an.frame_start} step={1} min={0} max={100000} digits={0} onChange={(v) => a.setAnimation("frame_start", v)} /></label>
      <label title="Last frame">End <Num value={an.frame_end} step={1} min={0} max={100000} digits={0} onChange={(v) => a.setAnimation("frame_end", v)} /></label>
      <label title="Frames a second">FPS <Num value={an.fps} step={1} min={1} max={120} digits={0} onChange={(v) => a.setAnimation("fps", v)} /></label>
    </div>
    <button class={`rec ${s.autokey ? "on" : ""}`} title="Auto-key: every change is keyed at this frame (moving something that already has keys always keys it)"
      onClick={() => a.setAutokey(!s.autokey)}>●</button>
    <button title="Key the selection's location, rotation and scale here (I) — Alt I removes" disabled={!sel.length}
      onClick={() => a.insertKeys()}>◆ Key</button>
    {here && <select value={interp || "bezier"} title="How the motion leaves this key" onChange={(e) => a.setInterpolation(e.currentTarget.value)}>
      {INTERPS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>}
    {s.engine && <button class="primary" disabled={!animated(s.doc).length || !!s.video}
      title={animated(s.doc).length ? "Render the animation as an mp4 (Cycles, a chunk at a time)" : "Key something first"}
      onClick={a.renderVideo}>Render video</button>}
  </div>;
}

const clock = (secs) => (secs >= 90 ? `${Math.round(secs / 60)} min` : `${Math.max(1, Math.round(secs))} s`);

// A video rendering: frames done, the time left (the server's estimate, counting down between
// chunks), what it's waiting on, and Cancel.
function VideoBar({ v, a }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t); }, []);
  const left = Math.max(0, (v.seconds_left || 0) - (Date.now() - v.at) / 1000);
  const pct = v.total ? (v.done / v.total) * 100 : 0;
  return <div class="videobar">
    <span class="spin" />
    <span>Rendering video{v.total ? ` · ${v.done}/${v.total} frames` : ""}{v.total ? ` · ${left > 0 ? `about ${clock(left)} left` : "nearly there"}` : ""}</span>
    <span class="bar"><i style={{ width: `${pct}%` }} /></span>
    {v.note && <span class="muted" title={v.note}>{v.note.length > 60 ? `${v.note.slice(0, 60)}…` : v.note}</span>}
    <button title="Stop it — what's rendered is dropped" onClick={a.cancelVideo}>Cancel</button>
  </div>;
}

// ─── shell ───────────────────────────────────────────────────────────────────

export function Studio({ app }) {
  const s = useApp(app);
  const a = app.actions;
  const host = useRef(null);
  // Panels follow the frame's width (it can mount at 0 while the canvas slides open)
  // until the person toggles them.
  const [wide, setWide] = useState(() => innerWidth > 760);
  const [picked, setPicked] = useState(null);
  const panels = picked ?? wide;
  const setPanels = setPicked;
  useEffect(() => {
    const fit = () => setWide(innerWidth > 760);
    addEventListener("resize", fit);
    return () => removeEventListener("resize", fit);
  }, []);
  useEffect(() => { app.start(host.current); }, []);
  return <div class={`studio ${panels ? "" : "compact"}`}>
    {s.doc ? <Header s={s} a={a} /> : <div class="header"><span class="brand">Studio</span></div>}
    <div class="body">
      {panels && s.doc && <Outliner s={s} a={a} />}
      <div class="viewport" ref={host}>
        {s.busy && <div class="busy"><span class="spin" /><span>{s.busy}</span>{s.progress && <Progress p={s.progress} />}</div>}
        {s.video && <VideoBar v={s.video} a={a} />}
        {!s.engine && s.doc && <div class="hint">Open the Studio from the chat to render and use Blender's tools.</div>}
        <button class="panels-toggle" onClick={() => setPanels(!panels)}>{panels ? "⤢" : "☰"}</button>
        {s.preview && <div class="preview">
          <div class="preview-h"><b>{s.preview.kind}</b>{s.preview.path && <span>{s.preview.path}</span>}
            {s.preview.seconds && <span class="muted">{s.preview.seconds}s</span>}<span class="grow" />
            {s.preview.path && s.engine && <button title="Open it full size on the canvas" onClick={() => a.openFile(s.preview.path)}>Open</button>}
            <button onClick={a.closePreview}>✕</button></div>
          <img src={s.preview.src} alt={s.preview.kind} />
        </div>}
      </div>
      {panels && s.doc && <Properties s={s} a={a} />}
    </div>
    {s.doc && <Timeline s={s} a={a} />}
    {s.toast && <div class={`toast ${s.toast.kind}`}>{s.toast.text}</div>}
  </div>;
}

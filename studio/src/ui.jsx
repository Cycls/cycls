import { useEffect, useRef, useState } from "preact/hooks";
import { SCHEMA, childrenOf, make, TEXTURE_FIELDS } from "./doc.js";

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
                  { head: "With Blender" }, ["bevel", "Bevel", "Ctrl B"], ["inset", "Inset faces", "I"], ["subdivide", "Subdivide"],
                  ["triangulate", "Triangulate"], ["merge_by_distance", "Merge by distance"], ["recalc_normals", "Recalculate normals"],
                  "-", ...UV_OPS];
const EXPORTS = [{ head: "Into exports/" }, { id: "glb", label: "glTF binary (.glb)" }, { id: "blend", label: "Blender (.blend)" },
                 { id: "fbx", label: "FBX (.fbx)" }, { id: "obj", label: "Wavefront (.obj)" }, { id: "stl", label: "STL (.stl)" }];
const items = (ops) => ops.map((o) => (o === "-" || o.head ? o : { id: o[0], label: o[2] ? `${o[1]}  (${o[2]})` : o[1] }));

export function runEditOp(a, op) {
  if (op.startsWith("uv:")) { a.uv(op.slice(3)); return; }
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
                 { id: "frame-sel", label: "Frame selected  (.)" }, { id: "cam-to-view", label: "Camera to view" }];
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
    <Menu label="View" items={views} onPick={(v) => v === "frame-all" ? a.frame(true) : v === "frame-sel" ? a.frame(false)
      : v === "cam-to-view" ? a.cameraToView() : a.view(v)} />
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

function Outliner({ s, a }) {
  const [editing, setEditing] = useState(null);
  const row = (id, depth) => {
    const o = s.doc.objects[id];
    const sel = s.selection.includes(id);
    const active = s.selection.at(-1) === id;
    return [<div key={id} class={`orow ${sel ? "sel" : ""} ${active ? "active" : ""}`} style={{ paddingLeft: 6 + depth * 14 }}
      onClick={(e) => a.select([id], e.shiftKey)} onDblClick={() => setEditing(id)}>
      <span class={`ticon t-${o.type}`}>{TYPE_ICON[o.type]}</span>
      {editing === id
        ? <input class="rename" autoFocus value={o.name} onBlur={(e) => { a.update((d) => { d.objects[id].name = e.currentTarget.value.slice(0, 64) || o.name; }, "rename"); setEditing(null); }}
            onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setEditing(null); }} />
        : <span class="oname">{o.name}</span>}
      {s.doc.render.camera === id && <span class="badge">render</span>}
      <button class={`eye ${o.visible ? "" : "off"}`} title="Hide in viewport and render"
        onClick={(e) => { e.stopPropagation(); a.update((d) => { d.objects[id].visible = !o.visible; }, "visibility"); }}>{o.visible ? "◉" : "◯"}</button>
    </div>, ...childrenOf(s.doc, id).sort((x, y) => s.doc.objects[x].name.localeCompare(s.doc.objects[y].name)).flatMap((c) => row(c, depth + 1))];
  };
  const roots = Object.keys(s.doc.objects).filter((id) => !s.doc.objects[id].parent || !(s.doc.objects[id].parent in s.doc.objects))
    .sort((x, y) => s.doc.objects[x].name.localeCompare(s.doc.objects[y].name));
  return <div class="outliner"><div class="panel-h">Scene</div>{roots.flatMap((id) => row(id, 0))}</div>;
}

// ─── properties ──────────────────────────────────────────────────────────────

function ObjectPanel({ s, a, id }) {
  const o = s.doc.objects[id];
  const set = (k, v) => a.update((d) => { d.objects[id][k] = v; }, k);
  return <Section title="Object">
    <label class="row"><span>Name</span><input value={o.name} onChange={(e) => set("name", e.currentTarget.value.slice(0, 64) || o.name)} /></label>
    <div class="row col"><span>Location</span><Vec value={o.location} onChange={(v) => set("location", v)} /></div>
    <div class="row col"><span>Rotation °</span><Vec value={o.rotation} step={5} onChange={(v) => set("rotation", v)} /></div>
    <div class="row col"><span>Scale</span><Vec value={o.scale} onChange={(v) => set("scale", v)} /></div>
    <label class="row"><span>Parent</span><select value={o.parent || ""} onChange={(e) => set("parent", e.currentTarget.value || null)}>
      <option value="">—</option>{Object.entries(s.doc.objects).filter(([k]) => k !== id).map(([k, x]) => <option key={k} value={k}>{x.name}</option>)}</select></label>
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
  if (o.type !== "mesh" && o.type !== "text") return null;
  const m = o.material && s.doc.materials[o.material];
  const setM = (k, v) => a.update((d) => { d.materials[o.material][k] = v; }, `material ${k}`);
  return <Section title="Material">
    <label class="row"><span>Uses</span><select value={o.material || ""} onChange={(e) => a.update((d) => { d.objects[id].material = e.currentTarget.value || null; }, "material")}>
      <option value="">—</option>{Object.entries(s.doc.materials).map(([k, x]) => <option key={k} value={k}>{x.name}</option>)}</select>
      <button title="New material" onClick={() => a.addMaterial(id)}>＋</button></label>
    {m && <>
      <label class="row"><span>Preset</span><select value={m.preset || ""} onChange={(e) => {
        const p = e.currentTarget.value;
        a.update((d) => { d.materials[o.material] = make.material(m.name, p || null); }, "material preset");
      }}><option value="">custom</option>{Object.keys(SCHEMA.material_presets).map((p) => <option key={p} value={p}>{label(p)}</option>)}</select></label>
      <Fields spec={SCHEMA.material} values={m} onChange={setM}
        skip={[...TEXTURE_FIELDS, ...MAPPING, ...(m.base_color_texture ? ["base_color"] : [])]} />
      <ImagesPanel s={s} a={a} mid={o.material} m={m} setM={setM} />
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
        <select value={(m.type === "boolean" ? m.object : m.mirror_object) || ""} onChange={(e) => setMods((ms) => {
          ms[i][m.type === "boolean" ? "object" : "mirror_object"] = e.currentTarget.value || null;
        }, "modifier object")}><option value="">—</option>{Object.entries(s.doc.objects).filter(([k, x]) => k !== id && x.type === "mesh")
          .map(([k, x]) => <option key={k} value={k}>{x.name}</option>)}</select></label>}
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
  </>;
}

// Edit mode: what's selected, and the settings the Mesh menu's ops use.
function EditPanel({ s, a }) {
  const m = s.editMesh, e = s.edit;
  if (!m || !e) return null;
  const nEdges = new Set(m.faces.flatMap((f) => f.map((v, i) => { const w = f[(i + 1) % f.length]; return v < w ? `${v},${w}` : `${w},${v}`; }))).size
    + m.loose.length;
  const total = { vert: m.co.length / 3, edge: nEdges, face: m.faces.length }[e.mode];
  const t = s.tools;
  const num = (k, name, opts = {}) => <label class="row"><span>{name}</span>
    <Num value={t[k]} step={opts.step ?? 0.01} min={opts.min ?? 0} max={opts.max} digits={opts.digits ?? 4}
      onChange={(v) => a.setTool(k, opts.int ? Math.max(1, Math.round(v)) : v)} /></label>;
  return <>
    <Section title="Edit Mode">
      <div class="muted">{e.items.length} of {total} {e.mode === "vert" ? "vertices" : e.mode === "edge" ? "edges" : "faces"} selected
        · {m.co.length / 3} verts · {m.faces.length} faces</div>
      <div class="muted">Click to select, Shift-click to add. G/R/S or the gizmo to move. E extrude, F fill, M merge, X delete.</div>
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
        {s.busy && <div class="busy"><span class="spin" />{s.busy}</div>}
        {!s.engine && s.doc && <div class="hint">Open the Studio from the chat to render and use Blender's tools.</div>}
        <button class="panels-toggle" onClick={() => setPanels(!panels)}>{panels ? "⤢" : "☰"}</button>
        {s.preview && <div class="preview">
          <div class="preview-h"><b>{s.preview.kind}</b>{s.preview.path && <span>{s.preview.path}</span>}
            {s.preview.seconds && <span class="muted">{s.preview.seconds}s</span>}<span class="grow" />
            <button onClick={a.closePreview}>✕</button></div>
          <img src={s.preview.src} alt={s.preview.kind} />
        </div>}
      </div>
      {panels && s.doc && <Properties s={s} a={a} />}
    </div>
    {s.toast && <div class={`toast ${s.toast.kind}`}>{s.toast.text}</div>}
  </div>;
}

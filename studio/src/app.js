// The controller: the document, its history, and keeping it in step with disk,
// the agent, the viewport and Blender.
import { SCHEMA, clone, deepEqual, merge3, patch, addObject, duplicate, remove, make, newId, isBackdrop } from "./doc.js";
import * as bridge from "./bridge.js";
import * as M from "./mesh.js";
import { b64Floats, bufferGeometry } from "./primitives.js";
import { diag, recordError } from "./diag.js";

const SESSION = Math.random().toString(36).slice(2, 8);
const UNDO_LIMIT = 128;
const VIEW_ITEMS = 2000;               // element selections past this go to the agent as a count only
// What an object keeps when Blender hands back its mesh (the Studio tool keeps the same).
const KEEP = ["name", "parent", "location", "rotation", "scale", "visible", "renderable", "material", "shading", "modifiers"];
// Edit-mode Blender ops that work on the selection (the rest take the whole mesh);
// the first three need one, the others take "nothing selected" as everything.
const ON_SELECTION = new Set(["bevel", "inset", "subdivide", "triangulate", "merge_by_distance", "recalc_normals"]);
const NEEDS_SELECTION = new Set(["bevel", "inset", "subdivide"]);

export const TOOL_DEFAULTS = { width: 0.05, segments: 2, thickness: 0.05, depth: 0, cuts: 1, distance: 0.0001,
                               voxel_size: 0.05, ratio: 0.5 };

export function createApp(viewportFactory) {
  const listeners = new Set();
  const s = {
    doc: null, base: null, selection: [], shading: "material", gizmo: "translate", status: "loading",
    busy: null, preview: null, toast: null, undo: [], redo: [], error: null, engine: bridge.canEngine(),
    mode: "object", edit: null, editMesh: null, tools: { ...TOOL_DEFAULTS },
  };
  const emit = () => { diag.status = s.status; diag.selection = s.selection; diag.mode = s.mode; listeners.forEach((f) => f(s)); };
  const set = (p) => { Object.assign(s, p); emit(); };
  let vp = null, saveTimer = null, evalTimer = null, viewTimer = null, saving = false, toastTimer = null;
  let elementMode = "vert";
  const meshCache = new Map(), meshLoading = new Map(), evalKeys = new Map();
  // Explicit meshes by data path ("meshes/m-….json"): the edit-mode mesh, its
  // sidecar text until it's on disk, and whether it is.
  const sidecars = new Map();

  function toast(text, kind = "info") {
    clearTimeout(toastTimer);
    set({ toast: { text, kind } });
    toastTimer = setTimeout(() => set({ toast: null }), kind === "error" ? 6000 : 3000);
  }

  // ─── the document ──────────────────────────────────────────────────────────

  function show() {
    vp?.sync(s.doc, s.selection, s.shading);
    if (s.mode === "edit") syncEdit();
    scheduleEvaluate();
  }

  function commit(next, label = "edit") {
    if (deepEqual(next, s.doc)) return;
    s.undo = [...s.undo.slice(-UNDO_LIMIT + 1), { doc: s.doc, label }];
    s.redo = [];
    s.doc = next;
    s.selection = s.selection.filter((id) => id in next.objects);
    set({ status: "unsaved" });
    show();
    scheduleSave();
  }

  function undo() {
    const last = s.undo.at(-1);
    if (!last) return;
    s.undo = s.undo.slice(0, -1);
    s.redo = [...s.redo, { doc: s.doc, label: last.label }];
    s.doc = last.doc;
    s.selection = s.selection.filter((id) => id in s.doc.objects);
    set({ status: "unsaved" }); show(); scheduleSave();
  }

  function redo() {
    const next = s.redo.at(-1);
    if (!next) return;
    s.redo = s.redo.slice(0, -1);
    s.undo = [...s.undo, { doc: s.doc, label: next.label }];
    s.doc = next.doc;
    set({ status: "unsaved" }); show(); scheduleSave();
  }

  function update(fn, label) {
    const next = clone(s.doc);
    fn(next);
    commit(next, label);
  }

  function pruneMeshes(d) {
    const used = new Set(Object.values(d.objects).map((o) => o.mesh).filter(Boolean));
    for (const k of Object.keys(d.meshes)) if (!used.has(k)) delete d.meshes[k];
  }

  // ─── disk + agent ──────────────────────────────────────────────────────────

  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 800);
  }

  // Mesh files first: the scene on disk must never point at one that isn't there.
  async function flushSidecars() {
    const want = new Set(Object.values(s.doc.meshes).map((m) => m.data).filter(Boolean));
    for (const [path, sc] of sidecars) {
      if (sc.written || !want.has(path)) continue;
      await bridge.writeData(path, sc.text);
      sc.written = true;
      sc.text = null;
    }
  }

  async function save() {
    if (saving) { scheduleSave(); return; }
    saving = true;
    set({ status: "saving" });
    try {
      await flushSidecars();
      let disk = null;
      try { disk = await bridge.readScene(); } catch { /* first save */ }
      if (disk && s.base && disk.rev > s.base.rev) absorb(disk, "on disk");      // only newer: a stale read never reverts
      const out = { ...clone(s.doc), rev: Math.max(disk?.rev || 0, s.doc.rev || 0) + 1, by: `app:${SESSION}`,
                    saved_at: new Date().toISOString().slice(0, 19) + "+00:00" };
      await bridge.writeScene(out);
      s.base = clone(out);
      s.doc = { ...s.doc, rev: out.rev, by: out.by, saved_at: out.saved_at };
      set({ status: "saved" });
    } catch (e) {
      set({ status: "error" });
      toast(`Couldn't save: ${e.message}`, "error");
    } finally {
      saving = false;
    }
  }

  // A newer scene from elsewhere (the agent, another tab): keep local edits, take theirs.
  function absorb(remote, where) {
    const { doc, conflicts } = merge3(s.base || remote, s.doc, remote);
    s.base = clone(remote);
    const changed = !deepEqual(doc, s.doc);
    s.doc = doc;
    s.selection = s.selection.filter((id) => id in doc.objects);
    if (conflicts.length) toast(`Kept your version of ${conflicts.slice(0, 3).join(", ")} (changed ${where} too)`, "warn");
    if (changed) show();
    emit();
    return conflicts;
  }

  function onCommand(cmd) {
    if (!cmd || !s.doc) return;
    if (cmd.type === "patch") {
      if (s.base && cmd.base === s.base.rev) {
        const remote = patch(s.base, cmd);
        remote.rev = cmd.rev;
        s.undo = [...s.undo.slice(-UNDO_LIMIT + 1), { doc: s.doc, label: `Agent: ${cmd.label || "edit"}` }];
        const conflicts = absorb(remote, "by the agent");
        if (cmd.label && !conflicts.length) toast(`Agent: ${cmd.label}`);
      } else {
        reload();                           // missed a step; the disk has it all
      }
    } else if (cmd.type === "turn_end") {
      reload();
    } else if (cmd.type === "render_done" || cmd.type === "snapshot") {
      set({ preview: { src: cmd.preview, path: cmd.path || null, kind: cmd.type === "snapshot" ? "Snapshot" : "Render" } });
    }
  }

  async function reload() {
    try {
      const disk = await bridge.readScene();
      if (!s.base || disk.rev > s.base.rev) absorb(disk, "by the agent");
    } catch { /* keep what we have */ }
  }

  // ─── Blender ───────────────────────────────────────────────────────────────

  async function engine(op, payload) {
    await flushSidecars();                // the engine reads mesh files from disk
    return bridge.engine(op, payload);
  }

  // Blender changed an object's mesh (apply, convert, join, an edit-mode op):
  // take it the way the Studio tool does.
  function foldApply(id, r, label) {
    let next = clone(s.doc);
    const o = next.objects[id];
    if (!o) return;
    const keep = Object.fromEntries(KEEP.filter((k) => k in o).map((k) => [k, clone(o[k])]));
    next.objects[id] = make.mesh(o.name, r.mesh_id, keep);
    if (r.modifiers != null) next.objects[id].modifiers = r.modifiers;
    next.meshes[r.mesh_id] = { data: r.data, verts: r.verts, faces: r.faces, bbox: r.bbox };
    const gone = (r.removed || []).filter((rid) => rid !== id && rid in next.objects);
    if (gone.length) next = remove(next, gone, (cid) => vp.worldTRS(cid));
    pruneMeshes(next);
    commit(next, label);
  }

  async function runApply(id, op, params, busy, label) {
    set({ busy });
    try {
      const r = await engine("apply", { scene: s.doc, params: { id, op, ...params } });
      foldApply(id, r, label);
      return r;
    } catch (e) {
      recordError(`apply ${op}`, e);
      toast(`Blender couldn't ${label}: ${e.message}`, "error");
      return null;
    } finally {
      set({ busy: null });
    }
  }

  // ─── selection ─────────────────────────────────────────────────────────────

  function publishView() {
    clearTimeout(viewTimer);
    viewTimer = setTimeout(() => {
      const view = { selection: s.selection, mode: s.mode };
      if (s.mode === "edit" && s.edit) {
        const o = s.doc.objects[s.edit.id];
        view.edit = { object: s.edit.id, mesh: o?.mesh || null, mode: s.edit.mode, count: s.edit.items.length,
                      items: s.edit.items.length <= VIEW_ITEMS ? s.edit.items : null };
      }
      bridge.publishView(view);
    }, 250);
  }

  function select(ids, additive = false) {
    diag.picks = (diag.picks || 0) + 1;
    if (s.mode === "edit" && !(ids.length === 1 && ids[0] === s.edit?.id)) leaveEdit();
    let next = ids;
    if (additive) {
      const cur = new Set(s.selection);
      for (const id of ids) cur.has(id) ? cur.delete(id) : cur.add(id);
      next = [...cur];
      const last = ids.at(-1);
      if (last && next.includes(last)) next = [...next.filter((x) => x !== last), last];   // clicked = active
    }
    set({ selection: next });
    vp?.sync(s.doc, next, s.shading);
    publishView();
  }

  // ─── edit mode ─────────────────────────────────────────────────────────────

  async function loadMesh(path) {
    const hit = sidecars.get(path);
    if (hit) return hit.mesh;
    if (!meshLoading.has(path)) {
      meshLoading.set(path, bridge.readJSON(path).then((side) => {
        const mesh = M.fromSidecar(side);
        sidecars.set(path, { mesh, text: null, written: true });
        trimCaches();
        return mesh;
      }).finally(() => meshLoading.delete(path)));
    }
    return meshLoading.get(path);
  }

  // Old meshes that are already on disk can be read again; keep memory bounded.
  function trimCaches() {
    for (const [path, sc] of sidecars) {
      if (sidecars.size <= 200) break;
      if (sc.written && sc.mesh !== s.editMesh) sidecars.delete(path);
    }
    for (const key of meshCache.keys()) {
      if (meshCache.size <= 64) break;
      meshCache.delete(key);
    }
  }

  const ekey = (x) => (Array.isArray(x) ? `${Math.min(x[0], x[1])},${Math.max(x[0], x[1])}` : x);

  async function enterEdit() {
    const id = s.selection.at(-1), o = id && s.doc.objects[id];
    if (!o || (o.type !== "mesh" && o.type !== "text")) { toast("Select a mesh to edit it"); return; }
    if (s.selection.length > 1) select([id]);
    if (o.type === "text" || !s.doc.meshes[o.mesh]?.data) {
      if (!bridge.canEngine()) { toast("Editing needs the Blender engine — open the Studio from the chat", "error"); return; }
      if (!(await runApply(id, "convert", {}, "Making it an editable mesh…", "convert to mesh"))) return;
    }
    let mesh;
    try {
      set({ busy: "Loading the mesh…" });
      mesh = await loadMesh(s.doc.meshes[s.doc.objects[id].mesh].data);
    } catch (e) {
      toast(`Couldn't load the mesh: ${e.message}`, "error");
      return;
    } finally {
      set({ busy: null });
    }
    s.mode = "edit";
    s.edit = { id, mode: elementMode, items: [] };
    s.editMesh = mesh;
    vp.enterEdit(id, mesh, s.edit);
    emit();
    publishView();
  }

  function leaveEdit() {
    if (s.mode !== "edit") return;
    s.mode = "object";
    s.edit = null;
    s.editMesh = null;
    vp?.leaveEdit();
    emit();
    scheduleEvaluate();
    publishView();
  }

  // After undo, redo or an agent change: show the edited object's mesh as the doc has it.
  async function syncEdit() {
    const e = s.edit, o = e && s.doc.objects[e.id];
    const m = o && s.doc.meshes[o.mesh];
    if (!m?.data) { leaveEdit(); toast("Left Edit mode — that object isn't an editable mesh now"); return; }
    let mesh = sidecars.get(m.data)?.mesh;
    if (mesh === s.editMesh) return;
    if (!mesh) {
      try { mesh = await loadMesh(m.data); } catch (err) { toast(`Couldn't load the mesh: ${err.message}`, "error"); return; }
      const now = s.edit && s.doc.objects[s.edit.id];
      if (!now || s.doc.meshes[now.mesh]?.data !== m.data) return;        // moved on meanwhile
    }
    const prev = s.editMesh;
    const same = prev && prev.co.length === mesh.co.length && prev.faces.length === mesh.faces.length;
    s.editMesh = mesh;
    s.edit = { ...s.edit, items: same ? s.edit.items : [] };
    vp.setEdit(mesh, s.edit);
    emit();
  }

  // A local edit: a new immutable mesh file (written before the next save or engine
  // call), and one undo step.
  function editCommit(mesh, sel, label, opts) {
    const e = s.edit;
    const side = M.toSidecar(mesh), text = JSON.stringify(side);
    const mid = M.sidecarId(text), path = `meshes/${mid}.json`;
    if (!sidecars.has(path)) sidecars.set(path, { text, mesh, written: false });
    const shown = sidecars.get(path).mesh;
    s.editMesh = shown;
    s.edit = { ...e, ...(sel.mode === e.mode ? sel : M.convertSelection(shown, sel, e.mode)) };
    update((d) => {
      d.meshes[mid] = { data: path, verts: side.counts.verts, faces: side.counts.faces, bbox: side.bbox };
      d.objects[e.id].mesh = mid;
      pruneMeshes(d);
    }, label);
    vp.setEdit(shown, s.edit, opts);
    trimCaches();
    emit();
    publishView();
  }

  function setEditSel(sel) {
    s.edit = { ...s.edit, ...sel };
    vp.setEdit(s.editMesh, s.edit);
    emit();
    publishView();
  }

  function editPick(item, additive) {
    const e = s.edit;
    if (!e) return;
    const it = Array.isArray(item) ? [Math.min(...item), Math.max(...item)] : item;
    let items;
    if (it == null) items = additive ? e.items : [];
    else if (additive) {
      items = e.items.some((x) => ekey(x) === ekey(it)) ? e.items.filter((x) => ekey(x) !== ekey(it)) : [...e.items, it];
    } else items = [it];
    setEditSel({ items });
  }

  function guard(fn) {
    try { fn(); } catch (err) { toast(err.message, "error"); }
  }

  const edit = {
    toggle() { return s.mode === "edit" ? leaveEdit() : enterEdit(); },
    setMode(mode) {
      if (!s.edit) return;
      elementMode = mode;
      setEditSel(M.convertSelection(s.editMesh, s.edit, mode));
    },
    selectAll(on = true) {
      if (!s.edit) return;
      setEditSel(on ? M.allElements(s.editMesh, s.edit.mode) : { items: [] });
    },
    invert() {
      if (!s.edit) return;
      const have = new Set(s.edit.items.map(ekey));
      setEditSel({ items: M.allElements(s.editMesh, s.edit.mode).items.filter((x) => !have.has(ekey(x))) });
    },
    remove() {
      const e = s.edit;
      if (!e?.items.length) return;
      guard(() => editCommit(M.remove(s.editMesh, e), { mode: e.mode, items: [] }, "delete"));
    },
    extrude() {
      const e = s.edit, m = s.editMesh;
      if (!e?.items.length) { toast("Select something to extrude"); return; }
      guard(() => {
        const r = e.mode === "face" ? M.extrudeFaces(m, e.items)
          : e.mode === "edge" ? M.extrudeEdges(m, e.items) : M.extrudeVerts(m, e.items);
        let normal = null;
        if (e.mode === "face") {
          const n = e.items.map((f) => M.faceNormal(m, m.faces[f])).reduce((a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]);
          if (Math.hypot(...n) > 1e-9) normal = n;
        }
        editCommit(r.mesh, r.selection, "extrude", { normal });
        actions.setGizmo("translate");
        toast(normal ? "Extruded — drag the blue arrow to pull it out" : "Extruded — drag to place it");
      });
    },
    fill() {
      const e = s.edit;
      guard(() => { const r = M.fill(s.editMesh, M.selectedVerts(s.editMesh, e)); editCommit(r.mesh, r.selection, "fill"); });
    },
    merge() {
      const e = s.edit;
      guard(() => { const r = M.mergeAtCenter(s.editMesh, M.selectedVerts(s.editMesh, e)); editCommit(r.mesh, r.selection, "merge"); });
    },
    // Bevel, inset, subdivide…: Blender does them on the saved mesh, then Edit mode
    // picks up the result.
    async blender(op, label) {
      const e = s.edit;
      if (!e) return;
      if (!bridge.canEngine()) { toast("That needs the Blender engine — open the Studio from the chat", "error"); return; }
      // Inset works on faces: whatever is selected, as the faces it covers.
      const sel = op === "inset" ? M.convertSelection(s.editMesh, e, "face") : e;
      if (NEEDS_SELECTION.has(op) && !sel.items.length) {
        toast(op === "inset" ? "Select the faces to inset" : `Select what to ${label}`); return;
      }
      const t = s.tools;
      const params = { bevel: { width: t.width, segments: t.segments }, inset: { thickness: t.thickness, depth: t.depth },
                       subdivide: { cuts: t.cuts }, merge_by_distance: { distance: t.distance },
                       remesh: { voxel_size: t.voxel_size }, decimate: { ratio: t.ratio } }[op] || {};
      if (ON_SELECTION.has(op)) params.selection = M.engineSelection(sel);
      const r = await runApply(e.id, op, params, `Blender: ${label}…`, label);
      if (r && s.edit) {
        const mesh = await loadMesh(r.data).catch(() => null);
        if (mesh && s.edit) {
          // What Blender left selected (the inset face, the bevel's faces), so the next key carries on.
          const sel = r.selection?.faces ? { mode: "face", items: r.selection.faces }
            : r.selection?.edges ? { mode: "edge", items: r.selection.edges } : null;
          s.editMesh = mesh;
          s.edit = { ...s.edit, items: sel ? M.convertSelection(mesh, sel, s.edit.mode).items : [] };
          vp.setEdit(mesh, s.edit); emit(); publishView();
        }
      }
    },
    onTransformEnd(mesh) {
      if (!s.edit) return;
      editCommit(mesh, { mode: s.edit.mode, items: s.edit.items }, { translate: "move", rotate: "rotate", scale: "scale" }[s.gizmo],
                 { normal: vp.edit?.normal || null });
    },
  };

  // ─── Blender-shaped geometry ───────────────────────────────────────────────

  function needsBlender(o) {
    if (o.type === "text") return true;
    if (o.type !== "mesh") return false;
    const m = s.doc.meshes[o.mesh];
    return m?.primitive === "monkey" || (o.modifiers || []).some((md) => md.show);
  }

  function evalKey(id) {
    const o = s.doc.objects[id];
    const refs = (o.modifiers || []).map((m) => m.object || m.mirror_object).filter(Boolean)
      .map((r) => [s.doc.objects[r], s.doc.objects[r] && s.doc.meshes[s.doc.objects[r].mesh]]);
    return JSON.stringify([o.type, o.text, o.modifiers, o.mesh && s.doc.meshes[o.mesh], refs,
                           (o.modifiers || []).length ? [o.location, o.rotation, o.scale] : 0]);
  }

  function scheduleEvaluate() {
    clearTimeout(evalTimer);
    evalTimer = setTimeout(evaluate, 300);
  }

  async function evaluate() {
    if (!s.doc || !bridge.canEngine()) return;
    const want = [];
    for (const [id, o] of Object.entries(s.doc.objects)) {
      if (s.mode === "edit" && s.edit?.id === id) continue;          // Edit mode shows the cage, not the result
      if (!needsBlender(o)) { if (evalKeys.has(id)) { evalKeys.delete(id); vp?.clearEvaluated(id); vp?.sync(s.doc, s.selection, s.shading); } continue; }
      const key = evalKey(id);
      if (evalKeys.get(id) !== key) want.push([id, key]);
    }
    if (!want.length) return;
    for (const [id, key] of want) evalKeys.set(id, key);
    diag.evaluations++;
    try {
      set({ busy: "Blender is shaping the geometry…" });
      const r = await engine("evaluate", { scene: s.doc, params: { ids: want.map(([id]) => id) } });
      for (const [id, key] of want) {
        const m = r.meshes?.[id];
        if (!m || evalKeys.get(id) !== key) continue;
        vp?.setEvaluated(id, key, { positions: new Float32Array(b64Floats(m.positions)),
                                    normals: new Float32Array(b64Floats(m.normals)),
                                    index: new Uint32Array(b64Floats(m.index)) });
      }
    } catch (e) {
      for (const [id] of want) evalKeys.delete(id);
      recordError("evaluate", e);
      toast(`Blender couldn't shape it: ${e.message}`, "error");
    } finally {
      set({ busy: null });
    }
  }

  function explicitGeometry(mid, m, shading = "auto") {
    const key = `${m?.data}|${shading}`;
    if (meshCache.has(key)) return meshCache.get(key);
    const hit = m?.data && sidecars.get(m.data);
    if (hit) {
      const g = bufferGeometry(M.displayBuffers(hit.mesh, shading));
      meshCache.set(key, g);
      return g;
    }
    if (m?.data && !meshLoading.has(m.data)) {
      const path = m.data;
      loadMesh(path).then(() => {
        // Whatever stood in for it until now gets rebuilt with the real thing.
        vp?.invalidate((id, o) => s.doc.meshes[o.mesh]?.data === path);
        vp?.sync(s.doc, s.selection, s.shading);
      }).catch(() => toast(`Couldn't load mesh ${path}`, "error"));
    }
    return null;
  }

  // ─── actions ───────────────────────────────────────────────────────────────

  // What "frame all" means: the subjects, not the studio sweep or a ground plane.
  function subjects() {
    return Object.entries(s.doc.objects)
      .filter(([id, o]) => (o.type === "mesh" || o.type === "text") && o.visible && !isBackdrop(s.doc, id))
      .map(([id]) => id);
  }

  const active = () => {
    const id = s.selection.at(-1);
    return id && s.doc.objects[id] ? id : null;
  };

  const actions = {
    commit, undo, redo, update, select, toast, edit,
    add(what) {
      leaveEdit();
      const at = [0, 0, 0];
      const { doc, id } = addObject(s.doc, what, at);
      commit(doc, `add ${what}`);
      select([id]);
    },
    duplicate() {
      let doc = s.doc;
      const ids = [];
      for (const id of s.selection) { const r = duplicate(doc, id); doc = r.doc; ids.push(r.id); }
      if (ids.length) { commit(doc, "duplicate"); select(ids); }
    },
    remove() {
      if (!s.selection.length) return;
      try { commit(remove(s.doc, s.selection, (id) => vp.worldTRS(id)), "delete"); select([]); }
      catch (e) { toast(e.message, "error"); }
    },
    hide(on) {
      update((d) => { for (const id of on ? s.selection : Object.keys(d.objects)) d.objects[id].visible = !on; },
             on ? "hide" : "unhide");
      if (on) select([]);
    },
    setShading(shading) { set({ shading }); vp?.sync(s.doc, s.selection, shading); },
    setGizmo(mode) { set({ gizmo: mode }); vp?.setGizmoMode(mode); },
    setTool(k, v) { set({ tools: { ...s.tools, [k]: v } }); },
    view(name) { if (name === "camera") { if (!vp.throughCamera(s.doc)) toast("No render camera yet"); } else vp.view(name); },
    frame(all) {
      if (s.mode === "edit" && !all && s.edit?.items.length) { vp.frame([s.edit.id]); return; }
      vp.frame(all || !s.selection.length ? subjects() : s.selection);
    },
    cameraToView() {
      const cam = s.doc.render.camera;
      if (!cam) { toast("No render camera — add one first"); return; }
      update((d) => Object.assign(d.objects[cam], vp.viewAsCamera(), { parent: null }), "camera to view");
    },
    setRenderCamera(id) { update((d) => { d.render.camera = id; }, "render camera"); },
    addMaterial(id) {
      update((d) => {
        const mid = newId(d.materials, `${id}_material`, "materials");
        d.materials[mid] = make.material(d.objects[id].name + " Material");
        d.objects[id].material = mid;
      }, "new material");
    },
    // Object mode: Blender's destructive ops on the active object.
    applyModifier(i) {
      const id = active(), md = id && s.doc.objects[id].modifiers[i];
      return md ? runApply(id, "modifier_apply", { index: i }, `Applying ${md.type}…`, `apply ${md.type}`) : null;
    },
    convert() {
      const id = active();
      return id ? runApply(id, "convert", {}, "Converting to a mesh…", "convert to mesh") : null;
    },
    join() {
      const id = active(), others = s.selection.filter((x) => x !== id && s.doc.objects[x]?.type === "mesh");
      if (!id || !others.length) { toast("Select the meshes to join, the one to keep last"); return; }
      runApply(id, "join", { others }, "Joining…", "join").then((r) => { if (r) select([id]); });
    },
    meshOp(op, label) {
      const id = active();
      if (!id) { toast("Select a mesh first"); return; }
      const t = s.tools;
      const params = { remesh: { voxel_size: t.voxel_size }, decimate: { ratio: t.ratio },
                       merge_by_distance: { distance: t.distance } }[op] || {};
      runApply(id, op, params, `Blender: ${label}…`, label);
    },
    async render(kind = "render") {
      if (!bridge.canEngine()) { toast("Rendering needs the Blender engine — open the Studio from the chat", "error"); return; }
      set({ busy: kind === "render" ? "Rendering with Blender (Cycles)…" : "Taking a quick look with Blender…" });
      const t0 = performance.now();
      try {
        const r = await engine(kind, { scene: s.doc, name: "studio" });
        set({ preview: { src: r.preview, path: r.path || null, kind: kind === "render" ? "Render" : "Snapshot",
                         seconds: Math.round((performance.now() - t0) / 1000) } });
        if (r.path) toast(`Saved ${r.path}`);
      } catch (e) {
        toast(e.message, "error");
      } finally {
        set({ busy: null });
      }
    },
    // The whole scene as a file in exports/ (the route names and saves it).
    async exportAs(format) {
      if (!bridge.canEngine()) { toast("Exporting needs the Blender engine — open the Studio from the chat", "error"); return; }
      set({ busy: `Exporting ${format.toUpperCase()} with Blender…` });
      try {
        const r = await engine("export", { scene: s.doc, params: { format }, name: "scene" });
        toast(`Saved ${r.path}`);
      } catch (e) {
        toast(`Couldn't export: ${e.message}`, "error");
      } finally {
        set({ busy: null });
      }
    },
    closePreview() { set({ preview: null }); },
    ask(text) { bridge.ask(text).catch((e) => toast(e.message, "error")); },
  };

  return {
    state: s, actions,
    subscribe(f) { listeners.add(f); return () => listeners.delete(f); },
    async start(host) {
      vp = viewportFactory(host, {
        onPick: (id, shift) => select(id ? [id] : [], shift && !!id),
        onTransform: () => {},
        onTransformEnd: (id, trs) => update((d) => Object.assign(d.objects[id], trs), "transform"),
        onEditPick: editPick,
        onEditTransformEnd: edit.onTransformEnd,
        onEditLost: () => { if (s.mode === "edit") leaveEdit(); },
        explicitGeometry,
      });
      await bridge.ready();
      diag.engine = bridge.canEngine();
      try {
        const doc = await bridge.readScene();
        s.doc = doc;
        s.base = clone(doc);
        set({ status: "saved" });
      } catch (e) {
        s.doc = clone(SCHEMA.new_scene);
        s.base = null;
        set({ status: "unsaved" });
        scheduleSave();
      }
      show();
      // Open on the shot: through the render camera when there is one.
      if (!(s.doc.render.camera && vp.throughCamera(s.doc))) vp.frame(subjects());
      bridge.onCommand(onCommand);
      return vp;
    },
    get viewport() { return vp; },
  };
}

// The 3D viewport: three.js in Blender's space (Z up, metres, Euler XYZ — which
// three.js reads as order 'ZYX'). It mirrors the scene document and reports what
// the user does back to the app; it never owns the document.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";
import { primitiveGeometry, bufferGeometry } from "./primitives.js";
import { deepEqual, isBackdrop } from "./doc.js";
import { displayBuffers, edges, selectedVerts, centroid, moveVerts } from "./mesh.js";
import { diag } from "./diag.js";
import { WORLDS } from "./worlds.js";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
const DEG = Math.PI / 180;
const ORANGE = 0xffa028, ORANGE_DIM = 0xe56d1c;
const GREY = new THREE.Color("#3d3d3d");            // Solid shading's backdrop, as Blender's
// Blender watts → three's physical units, tuned by eye against Cycles renders.
const LIGHT = { point: 0.08, spot: 0.08, area: 0.35, sun: 2.0 };

// A Blender world HDRI (a 64×32 copy, see scripts/worlds.py) as a texture.
const worldMaps = new Map();
function worldMap(name) {
  if (!worldMaps.has(name)) {
    const b64 = WORLDS[name] || WORLDS.studio;
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const data = new Uint16Array(bytes.length);
    for (let i = 0; i < bytes.length; i += 4) {
      const f = bytes[i + 3] ? 2 ** (bytes[i + 3] - 136) : 0;            // RGBE
      for (let c = 0; c < 3; c++) data[i + c] = THREE.DataUtils.toHalfFloat((bytes[i + c] + 0.5) * f);
      data[i + 3] = THREE.DataUtils.toHalfFloat(1);
    }
    const t = new THREE.DataTexture(data, 64, 32, THREE.RGBAFormat, THREE.HalfFloatType);
    t.magFilter = t.minFilter = THREE.LinearFilter;
    t.wrapS = THREE.RepeatWrapping;
    t.needsUpdate = true;
    worldMaps.set(name, t);
  }
  return worldMaps.get(name);
}

// The world as Cycles sees it: the HDRI in Blender's equirectangular mapping, in
// Blender's (Z-up) space, turned by the world's rotation, times its strength.
function skyDome(w) {
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(500, 32, 16), new THREE.ShaderMaterial({
    uniforms: { map: { value: worldMap(w.hdri) }, strength: { value: w.strength ?? 0.35 },
                turn: { value: (w.rotation || 0) * DEG } },
    vertexShader: `varying vec3 vDir;
      void main() {
        vec4 p = modelMatrix * vec4(position, 1.0);
        vDir = p.xyz - cameraPosition;
        gl_Position = projectionMatrix * viewMatrix * p;
      }`,
    fragmentShader: `uniform sampler2D map; uniform float strength; uniform float turn; varying vec3 vDir;
      void main() {
        vec3 d = normalize(vDir);
        float c = cos(turn), s = sin(turn);
        d = vec3(c * d.x - s * d.y, s * d.x + c * d.y, d.z);
        vec2 uv = vec2(0.5 - atan(d.y, d.x) / 6.28318530718, 0.5 - asin(clamp(d.z, -1.0, 1.0)) / 3.14159265359);
        gl_FragColor = vec4(texture2D(map, uv).rgb * strength, 1.0);
      }`,
    side: THREE.BackSide, depthWrite: false, toneMapped: false,
  }));
  mesh.frustumCulled = false;
  mesh.renderOrder = -1;
  return mesh;
}

export function trsOf(node) {
  return {
    location: node.position.toArray().map((v) => +v.toFixed(5)),
    rotation: [node.rotation.x, node.rotation.y, node.rotation.z].map((r) => +(r / DEG).toFixed(4)),
    scale: node.scale.toArray().map((v) => +v.toFixed(5)),
  };
}

function applyTRS(node, o) {
  node.position.fromArray(o.location);
  node.rotation.set(o.rotation[0] * DEG, o.rotation[1] * DEG, o.rotation[2] * DEG, "ZYX");
  node.scale.fromArray(o.scale);
}

export class Viewport {
  constructor(host, hooks) {
    this.hooks = hooks;
    this.nodes = new Map();          // object id -> THREE.Object3D (the object's own transform)
    this.sigs = new Map();           // object id -> signature of what built it
    this.evaluated = new Map();      // object id -> { key, geometry }
    this.selection = [];
    this.shading = "material";
    this.dirty = true;

    const r = (this.renderer = new THREE.WebGLRenderer({ antialias: true }));
    r.setPixelRatio(Math.min(devicePixelRatio, 2));
    r.toneMapping = THREE.NeutralToneMapping;        // Khronos PBR Neutral, as the engine renders
    r.domElement.tabIndex = 0;
    r.domElement.className = "viewport-canvas";
    host.appendChild(r.domElement);
    // Camera view's render frame; outside it is dimmed, as Blender's passepartout.
    this.frameEl = Object.assign(document.createElement("div"), { className: "cam-frame", hidden: true });
    host.appendChild(this.frameEl);

    const scene = (this.scene = new THREE.Scene());
    scene.background = GREY;
    RectAreaLightUniformsLib.init();
    this.pmrem = new THREE.PMREMGenerator(r);
    this.headlight = new THREE.HemisphereLight(0xffffff, 0x444444, 1.2);   // solid shading only
    scene.add(this.headlight);

    const grid = new THREE.GridHelper(40, 40, 0x555555, 0x4a4a4a);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);
    const axis = (a, b, color) => new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]),
                                                 new THREE.LineBasicMaterial({ color }));
    scene.add(axis(new THREE.Vector3(-20, 0, 0.001), new THREE.Vector3(20, 0, 0.001), 0x9e3a42));
    scene.add(axis(new THREE.Vector3(0, -20, 0.001), new THREE.Vector3(0, 20, 0.001), 0x6a9a2c));
    this.root = new THREE.Group();
    scene.add(this.root);

    const cam = (this.camera = new THREE.PerspectiveCamera(39.6, 1, 0.05, 2000));
    cam.position.set(7.36, -6.93, 4.96);
    this.orbit = new OrbitControls(cam, r.domElement);
    this.orbit.target.set(0, 0, 1);
    this.orbit.screenSpacePanning = true;
    this.orbit.update();
    // Orbiting leaves the camera view — but only once the view moves: a plain click
    // starts an orbit too, and must not put the camera's own lines at the eye.
    this.orbit.addEventListener("change", () => { this.touch(); if (this.orbiting) this.leaveCamera(); });
    this.orbit.addEventListener("start", () => { this.orbiting = true; });
    this.orbit.addEventListener("end", () => { this.orbiting = false; });

    const gizmo = (this.gizmo = new TransformControls(cam, r.domElement));
    gizmo.setSize(0.9);
    scene.add(gizmo.getHelper ? gizmo.getHelper() : gizmo);
    gizmo.addEventListener("change", () => this.touch());
    // Edit mode moves vertices through this: the gizmo sits on the selection's centre.
    this.pivot = new THREE.Object3D();
    scene.add(this.pivot);
    gizmo.addEventListener("dragging-changed", (e) => {
      this.orbit.enabled = !e.value;
      if (gizmo.object === this.pivot) { e.value ? this.editDragStart() : this.editDragEnd(); return; }
      if (!e.value && gizmo.object) this.hooks.onTransformEnd?.(gizmo.object.userData.id, trsOf(gizmo.object));
    });
    gizmo.addEventListener("objectChange", () => {
      if (gizmo.object === this.pivot) { this.editDragMove(); return; }
      if (gizmo.object) this.hooks.onTransform?.(gizmo.object.userData.id, trsOf(gizmo.object));
    });

    // Click selects; a drag orbits. Shift adds to the selection.
    const ray = new THREE.Raycaster();
    ray.params.Line.threshold = 0.05;
    let down = null;
    r.domElement.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; r.domElement.focus(); });
    r.domElement.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || gizmo.dragging || e.button !== 0) return;
      if (this.edit) { this.hooks.onEditPick?.(this.pickElement(e.clientX, e.clientY), e.shiftKey); return; }
      const rect = r.domElement.getBoundingClientRect();
      ray.setFromCamera({ x: ((e.clientX - rect.left) / rect.width) * 2 - 1,
                          y: -((e.clientY - rect.top) / rect.height) * 2 + 1 }, cam);
      // Looking through a camera puts its own gizmo at the eye; it must not win every click.
      const hit = ray.intersectObjects(this.root.children, true)
        .find((h) => this.idOf(h.object) && h.object.visible && this.idOf(h.object) !== this.through);
      this.hooks.onPick?.(hit ? this.idOf(hit.object) : null, e.shiftKey);
    });

    new ResizeObserver(() => this.resize()).observe(host);
    this.host = host;
    this.resize();
    this.draw = () => {
      clearTimeout(this.fallback);
      this.fallback = null;
      if (!this.dirty) return;
      this.dirty = false;
      r.render(scene, cam);
      diag.frames++;
    };
    const loop = () => { this.draw(); requestAnimationFrame(loop); };
    loop();
  }

  // Draw on the next frame — or from a timer, when the browser throttles frames for
  // this (cross-origin, possibly unfocused) iframe and rAF all but stops.
  touch() {
    this.dirty = true;
    if (!this.fallback) this.fallback = setTimeout(this.draw, 120);
  }

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    diag.resizes++;
    diag.host = [w, h];
    if (w === this._w && h === this._h) return;      // a canvas resize must never feed back into another
    this._w = w; this._h = h;
    this.renderer.setSize(w, h, false);
    diag.canvas = [this.renderer.domElement.width, this.renderer.domElement.height];
    this.camera.aspect = w / Math.max(1, h);
    this.camera.updateProjectionMatrix();
    this.fitShot();
    this.touch();
  }

  idOf(o) {
    for (let n = o; n; n = n.parent) if (n.userData.id && n.userData.pick) return n.userData.id;
    return null;
  }

  // ─── document → scene ─────────────────────────────────────────────────────

  sync(doc, selection, shading) {
    diag.syncs++;
    diag.objects = Object.keys(doc.objects).length;
    this.doc = doc;
    this.selection = selection;
    const shadingChanged = shading !== this.shading;
    this.shading = shading;
    this.headlight.visible = shading === "solid";
    for (const id of [...this.nodes.keys()]) if (!(id in doc.objects)) this.drop(id);
    for (const [id, o] of Object.entries(doc.objects)) {
      const sig = { o: { ...o, location: 0, rotation: 0, scale: 0, parent: 0 },
                    m: o.mesh ? doc.meshes[o.mesh] : null, mat: o.material ? doc.materials[o.material] : null,
                    ev: this.evaluated.get(id)?.key ?? null, shading };
      if (!this.nodes.has(id) || shadingChanged || !deepEqual(this.sigs.get(id), sig)) {
        this.drop(id);
        this.nodes.set(id, this.build(id, o, doc));
        this.sigs.set(id, sig);
      }
      const node = this.nodes.get(id);
      if (!(this.gizmo.dragging && this.gizmo.object === node)) applyTRS(node, o);
      node.visible = o.visible;
      if (id === this.through) node.children.forEach((c) => { c.visible = false; });
    }
    for (const [id, o] of Object.entries(doc.objects)) {       // parenting, after everything exists
      const node = this.nodes.get(id);
      const parent = o.parent && this.nodes.get(o.parent) ? this.nodes.get(o.parent) : this.root;
      if (node.parent !== parent) parent.add(node);
    }
    if (this.edit) this.attachEdit();
    if (this.through && !this.throughCamera(doc)) this.leaveCamera();      // camera view follows the camera
    this.scene.environment = shading === "material" ? this.probe(doc) : null;
    this.scene.background = shading === "material" ? this.worldBackground : GREY;      // the world, as it renders
    this.highlight();
    this.touch();
  }

  // What Material Preview lights with: what the subjects would see in Blender — the
  // world (its colour or its HDRI) past the backdrop, which the scene's lamps light.
  // Baked at the subjects' centre, again only when that changes.
  probe(doc) {
    const w = doc.world || {};
    const set = [], lamps = [];
    for (const [id, o] of Object.entries(doc.objects)) {
      const at = [o.location, o.rotation, o.scale, o.parent, o.visible];
      if (o.type === "light") lamps.push([at, o.light]);
      else if (isBackdrop(doc, id)) set.push([id, at, doc.meshes[o.mesh], o.material && doc.materials[o.material]]);
    }
    this.scene.updateMatrixWorld();
    const box = new THREE.Box3();
    for (const [id, node] of this.nodes) {
      const o = doc.objects[id];
      if ((o.type === "mesh" || o.type === "text") && o.visible && !isBackdrop(doc, id) && node.userData.surface) {
        box.expandByObject(node.userData.surface);
      }
    }
    const at = box.isEmpty() ? new THREE.Vector3(0, 0, 1) : box.getCenter(new THREE.Vector3());
    const key = JSON.stringify([w, set, lamps, at.toArray().map((v) => v.toFixed(1))]);
    if (key === this.probeKey) return this.probeTarget.texture;
    this.probeKey = key;

    // The world alone first: it lights the set, then the set and the world light the subjects.
    const sky = new THREE.Scene(), dome = w.kind === "color" ? null : skyDome(w);
    sky.background = new THREE.Color(0);
    if (dome) sky.add(dome);
    else sky.background = new THREE.Color(w.color).multiplyScalar(w.strength ?? 1);
    const world = this.pmrem.fromScene(sky, 0, 0.1, 1000);

    const s = this.scene, saved = [];
    const hide = (n) => { saved.push([n, n.visible]); n.visible = false; };
    s.children.forEach((c) => { if (c !== this.root) hide(c); });            // grid, axes, gizmo, headlight
    for (const [id, node] of this.nodes) {
      const o = doc.objects[id];
      if (o.type === "light") node.traverse((n) => { if (n.isMesh || n.isLine) hide(n); });   // the lamp, not its icon
      else if (isBackdrop(doc, id)) node.traverse((n) => { if (n.isLine || n.isPoints) hide(n); });   // no outlines
      else hide(node);
    }
    const [bg, env] = [s.background, s.environment];
    s.background = sky.background;
    s.environment = world.texture;
    if (dome) s.add(dome);
    const target = this.pmrem.fromScene(s, 0, 0.1, 1000, { position: at });
    if (dome) { s.remove(dome); dome.geometry.dispose(); dome.material.dispose(); }
    [s.background, s.environment] = [bg, env];
    saved.reverse().forEach(([n, v]) => { n.visible = v; });
    this.worldTarget?.dispose();
    this.worldTarget = world;
    this.worldBackground = dome ? world.texture : sky.background;
    this.probeTarget?.dispose();
    this.probeTarget = target;
    return target.texture;
  }

  // Rebuild these on the next sync even if the document says nothing changed.
  invalidate(pred) {
    for (const [id, o] of Object.entries(this.doc?.objects || {})) if (pred(id, o)) this.sigs.delete(id);
  }

  drop(id) {
    const node = this.nodes.get(id);
    if (!node) return;
    if (this.gizmo.object === node) this.gizmo.detach();
    if (this.edit?.group && this.edit.group.parent === node) node.remove(this.edit.group);   // the cage outlives its node
    for (const child of [...node.children]) if (child.userData.id && child.userData.pick) this.root.add(child);
    node.parent?.remove(node);
    node.traverse((n) => { if (n.geometry && !n.userData.shared) n.geometry.dispose(); });
    this.nodes.delete(id);
  }

  material(doc, mid) {
    if (this.shading === "solid") {
      return (this._solid ||= new THREE.MeshStandardMaterial({ color: 0xc8c8c8, roughness: 0.65, metalness: 0 }));
    }
    const m = mid ? doc.materials[mid] : null;
    if (!m) return (this._default ||= new THREE.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.5 }));
    const color = new THREE.Color(m.base_color);
    return new THREE.MeshPhysicalMaterial({
      color, metalness: m.metallic, roughness: m.roughness, clearcoat: m.coat, ior: m.ior,
      transmission: m.transmission, thickness: m.transmission ? 1 : 0,
      emissive: m.emission ? color : new THREE.Color(0), emissiveIntensity: m.emission,
      opacity: m.alpha, transparent: m.alpha < 1, side: THREE.DoubleSide,
    });
  }

  build(id, o, doc) {
    const node = new THREE.Group();
    node.userData = { id, pick: true };
    if (o.type === "mesh" || o.type === "text") {
      const ev = this.evaluated.get(id);
      let geom = ev ? ev.geometry : null;
      if (!geom && o.type === "mesh") {
        const m = doc.meshes[o.mesh];
        geom = m?.primitive ? primitiveGeometry(m) : this.hooks.explicitGeometry?.(o.mesh, m, o.shading) || null;
      }
      if (!geom) geom = new THREE.BoxGeometry(0.4, 0.4, 0.4);
      if (ev) geom.userData.shared = true;
      const mesh = geom.userData.line
        ? new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xdddddd }))
        : new THREE.Mesh(geom, this.material(doc, o.material));
      if (ev) mesh.userData.shared = true;
      node.add(mesh);
      node.userData.surface = mesh;
    } else if (o.type === "light") {
      node.add(this.buildLight(o.light));
    } else if (o.type === "camera") {
      node.add(cameraGizmo(o.camera));
    } else {
      node.add(new THREE.AxesHelper(0.6));
      node.add(pickProxy(0.3));
    }
    return node;
  }

  buildLight(l) {
    const g = new THREE.Group();
    const color = new THREE.Color(l.color);
    const show = this.shading === "material";
    let light;
    if (l.kind === "point") light = new THREE.PointLight(color, l.energy * LIGHT.point, 0, 2);
    else if (l.kind === "spot") {
      light = new THREE.SpotLight(color, l.energy * LIGHT.spot, 0, (l.spot_size / 2) * DEG, l.spot_blend, 2);
      light.position.set(0, 0, 0);
      light.target.position.set(0, 0, -1);
      g.add(light.target);
    } else if (l.kind === "sun") {
      light = new THREE.DirectionalLight(color, l.energy * LIGHT.sun);
      light.target.position.set(0, 0, -1);
      g.add(light.target);
    } else {
      const w = l.size, h = l.shape === "rectangle" || l.shape === "ellipse" ? l.size_y : l.size;
      light = new THREE.RectAreaLight(color, (l.energy / (w * h)) * LIGHT.area, w, h);
      light.rotation.set(0, 0, 0);          // RectAreaLight faces its -Z, as a Blender area light does
    }
    light.visible = show;
    g.add(light);
    // The lamp icon: a small sphere + a line along its facing, as Blender draws.
    const icon = new THREE.Mesh(new THREE.SphereGeometry(0.12, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffe08a }));
    g.add(icon);
    if (l.kind !== "point") {
      g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, -1.2)]),
                           new THREE.LineBasicMaterial({ color: 0xffe08a })));
    }
    return g;
  }

  // Blender-built display geometry for an object (after modifiers, or text).
  setEvaluated(id, key, data) {
    const prev = this.evaluated.get(id);
    if (prev?.key === key) return;
    prev?.geometry.dispose();
    this.evaluated.set(id, { key, geometry: bufferGeometry(data) });
    if (this.doc) this.sync(this.doc, this.selection, this.shading);
  }

  clearEvaluated(id) {
    const prev = this.evaluated.get(id);
    if (!prev) return;
    prev.geometry.dispose();
    this.evaluated.delete(id);
  }

  highlight() {
    for (const [id, node] of this.nodes) {
      const old = node.userData.outline;
      if (old) { node.remove(old); old.geometry.dispose(); node.userData.outline = null; }
      const i = this.selection.indexOf(id);
      if (i < 0 || this.edit?.id === id) continue;
      const surface = node.userData.surface;
      const color = i === this.selection.length - 1 ? ORANGE : ORANGE_DIM;
      let outline;
      if (surface?.isMesh) {
        outline = new THREE.LineSegments(new THREE.EdgesGeometry(surface.geometry, 30),
                                         new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.9 }));
      } else {
        outline = new THREE.BoxHelper(node, color);
        outline.matrixAutoUpdate = false;
      }
      outline.renderOrder = 10;
      node.add(outline);
      node.userData.outline = outline;
    }
    const active = this.selection[this.selection.length - 1];
    const node = active && this.nodes.get(active);
    if (this.edit) this.placePivot();
    else if (node && this.selection.length === 1) this.gizmo.attach(node);
    else this.gizmo.detach();
    this.touch();
  }

  // ─── edit mode ────────────────────────────────────────────────────────────
  // The edited object's own surface hides; a cage of its explicit mesh (surface,
  // wire, vertices, selected faces) takes its place as a child of its node, so the
  // object's transform applies. The app owns the mesh; this only shows it.

  enterEdit(id, mesh, sel, opts) {
    this.leaveEdit();
    this.edit = { id, mesh, sel, group: null };
    this.buildEdit(opts);
  }

  setEdit(mesh, sel, opts) {
    if (!this.edit) return;
    this.edit.mesh = mesh;
    this.edit.sel = sel;
    this.buildEdit(opts);
  }

  leaveEdit() {
    const e = this.edit;
    if (!e) return;
    this.disposeEdit();
    const node = this.nodes.get(e.id);
    if (node?.userData.surface) node.userData.surface.visible = true;
    this.edit = null;
    this.drag = null;
    if (this.gizmo.object === this.pivot) this.gizmo.detach();
    this.gizmo.setSpace("world");
    this.highlight();
  }

  disposeEdit() {
    const g = this.edit?.group;
    if (!g) return;
    g.parent?.remove(g);
    g.traverse((n) => { n.geometry?.dispose(); n.material?.dispose?.(); });
    this.edit.group = null;
  }

  attachEdit() {
    const e = this.edit, node = this.nodes.get(e.id);
    if (!node) { this.leaveEdit(); this.hooks.onEditLost?.(); return; }
    if (e.group && e.group.parent !== node) node.add(e.group);
    if (node.userData.surface) node.userData.surface.visible = false;
  }

  buildEdit({ keepPivot = false, normal = null } = {}) {
    const e = this.edit;
    this.disposeEdit();
    const m = e.mesh, sel = e.sel;
    const g = new THREE.Group();
    const d = displayBuffers(m);
    e.triFace = d.triFace;
    const surface = new THREE.Mesh(bufferGeometry(d), new THREE.MeshStandardMaterial({
      color: 0x9a9a9a, roughness: 0.7, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
    g.add(surface);
    e.surface = surface;

    const selV = new Set(selectedVerts(m, sel));
    const key = (a, b) => (a < b ? `${a},${b}` : `${b},${a}`);
    const selE = new Set(sel.mode === "edge" ? sel.items.map(([a, b]) => key(a, b)) : []);
    const selF = new Set(sel.mode === "face" ? sel.items : []);
    if (sel.mode === "face") for (const f of sel.items) (m.faces[f] || []).forEach((v, i, fv) => selE.add(key(v, fv[(i + 1) % fv.length])));
    const all = edges(m);
    e.edges = all;
    const lp = new Float32Array(all.length * 6), lc = new Float32Array(all.length * 6);
    const on = [1, 0.63, 0.16], off = [0, 0, 0];
    all.forEach(([a, b], i) => {
      lp.set([m.co[a * 3], m.co[a * 3 + 1], m.co[a * 3 + 2], m.co[b * 3], m.co[b * 3 + 1], m.co[b * 3 + 2]], i * 6);
      const lit = sel.mode === "vert" ? selV.has(a) && selV.has(b) : selE.has(key(a, b));
      const c = lit ? on : off;
      lc.set([...c, ...c], i * 6);
    });
    const wg = new THREE.BufferGeometry();
    wg.setAttribute("position", new THREE.BufferAttribute(lp, 3));
    wg.setAttribute("color", new THREE.BufferAttribute(lc, 3));
    g.add(new THREE.LineSegments(wg, new THREE.LineBasicMaterial({ vertexColors: true })));

    if (sel.mode === "vert") {
      const n = m.co.length / 3;
      const pc = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) pc.set(selV.has(i) ? on : off, i * 3);
      const pg = new THREE.BufferGeometry();
      pg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(m.co), 3));
      pg.setAttribute("color", new THREE.BufferAttribute(pc, 3));
      g.add(new THREE.Points(pg, new THREE.PointsMaterial({ size: 6, sizeAttenuation: false, vertexColors: true })));
    }
    if (selF.size) {
      const idx = [];
      d.triFace.forEach((f, t) => { if (selF.has(f)) idx.push(d.index[t * 3], d.index[t * 3 + 1], d.index[t * 3 + 2]); });
      const fg = new THREE.BufferGeometry();
      fg.setAttribute("position", new THREE.BufferAttribute(d.positions, 3));
      fg.setIndex(idx);
      g.add(new THREE.Mesh(fg, new THREE.MeshBasicMaterial({ color: ORANGE, transparent: true, opacity: 0.3, depthWrite: false,
        side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 })));
    }
    e.group = g;
    e.selVerts = [...selV];
    this.attachEdit();
    if (!keepPivot) { e.normal = normal; this.placePivot(); }
    this.touch();
  }

  // The gizmo at the selection's centre — along the edit's `normal` (world) right
  // after an extrude, so its blue arrow pulls the new faces out.
  placePivot() {
    const e = this.edit, node = e && this.nodes.get(e.id);
    if (this.drag) return;
    if (!node || !e.selVerts?.length) { if (this.gizmo.object === this.pivot) this.gizmo.detach(); return; }
    const normal = e.normal;
    node.updateWorldMatrix(true, false);
    this.pivot.position.fromArray(centroid(e.mesh, e.selVerts)).applyMatrix4(node.matrixWorld);
    this.pivot.scale.set(1, 1, 1);
    if (normal) {
      const n = new THREE.Vector3(...normal).transformDirection(node.matrixWorld);     // the object's space → world
      this.pivot.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
      this.gizmo.setSpace("local");
    } else {
      this.pivot.quaternion.identity();
      this.gizmo.setSpace("world");
    }
    this.pivot.updateMatrixWorld(true);
    if (this.gizmo.object !== this.pivot) this.gizmo.attach(this.pivot);
    this.touch();
  }

  editDragStart() {
    const e = this.edit;
    if (!e) return;
    this.pivot.updateMatrixWorld(true);
    this.drag = { start: this.pivot.matrixWorld.clone().invert(), mesh: e.mesh, verts: e.selVerts };
  }

  editDragMove() {
    const e = this.edit, node = e && this.nodes.get(e.id);
    if (!node || !this.drag) return;
    this.pivot.updateMatrixWorld(true);
    node.updateWorldMatrix(true, false);
    // local' = W⁻¹ · (pivot · pivot₀⁻¹) · W · local
    const W = node.matrixWorld;
    const L = W.clone().invert().multiply(this.pivot.matrixWorld.clone().multiply(this.drag.start)).multiply(W);
    const v = new THREE.Vector3();
    e.mesh = moveVerts(this.drag.mesh, this.drag.verts, (x, y, z) => v.set(x, y, z).applyMatrix4(L).toArray());
    this.buildEdit({ keepPivot: true });
  }

  editDragEnd() {
    const e = this.edit, d = this.drag;
    this.drag = null;
    if (!e || !d || e.mesh === d.mesh) return;
    this.hooks.onEditTransformEnd?.(e.mesh);
  }

  // The element under the pointer, in the edit selection mode: a vertex index, an
  // edge [a, b], a face index — or null. Hidden ones (behind the surface) don't count.
  pickElement(cx, cy) {
    const e = this.edit, node = e && this.nodes.get(e.id);
    if (!node || !e.surface) return null;
    node.updateWorldMatrix(true, true);
    const rect = this.renderer.domElement.getBoundingClientRect();
    const mx = cx - rect.left, my = cy - rect.top;
    const ray = new THREE.Raycaster();
    ray.setFromCamera({ x: (mx / rect.width) * 2 - 1, y: -(my / rect.height) * 2 + 1 }, this.camera);
    if (e.sel.mode === "face") {
      const hit = ray.intersectObject(e.surface, false)[0];
      return hit ? e.triFace[hit.faceIndex] : null;
    }
    const W = node.matrixWorld, cam = this.camera, m = e.mesh;
    const world = (i) => new THREE.Vector3(m.co[i * 3], m.co[i * 3 + 1], m.co[i * 3 + 2]).applyMatrix4(W);
    const screen = (p) => { const s = p.clone().project(cam); return [(s.x + 1) / 2 * rect.width, (1 - s.y) / 2 * rect.height, s.z]; };
    const seen = (p) => {
      const dir = p.clone().sub(cam.position), dist = dir.length();
      const r = new THREE.Raycaster(cam.position.clone(), dir.normalize());
      const hit = r.intersectObject(e.surface, false)[0];
      return !hit || hit.distance > dist - Math.max(1e-4, dist * 1e-3);
    };
    const near = [];
    if (e.sel.mode === "vert") {
      for (let i = 0; i < m.co.length / 3; i++) {
        const p = world(i), [sx, sy, sz] = screen(p);
        if (sz < -1 || sz > 1) continue;
        const d = Math.hypot(sx - mx, sy - my);
        if (d < 14) near.push({ d, p, item: i });
      }
    } else {
      for (const [a, b] of e.edges) {
        const pa = world(a), pb = world(b), A = screen(pa), B = screen(pb);
        if (A[2] < -1 || A[2] > 1 || B[2] < -1 || B[2] > 1) continue;
        const ex = B[0] - A[0], ey = B[1] - A[1], len2 = ex * ex + ey * ey || 1;
        const t = Math.min(1, Math.max(0, ((mx - A[0]) * ex + (my - A[1]) * ey) / len2));
        const d = Math.hypot(A[0] + t * ex - mx, A[1] + t * ey - my);
        if (d < 10) near.push({ d, p: pa.clone().lerp(pb, t), item: [a, b] });
      }
    }
    near.sort((x, y) => x.d - y.d);
    for (const n of near.slice(0, 12)) if (seen(n.p)) return n.item;
    return null;
  }

  setGizmoMode(mode) { this.gizmo.setMode(mode); this.touch(); }
  setGizmoAxes(axes) {
    this.gizmo.showX = axes.includes("x"); this.gizmo.showY = axes.includes("y"); this.gizmo.showZ = axes.includes("z");
    this.touch();
  }

  worldTRS(id) {
    const node = this.nodes.get(id);
    node.updateWorldMatrix(true, false);
    const p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3();
    node.matrixWorld.decompose(p, q, s);
    const e = new THREE.Euler().setFromQuaternion(q, "ZYX");
    return { location: p.toArray(), rotation: [e.x / DEG, e.y / DEG, e.z / DEG], scale: s.toArray() };
  }

  // ─── the view ─────────────────────────────────────────────────────────────

  view(name) {
    const t = this.orbit.target, d = this.camera.position.distanceTo(t);
    const dirs = { front: [0, -1, 0], back: [0, 1, 0], right: [1, 0, 0], left: [-1, 0, 0], top: [0, -0.0001, 1],
                   bottom: [0, -0.0001, -1] };
    this.camera.position.copy(t).add(new THREE.Vector3(...dirs[name]).normalize().multiplyScalar(d));
    this.orbit.update();
    this.touch();
  }

  frame(ids) {
    const box = new THREE.Box3();
    for (const id of ids.length ? ids : [...this.nodes.keys()]) {
      const n = this.nodes.get(id);
      if (n?.userData.surface) box.expandByObject(n.userData.surface);
      else if (n) box.expandByPoint(n.getWorldPosition(new THREE.Vector3()));
    }
    if (box.isEmpty()) return;
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const dir = this.camera.position.clone().sub(this.orbit.target).normalize();
    const fov = Math.min(this.camera.fov, this.camera.fov * this.camera.aspect) * DEG;
    const dist = Math.max(sphere.radius, 0.25) * 1.2 / Math.sin(fov / 2);
    this.orbit.target.copy(sphere.center);
    this.camera.position.copy(sphere.center).add(dir.multiplyScalar(dist));
    this.orbit.update();
    this.touch();
  }

  // Look through the scene's render camera (numpad 0).
  throughCamera(doc) {
    const id = doc.render.camera, node = id && this.nodes.get(id);
    if (!node || doc.objects[id]?.type !== "camera") return false;
    const c = doc.objects[id].camera, [w, h] = doc.render.resolution;
    node.updateWorldMatrix(true, false);
    const p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3();
    node.matrixWorld.decompose(p, q, s);
    this.camera.position.copy(p);
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(q);
    this.orbit.target.copy(p).add(fwd.multiplyScalar(5));
    this.orbit.update();
    if (this.through !== id) this.leaveCamera();
    this.through = id;
    // The render frame's half-extents one metre out; the sensor spans its longer side (AUTO fit).
    const t = c.sensor_width / 2 / c.lens;
    this.shot = w >= h ? { tw: t, th: t * h / w } : { tw: t * w / h, th: t };
    this.fitShot();
    node.children.forEach((c) => { c.visible = false; });     // don't draw the camera we're looking through
    this.touch();
    return true;
  }

  // In camera view the whole render frame fits the viewport, whatever its shape.
  fitShot() {
    if (!this.through || !this.shot) { this.frameEl.hidden = true; return; }
    const { tw, th } = this.shot, va = this.camera.aspect || 1;
    const fit = Math.max(th, tw / va) * 1.06;
    this.camera.fov = 2 * Math.atan(fit) / DEG;
    this.camera.updateProjectionMatrix();
    const fh = th / fit, fw = tw / va / fit;
    Object.assign(this.frameEl.style, { left: `${(1 - fw) * 50}%`, top: `${(1 - fh) * 50}%`,
                                        width: `${fw * 100}%`, height: `${fh * 100}%` });
    this.frameEl.hidden = false;
  }

  leaveCamera() {
    if (!this.through) return;
    const node = this.nodes.get(this.through);
    node?.children.forEach((c) => { c.visible = true; });
    this.through = null;
    this.frameEl.hidden = true;
    this.touch();
  }

  // Where the view is, as a camera the document can take ("camera to view").
  viewAsCamera() {
    const e = new THREE.Euler().setFromQuaternion(this.camera.quaternion, "ZYX");
    return { location: this.camera.position.toArray().map((v) => +v.toFixed(4)),
             rotation: [e.x / DEG, e.y / DEG, e.z / DEG].map((v) => +v.toFixed(3)) };
  }
}

function pickProxy(r) {
  const m = new THREE.Mesh(new THREE.SphereGeometry(r, 8, 6), new THREE.MeshBasicMaterial({ visible: false }));
  return m;
}

function cameraGizmo(c) {
  const d = 0.9, half = (c.sensor_width / 2 / c.lens) * d;
  const v = [new THREE.Vector3(0, 0, 0), new THREE.Vector3(-half, -half * 0.5625, -d),
             new THREE.Vector3(half, -half * 0.5625, -d), new THREE.Vector3(half, half * 0.5625, -d),
             new THREE.Vector3(-half, half * 0.5625, -d)];
  const pts = [v[0], v[1], v[0], v[2], v[0], v[3], v[0], v[4], v[1], v[2], v[2], v[3], v[3], v[4], v[4], v[1],
               v[3].clone().lerp(v[4], 0.5).add(new THREE.Vector3(0, 0.15, 0)), v[3], v[3].clone().lerp(v[4], 0.5).add(new THREE.Vector3(0, 0.15, 0)), v[4]];
  const g = new THREE.Group();
  g.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0x111111 })));
  g.add(pickProxy(0.35));
  return g;
}

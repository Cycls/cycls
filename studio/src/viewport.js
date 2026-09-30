// The 3D viewport: three.js in Blender's space (Z up, metres, Euler XYZ — which
// three.js reads as order 'ZYX'). It mirrors the scene document and reports what
// the user does back to the app; it never owns the document.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";
import { primitiveGeometry, bufferGeometry } from "./primitives.js";
import { deepEqual, isBackdrop, TEXTURE_FIELDS as TEXTURE_KEYS } from "./doc.js";
import { displayBuffers, edges, selectedVerts, centroid, moveVerts, edgeRing, proportionalWeights,
         moveVertsWeighted } from "./mesh.js";
import { diag } from "./diag.js";
import { WORLDS } from "./worlds.js";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
const DEG = Math.PI / 180;
const SNAP = 0.1;                                  // snapping's step for a move, in metres
const BATCH_MIN = 300;         // meshes in the scene before repeated ones draw instanced
const BIG_SCENE = 1000;        // objects past which glass draws as transparency (no transmission pass)
let PLACEHOLDER = null;                              // one stand-in for every mesh still loading
const placeholder = () => {
  if (!PLACEHOLDER) { PLACEHOLDER = new THREE.BoxGeometry(0.4, 0.4, 0.4); PLACEHOLDER.userData.shared = true; }
  return PLACEHOLDER;
};
const ORANGE = 0xffa028, ORANGE_DIM = 0xe56d1c;
const GREY = new THREE.Color("#3d3d3d");            // Solid shading's backdrop, as Blender's
// Blender watts → three's physical units, tuned by eye against Cycles renders.
const LIGHT = { point: 0.08, spot: 0.08, area: 0.35, sun: 1.0 };   // sun: both are irradiance (W/m²)

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

// The mean radiance (luminance) of a world HDRI, solid-angle weighted — how much light
// the sky sends, for weighing lamp shadows against it.
const worldMeans = new Map();
function worldMean(name) {
  if (!worldMeans.has(name)) {
    const bytes = Uint8Array.from(atob(WORLDS[name] || WORLDS.studio), (c) => c.charCodeAt(0));
    let sum = 0, wsum = 0;
    for (let y = 0; y < 32; y++) {
      const w = Math.cos(((y + 0.5) / 32 - 0.5) * Math.PI);
      for (let x = 0; x < 64; x++) {
        const i = (y * 64 + x) * 4, f = bytes[i + 3] ? 2 ** (bytes[i + 3] - 136) : 0;
        sum += w * f * (0.2126 * (bytes[i] + 0.5) + 0.7152 * (bytes[i + 1] + 0.5) + 0.0722 * (bytes[i + 2] + 0.5));
        wsum += w;
      }
    }
    worldMeans.set(name, sum / wsum);
  }
  return worldMeans.get(name);
}

// The world as Cycles sees it: the HDRI in Blender's equirectangular mapping, in
// Blender's (Z-up) space, turned by the world's rotation, times its strength.
function skyDome(w) {
  // A flat colour world is a dome too: three's own solid-colour background is a unit box at
  // the origin, which a probe baked anywhere else sees from outside.
  if (w.kind === "color") {
    const dome = new THREE.Mesh(new THREE.SphereGeometry(500, 16, 8), new THREE.MeshBasicMaterial({
      color: new THREE.Color(w.color).multiplyScalar(w.strength ?? 1), side: THREE.BackSide,
      depthWrite: false, toneMapped: false }));
    dome.frustumCulled = false;
    dome.renderOrder = -1;
    return dome;
  }
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
    this.evalGeoms = new Map();      // evaluate key -> { geometry, users }: identical results share one
    this.matCache = new Map();       // material signature -> material, shared by every object using it
    this.primCache = new Map();      // primitive parameters -> geometry
    this.batches = new Map();        // geometry+materials -> { mesh: InstancedMesh }
    this.selection = [];
    this.shading = "material";
    this.dirty = true;

    const r = (this.renderer = new THREE.WebGLRenderer({ antialias: true }));
    r.setPixelRatio(Math.min(devicePixelRatio, 2));
    r.toneMapping = THREE.NeutralToneMapping;        // Khronos PBR Neutral, as the engine renders
    // Shadows: re-rendered only when the scene changes (they don't depend on the view).
    this.shadows = !matchMedia?.("(pointer: coarse)")?.matches;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.VSMShadowMap;           // blurs wide: studio softboxes cast very soft shadows
    r.shadowMap.autoUpdate = false;
    r.domElement.tabIndex = 0;
    r.domElement.className = "viewport-canvas";
    host.appendChild(r.domElement);
    // Edit tools draw on top: the knife's path, the proportional circle.
    this.overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    this.overlay.setAttribute("class", "tool-overlay");
    host.appendChild(this.overlay);
    this.tool = null;                          // { kind: "loopcut", cuts, edge } | { kind: "knife", points: [[x, y]] }
    this.proportional = { on: false, radius: 1, falloff: "smooth" };
    this.snap = { on: false, target: "increment" };        // increment | vertex | surface
    this.ctrl = false;
    addEventListener("keydown", (e) => { if (e.key === "Control") { this.ctrl = true; this.applySnap(); } });
    addEventListener("keyup", (e) => { if (e.key === "Control") { this.ctrl = false; this.applySnap(); } });
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
    this.batchRoot = new THREE.Group();          // instanced draws of repeated objects (world-space matrices)
    scene.add(this.batchRoot);

    const cam = (this.camera = new THREE.PerspectiveCamera(39.6, 1, 0.05, 2000));
    cam.position.set(7.36, -6.93, 4.96);
    this.orbit = new OrbitControls(cam, r.domElement);
    this.orbit.target.set(0, 0, 1);
    this.orbit.screenSpacePanning = true;
    // A wheel notch zooms ~1.17x, near Blender's 1.2x (three's default 1.05x took ~90 notches to
    // get 100x closer — a crawl across a site-sized scene).
    this.orbit.zoomSpeed = 3;
    this.orbit.update();
    // Orbiting leaves the camera view — but only once the view moves: a plain click
    // starts an orbit too, and must not put the camera's own lines at the eye.
    this.orbit.addEventListener("change", () => { this.fitDepth(); this.touch(); if (this.orbiting) this.leaveCamera(); });
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
      const o = gizmo.object;
      this.moveStart = e.value && o ? this.dragStart(o) : null;
      if (!e.value) this.drawSnap(null);
      if (gizmo.object === this.pivot) { e.value ? this.editDragStart() : this.editDragEnd(); return; }
      if (!e.value && gizmo.object) this.hooks.onTransformEnd?.(gizmo.object.userData.id, trsOf(gizmo.object));
    });
    gizmo.addEventListener("objectChange", () => {
      this.shadowsDirty = true;
      if (gizmo.object) this.snapMove(gizmo.object);
      if (gizmo.object === this.pivot) { this.editDragMove(); return; }
      if (gizmo.object) this.hooks.onTransform?.(gizmo.object.userData.id, trsOf(gizmo.object));
    });

    // Click selects; a drag orbits. Shift adds to the selection.
    const ray = new THREE.Raycaster();
    ray.params.Line.threshold = 0.05;
    let down = null;
    r.domElement.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; r.domElement.focus(); });
    // Hover, for the loop cut's preview — once a frame at most. The pointer, for snapping and
    // the bisect's line.
    let hoverAt = null;
    r.domElement.addEventListener("pointermove", (e) => {
      this.pointer = [e.clientX, e.clientY];
      if (this.tool?.kind === "bisect" && this.tool.points.length === 1) { this.tool.cursor = this.pointer; this.drawBisect(); return; }
      if (!this.tool || this.tool.kind !== "loopcut" || gizmo.dragging) return;
      if (!hoverAt) requestAnimationFrame(() => { const [x, y] = hoverAt; hoverAt = null; this.hoverLoopCut(x, y); });
      hoverAt = [e.clientX, e.clientY];
    });
    // The wheel: more/fewer cuts while a loop cut hovers; a bigger/smaller proportional
    // radius while a drag is on (orbit is off then, so it doesn't zoom).
    r.domElement.addEventListener("wheel", (e) => {
      if (this.tool?.kind === "loopcut") {
        e.preventDefault(); e.stopImmediatePropagation();
        this.tool.cuts = Math.max(1, Math.min(32, this.tool.cuts + (e.deltaY < 0 ? 1 : -1)));
        this.drawLoopCut();
        this.hooks.onToolChange?.(this.tool);
      } else if (this.drag?.weights && this.proportional.on) {
        e.preventDefault(); e.stopImmediatePropagation();
        this.proportional.radius = Math.max(0.01, this.proportional.radius * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
        this.drag.weights = proportionalWeights(this.drag.world, this.drag.verts, this.proportional.radius, this.proportional.falloff);
        this.editDragMove();
        this.hooks.onToolChange?.({ kind: "proportional", radius: this.proportional.radius });
      }
    }, { capture: true, passive: false });
    r.domElement.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || gizmo.dragging || e.button !== 0) return;
      if (this.edit && this.tool) { this.toolClick(e.clientX, e.clientY); return; }
      if (this.edit) { this.hooks.onEditPick?.(this.pickElement(e.clientX, e.clientY), e.shiftKey); return; }
      const rect = r.domElement.getBoundingClientRect();
      ray.setFromCamera({ x: ((e.clientX - rect.left) / rect.width) * 2 - 1,
                          y: -((e.clientY - rect.top) / rect.height) * 2 + 1 }, cam);
      // Looking through a camera puts its own gizmo at the eye; it must not win every click.
      const hit = ray.intersectObjects(this.root.children, true)
        .find((h) => this.idOf(h.object) && this.pickable(h.object) && this.idOf(h.object) !== this.through);
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
      if (this.shadowsDirty) { r.shadowMap.needsUpdate = true; this.shadowsDirty = false; }
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
    // three keeps the gizmo a fixed share of the view's height; keep it ~95 px instead,
    // so it stays grabbable in the chat's narrow canvas.
    this.gizmo.setSize(Math.min(2.2, Math.max(0.9, 780 / Math.max(1, h))));
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
      const sig = { o: { ...o, location: 0, rotation: 0, scale: 0, parent: 0, keys: 0 },
                    m: o.mesh ? doc.meshes[o.mesh] : null, mat: (o.materials || []).map((mid) => mid && doc.materials[mid]),
                    ev: this.evaluated.get(id)?.key ?? null };
      if (!this.nodes.has(id) || !deepEqual(this.sigs.get(id), sig)) {
        this.drop(id);
        this.nodes.set(id, this.build(id, o, doc));
        this.sigs.set(id, sig);
      } else if (shadingChanged) {
        // Solid ↔ Material is a change of materials (shared, cached), not of objects: a scene
        // of thousands rebuilt every node on each switch.
        const surface = this.nodes.get(id).userData.surface;
        if (surface?.isMesh) surface.material = this.slotMaterials(doc, o, surface.geometry);
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
    this.findMovers(doc);
    if (this.edit) this.attachEdit();
    this.rebatch(doc);
    if (this.through && !this.throughCamera(doc)) this.leaveCamera();      // camera view follows the camera
    this.scene.environment = shading === "material" ? this.probe(doc) : null;
    this.scene.background = shading === "material" ? this.worldBackground : GREY;      // the world, as it renders
    this.shadowRig(doc);
    this.highlight();
    this.touch();
  }

  // What an animation moves: keyed objects, and everything they carry. They're never drawn
  // batched (a batch's matrices are baked), and playback touches only them.
  findMovers(doc) {
    this.animatedIds = Object.keys(doc.objects).filter((id) => doc.objects[id].keys);
    const movers = new Set(this.animatedIds);
    if (movers.size) {
      for (const id of Object.keys(doc.objects)) {
        for (let p = doc.objects[id].parent, n = 0; p && n < 64; p = doc.objects[p]?.parent, n++) {
          if (movers.has(p)) { movers.add(id); break; }
        }
      }
    }
    this.movers = movers;
  }

  // Playback and scrubbing: the keyed objects' transforms at this frame, nothing rebuilt and
  // nothing re-baked (the probe and the lamp rig wait for the next full sync); the shadow maps
  // redraw, and the camera view rides an animated camera.
  pose(doc) {
    this.doc = doc;
    for (const id of this.animatedIds || []) {
      const node = this.nodes.get(id), o = doc.objects[id];
      if (node && o && !(this.gizmo.dragging && this.gizmo.object === node)) applyTRS(node, o);
    }
    this.shadowsDirty = true;
    if (this.through && this.movers?.has(this.through)) this.throughCamera(doc);
    if (this.edit && this.movers?.has(this.edit.id)) this.placePivot();
    this.touch();
  }

  // Flat and wide — a floor, a site's terrain, a backdrop sheet: set dressing to stand
  // things on, not a subject to frame or light for (scene.py _is_ground).
  isGround(id) {
    const s = this.nodes.get(id)?.userData.surface;
    if (!s?.geometry) return false;
    if (!s.geometry.boundingBox) s.geometry.computeBoundingBox();
    s.updateWorldMatrix(true, false);
    const size = s.geometry.boundingBox.clone().applyMatrix4(s.matrixWorld).getSize(new THREE.Vector3());
    return size.z < 0.03 * Math.max(size.x, size.y, 1e-9);
  }

  // Where the subjects are: visible meshes and text that aren't the set or the ground.
  subjectBox(doc) {
    const box = new THREE.Box3();
    for (const [id, node] of this.nodes) {
      const o = doc.objects[id];
      if ((o.type === "mesh" || o.type === "text") && o.visible && !isBackdrop(doc, id) && node.userData.surface
          && !this.isGround(id)) {
        box.expandByObject(node.userData.surface);
      }
    }
    return box;
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
      else if (isBackdrop(doc, id)) set.push([id, at, doc.meshes[o.mesh], (o.materials || []).map((mid) => mid && doc.materials[mid])]);
    }
    this.scene.updateMatrixWorld();
    const box = this.subjectBox(doc);
    const at = box.isEmpty() ? new THREE.Vector3(0, 0, 1) : box.getCenter(new THREE.Vector3());
    const key = JSON.stringify([w, set, lamps, at.toArray().map((v) => v.toFixed(1))]);
    if (key === this.probeKey) return this.probeTarget.texture;
    this.probeKey = key;

    // The world alone first: it lights the set, then the set and the world light the subjects.
    const sky = new THREE.Scene(), dome = skyDome(w);
    sky.background = new THREE.Color(0);
    sky.add(dome);
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
    s.add(dome);
    const target = this.pmrem.fromScene(s, 0, 0.1, 1000, { position: at });
    s.remove(dome);
    dome.geometry.dispose();
    dome.material.dispose();
    [s.background, s.environment] = [bg, env];
    saved.reverse().forEach(([n, v]) => { n.visible = v; });
    this.worldTarget?.dispose();
    this.worldTarget = world;
    this.worldBackground = w.kind === "color" ? new THREE.Color(w.color).multiplyScalar(w.strength ?? 1) : world.texture;
    this.probeTarget?.dispose();
    this.probeTarget = target;
    return target.texture;
  }

  // Shadows that match the render: each lamp gets a proxy that only casts (no light —
  // three can't shadow the area lamps the studio rigs use), aimed at the subjects, whose
  // shadow strength is that lamp's share of the light reaching them (the world's share
  // counted too). The floor/sweep's catcher darkens by all of them together.
  shadowRig(doc) {
    const on = this.shadows && this.shading === "material";
    this.scene.updateMatrixWorld();
    const box = this.subjectBox(doc);
    const lamps = on && !box.isEmpty() ? Object.entries(doc.objects).filter(([, o]) => o.type === "light" && o.visible) : [];
    const sphere = box.isEmpty() ? new THREE.Sphere(new THREE.Vector3(0, 0, 1), 1) : box.getBoundingSphere(new THREE.Sphere());
    const key = JSON.stringify([on, lamps.map(([id, o]) => [id, o.light, ...this.nodes.get(id).matrixWorld.elements.map((v) => +v.toFixed(3))]),
                                sphere.center.toArray().map((v) => +v.toFixed(2)), +sphere.radius.toFixed(2), doc.world]);
    this.shadowsDirty = true;
    if (key === this.rigKey) return;
    this.rigKey = key;
    if (this.rig) { this.scene.remove(this.rig); this.rig.traverse((n) => n.shadow?.dispose?.()); }
    this.rig = new THREE.Group();
    this.scene.add(this.rig);
    if (!lamps.length) return;

    const c = sphere.center, R = Math.max(sphere.radius, 0.05);
    const pos = new THREE.Vector3(), quat = new THREE.Quaternion(), scl = new THREE.Vector3();
    const reach = lamps.map(([id, o]) => {                     // irradiance at the subjects, in viewport units
      this.nodes.get(id).matrixWorld.decompose(pos, quat, scl);
      const l = o.light, d = Math.max(pos.distanceTo(c), 1e-3);
      const facing = new THREE.Vector3(0, 0, -1).applyQuaternion(quat);
      const toward = c.clone().sub(pos).normalize();
      const cos = Math.max(0, facing.dot(toward));
      const e = l.kind === "sun" ? l.energy * LIGHT.sun
        : l.kind === "area" ? l.energy * LIGHT.area * cos / (d * d)
        : l.kind === "spot" ? l.energy * LIGHT.spot / (d * d) * (Math.acos(cos) <= (l.spot_size / 2) * DEG ? 1 : 0)
        : l.energy * LIGHT.point / (d * d);
      return { id, l, pos: pos.clone(), dir: l.kind === "sun" ? facing.clone() : toward, d, e };
    });
    const w = doc.world || {};
    const lum = (hex) => { const k = new THREE.Color(hex); return 0.2126 * k.r + 0.7152 * k.g + 0.0722 * k.b; };
    const sky = (w.strength ?? 0.35) * Math.PI * (w.kind === "color" ? lum(w.color) : worldMean(w.hdri) * 0.5);
    // Light the set bounces back into the shadows (Cycles has it; a white sweep fills them,
    // a black one doesn't): the lamps' light times the set's reflectance.
    const direct = reach.reduce((a, r) => a + r.e, 0);
    const setAlbedo = Math.max(0, ...Object.entries(doc.objects).filter(([id, o]) => isBackdrop(doc, id) && o.type === "mesh")
      .map(([, o]) => { const m = doc.materials[(o.materials || [])[0]]; return m ? lum(m.base_color) : 0.6; }));
    const total = direct * (1 + 1.4 * setAlbedo) + sky;
    for (const r of reach) {
      const share = total > 0 ? r.e / total : 0;
      if (share < 0.02) continue;
      // Softness: the penumbra the lamp's size throws at the floor (an occluder ~R up),
      // as a share of what the shadow map covers, in texels.
      let light, spread, frustum;
      if (r.l.kind === "sun") {
        light = new THREE.DirectionalLight(0xffffff, 0);
        light.position.copy(c).addScaledVector(r.dir, -R * 4);
        const cam = light.shadow.camera;
        cam.left = cam.bottom = -R * 1.6; cam.right = cam.top = R * 1.6;
        cam.near = R * 0.5; cam.far = R * 8 + 50;
        spread = Math.tan(((r.l.angle ?? 0.5) * DEG) / 2) * 2 * R;
        frustum = R * 3.2;
      } else {
        light = new THREE.SpotLight(0xffffff, 0);
        light.position.copy(r.pos);
        light.angle = Math.min(Math.PI / 2.2, Math.atan((R * 1.5) / r.d) * 1.3 + 0.05);
        light.penumbra = 0;
        light.shadow.camera.near = Math.max(0.02, r.d - R * 2);
        light.shadow.camera.far = r.d + R * 30 + 20;
        const size = r.l.kind === "area" ? Math.max(r.l.size, r.l.size_y || 0) : (r.l.radius ?? 0.1) * 2;
        spread = size * R / Math.max(r.d - R, R * 0.5);
        frustum = 2 * r.d * Math.tan(light.angle);
      }
      const soft = 0.6 * spread / frustum;                    // penumbra as a share of the map (VSM blurs wide)
      const res = soft > 0.04 ? 256 : soft > 0.012 ? 512 : 1024;
      light.shadow.mapSize.set(res, res);
      light.shadow.radius = Math.max(1.5, Math.min(24, soft * res));
      light.shadow.blurSamples = 16;
      light.target.position.copy(c);
      light.castShadow = true;
      light.shadow.intensity = Math.min(1, share * 0.75);     // a blurred map over-darkens beside things
      light.shadow.bias = -0.0005;
      this.rig.add(light, light.target);
    }
    // Contact: right under a thing the floor sees less of the sky and of every big
    // softbox — the dark, tight patch a uniform blur loses. A soft shadow cast straight down.
    const contact = new THREE.DirectionalLight(0xffffff, 0);
    contact.position.set(c.x, c.y, c.z + R * 4);
    contact.target.position.copy(c);
    const cam = contact.shadow.camera;
    cam.left = cam.bottom = -R * 1.6; cam.right = cam.top = R * 1.6;
    cam.near = R * 0.5; cam.far = R * 8 + 50;
    contact.castShadow = true;
    contact.shadow.mapSize.set(256, 256);
    contact.shadow.radius = 10;
    contact.shadow.blurSamples = 16;
    contact.shadow.intensity = Math.min(0.8, 0.2 + sky / Math.max(total, 1e-6) + 0.55 * (1 - setAlbedo));
    contact.shadow.bias = -0.0005;
    this.rig.add(contact, contact.target);
  }

  setShadows(on) {
    this.shadows = on;
    this.rigKey = null;
    if (this.doc) this.sync(this.doc, this.selection, this.shading);
  }

  // Rebuild these on the next sync even if the document says nothing changed.
  invalidate(pred) {
    for (const [id, o] of Object.entries(this.doc?.objects || {})) if (pred(id, o)) this.sigs.delete(id);
  }

  drop(id) {
    const node = this.nodes.get(id);
    if (!node) return;
    const mats = node.userData.surface?.material;
    for (const mat of Array.isArray(mats) ? mats : [mats]) {
      if (!mat?.userData.owned) continue;          // its own placement of any images, and itself
      for (const k of ["map", "roughnessMap", "normalMap"]) mat[k]?.dispose();
      mat.dispose();
    }
    if (this.gizmo.object === node) this.gizmo.detach();
    if (this.edit?.group && this.edit.group.parent === node) node.remove(this.edit.group);   // the cage outlives its node
    for (const child of [...node.children]) if (child.userData.id && child.userData.pick) this.root.add(child);
    node.parent?.remove(node);
    node.traverse((n) => { if (n.geometry && !n.userData.shared && !n.geometry.userData.shared) n.geometry.dispose(); });
    this.nodes.delete(id);
  }

  material(doc, mid) {
    if (this.shading === "solid") {
      return (this._solid ||= new THREE.MeshStandardMaterial({ color: 0xc8c8c8, roughness: 0.65, metalness: 0 }));
    }
    const m = mid ? doc.materials[mid] : null;
    if (!m) return (this._default ||= new THREE.MeshStandardMaterial({ color: 0xcccccc, roughness: 0.5 }));
    // One per material (and per image that has arrived for it), shared by every object using
    // it — a venue of 5,000 objects has a hundred materials, not 11,000 copies of them.
    const ready = TEXTURE_KEYS.map((f, i) => {
      const t = doc.textures?.[m[f]];
      return t ? (this.images?.get(`${t.data}|${["color", "rough", "normal"][i]}`)?.texture ? 2 : 1) : 0;
    }).join("");
    // Glass (transmission) makes three draw the whole scene again for what's behind it, every
    // frame; past BIG_SCENE objects it draws as plain transparency instead.
    const cheapGlass = m.transmission > 0 && Object.keys(doc.objects).length > BIG_SCENE;
    const sig = `${mid}|${ready}|${cheapGlass}|${JSON.stringify(m)}`;
    const hit = this.matCache.get(sig);
    if (hit) return hit;
    if (this.matCache.size > 2000) this.matCache.clear();      // edits leave old ones; the objects holding them keep them
    const color = new THREE.Color(m.base_color);
    const maps = this.maps(doc, m);
    const cutout = !!(maps.map && doc.textures[m.base_color_texture]?.alpha);
    const mat = new THREE.MeshPhysicalMaterial({
      color: maps.map ? new THREE.Color(1, 1, 1) : color,       // a linked Base Color replaces the value, as in Blender
      metalness: m.metallic, roughness: maps.roughnessMap ? 1 : m.roughness, clearcoat: m.coat, ior: m.ior,
      transmission: cheapGlass ? 0 : m.transmission, thickness: m.transmission && !cheapGlass ? 1 : 0,
      emissive: m.emission ? color : new THREE.Color(0), emissiveIntensity: m.emission,
      opacity: cheapGlass ? m.alpha * (1 - 0.7 * m.transmission) : m.alpha,
      transparent: m.alpha < 1 || cutout || cheapGlass, depthWrite: !cheapGlass, side: THREE.DoubleSide, ...maps,
    });
    if (maps.normalMap) mat.normalScale.set(m.normal_strength, m.normal_strength);
    this.matCache.set(sig, mat);
    return mat;
  }

  // An object's material for its geometry: one, or one per slot when the geometry is in
  // slot groups (a face past the last slot uses the last, as in Blender).
  slotMaterials(doc, o, geom) {
    const slots = o.materials || [];
    const n = geom.userData.slots || 1;
    if (this.shading === "solid" || n <= 1 || slots.length <= 1) return this.material(doc, slots[0] || null);
    return Array.from({ length: n }, (_, i) => this.material(doc, slots[Math.min(i, slots.length - 1)] || null));
  }

  // A material's images as three textures, placed as Blender's Mapping node places them
  // (uv' = offset + rotate · (scale · uv)). Images load once per file; each material gets
  // its own view of one (its placement), sharing the pixels. Until an image arrives the
  // material draws without it, then the objects using it rebuild.
  maps(doc, m) {
    const out = {};
    const place = (tex) => {
      const t = tex.clone();
      const [sx, sy] = m.texture_scale, [tx, ty] = m.texture_offset, a = m.texture_rotation * DEG;
      const c = Math.cos(a), s = Math.sin(a);
      t.matrixAutoUpdate = false;
      t.matrix.set(c * sx, -s * sy, tx, s * sx, c * sy, ty, 0, 0, 1);
      t.needsUpdate = true;
      return t;
    };
    for (const [field, slot, role] of [["base_color_texture", "map", "color"], ["roughness_texture", "roughnessMap", "rough"],
                                       ["normal_texture", "normalMap", "normal"]]) {
      const tex = doc.textures?.[m[field]];
      if (!tex) continue;
      const base = this.image(m[field], tex.data, role);
      if (base) out[slot] = place(base);
    }
    return out;
  }

  image(tid, rel, role) {
    this.images ||= new Map();
    const key = `${rel}|${role}`;
    const hit = this.images.get(key);
    if (hit) return hit.texture;
    const entry = { texture: null };
    this.images.set(key, entry);
    this.hooks.loadTexture?.(rel).then(async (side) => {
      const bytes = Uint8Array.from(atob(side.data), (ch) => ch.charCodeAt(0));
      // Blender's UV v=0 is the image's bottom row; an ImageBitmap ignores flipY, so flip here.
      const bmp = await createImageBitmap(new Blob([bytes], { type: side.media_type }),
                                          { imageOrientation: "flipY", premultiplyAlpha: "none", colorSpaceConversion: "none" });
      let t;
      if (role === "rough") {
        // three reads roughness from green; Blender reads a colour image as its luminance.
        const cv = new OffscreenCanvas(bmp.width, bmp.height), cx = cv.getContext("2d");
        cx.drawImage(bmp, 0, 0);
        const img = cx.getImageData(0, 0, bmp.width, bmp.height), d = img.data;
        for (let i = 0; i < d.length; i += 4) { const l = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]; d[i] = d[i + 1] = d[i + 2] = l; }
        t = new THREE.DataTexture(d, bmp.width, bmp.height);
        t.flipY = false;
      } else {
        t = new THREE.Texture(bmp);
      }
      t.colorSpace = role === "color" ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.anisotropy = 4;
      t.needsUpdate = true;
      entry.texture = t;
      this.invalidate((id, o) => (o.materials || []).some((mid) => mid && TEXTURE_KEYS.some((f) => this.doc.materials[mid]?.[f] === tid)));
      if (this.doc) this.sync(this.doc, this.selection, this.shading);
    }).catch((e) => { this.images.delete(key); console.warn("texture", rel, e); });
    return null;
  }

  build(id, o, doc) {
    const node = new THREE.Group();
    node.userData = { id, pick: true };
    if (o.type === "mesh" || o.type === "text") {
      const ev = this.evaluated.get(id);
      let geom = ev ? ev.geometry : null;
      if (!geom && o.type === "mesh") {
        const m = doc.meshes[o.mesh];
        geom = m?.primitive ? this.primitive(m) : this.hooks.explicitGeometry?.(o.mesh, m, o.shading) || null;
      }
      if (!geom) geom = placeholder();                       // until its mesh file arrives
      if (ev) geom.userData.shared = true;
      const mesh = geom.userData.line
        ? new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xdddddd }))
        : new THREE.Mesh(geom, this.slotMaterials(doc, o, geom));
      if (ev) mesh.userData.shared = true;
      node.add(mesh);
      node.userData.surface = mesh;
      if (!mesh.isLine) {
        if (isBackdrop(doc, id)) {
          // The floor/sweep catches shadows on a copy that only darkens (ShadowMaterial):
          // the lamps' light on it stays what it is.
          const catcher = new THREE.Mesh(geom, new THREE.ShadowMaterial({ transparent: true, depthWrite: false,
            polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 }));
          catcher.receiveShadow = true;
          catcher.renderOrder = 1;
          catcher.userData = { shared: true, catcher: true };
          catcher.raycast = () => {};
          node.add(catcher);
        } else {
          mesh.castShadow = true;
        }
      }
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
  // Blender's shape for an object; the caller syncs once for the whole batch (a sync per
  // object is a sync per object of every object).
  setEvaluated(id, key, data) {
    const prev = this.evaluated.get(id);
    if (prev?.key === key) return;
    if (prev) this.releaseEvaluated(id, prev.key);
    let g = this.evalGeoms.get(key);                 // the same object shape, evaluated for another id
    if (!g) this.evalGeoms.set(key, g = { geometry: bufferGeometry(data), users: new Set() });
    g.users.add(id);
    this.evaluated.set(id, { key, geometry: g.geometry });
    this.shadowsDirty = true;
  }

  releaseEvaluated(id, key) {
    const g = this.evalGeoms.get(key);
    if (!g) return;
    g.users.delete(id);
    if (!g.users.size) { g.geometry.dispose(); this.evalGeoms.delete(key); }
  }

  clearEvaluated(id) {
    const prev = this.evaluated.get(id);
    if (!prev) return;
    this.releaseEvaluated(id, prev.key);
    this.evaluated.delete(id);
  }

  primitive(m) {
    const key = JSON.stringify(m);
    let g = this.primCache.get(key);
    if (!g) {
      if (this.primCache.size > 500) this.primCache.clear();     // old ones stay with the objects holding them
      this.primCache.set(key, g = primitiveGeometry(m));
      g.userData.shared = true;
    }
    return g;
  }

  // Drawn — or drawn by its batch — and not inside something hidden.
  pickable(obj) {
    if (!obj.visible && !obj.userData.batched) return false;
    for (let n = obj.parent; n && n !== this.root; n = n.parent) if (!n.visible) return false;
    return true;
  }

  // A big scene repeats itself: a venue's 1,079 seats are one mesh and one material. Objects
  // sharing geometry and materials draw as one InstancedMesh — one draw call, not one per
  // object (the browser's cost is per call, not per triangle). What's selected, edited, hidden
  // or see-through draws on its own; picking still hits each object's own (hidden) mesh.
  rebatch(doc) {
    const surfaces = [];
    for (const [id, node] of this.nodes) {
      const s = node.userData.surface;
      if (s?.isMesh) surfaces.push([id, node, s]);
    }
    const on = surfaces.length >= BATCH_MIN;
    const sel = new Set(this.selection), groups = new Map();
    if (on) this.root.updateMatrixWorld(true);
    for (const [id, node, s] of surfaces) {
      if (this.edit?.id === id) continue;                      // Edit mode shows the cage instead
      s.userData.batched = false;
      const mats = [].concat(s.material);
      if (!on || sel.has(id) || !doc.objects[id] || this.movers?.has(id) || isBackdrop(doc, id) || !this.pickable(node)
          || mats.some((m) => m.transparent || m.transmission > 0)) { s.visible = true; continue; }
      const key = `${s.geometry.uuid}|${mats.map((m) => m.uuid).join(",")}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(s);
    }
    const next = new Map();
    for (const [key, members] of groups) {
      if (members.length < 2) { members[0].visible = true; continue; }
      let b = this.batches.get(key);
      this.batches.delete(key);
      if (b && b.mesh.instanceMatrix.count < members.length) { this.batchRoot.remove(b.mesh); b.mesh.dispose(); b = null; }
      if (!b) {
        const mesh = new THREE.InstancedMesh(members[0].geometry, members[0].material, members.length);
        mesh.castShadow = true;
        mesh.raycast = () => {};                                  // clicks go to the objects themselves
        this.batchRoot.add(mesh);
        b = { mesh };
      }
      b.mesh.count = members.length;
      members.forEach((s, i) => { b.mesh.setMatrixAt(i, s.matrixWorld); s.visible = false; s.userData.batched = true; });
      b.mesh.instanceMatrix.needsUpdate = true;
      b.mesh.computeBoundingSphere();
      next.set(key, b);
    }
    for (const b of this.batches.values()) { this.batchRoot.remove(b.mesh); b.mesh.dispose(); }   // geometry, materials: shared
    this.batches = next;
    diag.batches = next.size;
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
    this.setTool(null);
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
    if (this.proportional.on) {
      const node = this.nodes.get(e.id), W = node.matrixWorld, v = new THREE.Vector3(), co = e.mesh.co;
      const world = new Float32Array(co.length);
      for (let i = 0; i < co.length; i += 3) v.set(co[i], co[i + 1], co[i + 2]).applyMatrix4(W).toArray(world, i);
      this.drag.world = world;
      this.drag.weights = proportionalWeights(world, e.selVerts, this.proportional.radius, this.proportional.falloff);
    }
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
    const fn = (x, y, z) => v.set(x, y, z).applyMatrix4(L).toArray();
    e.mesh = this.drag.weights ? moveVertsWeighted(this.drag.mesh, this.drag.weights, fn)
      : moveVerts(this.drag.mesh, this.drag.verts, fn);
    this.buildEdit({ keepPivot: true });
    this.drawProportional();
  }

  editDragEnd() {
    const e = this.edit, d = this.drag;
    this.drag = null;
    this.drawProportional();
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

  // ─── edit tools ───────────────────────────────────────────────────────────

  toScreen(p) {
    const rect = this.renderer.domElement.getBoundingClientRect(), s = p.clone().project(this.camera);
    return [(s.x + 1) / 2 * rect.width, (1 - s.y) / 2 * rect.height, s.z];
  }

  setTool(tool) {
    this.tool = tool;
    this.drawTool();
  }

  drawTool() {
    if (this.tool?.kind === "loopcut") this.drawLoopCut();
    else if (this.tool?.kind === "knife") this.drawKnife();
    else if (this.tool?.kind === "bisect") this.drawBisect();
    else this.overlay.innerHTML = "";
    this.drawProportional();
  }

  // The bisect's line: from the first click to the pointer, then to the second click.
  drawBisect() {
    const t = this.tool, rect = this.renderer.domElement.getBoundingClientRect();
    const pts = [...(t?.points || []), ...(t?.points?.length === 1 && t.cursor ? [t.cursor] : [])];
    this.overlay.innerHTML = pts.map(([x, y]) => `<circle class="knife-dot" cx="${x - rect.left}" cy="${y - rect.top}" r="3.5"/>`).join("")
      + (pts.length === 2 ? `<line class="knife bisect" x1="${pts[0][0] - rect.left}" y1="${pts[0][1] - rect.top}" x2="${pts[1][0] - rect.left}" y2="${pts[1][1] - rect.top}"/>` : "");
  }

  // The plane through the eye and a line drawn on the screen, in the edited object's own
  // space, its normal pointing to the line's left as drawn — Blender's bisect.
  bisectPlane(points) {
    const e = this.edit, node = e && this.nodes.get(e.id);
    if (!node || points.length < 2) return null;
    const rect = this.renderer.domElement.getBoundingClientRect(), cam = this.camera;
    const ray = (x, y) => new THREE.Vector3((x - rect.left) / rect.width * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1, 0.5)
      .unproject(cam).sub(cam.position).normalize();
    const [[x0, y0], [x1, y1]] = points;
    if (Math.hypot(x1 - x0, y1 - y0) < 4) return null;
    const n = new THREE.Vector3().crossVectors(ray(x0, y0), ray(x1, y1)).normalize();
    const len = Math.hypot(x1 - x0, y1 - y0), mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
    const left = ray(mx + ((y1 - y0) / len) * 20, my - ((x1 - x0) / len) * 20);     // screen-left of the stroke (y down)
    if (n.dot(left) < 0) n.negate();
    node.updateWorldMatrix(true, false);
    const inv = node.matrixWorld.clone().invert();
    const co = cam.position.clone().applyMatrix4(inv);
    const no = n.clone().applyMatrix3(new THREE.Matrix3().getNormalMatrix(inv)).normalize();
    return { plane_co: co.toArray(), plane_no: no.toArray() };
  }

  hoverLoopCut(cx, cy) {
    if (this.tool?.kind !== "loopcut" || !this.edit) return;
    const mode = this.edit.sel.mode;
    this.edit.sel.mode = "edge";                         // pick an edge whatever the element mode
    const edge = this.pickElement(cx, cy);
    this.edit.sel.mode = mode;
    const key = edge && `${edge[0]},${edge[1]}`;
    if (key === this.tool.key) return;
    this.tool.edge = edge;
    this.tool.key = key;
    this.drawLoopCut();
  }

  // The cut-to-be: across each quad of the ring, at each cut's spacing.
  drawLoopCut() {
    const e = this.edit, node = e && this.nodes.get(e.id), t = this.tool;
    this.overlay.innerHTML = "";
    if (!node || !t?.edge) return;
    const ring = edgeRing(e.mesh, t.edge), m = e.mesh, W = node.matrixWorld;
    const at = (a, b, k) => new THREE.Vector3(...[0, 1, 2].map((i) => m.co[a * 3 + i] + (m.co[b * 3 + i] - m.co[a * 3 + i]) * k)).applyMatrix4(W);
    let d = "";
    for (let c = 1; c <= t.cuts; c++) {
      const k = c / (t.cuts + 1);
      const pts = ring.edges.map(([a, b]) => this.toScreen(at(a, b, k)));
      if (ring.closed) pts.push(pts[0]);
      d += "M" + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L");
    }
    this.overlay.innerHTML = `<path d="${d}" class="cut-preview"/>`;
  }

  drawKnife() {
    const pts = this.tool?.points || [];
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.overlay.innerHTML = pts.length ? `<polyline class="knife" points="${pts.map(([x, y]) => `${x - rect.left},${y - rect.top}`).join(" ")}"/>`
      + pts.map(([x, y]) => `<circle class="knife-dot" cx="${x - rect.left}" cy="${y - rect.top}" r="3.5"/>`).join("") : "";
  }

  drawProportional() {
    this.overlay.querySelectorAll(".prop").forEach((n) => n.remove());
    if (!this.proportional.on || !this.drag?.weights) return;
    const c = this.pivot.getWorldPosition(new THREE.Vector3());
    const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
    const a = this.toScreen(c), b = this.toScreen(c.clone().addScaledVector(right, this.proportional.radius));
    const r = Math.hypot(b[0] - a[0], b[1] - a[1]);
    this.overlay.insertAdjacentHTML("beforeend", `<circle class="prop" cx="${a[0]}" cy="${a[1]}" r="${r}"/>`);
  }

  toolClick(cx, cy) {
    const t = this.tool;
    if (t.kind === "loopcut") {
      this.hoverLoopCut(cx, cy);
      if (t.edge) this.hooks.onToolCommit?.({ kind: "loopcut", edge: t.edge, cuts: t.cuts });
    } else if (t.kind === "knife") {
      t.points.push([cx, cy]);
      this.drawKnife();
    } else if (t.kind === "bisect") {
      t.points.push([cx, cy]);
      this.drawBisect();
      if (t.points.length === 2) this.hooks.onToolCommit?.({ kind: "bisect", points: t.points });
    }
  }

  // Where the knife's path crosses the edited mesh's visible edges, in order along it:
  // [{edge: [a, b], t}] — each crossing found exactly, on the plane through the eye and
  // the path's segment.
  knifeCrossings(points) {
    const e = this.edit, node = e && this.nodes.get(e.id);
    if (!node || points.length < 2) return [];
    const rect = this.renderer.domElement.getBoundingClientRect(), cam = this.camera, m = e.mesh, W = node.matrixWorld;
    const ray = (x, y) => new THREE.Vector3((x - rect.left) / rect.width * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1, 0.5)
      .unproject(cam).sub(cam.position).normalize();
    const world = (i) => new THREE.Vector3(m.co[i * 3], m.co[i * 3 + 1], m.co[i * 3 + 2]).applyMatrix4(W);
    const seen = (p) => {
      const dir = p.clone().sub(cam.position), dist = dir.length();
      const hit = new THREE.Raycaster(cam.position.clone(), dir.normalize()).intersectObject(e.surface, false)[0];
      return !hit || hit.distance > dist - Math.max(1e-4, dist * 1e-3);
    };
    const out = [];
    for (let s = 0; s + 1 < points.length; s++) {
      const [x0, y0] = points[s], [x1, y1] = points[s + 1];
      const r0 = ray(x0, y0), r1 = ray(x1, y1), n = new THREE.Vector3().crossVectors(r0, r1).normalize();
      const found = [];
      for (const [a, b] of e.edges) {
        const pa = world(a), pb = world(b);
        const da = n.dot(pa.clone().sub(cam.position)), db = n.dot(pb.clone().sub(cam.position));
        if (da * db > 0 || da === db) continue;            // both on one side of the cut's plane
        const k = da / (da - db), p = pa.clone().lerp(pb, k);
        const [sx, sy] = this.toScreen(p);
        const ex = x1 - x0, ey = y1 - y0, len2 = ex * ex + ey * ey || 1;
        const u = ((sx + rect.left - x0) * ex + (sy + rect.top - y0) * ey) / len2;
        if (u < 0 || u > 1 || !seen(p)) continue;          // outside the segment, or behind the surface
        found.push({ edge: [a, b], t: k, u: s + u });
      }
      found.sort((p, q) => p.u - q.u);
      out.push(...found);
    }
    return out;
  }

  // Where a move starts: the moved thing's own and world placement, and — for an object — how far
  // its origin sits above its lowest point, so a surface snap can stand it on a floor.
  dragStart(o) {
    o.updateWorldMatrix(true, false);
    const st = { position: o.position.clone(), quaternion: o.quaternion.clone(),
                 world: o.getWorldPosition(new THREE.Vector3()), worldQ: o.getWorldQuaternion(new THREE.Quaternion()), lift: 0 };
    const surface = o !== this.pivot && o.userData.surface;
    if (surface) {
      const box = new THREE.Box3().setFromObject(surface);
      if (!box.isEmpty()) st.lift = st.world.z - box.min.z;
    }
    return st;
  }

  // Moves snap by increments of the move itself, as Blender does by default: what's moved
  // keeps its offset from the grid. (TransformControls' translationSnap rounds the position,
  // which in Edit mode would jump the selection's centre onto the grid first.) Or to a vertex or
  // a surface under the pointer.
  snapMove(o) {
    const st = this.moveStart;
    if (!st || this.gizmo.mode !== "translate" || this.snap.on === this.ctrl) return;
    if (this.snap.target !== "increment") { this.snapTo(o, st); return; }
    const d = o.position.clone().sub(st.position), local = this.gizmo.space === "local";
    const q = st.quaternion.clone();
    if (local) d.applyQuaternion(q.clone().invert());
    d.set(Math.round(d.x / SNAP) * SNAP, Math.round(d.y / SNAP) * SNAP, Math.round(d.z / SNAP) * SNAP);
    if (local) d.applyQuaternion(q);
    o.position.copy(st.position).add(d);
    o.updateMatrixWorld(true);
  }

  // Vertex: the moved thing's origin (Edit mode: the selection's centre) onto the nearest corner
  // of the face under the pointer. Surface: onto the point under the pointer — an object stands
  // on a surface that faces up. Within the gizmo's axis or plane, as Blender constrains a snap.
  snapTo(o, st) {
    const hit = this.snapTarget(o);
    this.drawSnap(hit);
    if (!hit) return;                                     // nothing there: the free move stands
    const want = hit.point.clone();
    if (this.snap.target === "surface" && o !== this.pivot && hit.normal.z > 0.7) want.z += st.lift;
    const d = want.sub(st.world), ax = this.gizmo.axis || "XYZ";
    if (ax.length < 3 && /^[XYZ]+$/.test(ax)) {
      const q = this.gizmo.space === "local" ? st.worldQ : new THREE.Quaternion();
      d.applyQuaternion(q.clone().invert());
      if (!ax.includes("X")) d.x = 0;
      if (!ax.includes("Y")) d.y = 0;
      if (!ax.includes("Z")) d.z = 0;
      d.applyQuaternion(q);
    }
    const world = st.world.clone().add(d);
    if (o.parent) { o.parent.updateWorldMatrix(true, false); o.parent.worldToLocal(world); }
    o.position.copy(world);
    o.updateMatrixWorld(true);
  }

  // What's under the pointer that the move could land on: never the thing moving (nor what it
  // carries), the edited mesh's own cage, a set's shadow catcher or an invisible pick proxy.
  snapTarget(moving) {
    if (!this.pointer) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ray = new THREE.Raycaster();
    ray.setFromCamera({ x: ((this.pointer[0] - rect.left) / rect.width) * 2 - 1,
                        y: -((this.pointer[1] - rect.top) / rect.height) * 2 + 1 }, this.camera);
    const inside = (obj, n0) => { for (let n = obj; n; n = n.parent) if (n === n0) return true; return false; };
    const cage = this.edit?.group;
    const hit = ray.intersectObjects(this.root.children, true).find((h) => h.object.isMesh && h.face
      && !h.object.userData.catcher && h.object.material?.visible !== false && this.pickable(h.object)
      && !inside(h.object, moving) && !(cage && inside(h.object, cage)));
    if (!hit) return null;
    const normal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
    if (this.snap.target === "surface") return { point: hit.point, normal };
    const pos = hit.object.geometry.attributes.position;
    let best = null, bd = Infinity;
    for (const i of [hit.face.a, hit.face.b, hit.face.c]) {
      const p = new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(hit.object.matrixWorld);
      const [sx, sy] = this.toScreen(p);
      const d = Math.hypot(sx + rect.left - this.pointer[0], sy + rect.top - this.pointer[1]);
      if (d < bd) { bd = d; best = p; }
    }
    return { point: best, normal };
  }

  drawSnap(hit) {
    this.overlay.querySelectorAll(".snap").forEach((n) => n.remove());
    if (!hit) return;
    const [x, y] = this.toScreen(hit.point);
    this.overlay.insertAdjacentHTML("beforeend", `<circle class="snap" cx="${x}" cy="${y}" r="6"/>`);
  }

  setSnapTarget(target) { this.snap.target = target; }

  applySnap() {
    const on = this.snap.on !== this.ctrl;                 // Ctrl held flips it, as in Blender
    this.gizmo.setRotationSnap(on ? 15 * DEG : null);
    this.gizmo.setScaleSnap(on ? 0.1 : null);
  }

  setSnap(on) { this.snap.on = on; this.applySnap(); }
  setProportional(p) { Object.assign(this.proportional, p); this.drawProportional(); }

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

  // The depth range follows the view: close up it resolves millimetres, from a kilometre out
  // it still reaches the far side of a site (a fixed 2 km cut a venue's terrain off).
  fitDepth() {
    const c = this.camera, d = c.position.distanceTo(this.orbit.target);
    const near = Math.min(5, Math.max(0.005, d / 2000)), far = Math.max(2000, d * 60);
    if (Math.abs(near - c.near) / c.near < 0.2 && Math.abs(far - c.far) / c.far < 0.2) return;
    c.near = near;
    c.far = far;
    c.updateProjectionMatrix();
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

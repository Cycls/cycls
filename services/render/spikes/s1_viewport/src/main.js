// Spike S1: does a Blender-style three.js viewport work inside the Cycls app
// sandbox (srcdoc, opaque origin, our CSP)? Every finding lands in `diag` and
// is written to data/diag.json through the bridge, so it can be read off disk.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { h, render } from "preact";

const diag = {
  started: new Date().toISOString(),
  ua: navigator.userAgent,
  isSecureContext: window.isSecureContext,
  cryptoSubtle: !!(window.crypto && window.crypto.subtle),
  origin: String(window.origin),
  bridge: typeof window.cycls === "object",
  bridgeCtx: null,
  cspViolations: [],
  errors: [],
  webgl2: false,
  gpu: null,
  pmrem: false,
  rectAreaLight: false,
  contextLost: 0,
  contextRestored: 0,
  fps: 0,
  triangles: 0,
  keys: [],
  gizmoDrags: 0,
  pointerCapture: null,
  load: "pending",
  saves: 0,
  saveError: null,
};

addEventListener("securitypolicyviolation", (e) =>
  diag.cspViolations.push(`${e.violatedDirective} ← ${e.blockedURI || "inline"}`));
addEventListener("error", (e) => diag.errors.push(String(e.message)));
addEventListener("unhandledrejection", (e) => diag.errors.push(String(e.reason)));

// Blender space: Z up.
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

const view = document.getElementById("view");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.NeutralToneMapping;   // Khronos PBR Neutral, as the engine
view.prepend(renderer.domElement);
renderer.domElement.tabIndex = 0;
diag.webgl2 = renderer.capabilities.isWebGL2 !== false;
try {
  const gl = renderer.getContext();
  const ext = gl.getExtension("WEBGL_debug_renderer_info");
  diag.gpu = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
} catch (e) { diag.gpu = `n/a (${e})`; }
renderer.domElement.addEventListener("webglcontextlost", (e) => { e.preventDefault(); diag.contextLost++; });
renderer.domElement.addEventListener("webglcontextrestored", () => { diag.contextRestored++; });

const scene = new THREE.Scene();
scene.background = new THREE.Color("#3a3a3a");
try {
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  diag.pmrem = true;
} catch (e) { diag.errors.push(`pmrem: ${e}`); }

const grid = new THREE.GridHelper(20, 20, 0x555555, 0x444444);
grid.rotation.x = Math.PI / 2;                       // GridHelper is XZ; Blender's floor is XY
scene.add(grid);

try {
  RectAreaLightUniformsLib.init();
  const key = new THREE.RectAreaLight(0xffffff, 6, 3, 3);
  key.position.set(-4, -4, 5);
  key.lookAt(0, 0, 0.5);
  scene.add(key);
  diag.rectAreaLight = true;
} catch (e) { diag.errors.push(`rectarea: ${e}`); }
scene.add(new THREE.HemisphereLight(0xffffff, 0x333333, 0.4));

const objects = [];
function add(name, geo, mat, pos, rot = [0, 0, 0]) {
  const m = new THREE.Mesh(geo, mat);
  m.name = name;
  m.position.set(...pos);
  m.rotation.set(...rot.map((d) => (d * Math.PI) / 180), "ZYX");   // Blender XYZ euler == three 'ZYX'
  scene.add(m);
  objects.push(m);
  return m;
}
const gold = new THREE.MeshPhysicalMaterial({ color: "#ffe1a0", metalness: 1, roughness: 0.15 });
const glass = new THREE.MeshPhysicalMaterial({ color: "#ffffff", metalness: 0, roughness: 0, transmission: 1, ior: 1.45, thickness: 1 });
const clay = new THREE.MeshPhysicalMaterial({ color: "#b04040", roughness: 0.4, clearcoat: 0.6 });
add("Torus", new THREE.TorusGeometry(1, 0.36, 48, 128), gold, [0, 0, 1.4], [90, 0, 0]);
add("Cube", new THREE.BoxGeometry(1.4, 1.4, 1.4), clay, [-3, 1, 0.7], [0, 0, 20]);
add("Glass", new THREE.SphereGeometry(0.8, 64, 32), glass, [3, 1, 0.8]);
add("Dense sphere (100k tris)", new THREE.SphereGeometry(1, 320, 160), clay, [0, 4, 1]);

const camera = new THREE.PerspectiveCamera(39.6, 1, 0.05, 500);   // 50mm on 36mm AUTO fit
camera.position.set(7, -9, 5);
camera.lookAt(0, 0, 1);

const orbit = new OrbitControls(camera, renderer.domElement);
orbit.target.set(0, 0, 1);
orbit.update();

const gizmo = new TransformControls(camera, renderer.domElement);
const gizmoHelper = gizmo.getHelper ? gizmo.getHelper() : gizmo;
scene.add(gizmoHelper);
gizmo.addEventListener("dragging-changed", (e) => {
  orbit.enabled = !e.value;
  if (!e.value) { diag.gizmoDrags++; scheduleSave(); }
});

let selected = null;
function select(obj) {
  selected = obj;
  obj ? gizmo.attach(obj) : gizmo.detach();
  paint();
}

// Click-select (not after a drag).
const ray = new THREE.Raycaster();
let down = null;
renderer.domElement.addEventListener("pointerdown", (e) => {
  down = [e.clientX, e.clientY];
  try {
    renderer.domElement.setPointerCapture(e.pointerId);
    diag.pointerCapture = renderer.domElement.hasPointerCapture(e.pointerId);
    renderer.domElement.releasePointerCapture(e.pointerId);
  } catch (err) { diag.pointerCapture = `error: ${err}`; }
  renderer.domElement.focus();
});
renderer.domElement.addEventListener("pointerup", (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || gizmo.dragging) return;
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera({ x: ((e.clientX - r.left) / r.width) * 2 - 1, y: -((e.clientY - r.top) / r.height) * 2 + 1 }, camera);
  const hit = ray.intersectObjects(objects, false)[0];
  select(hit ? hit.object : null);
});

// Blender hotkeys: G/R/S, numpad views, X/Delete.
const VIEWS = { Numpad1: [0, -1, 0], Numpad3: [1, 0, 0], Numpad7: [0, 0, 1] };
addEventListener("keydown", (e) => {
  diag.keys.push(e.code);
  if (diag.keys.length > 20) diag.keys.shift();
  if (e.code === "KeyG") gizmo.setMode("translate");
  if (e.code === "KeyR") gizmo.setMode("rotate");
  if (e.code === "KeyS") gizmo.setMode("scale");
  if (VIEWS[e.code]) {
    const d = new THREE.Vector3(...VIEWS[e.code]).multiplyScalar(camera.position.distanceTo(orbit.target));
    camera.position.copy(orbit.target).add(d);
    if (e.code === "Numpad7") camera.position.y -= 0.001;   // avoid a degenerate up vector
    orbit.update();
  }
  if ((e.code === "KeyX" || e.code === "Delete") && selected) {
    scene.remove(selected); objects.splice(objects.indexOf(selected), 1); select(null); scheduleSave();
  }
  bar();
});

// Outliner (Preact) + mode bar.
function paint() {
  render(h("div", null, objects.map((o) =>
    h("div", { class: "row" + (o === selected ? " sel" : ""), onClick: () => select(o) }, o.name))),
  document.getElementById("outliner"));
}
function bar() {
  const mode = gizmo.getMode ? gizmo.getMode() : gizmo.mode;
  render(h("div", { style: "display:flex;gap:4px" }, ["translate", "rotate", "scale"].map((m) =>
    h("button", { class: m === mode ? "on" : "", onClick: () => { gizmo.setMode(m); bar(); } }, m))),
  document.getElementById("bar"));
}
paint(); bar();

// Bridge: load + debounced save of transforms, and the diag report.
const state = () => Object.fromEntries(objects.map((o) => [o.name, {
  location: o.position.toArray(), rotation: [o.rotation.x, o.rotation.y, o.rotation.z], scale: o.scale.toArray() }]));
let saveTimer = null;
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    if (!window.cycls) return;
    try { await window.cycls.write("data/scene.json", JSON.stringify(state(), null, 1)); diag.saves++; }
    catch (e) { diag.saveError = String(e); }
  }, 800);
}
diag.inits = 0;
diag.initPorts = 0;
diag.writesResolved = 0;
addEventListener("message", (e) => {
  if (e.data && e.data.type === "cycls:init") { diag.inits++; if (e.ports && e.ports.length) diag.initPorts++; }
});
const t0 = performance.now();
const ms = () => Math.round(performance.now() - t0);
diag.readProbe = { hasReady: !!(window.cycls && window.cycls.ready) };
async function probeRead(tag) {
  diag.readProbe[tag + "_start"] = ms();
  try { const s = await window.cycls.read("data/scene.json"); diag.readProbe[tag] = `ok ${s.length}B @${ms()}ms`; }
  catch (e) { diag.readProbe[tag] = `err ${String(e).slice(0, 60)} @${ms()}ms`; }
}
if (window.cycls) {
  Promise.resolve(window.cycls.ready).then(() => { diag.readProbe.readyAt = ms(); });
  setTimeout(() => probeRead("read_10s"), 10000);
  setTimeout(() => probeRead("read_25s"), 25000);
}
async function load() {
  if (!window.cycls) { diag.load = "no bridge"; return; }
  try {
    await window.cycls.ready;
    diag.readProbe.loadReadStart = ms();
    diag.bridgeCtx = window.cycls.ctx || null;
    const saved = JSON.parse(await window.cycls.read("data/scene.json"));
    for (const o of objects) {
      const s = saved[o.name];
      if (!s) continue;
      o.position.fromArray(s.location); o.rotation.set(...s.rotation); o.scale.fromArray(s.scale);
    }
    diag.load = "loaded";
  } catch (e) { diag.load = `fresh (${String(e).slice(0, 60)})`; }
}
load();
setInterval(async () => {
  if (!window.cycls) return;
  try { await window.cycls.write("data/diag.json", JSON.stringify(diag, null, 1)); diag.writesResolved++; } catch (e) { diag.saveError = String(e); }
}, 3000);

// Resize + render loop with an FPS meter.
function resize() {
  const w = view.clientWidth, hgt = view.clientHeight;
  renderer.setSize(w, hgt, false);
  camera.aspect = w / Math.max(1, hgt);
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(view);
resize();
// Render on demand (what the real app does): only when something changed.
let dirty = true;
const touch = () => { dirty = true; };
orbit.addEventListener("change", touch);
gizmo.addEventListener("change", touch);
addEventListener("keydown", touch);
addEventListener("pointerup", touch);
new ResizeObserver(touch).observe(view);

// Synchronous GPU benchmark: ms per frame for each scene variant, forced to
// completion with a 1-pixel readPixels so throttled rAF can't hide or fake it.
function frameMs(n = 12) {
  const gl = renderer.getContext();
  const px = new Uint8Array(4);
  renderer.render(scene, camera); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
  const t0 = performance.now();
  for (let i = 0; i < n; i++) { renderer.render(scene, camera); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); }
  return +((performance.now() - t0) / n).toFixed(2);
}
setTimeout(() => {
  const byName = Object.fromEntries(objects.map((o) => [o.name, o]));
  const show = (names) => objects.forEach((o) => { o.visible = names.includes(o.name); });
  const all = objects.map((o) => o.name);
  const size = renderer.getDrawingBufferSize(new THREE.Vector2());
  diag.bench = { drawingBuffer: [size.x, size.y], pixelRatio: renderer.getPixelRatio() };
  const cases = {
    all,
    no_glass: all.filter((n) => n !== "Glass"),
    no_dense: all.filter((n) => !n.startsWith("Dense")),
    no_glass_no_dense: all.filter((n) => n !== "Glass" && !n.startsWith("Dense")),
  };
  for (const [k, names] of Object.entries(cases)) { show(names); diag.bench[k] = frameMs(); }
  show(all);
  diag.bench.byName = Object.keys(byName).length;
  dirty = true;
}, 1500);

let frames = 0, last = performance.now();
renderer.setAnimationLoop(() => {
  if (!dirty) return;
  dirty = false;
  renderer.render(scene, camera);
  frames++;
  const now = performance.now();
  if (now - last > 1000) {
    diag.fps = Math.round((frames * 1000) / (now - last));
    diag.triangles = renderer.info.render.triangles;
    frames = 0; last = now;
    document.getElementById("diag").textContent =
      `webgl2 ${diag.webgl2}  pmrem ${diag.pmrem}  rectArea ${diag.rectAreaLight}\n` +
      `fps ${diag.fps}  tris ${diag.triangles}  gpu ${String(diag.gpu).slice(0, 40)}\n` +
      `bridge ${diag.bridge}  load ${diag.load}  saves ${diag.saves}\n` +
      `csp violations ${diag.cspViolations.length}  errors ${diag.errors.length}  ctxLost ${diag.contextLost}\n` +
      `secure ${diag.isSecureContext}  subtle ${diag.cryptoSubtle}  keys ${diag.keys.slice(-5).join(" ")}`;
  }
});

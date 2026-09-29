// Phase C tools on the default cube with real input: Tab (Blender converts it), Ctrl+R and
// a hover over a side edge (the ring preview), wheel for two cuts, click to cut; then K,
// three clicks across the top face, Enter; then O and a gizmo drag with the proportional
// falloff; Shift+Tab and a snapped drag; then Blender's view of the result. Checks what
// reached the mesh at each step.
await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false }, page);
await goto("http://127.0.0.1:8094/");
await sleep(5000);
const S = (expr) => evalApp(`JSON.stringify(${expr})`).then(JSON.parse);
const waitIdle = async () => { for (let i = 0; i < 150; i++) { await sleep(200); if (!(await evalApp("__studio.state.busy"))) return; } };
const out = {};
await click(700, 880);                                       // focus the app's frame (keys go to it)
await evalApp(`__studio.actions.select(["cube"])`);
await key("Tab");
await waitIdle();
out.entered = await S(`{ faces: __studio.state.editMesh.faces.length, mode: __studio.state.mode }`);
// screen point of a world point on the cube
const at = (x, y, z) => evalApp(`(() => { const vp = __studio.viewport, V = vp.camera.position.constructor;
  const n = vp.nodes.get("cube"); const p = new V(${x}, ${y}, ${z}).applyMatrix4(n.matrixWorld);
  const r = vp.renderer.domElement.getBoundingClientRect(), s = p.project(vp.camera);
  return [r.left + (s.x + 1) / 2 * r.width, r.top + (1 - s.y) / 2 * r.height]; })()`);
// loop cut: hover the vertical front-right edge (x = 1, y = −1), wheel once for 2 cuts, click
await key("KeyR", "r", 2);                                   // Ctrl (modifier 2)
const [ex, ey] = await at(1, -1, 0);
await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: ex, y: ey }, page);
await sleep(300);
out.preview = await evalApp(`document.querySelector(".tool-overlay path") ? "drawn" : "none"`);
await send("Input.dispatchMouseEvent", { type: "mouseWheel", x: ex, y: ey, deltaX: 0, deltaY: -100 }, page);
await sleep(200);
await shot("tools-loopcut-preview");
await click(ex, ey);
await sleep(400);
out.loopcut = await S(`{ faces: __studio.state.editMesh.faces.length, cuts: __studio.state.lastCut && __studio.state.lastCut.cuts, label: __studio.state.undo.at(-1).label }`);
// knife across the top face: from above the −x edge to above the +x edge
await key("KeyK");
for (const [x, y, z] of [[-1.3, 0.2, 1], [0, 0.4, 1], [1.3, 0.3, 1]]) { const [sx, sy] = await at(x, y, z); await click(sx, sy); await sleep(120); }
await shot("tools-knife-path");
await key("Enter");
await sleep(400);
out.knife = await S(`{ faces: __studio.state.editMesh.faces.length, label: __studio.state.undo.at(-1).label, sel: __studio.state.edit.items.length }`);
await shot("tools-after");
// proportional: a top corner, O, the Z arrow dragged up with a wheel turn mid-drag — the
// loop-cut vertex below it follows part of the way, the far side stays put
await key("Digit1");
const near = (x, y, z) => evalApp(`(() => { const co = __studio.state.editMesh.co; let best = -1, d = 1e9;
  for (let i = 0; i < co.length / 3; i++) { const e = (co[i*3]-(${x}))**2 + (co[i*3+1]-(${y}))**2 + (co[i*3+2]-(${z}))**2; if (e < d) { d = e; best = i; } }
  return best; })()`);
const co = (i) => S(`Array.from(__studio.state.editMesh.co.slice(${i} * 3, ${i} * 3 + 3))`);
// the gizmo's Z arrow on screen: walk up the axis from the pivot, asking the gizmo what it hovers
const arrow = () => evalApp(`(() => { const vp = __studio.viewport, g = vp.gizmo, V = vp.camera.position.constructor;
  const r = vp.renderer.domElement.getBoundingClientRect(); vp.pivot.updateMatrixWorld(true);
  const o = new V().setFromMatrixPosition(vp.pivot.matrixWorld), dir = new V(0, 0, 1).applyQuaternion(vp.pivot.quaternion);
  const hits = [];
  for (let t = 0.01; t < 4; t += 0.01) { const p = o.clone().addScaledVector(dir, t).project(vp.camera);
    g.pointerHover({ x: p.x, y: p.y, button: 0 }); if (g.axis === "Z") hits.push([r.left + (p.x + 1) / 2 * r.width, r.top + (1 - p.y) / 2 * r.height]); }
  g.axis = null; return hits[Math.floor(hits.length / 2)] || null; })()`);
async function dragArrow(dy, wheel) {
  const [x0, y0] = await arrow();
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x0, y: y0 }, page);
  await sleep(50);
  await mouse("mousePressed", x0, y0);
  for (let i = 1; i <= 12; i++) {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x0, y: y0 + (dy * i) / 12, button: "left", buttons: 1 }, page);
    await sleep(16);
    if (wheel && i === 6) await send("Input.dispatchMouseEvent", { type: "mouseWheel", x: x0, y: y0 + dy / 2, deltaX: 0, deltaY: -100 }, page);
  }
  await mouse("mouseReleased", x0, y0 + dy);
  await sleep(300);
}
const corner = await near(1, -1, 1), below = await near(1, -1, 1 / 3), far = await near(-1, 1, -1);
const before = { corner: await co(corner), below: await co(below), far: await co(far) };
{ const [x, y] = await at(1, -1, 1); await click(x, y); await sleep(150); }
await key("KeyO");
out.picked = await S(`__studio.state.edit.items`);
await dragArrow(-60, true);
await shot("tools-proportional");
const after = { corner: await co(corner), below: await co(below), far: await co(far) };
const dz = after.corner[2] - before.corner[2], dzBelow = after.below[2] - before.below[2];
out.proportional = { on: await S(`__studio.state.proportional.on`), radius: +(await S(`__studio.state.proportional.radius`)).toFixed(3),
  dz: +dz.toFixed(3), share: +(dzBelow / dz).toFixed(3), farMoved: after.far.some((v, k) => Math.abs(v - before.far[k]) > 1e-6),
  label: await S(`__studio.state.undo.at(-1).label`) };
await key("KeyO");
// snapping: Shift+Tab, an off-grid vertex (a loop cut's third), a drag — it moves by whole 0.1 m steps
await key("Tab", "Tab", 8);
const third = await near(-1, -1, -1 / 3), t0 = await co(third);
{ const [x, y] = await at(-1, -1, -1 / 3); await click(x, y); await sleep(150); }
await dragArrow(-47);
const t1 = await co(third), steps = (t1[2] - t0[2]) / 0.1;
out.snap = { on: await S(`__studio.state.snap`), z0: +t0[2].toFixed(4), z1: +t1[2].toFixed(4), steps: +steps.toFixed(4),
  whole: Math.abs(steps - Math.round(steps)) < 1e-4 && Math.round(steps) !== 0, xyKept: Math.abs(t1[0] - t0[0]) + Math.abs(t1[1] - t0[1]) < 1e-6 };
await key("Tab", "Tab", 8);
await shot("tools-snap");
// Blender takes what the tools made as it is: recalculating normals on all of it brings the
// same mesh back (one Blender had to repair, or with a face turned inward, would not)
await key("KeyA");
const geo = `JSON.stringify({ co: Array.from(__studio.state.editMesh.co, (v) => +v.toFixed(4)), faces: __studio.state.editMesh.faces })`;
const g0 = await evalApp(geo);
await evalApp(`__studio.actions.edit.blender("recalc_normals", "recalculate normals")`);
await waitIdle();
const g1 = await evalApp(geo);
out.blender = { same: g0 === g1, faces: JSON.parse(g1).faces.length, label: await S(`__studio.state.undo.at(-1).label`) };
return out;

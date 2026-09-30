// Vertex and surface snapping, and bisect, with real input on a cube and a sphere (the harness
// workspace needs a `ball` uv_sphere at [3, 0, 1] beside the default cube): the ball's X arrow
// dragged onto the cube's corner snaps its x to the corner's; its centre handle dragged onto the
// cube's top stands it there; then Tab on the cube, Bisect across it, and Blender's cut comes back.
await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false }, page);
await goto("http://127.0.0.1:8094/");
await sleep(5000);
const S = (expr) => evalApp(`JSON.stringify(${expr})`).then(JSON.parse);
const waitIdle = async () => { for (let i = 0; i < 150; i++) { await sleep(200); if (!(await evalApp("__studio.state.busy"))) return; } };
const at = (x, y, z) => evalApp(`(() => { const vp = __studio.viewport, V = vp.camera.position.constructor;
  const p = new V(${x}, ${y}, ${z}), r = vp.renderer.domElement.getBoundingClientRect(), s = p.project(vp.camera);
  return [r.left + (s.x + 1) / 2 * r.width, r.top + (1 - s.y) / 2 * r.height]; })()`);
// walk out from the object's origin along a direction until the gizmo hovers `axis`
const handle = async (id, axis, dir) => {
  const o = await evalApp(`__studio.viewport.nodes.get("${id}").getWorldPosition(new (__studio.viewport.camera.position.constructor)()).toArray()`);
  const [ox, oy] = await at(...o);
  if (axis === "XYZ") {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: ox, y: oy }, page);
    await sleep(60);
    return (await evalApp("__studio.viewport.gizmo.axis")) === "XYZ" ? [ox, oy] : null;
  }
  const [dx, dy] = await at(o[0] + dir[0] * 0.05, o[1] + dir[1] * 0.05, o[2] + dir[2] * 0.05);
  const l = Math.hypot(dx - ox, dy - oy);
  for (let d = 8; d < 220; d += 4) {
    const x = ox + (dx - ox) / l * d, y = oy + (dy - oy) / l * d;
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y }, page);
    await sleep(20);
    if ((await evalApp("__studio.viewport.gizmo.axis")) === axis) return [x, y];
  }
  return null;
};
const out = {};
await click(700, 16);                                       // focus the frame
await evalApp(`__studio.actions.select(["ball"]); __studio.actions.edit.setSnapTarget("vertex"); 1`);
await sleep(300);
// vertex: the X arrow, dropped over the cube's front-right top corner (1, -1, 2)
let g = await handle("ball", "X", [1, 0, 0]);
const corner = await at(1, -1, 2);
if (g) { await drag(g[0], g[1], corner[0], corner[1], 20); await sleep(400); }
out.vertex = { grabbed: !!g, loc: await S(`__studio.state.doc.objects.ball.location`) };
await shot("snap-vertex");
// surface: the centre handle, dropped on the middle of the cube's top (0, 0, 2) — it stands there
await evalApp(`__studio.actions.edit.setSnapTarget("surface"); 1`);
g = await handle("ball", "XYZ");
const top = await at(0, 0.2, 2);
if (g) { await drag(g[0], g[1], top[0], top[1], 24); await sleep(400); }
out.surface = { grabbed: !!g, loc: await S(`__studio.state.doc.objects.ball.location`) };
await shot("snap-surface");
await evalApp(`__studio.actions.edit.toggleSnap(); 1`);
// bisect: Tab on the cube, two clicks across it a little above its middle
await evalApp(`__studio.actions.select(["cube"]); 1`);
await click(700, 16);
await key("Tab");
await waitIdle();
out.entered = await S(`{ faces: __studio.state.editMesh.faces.length, mode: __studio.state.mode }`);
await evalApp(`__studio.actions.edit.startTool("bisect"); 1`);
const a = await at(-2.2, -1, 1.2), b = await at(2.2, -1, 1.2);
await click(a[0], a[1]);
await sleep(150);
await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2 }, page);
await sleep(150);
out.line = await evalApp(`document.querySelectorAll(".tool-overlay circle").length`);
await shot("bisect-line");
await click(b[0], b[1]);
await waitIdle();
out.bisect = await S(`{ faces: __studio.state.editMesh.faces.length, verts: __studio.state.editMesh.co.length / 3,
  selected: __studio.state.edit.items.length, label: __studio.state.undo.at(-1).label }`);
await shot("bisect-cut");
// again, dropping the side left of the line (above it, drawn left to right) and filling
await key("KeyA");                                           // the cut is selected: bisect works on the selection
await evalApp(`__studio.actions.setTool("bisect_clear", "left"); __studio.actions.setTool("bisect_fill", true);
  __studio.actions.edit.startTool("bisect"); 1`);
const c = await at(-2.2, -1, 0.6), d = await at(2.2, -1, 0.6);
await click(c[0], c[1]);
await sleep(150);
await click(d[0], d[1]);
await waitIdle();
out.halved = await S(`{ faces: __studio.state.editMesh.faces.length, top: Math.max(...Array.from(__studio.state.editMesh.co).filter((_, i) => i % 3 === 2)) }`);
await key("Tab");
await sleep(600);
await shot("bisect-halved");
return out;

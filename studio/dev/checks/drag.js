// Select the target (the first subject mesh, or globalThis.TARGET) by clicking it, find its
// gizmo's X arrow by hovering, drag it, check the autosave.
await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false }, page);
await goto("http://127.0.0.1:8094/");
await sleep(3500);
const TARGET = globalThis.TARGET || await evalApp(`Object.entries(__studio.state.doc.objects).find(([id, o]) => o.type === "mesh" && !id.startsWith("studio_") && !["plane", "grid", "cyclorama"].includes(__studio.state.doc.meshes[o.mesh]?.primitive))?.[0]`);
// The target's world bounding box, inside the frame.
const BOX = `(() => { const s = __studio.viewport.nodes.get("${TARGET}").userData.surface; s.geometry.computeBoundingBox(); return s.geometry.boundingBox.clone().applyMatrix4(s.matrixWorld); })()`;
const proj = (expr) => evalApp(`(() => {
  const vp = __studio.viewport, THREE_V = vp.camera.position.constructor;
  const b = vp.renderer.domElement.getBoundingClientRect();
  const toScreen = (v) => { const p = v.clone().project(vp.camera); return [b.left + (p.x + 1) / 2 * b.width, b.top + (1 - p.y) / 2 * b.height]; };
  return ${expr};
})()`);
const before = JSON.parse(await (await fetch("http://127.0.0.1:8094/files/apps/studio/data/scene.json")).text());
// the target's middle
const [px, py] = await proj(`toScreen(${BOX}.getCenter(new THREE_V()))`);
await click(px, py);
await sleep(400);
const sel = await evalApp("JSON.stringify(__studio.state.selection)");
const origin = await proj(`toScreen(vp.nodes.get("${TARGET}").getWorldPosition(new THREE_V()))`);
const xdir = await proj(`(() => { const o = vp.nodes.get("${TARGET}").getWorldPosition(new THREE_V()); const a = toScreen(o), c = toScreen(o.clone().add(new THREE_V(0.05, 0, 0))); const l = Math.hypot(c[0]-a[0], c[1]-a[1]); return [(c[0]-a[0])/l, (c[1]-a[1])/l]; })()`);
let grab = null;
for (let d = 8; d < 220; d += 4) {
  const x = origin[0] + xdir[0] * d, y = origin[1] + xdir[1] * d;
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y }, page);
  await sleep(20);
  if ((await evalApp("__studio.viewport.gizmo.axis")) === "X") { grab = [x, y, d]; break; }
}
if (!grab) return { target: TARGET, sel, origin, xdir, error: "no X handle found" };
await shot("drag-0");
await drag(grab[0], grab[1], grab[0] + xdir[0] * 120, grab[1] + xdir[1] * 120, 16);
await sleep(300);
const afterDrag = await evalApp(`JSON.stringify({ loc: __studio.state.doc.objects["${TARGET}"].location, status: __studio.state.status, undo: __studio.state.undo.length })`);
await sleep(1600);                                   // autosave debounce is 800 ms
const status = await evalApp("__studio.state.status");
const disk = JSON.parse(await (await fetch("http://127.0.0.1:8094/files/apps/studio/data/scene.json")).text());
await shot("drag-1");
return { target: TARGET, sel, grab, afterDrag: JSON.parse(afterDrag), status, before: { rev: before.rev, loc: before.objects[TARGET].location },
         disk: { rev: disk.rev, by: disk.by, loc: disk.objects[TARGET].location } };

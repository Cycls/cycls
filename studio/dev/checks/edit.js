// Edit mode on the target (the first subject mesh, or globalThis.TARGET): Tab (Blender
// converts it), face mode, pick the top face, inset (Blender), extrude (here), leave, and
// check what reached disk.
const TARGET = globalThis.TARGET || await evalApp(`Object.entries(__studio.state.doc.objects).find(([id, o]) => o.type === "mesh" && !id.startsWith("studio_") && !["plane", "grid", "cyclorama"].includes(__studio.state.doc.meshes[o.mesh]?.primitive))?.[0]`);
// The target's world bounding box, inside the frame.
const BOX = `(() => { const s = __studio.viewport.nodes.get("${TARGET}").userData.surface; s.geometry.computeBoundingBox(); return s.geometry.boundingBox.clone().applyMatrix4(s.matrixWorld); })()`;
const S = (expr) => evalApp(`JSON.stringify(${expr})`).then(JSON.parse);
const state = () => S(`{ mode: __studio.state.mode, busy: __studio.state.busy, toast: __studio.state.toast && __studio.state.toast.text,
  edit: __studio.state.edit && { mode: __studio.state.edit.mode, items: __studio.state.edit.items.slice(0, 8), n: __studio.state.edit.items.length },
  mesh: __studio.state.doc.objects["${TARGET}"].mesh, meshEntry: __studio.state.doc.meshes[__studio.state.doc.objects["${TARGET}"].mesh],
  status: __studio.state.status, rev: __studio.state.doc.rev }`);
const waitIdle = async (ms = 60000) => { const t = Date.now(); let s; do { await sleep(400); s = await state(); } while (s.busy && Date.now() - t < ms); return s; };
const out = {};
await evalApp(`__studio.actions.select(['${TARGET}'])`);
await click(700, 880);                                // focus the viewport (empty floor) — a click, so it deselects…
await evalApp(`__studio.actions.select(['${TARGET}'])`); // …so select again
await key("Tab");
out.entered = await waitIdle();
await key("Digit3");                                  // face mode
await sleep(200);
// the top cap's centre, on screen
const top = await evalApp(`(() => {
  const vp = __studio.viewport, V = vp.camera.position.constructor;
  const b = vp.renderer.domElement.getBoundingClientRect();
  const box = ${BOX}, c = box.getCenter(new V());
  const p = new V(c.x, c.y, box.max.z).project(vp.camera);
  return [b.left + (p.x + 1) / 2 * b.width, b.top + (1 - p.y) / 2 * b.height];
})()`);
await click(top[0], top[1]);
await sleep(300);
out.picked = await state();
await shot("edit-picked");
await key("KeyI");                                    // inset, by Blender
out.inset = await waitIdle();
await shot("edit-inset");
await key("KeyE");                                    // extrude, here
await sleep(300);
out.extruded = await state();
await key("Tab");                                     // back to Object mode
await sleep(1800);                                    // autosave
out.left = await state();
const disk = JSON.parse(await (await fetch("http://127.0.0.1:8094/files/apps/studio/data/scene.json")).text());
const m = disk.meshes[disk.objects[TARGET].mesh];
const side = m && m.data ? await fetch("http://127.0.0.1:8094/files/apps/studio/data/" + m.data) : null;
out.disk = { rev: disk.rev, by: disk.by, mesh: m, sidecar: side && side.status };
out.log = JSON.parse(await evalHost("JSON.stringify(window.__log.filter(l => l[0] === 'engine' || (l[0] === 'write' && !String(l[1]).endsWith('scene.json'))))"));
await shot("edit-done");
return out;

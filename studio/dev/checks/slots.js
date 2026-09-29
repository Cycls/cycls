// Material slots on the target (the first subject mesh, or globalThis.TARGET): Edit mode,
// pick the top face, add a second slot with a new blue material, Assign, leave — then
// check the disk (two slots, the mesh file's material_index) and the viewport (one
// material per slot group).
const TARGET = globalThis.TARGET || await evalApp(`Object.entries(__studio.state.doc.objects).find(([id, o]) => o.type === "mesh" && !id.startsWith("studio_") && !["plane", "grid", "cyclorama"].includes(__studio.state.doc.meshes[o.mesh]?.primitive))?.[0]`);
const BOX = `(() => { const s = __studio.viewport.nodes.get("${TARGET}").userData.surface; s.geometry.computeBoundingBox(); return s.geometry.boundingBox.clone().applyMatrix4(s.matrixWorld); })()`;
const waitIdle = async () => { for (let i = 0; i < 150; i++) { await sleep(200); if (!(await evalApp("__studio.state.busy"))) return; } };
await evalApp(`__studio.actions.select(["${TARGET}"])`);
await click(700, 880);
await evalApp(`__studio.actions.select(["${TARGET}"])`);
await key("Tab");
await waitIdle();
await key("Digit3");
await sleep(200);
const top = await evalApp(`(() => {
  const vp = __studio.viewport, V = vp.camera.position.constructor;
  const b = vp.renderer.domElement.getBoundingClientRect();
  const box = ${BOX}, c = box.getCenter(new V());
  const p = new V(c.x, c.y, box.max.z).project(vp.camera);
  return [b.left + (p.x + 1) / 2 * b.width, b.top + (1 - p.y) / 2 * b.height];
})()`);
await click(top[0], top[1]);
await sleep(300);
const picked = await evalApp("JSON.stringify(__studio.state.edit.items)");
await evalApp(`(() => { const a = __studio.actions, id = "${TARGET}";
  a.addSlot(id); a.addMaterial(id, 1);
  const mid = __studio.state.doc.objects[id].materials[1];
  a.update((d) => { d.materials[mid].base_color = "#2050ff"; }, "blue");
  a.edit.assignSlot(1); })()`);
await key("Tab");
await waitIdle();
await sleep(1800);
const disk = JSON.parse(await (await fetch("http://127.0.0.1:8094/files/apps/studio/data/scene.json")).text());
const o = disk.objects[TARGET], mesh = disk.meshes[o.mesh];
const side = mesh.data ? JSON.parse(await (await fetch("http://127.0.0.1:8094/files/apps/studio/data/" + mesh.data)).text()) : {};
const view = JSON.parse(await evalApp(`JSON.stringify((() => { const m = __studio.viewport.nodes.get("${TARGET}").userData.surface;
  return { materials: Array.isArray(m.material) ? m.material.map((x) => x.color.getHexString()) : [m.material.color.getHexString()],
           groups: m.geometry.groups.map((g) => [g.start, g.count, g.materialIndex]) }; })())`));
await shot("slots");
return { target: TARGET, picked, slots: o.materials, file_has_material_index: !!side.material_index, view };

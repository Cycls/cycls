// A big scene (thousands of objects): does it open, draw, and stay interactive? Frames
// everything, waits for the mesh files, and times a few full redraws.
await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false }, page);
await goto("http://127.0.0.1:8094/");
const t0 = Date.now();
let ready = null;
for (let i = 0; i < 120 && !ready; i++) {
  await sleep(1000);
  ready = await evalApp(`(() => { const s = __studio.state; return s.doc && !s.busy ? Object.keys(s.doc.objects).length : null; })()`).catch(() => null);
}
const S = (expr) => evalApp(`JSON.stringify(${expr})`).then(JSON.parse);
await click(700, 880);
await key("Home");
await sleep(8000);                                   // mesh files stream in; Blender shapes the modified ones
const out = { objects: ready, open_s: Math.round((Date.now() - t0) / 100) / 10 };
out.nodes = await S(`__studio.viewport.nodes.size`);
out.draw_ms = await S(`(() => { const vp = __studio.viewport; const t = []; for (let i = 0; i < 5; i++) {
  const a = performance.now(); vp.renderer.render(vp.scene, vp.camera); vp.renderer.getContext().finish(); t.push(performance.now() - a); }
  return t.map((x) => Math.round(x)); })()`);
out.calls = await S(`__studio.viewport.renderer.info.render.calls`);
out.status = await S(`{ status: __studio.state.status, busy: __studio.state.busy, toast: __studio.state.toast && __studio.state.toast.text }`);
await shot("big-scene");
return out;

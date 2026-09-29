await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 535, deviceScaleFactor: 1, mobile: false }, page);
await goto("http://127.0.0.1:8094/");
await sleep(3500);
const r = await evalApp(`(() => {
  const vp = __studio.viewport;
  vp.throughCamera(__studio.state.doc);
  vp.scene.children.forEach((c) => { if (c.type === "GridHelper" || c.type === "Line") c.visible = false; });
  vp.touch();
  const b = vp.renderer.domElement.getBoundingClientRect();
  return [b.left, b.top, b.width, b.height];
})()`);
await sleep(800);
return await shot(globalThis.NAME || "probe", { x: r[0], y: r[1], width: r[2], height: r[3] });

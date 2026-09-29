// Figma's plugin API takes `lineHeight` / `letterSpacing` as { value, unit } (unit
// "PIXELS", "PERCENT" or "AUTO"). OpenPencil stores whatever it's given and its .fig
// writer then saves an object as NaN, so tracking and leading silently vanished
// (docs/quirks.md #2). This converts them to the pixel numbers the engine wants.
//
// A paint set the Figma way — `node.fills = [{ type: "SOLID", color }]` — leaves out
// what Figma defaults: `visible` (true) and `opacity` (1); a new stroke, the weight
// and align of the one it replaces (Figma keeps those on the node). OpenPencil stores
// it as given. Its .fig writer fills them in, so the saved file was right, but its
// live renderer skips a fill that isn't `visible`: an agent's edit replayed in the
// editor drew nothing until the design was reopened (docs/quirks.md #39). This
// fills in Figma's defaults.
//
// It works at the scene graph (every node setter goes through `graph.updateNode`),
// not on the node proxy: the editor's newer OpenPencil installs those accessors
// non-configurable, so they can't be redefined there.
//
// It runs before every script: engine.ts / job.ts prepend it to each script, and
// the editor bridge to each live edit — so a script behaves the same in both. Keep
// this file and editor/patches/figma-compat.js identical (a test checks). Idempotent.
function figmaCompat(figma) {
  const graph = figma.graph;
  if (!graph || graph.__cyclsCompat) return;
  const update = graph.updateNode.bind(graph);
  const object = (v) => v !== null && typeof v === "object";
  const toPx = (key, v, size) => {
    if (v.unit === "AUTO") return key === "lineHeight" ? null : 0;
    const n = Number(v.value);
    return v.unit === "PERCENT" ? (n / 100) * size : n;
  };
  const withDefaults = (list, defaults) => list.map((item) => {
    if (!object(item)) return item;
    const out = { ...item };
    for (const key in defaults) if (out[key] === undefined && defaults[key] !== undefined) out[key] = defaults[key];
    return out;
  });
  graph.updateNode = (id, changes) => {
    if (!object(changes)) return update(id, changes);
    const node = graph.getNode(id);
    if (object(changes.lineHeight) || object(changes.letterSpacing)) {
      const size = typeof changes.fontSize === "number" ? changes.fontSize
        : node && typeof node.fontSize === "number" ? node.fontSize : 16;
      changes = { ...changes };
      for (const key of ["lineHeight", "letterSpacing"])
        if (object(changes[key])) changes[key] = toPx(key, changes[key], size);
    }
    if (Array.isArray(changes.fills) || Array.isArray(changes.strokes) || Array.isArray(changes.effects)) {
      const first = node && Array.isArray(node.strokes) && object(node.strokes[0]) ? node.strokes[0] : {};
      changes = { ...changes };
      if (Array.isArray(changes.fills)) changes.fills = withDefaults(changes.fills, { visible: true, opacity: 1 });
      if (Array.isArray(changes.strokes)) changes.strokes = withDefaults(changes.strokes, {
        visible: true, opacity: 1, weight: first.weight, align: first.align,
      });
      if (Array.isArray(changes.effects)) changes.effects = withDefaults(changes.effects, { visible: true });
    }
    return update(id, changes);
  };
  Object.defineProperty(graph, "__cyclsCompat", { value: true });
}

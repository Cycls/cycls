// Figma's plugin API takes `lineHeight` / `letterSpacing` as { value, unit } (unit
// "PIXELS", "PERCENT" or "AUTO"). OpenPencil stores whatever it's given and its .fig
// writer then saves an object as NaN, so tracking and leading silently vanished
// (docs/quirks.md #2). This converts them to the pixel numbers the engine wants.
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
  const toPx = (key, v, size) => {
    if (v.unit === "AUTO") return key === "lineHeight" ? null : 0;
    const n = Number(v.value);
    return v.unit === "PERCENT" ? (n / 100) * size : n;
  };
  graph.updateNode = (id, changes) => {
    const object = (v) => v !== null && typeof v === "object";
    if (changes && (object(changes.lineHeight) || object(changes.letterSpacing))) {
      const node = graph.getNode(id);
      const size = typeof changes.fontSize === "number" ? changes.fontSize
        : node && typeof node.fontSize === "number" ? node.fontSize : 16;
      changes = { ...changes };
      for (const key of ["lineHeight", "letterSpacing"])
        if (object(changes[key])) changes[key] = toPx(key, changes[key], size);
    }
    return update(id, changes);
  };
  Object.defineProperty(graph, "__cyclsCompat", { value: true });
}

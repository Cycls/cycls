// The app's only way out of its sandbox: window.cycls (the host shim). Without it
// (vite dev, a shared view) the app still runs on an in-memory scene.
import { SCHEMA, clone } from "./doc.js";

const c = () => window.cycls;
export const hasBridge = () => typeof window.cycls === "object" && !!window.cycls;
export const canEngine = () => hasBridge() && typeof c().engine === "function";

let memory = null;

export async function ready() {
  if (hasBridge()) await c().ready;
}

export async function readScene() {
  if (!hasBridge()) return clone(memory || SCHEMA.new_scene);
  return JSON.parse(await c().read("data/scene.json"));
}

export async function writeScene(doc) {
  if (!hasBridge()) { memory = clone(doc); return; }
  await c().write("data/scene.json", JSON.stringify(doc));
}

// A file under data/ (mesh sidecars). Without a bridge there's nowhere to put it,
// and nothing that would read it back.
export async function writeData(rel, text) {
  if (!hasBridge()) return;
  await c().write(`data/${rel}`, text);
}

export async function readJSON(rel) {
  return JSON.parse(await c().read(`data/${rel}`));
}

export async function engine(op, payload) {
  if (!canEngine()) throw new Error("the Blender engine isn't reachable from here");
  const r = await c().engine(op, payload);
  if (r && r.ok === false) throw new Error(r.error || "the engine failed");
  return r;
}

export function onCommand(fn) {
  return hasBridge() && typeof c().onCommand === "function" ? c().onCommand(fn) : () => {};
}

export function publishView(view) {
  try { if (hasBridge()) c().me.set("view", view); } catch { /* best effort */ }
}

export function ask(text) {
  if (hasBridge() && typeof c().ask === "function") return c().ask(text);
  return Promise.reject(new Error("no chat here"));
}

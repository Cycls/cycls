import "./diag.js";
import { render } from "preact";
import { createApp } from "./app.js";
import { Viewport } from "./viewport.js";
import { Studio, runEditOp } from "./ui.jsx";
import "./studio.css";

const app = createApp((host, hooks) => new Viewport(host, hooks));
window.__studio = app;          // for debugging from the console of the frame

// Blender's keys, where they make sense in a browser. Ignored while typing in a field.
addEventListener("keydown", (e) => {
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
  const a = app.actions, s = app.state;
  if (!s.doc) return;
  const k = e.code, ctrl = e.ctrlKey || e.metaKey;
  const handled = () => { e.preventDefault(); e.stopPropagation(); };
  if (s.playing && k === "Escape") { a.pause(true); return handled(); }
  if (ctrl && k === "KeyZ") { e.shiftKey ? a.redo() : a.undo(); return handled(); }
  if (ctrl && k === "KeyY") { a.redo(); return handled(); }
  if (k === "Tab" && e.shiftKey && !ctrl) { a.edit.toggleSnap(); return handled(); }
  if (k === "Tab" && !ctrl && !e.altKey && !e.shiftKey) { if (!s.busy) a.edit.toggle(); return handled(); }
  if (s.mode === "edit") {
    if (s.tool) {
      if (k === "Escape") { a.edit.cancelTool(); return handled(); }
      if (s.tool.kind === "knife" && (k === "Enter" || k === "NumpadEnter" || k === "Space")) { a.edit.knife(); return handled(); }
    }
    if (k === "Space" && !ctrl) { a.play(); return handled(); }
    if (ctrl && k === "KeyR") { a.edit.startTool("loopcut"); return handled(); }
    if (ctrl && k === "KeyB") { runEditOp(a, "bevel"); return handled(); }
    if (ctrl && k === "KeyI") { a.edit.invert(); return handled(); }
    if (ctrl) return;
    const mode = { Digit1: "vert", Digit2: "edge", Digit3: "face" }[k];
    if (mode) { a.edit.setMode(mode); return handled(); }
    if (k === "KeyA") { a.edit.selectAll(!e.altKey); return handled(); }
    if (k === "Escape") { a.edit.selectAll(false); return handled(); }
    if (k === "KeyK") { a.edit.startTool("knife"); return handled(); }
    if (k === "KeyJ") { a.edit.connect(); return handled(); }
    if (k === "KeyO") { a.edit.setProportional({ on: !s.proportional.on }); return handled(); }
    const op = { KeyE: "extrude", KeyF: "fill", KeyM: "merge", KeyX: "delete", Delete: "delete", KeyI: "inset" }[k];
    if (op) { runEditOp(a, op); return handled(); }
  } else {
    if (ctrl && k === "KeyJ") { a.join(); return handled(); }
    if (ctrl) return;
    // Time: I keys, Alt+I unkeys, Space plays; ←/→ step a frame (Shift: to the ends), ↑/↓ jump key to key.
    if (k === "KeyI") { e.altKey ? a.deleteKeys() : a.insertKeys(); return handled(); }
    if (k === "Space") { a.play(); return handled(); }
    const an = s.doc.animation;
    if (k === "ArrowLeft") { a.setFrame(e.shiftKey ? an.frame_start : s.frame - 1); return handled(); }
    if (k === "ArrowRight") { a.setFrame(e.shiftKey ? an.frame_end : s.frame + 1); return handled(); }
    if (k === "ArrowUp") { a.jumpKey(1); return handled(); }
    if (k === "ArrowDown") { a.jumpKey(-1); return handled(); }
    if (k === "KeyX" || k === "Delete") { a.remove(); return handled(); }
    if (k === "KeyD" && e.shiftKey) { a.duplicate(); return handled(); }
    if (k === "KeyA" && e.shiftKey) { dispatchEvent(new CustomEvent("studio:open-menu", { detail: "Add" })); return handled(); }
    if (k === "KeyA" && e.altKey) { a.select([]); return handled(); }
    if (k === "KeyA") { a.select(Object.keys(s.doc.objects)); return handled(); }
    if (k === "Escape") { a.select([]); return handled(); }
    if (k === "KeyH") { a.hide(!e.altKey); return handled(); }
  }
  if (ctrl) return;
  if (k === "KeyG") { a.setGizmo("translate"); return handled(); }
  if (k === "KeyR") { a.setGizmo("rotate"); return handled(); }
  if (k === "KeyS" && !e.shiftKey) { a.setGizmo("scale"); return handled(); }
  if (k === "Numpad1") { a.view(e.ctrlKey ? "back" : "front"); return handled(); }
  if (k === "Numpad3") { a.view("right"); return handled(); }
  if (k === "Numpad7") { a.view("top"); return handled(); }
  if (k === "Numpad0") { a.view("camera"); return handled(); }
  if (k === "Home") { a.frame(true); return handled(); }
  if (k === "NumpadDecimal" || k === "Period") { a.frame(false); return handled(); }
  if (k === "F12") { a.render("render"); return handled(); }
});

render(<Studio app={app} />, document.getElementById("root"));

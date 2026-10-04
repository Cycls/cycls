import { useEffect, useRef } from "react";

// Escape closes one thing: the layer opened last — a menu, a popover, a dialog — and
// nothing under it. Each open layer registers here; one capture-phase listener hands
// the key to the newest and stops it there, so neither the layers beneath nor the
// page's own Escape (chat's closes the whole canvas pane) see it.
const layers: { current: () => void }[] = [];
let listening = false;

function onKeyDown(e: KeyboardEvent) {
  const top = layers[layers.length - 1];
  if (e.key !== "Escape" || e.isComposing || !top) return;
  e.preventDefault();
  e.stopPropagation();
  top.current();
}

export function useEscape(onEscape: () => void, open = true) {
  const handler = useRef(onEscape);
  handler.current = onEscape;
  useEffect(() => {
    if (!open) return;
    if (!listening) {
      window.addEventListener("keydown", onKeyDown, true);
      listening = true;
    }
    layers.push(handler);
    return () => {
      const i = layers.lastIndexOf(handler);
      if (i >= 0) layers.splice(i, 1);
    };
  }, [open]);
}

// The page's own Escape: what it does when nothing else took the key. A field or a
// list that uses Escape says so with `preventDefault` — and this looks only after
// every listener has run, so it doesn't matter which of them was added first.
export function useEscapeFallback(onEscape: () => void, active = true) {
  const handler = useRef(onEscape);
  handler.current = onEscape;
  useEffect(() => {
    if (!active) return;
    let live = true;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.isComposing) return;
      setTimeout(() => { if (live && !e.defaultPrevented) handler.current(); }, 0);
    };
    window.addEventListener("keydown", onKey);
    return () => { live = false; window.removeEventListener("keydown", onKey); };
  }, [active]);
}

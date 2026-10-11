import { useEffect, useRef } from "react";

// Escape closes only the newest layer; capture phase hides it from layers beneath and chat's canvas Escape.
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

// Runs when nothing took the key (`preventDefault`); deferred, so listener order doesn't matter.
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

import { useCallback, useEffect, useRef, useState } from "react";

// Width of a right-anchored pane, resized by dragging its left edge and
// persisted per key. `resizing` lets callers disable width animation during a
// drag.
//
// The pane never gets to squeeze the content beside it below its floor —
// `minGapLeft` px or `minGapFraction` of the viewport, whichever is larger.
// `offsetRight` is any pane docked further right (the rail sits right of the
// canvas): it measures the drag to THIS pane's edge and counts against the same
// floor, since it eats the same space.
//
// The floor is applied on every read, not only while dragging: a width restored
// from localStorage, a narrower window, or a rail that grew afterwards would all
// otherwise sail past it. The stored value stays untouched, so widening the
// window gives the preferred width back.
export function usePaneWidth(
  key: string, initial: number, min: number, minGapLeft: number,
  offsetRight = 0, onUndersize?: () => void, maxFraction = 1, minGapFraction = 0,
) {
  const [width, setWidth] = useState(() => Number(localStorage.getItem(key)) || initial);
  const [resizing, setResizing] = useState(false);
  const [, bump] = useState(0);
  const offsetRef = useRef(offsetRight);
  offsetRef.current = offsetRight;

  const clamp = useCallback((w: number) => {
    if (typeof window === "undefined") return w;
    const vw = window.innerWidth;
    const gap = Math.max(minGapLeft, vw * minGapFraction);
    return Math.max(Math.min(w, vw - gap - offsetRef.current, vw * maxFraction), min);
  }, [min, minGapLeft, maxFraction, minGapFraction]);

  // Re-clamp when the viewport changes; the stored preference is left alone.
  useEffect(() => {
    const onResize = () => bump((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const startResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    document.body.style.userSelect = "none";
    setResizing(true);
    const onMove = (ev: MouseEvent) => {
      const raw = window.innerWidth - ev.clientX - 8 - offsetRef.current;
      // Dragged well past the minimum: fold instead of pinning at min width.
      if (raw < min - 48) onUndersize?.();
      setWidth(clamp(raw));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.userSelect = "";
      setResizing(false);
      setWidth((w) => { localStorage.setItem(key, String(w)); return w; });
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [key, min, clamp, onUndersize]);

  return { width: clamp(width), startResize, resizing };
}

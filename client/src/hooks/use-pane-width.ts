import { useCallback, useRef, useState } from "react";

// Width of a right-anchored pane, resized by dragging its left edge and
// persisted per key. `minGapLeft` keeps that much viewport for the content
// beside it. `resizing` lets callers disable width animation during a drag.
// `offsetRight` is the width of any pane docked further right (the rail sits
// right of the canvas), so the drag measures to THIS pane's edge, not the
// viewport's.
export function usePaneWidth(key: string, initial: number, min: number, minGapLeft: number, offsetRight = 0,
                             onUndersize?: () => void, maxFraction = 1) {
  const [width, setWidth] = useState(() => Number(localStorage.getItem(key)) || initial);
  const [resizing, setResizing] = useState(false);
  const offsetRef = useRef(offsetRight);
  offsetRef.current = offsetRight;

  const startResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    document.body.style.userSelect = "none";
    setResizing(true);
    const onMove = (ev: MouseEvent) => {
      const raw = window.innerWidth - ev.clientX - 8 - offsetRef.current;
      // Dragged well past the minimum: fold instead of pinning at min width.
      if (raw < min - 48) onUndersize?.();
      // minGapLeft is what the content beside this pane must keep. Anything
      // docked further right eats into that too, so subtract it — otherwise the
      // chat column's floor was really `minGapLeft - railWidth`.
      setWidth(Math.min(Math.max(raw, min),
                        window.innerWidth - minGapLeft - offsetRef.current,
                        window.innerWidth * maxFraction));
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
  }, [key, min, minGapLeft]);

  // Clamp on read too: a width stored before the cap existed, or a window that
  // has since narrowed, would otherwise still hand back an oversized pane.
  const capped = typeof window === "undefined" ? width
    : Math.max(Math.min(width, window.innerWidth * maxFraction), min);
  return { width: capped, startResize, resizing };
}

import { useCallback, useEffect, useRef, useState } from "react";

// Width of a right-anchored pane, dragged by its left edge and persisted per
// key. The content beside it keeps `minGapLeft` px or `minGapFraction` of the
// viewport, whichever is larger; `offsetRight` is any pane docked further right
// and counts against the same floor. Clamped on read, so a stored width or a
// resized window can't get past it — the stored value itself is left alone.
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

import { useCallback, useState } from "react";

// Width of a right-anchored pane, resized by dragging its left edge and
// persisted per key. `minGapLeft` keeps that much viewport for the content
// beside it. `resizing` lets callers disable width animation during a drag.
export function usePaneWidth(key: string, initial: number, min: number, minGapLeft: number) {
  const [width, setWidth] = useState(() => Number(localStorage.getItem(key)) || initial);
  const [resizing, setResizing] = useState(false);

  const startResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    document.body.style.userSelect = "none";
    setResizing(true);
    const onMove = (ev: MouseEvent) =>
      setWidth(Math.min(Math.max(window.innerWidth - ev.clientX - 8, min), window.innerWidth - minGapLeft));
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

  return { width, startResize, resizing };
}

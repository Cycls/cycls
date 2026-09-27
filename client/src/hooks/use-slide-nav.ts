import { useCallback, useEffect, useState } from "react";

// Where a key moves a slide view, or null when the key isn't navigation. Shared by
// the slide viewers and present mode, so every deck pages the same way.
export function slideKeyTarget(key: string, active: number, count: number): number | null {
  if (count <= 0) return null;
  switch (key) {
    case "ArrowRight": case "ArrowDown": case "PageDown": case " ": case "Spacebar":
      return Math.min(count - 1, active + 1);
    case "ArrowLeft": case "ArrowUp": case "PageUp":
      return Math.max(0, active - 1);
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return null;
  }
}

// The active slide of a `count`-slide deck. A refetch can shrink the deck (a slide
// deleted in the editor, an agent's edit): `active` is kept on a real slide rather
// than pointing past the end (which rendered an empty stage).
export function useSlideNav(count: number, start = 0) {
  const [raw, setActive] = useState(start);
  const active = count > 0 ? Math.min(Math.max(0, raw), count - 1) : 0;
  useEffect(() => { if (raw !== active) setActive(active); }, [raw, active]);
  const go = useCallback((i: number) => setActive(count > 0 ? Math.max(0, Math.min(count - 1, i)) : 0), [count]);
  // A keydown handler for a focusable view: pages on navigation keys, else leaves
  // the event alone. (Space pages too, so it's only for non-text containers.)
  const onKey = useCallback((e: { key: string; preventDefault(): void }) => {
    const to = slideKeyTarget(e.key, active, count);
    if (to == null) return false;
    e.preventDefault();
    go(to);
    return true;
  }, [active, count, go]);
  return { active, go, onKey };
}

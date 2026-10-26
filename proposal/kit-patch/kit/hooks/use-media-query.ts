import { useEffect, useState } from "react";

/** true while the media query matches; false where matchMedia is unavailable. */
export function useMediaQuery(query: string): boolean {
  const get = () => { try { return matchMedia(query).matches; } catch { return false; } };
  const [m, setM] = useState(get);
  useEffect(() => {
    let mq: MediaQueryList;
    try { mq = matchMedia(query); } catch { return; }
    const f = () => setM(mq.matches);
    f();
    mq.addEventListener("change", f);
    return () => mq.removeEventListener("change", f);
  }, [query]);
  return m;
}

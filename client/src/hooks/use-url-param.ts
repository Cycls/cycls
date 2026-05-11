import { useEffect, useRef } from "react";

export function useUrlParam(name: string, onSeen: (value: string) => void, ready: boolean = true) {
  const seen = useRef(false);
  useEffect(() => {
    if (seen.current || !ready) return;
    const v = new URLSearchParams(window.location.search).get(name);
    if (!v) return;
    seen.current = true;
    const u = new URL(window.location.href);
    u.searchParams.delete(name);
    window.history.replaceState({}, "", u.toString());
    onSeen(v);
  }, [name, ready, onSeen]);
}

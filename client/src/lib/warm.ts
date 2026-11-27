// Waking a service before it is needed. The design editor's service (Cloud Run) goes to sleep when nobody uses
// it, and its first page then took 6–7 s to come (measured on super-dev, cycls-design-dev: an instance started at
// the click) — the person waited on it the first time they opened a design. A look at it as the app starts wakes
// it while they are still reading or typing. Once per page; what comes back isn't read (an opaque reply).
import { useEffect } from "react";

export const WARM_AFTER = 1500;   // ms after the app is up: its own first requests go first

export function warmService(base: string): void {
  const url = `${base.replace(/\/+$/, "")}/health`;
  void fetch(url, { mode: "no-cors", cache: "no-store", credentials: "omit" }).catch(() => {});
}

export function useWarmService(base: string | undefined | null): void {
  useEffect(() => {
    if (!base) return;
    const id = window.setTimeout(() => warmService(base), WARM_AFTER);
    return () => window.clearTimeout(id);
  }, [base]);
}

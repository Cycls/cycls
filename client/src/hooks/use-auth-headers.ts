import { useCallback, useRef } from "react";

// Module-level so every hook instance sends the same X-Workspace header. null = personal.
let activeWorkspace: string | null = null;

export function setActiveWorkspace(ws: string | null) {
  activeWorkspace = ws;
}

export function useAuthHeaders() {
  const getTokenRef = useRef<(() => Promise<string | null>) | null>(null);

  const setGetToken = useCallback((fn: () => Promise<string | null>) => {
    getTokenRef.current = fn;
  }, []);

  const authHeaders = useCallback(async () => {
    const h: Record<string, string> = {};
    if (getTokenRef.current) {
      const token = await getTokenRef.current();
      if (token) h["Authorization"] = `Bearer ${token}`;
    }
    if (activeWorkspace) h["X-Workspace"] = activeWorkspace;
    return h;
  }, []);

  return { setGetToken, authHeaders };
}

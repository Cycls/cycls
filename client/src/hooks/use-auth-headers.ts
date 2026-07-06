import { useCallback, useRef } from "react";

// Active workspace (multi-workspace mode). Module-level so every hook
// instance — useApi consumers, the chat stream POST, attachment uploads —
// sends the same X-Workspace header without threading state through each.
// null = personal (the server's default when the header is absent).
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

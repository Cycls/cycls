import { useCallback } from "react";

// Module-level so every hook instance sends the same X-Workspace header. null = personal.
let activeWorkspace: string | null = null;

// Module-level for the same reason: one signed-in user, one token. Held per
// instance it silently yields an unauthenticated hook — any caller App.tsx
// doesn't know to wire sends no Authorization header and just 401s.
let getToken: (() => Promise<string | null>) | null = null;

export function setActiveWorkspace(ws: string | null) {
  activeWorkspace = ws;
}

export function useAuthHeaders() {
  const setGetToken = useCallback((fn: () => Promise<string | null>) => {
    getToken = fn;
  }, []);

  const authHeaders = useCallback(async () => {
    const h: Record<string, string> = {};
    if (getToken) {
      const token = await getToken();
      if (token) h["Authorization"] = `Bearer ${token}`;
    }
    if (activeWorkspace) h["X-Workspace"] = activeWorkspace;
    return h;
  }, []);

  return { setGetToken, authHeaders };
}

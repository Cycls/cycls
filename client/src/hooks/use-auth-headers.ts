import { useCallback } from "react";

// Module-level so every hook instance sends the same X-Workspace header. null = personal.
let activeWorkspace: string | null = null;

// Module-level for the same reason: one signed-in user, one token. Held per
// instance it silently yields an unauthenticated hook — any caller App.tsx
// doesn't know to wire sends no Authorization header and just 401s.
// `fresh` asks for a token fetched now, not the cached one.
type GetToken = (fresh?: boolean) => Promise<string | null>;
let getToken: GetToken | null = null;

export function setActiveWorkspace(ws: string | null) {
  activeWorkspace = ws;
}

async function headersNow(fresh = false): Promise<Record<string, string>> {
  const h: Record<string, string> = {};
  if (getToken) {
    const token = await getToken(fresh);
    if (token) h["Authorization"] = `Bearer ${token}`;
  }
  if (activeWorkspace) h["X-Workspace"] = activeWorkspace;
  return h;
}

// A 401 retries once with a fresh token: a background tab's throttled refresh leaves the cached one stale.
// The body must be sendable twice (a string or FormData, not a stream).
export async function fetchAuthed(url: string, init: RequestInit = {}): Promise<Response> {
  const send = async (fresh: boolean) =>
    fetch(url, { ...init, headers: { ...(await headersNow(fresh)), ...(init.headers as Record<string, string> | undefined) } });
  const res = await send(false);
  return res.status === 401 && getToken ? send(true) : res;
}

export function useAuthHeaders() {
  const setGetToken = useCallback((fn: GetToken) => {
    getToken = fn;
  }, []);

  const authHeaders = useCallback(() => headersNow(), []);

  return { setGetToken, authHeaders };
}

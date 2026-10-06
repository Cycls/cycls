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

// A request that carries the signed-in user's headers. A 401 is asked once more with a
// token fetched afresh: in a tab left in the background the browser throttles the
// token's refresh, the cached one goes stale, and the first request on coming back
// failed — "Connection error: HTTP 401" — for no reason the person could see. The
// request must be one that can be sent twice (a string or FormData body, not a stream).
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

import { useCallback, useRef } from "react";

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
    return h;
  }, []);

  const getToken = useCallback(async () => {
    if (getTokenRef.current) return getTokenRef.current();
    return null;
  }, []);

  return { setGetToken, authHeaders, getToken };
}

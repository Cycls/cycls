import { useCallback } from "react";
import { useAuthHeaders } from "./use-auth-headers";

// Auth + JSON-aware fetch. Pass `json` for a JSON body (sets Content-Type and
// stringifies); pass `body` directly for FormData/etc. Throws Error("HTTP
// <status>") on non-OK, with `.status` on the error for callers that branch.
export function useApi(baseUrl: string = "") {
  const { setGetToken, authHeaders } = useAuthHeaders();
  const api = useCallback(async (path: string, init: RequestInit & { json?: unknown } = {}): Promise<Response> => {
    const { json, headers: rawHeaders, ...rest } = init;
    const headers: Record<string, string> = { ...(await authHeaders()), ...(rawHeaders as Record<string, string> || {}) };
    let body = rest.body;
    if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(json);
    }
    const res = await fetch(`${baseUrl}${path}`, { ...rest, headers, body });
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}`) as Error & { status: number };
      err.status = res.status;
      throw err;
    }
    return res;
  }, [baseUrl, authHeaders]);
  return { api, authHeaders, setGetToken };
}

import { useCallback } from "react";
import { useAuthHeaders } from "./use-auth-headers";
import { useToast } from "../lib/toast";

// FastAPI puts the human reason under `{detail: "..."}`. statusText is unset on
// HTTP/2 (so the browser's reason-phrase column is often blank), so reach into
// the body. Falls back to statusText, then the bare code.
export async function reasonOf(res: Response): Promise<string> {
  try {
    const data = await res.clone().json();
    if (typeof data?.detail === "string") return data.detail;
  } catch { /* not JSON */ }
  return res.statusText || `HTTP ${res.status}`;
}

// Auth + JSON-aware fetch. Pass `json` for a JSON body (sets Content-Type and
// stringifies); pass `body` directly for FormData/etc. Throws Error("HTTP
// <status>") on non-OK, with `.status` on the error. Non-OK also fires a
// top-center error toast; pass `silent: true` to suppress when the caller is
// already handling the failure path (e.g., expected-404 polling).
export function useApi(baseUrl: string = "") {
  const { setGetToken, authHeaders } = useAuthHeaders();
  const { error } = useToast();
  const api = useCallback(async (path: string, init: RequestInit & { json?: unknown; silent?: boolean } = {}): Promise<Response> => {
    const { json, silent, headers: rawHeaders, ...rest } = init;
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
      if (!silent) error(await reasonOf(res));
      throw err;
    }
    return res;
  }, [baseUrl, authHeaders, error]);
  return { api, authHeaders, setGetToken };
}

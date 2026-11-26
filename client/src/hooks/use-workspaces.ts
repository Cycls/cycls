import { useCallback, useState } from "react";
import { useApi } from "./use-api";

// What a search finds in every workspace you may enter, each hit naming its own (GET /search).
export interface Everywhere {
  workspaces: { id: string; name: string; icon?: string }[];
  chats: { id: string; title: string; updatedAt: string; ws: string }[];
  files: { name: string; path: string; ws: string }[];
  apps: { slug: string; name: string; description: string; ws: string }[];
}

export interface WorkspaceInfo {
  id: string;
  name: string;
  type: "personal" | "team";
  role: string | null;
  builtin?: string;
  icon?: string;   // Notion-style icon (emoji today); absent → client default
}

export interface MemberInfo {
  user_id: string;
  role: string;
}

// The list each account and org had last: a workspace switch remounts the app, which shows it at once, then the fresh one.
const known = new Map<string, WorkspaceInfo[]>();

export function useWorkspaces(baseUrl: string = "", account: string = "") {
  const { api, setGetToken } = useApi(baseUrl);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>(() => known.get(account) ?? []);

  const list = useCallback(async (): Promise<WorkspaceInfo[]> => {
    const rows = await (await api("/workspaces", { silent: true })).json();
    known.set(account, rows);
    setWorkspaces(rows);
    return rows;
  }, [api, account]);

  const create = useCallback(async (name: string): Promise<WorkspaceInfo> => {
    const row = await (await api("/workspaces", { method: "POST", json: { name } })).json();
    await list();
    return row;
  }, [api, list]);

  const update = useCallback(async (id: string, patch: { name?: string; icon?: string }): Promise<WorkspaceInfo> => {
    const row = await (await api(`/workspaces/${id}`, { method: "PATCH", json: patch })).json();
    await list();
    return row;
  }, [api, list]);

  const remove = useCallback(async (id: string) => {
    await api(`/workspaces/${id}`, { method: "DELETE" });
    await list();
  }, [api, list]);

  const members = useCallback(async (id: string): Promise<MemberInfo[]> =>
    (await api(`/workspaces/${id}/members`, { silent: true })).json(), [api]);

  const setMember = useCallback(async (id: string, userId: string, role: string) => {
    await api(`/workspaces/${id}/members/${userId}`, { method: "PUT", json: { role } });
  }, [api]);

  const removeMember = useCallback(async (id: string, userId: string) => {
    await api(`/workspaces/${id}/members/${userId}`, { method: "DELETE" });
  }, [api]);

  const search = useCallback(async (q: string, ws?: string): Promise<Everywhere> =>
    (await api(`/search?q=${encodeURIComponent(q)}${ws ? `&ws=${encodeURIComponent(ws)}` : ""}`, { silent: true })).json(), [api]);

  return { workspaces, list, create, update, remove, members, setMember, removeMember, search, setGetToken };
}

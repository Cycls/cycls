import { useCallback, useState } from "react";
import { useApi } from "./use-api";

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

export function useWorkspaces(baseUrl: string = "") {
  const { api, setGetToken } = useApi(baseUrl);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);

  const list = useCallback(async (): Promise<WorkspaceInfo[]> => {
    const rows = await (await api("/workspaces", { silent: true })).json();
    setWorkspaces(rows);
    return rows;
  }, [api]);

  const create = useCallback(async (name: string): Promise<WorkspaceInfo> => {
    const row = await (await api("/workspaces", { method: "POST", json: { name } })).json();
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

  return { workspaces, list, create, remove, members, setMember, removeMember, setGetToken };
}

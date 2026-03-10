import { useState, useCallback } from "react";
import { useAuthHeaders } from "./use-auth-headers";

export interface FileEntry {
  name: string;
  type: "file" | "directory";
  size: number;
  modified: string;
}

export function useFiles(baseUrl: string = "") {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const { setGetToken, authHeaders, getToken } = useAuthHeaders();

  const list = useCallback(async (dir: string = "") => {
    setLoading(true);
    try {
      const h = await authHeaders();
      const q = dir ? `?path=${encodeURIComponent(dir)}` : "";
      const res = await fetch(`${baseUrl}/files${q}`, { headers: h });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setEntries(data);
      setPath(dir);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [baseUrl, authHeaders]);

  const upload = useCallback(async (dir: string, file: File) => {
    const h = await authHeaders();
    const filePath = dir ? `${dir}/${file.name}` : file.name;
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${baseUrl}/files/${filePath}`, {
      method: "PUT",
      headers: h,
      body: form,
    });
    if (!res.ok) throw new Error(`${res.status}`);
  }, [baseUrl, authHeaders]);

  const mkdir = useCallback(async (dir: string, name: string) => {
    const h = await authHeaders();
    const dirPath = dir ? `${dir}/${name}` : name;
    const res = await fetch(`${baseUrl}/files/${dirPath}`, {
      method: "POST",
      headers: h,
    });
    if (!res.ok) throw new Error(`${res.status}`);
  }, [baseUrl, authHeaders]);

  const rename = useCallback(async (from: string, to: string) => {
    const h = await authHeaders();
    h["Content-Type"] = "application/json";
    const res = await fetch(`${baseUrl}/files/${from}`, {
      method: "PATCH",
      headers: h,
      body: JSON.stringify({ to }),
    });
    if (!res.ok) throw new Error(`${res.status}`);
  }, [baseUrl, authHeaders]);

  const remove = useCallback(async (filePath: string) => {
    const h = await authHeaders();
    const res = await fetch(`${baseUrl}/files/${filePath}`, {
      method: "DELETE",
      headers: h,
    });
    if (!res.ok) throw new Error(`${res.status}`);
  }, [baseUrl, authHeaders]);

  const openFile = useCallback(async (filePath: string) => {
    const token = await getToken();
    if (token) return `${baseUrl}/files/${filePath}?token=${encodeURIComponent(token)}`;
    return `${baseUrl}/files/${filePath}`;
  }, [baseUrl, getToken]);

  return { entries, path, loading, list, upload, mkdir, rename, remove, openFile, setGetToken };
}

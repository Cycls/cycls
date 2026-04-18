import { useState, useCallback } from "react";
import { useAuthHeaders } from "./use-auth-headers";
import { track } from "../lib/posthog";

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
    if (!res.ok) {
      track("file_upload_failed", {
        file_name: file.name,
        file_type: file.type,
        file_size: file.size,
        context: "files_panel",
        status: res.status,
      });
      throw new Error(`${res.status}`);
    }
    track("file_uploaded", {
      file_name: file.name,
      file_type: file.type,
      file_size: file.size,
      context: "files_panel",
    });
  }, [baseUrl, authHeaders]);

  const mkdir = useCallback(async (dir: string, name: string) => {
    const h = await authHeaders();
    const dirPath = dir ? `${dir}/${name}` : name;
    const res = await fetch(`${baseUrl}/files/${dirPath}`, {
      method: "POST",
      headers: h,
    });
    if (!res.ok) throw new Error(`${res.status}`);
    track("folder_created", { path: dirPath });
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
    track("file_renamed", { from, to });
  }, [baseUrl, authHeaders]);

  const remove = useCallback(async (filePath: string) => {
    const h = await authHeaders();
    const res = await fetch(`${baseUrl}/files/${filePath}`, {
      method: "DELETE",
      headers: h,
    });
    if (!res.ok) throw new Error(`${res.status}`);
    track("file_deleted", { path: filePath });
  }, [baseUrl, authHeaders]);

  const openFile = useCallback(async (filePath: string) => {
    const token = await getToken();
    if (token) return `${baseUrl}/files/${filePath}?token=${encodeURIComponent(token)}`;
    return `${baseUrl}/files/${filePath}`;
  }, [baseUrl, getToken]);

  return { entries, path, loading, list, upload, mkdir, rename, remove, openFile, setGetToken };
}

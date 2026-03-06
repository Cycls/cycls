import { useState, useCallback, useRef } from "react";

export interface FileEntry {
  name: string;
  type: "file" | "directory";
  size: number;
  modified: string;
}

export function useFiles(baseUrl: string = "/api") {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const getTokenRef = useRef<(() => Promise<string | null>) | null>(null);

  const setGetToken = useCallback((fn: () => Promise<string | null>) => {
    getTokenRef.current = fn;
  }, []);

  const headers = useCallback(async () => {
    const h: Record<string, string> = {};
    if (getTokenRef.current) {
      const token = await getTokenRef.current();
      if (token) h["Authorization"] = `Bearer ${token}`;
    }
    return h;
  }, []);

  const list = useCallback(async (dir: string = "") => {
    setLoading(true);
    try {
      const h = await headers();
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
  }, [baseUrl, headers]);

  const upload = useCallback(async (dir: string, file: File) => {
    const h = await headers();
    const filePath = dir ? `${dir}/${file.name}` : file.name;
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${baseUrl}/files/${filePath}`, {
      method: "PUT",
      headers: h,
      body: form,
    });
    if (!res.ok) throw new Error(`${res.status}`);
  }, [baseUrl, headers]);

  const mkdir = useCallback(async (dir: string, name: string) => {
    const h = await headers();
    const dirPath = dir ? `${dir}/${name}` : name;
    const res = await fetch(`${baseUrl}/files/${dirPath}`, {
      method: "POST",
      headers: h,
    });
    if (!res.ok) throw new Error(`${res.status}`);
  }, [baseUrl, headers]);

  const rename = useCallback(async (from: string, to: string) => {
    const h = await headers();
    h["Content-Type"] = "application/json";
    const res = await fetch(`${baseUrl}/files/${from}`, {
      method: "PATCH",
      headers: h,
      body: JSON.stringify({ to }),
    });
    if (!res.ok) throw new Error(`${res.status}`);
  }, [baseUrl, headers]);

  const remove = useCallback(async (filePath: string) => {
    const h = await headers();
    const res = await fetch(`${baseUrl}/files/${filePath}`, {
      method: "DELETE",
      headers: h,
    });
    if (!res.ok) throw new Error(`${res.status}`);
  }, [baseUrl, headers]);

  const openFile = useCallback(async (filePath: string) => {
    if (getTokenRef.current) {
      const token = await getTokenRef.current();
      if (token) return `${baseUrl}/files/${filePath}?token=${encodeURIComponent(token)}`;
    }
    return `${baseUrl}/files/${filePath}`;
  }, [baseUrl]);

  return { entries, path, loading, list, upload, mkdir, rename, remove, openFile, setGetToken };
}

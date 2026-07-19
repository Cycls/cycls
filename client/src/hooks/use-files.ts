import { useState, useCallback } from "react";
import { zip } from "fflate";
import { useApi } from "./use-api";
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
  const { api, setGetToken } = useApi(baseUrl);

  const list = useCallback(async (dir: string = "") => {
    setLoading(true);
    try {
      const q = dir ? `?path=${encodeURIComponent(dir)}` : "";
      setEntries(await (await api(`/files${q}`)).json());
      setPath(dir);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Raw body, not multipart — auth runs before the body is read, so slow uploads can't outlive the JWT.
  const upload = useCallback(async (dir: string, file: File) => {
    const filePath = dir ? `${dir}/${file.name}` : file.name;
    const meta = { file_name: file.name, file_type: file.type, file_size: file.size, context: "files_panel" };
    try {
      await api(`/files/${filePath}`, { method: "PUT", body: file });
    } catch (err) {
      track("file_upload_failed", { ...meta, status: (err as Error & { status?: number }).status });
      throw err;
    }
    track("file_uploaded", meta);
  }, [api]);

  // Zip small files client-side — one request per group instead of one per file.
  const uploadBatch = useCallback(async (dir: string, files: { rel: string; file: File }[]) => {
    const entries: Record<string, [Uint8Array, { level: 0 | 1 }]> = {};
    for (const { rel, file } of files) entries[rel] = [new Uint8Array(await file.arrayBuffer()), { level: 1 }];
    const data = await new Promise<Uint8Array>((resolve, reject) =>
      zip(entries, (err, out) => (err ? reject(err) : resolve(out))));
    const meta = { file_count: files.length, batch_bytes: data.length, context: "files_panel" };
    try {
      await api(`/files-batch/${dir}`, { method: "POST", body: new Blob([data as BlobPart]) });
    } catch (err) {
      track("file_upload_failed", { ...meta, status: (err as Error & { status?: number }).status });
      throw err;
    }
    track("file_uploaded", meta);
  }, [api]);

  const mkdir = useCallback(async (dir: string, name: string) => {
    const dirPath = dir ? `${dir}/${name}` : name;
    await api(`/files/${dirPath}`, { method: "POST" });
    track("folder_created", { path: dirPath });
  }, [api]);

  const rename = useCallback(async (from: string, to: string) => {
    await api(`/files/${from}`, { method: "PATCH", json: { to } });
    track("file_renamed", { from, to });
  }, [api]);

  const remove = useCallback(async (filePath: string) => {
    await api(`/files/${filePath}`, { method: "DELETE" });
    track("file_deleted", { path: filePath });
  }, [api]);

  // /files is bearer-only (JWTs in URLs leak via history/logs/Referer), so
  // <img src> / window.open can't hit it directly. Fetch with auth + return
  // a blob URL the browser can render in any context.
  const openFile = useCallback(async (filePath: string) => {
    return URL.createObjectURL(await (await api(`/files/${filePath}`)).blob());
  }, [api]);

  // Authed text fetch — the canvas renders md/html from source, not a blob URL.
  const readFile = useCallback(async (filePath: string) => {
    return (await api(`/files/${filePath}`)).text();
  }, [api]);

  // Overwrite a text file from the canvas editor.
  const writeFile = useCallback(async (filePath: string, text: string) => {
    await api(`/files/${filePath}`, { method: "PUT", body: new Blob([text]) });
    track("file_saved", { path: filePath });
  }, [api]);

  // Workspace files matching a query — backs the @-mention picker in the
  // composer. Recursive: matches nested paths like folder/sub/file.md too.
  const searchFiles = useCallback(async (query: string) => {
    try {
      const all = (await (await api(`/files?recursive=1`)).json()) as (FileEntry & { path: string })[];
      const q = query.toLowerCase();
      return all
        .filter((e) => e.type === "file" && e.path.toLowerCase().includes(q))
        .slice(0, 12)
        .map((e) => ({ name: e.name, path: e.path }));
    } catch {
      return [];
    }
  }, [api]);

  // All folders in the workspace — backs the "Move to…" destination picker.
  const listFolders = useCallback(async () => {
    try {
      const all = (await (await api(`/files?recursive=1`)).json()) as (FileEntry & { path: string })[];
      return all.filter((e) => e.type === "directory").map((e) => ({ name: e.name, path: e.path }));
    } catch {
      return [];
    }
  }, [api]);

  const shareFile = useCallback(async (filePath: string, audience: string = "public") => {
    const { url } = await (await api("/share", { method: "POST", json: { path: `file/${filePath}`, audience } })).json();
    track("file_shared", { path: filePath, audience });
    return `${window.location.origin}${url}`;
  }, [api]);

  return { entries, path, loading, list, upload, uploadBatch, mkdir, rename, remove, openFile, readFile, writeFile, searchFiles, listFolders, shareFile, setGetToken };
}

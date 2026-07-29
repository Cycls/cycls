import { useState, useCallback } from "react";
import { zip } from "fflate";
import { useApi } from "./use-api";
import { track } from "../lib/posthog";

export interface FileEntry {
  name: string;
  type: "file" | "directory";
  size: number;
  modified: string;
  // Render class decided server-side, so web and mobile agree on what can be
  // previewed. Absent from servers older than the change — callers fall back.
  kind?: string;
}

// Same predicate the server applies, for servers that don't apply it yet.
// NFC because a browser-typed query and a name off the mount can differ in
// normal form and never compare equal — routine with Arabic.
const fold = (s: string) => s.normalize("NFC").toLowerCase();
export const matchTokens = (path: string, tokens: string[]) =>
  tokens.every((t) => fold(path).includes(t));

export function useFiles(baseUrl: string = "") {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const { api, setGetToken } = useApi(baseUrl);

  // `fresh` skips the server's catalog cache. Worth it right after our own
  // write (serving is serverless, so another instance may have handled it and
  // this one never saw the invalidation) and after an agent turn, since the
  // agent writes through its sandbox rather than these routes.
  const list = useCallback(async (dir: string = "", opts?: { fresh?: boolean }) => {
    setLoading(true);
    try {
      const q = new URLSearchParams();
      if (dir) q.set("path", dir);
      if (opts?.fresh) q.set("fresh", "1");
      const qs = q.toString();
      setEntries(await (await api(`/files${qs ? `?${qs}` : ""}`)).json());
      setPath(dir);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  const reload = useCallback((dir: string = "") => list(dir, { fresh: true }), [list]);

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

  // Backs the composer's @-picker. The server matches, ranks and caps, so this
  // and the mobile client can't disagree about what a query means; `recursive=1`
  // rides along so a server predating `search` still returns a tree we can
  // filter here. X-Files-Search tells the two apart — guessing from the shape of
  // the response would misread a small workspace as a filtered result.
  const searchFiles = useCallback(async (query: string) => {
    // No early return on a blank query: a bare "@" browses. matchTokens with no
    // tokens matches everything, which is what the fallback path needs.
    const tokens = fold(query).split(/\s+/).filter(Boolean);
    try {
      const res = await api(`/files?recursive=1&search=${encodeURIComponent(query)}`);
      const all = (await res.json()) as (FileEntry & { path: string })[];
      const ranked = res.headers.get("X-Files-Search") === "1"
        ? all
        : all.filter((e) => e.type === "file" && matchTokens(e.path, tokens)).slice(0, 12);
      return ranked.map((e) => ({ name: e.name, path: e.path, kind: e.kind }));
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

  return { entries, path, loading, list, reload, upload, uploadBatch, mkdir, rename, remove, openFile, readFile, writeFile, searchFiles, listFolders, shareFile, setGetToken };
}

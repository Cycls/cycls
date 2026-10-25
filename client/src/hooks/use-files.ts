import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { zip } from "fflate";
import { voteUrl, type PollApi } from "../lib/polls";
import type { CommentsApi } from "../lib/comments";
import { useApi } from "./use-api";
import { track } from "../lib/analytics";
import type { TrashRow } from "../components/trash-view";

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

// Apps get their own surface, so the browser hides `apps/` at the root.
// Nested folders called "apps" are ordinary content and stay visible.
const APPS_DIR = "apps";
const hideApps = (dir: string, list: FileEntry[]) =>
  dir === "" ? list.filter((e) => !(e.type === "directory" && e.name === APPS_DIR)) : list;

// Each segment encoded (names may hold #, ?, %); a caller's `?as=` / `?download` query kept.
export function encPath(path: string): string {
  const q = path.search(/\?(as|download)(=|&|$)/);
  const [bare, query] = q >= 0 ? [path.slice(0, q), path.slice(q)] : [path, ""];
  return bare.split("/").map(encodeURIComponent).join("/") + query;
}

// brand/brand.yaml, as the design editor takes it.
export type BrandKit = { colors?: Record<string, string>; fonts?: { heading?: string | null; body?: string | null } };
// A design's earlier version (cycls/_agent/versions.py).
// `who`: the person whose write replaced it (a team workspace's history says whose change); `mine`: was that the viewer.
export type DesignVersion = { id: string; at: string; by: string; reason: string; intent?: string; size: number;
  who?: { id: string; name?: string }; mine?: boolean };
// `base`: the version a design's save started from.
export type WriteOpts = { silent?: boolean; base?: string; force?: boolean };
export type WriteFile = (path: string, data: BlobPart, opts?: boolean | WriteOpts) => Promise<{ version?: string } | void>;
// A design's live room and one person's pass for it (the server's /design/live).
export type DesignLive = { room: string; url: string; ticket: string; epoch: string };
export type FetchVersioned = (path: string) => Promise<{ url: string; version: string }>;
// The video editor's server side (web/video_routes.py).
export type VideoEditorSession = { url: string; sid: string; versions: Record<string, string>; notice?: string };
export type VideoRenderState = { state: "idle" | "rendering" | "done" | "failed"; progress?: number; path?: string; message?: string };
export type VideoEditorApi = {
  open: (path: string) => Promise<VideoEditorSession>;
  replace: (path: string, sid: string) => Promise<void>;
  close: (sid: string) => Promise<void>;
  render: (path: string, quality: "draft" | "standard" | "final") => Promise<VideoRenderState>;
  renderState: (path: string) => Promise<VideoRenderState>;
  readText: (path: string) => Promise<{ text: string; version: string }>;
};

// Cycls Sheets and Cycls Docs: may this workspace open the file in the editor, and where from.
export type OfficeOpen = { editor: true; url: string; name: string } | { editor: false; reason: string };
export type SheetsNotice = { kind: string; sheet?: string; message: string };
// What the editor opens: the workbook as the service read it (cached by version).
export type SheetsOpened = {
  version: string;
  modified?: string;
  snapshot: Record<string, unknown>;
  notices: SheetsNotice[];
  activeSheet?: string;
  readonly?: boolean;   // a Word document with tracked changes: view only
};
export type OfficeEditorApi = {
  sheets: (path: string) => Promise<OfficeOpen>;
  sheetsOpen: (path: string) => Promise<SheetsOpened>;
  // The file's version now (an open editor checks it once the file may have changed some other way).
  sheetsVersion?: (path: string) => Promise<{ version: string; modified?: string }>;
  pdf: (path: string) => Promise<string>;   // a blob URL of the file as PDF (the office-render service)
  // The editor's workbook written back into the file (only what differs changes). A file changed since
  // `base` answers {conflict: <its version>} instead.
  sheetsSave: (path: string, base: string, payload: { snapshot: unknown; ops: unknown[] }, force?: boolean, trail?: string[]) => Promise<SheetsSaved>;
  // Cycls Docs, the same four for a .docx (GET /office/docs…).
  docs?: (path: string) => Promise<OfficeOpen>;
  docsOpen?: (path: string) => Promise<SheetsOpened>;
  docsVersion?: (path: string) => Promise<{ version: string; modified?: string }>;
  docsSave?: (path: string, base: string, payload: { snapshot: unknown; ops: unknown[] }, force?: boolean, trail?: string[]) => Promise<SheetsSaved>;
};
export type SheetsSaved = { version: string; unchanged: boolean; modified?: string } | { conflict: string };

async function gzipJson(value: unknown): Promise<Blob> {
  const json = new Blob([JSON.stringify(value)], { type: "application/json" });
  if (typeof CompressionStream === "undefined") return json;
  return new Response(json.stream().pipeThrough(new CompressionStream("gzip"))).blob();
}

export function useFiles(baseUrl: string = "") {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [path, setPath] = useState("");
  const [loading, setLoading] = useState(false);
  const { api, authHeaders, setGetToken } = useApi(baseUrl);

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
      setEntries(hideApps(dir, await (await api(`/files${qs ? `?${qs}` : ""}`)).json()));
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
      await api(`/files/${encPath(filePath)}`, { method: "PUT", body: file });
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
      await api(`/files-batch/${encPath(dir)}`, { method: "POST", body: new Blob([data as BlobPart]) });
    } catch (err) {
      track("file_upload_failed", { ...meta, status: (err as Error & { status?: number }).status });
      throw err;
    }
    track("file_uploaded", meta);
  }, [api]);

  const mkdir = useCallback(async (dir: string, name: string) => {
    const dirPath = dir ? `${dir}/${name}` : name;
    await api(`/files/${encPath(dirPath)}`, { method: "POST" });
    track("folder_created", { path: dirPath });
  }, [api]);

  const rename = useCallback(async (from: string, to: string) => {
    await api(`/files/${encPath(from)}`, { method: "PATCH", json: { to } });
    track("file_renamed", { from, to });
  }, [api]);

  // A delete is a move into the workspace trash (docs/notes/trash.md).
  const remove = useCallback(async (filePath: string) => {
    const r = (await (await api(`/files/${encPath(filePath)}`, { method: "DELETE" })).json()) as { trash_id: string; kind: string };
    track("file_deleted", { path: filePath, kind: r.kind, by: "user", permanent: false });
    return r;
  }, [api]);

  const listTrash = useCallback(async () => (await (await api("/trash")).json()) as TrashRow[], [api]);

  const restoreTrash = useCallback(async (id: string, kind: string, method: string) => {
    const r = (await (await api(`/trash/${id}/restore`, { method: "POST" })).json()) as { path: string };
    track("trash_restored", { kind, method });
    return r.path;
  }, [api]);

  const purgeTrash = useCallback(async (id: string, kind: string) => {
    await api(`/trash/${id}`, { method: "DELETE" });
    track("trash_purged", { kind, all: false });
  }, [api]);

  const emptyTrash = useCallback(async () => {
    await api("/trash", { method: "DELETE" });
    track("trash_purged", { all: true });
  }, [api]);

  // /files is bearer-only (JWTs in URLs leak via history/logs/Referer), so
  // <img src> / window.open can't hit it directly. Fetch with auth + return
  // a blob URL the browser can render in any context. `silent` suppresses the
  // error toast for an expected-and-handled failure — e.g. an Office ?as=pdf
  // conversion when the converter is down, which falls back to the download card.
  const openFile = useCallback(async (filePath: string, silent = false) => {
    return URL.createObjectURL(await (await api(`/files/${encPath(filePath)}`, { silent })).blob());
  }, [api]);

  // Authed text fetch — the canvas renders md/html from source, not a blob URL.
  // `silent` suppresses the error toast: an app reading a file that does not
  // exist yet (its key-value store, an optional data file) is normal, and the
  // failure is already reported back to it over the bridge.
  const readFile = useCallback(async (filePath: string, silent = false) => {
    return (await api(`/files/${encPath(filePath)}`, { silent })).text();
  }, [api]);

  // An app's live call to a connector's API. The token stays on the server: it resolves the
  // workspace's grant per call, so a refreshed one is picked up with no change in the app.
  const fetchConnector = useCallback(async (name: string, path: string,
                                            init: { method: string; headers: Record<string, string>; body?: string }) => {
    // Raw fetch, not `api`: a 4xx from the provider is an answer the app has to read,
    // not an exception, and it must never raise a toast over someone's dashboard.
    const res = await fetch(`${baseUrl}/connectors/${name}/fetch/${String(path).replace(/^\/+/, "")}`, {
      method: init.method, body: init.body,
      headers: { ...(await authHeaders()), ...init.headers },
    });
    return { status: res.status, body: await res.text(), contentType: res.headers.get("content-type") || "" };
  }, [baseUrl, authHeaders]);

  // An app's rows. Raw fetch, like the connector relay: a 403 from the role gate
  // is an answer the app renders, not a toast over someone's dashboard.
  const appData = useCallback(async (slug: string, op: Record<string, unknown>) => {
    const kind = String(op.op || "get");
    const q = new URLSearchParams();
    if (op.who) q.set("who", String(op.who));
    if (kind === "list" && op.prefix) q.set("prefix", String(op.prefix));
    if (kind === "put" && op.version !== undefined) q.set("version", String(op.version));
    const key = kind === "list" ? "" : `/${String(op.key ?? "").replace(/^\/+/, "")}`;
    const method = kind === "put" ? "PUT" : kind === "delete" ? "DELETE" : "GET";
    const query = q.toString();
    const res = await fetch(`${baseUrl}/apps/${slug}/data${key}${query ? `?${query}` : ""}`, {
      method,
      headers: { ...(await authHeaders()), ...(method === "PUT" ? { "content-type": "application/json" } : {}) },
      body: method === "PUT" ? JSON.stringify(op.value ?? null) : undefined,
    });
    if (res.status === 404) return null;
    // 412 is the CAS answer, not a failure — the caller re-reads and retries.
    if (!res.ok) throw Object.assign(new Error(`${res.status} ${(await res.text()).slice(0, 200)}`),
                                     { status: res.status });
    return res.json();
  }, [baseUrl, authHeaders]);

  // Text or binary (the design editor writes .fig bytes). A stale `base` gets a 412; `force` writes anyway.
  const writeFile = useCallback(async (filePath: string, data: BlobPart,
                                       opts: boolean | { silent?: boolean; base?: string; force?: boolean } = false) => {
    const { silent = false, base, force } = typeof opts === "boolean" ? { silent: opts } : opts;
    const q = new URLSearchParams();
    if (base) q.set("base", base);
    if (force) q.set("force", "1");
    const res = await api(`/files/${encPath(filePath)}${q.size ? `?${q}` : ""}`, { method: "PUT", body: new Blob([data]), silent });
    track("file_saved", { path: filePath });
    try {
      return (await res.json()) as { version?: string };
    } catch {
      return {};
    }
  }, [api]);

  // X-Version is what the design's saves name as `base`.
  const fetchVersioned = useCallback(async (filePath: string) => {
    const res = await api(`/files/${encPath(filePath)}`, { silent: true });
    return { url: URL.createObjectURL(await res.blob()), version: res.headers.get("X-Version") ?? "" };
  }, [api]);

  // The video editor's routes (web/video_routes.py): a session for a composition, the agent's edit
  // handed to it, its close, and a render it asks for; and a composition's text with its version.
  const videoEditor = useMemo<VideoEditorApi>(() => ({
    open: async (filePath) =>
      (await api(`/video/editor?path=${encodeURIComponent(filePath)}`, { method: "POST", silent: true })).json(),
    replace: async (filePath, sid) => {
      await api(`/video/editor?path=${encodeURIComponent(filePath)}&sid=${encodeURIComponent(sid)}`, { method: "PUT", silent: true });
    },
    close: async (sid) => {
      await api(`/video/editor?sid=${encodeURIComponent(sid)}`, { method: "DELETE", silent: true }).catch(() => {});
    },
    render: async (filePath, quality) =>
      (await api(`/video/render?path=${encodeURIComponent(filePath)}&quality=${quality}`, { method: "POST", silent: true })).json(),
    renderState: async (filePath) =>
      (await api(`/video/render?path=${encodeURIComponent(filePath)}`, { silent: true })).json(),
    readText: async (filePath) => {
      const res = await api(`/files/${encPath(filePath)}`, { silent: true });
      return { text: await res.text(), version: res.headers.get("X-Version") ?? "" };
    },
  }), [api]);

  const officeEditor = useMemo<OfficeEditorApi>(() => {
    // The same four calls for each editor, under /office/<product>.
    const check = (product: string) => async (filePath: string): Promise<OfficeOpen> =>
      (await api(`/office/${product}?path=${encodeURIComponent(filePath)}`, { silent: true })).json();
    const open = (product: string) => async (filePath: string): Promise<SheetsOpened> => {
      const res = await api(`/office/${product}/open?path=${encodeURIComponent(filePath)}`, { silent: true });
      const body = (await res.json()) as SheetsOpened;
      return { ...body, modified: res.headers.get("X-Modified") ?? body.modified };
    };
    const version = (product: string) => async (filePath: string): Promise<{ version: string; modified?: string }> =>
      (await api(`/office/${product}/version?path=${encodeURIComponent(filePath)}`, { silent: true })).json();
    const save = (product: string) => async (filePath: string, base: string, payload: { snapshot: unknown; ops: unknown[] }, force?: boolean, trail?: string[]): Promise<SheetsSaved> => {
      const q = new URLSearchParams({ path: filePath });
      if (base) q.set("base", base);
      if (force) q.set("force", "true");
      // The editor's trail since its last save, logged with it on the server (a header: no text in it, only names and offsets).
      const headers: Record<string, string> = {};
      if (trail?.length) {
        let lines = trail;
        let value = encodeURIComponent(JSON.stringify(lines));
        while (value.length > 7000 && lines.length > 1) value = encodeURIComponent(JSON.stringify(lines = lines.slice(0, -1)));
        if (value.length <= 7000) headers["X-Edit-Trail"] = value;
      }
      try {
        const res = await api(`/office/${product}/save?${q}`, { method: "PUT", body: await gzipJson(payload), headers, silent: true });
        track("file_saved", { path: filePath });
        return (await res.json()) as { version: string; unchanged: boolean; modified?: string };
      } catch (err) {
        if ((err as { status?: number }).status === 412) {
          const now = await (err as { response?: Response }).response?.json().then((j) => j?.version).catch(() => undefined);
          return { conflict: typeof now === "string" ? now : "" };
        }
        throw err;
      }
    };
    return {
      sheets: check("sheets"), sheetsOpen: open("sheets"), sheetsVersion: version("sheets"), sheetsSave: save("sheets"),
      docs: check("docs"), docsOpen: open("docs"), docsVersion: version("docs"), docsSave: save("docs"),
      pdf: async (filePath) =>
        URL.createObjectURL(await (await api(`/files/${encPath(filePath)}?as=pdf`)).blob()),
    };
  }, [api]);

  // null where a design opens alone, or on a server without the route.
  const designLive = useCallback(async (filePath: string) => {
    try {
      const res = await api(`/design/live?path=${encodeURIComponent(filePath)}`, { silent: true });
      return ((await res.json()) as { live: DesignLive | null }).live ?? null;
    } catch {
      return null;
    }
  }, [api]);

  // Newest first.
  const listVersions = useCallback(async (filePath: string) =>
    ((await (await api(`/versions/${encPath(filePath)}`)).json()) as { versions: DesignVersion[] }).versions, [api]);
  const versionBlob = useCallback(async (filePath: string, id: string) =>
    (await api(`/versions/${encPath(filePath)}?id=${encodeURIComponent(id)}`)).blob(), [api]);
  // A picture of the version's first slide or page.
  const versionPreview = useCallback(async (filePath: string, id: string) =>
    (await api(`/versions/${encPath(filePath)}?id=${encodeURIComponent(id)}&as=png`, { silent: true })).blob(), [api]);
  const restoreVersion = useCallback(async (filePath: string, id: string) =>
    (await (await api(`/versions/${encPath(filePath)}?restore=${encodeURIComponent(id)}`, { method: "POST" })).json()) as { version: string },
  [api]);

  // Never overwrites: the server takes the next free name (…-2, -3) and returns it.
  const writeNew = useCallback(async (filePath: string, data: BlobPart) => {
    const r = await (await api(`/files/${encPath(filePath)}?dedupe=1`, { method: "PUT", body: new Blob([data]) })).json();
    return (r as { path?: string }).path ?? filePath;
  }, [api]);

  // A blank design in designs/, of a size preset or [w, h].
  // In the folder the person is in, like any new file.
  const newDesign = useCallback(async (body: { name?: string; size?: string | [number, number]; background?: string } = {}) => {
    return (await (await api("/design/new", { method: "POST", json: { ...body, ...(path ? { folder: path } : {}) } })).json()) as { path: string; name: string; size: [number, number] };
  }, [api, path]);

  // Rendered by the design service to a file beside the design.
  const exportDesign = useCallback(async (filePath: string, format: "pdf" | "png", page?: string) => {
    const json = { path: filePath, format, ...(page ? { page } : {}) };
    return ((await (await api("/design/export", { method: "POST", json })).json()) as { path: string }).path;
  }, [api]);

  // null without a kit, or on a server without the route.
  const brand = useCallback(async (): Promise<BrandKit | null> => {
    try {
      return ((await (await api("/brand", { silent: true })).json()) as { brand: BrandKit | null }).brand;
    } catch {
      return null;
    }
  }, [api]);

  // Run on the deck's .fig by the server; slide numbers are 1-based.
  const deckOp = useCallback(async (deckPath: string, body: { op: string; number?: number; to?: number; title?: string; text?: string; notes?: string }) => {
    await api(`/deck/${encPath(deckPath)}`, { method: "POST", json: body });
  }, [api]);

  // Design comment threads (lib/comments.ts); `list` is polled quietly with the page's version.
  const comments = useMemo<CommentsApi>(() => ({
    list: async (design, version) =>
      (await api(`/comments/${encPath(design)}${version ? `?v=${encodeURIComponent(version)}` : ""}`, { silent: true })).json(),
    add: async (design, body) => (await api(`/comments/${encPath(design)}`, { method: "POST", json: body })).json(),
    change: async (design, id, body) =>
      (await api(`/comments/${encPath(design)}?id=${encodeURIComponent(id)}`, { method: "POST", json: body })).json(),
  }), [api]);

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
      return ranked
        .filter((e) => !e.path.startsWith(`${APPS_DIR}/`))
        .map((e) => ({ name: e.name, path: e.path, kind: e.kind }));
    } catch {
      return [];
    }
  }, [api]);

  // All folders in the workspace — backs the "Move to…" destination picker.
  const listFolders = useCallback(async () => {
    try {
      const all = (await (await api(`/files?recursive=1`)).json()) as (FileEntry & { path: string })[];
      return all
        .filter((e) => e.type === "directory" && e.path !== APPS_DIR && !e.path.startsWith(`${APPS_DIR}/`))
        .map((e) => ({ name: e.name, path: e.path }));
    } catch {
      return [];
    }
  }, [api]);

  const shareFile = useCallback(async (filePath: string, audience: string = "public", author: Record<string, string | undefined> = {}) => {
    const { url } = await (await api("/share", { method: "POST", json: { path: `file/${filePath}`, audience, ...author } })).json();
    track("file_shared", { path: filePath, audience });
    return `${window.location.origin}${url}`;
  }, [api]);

  // The audience votes through the deck's public share, existing or made by the presenter.
  const pollsFor = useCallback((deck: string): PollApi => ({
    open: async (slide, poll) =>
      (await api("/polls", { method: "POST", json: { deck, slide, question: poll.question, options: poll.options } })).json(),
    close: async (session) => { await api("/polls/close", { method: "POST", json: { deck, session }, silent: true }); },
    results: async (session) =>
      (await api(`/polls/results?deck=${encodeURIComponent(deck)}&session=${encodeURIComponent(session)}`, { silent: true })).json(),
    joinUrl: async () => {
      const shares = (await (await api("/share", { silent: true })).json()) as { path?: string; audience?: string; url?: string }[];
      const hit = shares.find((s) => s.path === `file/${deck}` && (s.audience ?? "public") === "public" && s.url);
      return hit ? voteUrl(`${window.location.origin}${hit.url}`) : null;
    },
    makeLink: async () => voteUrl(await shareFile(deck, "public")),
  }), [api, shareFile]);

  return { listTrash, restoreTrash, purgeTrash, emptyTrash, entries, path, loading, list, reload, upload, uploadBatch, mkdir, rename, remove, openFile, readFile, writeFile, fetchVersioned, videoEditor, officeEditor, designLive, listVersions, versionBlob, versionPreview, restoreVersion, writeNew, newDesign, exportDesign, brand, deckOp, comments, fetchConnector, appData, searchFiles, listFolders, shareFile, pollsFor, setGetToken };
}

// The agent writes through its sandbox, not these routes, so nothing invalidates
// the server's catalog when a turn produces a file. Re-list fresh when streaming
// stops — which also means a new deliverable shows up without hitting refresh.
export function useRefreshOnTurnEnd(files: ReturnType<typeof useFiles>, streaming: boolean) {
  const was = useRef(false);
  useEffect(() => {
    if (was.current && !streaming) files.reload(files.path);
    was.current = streaming;
  }, [streaming]);   // only the transition matters; reload/path are read at fire time
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDarkMode } from "../hooks/use-dark-mode";
import { useEscape } from "../hooks/use-escape";
import type { BrandKit, DesignLive, DesignVersion, FetchVersioned, WriteFile } from "../hooks/use-files";
import { track } from "../lib/analytics";
import { useComments } from "../lib/comments";
import { peerColor } from "../lib/people";
import { CommentsList, OpenComment, editorComments } from "./comments";
import { getLang, t, useLang } from "../lib/i18n";
import { useToast } from "../lib/toast";
import { cn } from "../lib/utils";

// A `.fig` in the embedded design editor, an iframe on its own origin that edits only
// this file; new documents (new design, copy, export) are written by Cycls (docs/notes/design.md).
//
// postMessage protocol 2 (cycls-design editor/patches):
//   host → editor:
//     load {protocol:2, doc, name, fig, brand?, page?, live?} · written {doc, id, ok}
//     save · flush {id} · command {script, intent?, page?} · theme {theme} · locale {lang}
//     page {name} (feature "pages") · fit (feature "fit")
//     comments {pins, adding, active, draft, me} (feature "comments")
//     follow {client} · liveTicket {id, ticket} · liveBase {version} · liveReset (feature "live")
//   editor → host:
//     ready {protocol, features?} · loaded {doc, live?} · saved {doc, id, name, fig} · flushed {id, ok}
//     error · applied · commandError · selection {doc, frame, nodes}
//     pages {doc, page, pages} · frames {doc, page, frames}
//     commentAt {doc, page?, frame, frame_name?, x, y} · commentOpen {id} · commentPlace {id, at, box} · commentEscape
//     newDesign {size?} · saveCopy {doc, name, fig} · export {doc, files} · exportAs {doc, format}
//     presence {doc, peers, saver, connected} · liveTicket {id}
//     liveAgent {doc, version} · liveReload {doc, version} · liveBase {doc, version}
// `doc` tags one load: a save from an older load is refused. Saves name the version they
// stand on as their base, so a save over a newer file is refused. An editor before
// protocol 2 sends none of the new messages and never waits for `written`.

function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode(...Array.from(bytes.subarray(i, i + 0x8000)));
  }
  return btoa(s);
}
function fromBase64(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// What Cycls does for the editor. `writeNew` never overwrites: the server picks a free name.
export type DesignHost = {
  newDesign: (size?: [number, number]) => Promise<void>;
  writeNew: (path: string, data: BlobPart) => Promise<string>;
  brand: () => Promise<BrandKit | null>;
  openInCanvas: (path: string) => void;
  refreshFiles?: () => void;
  // Rendered beside the design by the design service → its path; `page` defaults to the first.
  exportDesign?: (path: string, format: "pdf" | "png", page?: string) => Promise<string>;
  // Versioned reads and history: absent on an older server or a shared view.
  fetchVersioned?: FetchVersioned;
  listVersions?: (path: string) => Promise<DesignVersion[]>;
  versionBlob?: (path: string, id: string) => Promise<Blob>;
  versionPreview?: (path: string, id: string) => Promise<Blob>;
  restoreVersion?: (path: string, id: string) => Promise<{ version: string }>;
  // The design's live room and pass (null: it opens alone), and who this is, for their cursor.
  live?: (path: string) => Promise<DesignLive | null>;
  me?: { id: string; name: string };
};
export type { DesignLive } from "../hooks/use-files";

// Mounted editors by path: flushed before a close, rename or hide; detached during a delete.
type Handle = {
  flush: (ms: number) => Promise<boolean>; detach: () => () => void; fullscreen: () => void; reload: () => void;
  page: (name: string) => void;
  follow: (client: number | null) => void;
};
const editors = new Map<string, Set<Handle>>();
const under = (path: string, prefix: string) => path === prefix || path.startsWith(`${prefix}/`);
const handlesUnder = (prefix: string | null) =>
  [...editors.entries()].filter(([p]) => prefix == null || under(p, prefix)).flatMap(([, set]) => [...set]);

export const flushDesignEditor = (path: string, ms = 5000) =>
  Promise.all([...(editors.get(path) ?? [])].map((h) => h.flush(ms))).then((oks) => oks.every(Boolean));
export const flushDesignEditorsUnder = (prefix: string, ms = 5000) =>
  Promise.all(handlesUnder(prefix).map((h) => h.flush(ms))).then((oks) => oks.every(Boolean));
export const flushAllDesignEditors = (ms = 1500) =>
  Promise.all(handlesUnder(null).map((h) => h.flush(ms))).then((oks) => oks.every(Boolean));
// Returns re-attach (the delete failed); saves are dropped until then.
export function detachDesignEditorsUnder(prefix: string): () => void {
  const undo = handlesUnder(prefix).map((h) => h.detach());
  return () => undo.forEach((f) => f());
}
// Call from a click: the browser only grants full screen to a user gesture.
export function fullscreenDesignEditor(path: string): void {
  [...(editors.get(path) ?? [])].pop()?.fullscreen();
}
export const canFullscreen = () => typeof document !== "undefined" && document.fullscreenEnabled === true;
// Re-open on the saved file: after a restore, or a slide change made in the deck viewer.
export function reloadDesignEditors(path: string): void {
  for (const h of editors.get(path) ?? []) h.reload();
}

// The only types an editor export may write into the workspace.
const EXPORT_TYPES: Record<string, string> = {
  "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg", "application/pdf": "pdf",
};

type EditorMessage = {
  source?: string; type?: string; protocol?: number; doc?: string; id?: string; ok?: boolean; name?: string;
  fig?: string; message?: string; size?: [number, number]; features?: string[]; format?: string;
  files?: { name: string; mime: string; data: string }[];
  frame?: string | null; nodes?: DesignSelection["nodes"];
  page?: string; pages?: string[];
  peers?: DesignPeer[]; saver?: boolean; connected?: boolean; version?: string | null; live?: "seed" | "join";
  frames?: { name: string; w: number; h: number }[]; frame_name?: string; x?: number; y?: number;
  at?: { x: number; y: number } | null; box?: { w: number; h: number };
};

// The latest selection per design: what "Add selection" attaches to a message. A video's
// (video-editor-view.tsx) has no frame, and `time`: where its playhead was.
export type DesignSelection = { path: string; frame: string | null; nodes: { name: string; type: string; text?: string }[]; page?: string; time?: number };
const selections = new Map<string, DesignSelection>();
export const designSelection = (path: string) => selections.get(path) ?? null;
/** The latest selection in an open design or video, for the composer's "Add selection". */
export function publishSelection(sel: DesignSelection): void {
  if (sel.nodes.length) selections.set(sel.path, sel);
  else selections.delete(sel.path);
  window.dispatchEvent(new CustomEvent("cycls:design-selection", { detail: sel }));
}

// A design's pages (its variants) and the one in view; null while no editor of it is open.
export type DesignPages = { path: string; page: string; pages: string[] };
const pageSets = new Map<string, DesignPages>();
export const designPages = (path: string) => pageSets.get(path) ?? null;
export const designPage = (path: string) => {
  const p = pageSets.get(path);
  return p && p.pages.length > 1 ? p.page : undefined;
};
export function showDesignPage(path: string, page: string): void {
  for (const h of editors.get(path) ?? []) h.page(page);
}
export function useDesignPages(path: string): DesignPages | null {
  const [value, setValue] = useState(() => designPages(path));
  useEffect(() => {
    setValue(designPages(path));
    const onPages = (e: Event) => {
      if ((e as CustomEvent<{ path?: string }>).detail?.path === path) setValue(designPages(path));
    };
    window.addEventListener("cycls:design-pages", onPages);
    return () => window.removeEventListener("cycls:design-pages", onPages);
  }, [path]);
  return value;
}
// A `design_command` event. `reload`: the pages changed; `live`: the room already took it.
export type DesignCommand = { path: string; script: string; intent?: string; version?: string; page?: string; reload: boolean; live: boolean };
export function designCommandDetail(ev: Record<string, unknown>): DesignCommand {
  const words = (v: unknown) => (typeof v === "string" ? v : undefined);
  return { path: String(ev.path), script: String(ev.script), intent: words(ev.intent), version: words(ev.version),
           page: words(ev.page), reload: ev.reload === true, live: ev.live === true };
}

// Who else is in the design, and whether this editor saves for the room; null when alone.
export type DesignPeer = { client: number; name: string; user: string | null; color: string | null };
export type DesignPresence = { path: string; peers: DesignPeer[]; saver: boolean; connected: boolean };
const presences = new Map<string, DesignPresence>();
export const designPresence = (path: string) => presences.get(path) ?? null;
export function useDesignPresence(path: string): DesignPresence | null {
  const [value, setValue] = useState(() => designPresence(path));
  useEffect(() => {
    setValue(designPresence(path));
    const onPresence = (e: Event) => {
      if ((e as CustomEvent<{ path?: string }>).detail?.path === path) setValue(designPresence(path));
    };
    window.addEventListener("cycls:design-presence", onPresence);
    return () => window.removeEventListener("cycls:design-presence", onPresence);
  }, [path]);
  return value;
}
// null stops following.
export function followDesignPeer(path: string, client: number | null): void {
  for (const h of editors.get(path) ?? []) h.follow(client);
}
export { peerColor };

// The slides of the page in view, in order; a comment finds its slide by name.
export type DesignFrames = { path: string; page: string; frames: { name: string; w: number; h: number }[] };
const frameSets = new Map<string, DesignFrames>();
const commenting = new Set<string>();
// An older editor can't draw pins: comments then go on the design's preview.
export const designEditorComments = (path: string) => commenting.has(path);
export function useDesignFrames(path: string): DesignFrames | null {
  const [value, setValue] = useState(() => frameSets.get(path) ?? null);
  useEffect(() => {
    setValue(frameSets.get(path) ?? null);
    const onFrames = (e: Event) => {
      if ((e as CustomEvent<{ path?: string }>).detail?.path === path) setValue(frameSets.get(path) ?? null);
    };
    window.addEventListener("cycls:design-frames", onFrames);
    return () => window.removeEventListener("cycls:design-frames", onFrames);
  }, [path]);
  return value;
}

// The page a design was last on, so it reopens there.
const pageKey = (path: string) => `cycls:design-page:${path}`;
const lastPage = (path: string) => { try { return localStorage.getItem(pageKey(path)) || undefined; } catch { return undefined; } };
function keepPage(path: string, page: string | null) {
  try {
    if (page) localStorage.setItem(pageKey(path), page);
    else localStorage.removeItem(pageKey(path));
  } catch { /* no storage: it opens on its first page */ }
}

// An agent edit to replay: `intent` labels the cursor, `version` is the file's after it.
type Command = { script: string; intent?: string; version?: string; page?: string };

export function DesignEditorView({ url, path, name, editorUrl, writeFile, reload, host }: {
  url: string;        // blob URL of the .fig, used when there's no host.fetchVersioned
  path: string;       // workspace path to write edits back to
  name: string;
  editorUrl: string;  // base URL of the deployed editor (config.design_editor_url)
  writeFile: WriteFile;
  reload?: () => Promise<string>;   // a fresh blob URL of the saved .fig
  host?: DesignHost;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);        // what goes full screen: the editor and its pills
  const [full, setFull] = useState(false);
  const [hint, setHint] = useState(false);            // "Exit full screen", shown for a moment on entry
  const [frameKey, setFrameKey] = useState(0);        // bump → the editor iframe remounts
  const sourceRef = useRef<string | null>(null);      // what the next `ready` loads, if not `url`
  const [status, setStatus] = useState<"loading" | "ready" | "saved" | "error" | "saveerror">("loading");
  const [copyOf, setCopyOf] = useState<{ fig: string } | null>(null);
  // A save refused over a change made elsewhere; saves wait while the person decides.
  const [conflict, setConflict] = useState<{ version: string; fig: string } | null>(null);
  const conflictRef = useRef(conflict);
  conflictRef.current = conflict;
  const dark = useDarkMode();
  const lang = useLang();
  const toast = useToast();
  const base = editorUrl.replace(/\/+$/, "");
  // Fixed at first load so the iframe never reloads; later changes are posted live.
  const [src] = useState(() => `${base}/?embed=cycls&theme=${dark ? "dark" : "light"}&lang=${lang}`);
  const version = useRef<string | null>(null);        // the base version of the editor's saves
  const loadedVersion = useRef<string | null>(null);  // the version this load read
  const commands = useRef<Command[]>([]);             // agent edits waiting to replay
  const replaying = useRef<Command | null>(null);
  const editorLoaded = useRef(false);                 // the editor has this load's document open (`loaded`)
  const pending = useRef<{ version: string; timer: number } | null>(null);   // a 412 an agent edit may yet explain
  const force = useRef(false);                        // "keep mine": the next save writes over the newer file
  // Never "*": the design and the live ticket go to the editor's origin or nowhere.
  const origin = (() => { try { const u = new URL(editorUrl, window.location.href); return /^https?:$/.test(u.protocol) ? u.origin : null; } catch { return null; } })();
  const latest = useRef({ url, path, writeFile, reload, host, toast });
  latest.current = { url, path, writeFile, reload, host, toast };
  const protocol = useRef(0);           // 2, or 0 for a pre-protocol editor
  const doc = useRef("");               // the current load's tag
  const detached = useRef(false);       // the file is being deleted: write nothing
  const flushes = useRef(new Map<string, (ok: boolean) => void>());
  const features = useRef<Set<string>>(new Set());   // from the editor's `ready`
  const resetWait = useRef<number | null>(null);   // "Load the latest" in a room: the editor is telling the room
  const known = useRef(new Set<string>());   // file versions the room's document holds (`liveBase`)
  const retried = useRef(0);            // consecutive 412 retries on a version the room holds
  const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const stem = (path.split("/").pop() ?? name).replace(/\.fig$/i, "");

  const post = useCallback((msg: Record<string, unknown>) => {
    if (origin) frameRef.current?.contentWindow?.postMessage({ target: "cycls-editor", ...msg }, origin);
  }, [origin]);

  // The editor draws the pins; the open card is ours, laid over the editor.
  const comments = useComments(path);
  const commentsRef = useRef(comments);
  commentsRef.current = comments;
  const pagesNow = useDesignPages(path);
  const framesNow = useDesignFrames(path);
  const [pinsOn, setPinsOn] = useState(false);   // this load's editor draws comments, and has its document open
  const [place, setPlace] = useState<{ id: string; at: { x: number; y: number } | null; box: { w: number; h: number } } | null>(null);
  const names = useMemo(() => (framesNow?.frames ?? []).map((f) => f.name), [framesNow]);
  const drawing = useMemo(
    () => (comments && pinsOn ? editorComments(comments, names, pagesNow?.page, pagesNow?.pages ?? []) : null),
    [comments?.threads, comments?.adding, comments?.active, comments?.draft, comments?.host, pinsOn, names, pagesNow],   // eslint-disable-line react-hooks/exhaustive-deps
  );
  useEffect(() => {
    if (drawing) post({ type: "comments", ...drawing });
  }, [drawing, post]);
  const cardOpen = !!comments && pinsOn && (comments.active !== null || comments.draft !== null);
  useEscape(() => commentsRef.current?.store.set({ active: null, draft: null }), cardOpen);
  useEscape(() => commentsRef.current?.store.set({ adding: false }), !!comments?.adding && pinsOn && !cardOpen);

  useEffect(() => {
    if (protocol.current >= 2) post({ type: "theme", theme: dark ? "dark" : "light" });
  }, [dark, post]);
  useEffect(() => {
    if (protocol.current >= 2) post({ type: "locale", lang });
  }, [lang, post]);

  // One edit at a time, the next on `applied`; skip ones already in the loaded file. None
  // before `loaded`: the editor would answer `commandError` and force a reload.
  const pump = useCallback(() => {
    if (replaying.current || !editorLoaded.current) return;
    let next = commands.current.shift();
    while (next?.version && next.version === loadedVersion.current) next = commands.current.shift();
    if (!next) return;
    replaying.current = next;
    post({ type: "command", script: next.script, intent: next.intent, ...(next.page ? { page: next.page } : {}) });
  }, [post]);

  // Re-open on the saved file (a fresh fetch, with its version).
  const reopen = useCallback(() => {
    commands.current = [];
    replaying.current = null;
    editorLoaded.current = false;
    setStatus("loading");
    setFrameKey((k) => k + 1);
  }, []);

  // Full screen is the editor's box, not the page, so the iframe doesn't reload.
  const enterFullscreen = useCallback(() => {
    const box = boxRef.current;
    if (!box?.requestFullscreen || document.fullscreenElement) return;
    box.requestFullscreen({ navigationUI: "hide" }).then(() => {
      frameRef.current?.focus();   // keys go to the editor, not the button left behind
    }).catch(() => {});
  }, []);
  // Anything opened in another canvas tab would be hidden under full screen.
  const leaveFullscreen = useCallback(async () => {
    if (boxRef.current && document.fullscreenElement === boxRef.current) await document.exitFullscreen().catch(() => {});
  }, []);
  useEffect(() => {
    let timer: number | undefined;
    const onChange = () => {
      const on = !!boxRef.current && document.fullscreenElement === boxRef.current;
      setFull(on);
      setHint(on);
      window.clearTimeout(timer);
      if (on) timer = window.setTimeout(() => setHint(false), 2500);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      window.clearTimeout(timer);
    };
  }, []);

  // Refit the design when the box changes size a lot (full screen, canvas expanded).
  useEffect(() => {
    const box = boxRef.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    let last = box.getBoundingClientRect();
    let timer: number | undefined;
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const now = box.getBoundingClientRect();
        if (!now.width || !now.height) return;   // hidden (another canvas tab is showing)
        const grew = (a: number, b: number) => b > 0 && Math.abs(a - b) > b * 0.15;
        if ((grew(now.width, last.width) || grew(now.height, last.height)) && editorLoaded.current && features.current.has("fit")) {
          post({ type: "fit" });
        }
        last = now;
      }, 250);
    });
    observer.observe(box);
    return () => { observer.disconnect(); window.clearTimeout(timer); };
  }, [post]);

  useEffect(() => {
    const handle: Handle = {
      flush: (ms) => {
        if (protocol.current < 2 || !frameRef.current?.contentWindow) return Promise.resolve(true);
        const id = `f${Math.random().toString(36).slice(2)}`;
        return new Promise<boolean>((resolve) => {
          const timer = window.setTimeout(() => { flushes.current.delete(id); resolve(false); }, ms);
          flushes.current.set(id, (ok) => { window.clearTimeout(timer); resolve(ok); });
          post({ type: "flush", id });
        });
      },
      detach: () => {
        detached.current = true;
        return () => { detached.current = false; };
      },
      fullscreen: enterFullscreen,
      reload: reopen,
      page: (name) => { if (features.current.has("pages")) post({ type: "page", name }); },
      follow: (client) => { if (features.current.has("live")) post({ type: "follow", client }); },
    };
    let set = editors.get(path);
    if (!set) editors.set(path, (set = new Set()));
    set.add(handle);
    return () => {
      set!.delete(handle);
      if (!set!.size) {
        editors.delete(path);
        if (pageSets.delete(path)) window.dispatchEvent(new CustomEvent("cycls:design-pages", { detail: { path } }));
        commenting.delete(path);
        if (frameSets.delete(path)) window.dispatchEvent(new CustomEvent("cycls:design-frames", { detail: { path } }));
        if (presences.delete(path)) window.dispatchEvent(new CustomEvent("cycls:design-presence", { detail: { path } }));
      }
    };
  }, [path, post, enterFullscreen, reopen]);

  useEffect(() => {
    let disposed = false;
    let readies = 0;
    // After `loaded`, an `error` is a transient save blip, not a broken editor.
    let loaded = false;
    let spoke = false;    // the editor has said `ready`: its protocol is known
    const flash = (s: "saved" | "saveerror") => {
      if (disposed) return;
      setStatus(s);
      window.setTimeout(() => { if (!disposed) setStatus("ready"); }, 1500);
    };
    // "Will retry": what didn't save is still the editor's unsaved change, so it is asked for
    // again, later after each failure in a row. A flush saves only what is still unsaved.
    let failures = 0;
    let retry: number | undefined;
    const failed = () => {
      flash("saveerror");
      window.clearTimeout(retry);
      retry = window.setTimeout(() => { if (!disposed) post({ type: "flush", id: `r${Date.now().toString(36)}` }); },
                                Math.min(30_000, 2000 * 2 ** failures++));
    };

    const exportFiles = async (files: NonNullable<EditorMessage["files"]>) => {
      const { host, toast } = latest.current;
      if (!host) return;
      try {
        const written: string[] = [];
        for (const f of files) {
          if (!EXPORT_TYPES[f.mime] || typeof f.data !== "string") continue;
          const fileName = String(f.name).split(/[\\/]/).pop() || `export.${EXPORT_TYPES[f.mime]}`;
          const target = `${dir ? `${dir}/` : ""}${stem}-${fileName}`;
          written.push(await host.writeNew(target, fromBase64(f.data) as unknown as BlobPart));
        }
        if (!written.length) return;
        track("design_exported", { format: written[0].split(".").pop() ?? "", files: written.length });
        host.refreshFiles?.();
        const text = written.length === 1
          ? t("exportedTo").replace("{name}", written[0].split("/").pop() ?? written[0])
          : t("exportedN").replace("{n}", String(written.length)).replace("{dir}", dir || "/");
        toast.action(text, t("open"), () => { void leaveFullscreen().then(() => host.openInCanvas(written[0])); });
      } catch {
        toast.error(t("exportFailed"));
      }
    };

    // Rendered by the design service: the editor's own PDF embeds no fonts.
    const exportAs = async (format: "pdf" | "png") => {
      const { host, toast, path } = latest.current;
      if (!host?.exportDesign) return;
      try {
        await flushDesignEditor(path, 3000);   // what's unsaved is in the export
        const page = designPage(path);
        const written = await (page ? host.exportDesign(path, format, page) : host.exportDesign(path, format));
        track("design_exported", { format, files: 1 });
        host.refreshFiles?.();
        toast.action(t("exportedTo").replace("{name}", written.split("/").pop() ?? written), t("open"),
                     () => { void leaveFullscreen().then(() => host.openInCanvas(written)); });
      } catch {
        toast.error(t("exportFailed"));
      }
    };

    const onMessage = async (e: MessageEvent) => {
      if (!frameRef.current || e.source !== frameRef.current.contentWindow) return;   // this editor only
      if (e.origin !== origin) return;
      const m = e.data as EditorMessage;
      if (!m || m.source !== "cycls-editor") return;
      const { host, toast } = latest.current;
      if (m.type === "ready") {
        protocol.current = typeof m.protocol === "number" ? m.protocol : 0;
        features.current = new Set(Array.isArray(m.features) ? m.features : []);
        commenting.delete(latest.current.path);
        if (!disposed) { setPinsOn(false); setPlace(null); }
        let source = sourceRef.current;
        sourceRef.current = null;
        version.current = loadedVersion.current = null;
        commands.current = [];          // edits made before now are in the file this load reads
        replaying.current = null;
        editorLoaded.current = false;   // ones that arrive from here wait until it is open
        spoke = true;
        if (protocol.current >= 2 && host?.fetchVersioned) {
          // Read afresh with its version: the base its saves name (design/store.py).
          if (source) URL.revokeObjectURL(source);
          try {
            const got = await host.fetchVersioned(latest.current.path);
            source = got.url;
            version.current = loadedVersion.current = got.version || null;
          } catch {
            if (!disposed) setStatus("error");
            return;
          }
        } else if (!source && readies > 0 && latest.current.reload) {
          // A later `ready` (the editor reloaded itself) reads the saved file again.
          try { source = await latest.current.reload(); } catch { source = null; }
        }
        readies++;
        known.current = new Set();
        retried.current = 0;
        if (presences.delete(latest.current.path)) {
          window.dispatchEvent(new CustomEvent("cycls:design-presence", { detail: { path: latest.current.path } }));
        }
        try {
          const together = protocol.current >= 2 && features.current.has("live") && !!host?.live && !!host.me;
          const [buf, brand, room] = await Promise.all([
            fetch(source ?? latest.current.url).then((r) => r.arrayBuffer()),
            protocol.current >= 2 && host ? host.brand().catch(() => null) : Promise.resolve(null),
            together ? host!.live!(latest.current.path).catch(() => null) : Promise.resolve(null),
          ]);
          if (disposed) return;
          const live = room && host?.me
            ? { ...room, epoch: version.current ?? room.epoch,   // the version of the bytes it is given
                user: { id: host.me.id, name: host.me.name, color: peerColor(host.me.id) } } : null;
          doc.current = `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
          const page = lastPage(latest.current.path);   // where they left it
          post({ type: "load", protocol: 2, doc: doc.current, name, fig: toBase64(new Uint8Array(buf)),
                 ...(brand ? { brand } : {}), ...(page ? { page } : {}), ...(live ? { live } : {}) });
          if (protocol.current >= 2) {
            post({ type: "theme", theme: document.body.classList.contains("dark") ? "dark" : "light" });
            post({ type: "locale", lang: getLang() });
          }
        } catch {
          if (!disposed) setStatus("error");
        } finally {
          if (source && source !== latest.current.url) URL.revokeObjectURL(source);
        }
      } else if (m.type === "loaded") {
        loaded = true;
        if (!disposed) setStatus("ready");
        // A `join` took the room's document: its base comes from `liveBase`, not the file read.
        if (m.live !== "join" && loadedVersion.current) {
          version.current = loadedVersion.current;
          known.current = new Set([loadedVersion.current]);
        }
        // Not in a room after all (everyone left before it joined): drop stale presence.
        if (!m.live && presences.delete(latest.current.path)) {
          window.dispatchEvent(new CustomEvent("cycls:design-presence", { detail: { path: latest.current.path } }));
        }
        // Drop queued edits up to the one the loaded file already holds.
        const waiting = commands.current;
        for (let i = waiting.length - 1; i >= 0; i--) {
          if (waiting[i].version && waiting[i].version === loadedVersion.current) { waiting.splice(0, i + 1); break; }
        }
        editorLoaded.current = true;
        if (features.current.has("comments")) {
          commenting.add(latest.current.path);
          if (!disposed) setPinsOn(true);
        }
        pump();
      } else if (m.type === "frames" && Array.isArray(m.frames)) {
        if (m.doc && m.doc !== doc.current) return;
        const now: DesignFrames = { path: latest.current.path, page: typeof m.page === "string" ? m.page : "",
                                    frames: m.frames.filter((f) => f && typeof f.name === "string") };
        frameSets.set(now.path, now);
        window.dispatchEvent(new CustomEvent("cycls:design-frames", { detail: now }));
      } else if (m.type === "commentAt" && typeof m.frame === "number" && typeof m.x === "number" && typeof m.y === "number") {
        // A comment-mode click on a slide: start a draft there.
        if (m.doc && m.doc !== doc.current) return;
        commentsRef.current?.store.pin({ ...(m.page ? { page: m.page } : {}), frame: m.frame,
                                         ...(m.frame_name ? { frame_name: m.frame_name } : {}), x: m.x, y: m.y });
      } else if (m.type === "commentOpen" && typeof m.id === "string") {
        const c = commentsRef.current;
        c?.store.open(c.active === m.id ? null : m.id);
      } else if (m.type === "commentPlace" && typeof m.id === "string" && m.box) {
        if (!disposed) setPlace({ id: m.id, at: m.at ?? null, box: m.box });
      } else if (m.type === "commentEscape") {
        // Escape in the editor: close the card first, then comment mode.
        const c = commentsRef.current;
        if (c) c.store.set(c.active !== null || c.draft !== null ? { active: null, draft: null } : { adding: false });
      } else if (m.type === "saved" && typeof m.fig === "string") {
        const reply = (ok: boolean) => post({ type: "written", doc: m.doc, id: m.id, ok });
        // A save from a replaced load, or of a file being deleted, is dropped.
        if ((m.doc && m.doc !== doc.current) || detached.current) {
          reply(false);
          return;
        }
        if (conflictRef.current) {   // the person is deciding the conflict
          reply(false);
          return;
        }
        const keep = force.current;
        try {
          // Cast: TS 5.7's Uint8Array<ArrayBufferLike> isn't a BlobPart.
          const r = await latest.current.writeFile(latest.current.path, fromBase64(m.fig) as unknown as BlobPart, {
            silent: true, ...(version.current ? { base: version.current } : {}), ...(keep ? { force: true } : {}),
          });
          if (keep) force.current = false;
          if (r && r.version && version.current !== null) version.current = r.version;
          if (r && r.version) known.current.add(r.version);
          retried.current = 0;
          failures = 0;
          reply(true);
          flash("saved");
        } catch (err) {
          reply(false);
          if ((err as { status?: number }).status === 412) {
            const now = await (err as { response?: Response }).response?.json().then((j) => j?.version).catch(() => undefined);
            if (presences.has(latest.current.path) && typeof now === "string" && now && known.current.has(now) && retried.current < 3) {
              // The room's document already holds that version: save again on it. An
              // unknown version is a change from outside the room: ask.
              retried.current++;
              version.current = now;
              post({ type: "save" });
            } else {
              stale(typeof now === "string" ? now : "", m.fig);
            }
          } else {
            failed();
          }
        }
      } else if (m.type === "flushed" && typeof m.id === "string") {
        flushes.current.get(m.id)?.(m.ok === true);
        flushes.current.delete(m.id);
      } else if (m.type === "applied") {
        // Saves go on from the edit's version; the flush resends one refused meanwhile.
        const done = replaying.current;
        replaying.current = null;
        if (done?.version && version.current !== null) {
          version.current = done.version;
          known.current.add(done.version);
          if (presences.has(latest.current.path)) post({ type: "liveBase", version: done.version });
          post({ type: "flush", id: `v${done.version}` });
        }
        pump();
      } else if (m.type === "selection" && Array.isArray(m.nodes)) {
        const page = designPage(latest.current.path);
        const sel: DesignSelection = { path: latest.current.path, frame: typeof m.frame === "string" ? m.frame : null, nodes: m.nodes,
                                       ...(page ? { page } : {}) };
        publishSelection(sel);
      } else if (m.type === "pages" && Array.isArray(m.pages) && typeof m.page === "string") {
        if (m.doc && m.doc !== doc.current) return;
        const now: DesignPages = { path: latest.current.path, page: m.page, pages: m.pages.filter((p) => typeof p === "string") };
        pageSets.set(now.path, now);
        keepPage(now.path, now.pages.length > 1 && now.page !== now.pages[0] ? now.page : null);
        window.dispatchEvent(new CustomEvent("cycls:design-pages", { detail: now }));
      } else if (m.type === "presence" && Array.isArray(m.peers)) {
        if (m.doc && m.doc !== doc.current) return;
        const now: DesignPresence = {
          path: latest.current.path, saver: m.saver === true, connected: m.connected !== false,
          peers: m.peers.filter((p) => p && typeof p.client === "number").map((p) => ({
            client: p.client, name: typeof p.name === "string" ? p.name : "",
            user: typeof p.user === "string" ? p.user : null, color: typeof p.color === "string" ? p.color : null })),
        };
        presences.set(now.path, now);
        window.dispatchEvent(new CustomEvent("cycls:design-presence", { detail: now }));
      } else if (m.type === "liveTicket" && typeof m.id === "string") {
        // The editor is reconnecting: it needs a fresh ticket.
        const room = await host?.live?.(latest.current.path).catch(() => null);
        if (room && !disposed) post({ type: "liveTicket", id: m.id, ticket: room.ticket });
      } else if (m.type === "liveBase" && typeof m.version === "string" && m.version) {
        // The room holds this version: base on it if not the saver, and resend a save refused over it.
        if (m.doc && m.doc !== doc.current) return;
        known.current.add(m.version);
        if (version.current !== null && !presences.get(latest.current.path)?.saver) version.current = m.version;
        if (pending.current?.version === m.version) {
          window.clearTimeout(pending.current.timer);
          pending.current = null;
          version.current = m.version;
          post({ type: "save" });
        }
      } else if (m.type === "liveAgent") {
        // The server handed an agent edit to the room: base on its version and save.
        if (m.doc && m.doc !== doc.current) return;
        if (pending.current) { window.clearTimeout(pending.current.timer); pending.current = null; }
        if (typeof m.version === "string" && m.version) known.current.add(m.version);
        if (typeof m.version === "string" && m.version && version.current !== null) version.current = m.version;
        post({ type: "flush", id: `a${Date.now().toString(36)}` });
      } else if (m.type === "liveReload") {
        // The file was rewritten (re-render, restore, slide moved): reopen.
        if (m.doc && m.doc !== doc.current) return;
        if (pending.current) { window.clearTimeout(pending.current.timer); pending.current = null; }
        if (resetWait.current) { window.clearTimeout(resetWait.current); resetWait.current = null; }
        reopen();
      } else if (m.type === "commandError") {
        // The server already saved the edit: reopen on a fresh fetch, or an auto-save would undo it.
        commands.current = [];
        replaying.current = null;
        editorLoaded.current = false;
        if (!host?.fetchVersioned) {
          try { sourceRef.current = latest.current.reload ? await latest.current.reload() : null; } catch { sourceRef.current = null; }
        }
        if (disposed) return;
        loaded = false;
        readies = 0;
        setStatus("loading");
        setFrameKey((k) => k + 1);
      } else if (m.type === "error") {
        if (!disposed) loaded ? failed() : setStatus("error");
      } else if (m.type === "newDesign" && host) {
        await leaveFullscreen();
        try { await host.newDesign(Array.isArray(m.size) ? m.size : undefined); } catch { toast.error(t("newDesignFailed")); }
      } else if (m.type === "export" && Array.isArray(m.files)) {
        await exportFiles(m.files);
      } else if (m.type === "exportAs" && (m.format === "pdf" || m.format === "png")) {
        await exportAs(m.format);
      } else if (m.type === "saveCopy" && typeof m.fig === "string" && host) {
        setCopyOf({ fig: m.fig });
      }
    };
    // A 412 during an agent replay is expected (it resends on `applied`). Otherwise wait:
    // the agent's event may arrive after the 412.
    const stale = (now: string, fig: string) => {
      if (replaying.current || commands.current.length) return;
      if (pending.current) window.clearTimeout(pending.current.timer);
      pending.current = {
        version: now,
        timer: window.setTimeout(() => {
          pending.current = null;
          if (disposed || replaying.current || commands.current.length) return;
          setConflict({ version: now, fig });
          track("design_save_conflict", { choice: "shown" });
        }, presences.has(latest.current.path) ? 6000 : 3000),   // a room's explanation comes later
      };
    };

    // From chat.tsx, on a `design_command` event.
    const onCommand = (e: Event) => {
      const d = (e as CustomEvent).detail as { path?: string; script?: string; intent?: string; version?: string; page?: string; reload?: boolean; live?: boolean };
      if (!d || d.path !== latest.current.path || typeof d.script !== "string") return;
      // The room applies it once for everyone; replaying here would apply it twice.
      if (d.live && features.current.has("live") && presences.has(latest.current.path)) return;
      if (spoke && protocol.current < 2) {   // an editor from before the protocol never says `applied`
        post({ type: "command", script: d.script, intent: d.intent });
        return;
      }
      if (d.reload) {
        // The pages changed: reopen the saved file on the edit's page.
        if (pending.current) window.clearTimeout(pending.current.timer);
        pending.current = null;
        keepPage(latest.current.path, d.page || null);
        reopen();
        return;
      }
      if (pending.current && d.version === pending.current.version) {   // the change was this edit's
        window.clearTimeout(pending.current.timer);
        pending.current = null;
      }
      commands.current.push({ script: d.script, intent: d.intent, version: typeof d.version === "string" ? d.version : undefined,
                              page: typeof d.page === "string" && d.page ? d.page : undefined });
      pump();
    };

    window.addEventListener("message", onMessage);
    window.addEventListener("cycls:design-command", onCommand as EventListener);
    return () => {
      disposed = true;
      window.clearTimeout(retry);
      if (pending.current) window.clearTimeout(pending.current.timer);
      pending.current = null;
      if (resetWait.current) window.clearTimeout(resetWait.current);
      resetWait.current = null;
      window.removeEventListener("message", onMessage);
      window.removeEventListener("cycls:design-command", onCommand as EventListener);
    };
  }, [origin, post, name, dir, stem, frameKey, leaveFullscreen, pump, reopen]);

  const resolve = async (choice: "latest" | "mine" | "copy") => {
    const c = conflictRef.current;
    if (!c) return;
    setConflict(null);
    track("design_save_conflict", { choice });
    if (choice === "mine") {
      version.current = c.version || version.current;
      force.current = true;
      post({ type: "save" });
      return;
    }
    if (choice === "copy" && host) {
      try {
        const written = await host.writeNew(`${dir ? `${dir}/` : ""}${stem} ${t("copySuffix")}.fig`, fromBase64(c.fig) as unknown as BlobPart);
        host.refreshFiles?.();
        await leaveFullscreen();
        host.openInCanvas(written);
        toast.info(t("savedCopy").replace("{name}", written.split("/").pop() ?? written));
      } catch {
        toast.error(t("copyFailed"));
        return;   // nothing was saved: keep this editor's work
      }
    }
    // In a room the reset is for everyone: wait for the editor's `liveReload` (reopening
    // first would cut its message to the room), but not for long.
    if (presences.has(latest.current.path)) {
      post({ type: "liveReset" });
      if (resetWait.current) window.clearTimeout(resetWait.current);
      resetWait.current = window.setTimeout(() => { resetWait.current = null; reopen(); }, 1500);
      return;
    }
    reopen();
  };

  const saveCopy = async (copyName: string) => {
    const { host, toast } = latest.current;
    if (!copyOf || !host) return;
    setCopyOf(null);
    try {
      const written = await host.writeNew(`${dir ? `${dir}/` : ""}${copyName}.fig`, fromBase64(copyOf.fig) as unknown as BlobPart);
      track("design_copied", {});
      host.refreshFiles?.();
      await leaveFullscreen();
      host.openInCanvas(written);
      toast.info(t("savedCopy").replace("{name}", written.split("/").pop() ?? written));
    } catch {
      toast.error(t("copyFailed"));
    }
  };

  return (
    // `data-toasts`: Cycls's toasts show inside it while it's full screen.
    <div ref={boxRef} data-toasts="" className="relative h-full w-full bg-background">
      {/* Not sandboxed: the editor needs CanvasKit, workers and storage on its own origin. */}
      <iframe key={frameKey} ref={frameRef} src={src} title={name} className="h-full w-full border-0" />
      {/* The open comment's card, at the pin the editor reports (editor pixels are box pixels). */}
      {comments && pinsOn && place?.at && place.id === (comments.draft ? "draft" : comments.active) && (
        <div className="pointer-events-none absolute inset-0 z-10" data-testid="editor-comment">
          <OpenComment path={path} at={place.at} within={place.box} />
        </div>
      )}
      {pinsOn && <CommentsList path={path} names={names} page={pagesNow?.page} pages={pagesNow?.pages}
                               onPage={(page) => showDesignPage(path, page)} />}
      {full && (
        // Always visible in full screen: labelled at first, then a small button.
        <button
          onClick={() => void leaveFullscreen()}
          aria-label={t("exitFullScreen")}
          title={t("exitFullScreen")}
          data-testid="exit-fullscreen"
          className={cn(
            "absolute left-1/2 top-2 z-10 flex h-8 -translate-x-1/2 items-center gap-1.5 rounded-full bg-background/90 text-xs text-foreground shadow backdrop-blur transition-opacity cursor-pointer",
            hint ? "px-3 opacity-100" : "w-8 justify-center opacity-60 hover:opacity-100",
          )}
        >
          <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3.75v4.5h-4.5m12-4.5v4.5h4.5m0 7.5h-4.5v4.5m-7.5 0v-4.5h-4.5" />
          </svg>
          {hint && t("exitFullScreen")}
        </button>
      )}
      {status !== "ready" && (
        <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow backdrop-blur">
          {t(status === "error" ? "editorError"
            : status === "saveerror" ? "editorSaveError"
              : status === "saved" ? "editorSaved"
                : "editorLoading")}
        </div>
      )}
      {copyOf && (
        <SaveCopyDialog initial={`${stem} ${t("copySuffix")}`} onCancel={() => setCopyOf(null)} onSave={saveCopy} />
      )}
      {conflict && <ConflictDialog canCopy={!!host} onChoose={(c) => void resolve(c)} />}
    </div>
  );
}

// The design changed elsewhere while this editor had unsaved work: nothing is written until they choose.
function ConflictDialog({ canCopy, onChoose }: { canCopy: boolean; onChoose: (c: "latest" | "mine" | "copy") => void }) {
  const choice = "w-full cursor-pointer rounded-md px-3 py-2 text-start text-xs hover:bg-secondary";
  useEscape(() => {});   // Escape neither dismisses it nor closes the canvas under it
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/30" role="dialog" aria-modal="true"
         aria-labelledby="design-conflict-title">
      <div className="w-96 rounded-xl border border-border bg-background p-4 shadow-xl">
        <div id="design-conflict-title" className="mb-1 text-sm font-medium text-foreground">{t("designChangedTitle")}</div>
        <p className="mb-3 text-xs text-muted-foreground">{t("designChangedBody")}</p>
        <div className="flex flex-col gap-1">
          <button type="button" className={choice} onClick={() => onChoose("latest")}>
            <div className="font-medium text-foreground">{t("designLoadLatest")}</div>
            <div className="text-muted-foreground">{t("designLoadLatestHint")}</div>
          </button>
          <button type="button" className={choice} onClick={() => onChoose("mine")}>
            <div className="font-medium text-foreground">{t("designKeepMine")}</div>
            <div className="text-muted-foreground">{t("designKeepMineHint")}</div>
          </button>
          {canCopy && (
            <button type="button" className={choice} onClick={() => onChoose("copy")}>
              <div className="font-medium text-foreground">{t("designSaveMineAsCopy")}</div>
              <div className="text-muted-foreground">{t("designSaveMineAsCopyHint")}</div>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function SaveCopyDialog({ initial, onCancel, onSave }: {
  initial: string;
  onCancel: () => void;
  onSave: (name: string) => void;
}) {
  const [value, setValue] = useState(initial);
  const name = value.trim().replace(/[\\/]+/g, "-").replace(/\.fig$/i, "");
  useEscape(onCancel);
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/30" onClick={onCancel}>
      <form
        className="w-80 rounded-xl border border-border bg-background p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); if (name) onSave(name); }}
      >
        <div className="mb-3 text-sm font-medium text-foreground">{t("saveCopy")}</div>
        <label className="mb-1 block text-xs text-muted-foreground" htmlFor="design-copy-name">{t("copyName")}</label>
        <input
          id="design-copy-name"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="w-full rounded-md border border-border bg-transparent px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          dir="auto"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="cursor-pointer rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-secondary">
            {t("cancel")}
          </button>
          <button type="submit" disabled={!name} className="cursor-pointer rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">
            {t("saveCopy")}
          </button>
        </div>
      </form>
    </div>
  );
}

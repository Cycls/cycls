// A video on the canvas, edited by hand: the Cycls video editor (cycls-video's editor, HyperFrames'
// editor made Cycls's) in an iframe on the video service's own origin, opened for ONE composition of
// the workspace — the session POST /video/editor makes for it (web/video_routes.py).
//
// The workspace stays the truth; the session is a working copy. Each change comes back as the clean
// source (`saved`) and is written here with PUT /files?base= — only to the composition this view was
// opened on, and to the words files the session was given — so a stale base is a 412 and the person
// decides (the conflict dialog). An agent edit reaches an open editor as a `load` of the new file,
// after what is unsaved went out first (`flush`).
//
// postMessage protocol 1 (cycls-video editor/patches/cycls/bridge.ts):
//   to the editor   {target: "cycls-video-editor", type}: load {doc, html} · written {doc, id, ok} ·
//                   flush {id} · theme {theme} · render-state {state, progress?, message?}
//   from it         {source: "cycls-video-editor", type}: ready {protocol} · loaded {doc} · flushed {id} ·
//                   saved {doc, id, composition?, words?: [{path, text}]} · selection {doc, path, time, nodes} ·
//                   ask {…selection} · render {doc, quality} · error {doc, lost?, message?}
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useDarkMode } from "../hooks/use-dark-mode";
import { useEscape } from "../hooks/use-escape";
import type { VideoEditorApi, VideoEditorSession, WriteFile } from "../hooks/use-files";
import { track } from "../lib/analytics";
import { t } from "../lib/i18n";
import { useToast } from "../lib/toast";
import { cn } from "../lib/utils";
import { publishSelection, type DesignSelection } from "./design-editor-view";

const TARGET = "cycls-video-editor";
const HTML_LIMIT = 400_000;           // the service's own limit on a composition
const WORDS_LIMIT = 2_000_000;

// ── open editors, for Cycls's flushes (tab switch, close, rename, delete) and agent edits ──────────
type Handle = { flush: (ms: number) => Promise<boolean>; detach: () => () => void; reload: (version?: string) => void;
                refresh: () => Promise<void> };
const editors = new Map<string, Set<Handle>>();
const under = (path: string, prefix: string) => path === prefix || path.startsWith(`${prefix}/`);
const handlesUnder = (prefix: string | null) =>
  [...editors.entries()].filter(([p]) => prefix === null || under(p, prefix)).flatMap(([, hs]) => [...hs]);
export const flushVideoEditor = (path: string, ms = 5000) =>
  Promise.all([...(editors.get(path) ?? [])].map((h) => h.flush(ms))).then((oks) => oks.every(Boolean));
export const flushVideoEditorsUnder = (prefix: string, ms = 5000) =>
  Promise.all(handlesUnder(prefix).map((h) => h.flush(ms))).then((oks) => oks.every(Boolean));
export const flushAllVideoEditors = (ms = 1500) =>
  Promise.all(handlesUnder(null).map((h) => h.flush(ms))).then((oks) => oks.every(Boolean));
export function detachVideoEditorsUnder(prefix: string): () => void {
  const undo = handlesUnder(prefix).map((h) => h.detach());
  return () => undo.forEach((u) => u());
}
/** The agent changed a video (refresh_canvas): an editor open on it takes the new file in. */
export function reloadVideoEditors(path: string, version?: string): void {
  for (const h of editors.get(path) ?? []) h.reload(version);
}
/** A turn ended: any file tool may have changed an open video (not only the Video tool, which
 *  says so with refresh_canvas). Each open editor takes its file in again only if it changed. */
export function refreshVideoEditors(): Promise<void> {
  return Promise.all(handlesUnder(null).map((h) => h.refresh().catch(() => {}))).then(() => {});
}
export const videoEditorOpen = (path: string) => (editors.get(path)?.size ?? 0) > 0;

// Where the editor makes sense: a pointer, and room for a timeline beside a preview.
export function canEditVideo(): boolean {
  if (typeof window === "undefined") return false;
  return window.innerWidth >= 900 && window.matchMedia?.("(pointer: fine)").matches !== false;
}

type Status = "opening" | "ready" | "saving" | "saved" | "saveerror" | "error";
type Pending = { doc: string; id: unknown; composition?: string; words?: { path: string; text: string }[] };

export function VideoEditorView({ path, name, api, writeFile, onClose, onRendered, aside = false, onAside, onBack }: {
  path: string;                 // the composition: videos/<name>.video.html
  name: string;
  api: VideoEditorApi;
  writeFile: WriteFile;
  onClose: () => void;
  onRendered?: (mp4: string) => void;
  // Ask Cycls steps the editor aside so the chat can be typed into: still open and loaded (an agent
  // edit reaches it), but out of sight until Back (or Edit) brings it back.
  aside?: boolean;
  onAside?: () => void;
  onBack?: () => void;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [session, setSession] = useState<VideoEditorSession | null>(null);
  const [status, setStatus] = useState<Status>("opening");
  const [problem, setProblem] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ pending: Pending } | null>(null);
  const [opening, setOpening] = useState(0);            // bump → a new session (a lost one)
  const dark = useDarkMode();
  const toast = useToast();
  const versions = useRef<Record<string, string>>({});
  const doc = useRef("");
  const docs = useRef(0);
  const queue = useRef<Promise<unknown>>(Promise.resolve());   // writes, one after another
  const flushes = useRef(new Map<string, (ok: boolean) => void>());
  const detached = useRef(false);
  const conflictRef = useRef(conflict);
  conflictRef.current = conflict;
  const latest = useRef({ path, api, writeFile, onRendered, toast, aside, onAside, onBack });
  latest.current = { path, api, writeFile, onRendered, toast, aside, onAside, onBack };
  const origin = (() => { try { return session ? new URL(session.url).origin : ""; } catch { return ""; } })();

  const post = useCallback((msg: Record<string, unknown>) => {
    if (origin) frameRef.current?.contentWindow?.postMessage({ target: TARGET, ...msg }, origin);
  }, [origin]);

  // ── the session ────────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    let gone = false;
    setStatus("opening");
    setProblem(null);
    latest.current.api.open(latest.current.path).then((s) => {
      if (gone) { void latest.current.api.close(s.sid); return; }
      versions.current = { ...s.versions };
      setSession(s);
      if (s.notice) latest.current.toast.info(s.notice);
      track("video_editor_opened", {});
    }).catch(async (err: { status?: number; response?: Response }) => {
      if (gone) return;
      const detail = await err.response?.json().then((j: { detail?: string }) => j?.detail).catch(() => undefined);
      setProblem(detail || t("editorUnavailable"));
      setStatus("error");
    });
    return () => { gone = true; };
  }, [opening]);

  useEffect(() => () => { if (session) void latest.current.api.close(session.sid); }, [session]);

  // ── loading the workspace's file into the editor ─────────────────────────────────────────────
  const load = useCallback(async () => {
    const { text, version } = await latest.current.api.readText(latest.current.path);
    versions.current[latest.current.path] = version;
    doc.current = `d${++docs.current}`;
    post({ type: "load", doc: doc.current, html: text });
  }, [post]);

  // ── what the editor saves ─────────────────────────────────────────────────────────────────────
  const words = (w: unknown): w is { path: string; text: string }[] =>
    Array.isArray(w) && w.every((x) => x && typeof x.path === "string" && typeof x.text === "string");

  const write = useCallback(async (p: Pending, force = false): Promise<boolean> => {
    const { path: rel, writeFile: wf } = latest.current;
    const jobs: [string, string][] = [];
    if (typeof p.composition === "string") {
      if (new TextEncoder().encode(p.composition).length > HTML_LIMIT) throw new Error("too large");
      jobs.push([rel, p.composition]);
    }
    for (const w of p.words ?? []) {
      // Only the words files the session was given, and only words files at that.
      if (w.path === rel || !(w.path in versions.current) || !w.path.endsWith(".words.json")) continue;
      if (w.text.length > WORDS_LIMIT) continue;
      try {
        const parsed = JSON.parse(w.text);
        if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.words)) continue;
      } catch { continue; }
      jobs.push([w.path, w.text]);
    }
    for (const [file, text] of jobs) {
      const r = await wf(file, text, { silent: true, ...(versions.current[file] ? { base: versions.current[file] } : {}), ...(force ? { force: true } : {}) });
      if (r && r.version) versions.current[file] = r.version;
      track("video_edited", { kind: file === rel ? "composition" : "words" });
    }
    return true;
  }, []);

  const saved = useCallback((m: Pending) => {
    queue.current = queue.current.then(async () => {
      const reply = (ok: boolean) => post({ type: "written", doc: m.doc, id: m.id, ok });
      if (m.doc !== doc.current || detached.current || conflictRef.current) return reply(false);
      setStatus("saving");
      try {
        await write(m);
        reply(true);
        setStatus("saved");
      } catch (err) {
        reply(false);
        if ((err as { status?: number }).status === 412) {
          setConflict({ pending: m });
          latest.current.onBack?.();                       // the person decides, so they must see it
          track("video_save_conflict", { choice: "shown" });
        } else {
          setStatus("saveerror");
        }
      }
    });
    return queue.current;
  }, [post, write]);

  const resolve = useCallback(async (choice: "latest" | "mine") => {
    const c = conflictRef.current;
    setConflict(null);
    track("video_save_conflict", { choice });
    if (!c) return;
    if (choice === "mine") {
      try { await write(c.pending, true); setStatus("saved"); } catch { setStatus("saveerror"); }
    } else {
      await load();
    }
  }, [load, write]);

  // ── rendering, asked for in the editor ───────────────────────────────────────────────────────
  const render = useCallback(async (quality: string) => {
    await queue.current;                                   // what was saved just before is in the render
    const q = quality === "draft" || quality === "final" ? quality : "standard";
    try {
      let s = await latest.current.api.render(latest.current.path, q);
      post({ type: "render-state", state: s.state, progress: s.progress ?? 0 });
      while (s.state === "rendering") {
        await new Promise((r) => setTimeout(r, 2000));
        s = await latest.current.api.renderState(latest.current.path);
        post({ type: "render-state", state: s.state, progress: s.progress ?? 0, ...(s.message ? { message: s.message } : {}) });
      }
      if (s.state === "done" && s.path) {
        track("video_rendered_from_editor", { quality: q });
        latest.current.toast.info(`${t("videoEditorRendered")}: ${s.path}`);
        latest.current.onRendered?.(s.path);
      } else if (s.state === "failed") {
        latest.current.toast.error(s.message || t("videoEditorRenderFailed"));
      }
    } catch {
      post({ type: "render-state", state: "failed", message: t("videoEditorRenderFailed") });
    }
  }, [post]);

  // ── the editor's messages ──────────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!session || !origin) return;
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== origin || e.source !== frameRef.current?.contentWindow) return;
      const m = e.data;
      if (!m || typeof m !== "object" || m.source !== TARGET) return;
      switch (m.type) {
        case "ready":
          void load().catch(() => setStatus("error"));
          post({ type: "theme", theme: dark ? "dark" : "light" });
          break;
        case "loaded":
          if (m.doc === doc.current) setStatus("ready");
          break;
        case "saved":
          void saved({ doc: m.doc, id: m.id, composition: typeof m.composition === "string" ? m.composition : undefined,
                       words: words(m.words) ? m.words : undefined });
          break;
        case "flushed":
          if (typeof m.id === "string") { flushes.current.get(m.id)?.(true); flushes.current.delete(m.id); }
          break;
        case "selection":
        case "ask": {
          if (m.doc !== doc.current || !Array.isArray(m.nodes)) break;
          const nodes = m.nodes.filter((n: unknown) => n && typeof (n as { name?: unknown }).name === "string")
            .slice(0, 20).map((n: { name: string; type?: string; text?: string }) => ({
              name: n.name.slice(0, 120), type: String(n.type ?? "element").slice(0, 24), ...(n.text ? { text: String(n.text).slice(0, 80) } : {}) }));
          const sel: DesignSelection = { path: latest.current.path, frame: null, nodes,
                                         ...(typeof m.time === "number" ? { time: m.time } : {}) };
          publishSelection(sel);
          if (m.type === "ask" && nodes.length) {
            latest.current.onAside?.();                     // the composer is under the editor otherwise
            window.dispatchEvent(new CustomEvent("cycls:ask-selection", { detail: sel }));
          }
          break;
        }
        case "render":
          if (m.doc === doc.current) void render(String(m.quality ?? "standard"));
          break;
        case "error":
          if (m.lost) setOpening((n) => n + 1);              // the session is gone: open another
          break;
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [session, origin, load, post, saved, render, dark]);

  useEffect(() => { post({ type: "theme", theme: dark ? "dark" : "light" }); }, [dark, post]);

  // ── this editor in the registry ────────────────────────────────────────────────────────────────
  useEffect(() => {
    const handle: Handle = {
      flush: (ms) => new Promise<boolean>((resolveFlush) => {
        if (!session || detached.current) return resolveFlush(true);
        const id = `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
        const timer = window.setTimeout(() => { flushes.current.delete(id); resolveFlush(false); }, ms);
        flushes.current.set(id, (ok) => {
          window.clearTimeout(timer);
          void queue.current.then(() => resolveFlush(ok && !conflictRef.current));
        });
        post({ type: "flush", id });
      }),
      detach: () => { detached.current = true; return () => { detached.current = false; }; },
      reload: (version) => {
        if (version && versions.current[latest.current.path] === version) return;   // its own save
        void handle.flush(5000).then(() => { if (!conflictRef.current) void load(); });
      },
      refresh: async () => {
        if (!session || detached.current || !doc.current) return;
        await queue.current;                                   // its own saves have their versions
        const { version } = await latest.current.api.readText(latest.current.path);
        if (version !== versions.current[latest.current.path]) handle.reload(version);
      },
    };
    const set = editors.get(path) ?? new Set<Handle>();
    set.add(handle);
    editors.set(path, set);
    return () => { set.delete(handle); if (!set.size) editors.delete(path); };
  }, [path, session, post, load]);

  // ── Done / Escape: what is unsaved goes first ─────────────────────────────────────────────────
  const done = useCallback(async () => {
    await flushVideoEditor(path, 5000);
    publishSelection({ path, frame: null, nodes: [] });
    onClose();
  }, [path, onClose]);
  useEscape(() => { if (!conflictRef.current && !latest.current.aside) void done(); });

  useEffect(() => {
    // The browser's own full screen where there is one; the overlay covers the page either way.
    const el = document.documentElement;
    if (document.fullscreenEnabled && !document.fullscreenElement && window.innerWidth < 1280) {
      el.requestFullscreen?.().catch(() => {});
      return () => { if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => {}); };
    }
  }, []);

  const label = status === "opening" ? t("videoEditorOpening") : status === "saving" ? t("videoEditorSaving")
    : status === "saved" ? t("videoEditorSaved") : status === "saveerror" ? t("videoEditorSaveFailed") : "";

  return createPortal(
    <div className={cn("fixed inset-0 z-[60] flex flex-col bg-background", aside && "invisible pointer-events-none")}
         role="dialog" aria-label={name} aria-hidden={aside || undefined} data-testid="video-editor">
      {aside && (
        <button type="button" onClick={() => onBack?.()} data-testid="video-editor-back"
                className="visible pointer-events-auto fixed left-1/2 top-3 -translate-x-1/2 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground shadow-md transition-colors hover:bg-secondary cursor-pointer">
          {t("videoEditorBack")}
        </button>
      )}
      <div className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-border px-3">
        <span className="truncate text-sm font-medium text-foreground" dir="auto">{name}</span>
        <div className="flex items-center gap-3">
          {label && <span className={cn("text-xs", status === "saveerror" ? "text-destructive" : "text-muted-foreground")}>{label}</span>}
          <button type="button" onClick={() => void done()} data-testid="video-editor-done"
                  className="rounded-md bg-foreground px-3 py-1 text-xs font-medium text-background transition-opacity hover:opacity-90 cursor-pointer">
            {t("videoEditorDone")}
          </button>
        </div>
      </div>
      <div className="relative min-h-0 flex-1">
        {session && (
          <iframe ref={frameRef} key={session.sid} title={name} src={`${session.url}?theme=${dark ? "dark" : "light"}`}
                  sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
                  allow="clipboard-read; clipboard-write; fullscreen" className="h-full w-full border-0" />
        )}
        {status === "opening" && !problem && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">{t("videoEditorOpening")}</div>
        )}
        {problem && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            <div className="max-w-md text-sm text-muted-foreground">{problem}</div>
            <button type="button" onClick={onClose}
                    className="rounded-md bg-secondary px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary/80 cursor-pointer">
              {t("videoEditorDone")}
            </button>
          </div>
        )}
        {conflict && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/40 p-4" data-testid="video-conflict">
            <div className="w-full max-w-md rounded-xl border border-border bg-background p-5 shadow-xl">
              <div className="text-sm font-semibold text-foreground">{t("videoConflictTitle")}</div>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{t("videoConflictBody")}</p>
              <div className="mt-4 flex justify-end gap-2">
                <button type="button" onClick={() => void resolve("latest")}
                        className="rounded-md bg-secondary px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary/80 cursor-pointer">
                  {t("videoConflictLatest")}
                </button>
                <button type="button" onClick={() => void resolve("mine")}
                        className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background hover:opacity-90 cursor-pointer">
                  {t("videoConflictMine")}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

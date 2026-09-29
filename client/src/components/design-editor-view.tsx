import { useCallback, useEffect, useRef, useState } from "react";
import { useDarkMode } from "../hooks/use-dark-mode";
import type { BrandKit } from "../hooks/use-files";
import { track } from "../lib/analytics";
import { t } from "../lib/i18n";
import { useToast } from "../lib/toast";
import { cn } from "../lib/utils";

// Renders a `.fig` on the canvas as the embedded OpenPencil editor — an iframe on
// its OWN origin (the deployed editor), editing ONE design of the workspace: the
// file this view was opened on. Every save goes back to that file; everything that
// would make another document — a new design, a copy, an export — comes to Cycls,
// which writes it into the workspace (docs/notes/design.md, "Editing").
//
// postMessage protocol 2 (the editor's embed bridge, cycls-design editor/patches):
//   host → editor : load {protocol:2, doc, name, fig, brand?} · written {doc, id, ok}
//                   save · flush {id} · command {script, intent?} · theme {theme}
//   editor → host : ready {protocol} · loaded {doc} · saved {doc, id, name, fig}
//                   flushed {id, ok} · error · applied · commandError
//                   newDesign {size?} · saveCopy {doc, name, fig} · export {doc, files}
// `doc` tags one load: a save carrying an older tag (the document was replaced) is
// refused, not written over the file. An editor from before protocol 2 sends none
// of the new messages and never waits for `written`.
//
// An agent edit is applied and saved on the server BEFORE it reaches us (the Design
// tool checks every edit headlessly), then replayed here for the live cursor. If the
// replay fails (`commandError`) the saved file already has the edit, so we re-open
// the editor on it — never leave a stale document that a later auto-save would
// write back over the agent's change.

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

// What Cycls does for the editor: make a new design and open it in its own tab,
// write a new file beside this one (never over one — the server picks a free
// name), read the brand kit, open a file, refresh the Files panel.
export type DesignHost = {
  newDesign: (size?: [number, number]) => Promise<void>;
  writeNew: (path: string, data: BlobPart) => Promise<string>;
  brand: () => Promise<BrandKit | null>;
  openInCanvas: (path: string) => void;
  refreshFiles?: () => void;
};

// Every mounted editor, by the file it edits — so Cycls can have one save what's
// unsaved before its tab closes, the file is renamed or the canvas hides, can stop
// one from writing a file that is being deleted, and can open one full screen.
type Handle = { flush: (ms: number) => Promise<boolean>; detach: () => () => void; fullscreen: () => void };
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
// → re-attach (the delete failed): until then, their saves aren't written.
export function detachDesignEditorsUnder(prefix: string): () => void {
  const undo = handlesUnder(prefix).map((h) => h.detach());
  return () => undo.forEach((f) => f());
}
// The editor of `path`, full screen: the whole screen for designing, the same iframe
// (nothing reloads, saves go on). Called from a click — the browser asks for one.
export function fullscreenDesignEditor(path: string): void {
  [...(editors.get(path) ?? [])].pop()?.fullscreen();
}
export const canFullscreen = () => typeof document !== "undefined" && document.fullscreenEnabled === true;

// Chrome and Edge let a full-screen page keep Esc (holding it still leaves): the
// editor's Esc — deselect, leave a text edit — then doesn't end full screen.
type KeyboardLock = { lock?: (keys?: string[]) => Promise<void>; unlock?: () => void };
const keyboard = () => (navigator as Navigator & { keyboard?: KeyboardLock }).keyboard;

// What an export may write into the workspace, by the type the editor gives it.
const EXPORT_TYPES: Record<string, string> = {
  "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg", "application/pdf": "pdf",
};

type EditorMessage = {
  source?: string; type?: string; protocol?: number; doc?: string; id?: string; ok?: boolean; name?: string;
  fig?: string; message?: string; size?: [number, number];
  files?: { name: string; mime: string; data: string }[];
};

export function DesignEditorView({ url, path, name, editorUrl, writeFile, reload, host }: {
  url: string;        // blob URL of the .fig bytes (already fetched, authed)
  path: string;       // workspace path to write edits back to
  name: string;
  editorUrl: string;  // base URL of the deployed editor (config.design_editor_url)
  writeFile: (path: string, data: BlobPart, silent?: boolean) => Promise<void>;
  reload?: () => Promise<string>;   // a FRESH blob URL of the saved .fig (re-open after a failed replay)
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
  const dark = useDarkMode();
  const toast = useToast();
  const base = editorUrl.replace(/\/+$/, "");
  // The theme at first load; later changes go to the editor live (`theme`).
  const [src] = useState(() => `${base}/?embed=cycls&theme=${dark ? "dark" : "light"}`);
  const origin = (() => { try { return new URL(editorUrl).origin; } catch { return "*"; } })();
  const latest = useRef({ url, path, writeFile, reload, host, toast });
  latest.current = { url, path, writeFile, reload, host, toast };
  const protocol = useRef(0);           // the editor's: 2, or 0 for one from before the protocol
  const doc = useRef("");               // the current load's tag
  const detached = useRef(false);       // the file is being deleted: write nothing
  const flushes = useRef(new Map<string, (ok: boolean) => void>());
  const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const stem = (path.split("/").pop() ?? name).replace(/\.fig$/i, "");

  const post = useCallback((msg: Record<string, unknown>) =>
    frameRef.current?.contentWindow?.postMessage({ target: "cycls-editor", ...msg }, origin), [origin]);

  // Light/dark follows Cycls, live.
  useEffect(() => {
    if (protocol.current >= 2) post({ type: "theme", theme: dark ? "dark" : "light" });
  }, [dark, post]);

  // Full screen is the editor's box, not the page: the iframe stays where it is.
  const enterFullscreen = useCallback(() => {
    const box = boxRef.current;
    if (!box?.requestFullscreen || document.fullscreenElement) return;
    box.requestFullscreen({ navigationUI: "hide" }).then(() => {
      keyboard()?.lock?.(["Escape"]).catch(() => {});
      frameRef.current?.focus();   // keys go to the editor, not the button left behind
    }).catch(() => {});
  }, []);
  // What opens in another canvas tab (a new design, a copy, an export) isn't seen
  // under a full-screen editor, so it leaves full screen first.
  const leaveFullscreen = useCallback(async () => {
    if (boxRef.current && document.fullscreenElement === boxRef.current) await document.exitFullscreen().catch(() => {});
  }, []);
  useEffect(() => {
    let timer: number | undefined;
    let was = false;
    const onChange = () => {
      const on = !!boxRef.current && document.fullscreenElement === boxRef.current;
      setFull(on);
      setHint(on);
      window.clearTimeout(timer);
      if (on) timer = window.setTimeout(() => setHint(false), 2500);
      else if (was) keyboard()?.unlock?.();
      was = on;
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      window.clearTimeout(timer);
      if (was) keyboard()?.unlock?.();   // closed while full screen (the browser leaves it)
    };
  }, []);

  // This editor in the registry, for Cycls's flushes, deletes and full screen.
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
    };
    let set = editors.get(path);
    if (!set) editors.set(path, (set = new Set()));
    set.add(handle);
    return () => {
      set!.delete(handle);
      if (!set!.size) editors.delete(path);
    };
  }, [path, post, enterFullscreen]);

  useEffect(() => {
    let disposed = false;
    let readies = 0;
    // Once the editor reports the doc loaded, it's live and editable. A later
    // "error" is a background hiccup (e.g. an auto-save blip), NOT a broken editor —
    // so it must not latch the scary permanent "Editor error". Only a failure
    // BEFORE load is a real, sticky error.
    let loaded = false;
    const flash = (s: "saved" | "saveerror") => {
      if (disposed) return;
      setStatus(s);
      window.setTimeout(() => { if (!disposed) setStatus("ready"); }, 1500);
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

    const onMessage = async (e: MessageEvent) => {
      if (!frameRef.current || e.source !== frameRef.current.contentWindow) return;   // this editor only
      if (origin !== "*" && e.origin !== origin) return;
      const m = e.data as EditorMessage;
      if (!m || m.source !== "cycls-editor") return;
      const { host, toast } = latest.current;
      if (m.type === "ready") {
        protocol.current = typeof m.protocol === "number" ? m.protocol : 0;
        // The first load has the bytes this view fetched; a later one (the editor
        // reloaded itself) reads the file again, for what's saved now.
        let source = sourceRef.current;
        sourceRef.current = null;
        if (!source && readies > 0 && latest.current.reload) {
          try { source = await latest.current.reload(); } catch { source = null; }
        }
        readies++;
        try {
          const [buf, brand] = await Promise.all([
            fetch(source ?? latest.current.url).then((r) => r.arrayBuffer()),
            protocol.current >= 2 && host ? host.brand().catch(() => null) : Promise.resolve(null),
          ]);
          if (disposed) return;
          doc.current = `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
          post({ type: "load", protocol: 2, doc: doc.current, name, fig: toBase64(new Uint8Array(buf)), ...(brand ? { brand } : {}) });
          if (protocol.current >= 2) post({ type: "theme", theme: document.body.classList.contains("dark") ? "dark" : "light" });
        } catch {
          if (!disposed) setStatus("error");
        } finally {
          if (source && source !== latest.current.url) URL.revokeObjectURL(source);
        }
      } else if (m.type === "loaded") {
        loaded = true;
        if (!disposed) setStatus("ready");
      } else if (m.type === "saved" && typeof m.fig === "string") {
        const reply = (ok: boolean) => post({ type: "written", doc: m.doc, id: m.id, ok });
        // A save from a document since replaced, or of a file being deleted: not written.
        if ((m.doc && m.doc !== doc.current) || detached.current) {
          reply(false);
          return;
        }
        try {
          // Cast: TS 5.7 types Uint8Array as Uint8Array<ArrayBufferLike>, which
          // doesn't structurally match BlobPart's ArrayBufferView<ArrayBuffer>.
          await latest.current.writeFile(latest.current.path, fromBase64(m.fig) as unknown as BlobPart);
          reply(true);
          flash("saved");
        } catch {
          reply(false);
          flash("saveerror");
        }
      } else if (m.type === "flushed" && typeof m.id === "string") {
        flushes.current.get(m.id)?.(m.ok === true);
        flushes.current.delete(m.id);
      } else if (m.type === "commandError") {
        // The live replay of an agent edit failed; the saved file already holds the
        // edit. Re-open the editor on it (a fresh fetch — `url` may predate the edit).
        try { sourceRef.current = latest.current.reload ? await latest.current.reload() : null; } catch { sourceRef.current = null; }
        if (disposed) return;
        loaded = false;
        readies = 0;
        setStatus("loading");
        setFrameKey((k) => k + 1);
      } else if (m.type === "error") {
        // Pre-load: the editor genuinely failed to open → sticky "Editor error".
        // Post-load: a background blip (e.g. an auto-save) → transient, then the
        // live editor stays up.
        if (!disposed) loaded ? flash("saveerror") : setStatus("error");
      } else if (m.type === "newDesign" && host) {
        await leaveFullscreen();
        try { await host.newDesign(Array.isArray(m.size) ? m.size : undefined); } catch { toast.error(t("newDesignFailed")); }
      } else if (m.type === "export" && Array.isArray(m.files)) {
        await exportFiles(m.files);
      } else if (m.type === "saveCopy" && typeof m.fig === "string" && host) {
        setCopyOf({ fig: m.fig });
      }
    };
    // The agent edits an open design live: chat.tsx dispatches this when its
    // Design tool fires a `design_command`; we relay the script to our editor.
    const onCommand = (e: Event) => {
      const d = (e as CustomEvent).detail as { path?: string; script?: string; intent?: string };
      if (!d || d.path !== latest.current.path || typeof d.script !== "string") return;
      post({ type: "command", script: d.script, intent: d.intent });
    };

    window.addEventListener("message", onMessage);
    window.addEventListener("cycls:design-command", onCommand as EventListener);
    return () => {
      disposed = true;
      window.removeEventListener("message", onMessage);
      window.removeEventListener("cycls:design-command", onCommand as EventListener);
    };
  }, [origin, post, name, dir, stem, frameKey, leaveFullscreen]);

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
      {/* Own-origin editor iframe (not sandboxed): the app needs its full
          capabilities — CanvasKit, workers, storage — on its real origin. */}
      <iframe key={frameKey} ref={frameRef} src={src} title={name} className="h-full w-full border-0" />
      {full && (
        // A strip along the top middle: the pointer there (or the first moments of
        // full screen) shows the way out. The iframe keeps every other pointer event.
        <div className="group absolute left-1/2 top-0 z-10 flex h-2 w-72 -translate-x-1/2 justify-center hover:h-14">
          <button
            onClick={() => void leaveFullscreen()}
            className={cn(
              "mt-2 flex h-8 items-center gap-1.5 rounded-full bg-background/90 px-3 text-xs text-foreground shadow backdrop-blur transition-opacity cursor-pointer",
              hint ? "opacity-100" : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100",
            )}
          >
            <svg className="size-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3.75v4.5h-4.5m12-4.5v4.5h4.5m0 7.5h-4.5v4.5m-7.5 0v-4.5h-4.5" />
            </svg>
            {t("exitFullScreen")}
          </button>
        </div>
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
    </div>
  );
}

// "Save a copy": the copy's name, then Cycls writes it beside the design and opens it.
function SaveCopyDialog({ initial, onCancel, onSave }: {
  initial: string;
  onCancel: () => void;
  onSave: (name: string) => void;
}) {
  const [value, setValue] = useState(initial);
  const name = value.trim().replace(/[\\/]+/g, "-").replace(/\.fig$/i, "");
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
          onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
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

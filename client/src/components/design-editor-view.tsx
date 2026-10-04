import { useCallback, useEffect, useRef, useState } from "react";
import { useDarkMode } from "../hooks/use-dark-mode";
import { useEscape } from "../hooks/use-escape";
import type { BrandKit, DesignVersion, FetchVersioned, WriteFile } from "../hooks/use-files";
import { track } from "../lib/analytics";
import { getLang, t, useLang } from "../lib/i18n";
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
//                   save · flush {id} · command {script, intent?} · theme {theme} · locale {lang}
//                   fit (the editor's box changed size: fit the design again — feature "fit")
//   editor → host : ready {protocol, features?} · loaded {doc} · saved {doc, id, name, fig}
//                   flushed {id, ok} · error · applied · commandError · selection {doc, frame, nodes}
//                   newDesign {size?} · saveCopy {doc, name, fig} · export {doc, files}
// Every load reads the design with its version, and its saves name it as their
// base: a save over a newer file is refused (docs/notes/design.md, "No save
// overwrites what it didn't see").
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
  // A design with its version, which its saves name as their base (design/store.py),
  // and its earlier versions — absent on an older server or a shared view.
  fetchVersioned?: FetchVersioned;
  listVersions?: (path: string) => Promise<DesignVersion[]>;
  versionBlob?: (path: string, id: string) => Promise<Blob>;
  restoreVersion?: (path: string, id: string) => Promise<{ version: string }>;
};

// Every mounted editor, by the file it edits — so Cycls can have one save what's
// unsaved before its tab closes, the file is renamed or the canvas hides, can stop
// one from writing a file that is being deleted, and can open one full screen.
type Handle = { flush: (ms: number) => Promise<boolean>; detach: () => () => void; fullscreen: () => void; reload: () => void };
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
// Re-open the editors of `path` on the file as saved now — after a restore, or a
// slide change made beside them (the deck viewer's own).
export function reloadDesignEditors(path: string): void {
  for (const h of editors.get(path) ?? []) h.reload();
}

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
  fig?: string; message?: string; size?: [number, number]; features?: string[];
  files?: { name: string; mime: string; data: string }[];
  frame?: string | null; nodes?: DesignSelection["nodes"];
};

// What the person has selected in an open design, by name (the editor's `selection`)
// — what "Add selection" attaches to a message. The latest, per design.
export type DesignSelection = { path: string; frame: string | null; nodes: { name: string; type: string; text?: string }[] };
const selections = new Map<string, DesignSelection>();
export const designSelection = (path: string) => selections.get(path) ?? null;

// An agent edit to replay in the editor: its script, the cursor's label, and the
// design's version once the server saved it.
type Command = { script: string; intent?: string; version?: string };

export function DesignEditorView({ url, path, name, editorUrl, writeFile, reload, host }: {
  url: string;        // blob URL of the .fig bytes (already fetched, authed) — used when there's no host.fetchVersioned
  path: string;       // workspace path to write edits back to
  name: string;
  editorUrl: string;  // base URL of the deployed editor (config.design_editor_url)
  writeFile: WriteFile;
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
  // A save refused because the design changed elsewhere (not by an agent edit landing
  // here): the person decides, and saves wait meanwhile. `fig` is the refused save.
  const [conflict, setConflict] = useState<{ version: string; fig: string } | null>(null);
  const conflictRef = useRef(conflict);
  conflictRef.current = conflict;
  const dark = useDarkMode();
  const lang = useLang();
  const toast = useToast();
  const base = editorUrl.replace(/\/+$/, "");
  // The theme and language at first load; later changes go to the editor live (`theme`, `locale`).
  const [src] = useState(() => `${base}/?embed=cycls&theme=${dark ? "dark" : "light"}&lang=${lang}`);
  const version = useRef<string | null>(null);        // the version the editor's document stands on: its saves' base
  const loadedVersion = useRef<string | null>(null);  // the version this load read
  const commands = useRef<Command[]>([]);             // agent edits waiting to replay, one at a time
  const replaying = useRef<Command | null>(null);
  const editorLoaded = useRef(false);                 // the editor has this load's document open (`loaded`)
  const pending = useRef<{ version: string; timer: number } | null>(null);   // a 412 an agent edit may yet explain
  const force = useRef(false);                        // "keep mine": the next save writes over the newer file
  const origin = (() => { try { return new URL(editorUrl).origin; } catch { return "*"; } })();
  const latest = useRef({ url, path, writeFile, reload, host, toast });
  latest.current = { url, path, writeFile, reload, host, toast };
  const protocol = useRef(0);           // the editor's: 2, or 0 for one from before the protocol
  const doc = useRef("");               // the current load's tag
  const detached = useRef(false);       // the file is being deleted: write nothing
  const flushes = useRef(new Map<string, (ok: boolean) => void>());
  const features = useRef<Set<string>>(new Set());   // what the editor does beyond protocol 2 (its `ready`)
  const dir = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  const stem = (path.split("/").pop() ?? name).replace(/\.fig$/i, "");

  const post = useCallback((msg: Record<string, unknown>) =>
    frameRef.current?.contentWindow?.postMessage({ target: "cycls-editor", ...msg }, origin), [origin]);

  // Light/dark and the language follow Cycls, live.
  useEffect(() => {
    if (protocol.current >= 2) post({ type: "theme", theme: dark ? "dark" : "light" });
  }, [dark, post]);
  useEffect(() => {
    if (protocol.current >= 2) post({ type: "locale", lang });
  }, [lang, post]);

  // One agent edit replays at a time; the next goes once the editor says `applied`.
  // One the editor loaded already (its version is what it read) is in the document.
  // None goes before the editor has the document open: an edit that arrived while it
  // was still loading got `commandError: no document is open`, and a whole reload.
  const pump = useCallback(() => {
    if (replaying.current || !editorLoaded.current) return;
    let next = commands.current.shift();
    while (next?.version && next.version === loadedVersion.current) next = commands.current.shift();
    if (!next) return;
    replaying.current = next;
    post({ type: "command", script: next.script, intent: next.intent });
  }, [post]);

  // Re-open the editor on the saved file (a fresh fetch, with its version).
  const reopen = useCallback(() => {
    commands.current = [];
    replaying.current = null;
    editorLoaded.current = false;
    setStatus("loading");
    setFrameKey((k) => k + 1);
  }, []);

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

  // A much bigger or smaller editor — full screen, the canvas expanded over the chat —
  // fits the design to it again. (The editor does, unless the person has set their own
  // view; it stayed small in a corner, at the docked zoom.)
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
      reload: reopen,
    };
    let set = editors.get(path);
    if (!set) editors.set(path, (set = new Set()));
    set.add(handle);
    return () => {
      set!.delete(handle);
      if (!set!.size) editors.delete(path);
    };
  }, [path, post, enterFullscreen, reopen]);

  useEffect(() => {
    let disposed = false;
    let readies = 0;
    // Once the editor reports the doc loaded, it's live and editable. A later
    // "error" is a background hiccup (e.g. an auto-save blip), NOT a broken editor —
    // so it must not latch the scary permanent "Editor error". Only a failure
    // BEFORE load is a real, sticky error.
    let loaded = false;
    let spoke = false;    // the editor has said `ready`: its protocol is known
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
        features.current = new Set(Array.isArray(m.features) ? m.features : []);
        let source = sourceRef.current;
        sourceRef.current = null;
        version.current = loadedVersion.current = null;
        commands.current = [];          // edits made before now are in the file this load reads
        replaying.current = null;
        editorLoaded.current = false;   // ones that arrive from here wait until it is open
        spoke = true;
        if (protocol.current >= 2 && host?.fetchVersioned) {
          // Every load reads the file afresh, with its version: what its saves name as
          // their base, so a save over a newer file is refused (design/store.py).
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
          // The first load has the bytes this view fetched; a later one (the editor
          // reloaded itself) reads the file again, for what's saved now.
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
        // What it read holds every edit up to the one whose version it is; the rest replay.
        const waiting = commands.current;
        for (let i = waiting.length - 1; i >= 0; i--) {
          if (waiting[i].version && waiting[i].version === loadedVersion.current) { waiting.splice(0, i + 1); break; }
        }
        editorLoaded.current = true;
        pump();
      } else if (m.type === "saved" && typeof m.fig === "string") {
        const reply = (ok: boolean) => post({ type: "written", doc: m.doc, id: m.id, ok });
        // A save from a document since replaced, or of a file being deleted: not written.
        if ((m.doc && m.doc !== doc.current) || detached.current) {
          reply(false);
          return;
        }
        if (conflictRef.current) {   // the person is deciding: nothing is written meanwhile
          reply(false);
          return;
        }
        const keep = force.current;
        try {
          // Cast: TS 5.7 types Uint8Array as Uint8Array<ArrayBufferLike>, which
          // doesn't structurally match BlobPart's ArrayBufferView<ArrayBuffer>.
          const r = await latest.current.writeFile(latest.current.path, fromBase64(m.fig) as unknown as BlobPart, {
            silent: true, ...(version.current ? { base: version.current } : {}), ...(keep ? { force: true } : {}),
          });
          if (keep) force.current = false;
          if (r && r.version && version.current !== null) version.current = r.version;
          reply(true);
          flash("saved");
        } catch (err) {
          reply(false);
          if ((err as { status?: number }).status === 412) {
            const now = await (err as { response?: Response }).response?.json().then((j) => j?.version).catch(() => undefined);
            stale(typeof now === "string" ? now : "", m.fig);
          } else {
            flash("saveerror");
          }
        }
      } else if (m.type === "flushed" && typeof m.id === "string") {
        flushes.current.get(m.id)?.(m.ok === true);
        flushes.current.delete(m.id);
      } else if (m.type === "applied") {
        // An agent edit is in the document now: saves go on from its version, and one
        // refused while it replayed goes now.
        const done = replaying.current;
        replaying.current = null;
        if (done?.version && version.current !== null) {
          version.current = done.version;
          post({ type: "flush", id: `v${done.version}` });
        }
        pump();
      } else if (m.type === "selection" && Array.isArray(m.nodes)) {
        const sel: DesignSelection = { path: latest.current.path, frame: typeof m.frame === "string" ? m.frame : null, nodes: m.nodes };
        if (sel.nodes.length) selections.set(sel.path, sel);
        else selections.delete(sel.path);
        window.dispatchEvent(new CustomEvent("cycls:design-selection", { detail: sel }));
      } else if (m.type === "commandError") {
        // The live replay of an agent edit failed; the saved file already holds the
        // edit. Re-open the editor on it (a fresh fetch — `url` may predate the edit).
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
    // A save refused as stale. While an agent edit is landing here that's expected —
    // it saved the file first — and the save goes again once the edit is applied.
    // Otherwise the design changed elsewhere; the agent's event may still be on its
    // way (it travels apart from the save's answer), so give it a moment first.
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
        }, 3000),
      };
    };

    // The agent edits an open design live: chat.tsx dispatches this when its
    // Design tool fires a `design_command`; it replays here, one at a time.
    const onCommand = (e: Event) => {
      const d = (e as CustomEvent).detail as { path?: string; script?: string; intent?: string; version?: string };
      if (!d || d.path !== latest.current.path || typeof d.script !== "string") return;
      if (spoke && protocol.current < 2) {   // an editor from before the protocol never says `applied`
        post({ type: "command", script: d.script, intent: d.intent });
        return;
      }
      if (pending.current && d.version === pending.current.version) {   // the change was this edit's
        window.clearTimeout(pending.current.timer);
        pending.current = null;
      }
      commands.current.push({ script: d.script, intent: d.intent, version: typeof d.version === "string" ? d.version : undefined });
      pump();
    };

    window.addEventListener("message", onMessage);
    window.addEventListener("cycls:design-command", onCommand as EventListener);
    return () => {
      disposed = true;
      if (pending.current) window.clearTimeout(pending.current.timer);
      pending.current = null;
      window.removeEventListener("message", onMessage);
      window.removeEventListener("cycls:design-command", onCommand as EventListener);
    };
  }, [origin, post, name, dir, stem, frameKey, leaveFullscreen, pump]);

  // The conflict's three ways out.
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
        return;   // keep this editor's work: nothing was saved anywhere
      }
    }
    reopen();   // this design, as it is now
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
      {conflict && <ConflictDialog canCopy={!!host} onChoose={(c) => void resolve(c)} />}
    </div>
  );
}

// The design changed elsewhere — another tab, another person, a script — while this
// editor had unsaved work: which one stands. Nothing is written until they choose.
function ConflictDialog({ canCopy, onChoose }: { canCopy: boolean; onChoose: (c: "latest" | "mine" | "copy") => void }) {
  const choice = "w-full cursor-pointer rounded-md px-3 py-2 text-start text-xs hover:bg-secondary";
  useEscape(() => {});   // it wants an answer: Escape doesn't dismiss it, nor close the canvas under it
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

// "Save a copy": the copy's name, then Cycls writes it beside the design and opens it.
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

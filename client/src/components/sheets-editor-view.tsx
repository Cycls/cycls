import { useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDarkMode } from "../hooks/use-dark-mode";
import type { OfficeEditorApi, OfficeOpen, SheetsOpened } from "../hooks/use-files";
import { useComments, type CellSpot, type CommentChange, type SheetCommentThread } from "../lib/comments";
import { getLang, t, useLang } from "../lib/i18n";
import { CanvasHeaderSlot } from "./canvas-header-slot";
import { publishSelection } from "./design-editor-view";
import { SheetGlyph } from "./file-glyph";
import { LoadingBar } from "./loading-bar";
import { cn } from "../lib/utils";

// Cycls Sheets in the canvas: a header (where the file is, when it changed, Open ⌄) over the editor,
// which the cycls-office service serves into an iframe.
//
// Protocol 1 (postMessage, JSON). Cycls → editor {target: "cycls-sheets", type, …}, posted to the
// editor's exact origin only; editor → Cycls {source: "cycls-sheets", type, …}, heard only from that
// origin and that frame.
//   Cycls → editor   load {doc, name, snapshot, activeSheet, readonly}   theme   locale   readonly
//                    written {doc, id, ok}   flush {id}   save   command {doc, id, mutations}
//   editor → Cycls   ready {protocol, features}   loaded {doc}   error {doc, message}
//                    dirty {doc, dirty}   saved {doc, id, snapshot, ops}   flushed {id, ok}
//                    applied {doc, id, ok}   selection {doc, sheet, ranges: [{a1, text?}]}
// The selection is offered to the composer like a design's ("Add selection"): the sheet is its page,
// each range a node, so the agent reads "[Selected in budget.xlsx page "Sheet1": B8:E8 (cells)]".
// A save writes the editor's workbook back into the .xlsx through the service (only what differs
// changes) and keeps the replaced version; a file changed elsewhere since it was opened asks first.
// The agent's `sheets` edits are already in the file when they arrive (a `sheets_command` from the
// chat): the editor replays them, read-only while the agent works; one that does not replay reopens
// the file.

// Mounted editors by path: saved before a message is sent, so the agent reads what the person sees.
type Handle = { flush: (ms: number) => Promise<boolean> };
const editors = new Map<string, Set<Handle>>();
export const flushSheetsEditor = (path: string, ms = 3000) =>
  Promise.all([...(editors.get(path) ?? [])].map((h) => h.flush(ms))).then((oks) => oks.every(Boolean));
export const sheetsEditorsOpen = () => editors.size > 0;
export const flushAllSheetsEditors = (ms = 1500) =>
  Promise.all([...editors.values()].flatMap((set) => [...set]).map((h) => h.flush(ms))).then((oks) => oks.every(Boolean));

/** A `sheets_command` event from the chat: the agent's edit, already written to `path`. */
export type SheetsCommand = { path: string; mutations: unknown[] | null; version?: string; intent?: string; reload: boolean };
// What the editor asks of a comment (its own comment UI): checked here, then sent through the comment store.
type CommentAsk = {
  rid?: unknown; op?: unknown; id?: unknown; reply?: unknown; text?: unknown;
  sheet?: unknown; sheet_name?: unknown; cell?: unknown;
};
export function sheetsCommandDetail(ev: Record<string, unknown>): SheetsCommand {
  return {
    path: String(ev.path),
    mutations: Array.isArray(ev.mutations) ? ev.mutations : null,
    version: typeof ev.version === "string" ? ev.version : undefined,
    intent: typeof ev.intent === "string" ? ev.intent.slice(0, 80) : undefined,
    reload: ev.reload === true,
  };
}

/** Asks once per file whether this workspace opens it in Cycls Sheets; otherwise shows `preview`. */
export function SheetsOrPreview({ path, name, api, preview, onDownload, live, contentKey }: {
  path: string;
  name: string;
  api: OfficeEditorApi;
  preview: ReactNode;
  onDownload?: () => void;
  live?: boolean;
  contentKey?: string | null;   // changes each time the canvas fetches the file again
}) {
  const [open, setOpen] = useState<OfficeOpen | null>(null);
  useEffect(() => {
    let cancelled = false;
    setOpen(null);
    api.sheets(path)
      .then((o) => { if (!cancelled) setOpen(o); })
      .catch(() => { if (!cancelled) setOpen({ editor: false, reason: "unavailable" }); });
    return () => { cancelled = true; };
  }, [api, path]);
  if (!open) return <LoadingBar />;
  return open.editor
    ? <SheetsEditorView url={open.url} path={path} name={name} api={api} onDownload={onDownload} fallback={preview} live={live} contentKey={contentKey} />
    : <>{preview}</>;
}

function modifiedLabel(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const locale = getLang() === "ar" ? "ar-SA-u-ca-gregory-nu-latn" : undefined;
  const sameDay = d.toDateString() === new Date().toDateString();
  const time = sameDay
    ? d.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString(locale, { day: "numeric", month: "short", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
  return t("sheetsLastModified").replace("{time}", time);
}

export function SheetsEditorView({ url, path, name, api, onDownload, fallback, live = false, contentKey }: {
  url: string;
  path: string;
  name: string;
  api?: OfficeEditorApi;
  onDownload?: () => void;
  fallback?: ReactNode;
  live?: boolean;     // the agent is working: read-only, its edits replayed
  contentKey?: string | null;   // changes each time the canvas fetches the file again
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const slots = useContext(CanvasHeaderSlot);
  const dark = useDarkMode();
  const lang = useLang();
  const [ready, setReady] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [opened, setOpened] = useState<SheetsOpened | null>(null);
  const [failed, setFailed] = useState(false);
  const [menu, setMenu] = useState(false);
  const [noticesOpen, setNoticesOpen] = useState(false);
  type Status = "saved" | "saving" | "dirty" | "error";
  const [status, setStatus] = useState<Status>("saved");
  const [conflict, setConflict] = useState<string | null>(null);   // the file's newer version
  const [savedAt, setSavedAt] = useState<string | null>(null);     // when this editor last wrote the file
  const editable = !!api;
  const doc = useRef("");
  const version = useRef("");       // what the next save names as its base
  const forceNext = useRef(false);  // "Keep mine": the next save writes over the newer file
  const saving = useRef<Promise<void> | null>(null);
  const loadedRef = useRef(false);
  const liveRef = useRef(live);
  liveRef.current = live;
  const [intent, setIntent] = useState<string | null>(null);   // what the agent's last edit did
  const seq = useRef(0);
  const commands = useRef(new Map<string, string | undefined>());   // command id → the file's version after it
  const flushes = useRef(new Map<string, (ok: boolean) => void>());
  const reopenRef = useRef<() => void>(() => {});
  const features = useRef<string[]>([]);   // what the editor said it does (ready)
  // Comments on cells: the workspace's record for this file (the same store as a design's), polled; none on a
  // view that cannot comment (a share).
  const comments = useComments(api ? path : undefined);
  const commentsRef = useRef(comments);
  commentsRef.current = comments;
  const answerRef = useRef<(ask: CommentAsk) => Promise<void>>(async () => {});
  // Never "*": anything sent goes to the editor's origin or nowhere.
  const origin = (() => {
    try {
      const u = new URL(url, window.location.href);
      return /^https?:$/.test(u.protocol) ? u.origin : null;
    } catch {
      return null;
    }
  })();
  // Fixed at first load so the iframe never reloads; later changes are posted.
  const [src] = useState(() => {
    const u = new URL(url, window.location.href);
    u.searchParams.set("embed", "cycls");
    u.searchParams.set("theme", dark ? "dark" : "light");
    u.searchParams.set("lang", lang);
    return u.toString();
  });

  const post = useCallback((msg: Record<string, unknown>) => {
    if (origin) frameRef.current?.contentWindow?.postMessage({ target: "cycls-sheets", ...msg }, origin);
  }, [origin]);

  // The workbook, read by the service (cached by version).
  useEffect(() => {
    if (!api) return;
    let cancelled = false;
    setOpened(null);
    setFailed(false);
    api.sheetsOpen(path)
      .then((o) => { if (!cancelled) setOpened(o); })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, [api, path]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (!origin || e.origin !== origin || e.source !== frameRef.current?.contentWindow) return;
      const msg = e.data as { source?: string; type?: string; doc?: string };
      if (msg?.source !== "cycls-sheets") return;
      if (msg.type === "ready") {
        const f = (msg as { features?: unknown }).features;
        features.current = Array.isArray(f) ? f.filter((x): x is string => typeof x === "string") : [];
        setReady(true);
      }
      else if (msg.type === "comment" && msg.doc === doc.current) void answerRef.current(msg as unknown as CommentAsk);
      else if (msg.type === "loaded" && msg.doc === doc.current) { loadedRef.current = true; setLoaded(true); }
      else if (msg.type === "applied" && msg.doc === doc.current) {
        const { id, ok } = msg as { id?: string; ok?: boolean };
        if (typeof id !== "string" || !commands.current.has(id)) return;
        const after = commands.current.get(id);
        commands.current.delete(id);
        if (ok && after) version.current = after;   // the open workbook is the file again
        else if (!ok) reopenRef.current();
      } else if (msg.type === "selection" && msg.doc === doc.current) {
        const { sheet, ranges } = msg as { sheet?: unknown; ranges?: unknown };
        if (typeof sheet !== "string" || !Array.isArray(ranges)) return;
        const nodes = ranges
          .filter((r): r is { a1: string; text?: unknown } => !!r && typeof (r as { a1?: unknown }).a1 === "string")
          .slice(0, 5)
          .map((r) => ({ name: r.a1.slice(0, 40), type: r.a1.includes(":") ? "cells" : "cell",
                         ...(typeof r.text === "string" && r.text ? { text: r.text.slice(0, 80) } : {}) }));
        publishSelection({ path, frame: null, page: sheet.slice(0, 80), nodes });
      } else if (msg.type === "flushed") {
        const { id, ok } = msg as { id?: string; ok?: boolean };
        if (typeof id === "string") { flushes.current.get(id)?.(ok === true); flushes.current.delete(id); }
      }
      else if (msg.type === "print" && msg.doc === doc.current) void printRef.current();
      else if (msg.type === "error" && msg.doc === doc.current) setFailed(true);
      else if (msg.type === "dirty" && msg.doc === doc.current) {
        const d = (msg as { dirty?: boolean }).dirty;
        setStatus((now) => (now === "saving" ? now : d ? "dirty" : "saved"));
      } else if (msg.type === "saved" && msg.doc === doc.current) {
        const { id, snapshot, ops } = msg as { id?: string; snapshot?: unknown; ops?: unknown[] };
        if (typeof id === "string" && snapshot) void save(id, snapshot, Array.isArray(ops) ? ops : []);
      }
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      publishSelection({ path, frame: null, nodes: [] });   // closed: nothing selected here any more
    };
  }, [origin, path]);

  // Send the workbook once both sides are ready (and again if the file's version changes).
  useEffect(() => {
    if (!ready || !opened) return;
    doc.current = `${path}@${opened.version}`;
    version.current = opened.version;
    commands.current.clear();
    loadedRef.current = false;
    setLoaded(false);
    setStatus("saved");
    setConflict(null);
    setSavedAt(null);
    post({ type: "load", doc: doc.current, name, snapshot: opened.snapshot, activeSheet: opened.activeSheet, readonly: !editable || liveRef.current });
  }, [ready, opened, path, name, post, editable]);

  // While the agent works the person watches; editing comes back when the turn ends.
  useEffect(() => {
    if (!ready) return;
    post({ type: "readonly", readonly: !editable || live });
    if (!live) setIntent(null);
  }, [live, ready, editable, post]);

  // The workbook's comments, given to the editor whenever they change (its own comment UI shows them; what is
  // written there comes back as `comment` and goes through the store).
  const threads = comments?.threads;
  const commentsLoaded = comments?.loaded;
  const meId = comments?.me;
  useEffect(() => {
    if (!ready || !loaded || !commentsLoaded || !features.current.includes("comments")) return;
    const host = commentsRef.current?.host;
    const me = host?.me ? { id: meId || host.me.id, name: host.me.name, ...(host.me.image ? { image: host.me.image } : {}) } : undefined;
    post({ type: "comments", doc: doc.current, threads: threads ?? [], me, ...(host?.agent ? { agent: host.agent } : {}) });
  }, [ready, loaded, threads, commentsLoaded, meId, post]);

  answerRef.current = async (ask: CommentAsk) => {
    const store = commentsRef.current?.store;
    const forDoc = doc.current;
    const reply = (ok: boolean, thread: SheetCommentThread | null = null, error?: string) =>
      post({ type: "commentDone", doc: forDoc, rid: ask.rid, ok, thread, ...(error ? { error } : {}) });
    if (!store || typeof ask.rid !== "string") return reply(false, null, "Comments are off here.");
    try {
      if (ask.op === "add") {
        const spot: CellSpot = { sheet: String(ask.sheet ?? ""), cell: typeof ask.cell === "string" ? ask.cell : null, ...(ask.sheet_name ? { sheet_name: String(ask.sheet_name).slice(0, 120) } : {}) };
        const thread = await store.add(spot, String(ask.text ?? ""));
        return reply(true, thread as unknown as SheetCommentThread);
      }
      if (typeof ask.id !== "string") return reply(false, null, "Which comment?");
      const reply_ = typeof ask.reply === "string" ? { reply: ask.reply } : {};
      let body: CommentChange;
      switch (ask.op) {
        case "reply": body = { op: "reply", text: String(ask.text ?? "") }; break;
        case "edit": body = { op: "edit", text: String(ask.text ?? ""), ...reply_ }; break;
        case "resolve": case "reopen": body = { op: ask.op }; break;
        case "delete": body = { op: "delete", ...reply_ }; break;
        case "move": body = { op: "move", sheet: String(ask.sheet ?? ""), cell: typeof ask.cell === "string" ? ask.cell : null, ...(ask.sheet_name ? { sheet_name: String(ask.sheet_name).slice(0, 120) } : {}) }; break;
        default: return reply(false, null, "Unknown comment change.");
      }
      await store.change(ask.id, body);
      const now = store.get().threads.find((x) => x.id === ask.id) ?? null;
      return reply(true, now as unknown as SheetCommentThread | null);
    } catch (e) {
      return reply(false, null, String((e as Error)?.message ?? e));
    }
  };

  // The file again, as saved (an edit that did not replay, or one too large to send, or a change made elsewhere).
  // What had focus on the page keeps it: the editor takes focus when a workbook loads, which would pull the
  // person out of the message they are typing.
  const keepFocus = useRef<HTMLElement | null>(null);
  const reopen = useCallback(() => {
    if (!api) return;
    const el = document.activeElement;
    keepFocus.current = el instanceof HTMLElement && el !== document.body && el !== frameRef.current ? el : null;
    api.sheetsOpen(path).then(setOpened).catch(() => setFailed(true));
  }, [api, path]);
  reopenRef.current = reopen;
  useEffect(() => {
    if (!loaded || !keepFocus.current) return;
    const el = keepFocus.current;
    keepFocus.current = null;
    // The editor may take focus a moment after it says the workbook is in.
    const give = () => { if (document.activeElement === frameRef.current && el.isConnected) el.focus({ preventScroll: true }); };
    const timers = [0, 250, 750, 1500].map((ms) => window.setTimeout(give, ms));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [loaded]);

  // The agent's edits (from chat.tsx).
  useEffect(() => {
    const onCommand = (e: Event) => {
      const d = (e as CustomEvent<SheetsCommand>).detail;
      if (!d || d.path !== path) return;
      if (d.intent) setIntent(d.intent);
      if (d.reload || !d.mutations || !loadedRef.current) { reopen(); return; }
      const id = `c${++seq.current}`;
      commands.current.set(id, d.version);
      post({ type: "command", doc: doc.current, id, mutations: d.mutations });
    };
    window.addEventListener("cycls:sheets-command", onCommand);
    return () => window.removeEventListener("cycls:sheets-command", onCommand);
  }, [path, post, reopen]);

  // Save what is unsaved now (before a message goes): true once it is in the file.
  useEffect(() => {
    const handle: Handle = {
      flush: (ms) => new Promise<boolean>((resolve) => {
        if (!loadedRef.current || !editable) return resolve(true);
        const id = `f${++seq.current}`;
        const timer = window.setTimeout(() => { flushes.current.delete(id); resolve(false); }, ms);
        flushes.current.set(id, (ok) => { window.clearTimeout(timer); resolve(ok); });
        post({ type: "flush", id });
      }),
    };
    const set = editors.get(path) ?? new Set<Handle>();
    set.add(handle);
    editors.set(path, set);
    return () => {
      set.delete(handle);
      if (!set.size) editors.delete(path);
    };
  }, [path, post, editable]);

  // One save at a time; the editor sends the next once this one is answered.
  const save = async (id: string, snapshot: unknown, ops: unknown[]) => {
    if (!api) return;
    const forDoc = doc.current;
    const run = (async () => {
      setStatus("saving");
      try {
        const force = forceNext.current;
        const r = await api.sheetsSave(path, version.current, { snapshot, ops }, force);
        if (forDoc !== doc.current) return;
        if ("conflict" in r) {
          setConflict(r.conflict);
          setStatus("error");
          post({ type: "written", doc: forDoc, id, ok: false });
          return;
        }
        forceNext.current = false;
        version.current = r.version;
        if (!r.unchanged && r.modified) setSavedAt(r.modified);
        setConflict(null);
        setStatus("saved");
        post({ type: "written", doc: forDoc, id, ok: true });
      } catch {
        setStatus("error");
        post({ type: "written", doc: forDoc, id, ok: false });
      }
    })();
    saving.current = run;
    await run;
  };

  const loadLatest = () => {
    setConflict(null);
    setOpened(null);
    reopen();
  };
  const keepMine = () => {
    forceNext.current = true;
    setConflict(null);
    post({ type: "save" });
  };

  // A file changed some other way (the agent's other tools, another tab or person): each time the canvas
  // fetches the file again (a turn ended, a refresh), its version is checked once the agent is done — the editor
  // takes the new file in, or, with changes not yet saved, shows the bar that asks.
  const statusRef = useRef(status);
  statusRef.current = status;
  const conflictRef = useRef(conflict);
  conflictRef.current = conflict;
  const seenContent = useRef(contentKey);
  const needsCheck = useRef(false);
  if (contentKey !== seenContent.current) {
    seenContent.current = contentKey;
    needsCheck.current = true;
  }
  // Nor does an editor left open wait for a turn: it looks again when the page comes back into view and every
  // 30 s while it is shown, so a change made in another tab or by someone else reaches it.
  const [poll, setPoll] = useState(0);
  useEffect(() => {
    if (!api?.sheetsVersion) return;
    const look = () => {
      if (document.visibilityState !== "visible") return;
      needsCheck.current = true;
      setPoll((n) => n + 1);
    };
    const timer = window.setInterval(look, 30_000);
    window.addEventListener("focus", look);
    document.addEventListener("visibilitychange", look);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", look);
      document.removeEventListener("visibilitychange", look);
    };
  }, [api]);
  useEffect(() => {
    if (!needsCheck.current || !api?.sheetsVersion || live || !loaded || commands.current.size) return;
    needsCheck.current = false;
    let cancelled = false;
    void (async () => {
      await saving.current;
      const now = await api.sheetsVersion!(path).catch(() => null);
      if (cancelled || !now?.version || now.version === version.current || conflictRef.current !== null) return;
      // Taken in quietly when nothing here is unsaved and the person is not in the editor (a cell being typed
      // into is not saved yet); otherwise the bar asks.
      const inEditor = !!frameRef.current && document.activeElement === frameRef.current;
      if (statusRef.current === "saved" && !inEditor) reopen();
      else setConflict(now.version);
    })();
    return () => { cancelled = true; };
  }, [contentKey, poll, live, loaded, api, path, reopen]);

  useEffect(() => { if (ready) post({ type: "theme", theme: dark ? "dark" : "light" }); }, [dark, ready, post]);
  useEffect(() => { if (ready) post({ type: "locale", lang }); }, [lang, ready, post]);

  // What is unsaved goes into the file first: a PDF or a print is made from the file.
  const flushNow = (ms = 8000) => new Promise<boolean>((resolve) => {
    if (!loadedRef.current || !editable) return resolve(true);
    const id = `f${++seq.current}`;
    const timer = window.setTimeout(() => { flushes.current.delete(id); resolve(false); }, ms);
    flushes.current.set(id, (ok) => { window.clearTimeout(timer); resolve(ok); });
    post({ type: "flush", id });
  });

  const savePdf = async () => {
    setMenu(false);
    if (!api) return;
    await flushNow();
    try {
      const href = await api.pdf(path);
      const a = document.createElement("a");
      a.href = href;
      a.download = `${name.replace(/\.[^.]+$/, "")}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(href), 10_000);
    } catch { /* the toast comes from the request */ }
  };

  // Printed as the PDF the file makes (the canvas would print only what is on screen): the browser's print
  // dialog over a hidden frame holding it; where a browser cannot print a framed PDF, it is saved instead.
  const printPdf = async () => {
    setMenu(false);
    if (!api) return;
    await flushNow();
    let href: string;
    try {
      href = await api.pdf(path);
    } catch { return; /* the toast comes from the request */ }
    const frame = document.createElement("iframe");
    frame.style.cssText = "position:fixed;inset-inline-end:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
    frame.src = href;
    frame.onload = () => {
      try {
        frame.contentWindow?.focus();
        frame.contentWindow?.print();
      } catch {
        const a = document.createElement("a");
        a.href = href;
        a.download = `${name.replace(/\.[^.]+$/, "")}.pdf`;
        a.click();
      }
    };
    document.body.appendChild(frame);
    setTimeout(() => { frame.remove(); URL.revokeObjectURL(href); }, 120_000);
  };
  const printRef = useRef(printPdf);
  printRef.current = printPdf;

  if (!origin) return null;
  if (failed && fallback) return <>{fallback}</>;
  const crumbs = path.split("/").slice(0, -1);
  const notices = opened?.notices ?? [];

  // In the canvas the file's header row is the canvas's: these go into it. Elsewhere (a share) the
  // view brings its own row.
  const modifiedAt = savedAt ?? opened?.modified;
  const modified = modifiedAt ? modifiedLabel(modifiedAt) : "";
  const startItems = modified ? <span className="shrink-0 text-muted-foreground">· {modified}</span> : null;
  const endItems = (
    <>
      {notices.length > 0 && (
        <div className="relative">
          <button onClick={() => setNoticesOpen((v) => !v)} title={t("sheetsKept")}
                  className="cursor-pointer rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground">
            ⓘ {notices.length}
          </button>
          {noticesOpen && (
            <div className="absolute end-0 top-8 z-30 w-72 rounded-xl border border-border bg-card p-3 text-xs shadow-lg">
              <div className="mb-1.5 font-medium">{t("sheetsKept")}</div>
              <ul className="space-y-1 text-muted-foreground">
                {notices.map((n, i) => <li key={i} dir="auto">{n.message}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
      <span className={cn("shrink-0 rounded-md px-2 py-0.5 text-xs", status === "error" ? "bg-red-500/10 text-red-600" : "bg-secondary text-muted-foreground")}
            data-testid="sheets-status">
        {!editable ? t("sheetsViewOnly") : status === "saving" ? t("sheetsSaving") : status === "dirty" ? t("sheetsUnsaved") : status === "error" ? t("sheetsSaveFailed") : t("sheetsSaved")}
      </span>
      <div className="relative">
        <button onClick={() => setMenu((v) => !v)} aria-haspopup="menu" aria-expanded={menu}
                className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-2 py-1 text-xs font-medium hover:bg-secondary">
          <SheetGlyph className="size-3.5" />
          {t("sheetsOpen")}
          <span aria-hidden="true" className="text-muted-foreground">▾</span>
        </button>
        {menu && (
          <div role="menu" className="absolute end-0 top-9 z-30 w-56 rounded-xl border border-border bg-card p-1 text-xs shadow-lg">
            {onDownload && (
              <button role="menuitem" onClick={() => { setMenu(false); onDownload(); }}
                      className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-start hover:bg-secondary">
                <SheetGlyph className="size-4" />{t("sheetsDownloadXlsx")}
              </button>
            )}
            {api && (
              <button role="menuitem" onClick={() => void savePdf()}
                      className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-start hover:bg-secondary">
                <span className="flex size-4 items-center justify-center rounded bg-red-600 text-[8px] font-bold text-white">PDF</span>{t("sheetsSavePdf")}
              </button>
            )}
            {api && (
              <button role="menuitem" onClick={() => void printPdf()} data-testid="sheets-print"
                      className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-start hover:bg-secondary">
                <svg viewBox="0 0 16 16" className="size-4 text-muted-foreground" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
                  <path d="M4.5 6V2.5h7V6M4.5 11.5h-2v-5h11v5h-2M4.5 9.5h7v4h-7z" strokeLinejoin="round" />
                </svg>
                <span className="flex-1">{t("sheetsPrint")}</span>
                <span className="text-muted-foreground" dir="ltr">Ctrl+P</span>
              </button>
            )}
          </div>
        )}
      </div>
    </>
  );
  const inCanvas = !!slots.end;

  return (
    <div className="flex h-full w-full flex-col" data-testid="sheets-editor" data-path={path}>
      {inCanvas ? (
        <>
          {slots.start && startItems && createPortal(startItems, slots.start)}
          {createPortal(endItems, slots.end!)}
        </>
      ) : (
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3 text-xs">
          <SheetGlyph className="size-4 shrink-0" />
          <div className="flex min-w-0 items-center gap-1 text-muted-foreground" dir="auto">
            <span className="shrink-0">{t("sheetsWorkspace")}</span>
            {crumbs.map((c, i) => <span key={i} className="shrink-0">/ {c}</span>)}
            <span className="shrink-0">/</span>
            <span className="truncate font-medium text-foreground" title={name}>{name}</span>
          </div>
          {startItems && <span className="hidden sm:inline">{startItems}</span>}
          <div className="flex-1" />
          {endItems}
        </div>
      )}
      {live && editable && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border bg-[#EF8733]/10 px-3 py-1.5 text-xs" role="status" data-testid="sheets-live">
          <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-[#EF8733]" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate" dir="auto">{t("sheetsAgentEditing")}{intent ? <span className="text-muted-foreground"> · {intent}</span> : null}</span>
        </div>
      )}
      {conflict !== null && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-amber-500/10 px-3 py-2 text-xs" role="alert">
          <span className="flex-1">{t("sheetsChangedElsewhere")}</span>
          <button onClick={loadLatest} className="cursor-pointer rounded-md bg-foreground px-2.5 py-1 font-medium text-background hover:opacity-90">{t("sheetsLoadLatest")}</button>
          <button onClick={keepMine} className="cursor-pointer rounded-md border border-border px-2.5 py-1 font-medium hover:bg-secondary">{t("sheetsKeepMine")}</button>
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        {!loaded && <div className="absolute inset-x-0 top-0 z-10"><LoadingBar /></div>}
        {failed && <div className="absolute inset-0 z-10 flex items-center justify-center p-6 text-sm text-muted-foreground">{t("sheetsCouldNotOpen")}</div>}
        <iframe ref={frameRef} src={src} title={name} className="h-full w-full border-0"
                allow="clipboard-read; clipboard-write" />
      </div>
    </div>
  );
}

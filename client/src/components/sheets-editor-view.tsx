import { useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDarkMode } from "../hooks/use-dark-mode";
import type { OfficeEditorApi, OfficeOpen, SheetsOpened } from "../hooks/use-files";
import { getLang, t, useLang } from "../lib/i18n";
import { CanvasHeaderSlot } from "./canvas-header-slot";
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
//                    written {doc, id, ok}   flush {id}   save
//   editor → Cycls   ready {protocol, features}   loaded {doc}   error {doc, message}
//                    dirty {doc, dirty}   saved {doc, id, snapshot}   flushed {id, ok}
// A save writes the editor's workbook back into the .xlsx through the service (only what differs
// changes) and keeps the replaced version; a file changed elsewhere since it was opened asks first.

/** Asks once per file whether this workspace opens it in Cycls Sheets; otherwise shows `preview`. */
export function SheetsOrPreview({ path, name, api, preview, onDownload }: {
  path: string;
  name: string;
  api: OfficeEditorApi;
  preview: ReactNode;
  onDownload?: () => void;
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
    ? <SheetsEditorView url={open.url} path={path} name={name} api={api} onDownload={onDownload} fallback={preview} />
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

export function SheetsEditorView({ url, path, name, api, onDownload, fallback }: {
  url: string;
  path: string;
  name: string;
  api?: OfficeEditorApi;
  onDownload?: () => void;
  fallback?: ReactNode;
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
  const editable = !!api;
  const doc = useRef("");
  const version = useRef("");       // what the next save names as its base
  const forceNext = useRef(false);  // "Keep mine": the next save writes over the newer file
  const saving = useRef<Promise<void> | null>(null);
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
      if (msg.type === "ready") setReady(true);
      else if (msg.type === "loaded" && msg.doc === doc.current) setLoaded(true);
      else if (msg.type === "error" && msg.doc === doc.current) setFailed(true);
      else if (msg.type === "dirty" && msg.doc === doc.current) {
        const d = (msg as { dirty?: boolean }).dirty;
        setStatus((now) => (now === "saving" ? now : d ? "dirty" : "saved"));
      } else if (msg.type === "saved" && msg.doc === doc.current) {
        const { id, snapshot } = msg as { id?: string; snapshot?: unknown };
        if (typeof id === "string" && snapshot) void save(id, snapshot);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [origin]);

  // Send the workbook once both sides are ready (and again if the file's version changes).
  useEffect(() => {
    if (!ready || !opened) return;
    doc.current = `${path}@${opened.version}`;
    version.current = opened.version;
    setLoaded(false);
    setStatus("saved");
    setConflict(null);
    post({ type: "load", doc: doc.current, name, snapshot: opened.snapshot, activeSheet: opened.activeSheet, readonly: !editable });
  }, [ready, opened, path, name, post, editable]);

  // One save at a time; the editor sends the next once this one is answered.
  const save = async (id: string, snapshot: unknown) => {
    if (!api) return;
    const forDoc = doc.current;
    const run = (async () => {
      setStatus("saving");
      try {
        const force = forceNext.current;
        const r = await api.sheetsSave(path, version.current, snapshot, force);
        if (forDoc !== doc.current) return;
        if ("conflict" in r) {
          setConflict(r.conflict);
          setStatus("error");
          post({ type: "written", doc: forDoc, id, ok: false });
          return;
        }
        forceNext.current = false;
        version.current = r.version;
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
    if (!api) return;
    setConflict(null);
    setOpened(null);
    api.sheetsOpen(path).then(setOpened).catch(() => setFailed(true));
  };
  const keepMine = () => {
    forceNext.current = true;
    setConflict(null);
    post({ type: "save" });
  };

  useEffect(() => { if (ready) post({ type: "theme", theme: dark ? "dark" : "light" }); }, [dark, ready, post]);
  useEffect(() => { if (ready) post({ type: "locale", lang }); }, [lang, ready, post]);

  const savePdf = async () => {
    setMenu(false);
    if (!api) return;
    try {
      const href = await api.pdf(path);
      const a = document.createElement("a");
      a.href = href;
      a.download = `${name.replace(/\.[^.]+$/, "")}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(href), 10_000);
    } catch { /* the toast comes from the request */ }
  };

  if (!origin) return null;
  if (failed && fallback) return <>{fallback}</>;
  const crumbs = path.split("/").slice(0, -1);
  const notices = opened?.notices ?? [];

  // In the canvas the file's header row is the canvas's: these go into it. Elsewhere (a share) the
  // view brings its own row.
  const modified = opened?.modified ? modifiedLabel(opened.modified) : "";
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

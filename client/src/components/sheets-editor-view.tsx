import { useEffect, useRef, useState, type ReactNode } from "react";
import { useDarkMode } from "../hooks/use-dark-mode";
import type { OfficeEditorApi, OfficeOpen } from "../hooks/use-files";
import { useLang } from "../lib/i18n";
import { LoadingBar } from "./loading-bar";

// Cycls Sheets in the canvas: the editor, served by the cycls-office service, in an iframe.
//
// Protocol 1 (postMessage, JSON). Cycls → editor {target: "cycls-sheets", type, …}, posted to the
// editor's exact origin only; editor → Cycls {source: "cycls-sheets", type, …}, accepted only from
// that origin and that frame. Phase 0 carries `ready`, `theme` and `locale`; loading the file,
// saving and the agent's edits join it with the Excel reader.

/** Asks once per file whether this workspace opens it in Cycls Sheets; otherwise shows `preview`. */
export function SheetsOrPreview({ path, name, api, preview }: {
  path: string;
  name: string;
  api: OfficeEditorApi;
  preview: ReactNode;
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
  return open.editor ? <SheetsEditorView url={open.url} path={path} name={name} /> : <>{preview}</>;
}

export function SheetsEditorView({ url, path, name }: { url: string; path: string; name: string }) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const dark = useDarkMode();
  const lang = useLang();
  const [ready, setReady] = useState(false);
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

  const post = (msg: Record<string, unknown>) => {
    if (origin) frameRef.current?.contentWindow?.postMessage({ target: "cycls-sheets", ...msg }, origin);
  };

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (!origin || e.origin !== origin || e.source !== frameRef.current?.contentWindow) return;
      const msg = e.data as { source?: string; type?: string };
      if (msg?.source !== "cycls-sheets") return;
      if (msg.type === "ready") setReady(true);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [origin]);

  useEffect(() => { if (ready) post({ type: "theme", theme: dark ? "dark" : "light" }); }, [dark, ready]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready) post({ type: "locale", lang }); }, [lang, ready]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!origin) return null;
  return (
    <div className="relative h-full w-full" data-testid="sheets-editor" data-path={path}>
      {!ready && <div className="absolute inset-x-0 top-0 z-10"><LoadingBar /></div>}
      <iframe ref={frameRef} src={src} title={name} className="h-full w-full border-0"
              allow="clipboard-read; clipboard-write" />
    </div>
  );
}

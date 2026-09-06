import { useEffect, useRef, useState } from "react";
import { t } from "../lib/i18n";
import { tintTile, tintLabel, ext } from "./canvas-utils";

// Match the editor to the app's theme. Collabora falls back to its blue light
// theme unless told otherwise; it honors `ui_defaults=UITheme=(light|dark)` on
// the load form, so we mirror the app's current mode. (The `.dark` class lives
// on <body>.) css_variables would recolor further but the container ignores it
// unless integrator theming is enabled there, so UITheme is the reliable lever.
function uiDefaults(): string {
  const dark = typeof document !== "undefined" && document.body.classList.contains("dark");
  return `UITheme=${dark ? "dark" : "light"}`;
}

// Embeds the Collabora Online editor for an Office file. The server mints a
// per-file WOPI token and hands back the editor URL; we load Collabora into an
// iframe via the documented form-POST (token in the body, not the URL, so it
// doesn't leak into history/referrer). Collabora then calls the agent's WOPI
// host to fetch and save the actual .docx/.xlsx/.pptx.
//
// Once loaded we speak Collabora's postMessage API: the host must send
// `Host_PostmessageReady` for Collabora to start posting back, and Collabora
// replies with `App_LoadingStatus: Document_Loaded` when the document is on
// screen — we hold our own "opening…" overlay until then so there's no flash of
// empty editor. (The server enables this by returning `PostMessageOrigin` in
// CheckFileInfo.)
export function CollaboraEditor({ file, getEditor, onDownload }: {
  file: { path: string; name: string };
  getEditor: (path: string) => Promise<{ editor_url: string; access_token: string; access_token_ttl: number }>;
  onDownload?: () => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [cfg, setCfg] = useState<{ editor_url: string; access_token: string; access_token_ttl: number } | null>(null);
  const [error, setError] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setCfg(null);
    setError(false);
    setLoaded(false);
    getEditor(file.path)
      .then((c) => { if (!cancelled) setCfg(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [file.path, getEditor]);

  // Submit once the config lands — POST navigates the named iframe to the editor.
  useEffect(() => { if (cfg) formRef.current?.submit(); }, [cfg]);

  // Talk to Collabora once it's embedded: listen for its status, and don't let
  // the overlay outlive a dropped handshake (fallback reveals the editor anyway).
  useEffect(() => {
    if (!cfg) return;
    let origin = "";
    try { origin = new URL(cfg.editor_url).origin; } catch { /* keep "" → accept none */ }
    const onMessage = (e: MessageEvent) => {
      if (origin && e.origin !== origin) return;
      let msg: { MessageId?: string; Values?: { Status?: string } } | null = null;
      try { msg = typeof e.data === "string" ? JSON.parse(e.data) : e.data; } catch { return; }
      if (msg?.MessageId === "App_LoadingStatus" && msg.Values?.Status === "Document_Loaded") setLoaded(true);
    };
    window.addEventListener("message", onMessage);
    const fallback = window.setTimeout(() => setLoaded(true), 8000);
    return () => { window.removeEventListener("message", onMessage); window.clearTimeout(fallback); };
  }, [cfg]);

  // Kick off the postMessage handshake after the editor page loads in the frame.
  const onFrameLoad = () => {
    if (!cfg) return;
    try {
      frameRef.current?.contentWindow?.postMessage(
        JSON.stringify({ MessageId: "Host_PostmessageReady" }),
        new URL(cfg.editor_url).origin,
      );
    } catch { /* frame not ready / cross-origin timing — the fallback covers UX */ }
  };

  if (error) {
    // Collabora unreachable / token refused → offer the file rather than a dead frame.
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
        <div className="flex size-16 items-center justify-center rounded-2xl bg-secondary text-xs font-bold text-muted-foreground" style={tintTile(file.name)}>
          <span style={tintLabel(file.name)}>{(ext(file.name) || "file").slice(0, 4).toUpperCase()}</span>
        </div>
        <p className="text-sm font-medium text-foreground">{file.name}</p>
        <p className="text-xs text-muted-foreground">{t("editorUnavailable")}</p>
        {onDownload && (
          <button onClick={onDownload} className="mt-1 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 transition-opacity cursor-pointer">
            {t("download")}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      {(!cfg || !loaded) && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background text-sm text-muted-foreground">
          {t("openingEditor")}
        </div>
      )}
      {/* Named target for the form POST below. No sandbox: Collabora is our own
          first-party service and needs same-origin + scripts to run. */}
      <iframe
        ref={frameRef}
        name="cycls-collabora"
        title={file.name}
        onLoad={onFrameLoad}
        className="h-full w-full border-0"
        allow="clipboard-read; clipboard-write; fullscreen"
      />
      {cfg && (
        <form ref={formRef} action={cfg.editor_url} method="post" target="cycls-collabora" className="hidden">
          <input type="hidden" name="access_token" value={cfg.access_token} />
          <input type="hidden" name="access_token_ttl" value={String(cfg.access_token_ttl)} />
          {/* Match the editor's theme to the app (dark → dark, not Collabora blue). */}
          <input type="hidden" name="ui_defaults" value={uiDefaults()} />
        </form>
      )}
    </div>
  );
}

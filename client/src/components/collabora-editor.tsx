import { useEffect, useRef, useState } from "react";
import { t } from "../lib/i18n";
import { tintTile, tintLabel, ext } from "./canvas-utils";

// Embeds the Collabora Online editor for an Office file. The server mints a
// per-file WOPI token and hands back the editor URL; we load Collabora into an
// iframe via the documented form-POST (token in the body, not the URL, so it
// doesn't leak into history/referrer). Collabora then calls the agent's WOPI
// host to fetch and save the actual .docx/.xlsx/.pptx.
export function CollaboraEditor({ file, getEditor, onDownload }: {
  file: { path: string; name: string };
  getEditor: (path: string) => Promise<{ editor_url: string; access_token: string; access_token_ttl: number }>;
  onDownload?: () => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [cfg, setCfg] = useState<{ editor_url: string; access_token: string; access_token_ttl: number } | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setCfg(null);
    setError(false);
    getEditor(file.path)
      .then((c) => { if (!cancelled) setCfg(c); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [file.path, getEditor]);

  // Submit once the config lands — POST navigates the named iframe to the editor.
  useEffect(() => { if (cfg) formRef.current?.submit(); }, [cfg]);

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
      {!cfg && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          {t("openingEditor")}
        </div>
      )}
      {/* Named target for the form POST below. No sandbox: Collabora is our own
          first-party service and needs same-origin + scripts to run. */}
      <iframe
        name="cycls-collabora"
        title={file.name}
        className="h-full w-full border-0"
        allow="clipboard-read; clipboard-write; fullscreen"
      />
      {cfg && (
        <form ref={formRef} action={cfg.editor_url} method="post" target="cycls-collabora" className="hidden">
          <input type="hidden" name="access_token" value={cfg.access_token} />
          <input type="hidden" name="access_token_ttl" value={String(cfg.access_token_ttl)} />
        </form>
      )}
    </div>
  );
}

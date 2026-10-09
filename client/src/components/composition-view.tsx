// A Video composition on the canvas: the page the video service built of it (?as=player) — its
// bundle with the pinned player inlined, fonts and images inside it — played in a sandboxed srcDoc
// iframe allowed scripts and nothing else, under a CSP that lets it load nothing. The player is
// never mounted in this React tree, and the page never gets this origin. When the video has been
// rendered, a switch shows the MP4; with no preview (the service away, errors to fix) the MP4
// shows if there is one, else a card saying why, with the download.
import { useEffect, useMemo, useState } from "react";
import { t } from "../lib/i18n";
import { cn } from "../lib/utils";

export interface CompositionManifest {
  html: string | null;
  reason: string | null;
  version?: string;
  render?: { path: string; exists: boolean };
}

export function parseManifest(data: string | null): CompositionManifest | null {
  if (!data) return null;
  try {
    const m = JSON.parse(data);
    return m && typeof m === "object" && ("html" in m || "reason" in m) ? (m as CompositionManifest) : null;
  } catch {
    return null;
  }
}

// The page already carries the service's CSP; this one is ours, first in <head>, so the page is held
// to it whatever it says (two policies: both apply).
export const COMPOSITION_CSP =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; " +
  "font-src data:; media-src data: blob:; frame-src 'self' about: blob: data:; connect-src 'none'";

export function withCsp(html: string): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${COMPOSITION_CSP}">`;
  const head = html.match(/<head\b[^>]*>/i);
  if (head && head.index !== undefined) {
    const at = head.index + head[0].length;
    return html.slice(0, at) + meta + html.slice(at);
  }
  return meta + html;
}

export default function CompositionView({ data, name, openFile, onDownload }: {
  data: string;
  name: string;
  openFile?: (path: string, silent?: boolean) => Promise<string>;
  onDownload?: () => void;
}) {
  const m = useMemo(() => parseManifest(data), [data]);
  const rendered = !!m?.render?.exists && !!openFile;
  const [mode, setMode] = useState<"preview" | "video">(m?.html ? "preview" : "video");
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  useEffect(() => { setMode(m?.html ? "preview" : "video"); }, [m?.html]);

  const wantVideo = rendered && (mode === "video" || !m?.html);
  useEffect(() => {
    if (!wantVideo || !openFile || !m?.render) return;
    let url: string | null = null;
    let cancelled = false;
    openFile(m.render.path, true).then((u) => { url = u; if (!cancelled) setVideoUrl(u); }).catch(() => {});
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); setVideoUrl(null); };
  }, [wantVideo, openFile, m?.render?.path, m?.version]);

  const page = useMemo(() => (m?.html ? withCsp(m.html) : null), [m?.html]);

  if (!m) return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Couldn't load this file.</div>;

  return (
    <div className="relative flex h-full w-full flex-col bg-black">
      {page && rendered && (
        <div className="absolute end-3 top-3 z-10 flex rounded-full border border-white/15 bg-black/60 p-0.5 text-xs backdrop-blur"
             role="tablist">
          {(["preview", "video"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={mode === k} onClick={() => setMode(k)}
                    className={cn("rounded-full px-3 py-1 transition-colors cursor-pointer",
                                  mode === k ? "bg-white text-black" : "text-white/80 hover:text-white")}>
              {k === "preview" ? t("videoPreview") : t("videoRendered")}
            </button>
          ))}
        </div>
      )}
      {page && mode === "preview" ? (
        <iframe sandbox="allow-scripts" srcDoc={page} title={name} className="h-full w-full flex-1 border-0" />
      ) : wantVideo ? (
        <div className="flex flex-1 items-center justify-center">
          {videoUrl && <video src={videoUrl} controls className="max-h-full max-w-full" />}
        </div>
      ) : (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-background p-6 text-center">
          <div className="text-sm font-medium text-foreground">{t("videoNoPreview")}</div>
          <div className="max-w-sm text-xs text-muted-foreground">{m.reason || t("videoNotRendered")}</div>
          {onDownload && (
            <button onClick={onDownload}
                    className="rounded-md bg-secondary px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-secondary/80 cursor-pointer">
              {t("download")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

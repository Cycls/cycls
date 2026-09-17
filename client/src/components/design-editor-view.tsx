import { useEffect, useRef, useState } from "react";

// Renders a `.fig` on the canvas as the embedded OpenPencil editor — an iframe
// on its OWN origin (the deployed editor), so the human edits the same design
// the agent renders headlessly. The design file is the shared source of truth:
// loaded into the editor here, and edits written back to the workspace file.
//
// postMessage protocol (matches the editor's cycls embed-bridge):
//   host   → editor : { target:"cycls-editor", type:"load", name, fig:<base64> }  |  { type:"save" }
//   editor → host   : { source:"cycls-editor", type:"ready"|"loaded"|"saved"|"error", fig?, message? }

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

export function DesignEditorView({ url, path, name, editorUrl, writeFile }: {
  url: string;        // blob URL of the .fig bytes (already fetched, authed)
  path: string;       // workspace path to write edits back to
  name: string;
  editorUrl: string;  // base URL of the deployed editor (config.design_editor_url)
  writeFile: (path: string, data: BlobPart, silent?: boolean) => Promise<void>;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "saved" | "error">("loading");
  const base = editorUrl.replace(/\/+$/, "");
  const src = `${base}/?embed=cycls`;
  const origin = (() => { try { return new URL(editorUrl).origin; } catch { return "*"; } })();

  useEffect(() => {
    let disposed = false;
    const post = (msg: Record<string, unknown>) =>
      frameRef.current?.contentWindow?.postMessage({ target: "cycls-editor", ...msg }, origin);

    const onMessage = async (e: MessageEvent) => {
      if (origin !== "*" && e.origin !== origin) return;
      const m = e.data as { source?: string; type?: string; fig?: string };
      if (!m || m.source !== "cycls-editor") return;
      if (m.type === "ready") {
        try {
          const buf = await (await fetch(url)).arrayBuffer();
          if (!disposed) post({ type: "load", name, fig: toBase64(new Uint8Array(buf)) });
        } catch {
          if (!disposed) setStatus("error");
        }
      } else if (m.type === "loaded") {
        if (!disposed) setStatus("ready");
      } else if (m.type === "saved" && typeof m.fig === "string") {
        try {
          // Cast: TS 5.7 types Uint8Array as Uint8Array<ArrayBufferLike>, which
          // doesn't structurally match BlobPart's ArrayBufferView<ArrayBuffer>.
          await writeFile(path, fromBase64(m.fig) as unknown as BlobPart);
          if (!disposed) {
            setStatus("saved");
            window.setTimeout(() => { if (!disposed) setStatus("ready"); }, 1500);
          }
        } catch {
          if (!disposed) setStatus("error");
        }
      } else if (m.type === "error") {
        if (!disposed) setStatus("error");
      }
    };
    // The agent edits an open design live: chat.tsx dispatches this when its
    // Design tool fires a `design_command`; we relay the script to our editor.
    const onCommand = (e: Event) => {
      const d = (e as CustomEvent).detail as { path?: string; script?: string };
      if (!d || d.path !== path || typeof d.script !== "string") return;
      post({ type: "command", script: d.script });
    };

    window.addEventListener("message", onMessage);
    window.addEventListener("cycls:design-command", onCommand as EventListener);
    return () => {
      disposed = true;
      window.removeEventListener("message", onMessage);
      window.removeEventListener("cycls:design-command", onCommand as EventListener);
    };
  }, [url, path, name, origin, writeFile]);

  return (
    <div className="relative h-full w-full">
      {/* Own-origin editor iframe (not sandboxed): the app needs its full
          capabilities — CanvasKit, workers, storage — on its real origin. */}
      <iframe ref={frameRef} src={src} title={name} className="h-full w-full border-0" />
      {status !== "ready" && (
        <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow backdrop-blur">
          {status === "error" ? "Editor error" : status === "saved" ? "Saved ✓" : "Loading editor…"}
        </div>
      )}
    </div>
  );
}

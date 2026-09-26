import { useEffect, useRef, useState } from "react";

// Renders a `.fig` on the canvas as the embedded OpenPencil editor — an iframe
// on its OWN origin (the deployed editor), so the human edits the same design
// the agent renders headlessly. The design file is the shared source of truth:
// loaded into the editor here, and edits written back to the workspace file.
//
// postMessage protocol (matches the editor's cycls embed-bridge):
//   host   → editor : { target:"cycls-editor", type:"load", name, fig:<base64> }  |  { type:"save" }
//   editor → host   : { source:"cycls-editor", type:"ready"|"loaded"|"saved"|"error"|"applied"|"commandError", fig?, message? }
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

export function DesignEditorView({ url, path, name, editorUrl, writeFile, reload }: {
  url: string;        // blob URL of the .fig bytes (already fetched, authed)
  path: string;       // workspace path to write edits back to
  name: string;
  editorUrl: string;  // base URL of the deployed editor (config.design_editor_url)
  writeFile: (path: string, data: BlobPart, silent?: boolean) => Promise<void>;
  reload?: () => Promise<string>;   // a FRESH blob URL of the saved .fig (re-open after a failed replay)
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [frameKey, setFrameKey] = useState(0);        // bump → the editor iframe remounts
  const sourceRef = useRef<string | null>(null);      // what the next `ready` loads, if not `url`
  const [status, setStatus] = useState<"loading" | "ready" | "saved" | "error" | "saveerror">("loading");
  const base = editorUrl.replace(/\/+$/, "");
  // Sync the editor's light/dark to the app's current mode (set at load; re-open
  // to re-sync). Cycls toggles the `.dark` class on document.body (see lib/utils
  // applyTheme + use-dark-mode) — NOT on <html> — so read it there.
  const theme = typeof document !== "undefined" && document.body.classList.contains("dark") ? "dark" : "light";
  const src = `${base}/?embed=cycls&theme=${theme}`;
  const origin = (() => { try { return new URL(editorUrl).origin; } catch { return "*"; } })();

  useEffect(() => {
    let disposed = false;
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
    const post = (msg: Record<string, unknown>) =>
      frameRef.current?.contentWindow?.postMessage({ target: "cycls-editor", ...msg }, origin);

    const onMessage = async (e: MessageEvent) => {
      if (origin !== "*" && e.origin !== origin) return;
      const m = e.data as { source?: string; type?: string; fig?: string };
      if (!m || m.source !== "cycls-editor") return;
      if (m.type === "ready") {
        const source = sourceRef.current ?? url;
        try {
          const buf = await (await fetch(source)).arrayBuffer();
          if (!disposed) post({ type: "load", name, fig: toBase64(new Uint8Array(buf)) });
        } catch {
          if (!disposed) setStatus("error");
        } finally {
          if (sourceRef.current) { URL.revokeObjectURL(sourceRef.current); sourceRef.current = null; }
        }
      } else if (m.type === "loaded") {
        loaded = true;
        if (!disposed) setStatus("ready");
      } else if (m.type === "saved" && typeof m.fig === "string") {
        try {
          // Cast: TS 5.7 types Uint8Array as Uint8Array<ArrayBufferLike>, which
          // doesn't structurally match BlobPart's ArrayBufferView<ArrayBuffer>.
          await writeFile(path, fromBase64(m.fig) as unknown as BlobPart);
          flash("saved");
        } catch {
          flash("saveerror");
        }
      } else if (m.type === "commandError") {
        // The live replay of an agent edit failed; the saved file already holds the
        // edit. Re-open the editor on it (a fresh fetch — `url` may predate the edit).
        try { sourceRef.current = reload ? await reload() : null; } catch { sourceRef.current = null; }
        if (disposed) return;
        loaded = false;
        setStatus("loading");
        setFrameKey((k) => k + 1);
      } else if (m.type === "error") {
        // Pre-load: the editor genuinely failed to open → sticky "Editor error".
        // Post-load: a background blip (e.g. an auto-save) → transient, then the
        // live editor stays up.
        if (!disposed) loaded ? flash("saveerror") : setStatus("error");
      }
    };
    // The agent edits an open design live: chat.tsx dispatches this when its
    // Design tool fires a `design_command`; we relay the script to our editor.
    const onCommand = (e: Event) => {
      const d = (e as CustomEvent).detail as { path?: string; script?: string; intent?: string };
      if (!d || d.path !== path || typeof d.script !== "string") return;
      post({ type: "command", script: d.script, intent: d.intent });
    };

    window.addEventListener("message", onMessage);
    window.addEventListener("cycls:design-command", onCommand as EventListener);
    return () => {
      disposed = true;
      window.removeEventListener("message", onMessage);
      window.removeEventListener("cycls:design-command", onCommand as EventListener);
    };
  }, [url, path, name, origin, writeFile, reload]);

  return (
    <div className="relative h-full w-full">
      {/* Own-origin editor iframe (not sandboxed): the app needs its full
          capabilities — CanvasKit, workers, storage — on its real origin. */}
      <iframe key={frameKey} ref={frameRef} src={src} title={name} className="h-full w-full border-0" />
      {status !== "ready" && (
        <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow backdrop-blur">
          {status === "error"
            ? "Editor error"
            : status === "saveerror"
              ? "Couldn’t save — will retry"
              : status === "saved"
                ? "Saved ✓"
                : "Loading editor…"}
        </div>
      )}
    </div>
  );
}

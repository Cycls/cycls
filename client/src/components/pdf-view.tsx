import { useEffect, useRef, useState } from "react";
import { LoadingBar } from "./loading-bar";

// pdf.js renderer for browsers without a native inline PDF viewer (every
// mobile browser: iOS Safari shows only page 1 in an iframe, Android Chrome
// downloads instead). Desktop keeps the native <iframe> viewer — see
// CanvasDoc. pdfjs-dist is lazy-imported so it stays out of the main bundle
// (same tactic as the xlsx worker).
export function PdfView({ url }: { url: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let doc: { destroy: () => void } | null = null;
    setLoading(true);
    setError(false);
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        if (!pdfjs.GlobalWorkerOptions.workerPort) {
          pdfjs.GlobalWorkerOptions.workerPort = new Worker(
            new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url),
            { type: "module" },
          );
        }
        const loaded = await pdfjs.getDocument(url).promise;
        if (cancelled) { loaded.destroy(); return; }
        doc = loaded;
        const container = containerRef.current;
        if (!container) return;
        container.textContent = "";
        const width = container.clientWidth - 16; // p-2 padding
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        for (let i = 1; i <= loaded.numPages; i++) {
          const page = await loaded.getPage(i);
          if (cancelled) return;
          const scale = width / page.getViewport({ scale: 1 }).width;
          const viewport = page.getViewport({ scale });
          const canvas = document.createElement("canvas");
          canvas.width = Math.floor(viewport.width * dpr);
          canvas.height = Math.floor(viewport.height * dpr);
          canvas.style.width = `${Math.floor(viewport.width)}px`;
          canvas.style.height = `${Math.floor(viewport.height)}px`;
          canvas.className = "mx-auto mb-2 block bg-white shadow-sm";
          container.appendChild(canvas);
          await page.render({
            canvasContext: canvas.getContext("2d")!,
            viewport,
            transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
          }).promise;
          if (i === 1) setLoading(false); // first page visible — drop the bar
        }
        setLoading(false);
      } catch {
        if (!cancelled) { setError(true); setLoading(false); }
      }
    })();
    return () => { cancelled = true; doc?.destroy(); };
  }, [url]);

  if (error) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Couldn't load this file.</div>;
  }
  return (
    <div className="h-full overflow-y-auto bg-muted/30 p-2">
      {loading && <LoadingBar />}
      <div ref={containerRef} />
    </div>
  );
}

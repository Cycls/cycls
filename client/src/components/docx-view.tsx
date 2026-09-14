import { useEffect, useRef, useState } from "react";
import { LoadingBar } from "./loading-bar";

// Renders a .docx natively as formatted HTML via docx-preview (pages, fonts,
// tables, inline images, RTL/bidi from the document's own settings) — so Word
// files read like the document rather than a flat PDF. `url` is an authed blob
// URL (from openFile), so this works for owned files and token-scoped shares
// alike. docx-preview is dynamically imported so it never weighs on the main
// bundle. A parse failure shows the same "couldn't render" note the PDF path
// falls back to; the download/share controls stay in the canvas chrome.
export function DocxView({ url }: { url: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "ok" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    (async () => {
      try {
        const buffer = await (await fetch(url)).arrayBuffer();
        const { renderAsync } = await import("docx-preview");
        if (cancelled || !ref.current) return;
        ref.current.innerHTML = "";
        await renderAsync(buffer, ref.current, undefined, {
          className: "docx",
          inWrapper: true,
          breakPages: true,
          ignoreLastRenderedPageBreak: true,
          experimental: true,   // better tab-stops / table layout fidelity
        });
        if (!cancelled) setState("ok");
      } catch {
        if (!cancelled) setState("error");
      }
    })();
    return () => { cancelled = true; };
  }, [url]);

  return (
    <div className="h-full overflow-auto bg-neutral-200 dark:bg-neutral-800">
      {state === "loading" && <LoadingBar />}
      {state === "error" && (
        <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
          Couldn't render this document.
        </div>
      )}
      {/* docx-preview writes its own white "page" wrapper + styles into here. */}
      <div ref={ref} className={state === "ok" ? "" : "hidden"} />
    </div>
  );
}

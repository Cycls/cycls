import { useMemo, useState, useRef, useEffect } from "react";
import { PresentMode } from "./present-mode";
import { useSlideNav } from "../hooks/use-slide-nav";
import { track } from "../lib/analytics";
import { t } from "../lib/i18n";

interface SlideManifest { count: number; slides: string[] }

// Renders a presentation as a slide viewer — a big current slide plus a
// thumbnail rail — from the ?as=slides manifest (per-slide PNG data-URIs the
// office-render service produced). `data` is that JSON, fetched authed (works
// for owned files and token-scoped shares alike). Arrow keys / clicking a
// thumbnail move between slides; the images are pre-rendered by LibreOffice, so
// RTL decks come through already shaped. Present shows it full screen.
export function SlidesView({ data }: { data: string }) {
  const manifest = useMemo<SlideManifest | null>(() => {
    try { return JSON.parse(data); } catch { return null; }
  }, [data]);
  const slides = manifest?.slides ?? [];
  const n = slides.length;
  const { active, go, onKey } = useSlideNav(n);
  const [presenting, setPresenting] = useState(false);
  const railRef = useRef<HTMLDivElement>(null);

  // Keep the active thumbnail scrolled into view as we page through.
  useEffect(() => {
    railRef.current?.querySelector(`[data-slide="${active}"]`)
      ?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [active]);

  if (!manifest || n === 0) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Couldn't render this presentation.</div>;
  }

  return (
    <div className="flex h-full outline-none" tabIndex={0} onKeyDown={onKey}>
      {/* Main slide */}
      <div className="relative flex flex-1 items-center justify-center overflow-auto bg-neutral-200 p-4 dark:bg-neutral-800">
        <img
          src={slides[active]}
          alt={`Slide ${active + 1}`}
          className="max-h-full max-w-full object-contain shadow-lg"
        />
        <button
          onClick={() => { track("deck_presented", { slides: n, from: active === 0 ? "start" : "current", source: "office" }); setPresenting(true); }}
          className="absolute right-3 top-3 flex items-center gap-1.5 rounded-full bg-background/85 px-3 py-1 text-xs font-medium text-foreground shadow backdrop-blur hover:bg-background cursor-pointer"
        >
          <svg className="size-3" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
          {t("present")}
        </button>
        {n > 1 && (
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-background/85 px-3 py-1 text-xs text-muted-foreground shadow backdrop-blur">
            {active + 1} / {n}
          </div>
        )}
      </div>
      {/* Thumbnail rail — only when there's more than one slide */}
      {n > 1 && (
        <div ref={railRef} className="w-40 shrink-0 space-y-2 overflow-y-auto border-l border-border bg-background/60 p-2">
          {slides.map((src, i) => (
            <button
              key={i}
              data-slide={i}
              onClick={() => go(i)}
              className={`block w-full overflow-hidden rounded-md border transition-colors ${i === active ? "border-primary ring-1 ring-primary" : "border-border hover:border-muted-foreground"}`}
            >
              <img src={src} alt={`Slide ${i + 1}`} className="w-full" loading="lazy" />
              <span className="block px-1 py-0.5 text-left text-[10px] text-muted-foreground">{i + 1}</span>
            </button>
          ))}
        </div>
      )}
      {presenting && <PresentMode deck={{ slides }} start={active} onClose={(last) => { setPresenting(false); go(last); }} />}
    </div>
  );
}

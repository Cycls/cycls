import { useMemo, useState, useRef, useEffect } from "react";

interface SlideManifest { count: number; slides: string[] }

// Renders a presentation as a slide viewer — a big current slide plus a
// thumbnail rail — from the ?as=slides manifest (per-slide PNG data-URIs the
// office-render service produced). `data` is that JSON, fetched authed (works
// for owned files and token-scoped shares alike). Arrow keys / clicking a
// thumbnail move between slides; the images are pre-rendered by LibreOffice, so
// RTL decks come through already shaped.
export function SlidesView({ data }: { data: string }) {
  const manifest = useMemo<SlideManifest | null>(() => {
    try { return JSON.parse(data); } catch { return null; }
  }, [data]);
  const [active, setActive] = useState(0);
  const railRef = useRef<HTMLDivElement>(null);
  const slides = manifest?.slides ?? [];
  const n = slides.length;

  // Keep the active thumbnail scrolled into view as we page through.
  useEffect(() => {
    railRef.current?.querySelector(`[data-slide="${active}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [active]);

  if (!manifest || n === 0) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Couldn't render this presentation.</div>;
  }

  const go = (i: number) => setActive(Math.max(0, Math.min(n - 1, i)));
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === "PageDown") { go(active + 1); e.preventDefault(); }
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp" || e.key === "PageUp") { go(active - 1); e.preventDefault(); }
    else if (e.key === "Home") { go(0); e.preventDefault(); }
    else if (e.key === "End") { go(n - 1); e.preventDefault(); }
  };

  return (
    <div className="flex h-full outline-none" tabIndex={0} onKeyDown={onKey}>
      {/* Main slide */}
      <div className="relative flex flex-1 items-center justify-center overflow-auto bg-neutral-200 p-4 dark:bg-neutral-800">
        <img
          src={slides[active]}
          alt={`Slide ${active + 1}`}
          className="max-h-full max-w-full object-contain shadow-lg"
        />
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
    </div>
  );
}

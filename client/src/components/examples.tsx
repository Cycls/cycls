import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import { useFileContent, CanvasDoc } from "./canvas";
import { isHtml, isRenderable } from "./canvas-utils";
import { track } from "../lib/posthog";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";

// The examples gallery — curated public shares rendered as artifact cards on
// the empty-chat screen (docs/notes/examples-gallery.md). Cards preview the
// conversation's final artifact through the same CanvasDoc the canvas uses;
// "Use prompt" drops the example's prompt into the composer, "View" opens the
// share page (transcript + artifact). Data: GET /examples, resolved
// server-side from the operator's `.examples()` share list.

export interface ExampleItem {
  share: string;   // /shared/<user>/<token>?example=1 — the full story
  title: string;
  prompt: string;
  file: { path: string; name: string; url: string } | null;
}

export interface ExampleCategory {
  label: string;
  label_ar?: string | null;
  items: ExampleItem[];
}

// Module-level cache: the gallery re-mounts on every new chat; the cards don't.
let cached: ExampleCategory[] | null = null;

export function useExamples() {
  const [categories, setCategories] = useState<ExampleCategory[]>(cached || []);
  useEffect(() => {
    if (cached) return;
    let cancelled = false;
    fetch("/examples")
      .then((r) => (r.ok ? r.json() : { categories: [] }))
      .then((d) => {
        cached = d.categories || [];
        if (!cancelled) setCategories(cached!);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);
  return categories;
}

export function ExamplesGallery({ onUsePrompt, className }: {
  onUsePrompt: (text: string) => void;
  className?: string;
}) {
  const categories = useExamples();
  const [active, setActive] = useState<string | null>(null);
  if (!categories.length) return null;

  const labeled = categories.filter((c) => c.label);
  const current = categories.find((c) => c.label === (active ?? categories[0].label)) || categories[0];

  return (
    <div className={cn("flex w-full flex-col items-center", className)}>
      {/* Category pills — directly under the composer, hanging off its left
          edge like prompt starters, not a centered toolbar. One scrollable
          row on mobile. */}
      {labeled.length > 1 && (
        <div className="flex w-full max-w-3xl justify-start gap-2 overflow-x-auto scrollbar-none px-1 sm:flex-wrap sm:overflow-visible">
          {categories.map((c) => (
            <button
              key={c.label}
              onClick={() => {
                setActive(c.label);
                track("example_category_selected", { category: c.label });
              }}
              className={cn(
                "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors cursor-pointer",
                c.label === current.label
                  ? "border-border bg-secondary text-foreground"
                  : "border-border bg-background text-foreground hover:bg-secondary/50",
              )}
            >
              {getLang() === "ar" && c.label_ar ? c.label_ar : c.label}
            </button>
          ))}
        </div>
      )}
      {/* Mobile: one swipeable snap row, next card peeking — the composer
          stays dominant but the outputs are still on the first screen.
          Desktop: the grid. */}
      <div className="-mx-6 mt-6 flex w-[calc(100%+3rem)] snap-x snap-mandatory gap-3 overflow-x-auto scrollbar-none px-6 sm:mx-0 sm:grid sm:w-full sm:snap-none sm:grid-cols-2 sm:gap-4 sm:overflow-visible sm:px-0 lg:grid-cols-3">
        {current.items.map((item) => (
          <ExampleCard key={item.share} item={item} category={current.label} onUsePrompt={onUsePrompt} />
        ))}
      </div>
    </div>
  );
}

// One card: a live, scaled-down render of the artifact (lazy — fetched when
// the card scrolls near the viewport), hover/touch actions on top.
function ExampleCard({ item, category, onUsePrompt }: {
  item: ExampleItem;
  category: string;
  onUsePrompt: (text: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setVisible(true); io.disconnect(); } },
      { rootMargin: "200px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="group relative w-[78vw] max-w-[420px] shrink-0 snap-center overflow-hidden rounded-xl border border-border bg-card sm:w-auto sm:max-w-none sm:shrink sm:snap-align-none"
    >
      <div className="aspect-video w-full overflow-hidden transition-transform duration-300 ease-out sm:group-hover:scale-[1.13]">
        <ExamplePreview item={item} load={visible} />
      </div>

      {/* Hover actions — always reachable on touch, hover-revealed on desktop.
          The scrim is a whisper of background fading from the top, not a sheet. */}
      <div className="absolute inset-0 flex items-center justify-center gap-2 bg-[linear-gradient(to_bottom,color-mix(in_oklab,var(--color-background)_35%,transparent)_0%,color-mix(in_oklab,var(--color-background)_12%,transparent)_45%,transparent_75%)] opacity-100 sm:opacity-0 transition-opacity duration-300 sm:group-hover:opacity-100">
        {item.prompt && (
          <button
            onClick={() => {
              onUsePrompt(item.prompt);
              track("example_prompt_used", { category, share: item.share });
            }}
            className="rounded-full bg-background border border-border px-3.5 py-2 text-sm font-medium text-foreground hover:bg-secondary transition-colors cursor-pointer shadow-sm"
          >
            {t("usePrompt")}
          </button>
        )}
        <a
          href={item.share}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => track("example_viewed", { category, share: item.share })}
          className="rounded-full bg-foreground px-3.5 py-2 text-sm font-medium text-background hover:opacity-90 transition-opacity shadow-sm"
        >
          {t("viewExample")}
        </a>
      </div>
    </motion.div>
  );
}

function ExamplePreview({ item, load }: { item: ExampleItem; load: boolean }) {
  const file = item.file;
  const readFile = useCallback(async () => {
    const r = await fetch(file!.url);
    if (!r.ok) throw new Error("failed");
    return r.text();
  }, [file?.url]);   // eslint-disable-line react-hooks/exhaustive-deps
  const openFile = useCallback(async () => {
    const r = await fetch(file!.url);
    if (!r.ok) throw new Error("failed");
    return URL.createObjectURL(await r.blob());
  }, [file?.url]);   // eslint-disable-line react-hooks/exhaustive-deps

  const renderable = !!file && isRenderable(file.path);
  const { content, error } = useFileContent(load && renderable ? file : null, readFile, openFile);

  // No artifact (or unrenderable): the prompt itself is the preview.
  if (!renderable) {
    return (
      <div className="h-full w-full bg-secondary/30 p-4">
        <p className="text-xs leading-relaxed text-muted-foreground line-clamp-5">{item.prompt}</p>
      </div>
    );
  }

  // HTML renders at desktop width, scaled to card size — the real page, not a
  // thumbnail of it. pointer-events off: the card owns the interactions.
  if (isHtml(file!.path)) {
    return (
      <div className="pointer-events-none h-full w-full overflow-hidden">
        <div className="h-[400%] w-[400%] origin-top-left scale-[0.25]">
          {content != null && <CanvasDoc file={file!} content={content} error={error} shared />}
        </div>
      </div>
    );
  }
  return (
    <div className="pointer-events-none h-full w-full">
      <CanvasDoc file={file!} content={content} error={error} shared />
    </div>
  );
}

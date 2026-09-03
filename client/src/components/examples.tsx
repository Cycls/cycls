import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import { useFileContent, CanvasDoc } from "./canvas";
import { isHtml, isRenderable } from "./canvas-utils";
import { Icon } from "./icon";
import { track } from "../lib/analytics";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";

// The examples gallery — curated public shares rendered as artifact cards on
// the empty-chat screen (docs/notes/examples-gallery.md). Cards preview the
// conversation's final artifact through the same CanvasDoc the canvas uses;
// "Use prompt" drops the example's prompt into the composer, "View" opens the
// share page (transcript + artifact). Data: GET /examples, resolved
// server-side from the operator's `.examples()` share list.

export interface ExampleItem {
  share?: string | null;   // artifact card: /shared/<user>/<token>?example=1
  title: string;
  prompt?: string;
  file?: { path: string; name: string; url: string } | null;
  video?: string | null;   // tutorial card: direct mp4/webm or a YouTube URL
}

// YouTube in any of its shapes → the video id; null means not YouTube.
export function youtubeId(url: string): string | null {
  const m = url.match(/(?:youtube\.com\/(?:watch\?[^#]*v=|shorts\/|embed\/)|youtu\.be\/)([\w-]{6,20})/);
  return m ? m[1] : null;
}

export function vimeoId(url: string): string | null {
  const m = url.match(/vimeo\.com\/(?:video\/)?(\d{6,12})/);
  return m ? m[1] : null;
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
  const [playing, setPlaying] = useState<ExampleItem | null>(null);
  // One impression per gallery view — the denominator for example_prompt_used.
  useEffect(() => {
    if (!categories.length) return;
    track("examples_shown", {
      categories: categories.length,
      items: categories.reduce((n, c) => n + c.items.length, 0),
    });
  }, [categories.length]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!categories.length) return null;

  const labeled = categories.filter((c) => c.label);
  const current = categories.find((c) => c.label === (active ?? categories[0].label)) || categories[0];

  return (
    <div className={cn("flex w-full flex-col items-center", className)}>
      {/* Category pills — directly under the composer, hanging off its left
          edge like prompt starters, not a centered toolbar. One scrollable
          row on mobile. Shown even for a single category: the pill names what
          the cards below are, which is worth more than the row it costs.
          Maps `labeled`, so a category configured without a label can still
          hold cards without rendering a blank pill. */}
      {labeled.length > 0 && (
        <div className="flex w-full max-w-3xl justify-start gap-2 overflow-x-auto scrollbar-none px-1 sm:flex-wrap sm:overflow-visible">
          {labeled.map((c) => (
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
          <ExampleCard key={item.share || item.video || item.title} item={item} category={current.label}
                       onUsePrompt={onUsePrompt} onWatch={() => setPlaying(item)} />
        ))}
      </div>
      {playing?.video && <VideoLightbox item={playing} onClose={() => setPlaying(null)} />}
    </div>
  );
}

// In-page player for tutorial cards — dimmed backdrop, Esc/backdrop/X to
// close. YouTube plays through the privacy embed; files through <video>.
function VideoLightbox({ item, onClose }: { item: ExampleItem; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const yt = youtubeId(item.video || "");
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 sm:p-8" onClick={onClose}>
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.15 }}
                  className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.15 }}
        className="relative w-full max-w-4xl overflow-hidden rounded-xl bg-black shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {yt ? (
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${yt}?autoplay=1`}
            title={item.title || "Tutorial"}
            className="aspect-video w-full"
            allow="autoplay; encrypted-media; fullscreen; picture-in-picture"
            allowFullScreen
          />
        ) : vimeoId(item.video || "") ? (
          <iframe
            src={`https://player.vimeo.com/video/${vimeoId(item.video || "")}?autoplay=1`}
            title={item.title || "Tutorial"}
            className="aspect-video w-full"
            allow="autoplay; fullscreen; picture-in-picture"
            allowFullScreen
          />
        ) : (
          <video src={item.video || undefined} controls autoPlay playsInline className="aspect-video w-full" />
        )}
      </motion.div>
      <button
        onClick={onClose}
        className="absolute top-4 end-4 z-10 flex size-9 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors cursor-pointer"
        aria-label="Close"
      >
        <Icon name="x" className="size-4" />
      </button>
    </div>
  );
}

// One card: a live, scaled-down render of the artifact (lazy — fetched when
// the card scrolls near the viewport), hover/touch actions on top.
function ExampleCard({ item, category, onUsePrompt, onWatch }: {
  item: ExampleItem;
  category: string;
  onUsePrompt: (text: string) => void;
  onWatch: () => void;
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
        {item.video ? (
          // Tutorial card: one action — play it right here on the page.
          <button
            onClick={() => {
              onWatch();
              track("example_watched", { category, video: item.video });
            }}
            className="rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 transition-opacity shadow-sm cursor-pointer"
          >
            {t("watch")}
          </button>
        ) : (
          <>
            {item.prompt && (
              <button
                onClick={() => {
                  onUsePrompt(item.prompt!);
                  track("example_prompt_used", { category, share: item.share });
                }}
                className="rounded-full bg-background border border-border px-3.5 py-2 text-sm font-medium text-foreground hover:bg-secondary transition-colors cursor-pointer shadow-sm"
              >
                {t("usePrompt")}
              </button>
            )}
            <a
              href={item.share || "#"}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => track("example_viewed", { category, share: item.share })}
              className="rounded-full bg-foreground px-3.5 py-2 text-sm font-medium text-background hover:opacity-90 transition-opacity shadow-sm"
            >
              {t("viewExample")}
            </a>
          </>
        )}
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
  const { content, error } = useFileContent(load && renderable && !item.video ? file! : null, readFile, openFile);

  // Tutorial preview — a muted looping clip for direct files, the thumbnail
  // for YouTube, a play glyph for other hosted players (Vimeo has no free
  // thumbnail URL); only fetched once the card scrolls into view.
  if (item.video) {
    const yt = youtubeId(item.video);
    const isFile = !yt && !vimeoId(item.video);
    return (
      <div className="pointer-events-none flex h-full w-full items-center justify-center bg-secondary/30">
        {load && (yt ? (
          <img src={`https://i.ytimg.com/vi/${yt}/hqdefault.jpg`} alt="" className="h-full w-full object-cover" />
        ) : isFile ? (
          <video
            src={item.video}
            muted
            loop
            autoPlay
            playsInline
            preload="metadata"
            className="h-full w-full object-cover"
          />
        ) : (
          <svg viewBox="0 0 24 24" className="size-10 text-muted-foreground/60" fill="currentColor">
            <path d="M8 5.14v13.72c0 .9.98 1.45 1.74.98l10.02-6.86a1.15 1.15 0 000-1.96L9.74 4.16A1.15 1.15 0 008 5.14z" />
          </svg>
        ))}
      </div>
    );
  }

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

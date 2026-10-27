import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { shownName, tileExt, tintLabel, tintTile } from "./canvas-utils";
import { Icon } from "./icon";
import { track } from "../lib/analytics";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { useEscape } from "../hooks/use-escape";

// The examples gallery — curated public shares on the empty-chat screen
// (docs/notes/examples-gallery.md), in a new order each visit. A card is the
// example's prompt and the file it made, in text; it opens the share page
// (transcript + artifact), and "Use prompt" drops the prompt into the composer.
// Data: GET /examples, resolved server-side from the operator's `.examples()` share list.

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

// A new order each visit, kept for the visit: no example is always first.
function shuffled<T>(xs: T[]): T[] {
  const out = [...xs];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export function useExamples() {
  const [categories, setCategories] = useState<ExampleCategory[]>(cached || []);
  useEffect(() => {
    if (cached) return;
    let cancelled = false;
    fetch("/examples")
      .then((r) => (r.ok ? r.json() : { categories: [] }))
      .then((d) => {
        cached = ((d.categories || []) as ExampleCategory[]).map((c) => ({ ...c, items: shuffled(c.items || []) }));
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
  useEscape(onClose);
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

// One card. A tutorial plays its clip; an example is what was asked and the file it made, in text: a live
// render of a PDF or a sheet looks different on every device, and loads the whole file for one card.
function ExampleCard({ item, category, onUsePrompt, onWatch }: {
  item: ExampleItem;
  category: string;
  onUsePrompt: (text: string) => void;
  onWatch: () => void;
}) {
  if (item.video) return <VideoCard item={item} category={category} onWatch={onWatch} />;
  const file = item.file;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex w-[78vw] max-w-[420px] shrink-0 snap-center flex-col items-start gap-2 sm:w-auto sm:max-w-none sm:shrink sm:snap-align-none"
    >
      <a
        href={item.share || "#"}
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => track("example_viewed", { category, share: item.share })}
        className="flex aspect-video w-full flex-col justify-between gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:bg-secondary/40"
      >
        <p dir="auto" className="line-clamp-4 text-start text-sm leading-relaxed text-foreground">{item.prompt || item.title}</p>
        {file && (
          <span className="flex w-full min-w-0 items-center gap-2">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-secondary text-[9px] font-bold" style={tintTile(file.name)}>
              <span style={tintLabel(file.name)}>{(tileExt(file.name) || "file").slice(0, 4).toUpperCase()}</span>
            </span>
            <span dir="auto" className="truncate text-xs text-muted-foreground">{shownName(file.name)}</span>
          </span>
        )}
      </a>
      {item.prompt && (
        <button
          onClick={() => {
            onUsePrompt(item.prompt!);
            track("example_prompt_used", { category, share: item.share });
          }}
          className="rounded-full border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground cursor-pointer"
        >
          {t("usePrompt")}
        </button>
      )}
    </motion.div>
  );
}

// A tutorial: its clip or thumbnail (fetched when the card scrolls near), Watch on top.
function VideoCard({ item, category, onWatch }: { item: ExampleItem; category: string; onWatch: () => void }) {
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

  const yt = youtubeId(item.video || "");
  const isFile = !yt && !vimeoId(item.video || "");
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="group relative w-[78vw] max-w-[420px] shrink-0 snap-center overflow-hidden rounded-xl border border-border bg-card sm:w-auto sm:max-w-none sm:shrink sm:snap-align-none"
    >
      <div className="pointer-events-none flex aspect-video w-full items-center justify-center bg-secondary/30">
        {visible && (yt ? (
          <img src={`https://i.ytimg.com/vi/${yt}/hqdefault.jpg`} alt="" className="h-full w-full object-cover" />
        ) : isFile ? (
          <video src={item.video || undefined} muted loop autoPlay playsInline preload="metadata" className="h-full w-full object-cover" />
        ) : (
          <svg viewBox="0 0 24 24" className="size-10 text-muted-foreground/60" fill="currentColor">
            <path d="M8 5.14v13.72c0 .9.98 1.45 1.74.98l10.02-6.86a1.15 1.15 0 000-1.96L9.74 4.16A1.15 1.15 0 008 5.14z" />
          </svg>
        ))}
      </div>
      <div className="absolute inset-0 flex items-center justify-center">
        <button
          onClick={() => {
            onWatch();
            track("example_watched", { category, video: item.video });
          }}
          className="rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90 transition-opacity shadow-sm cursor-pointer"
        >
          {t("watch")}
        </button>
      </div>
    </motion.div>
  );
}

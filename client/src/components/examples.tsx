import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import { useFileContent, CanvasDoc } from "./canvas";
import { embedsPdf, isHtml, isPdf, isPresentation, isRenderable, isSpreadsheet, tileExt, tintLabel, tintTile } from "./canvas-utils";
import { parseDeck } from "./deck-view";
import { Icon } from "./icon";
import { track } from "../lib/analytics";
import { t, getLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { useEscape } from "../hooks/use-escape";

// The examples gallery — curated public shares on the empty-chat screen
// (docs/notes/examples-gallery.md), in a new order each visit. A card previews
// the conversation's final artifact through the same CanvasDoc the canvas uses
// (its type and prompt when the file can't be drawn there); the card and "View"
// open the share page (transcript + artifact), "Use prompt" drops the example's
// prompt into the composer: both in a slim bar at the card's foot, always there
// on a touch screen, on hover where a pointer hovers.
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

// True once the element scrolls within 200px of the viewport: what a card fetches waits for it.
function useNear(ref: React.RefObject<HTMLDivElement | null>) {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setNear(true); io.disconnect(); } },
      { rootMargin: "200px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref]);
  return near;
}

function ExampleCard({ item, category, onUsePrompt, onWatch }: {
  item: ExampleItem;
  category: string;
  onUsePrompt: (text: string) => void;
  onWatch: () => void;
}) {
  return item.video
    ? <VideoCard item={item} category={category} onWatch={onWatch} />
    : <FileCard item={item} category={category} onUsePrompt={onUsePrompt} />;
}

// An example: a live, scaled-down render of the file it made; the box opens the example. Use prompt and View: on a
// touch screen in a slim bar along its foot, always there; where a pointer hovers, in its middle while it does, so
// the card is clean until then.
function FileCard({ item, category, onUsePrompt }: {
  item: ExampleItem;
  category: string;
  onUsePrompt: (text: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useNear(ref);
  const viewed = () => track("example_viewed", { category, share: item.share });
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="group relative aspect-video w-[78vw] max-w-[420px] shrink-0 snap-center overflow-hidden rounded-xl border border-border bg-card transition-colors hover:border-foreground/20 sm:w-auto sm:max-w-none sm:shrink sm:snap-align-none"
    >
      <a href={item.share || "#"} target="_blank" rel="noopener noreferrer" onClick={viewed} aria-label={t("viewExample")}
         className="block h-full w-full">
        <div className="h-full w-full transition-transform duration-300 ease-out group-hover:scale-[1.03]">
          <ExamplePreview item={item} load={near} />
        </div>
      </a>
      {/* Touch: a slim bar at the foot, always there. Pointer: in the middle, only while hovered, nothing else over it. */}
      <div data-example-actions
           className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-end gap-1.5 bg-gradient-to-t from-background/85 via-background/40 to-transparent px-2.5 pb-2.5 pt-6 transition-opacity duration-200 [@media(hover:hover)]:inset-0 [@media(hover:hover)]:items-center [@media(hover:hover)]:justify-center [@media(hover:hover)]:gap-2 [@media(hover:hover)]:bg-none [@media(hover:hover)]:px-0 [@media(hover:hover)]:pb-0 [@media(hover:hover)]:pt-0 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100">
        {item.prompt && (
          <button
            onClick={() => {
              onUsePrompt(item.prompt!);
              track("example_prompt_used", { category, share: item.share });
            }}
            className="pointer-events-auto rounded-full border border-border bg-background/90 px-3 py-1 text-xs font-medium text-foreground backdrop-blur transition-colors hover:bg-secondary cursor-pointer [@media(hover:hover)]:bg-background [@media(hover:hover)]:px-3.5 [@media(hover:hover)]:py-2 [@media(hover:hover)]:text-sm [@media(hover:hover)]:shadow-sm"
          >
            {t("usePrompt")}
          </button>
        )}
        <a href={item.share || "#"} target="_blank" rel="noopener noreferrer" onClick={viewed}
           className="pointer-events-auto rounded-full bg-foreground px-3 py-1 text-xs font-medium text-background transition-opacity hover:opacity-90 [@media(hover:hover)]:px-3.5 [@media(hover:hover)]:py-2 [@media(hover:hover)]:text-sm [@media(hover:hover)]:shadow-sm">
          {t("viewExample")}
        </a>
      </div>
    </motion.div>
  );
}

function ExamplePreview({ item, load }: { item: ExampleItem; load: boolean }) {
  const file = item.file;
  // The canvas asks for a file by its path, a deck with `?as=slides`: the share's file route takes the same query.
  const readFile = useCallback(async (path: string) => {
    const r = await fetch(file!.url + (path.includes("?") ? path.slice(path.indexOf("?")) : ""));
    if (!r.ok) throw new Error("failed");
    return r.text();
  }, [file?.url]);   // eslint-disable-line react-hooks/exhaustive-deps
  const openFile = useCallback(async (path: string) => {
    const r = await fetch(file!.url + (path.includes("?") ? path.slice(path.indexOf("?")) : ""));
    if (!r.ok) throw new Error("failed");
    return URL.createObjectURL(await r.blob());
  }, [file?.url]);   // eslint-disable-line react-hooks/exhaustive-deps

  // A PDF where the browser can't show one in the page (Chrome on Android) can't be drawn in a card either.
  const renderable = !!file && isRenderable(file.path) && !(isPdf(file.path) && !embedsPdf());
  const { content, error } = useFileContent(load && renderable ? file! : null, readFile, openFile, 0, true);
  if (!renderable || error) return <PreviewFallback item={item} />;

  // A PDF fills the card's width, its page and nothing of the viewer (no toolbar, page list or scrollbar), the
  // frame 10px past every edge so the margin the viewer leaves round a page is cut off.
  if (isPdf(file!.path)) {
    return (
      <div className="pointer-events-none relative h-full w-full overflow-hidden bg-white">
        {content && (
          <iframe src={`${content}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`} title={file!.name}
                  className="absolute -inset-[10px] h-[calc(100%+20px)] w-[calc(100%+20px)] border-0" />
        )}
      </div>
    );
  }
  // A deck is its first slide, filling the card, not the deck viewer squeezed into it.
  if (isPresentation(file!.path)) {
    const first = content != null ? parseDeck(content)?.slides?.[0] : undefined;
    if (content != null && !first) return <PreviewFallback item={item} />;
    return (
      <div className="pointer-events-none h-full w-full bg-secondary/30">
        {first && <img src={first} alt="" className="h-full w-full object-cover" />}
      </div>
    );
  }
  // A sheet is its grid: the viewer's note under it falls past the card's foot, and no scrollbars.
  if (isSpreadsheet(file!.path)) {
    return (
      <div className="pointer-events-none relative h-full w-full overflow-hidden [&_*]:[scrollbar-width:none]">
        <div className="absolute inset-x-0 top-0 h-[calc(100%+3rem)]">
          <CanvasDoc file={file!} content={content} error={error} shared />
        </div>
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

// A card whose file can't be drawn here: its type, in the type's colour, and what was asked.
function PreviewFallback({ item }: { item: ExampleItem }) {
  const name = item.file?.name || "";
  return (
    <div className="flex h-full w-full flex-col justify-between gap-3 bg-secondary/30 p-4 pb-12" style={tintTile(name)}>
      {name && (
        <span className="flex size-10 items-center justify-center rounded-lg bg-background/70 text-[10px] font-bold" style={tintLabel(name)}>
          {(tileExt(name) || "file").slice(0, 4).toUpperCase()}
        </span>
      )}
      <p dir="auto" className="line-clamp-2 text-start text-sm leading-relaxed text-foreground/80 sm:line-clamp-3">{item.prompt || item.title}</p>
    </div>
  );
}

// A tutorial: its clip or thumbnail (fetched when the card scrolls near), Watch on top.
function VideoCard({ item, category, onWatch }: { item: ExampleItem; category: string; onWatch: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const visible = useNear(ref);

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

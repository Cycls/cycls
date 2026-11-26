import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import { useFileContent, CanvasDoc } from "./canvas";
import { embedsPdf, isDocx, isHtml, isMd, isPdf, isPresentation, isRenderable, isSpreadsheet, tileExt, tintLabel, tintTile } from "./canvas-utils";
import { parseDeck } from "./deck-view";
import { FormatTiles, formatHint, formatName, formatOf, TypeTile, type FormatOption } from "./example-filters";
import { Icon } from "./icon";
import { track } from "../lib/analytics";
import { t, getLang, useLang } from "../lib/i18n";
import { cn } from "../lib/utils";
import { useEscape } from "../hooks/use-escape";

// The examples gallery — curated public shares on the empty-chat screen
// (docs/notes/examples-gallery.md), in a new order each visit, two rows at a time and more as you scroll. Over it,
// under the composer, the file types the work comes in (example-filters.tsx): one chosen shows only its examples
// and has the composer ask its question. A card is the work as a page tilted on a tile, straightening while hovered —
// its picture, or the file drawn live through the same CanvasDoc the canvas uses — with the file's type, its title
// and the request under it. The card opens the share page; "Make one like this" hands the composer the example's
// template, its blanks in [brackets], on hover where a pointer hovers, always on a touch screen. cycls.com's examples are the same card (cycls ai web: components/sections/library-card.tsx).
// Data: GET /examples, resolved server-side from the operator's `.examples()` share list or the CMS.

export interface ExampleItem {
  share?: string | null;   // artifact card: /shared/<user>/<token>?example=1
  title: string;
  title_ar?: string | null;
  prompt?: string;
  kind?: string | null;    // the file's type when the card brings its own picture: pdf, docx, xlsx, pptx, md, html, fig, image, video
  file?: { path: string; name: string; url: string } | null;
  video?: string | null;   // tutorial card: direct mp4/webm or a YouTube URL
  thumbnail?: string | null;   // the picture the card shows instead, for a file that doesn't preview well
  template?: string | null;    // "Make one like this": the request with its particulars as [blanks]
  template_ar?: string | null;
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

// The composer beside the gallery: the type chosen under it, whose question it asks (`hint`), and "Make one like
// this" (`makeLike`), which puts in an example's template, replacing only an empty composer or the template before
// it, never what the person wrote, and selects its first blank to type over.
export function useExampleComposer(input: string, setInput: (v: string) => void,
                                   textareaRef: React.RefObject<HTMLTextAreaElement | null>) {
  const [format, setFormat] = useState<string | null>(null);
  const auto = useRef("");
  const toBlank = (text: string, select: boolean) => requestAnimationFrame(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.scrollIntoView?.({ block: "center", behavior: "smooth" });
    ta.focus({ preventScroll: true });
    const a = text.indexOf("["), b = text.indexOf("]", a + 1);
    if (select && a >= 0 && b > a) ta.setSelectionRange(a, b + 1);
  });
  // A draft that came with blanks (a "Make one like this" link from cycls.com): its first blank, ready to type over.
  useEffect(() => { if (/\[[^\]]+\]/.test(input)) { auto.current = input; toBlank(input, true); } }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  const makeLike = (text: string) => {
    const replace = !input.trim() || input === auto.current;
    if (replace) { setInput(text); auto.current = text; }
    toBlank(text, replace);
  };
  return { hint: format ? formatHint(format) : "", setFormat, makeLike };
}

const ALL = "\0all";
const keyOf = (item: ExampleItem) => item.share || item.video || item.title;

// Three cards a row where there is room, two on a phone (the grid's lg: breakpoint).
function useColumns() {
  const query = "(min-width: 64rem)";
  const [cols, setCols] = useState(() => (window.matchMedia?.(query).matches ? 3 : 2));
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setCols(mq.matches ? 3 : 2);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return cols;
}

export function ExamplesGallery({ onUsePrompt, onFormat, name, className }: {
  onUsePrompt: (text: string) => void;   // "Make one like this": the example's template
  onFormat?: (format: string | null) => void;   // the type chosen under the composer, null for all
  name?: string;   // the agent's: the gallery is «Made with <name>»
  className?: string;
}) {
  const categories = useExamples();
  const cols = useColumns();
  const lang = useLang();   // the type names and the cards' words follow a change of language
  const [active, setActive] = useState<string | null>(null);
  const [rows, setRows] = useState(2);
  const [playing, setPlaying] = useState<ExampleItem | null>(null);
  const end = useRef<HTMLDivElement>(null);
  // One impression per gallery view — the denominator for example_prompt_used.
  useEffect(() => {
    if (!categories.length) return;
    track("examples_shown", {
      categories: categories.length,
      items: categories.reduce((n, c) => n + c.items.length, 0),
    });
  }, [categories.length]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Every card once; the file types they come in, the most first.
  const all = useMemo(() => {
    const seen = new Set<string>();
    return categories.flatMap((c) => c.items).filter((i) => !seen.has(keyOf(i)) && !!seen.add(keyOf(i)));
  }, [categories]);
  const kinds = useMemo(() => {
    const by = new Map<string, ExampleItem[]>();
    for (const i of all) by.set(formatOf(i), [...(by.get(formatOf(i)) || []), i]);
    return [...by].sort((a, b) => b[1].length - a[1].length).map(([f, items]) => ({ key: f, text: formatName(f), items }));
  }, [all, lang]);   // eslint-disable-line react-hooks/exhaustive-deps
  const current = active ?? ALL;
  const items = (current !== ALL && kinds.find((k) => k.key === current)?.items) || all;
  const category = current === ALL ? "all" : current;
  const shown = rows * cols;

  // Two rows first; two more each time the end of the grid comes into view.
  useEffect(() => setRows(2), [current]);
  useEffect(() => { onFormat?.(current === ALL ? null : current); }, [current]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = end.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) setRows((r) => r + 2); }, { rootMargin: "100px" });
    io.observe(el);
    return () => io.disconnect();
  }, [shown, current, items.length]);

  if (!categories.length) return null;
  const options: FormatOption[] = [
    { key: ALL, text: t("all"), count: all.length },
    ...kinds.map((k) => ({ key: k.key, text: k.text, count: k.items.length, format: k.key })),
  ];
  const choose = (key: string) => {
    setActive(key);
    track("example_category_selected", { category: key === ALL ? "all" : key });
  };
  // "Make one like this": the row marks what it makes, and the composer gets its template.
  const makeLike = (item: ExampleItem) => {
    setActive(formatOf(item));
    onUsePrompt(templateOf(item));
  };

  return (
    <div className={cn("flex w-full flex-col", className)}>
      {kinds.length > 1 && <FormatTiles value={current} options={options} onChange={choose} />}
      <h2 className="mt-10 text-[15px] font-semibold text-foreground">{name ? t("madeWith").replace("{name}", name) : t("examples")}</h2>
      {/* Two columns on a phone, three where there is room; the page scrolls and brings more. */}
      <div className="mt-4 grid w-full grid-cols-2 gap-x-3 gap-y-6 sm:gap-x-[18px] sm:gap-y-[23px] lg:grid-cols-3">
        {items.slice(0, shown).map((item) => (
          <ExampleCard key={keyOf(item)} item={item} category={category}
                       onUseExample={() => makeLike(item)} onWatch={() => setPlaying(item)} />
        ))}
      </div>
      {shown < items.length && <div ref={end} data-examples-more className="h-px w-full" />}
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

// A card comes in once a page: back after a workspace switch (Chat remounts), it is simply there.
const entered = new WeakSet<ExampleItem>();
function useEntrance(item: ExampleItem) {
  const [first] = useState(() => !entered.has(item));
  useEffect(() => { entered.add(item); }, [item]);
  return { initial: first && { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.2 } };
}

function ExampleCard({ item, category, onUseExample, onWatch }: {
  item: ExampleItem;
  category: string;
  onUseExample: () => void;
  onWatch: () => void;
}) {
  return item.video
    ? <VideoCard item={item} category={category} onWatch={onWatch} />
    : <WorkCard item={item} category={category} onUseExample={onUseExample} />;
}

const titleOf = (item: ExampleItem) => (getLang() === "ar" && item.title_ar) || item.title;
// The template in the page's language, else the other, else the request itself.
const templateOf = (item: ExampleItem) =>
  (getLang() === "ar" ? item.template_ar || item.template : item.template || item.template_ar) || item.prompt || "";

// A card's file type, in the tile cycls.com draws (example-filters.tsx: TypeTile).
const KIND_EXT: Record<string, string> = { pdf: "pdf", docx: "docx", xlsx: "xlsx", pptx: "pptx", md: "md", html: "html", fig: "fig", image: "png", video: "mp4" };
function KindTile({ item }: { item: ExampleItem }) {
  const name = item.video ? "f.mp4" : item.file?.name || (item.kind ? `f.${KIND_EXT[item.kind] || item.kind}` : "");
  const label = (item.video ? "video" : item.kind === "image" ? "img" : tileExt(name) || "file").slice(0, 6).toUpperCase();
  return <TypeTile name={name} label={label} className="mt-0.5" />;
}

// The file's type, its title and the request, under a card's tile.
function CardText({ item }: { item: ExampleItem }) {
  return (
    <>
      <KindTile item={item} />
      <span className="min-w-0">
        <span dir="auto" className="line-clamp-1 text-[15px] font-semibold leading-snug text-foreground">{titleOf(item)}</span>
        {item.prompt && <span dir="auto" className="line-clamp-1 text-[13px] leading-6 text-muted-foreground">«{item.prompt}»</span>}
      </span>
    </>
  );
}

function WorkCard({ item, category, onUseExample }: {
  item: ExampleItem;
  category: string;
  onUseExample: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const near = useNear(ref);
  const entrance = useEntrance(item);
  const viewed = () => track("example_viewed", { category, share: item.share });
  return (
    <motion.div
      ref={ref}
      {...entrance}
      className="group relative grid min-w-0 content-start gap-2.5 text-start"
    >
      <a href={item.share || "#"} target="_blank" rel="noopener noreferrer" onClick={viewed} aria-label={titleOf(item) || t("viewExample")}
         className="block">
        <Tile item={item} load={near} />
      </a>
      {(item.template || item.template_ar || item.prompt) && (
        <button
          onClick={() => {
            onUseExample();
            track("example_prompt_used", { category, share: item.share });
          }}
          className="absolute top-2 end-2 cursor-pointer rounded-full border border-border bg-background/90 px-3 py-1 text-xs font-medium text-foreground shadow-sm backdrop-blur transition-opacity hover:bg-secondary [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 [@media(hover:hover)]:focus-visible:opacity-100"
        >
          {t("makeOneLikeThis")}
        </button>
      )}
      <a href={item.share || "#"} target="_blank" rel="noopener noreferrer" onClick={viewed} className="flex min-w-0 items-start gap-2.5">
        <CardText item={item} />
      </a>
    </motion.div>
  );
}

// A page — a PDF, a document — stands upright; a deck, a page of the web or a sheet lies wide.
const upright = (item: ExampleItem) => {
  const p = item.file?.path || "";
  return isPdf(p) || isDocx(p) || isMd(p);
};

// The work as a page on a light grey tile (dark grey in the dark), tilted until the card is hovered (the Super
// mockup's miniature): a page stands and is cut off at its foot, a slide or a screen lies wide. Its picture decides
// which by its own shape.
const TILE = "relative flex aspect-[16/10] w-full items-center justify-center overflow-hidden rounded-[4px] border border-black/[.07] bg-[#e1e1e1] dark:border-white/[.06] dark:bg-[#222]";

function Tile({ item, load }: { item: ExampleItem; load: boolean }) {
  const [wide, setWide] = useState<boolean | null>(item.thumbnail ? null : !upright(item));
  const paper = cn(
    "shadow-[3px_5px_9px_#0003] transition-[translate,rotate,opacity] duration-200 group-hover:translate-y-[2%] group-hover:rotate-[-1deg]",
    wide ? "w-[86%] translate-y-[5%] rotate-[-4deg]" : "h-[136%] max-w-[92%] translate-y-[10%] rotate-[-5deg]",
  );
  return (
    <span className={TILE}>
      {item.thumbnail ? (   // a picture chosen for it: the file isn't fetched at all
        load && (
          <img src={item.thumbnail} alt="" draggable={false}
               onLoad={(e) => setWide(e.currentTarget.naturalWidth > e.currentTarget.naturalHeight * 1.1)}
               className={cn(paper, wide ? "h-auto" : "w-auto object-cover object-top", wide === null && "opacity-0")} />
        )
      ) : (
        <span className={cn(paper, "pointer-events-none block overflow-hidden bg-background", wide ? "aspect-video" : "aspect-[1/1.414] bg-white")}>
          <ExamplePreview item={item} load={load} />
        </span>
      )}
    </span>
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

  // A PDF fills the page's width, its page and nothing of the viewer (no toolbar, page list or scrollbar), the
  // frame 10px past every edge so the margin the viewer leaves round a page is cut off.
  if (isPdf(file!.path)) {
    return (
      <div className="relative h-full w-full overflow-hidden bg-white">
        {content && (
          <iframe src={`${content}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`} title={file!.name}
                  className="absolute -inset-[10px] h-[calc(100%+20px)] w-[calc(100%+20px)] border-0" />
        )}
      </div>
    );
  }
  // A deck is its first slide, not the deck viewer squeezed into it.
  if (isPresentation(file!.path)) {
    const first = content != null ? parseDeck(content)?.slides?.[0] : undefined;
    if (content != null && !first) return <PreviewFallback item={item} />;
    return first ? <img src={first} alt="" className="h-full w-full object-cover" /> : null;
  }
  // A sheet is its grid: the viewer's note under it falls past the page's foot, and no scrollbars.
  if (isSpreadsheet(file!.path)) {
    return (
      <div className="relative h-full w-full overflow-hidden [&_*]:[scrollbar-width:none]">
        <div className="absolute inset-x-0 top-0 h-[calc(100%+3rem)]">
          <CanvasDoc file={file!} content={content} error={error} shared />
        </div>
      </div>
    );
  }
  // HTML renders at desktop width, scaled to the page — the real page, not a picture of it.
  if (isHtml(file!.path)) {
    return (
      <div className="h-full w-full overflow-hidden">
        <div className="h-[400%] w-[400%] origin-top-left scale-[0.25]">
          {content != null && <CanvasDoc file={file!} content={content} error={error} shared />}
        </div>
      </div>
    );
  }
  return (
    <div className="h-full w-full">
      <CanvasDoc file={file!} content={content} error={error} shared />
    </div>
  );
}

// A card whose file can't be drawn here: its type, in the type's colour, and what was asked.
function PreviewFallback({ item }: { item: ExampleItem }) {
  const name = item.file?.name || "";
  return (
    <div className="flex h-full w-full flex-col justify-between gap-2 bg-secondary/30 p-3" style={tintTile(name)}>
      {name && (
        <span className="flex size-8 items-center justify-center rounded-lg bg-background/70 text-[9px] font-bold" style={tintLabel(name)}>
          {(tileExt(name) || "file").slice(0, 4).toUpperCase()}
        </span>
      )}
      <p dir="auto" className="line-clamp-3 text-start text-xs leading-relaxed text-foreground/80">{item.prompt || item.title}</p>
    </div>
  );
}

// A tutorial: its clip or thumbnail (fetched when the card scrolls near) on a dark tile, Watch on top; its title under.
function VideoCard({ item, category, onWatch }: { item: ExampleItem; category: string; onWatch: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const visible = useNear(ref);
  const entrance = useEntrance(item);

  const yt = youtubeId(item.video || "");
  const isFile = !yt && !vimeoId(item.video || "");
  const watch = () => {
    onWatch();
    track("example_watched", { category, video: item.video });
  };
  return (
    <motion.div
      ref={ref}
      {...entrance}
      className="group relative grid min-w-0 content-start gap-2.5 text-start"
    >
      <button onClick={watch} aria-label={t("watch")} className={cn(TILE, "cursor-pointer")}>
        {visible && (item.thumbnail || yt ? (
          <img src={item.thumbnail || `https://i.ytimg.com/vi/${yt}/hqdefault.jpg`} alt="" className="absolute inset-0 h-full w-full object-cover" />
        ) : isFile ? (
          <video src={item.video || undefined} muted loop autoPlay playsInline preload="metadata" className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <svg viewBox="0 0 24 24" className="size-10 text-muted-foreground/60" fill="currentColor">
            <path d="M8 5.14v13.72c0 .9.98 1.45 1.74.98l10.02-6.86a1.15 1.15 0 000-1.96L9.74 4.16A1.15 1.15 0 008 5.14z" />
          </svg>
        ))}
        <span className="relative rounded-full bg-foreground px-4 py-2 text-sm font-medium text-background shadow-sm transition-opacity group-hover:opacity-90">
          {t("watch")}
        </span>
      </button>
      {titleOf(item) && (
        <button onClick={watch} className="flex min-w-0 cursor-pointer items-start gap-2.5 text-start">
          <CardText item={item} />
        </button>
      )}
    </motion.div>
  );
}

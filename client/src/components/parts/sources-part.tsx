import { useState, useRef, useLayoutEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { t } from "../../lib/i18n";
import { track } from "../../lib/analytics";
import type { Source } from "../../hooks/use-chat";

// A chip is only ever shown for a URL a search actually returned, so the
// favicon is fetched per-domain rather than bundled.
const favicon = (url: string) =>
  `https://www.google.com/s2/favicons?sz=64&domain_url=${encodeURIComponent(url)}`;

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.split("/").pop() || url;
  }
}

const VISIBLE = 4;   // chips shown before the "+n" overflow

function Favicon({ url, className }: { url: string; className: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className={`${className} rounded-full bg-muted-foreground/30`} />;
  return (
    <img
      src={favicon(url)}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className={`${className} rounded-full`}
    />
  );
}

// The hover card. Positioned by the chip, flipped above or below depending on
// room, and clamped inside the viewport so a chip near the edge doesn't push
// the card off-screen.
function Card({ source, anchor }: { source: Source; anchor: DOMRect }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const margin = 8;
    const above = anchor.top - height - margin;
    const top = above > margin ? above : anchor.bottom + margin;
    const left = Math.min(
      Math.max(margin, anchor.left + anchor.width / 2 - width / 2),
      window.innerWidth - width - margin,
    );
    setPos({ top, left });
  }, [anchor]);

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 2 }}
      animate={{ opacity: pos ? 1 : 0, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.12 }}
      dir="auto"
      className="pointer-events-none fixed z-50 w-80 max-w-[calc(100vw-1rem)] rounded-xl border border-border bg-background p-3 shadow-lg"
      style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999 }}
    >
      <div className="flex items-center gap-1.5" dir="ltr">
        <Favicon url={source.url} className="size-4 shrink-0" />
        <span className="truncate text-sm text-muted-foreground">{domainOf(source.url)}</span>
      </div>
      {source.title && (
        <p className="mt-1.5 line-clamp-2 text-sm font-medium leading-snug text-foreground">{source.title}</p>
      )}
      {source.snippet && (
        <p className="mt-1 line-clamp-3 text-sm leading-snug text-muted-foreground">{source.snippet}</p>
      )}
    </motion.div>
  );
}

// Match key for an inline link against a returned result. Scheme and a
// trailing slash differ freely between what the engine returned and what the
// model typed; anything past that is a different page.
export function urlKey(url: string): string {
  try {
    const u = new URL(url);
    return `${u.hostname.replace(/^www\./, "")}${u.pathname.replace(/\/$/, "")}${u.search}`.toLowerCase();
  } catch {
    return url.trim().toLowerCase();
  }
}

export function SourceChip({ source, onOpen }: { source: Source; onOpen?: () => void }) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null);
  const ref = useRef<HTMLAnchorElement>(null);
  const show = () => ref.current && setAnchor(ref.current.getBoundingClientRect());

  return (
    <>
      <a
        ref={ref}
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={onOpen}
        onMouseEnter={show}
        onMouseLeave={() => setAnchor(null)}
        onFocus={show}
        onBlur={() => setAnchor(null)}
        dir="ltr"
        className="inline-flex h-6 max-w-40 items-center gap-1.5 rounded-full bg-secondary py-0 pe-2.5 ps-1.5 text-xs text-muted-foreground no-underline transition-colors hover:bg-secondary/70 hover:text-foreground"
      >
        <Favicon url={source.url} className="size-3.5 shrink-0" />
        <span className="truncate">{domainOf(source.url)}</span>
      </a>
      <AnimatePresence>{anchor && <Card source={source} anchor={anchor} />}</AnimatePresence>
    </>
  );
}

// The sources a single search returned — rendered where the search ran, so a
// turn with several searches shows each one's citations next to its own step.
export function SourcesPart({ sources }: { sources: Source[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!sources.length) return null;

  const hidden = sources.length - VISIBLE;
  const shown = expanded ? sources : sources.slice(0, VISIBLE);

  return (
    <div className="flex flex-wrap items-center gap-1.5 py-1" dir="auto">
      <span className="text-xs text-muted-foreground/70">{t("sources")}</span>
      {shown.map((s, i) => (
        <SourceChip
          key={`${s.url}-${i}`}
          source={s}
          onOpen={() => track("source_opened", { url: s.url, domain: domainOf(s.url), placement: "row" })}
        />
      ))}
      {!expanded && hidden > 0 && (
        <button
          onClick={() => setExpanded(true)}
          dir="ltr"
          className="inline-flex h-6 items-center rounded-full bg-secondary px-2.5 text-xs text-muted-foreground transition-colors hover:bg-secondary/70 hover:text-foreground cursor-pointer"
        >
          +{hidden}
        </button>
      )}
    </div>
  );
}

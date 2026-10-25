import { useEffect, useRef, useState } from "react";
import { FilePart } from "./file-part";
import { cn } from "../../lib/utils";
import { t } from "../../lib/i18n";
import type { Part } from "../../hooks/use-chat";

export const IMAGE_FILE = /\.(png|jpe?g|gif|webp|avif|bmp|svg)$/i;

// A picture in a message: an image part's own address, a workspace file a tool opened (a canvas card), or
// one a tool is still making, held as a frame of its shape. A file keeps the shape it was made in, when known.
type Shot = { src?: string; path?: string; caption?: string; making?: string; label?: string; shape?: string };
const shot = (p: Part): Shot =>
  p.type === "image" ? { src: p.src, caption: p.caption || p.alt }
  : p.picture && p.tool_name !== "Canvas" ? { making: p.picture, label: p.step }
  : { path: p.step, caption: p.step?.split("/").pop(), shape: p.picture };

const dims = (shape?: string) => {
  const [w, h] = (shape || "").split(":").map(Number);
  return w > 0 && h > 0 ? [w, h] : [1, 1];
};
// A picture a tool made, alone in its message, is at most 20rem on its long side: the frame it is made in, and
// the picture that takes its place.
const fit = (shape?: string) => {
  const [w, h] = dims(shape);
  return { aspectRatio: `${w} / ${h}`, width: `${20 * Math.min(1, w / h)}rem` };
};

// The frame a picture is made in: dots over a blur, crossed by a sweep of light in step with the shimmer on its
// words, until the picture takes its place.
export function Making({ shape, label, one }: { shape?: string; label?: string; one?: boolean }) {
  return (
    <div className="relative max-w-full overflow-hidden rounded-xl border border-border bg-secondary"
         style={one ? fit(shape) : { aspectRatio: "1 / 1" }}>
      <div className="absolute -inset-6 opacity-60 blur-2xl"
           style={{ background: "radial-gradient(circle at 25% 30%, rgb(47 107 255 / .35), transparent 55%), radial-gradient(circle at 75% 70%, rgb(255 84 0 / .3), transparent 55%)" }} />
      <div className="dot-shimmer absolute inset-3" />
      <div className="absolute inset-x-0 bottom-0 flex items-center gap-2 bg-gradient-to-t from-background/90 to-transparent px-3 pb-2.5 pt-8 text-xs">
        <span className="text-shimmer shrink-0 font-medium">{t("makingPicture")}</span>
        {label && <span dir="auto" className="min-w-0 truncate text-muted-foreground">{label}</span>}
      </div>
    </div>
  );
}

// The pictures of a message: one at its own size, several in a grid. A file opens in the canvas, as its card did.
export function Gallery({ items, resolve, onOpenFile }: {
  items: Part[];
  resolve?: (path: string) => Promise<string>;   // a workspace file → a URL this page can show
  onOpenFile?: (path: string) => void;
}) {
  const shots = items.map(shot);
  const [urls, setUrls] = useState<Record<string, string>>({});
  // Each file is fetched once, as it arrives — a picture made later doesn't refetch the ones before it.
  const fetched = useRef<Record<string, string>>({});
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; Object.values(fetched.current).forEach((u) => u && URL.revokeObjectURL(u)); }, []);
  const paths = shots.flatMap((s) => (s.path ? [s.path] : [])).join("\n");
  useEffect(() => {
    if (!resolve || !paths) return;
    for (const p of paths.split("\n")) {
      if (p in fetched.current) continue;
      fetched.current[p] = "";
      resolve(p).then((u) => {
        if (!alive.current) return URL.revokeObjectURL(u);
        fetched.current[p] = u;
        setUrls((cur) => ({ ...cur, [p]: u }));
      }).catch(() => {});
    }
  }, [paths, resolve]);

  // A shared chat has no way into the workspace: its files stay cards.
  if (!resolve && shots.some((s) => s.path))
    return <>{shots.map((s, i) => (s.path ? <FilePart key={i} path={s.path} onOpen={onOpenFile} /> : null))}</>;

  const one = shots.length === 1;
  const cols = shots.length === 2 || shots.length === 4 ? "grid-cols-2" : "grid-cols-3";
  return (
    <div className={cn("my-2", one ? "max-w-md" : cn("grid max-w-xl gap-1.5", cols))}>
      {shots.map((s, i) => {
        if (s.making) return <Making key={i} shape={s.making} label={s.label} one={one} />;
        const src = s.src || (s.path ? urls[s.path] : undefined);
        const look = cn("relative block overflow-hidden rounded-xl border border-border bg-secondary", one ? "w-fit max-w-full" : "aspect-square");
        const size = !one ? "size-full object-cover" : s.path ? "block max-h-80 max-w-[min(20rem,100vw_-_3rem)]" : "block max-h-[28rem] max-w-full";
        const picture = src ? <img src={src} alt={s.caption || ""} className={size} />
                            : <span className={cn("block max-w-full animate-pulse", one ? !s.shape && "h-60 w-80" : "size-full")}
                                    style={one && s.shape ? fit(s.shape) : undefined} />;
        if (s.path && onOpenFile)
          return <button key={i} type="button" onClick={() => onOpenFile(s.path!)} aria-label={s.caption} className={cn(look, "cursor-pointer")}>{picture}</button>;
        // An image an app sent keeps its caption under it.
        return <figure key={i} className="m-0"><span className={look}>{picture}</span>
          {one && s.caption && <figcaption dir="auto" className="mt-2 text-center text-sm text-muted-foreground">{s.caption}</figcaption>}</figure>;
      })}
    </div>
  );
}

import { cn } from "../lib/utils";

export interface AppIconSource {
  name: string;
  icon?: string;
  iconSrc?: string;
  letter?: string;
}

// A line icon (an SVG, as the ready-made apps' are): drawn in the text's colour through a mask, so it follows light
// and dark and the tile it sits on. A mask never runs what the file holds.
const lined = (src?: string) => !!src?.startsWith("data:image/svg+xml");
export const Lines = ({ src, className }: { src: string; className?: string }) => {
  const m = `url("${src}") center / contain no-repeat`;
  return <span aria-hidden className={cn("shrink-0 bg-current", className)} style={{ mask: m, WebkitMask: m }} />;
};

// An image if the manifest names one, else its emoji, else the first letter of
// the app's name — so an app always has something to recognise it by.
export function AppIcon({ app, className, textClassName }: {
  app: AppIconSource;
  className?: string;
  textClassName?: string;
}) {
  if (lined(app.iconSrc)) return <Lines src={app.iconSrc!} className={className} />;
  if (app.iconSrc) {
    return (
      <img
        src={app.iconSrc}
        alt=""
        aria-hidden
        className={cn("shrink-0 rounded object-cover", className)}
      />
    );
  }
  const glyph = app.icon || app.letter || [...app.name][0]?.toUpperCase() || "?";
  return (
    <span aria-hidden className={cn("shrink-0 leading-none", textClassName, !app.icon && "font-semibold")}>
      {glyph}
    </span>
  );
}

// An app's face: the agents' own tile (the brand's), black on a light page and white on a dark one, its icon in the
// other colour. A picture fills it.
export function AppTile({ app, className, textClassName }: {
  app: AppIconSource & { slug?: string };
  className?: string;
  textClassName?: string;
}) {
  return (
    <span className={cn("flex shrink-0 items-center justify-center overflow-hidden rounded-[24%] bg-foreground text-background", className)}>
      <AppIcon app={app} className={lined(app.iconSrc) ? "size-[45%]" : "size-full rounded-none"} textClassName={textClassName} />
    </span>
  );
}

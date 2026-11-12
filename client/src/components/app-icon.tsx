import { cn } from "../lib/utils";

export interface AppIconSource {
  name: string;
  icon?: string;
  iconSrc?: string;
  letter?: string;
}

// An image if the manifest names one, else its emoji, else the first letter of
// the app's name — so an app always has something to recognise it by.
export function AppIcon({ app, className, textClassName }: {
  app: AppIconSource;
  className?: string;
  textClassName?: string;
}) {
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

// An app's face as a phone shows it: a squircle in a soft tint of its own, lit from above. The tint comes from the
// app's folder, so a rename keeps it.
const TINTS = [
  "from-amber-50 to-amber-200 dark:from-amber-300/30 dark:to-amber-600/30",
  "from-sky-50 to-sky-200 dark:from-sky-300/30 dark:to-sky-600/30",
  "from-rose-50 to-rose-200 dark:from-rose-300/30 dark:to-rose-600/30",
  "from-violet-50 to-violet-200 dark:from-violet-300/30 dark:to-violet-600/30",
  "from-emerald-50 to-emerald-200 dark:from-emerald-300/30 dark:to-emerald-600/30",
  "from-orange-50 to-orange-200 dark:from-orange-300/30 dark:to-orange-600/30",
  "from-teal-50 to-teal-200 dark:from-teal-300/30 dark:to-teal-600/30",
];

export function AppTile({ app, className, textClassName }: {
  app: AppIconSource & { slug?: string };
  className?: string;
  textClassName?: string;
}) {
  const tint = TINTS[[...(app.slug ?? app.name)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 0) % TINTS.length];
  return (
    <span className={cn(
      "flex shrink-0 items-center justify-center overflow-hidden rounded-[24%] bg-gradient-to-b text-neutral-700 dark:text-neutral-100",
      "shadow-[0_1px_3px_rgba(0,0,0,0.12),inset_0_1px_0_rgba(255,255,255,0.7),inset_0_0_0_0.5px_rgba(0,0,0,0.08)]",
      tint, className,
    )}>
      <AppIcon app={app} className="size-full rounded-none" textClassName={cn("drop-shadow-[0_1px_1px_rgba(0,0,0,0.15)]", textClassName)} />
    </span>
  );
}

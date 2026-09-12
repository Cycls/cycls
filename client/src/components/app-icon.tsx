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

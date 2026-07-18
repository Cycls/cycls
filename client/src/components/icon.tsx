import { cn } from "../lib/utils";

// Stroke-style icons (heroicons-shaped). One-off icons stay inline at their
// call site; only icons used in 2+ places live here.
const ICONS = {
  check:           "M5 13l4 4L19 7",
  x:               "M6 18L18 6M6 6l12 12",
  "chevron-down":  "M19 9l-7 7-7-7",
  "chevron-right": "M9 5l7 7-7 7",
  "chevron-left":  "M15 19l-7-7 7-7",
  moon:            "M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z",
  copy:            "M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z",
  list:            "M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12",
  upload:          "M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5",
  paperclip:       "M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48",
  folder:          "M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.06-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z",
  link:            "M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1",
  expand:          "M15 3.75h5.25V9m0-5.25L13.5 10.5M9 20.25H3.75V15m0 5.25L10.5 13.5",
  collapse:        "M9.75 14.25H4.5m5.25 0v5.25m0-5.25L3.75 20.25M14.25 9.75h5.25m-5.25 0V4.5m0 5.25l6-6",
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, className = "size-4", strokeWidth = 2 }: { name: IconName; className?: string; strokeWidth?: number }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={strokeWidth} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d={ICONS[name]} />
    </svg>
  );
}

export function Spinner({ className = "size-4" }: { className?: string }) {
  return (
    <svg className={cn("animate-spin", className)} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

const ICON_BTN = "text-muted-foreground hover:text-foreground hover:bg-secondary/80 rounded-lg p-2 transition-colors cursor-pointer";

export function IconButton({ name, onClick, label, className, strokeWidth }: { name: IconName; onClick: () => void; label: string; className?: string; strokeWidth?: number }) {
  return (
    <button onClick={onClick} aria-label={label} className={cn(ICON_BTN, className)}>
      <Icon name={name} strokeWidth={strokeWidth} />
    </button>
  );
}

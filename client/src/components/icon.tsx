import { cn } from "../lib/utils";

// Stroke-style icons (heroicons-shaped). One-off icons stay inline at their
// call site; only icons used in 2+ places live here.
const ICONS = {
  check:           "M5 13l4 4L19 7",
  doc:             "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  pencil:          "M16.862 4.487l1.688-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125",
  terminal:        "M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  database:        "M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m-16 0c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 12c0 2.21 3.582 4 8 4s8-1.79 8-4",
  star:            "M 12 0 L 13.11 3.78 C 14.09 7.21 16.79 9.9 20.22 10.9 L 24 11.98 L 20.22 13.07 C 16.79 14.07 14.09 16.76 13.11 20.19 L 12 24 L 10.89 20.22 C 9.91 16.79 7.21 14.1 3.78 13.11 L 0 12.02 L 3.78 10.93 C 7.21 9.93 9.91 7.24 10.89 3.81 L 12 0 Z",
  globe:           "M12 21a9 9 0 100-18 9 9 0 000 18zm0 0c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3s-4.5 4.03-4.5 9 2.015 9 4.5 9zM3.6 9h16.8M3.6 15h16.8",
  hand:            "M10.05 4.575a1.575 1.575 0 10-3.15 0v3m3.15-3v-1.5a1.575 1.575 0 013.15 0v1.5m-3.15 0l.075 5.925m3.075.75V4.575m0 0a1.575 1.575 0 013.15 0V15M6.9 7.575a1.575 1.575 0 10-3.15 0v8.175a6.75 6.75 0 006.75 6.75h2.018a5.25 5.25 0 003.712-1.538l1.732-1.732a5.25 5.25 0 001.538-3.712l.003-2.024a.668.668 0 01.198-.471 1.575 1.575 0 10-2.228-2.228 3.818 3.818 0 00-1.12 2.687M6.9 7.575V12m6.27 4.318A4.49 4.49 0 0116.35 15m.002 0h-.002",
  forward:         "M3 8.689c0-.864.933-1.406 1.683-.977l7.108 4.061a1.125 1.125 0 010 1.954l-7.108 4.061A1.125 1.125 0 013 16.811V8.69zM12.75 8.689c0-.864.933-1.406 1.683-.977l7.108 4.061a1.125 1.125 0 010 1.954l-7.108 4.061a1.125 1.125 0 01-1.683-.977V8.69z",
  x:               "M6 18L18 6M6 6l12 12",
  "chevron-down":  "M19 9l-7 7-7-7",
  "chevron-right": "M9 5l7 7-7 7",
  "chevron-left":  "M15 19l-7-7 7-7",
  moon:            "M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z",
  copy:            "M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z",
  list:            "M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12",
  upload:          "M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5",
  plus:            "M12 4.5v15m7.5-7.5h-15",
  "arrow-right":   "M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3",
  "arrow-up-right": "M7 17 17 7M8 7h9v9",
  search:          "M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z",
  paperclip:       "M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48",
  folder:          "M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.06-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z",
  link:            "M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1",
  expand:          "M15 3.75h5.25V9m0-5.25L13.5 10.5M9 20.25H3.75V15m0 5.25L10.5 13.5",
  grid:            "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  collapse:        "M9.75 14.25H4.5m5.25 0v5.25m0-5.25L3.75 20.25M14.25 9.75h5.25m-5.25 0V4.5m0 5.25l6-6",
  refresh:         "M16.023 9.348h4.992V4.356m0 4.992l-3.181-3.183a8.25 8.25 0 00-13.803 3.7M2.985 14.652H7.977v4.992m-4.992-4.992l3.181 3.183a8.25 8.25 0 0013.803-3.7",
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

import type { ComponentProps } from "react";
import { Badge } from "../ui/badge";
import { cn } from "../lib/utils";

export type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";
// Whole class names only: Tailwind cannot see a class assembled from a template string.
const TONES: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  primary: "bg-primary-soft text-primary",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-destructive-soft text-destructive",
  info: "bg-info-soft text-info",
};
export const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-muted-foreground", primary: "text-primary", success: "text-success", warning: "text-warning", danger: "text-destructive", info: "text-info",
};

/** shadcn Badge with the kit's status tones (soft background + strong text, ≥ 4.5:1).
 *  dir="auto": a label from data (an English category in the Arabic UI) keeps its own order. */
export function StatusBadge({ tone = "neutral", className, ...p }: ComponentProps<typeof Badge> & { tone?: Tone }) {
  return <Badge variant="secondary" dir="auto" className={cn("max-w-full truncate", TONES[tone], className)} {...p} />;
}

// Small text primitives for mixed Arabic/Latin data: AutoText (dir="auto" for user or agent
// text), Ltr (formulas, codes), Amount (money that never truncates), UnreadableValue (a
// field the app could not read, shown instead of a silent default) and UnreadableNotice.
import type { HTMLAttributes, ReactNode } from "react";
import { TriangleAlert } from "lucide-react";
import { useLang } from "../i18n";
import { currencyUnit, formatCompactSAR, formatSAR, type MoneyOptions } from "../format";
import { rawText } from "../parse";
import { useKitT } from "../strings";
import { cn } from "../lib/utils";

/** Text of unknown language (a title, a name, a note the person or the agent wrote):
 *  dir="auto", so an Arabic note in the English UI keeps its punctuation at the right end,
 *  and an English title in the Arabic UI is not cut at its start. Inline by default. */
export function AutoText({ as: C = "span", ...p }: { as?: "span" | "p" | "div" | "h2" | "h3" | "h4" | "li" | "dd" | "td" } & Omit<HTMLAttributes<HTMLElement>, "dir">) {
  return <C dir="auto" {...p} />;
}

/** Left-to-right, isolated: 1080×1920, 9:16, T+2, ×1.00, +13.31%, 10:00–15:00, file names. */
export function Ltr({ className, children, num = true }: { className?: string; children: ReactNode; num?: boolean }) {
  return <bdi dir="ltr" className={cn(num && "num-ltr", className)}>{children}</bdi>;
}

/** Money in a stat card or a table: the unit is its own smaller span, nothing truncates,
 *  and `compact` ("auto" = below the sm breakpoint only) switches 1,330,000 to
 *  "1.33 مليون ر.س" / "SAR 1.33M" so it fits a 360 px card. */
export function Amount({ value, compact = "auto", className, unitClassName, ...o }: {
  value: number; compact?: boolean | "auto"; className?: string; unitClassName?: string;
} & Omit<MoneyOptions, "isolate" | "currencyAs">) {
  const { lang } = useLang();
  const full = formatSAR(value, lang, { ...o, currencyAs: "none" });
  const short = formatCompactSAR(value, lang, { ...o, currencyAs: "none" });
  const unit = currencyUnit(lang, o.currency ?? "SAR");
  const u = <span className={cn("text-[0.7em] font-medium text-muted-foreground", unitClassName)}>{unit}</span>;
  const n = (s: string, cls?: string) => <span className={cn("whitespace-nowrap", cls)}>{s}</span>;
  return (
    <bdi dir={lang === "ar" ? "rtl" : "ltr"} className={cn("num inline-flex flex-wrap items-baseline gap-x-1 whitespace-nowrap", className)}
      title={formatSAR(value, lang, o)} data-amount={value}>
      {lang === "en" && u}
      {compact === true ? n(short) : compact === false ? n(full) : <>{n(short, "sm:hidden")}{n(full, "hidden sm:inline")}</>}
      {lang === "ar" && u}
    </bdi>
  );
}

/** A field whose stored value could not be read (parseISODate / parseAmount / parseEnum
 *  flagged it): a warning chip "Unreadable value" with the raw value in its tooltip, shown
 *  where the value would be. Never replace it by a default that looks real. */
export function UnreadableValue({ raw, field, reason, className }: {
  raw: unknown; field?: string;
  /** why it could not be read, e.g. «اليوم والشهر ملتبسان» — shown under the chip */
  reason?: ReactNode; className?: string;
}) {
  const t = useKitT();
  const shown = rawText(raw);
  const hint = shown ? t("unreadableHint", { raw: `«${shown}»` }) : t("unreadableValue");
  // cycls-default-apps: a native title instead of a Radix Tooltip — the popper it pulled in
  // cost ~65 KB in every app that flags a value.
  return (
    <span data-unreadable={field ?? ""} title={hint}
      className={cn("inline-flex max-w-full flex-col items-start gap-0.5 align-middle", className)}>
      <span tabIndex={0} aria-label={`${t("unreadableValue")}: ${hint}`}
        className="inline-flex max-w-full items-center gap-1 rounded-md bg-warning-soft px-1.5 py-0.5 text-[11px] font-medium text-warning">
        <TriangleAlert aria-hidden className="size-3 shrink-0" />
        <span className="min-w-0 truncate">{t("unreadableValue")}</span>
        {shown && <bdi dir="ltr" className="min-w-0 max-w-[10rem] truncate font-normal opacity-80">{rawText(raw, 24)}</bdi>}
      </span>
      {reason && <span className="text-[11px] leading-snug text-muted-foreground">{reason}</span>}
    </span>
  );
}

/** "3 rows could not be read" — one muted line (useCollection's `.invalid`), nothing when 0. */
export function UnreadableNotice({ count, className }: { count: number; className?: string }) {
  const t = useKitT();
  if (!count) return null;
  return (
    <p role="status" data-unreadable-rows={count} className={cn("flex items-center gap-1.5 text-xs text-warning", className)}>
      <TriangleAlert aria-hidden className="size-3.5 shrink-0" />{t("unreadableRows", { count })}
    </p>
  );
}

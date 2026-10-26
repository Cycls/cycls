import { useMemo, useState, useId, type ComponentProps } from "react";
import { arSA, enUS } from "react-day-picker/locale";
import { CalendarDays, ChevronDown } from "lucide-react";
import { Calendar, CalendarDayButton } from "../ui/calendar";
import { Button } from "../ui/button";
import { useLang } from "../i18n";
import { useKitT } from "../strings";
import { HIJRI_MONTHS, HIJRI_SUPPORTED, addBusinessDays, isWeekend, toHijri, todayRiyadh, type ISODate } from "../saudi-time";
import { cn } from "../lib/utils";

const fromDate = (d: Date): ISODate => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const toDate = (iso: ISODate): Date => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };

/** A date field showing the gregorian AND the Umm al-Qura date, on shadcn's Calendar.
 *  Opens inline (no popover portal: it works inside a Drawer and never overflows 360 px).
 *  Sunday first, Friday/Saturday muted, `holidays` marked; `quickDays` adds
 *  "+N business days" chips. Cells are 40 px. */
export function DatePicker({ value, onChange, holidays, quickDays = [1, 3, 5, 10], label, allowClear = true, className }: {
  value: ISODate | null | undefined;
  onChange: (v: ISODate | null) => void;
  holidays?: ReadonlySet<ISODate>;
  quickDays?: number[];
  label?: string;
  allowClear?: boolean;
  className?: string;
}) {
  const { lang, dir, dual, num } = useLang();
  const t = useKitT();
  const [open, setOpen] = useState(false);
  const panel = useId();
  const today = todayRiyadh();
  const [month, setMonth] = useState<Date>(() => toDate(value || today));
  const hol = holidays ?? new Set<ISODate>();

  // With captionLayout="dropdown" DayPicker shows month/year <select>s and uses formatCaption
  // only for its screen-reader status line, so the Hijri span is drawn under the dropdowns
  // (MonthCaption below) and also kept in the announced caption.
  const hijriSpan = useMemo(() => (m: Date): string => {
    if (!HIJRI_SUPPORTED) return "";
    const a = toHijri(fromDate(new Date(m.getFullYear(), m.getMonth(), 1)));
    const b = toHijri(fromDate(new Date(m.getFullYear(), m.getMonth() + 1, 0)));
    const n = HIJRI_MONTHS[lang];
    return a.m === b.m ? `${n[a.m - 1]} ${a.y}` : a.y === b.y ? `${n[a.m - 1]} – ${n[b.m - 1]} ${b.y}` : `${n[a.m - 1]} ${a.y} – ${n[b.m - 1]} ${b.y}`;
  }, [lang]);
  const formatters = useMemo(() => ({
    formatCaption: (m: Date) => {
      const g = new Intl.DateTimeFormat(lang === "ar" ? "ar-SA-u-ca-gregory-nu-latn" : "en-GB-u-ca-gregory", { month: "long", year: "numeric" }).format(m);
      const h = hijriSpan(m);
      return h ? `${g} · ${h}` : g;
    },
  }), [lang, hijriSpan]);
  const MonthCaption = useMemo(() => function MonthCaption({ calendarMonth, displayIndex: _i, children, ...div }: ComponentProps<"div"> & { calendarMonth: { date: Date }; displayIndex: number }) {
    const h = hijriSpan(calendarMonth.date);
    return (
      <div {...div}>
        {children}
        {h && <span aria-hidden data-hijri-caption className="num text-xs text-muted-foreground text-balance">{h}</span>}
      </div>
    );
  }, [hijriSpan]);

  return (
    <div className={cn("min-w-0", className)}>
      <Button type="button" variant="outline" aria-expanded={open} aria-controls={panel} aria-label={label ? `${label}: ${value ? dual(value) : t("pickDate")}` : undefined}
        onClick={() => { setOpen((o) => !o); if (value) setMonth(toDate(value)); }}
        className="h-auto min-h-10 w-full justify-start whitespace-normal px-3 py-2 text-start font-normal">
        <CalendarDays aria-hidden className="text-muted-foreground" />
        <span className={cn("min-w-0 flex-1 break-words", !value && "text-muted-foreground")}>{value ? dual(value, { weekday: true, style: "short" }) : t("pickDate")}</span>
        <ChevronDown aria-hidden className={cn("text-muted-foreground transition-transform", open && "rotate-180")} />
      </Button>
      {open && (
        <div id={panel} className="mt-2 rounded-lg border bg-card p-2">
          {quickDays.length > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-1.5" role="group" aria-label={t("businessDaysFromToday")}>
              <span className="w-full text-xs text-muted-foreground">{t("businessDaysFromToday")}</span>
              {quickDays.map((n) => {
                const d = addBusinessDays(today, n, hol);
                return (
                  <Button key={n} type="button" variant={value === d ? "default" : "outline"} className="num h-10 min-w-10"
                    onClick={() => { onChange(d); setMonth(toDate(d)); setOpen(false); }}>+{num(n)}</Button>
                );
              })}
            </div>
          )}
          <Calendar
            mode="single"
            dir={dir}
            locale={lang === "ar" ? arSA : enUS}
            numerals="latn"
            weekStartsOn={0}
            month={month}
            onMonthChange={setMonth}
            // cycls-default-apps: month/year dropdowns — a trigger date years back took dozens of clicks
            captionLayout="dropdown"
            startMonth={new Date(1990, 0)}
            endMonth={new Date(new Date().getFullYear() + 15, 11)}
            selected={value ? toDate(value) : undefined}
            onSelect={(d: Date | undefined) => { if (d) { onChange(fromDate(d)); setOpen(false); } }}
            formatters={formatters}
            labels={{ labelPrevious: () => t("prevMonth"), labelNext: () => t("nextMonth") }}
            modifiers={{ weekend: (d: Date) => isWeekend(fromDate(d)), holiday: (d: Date) => hol.has(fromDate(d)) }}
            modifiersClassNames={{ weekend: "text-muted-foreground", holiday: "[&_button]:bg-warning-soft [&_button]:text-warning" }}
            className="w-full bg-transparent p-1 [--cell-size:--spacing(10)]"
            // the nav (prev/next) sits absolutely on the first row; the dropdowns share that row
            // between the two buttons and the Hijri span goes on a second line
            classNames={{ root: "w-full", month_caption: "flex min-h-(--cell-size) w-full flex-col items-center justify-start gap-1 px-(--cell-size) text-center" }}
            components={{ DayButton: DualDayButton, MonthCaption }}
          />
          <div className="mt-1 flex items-center justify-between gap-2 border-t pt-2">
            <Button type="button" variant="ghost" className="text-primary" onClick={() => { onChange(today); setOpen(false); }}>{t("today")}</Button>
            {allowClear && value && <Button type="button" variant="ghost" className="text-muted-foreground" onClick={() => { onChange(null); setOpen(false); }}>{t("clear")}</Button>}
          </div>
        </div>
      )}
    </div>
  );
}

/** shadcn's CalendarDayButton with the hijri day under the gregorian one. */
function DualDayButton(props: ComponentProps<typeof CalendarDayButton>) {
  const h = HIJRI_SUPPORTED ? toHijri(fromDate(props.day.date)).d : null;
  return (
    <CalendarDayButton {...props}>
      <span className="num text-sm! opacity-100!">{props.day.date.getDate()}</span>
      {h !== null && <span className="num text-[11px]">{h}</span>}
    </CalendarDayButton>
  );
}

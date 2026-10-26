// "Import from my email": the app cannot read mail (no network, no connector call from the
// frame), so it asks the agent, which reads the mailbox through a Gmail/Outlook connector IF
// IT HAS ONE and writes one row per item with `source: {kind: "email", id, from, date, subject}`.
// On 2026-10-21 none of the 7 agents has a mail connector (data-contracts critique): the rules
// tell the agent to say so and ask the person to paste the emails; such rows get no `source`.
// The app builds the prompt (key prefix, row shape, what to skip); this component owns the
// period/filter sheet, the ask-or-copy fallback and the ✉ badge. decisions-lead.md item 14.
import { useMemo, useState } from "react";
import { Copy, Mail, Send } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { ASK_MAX, askAgent, copyText, features, useCycls, useViewState } from "../cycls";
import { lastDaysPhrase, plain, useLang, useT, type Lang } from "../i18n";
import { addDays, isISODate, todayRiyadh, type ISODate } from "../saudi-time";
import { cn } from "../lib/utils";
import { ResponsiveSheet } from "./responsive-sheet";
import { Segmented } from "./segmented";
import { Field } from "./field";

/** Where an imported row came from. `id` is the mail provider's message id: the dedupe key. */
export interface EmailSource { kind: "email"; id: string; from?: string; date?: string; subject?: string }
export const isEmailSource = (v: unknown): v is EmailSource =>
  !!v && typeof v === "object" && (v as EmailSource).kind === "email" && typeof (v as EmailSource).id === "string";

export const EMAIL_PERIODS = [7, 30, 90] as const;
export type EmailPeriod = (typeof EMAIL_PERIODS)[number];
export interface EmailImportQuery {
  days: EmailPeriod;
  /** sender or keyword typed by the person, trimmed; "" = none */
  filter: string;
  lang: Lang;
  today: ISODate;
  /** today − days (Riyadh) */
  since: ISODate;
  /** "آخر 7 أيام" / "the last 7 days": grammatical in Arabic for every period. Use it
   *  instead of writing `${days} يومًا` (which gives «7 يومًا»). */
  period: string;
}

const S = {
  en: {
    button: "Import from email", title: "Import from my email",
    body: "The agent reads your mailbox if a mail connector (Gmail or Outlook) is set up for it, and adds one row per item. Without one, it will ask you to paste the emails in the chat. This app cannot read mail itself.",
    period: "Period", days: "{count} days", filter: "Only from / containing (optional)",
    filterHint: "A sender (name or @domain) or a keyword, e.g. invoice",
    prompt: "What the agent will be asked", ask: "Ask the agent", copy: "Copy the prompt",
    asked: "Prompt placed in the chat — press send", copied: "Prompt copied — paste it in the chat",
    copyFailed: "Copy it by hand: select the text", cancel: "Cancel",
    note: "Rows imported from email carry ✉ with the sender, date and subject. Nothing is linked or fetched.",
    badge: "From email", from: "From", date: "Date", subject: "Subject",
  },
  ar: {
    button: "استيراد من البريد", title: "استيراد من بريدي",
    body: "يقرأ الوكيل صندوق بريدك إن كان لديه موصّل بريد (Gmail أو Outlook)، ويضيف صفًّا لكل عنصر. وإن لم يكن لديه موصّل فسيطلب منك لصق الرسائل في المحادثة. هذا التطبيق لا يقرأ البريد بنفسه.",
    period: "المدة", days: { zero: "{count} يوم", one: "يوم واحد", two: "يومان", few: "{count} أيام", many: "{count} يومًا", other: "{count} يوم" },
    filter: "من مرسل معيّن أو يحتوي على كلمة (اختياري)",
    filterHint: "مرسل (اسم أو ‎@نطاق) أو كلمة، مثل: فاتورة",
    prompt: "ما سيُطلب من الوكيل", ask: "اطلب من الوكيل", copy: "نسخ التعليمة",
    asked: "وُضعت التعليمة في المحادثة — اضغط إرسال", copied: "نُسخت التعليمة — الصقها في المحادثة",
    copyFailed: "انسخ النص يدويًا بتحديده", cancel: "إلغاء",
    note: "الصفوف المستوردة من البريد تحمل ✉ مع المرسل والتاريخ والموضوع، دون أي رابط أو تنزيل.",
    badge: "من البريد", from: "من", date: "التاريخ", subject: "الموضوع",
  },
};

/** The sentences every import prompt ends with (dedupe, skip, NO CONNECTOR), in `lang`.
 *  Not longer than the 2026-10-21 version, so every app prompt stays ≤ 1000 characters. */
export function emailImportRules(lang: Lang, skip?: string): string {
  return lang === "ar"
    ? `ضع لكل صف source = {kind:"email", id:<معرّف الرسالة>, from, date, subject}، وتخطَّ رسالة لها صف بنفس source.id. تجاهل النشرات والإعلانات والإشعارات الآلية${skip ? ` و${skip}` : ""}. لا تخترع حقلًا. إن لم يكن لديك موصّل بريد (Gmail أو Outlook) فقل ذلك صراحةً واطلب مني لصق الرسائل هنا، ودوّن ما ألصقه دون source. في النهاية اذكر عدد ما أُضيف وما تُخطّي.`
    : `Set source = {kind:"email", id:<message id>, from, date, subject} on each row; skip an email whose source.id is already on a row. Skip newsletters, marketing and automated notices${skip ? `, and ${skip}` : ""}. Never invent a field. If you have no mail connector (Gmail or Outlook), say so plainly and ask me to paste the emails here; log those without source. End with how many rows you added and skipped.`;
}

/** A button (toolbar-sized: the explanation lives in the sheet, not above the data). It
 *  opens a sheet (period 7/30/90, optional filter), then `cycls.ask(buildPrompt(q))` on a
 *  live branch host, else copies the prompt. `variant="block"` adds the muted note under it. */
export function EmailImport({ buildPrompt, className, stateKey = "mailin", variant = "button", open: openProp, onOpenChange, compact }: {
  buildPrompt: (q: EmailImportQuery) => string;
  className?: string;
  stateKey?: string;
  /** "none": no trigger of its own — open it from a menu item with `open` / `onOpenChange` */
  variant?: "button" | "block" | "none";
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** hide the "(30 days)" part of the button below 640 px */
  compact?: boolean;
}) {
  const t = useT(S);
  const { lang } = useLang();
  const { mode } = useCycls();
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const setOpen = (o: boolean) => { setOpenState(o); onOpenChange?.(o); };
  const [days, setDays] = useViewState<EmailPeriod>(`kit:${stateKey}-days`, 30);
  const [filter, setFilter] = useViewState(`kit:${stateKey}-filter`, "");
  const [manual, setManual] = useState(false);
  const canAsk = mode === "live" && features.ask;
  const text = useMemo(() => {
    const today = todayRiyadh();
    return plain(buildPrompt({ days, filter: filter.trim(), lang, today, since: addDays(today, -days), period: plain(lastDaysPhrase(days, lang)) })).slice(0, ASK_MAX);
  }, [buildPrompt, days, filter, lang]);

  async function go() {
    if (canAsk && (await askAgent(text))) { toast.success(t("asked")); setOpen(false); return; }
    if (copyText(text)) { toast.success(t("copied")); return; }
    setManual(true);
    toast.info(t("copyFailed"));
  }

  return (
    <div className={cn("flex min-w-0 flex-col items-start gap-1", className)}>
      {variant !== "none" && <Button variant="outline" onClick={() => { setManual(false); setOpen(true); }}>
        <Mail />{t("button")}<span className={cn("num text-muted-foreground", compact && "max-sm:hidden")}>({t("days", { count: days })})</span>
      </Button>}
      {variant === "block" && <p className="text-xs text-muted-foreground">{t("note")}</p>}
      <ResponsiveSheet open={open} onOpenChange={setOpen} title={t("title")} description={t("body")}
        footer={<>
          <Button variant="outline" onClick={() => setOpen(false)}>{t("cancel")}</Button>
          <Button onClick={go}>{canAsk ? <Send className="rtl:-scale-x-100" /> : <Copy />}{canAsk ? t("ask") : t("copy")}</Button>
        </>}>
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">{t("note")}</p>
          <div className="space-y-2">
            <p className="text-sm font-medium">{t("period")}</p>
            <Segmented<string> label={t("period")} value={String(days)} onChange={(v) => setDays(Number(v) as EmailPeriod)}
              options={EMAIL_PERIODS.map((d) => ({ value: String(d), label: <span className="num">{t("days", { count: d })}</span> }))} />
          </div>
          <Field label={t("filter")} hint={t("filterHint")}>
            {(id, desc) => <Input id={id} aria-describedby={desc} value={filter} maxLength={40} onChange={(e) => setFilter(e.target.value)} autoComplete="off" />}
          </Field>
          <section className="space-y-1.5">
            <h4 className="text-xs font-medium text-muted-foreground">{t("prompt")}</h4>
            {manual
              ? <textarea readOnly value={text} rows={8} onFocus={(e) => e.currentTarget.select()} autoFocus aria-label={t("prompt")}
                  className="w-full rounded-lg border bg-muted p-2 text-sm" />
              : <p className="select-text whitespace-pre-wrap break-words rounded-lg bg-muted px-3 py-2 text-xs leading-5" data-email-prompt>{text}</p>}
          </section>
        </div>
      </ResponsiveSheet>
    </div>
  );
}

/** ✉ + sender (compact: cards and table cells), or sender / date / subject (detail). Plain
 *  text: no mailto, no link, nothing fetched. */
export function EmailSourceBadge({ source, detail, className }: { source: EmailSource; detail?: boolean; className?: string }) {
  const t = useT(S);
  const { date } = useLang();
  const day = source.date && isISODate(source.date.slice(0, 10)) ? date(source.date.slice(0, 10) as ISODate, { style: "short" }) : source.date;
  const full = [source.from, day, source.subject].filter(Boolean).join(" · ");
  if (detail) {
    return (
      <div className={cn("min-w-0 rounded-lg border bg-muted/50 px-3 py-2 text-xs", className)} data-email-source={source.id}>
        <p className="mb-1 flex items-center gap-1.5 font-medium"><span aria-hidden>✉</span>{t("badge")}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-muted-foreground">
          {source.from && <><dt>{t("from")}</dt><dd className="min-w-0 break-words text-foreground" dir="auto">{source.from}</dd></>}
          {day && <><dt>{t("date")}</dt><dd className="num min-w-0">{day}</dd></>}
          {source.subject && <><dt>{t("subject")}</dt><dd className="min-w-0 break-words text-foreground" dir="auto">{source.subject}</dd></>}
        </dl>
      </div>
    );
  }
  return (
    <span className={cn("inline-flex min-w-0 max-w-full items-center gap-1 rounded-md bg-info-soft px-1.5 py-0.5 text-[11px] text-info", className)}
      title={full || t("badge")} aria-label={`${t("badge")}: ${full}`} data-email-source={source.id}>
      <span aria-hidden>✉</span><span className="min-w-0 truncate" dir="auto">{source.from?.replace(/\s*<[^>]*>\s*$/, "") || source.from || t("badge")}</span>
    </span>
  );
}

// Text helpers with NO imports (node --test runs this file directly): bidi isolation,
// plural/case selection, counted nouns, agent names, numbers, percent and currency.
// i18n.ts re-exports everything here; apps import from "./kit/i18n".
//
// BIDI. Arabic UI text is a right-to-left paragraph. A value with no strong letter of its
// own (2026-10-21, T+2, 1080×1920, 10:00–15:00, +13.31%, ≥ 70) is reordered by the Unicode
// bidi algorithm inside it: «تحققت في 2026-10-21» renders "21-10-2026". The fix is an
// isolate around the value: FSI (U+2068) … PDI (U+2069) takes the value's own first strong
// direction, and LTR when it has none, so the value keeps its order and does not reorder
// the sentence around it. LRI (U+2066) forces LTR (codes, file names starting in Arabic).
// The isolate characters are invisible; plain() strips them for chat prompts, copies and
// files (askAgent, copyText and saveFile already do).

export type Lang = "ar" | "en";

export const LRI = "⁦", RLI = "⁧", FSI = "⁨", PDI = "⁩";
const ISOLATES_RE = /[⁦-⁩]/g;
/** Arabic letters, marks, tatweel, Arabic punctuation used inside words (no digits). */
const ARABIC_WORD_RE = /^[؀-ٟٮ-ۓە-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿\s‌‍«»]*$/;
const RTL_RE = /[֐-ࣿיִ-﷿ﹰ-﻿]/;

/** Values that display correctly inside Arabic text WITHOUT an isolate, so none is added
 *  (fewer invisible characters in copies and in text-matching tests): a plain number with
 *  "," "." "/" ":" separators ("5", "1,250.50", "21/10/2026", "10:30"), or Latin words
 *  ("USD", "Najiz Portal"). Signs, %, ×, dashes, brackets, ISO dates, "T+2" are isolated. */
const SAFE_IN_ARABIC_RE = /^(?:[0-9٠-٩۰-۹]+(?:[.,/:٫٬][0-9٠-٩۰-۹]+)*|[A-Za-z]+(?: [A-Za-z]+)*)$/;

/** Removes the isolate controls (U+2066–2069) from a string: for prompts, copies, files, data. */
export function plain(s: string): string { return s.replace(ISOLATES_RE, ""); }

/** FSI…PDI around `v` when it needs it in `lang`:
 *  - ar: unless `v` is only Arabic words (those keep their shaping and need nothing), a
 *    plain number or Latin words (SAFE_IN_ARABIC_RE),
 *  - en: when `v` contains right-to-left letters.
 *  Already isolated values are returned as they are. */
export function isolate(v: string, lang: Lang): string {
  if (!v || v.charCodeAt(0) >= 0x2066 && v.charCodeAt(0) <= 0x2068) return v;
  if (lang === "ar" ? ARABIC_WORD_RE.test(v) || SAFE_IN_ARABIC_RE.test(v) : !RTL_RE.test(v)) return v;
  return FSI + v + PDI;
}
// A value and the symbols glued to it form ONE token, isolated as a whole: "{w}×{h}",
// "T+{n}", "{pct}%", "{from}–{to}", "≥{n}". Isolating the value alone would leave "%" or
// "×" outside, where the Arabic paragraph moves them to the wrong side ("%42", "1920×1080").
// The token stops at spaces, at Arabic letters ("لـ{unit}" keeps «لـ» outside) and at a
// sentence-ending . , : ; ! ? that is followed by a space or the end.
const OPEN = "", CLOSE = "";
const LEFT_GLUE = /[0-9A-Za-z+\-−±#@$€£×~≈<>≤≥=٠-٩۰-۹]/;
const RIGHT_GLUE = /[0-9A-Za-z%٪+\-−–—×÷/:.,°#*^=~±‰'_٠-٩۰-۹٫٬]/;
const END_PUNCT = /[.,:;!?]/;

/** Replaces {name} in `tpl` with `vars` (numbers through formatNumber) and bidi-isolates
 *  each value with the symbols glued to it (see above). `raw: true` → no isolates (files,
 *  stored data). Unknown placeholders stay as {name}. The reserved `case` var is ignored. */
export function interpolate(tpl: string, vars: Record<string, string | number>, lang: Lang, o: { raw?: boolean } = {}): string {
  const marked = tpl.replace(/\{(\w+)\}/g, (m, k) => {
    const v = vars[k];
    if (v === undefined) return m;
    const text = plain(typeof v === "number" ? formatNumber(v, lang) : String(v));
    return o.raw ? text : lang === "ar" ? OPEN + text + CLOSE : isolate(text, lang);
  });
  if (o.raw || lang !== "ar" || !marked.includes(OPEN)) return marked;
  let out = "", i = 0;
  while (i < marked.length) {
    const a = marked.indexOf(OPEN, i);
    if (a < 0) { out += marked.slice(i); break; }
    let start = a;
    // also across . : / _ inside a Latin run ("system_prompt.md:{line}", "event/{id}"), never after Arabic ("رقم:{n}")
    while (start > i && (LEFT_GLUE.test(marked[start - 1]) || (/[.:/_]/.test(marked[start - 1]) && start - 2 >= i && /[0-9A-Za-z]/.test(marked[start - 2])))) start--;
    out += marked.slice(i, start);
    let j = a;
    for (;;) {
      j = marked.indexOf(CLOSE, j) + 1;
      let k = j;
      while (k < marked.length && RIGHT_GLUE.test(marked[k])) k++;
      if (marked[k] === OPEN) { j = k; continue; }
      while (k > j && END_PUNCT.test(marked[k - 1]) && (k === marked.length || /\s/.test(marked[k]))) k--;
      j = k;
      break;
    }
    out += isolate(marked.slice(start, j).replace(/[]/g, ""), lang);
    i = j;
  }
  return out;
}

/** Always left-to-right: LRI…PDI. Codes, file names, keys, formulas (1080×1920, T+2). */
export function ltr(v: string | number): string { return LRI + plain(String(v)) + PDI; }

// ---- plurals and grammatical case ---------------------------------------------------

export type PluralCategory = "zero" | "one" | "two" | "few" | "many" | "other";
/** "gen" = after a preposition or in an idafa (قبل يومين، بعد يومي عمل); "acc" = object.
 *  Only the forms that differ need a variant: the dual (يومان → يومين) and sound
 *  masculine plurals. A missing variant falls back to the plain (nominative) form. */
export type GrammaticalCase = "nom" | "gen" | "acc";
/** Plural forms keyed by Intl.PluralRules category, plus optional case variants
 *  (`two_gen`, `other_acc`, …). `other` is required. Templates may contain {count}. */
export type PluralForms = Partial<Record<PluralCategory | `${PluralCategory}_gen` | `${PluralCategory}_acc`, string>> & { other: string };

const PR: Record<Lang, Intl.PluralRules> = { ar: new Intl.PluralRules("ar"), en: new Intl.PluralRules("en") };
export function pluralCategory(n: number, lang: Lang): PluralCategory { return PR[lang].select(n) as PluralCategory; }

/** The template for `n` in `lang` and `grammaticalCase`, from plural forms. */
export function selectForm(forms: PluralForms, n: number, lang: Lang, grammaticalCase: GrammaticalCase = "nom"): string {
  const cat = pluralCategory(n, lang);
  const f = forms as Record<string, string | undefined>;
  if (grammaticalCase !== "nom") {
    const v = f[`${cat}_${grammaticalCase}`];
    if (v !== undefined) return v;
    if (f[cat] === undefined && f[`other_${grammaticalCase}`] !== undefined) return f[`other_${grammaticalCase}`]!;
  }
  return f[cat] ?? forms.other;
}

let arabicDigits = false;
/** Arabic-Indic digits (٠-٩) in Arabic. Default false: Latin digits, as Saudi business
 *  documents, invoices (ZATCA) and banking UIs use them. */
export function setArabicDigits(on: boolean) { arabicDigits = on; }
export function usesArabicDigits() { return arabicDigits; }
const numLocale = (lang: Lang) => (lang === "ar" ? (arabicDigits ? "ar-SA-u-nu-arab" : "ar-SA-u-nu-latn") : "en-SA-u-nu-latn");

/** Extra options of the kit's formatters: `isolate: true` wraps the result for Arabic text. */
export interface KitFormatOptions { isolate?: boolean }
const iso = (s: string, lang: Lang, o?: KitFormatOptions) => (o?.isolate ? isolate(s, lang) : s);

export function formatNumber(n: number, lang: Lang, o: Intl.NumberFormatOptions & KitFormatOptions = {}): string {
  const { isolate: wrap, ...nf } = o;
  return iso(new Intl.NumberFormat(numLocale(lang), nf).format(n), lang, { isolate: wrap });
}

/** A counted noun, grammatical in Arabic: countNoun(7, DAY, "ar") → "7 أيام", 2 → "يومان",
 *  countNoun(2, DAY, "ar", {case: "gen"}) → "يومين" (after قبل/بعد/بـ/خلال).
 *  Forms are templates with {count}; a form without {count} is used as is for zero/one/two
 *  ("يوم واحد", "يومان") and gets the number in front for few/many/other ("أيام" → "7 أيام"). */
export function countNoun(n: number, forms: PluralForms | Record<Lang, PluralForms>, lang: Lang,
  o: { case?: GrammaticalCase; isolate?: boolean } = {}): string {
  const f: PluralForms = "other" in forms ? forms as PluralForms : (forms as Record<Lang, PluralForms>)[lang];
  const cat = pluralCategory(n, lang);
  const tpl = selectForm(f, n, lang, o.case);
  const num = formatNumber(n, lang, { isolate: o.isolate });
  if (tpl.includes("{count}")) return tpl.replace(/\{count\}/g, num);
  return cat === "zero" || cat === "one" || cat === "two" ? tpl : `${num} ${tpl}`;
}

/** Common counted nouns, both languages, with the genitive dual (and genitive sound plurals). */
export const NOUNS = {
  day: {
    ar: { zero: "{count} يوم", one: "يوم واحد", two: "يومان", two_gen: "يومين", few: "{count} أيام", many: "{count} يومًا", other: "{count} يوم" },
    en: { one: "{count} day", other: "{count} days" },
  },
  businessDay: {
    ar: { zero: "{count} يوم عمل", one: "يوم عمل واحد", two: "يوما عمل", two_gen: "يومي عمل", few: "{count} أيام عمل", many: "{count} يوم عمل", other: "{count} يوم عمل" },
    en: { one: "{count} business day", other: "{count} business days" },
  },
  week: {
    ar: { zero: "{count} أسبوع", one: "أسبوع واحد", two: "أسبوعان", two_gen: "أسبوعين", few: "{count} أسابيع", many: "{count} أسبوعًا", other: "{count} أسبوع" },
    en: { one: "{count} week", other: "{count} weeks" },
  },
  month: {
    ar: { zero: "{count} شهر", one: "شهر واحد", two: "شهران", two_gen: "شهرين", few: "{count} أشهر", many: "{count} شهرًا", other: "{count} شهر" },
    en: { one: "{count} month", other: "{count} months" },
  },
  year: {
    ar: { zero: "{count} سنة", one: "سنة واحدة", two: "سنتان", two_gen: "سنتين", few: "{count} سنوات", many: "{count} سنة", other: "{count} سنة" },
    en: { one: "{count} year", other: "{count} years" },
  },
  hour: {
    ar: { zero: "{count} ساعة", one: "ساعة واحدة", two: "ساعتان", two_gen: "ساعتين", few: "{count} ساعات", many: "{count} ساعة", other: "{count} ساعة" },
    en: { one: "{count} hour", other: "{count} hours" },
  },
  item: {
    ar: { zero: "{count} عنصر", one: "عنصر واحد", two: "عنصران", two_gen: "عنصرين", few: "{count} عناصر", many: "{count} عنصرًا", other: "{count} عنصر" },
    en: { one: "{count} item", other: "{count} items" },
  },
  row: {
    ar: { zero: "{count} صف", one: "صف واحد", two: "صفّان", two_gen: "صفّين", few: "{count} صفوف", many: "{count} صفًّا", other: "{count} صف" },
    en: { one: "{count} row", other: "{count} rows" },
  },
  record: {
    ar: { zero: "{count} سجل", one: "سجل واحد", two: "سجلّان", two_gen: "سجلّين", few: "{count} سجلات", many: "{count} سجلًّا", other: "{count} سجل" },
    en: { one: "{count} record", other: "{count} records" },
  },
  member: {
    ar: { zero: "{count} عضو", one: "عضو واحد", two: "عضوان", two_gen: "عضوين", few: "{count} أعضاء", many: "{count} عضوًا", other: "{count} عضو" },
    en: { one: "{count} member", other: "{count} members" },
  },
} satisfies Record<string, Record<Lang, PluralForms>>;
export type NounKey = keyof typeof NOUNS;

/** "the last 7 days" / "آخر 7 أيام", "the last 30 days" / "آخر 30 يومًا". */
export function lastDaysPhrase(n: number, lang: Lang): string {
  return lang === "ar" ? `آخر ${countNoun(n, NOUNS.day, "ar")}` : `the last ${countNoun(n, NOUNS.day, "en")}`;
}

// ---- agent names --------------------------------------------------------------------

export type AgentSlug = "super" | "haseef" | "khitabik" | "imagine" | "injaz" | "tasibot" | "monafasaty";
/** The seven agents' display names (the names their Example apps use). In an Arabic
 *  sentence quote them: agentName(slug, "ar", {quote: true}) → «خطابك» («مصمم» and «خطابك»
 *  otherwise read as common nouns). */
export const AGENT_NAMES: Record<AgentSlug, Record<Lang, string>> = {
  super: { ar: "سوبر", en: "Super" },
  haseef: { ar: "حصيف", en: "Haseef" },
  khitabik: { ar: "خطابك", en: "Khitabik" },
  imagine: { ar: "مصمم", en: "Imagine" },
  injaz: { ar: "إنجاز", en: "Injaz" },
  tasibot: { ar: "محلل تاسي", en: "TasiBot" },
  monafasaty: { ar: "منافساتي", en: "Monafasaty" },
};
/** Display name of an agent from its slug (case-insensitive; "source_agent" values like
 *  "Monafasaty" work too). Unknown names come back unchanged; empty → "". */
export function agentName(slug: string | null | undefined, lang: Lang, o: { quote?: boolean } = {}): string {
  if (!slug) return "";
  const key = String(slug).trim().toLowerCase().replace(/[\s_-]+/g, "") as AgentSlug;
  const hit = AGENT_NAMES[key] ?? (Object.values(AGENT_NAMES).find((n) => n.en.toLowerCase().replace(/\s+/g, "") === key || n.ar === String(slug).trim()));
  const name = hit ? hit[lang] : String(slug);
  return o.quote && lang === "ar" && hit ? `«${name}»` : name;
}

// ---- percent and currency (one function each) ---------------------------------------
// PERCENT: one sign, "%", in both languages (Latin digits are the kit default and ZATCA,
// bank and Tadawul documents write 15%). Never "٪" next to "%" on one screen: write a
// percentage through formatPercent/pct(), never a literal "{n}%" in a string.
// CURRENCY: amounts are "1,250.00 ر.س" in Arabic (no trailing dot: «ر.س.» reads as the
// end of a sentence in a table) and "SAR 1,250.00" in English. In running prose say
// «ريال» / "riyals" (write it in the string, not through formatSAR).

/** 0.153 → "15.3%" (a FRACTION in, like Intl). `digits` = maximum fraction digits.
 *  `signed: true` → "+15.3%" / "−2%". Arabic uses "%" too (see above). */
export function formatPercent(n: number, lang: Lang, digits = 1, o: KitFormatOptions & { signed?: boolean; minDigits?: number } = {}): string {
  const s = formatNumber(n * 100, lang, { maximumFractionDigits: digits, minimumFractionDigits: o.minDigits ?? 0, signDisplay: o.signed ? "exceptZero" : "auto" }) + "%";
  return iso(s, lang, o);
}

export interface MoneyOptions extends KitFormatOptions {
  /** "SAR" (default). Other ISO codes print with the code: "1,250.00 USD" / "USD 1,250.00". */
  currency?: string;
  /** fraction digits, default 2 (0 for whole riyals) */
  digits?: number;
  /** "symbol" (default: ر.س / SAR), "code" (SAR in both), "none" (number only) */
  currencyAs?: "symbol" | "code" | "none";
  signed?: boolean;
}
const CUR_AR: Record<string, string> = { SAR: "ر.س", USD: "دولار", EUR: "يورو", AED: "د.إ" };

/** The unit printed with an amount: "ر.س" / "SAR". */
export function currencyUnit(lang: Lang, currency = "SAR", unit: MoneyOptions["currencyAs"] = "symbol"): string {
  if (unit === "none") return "";
  if (unit === "code" || lang === "en") return currency;
  return CUR_AR[currency] ?? currency;
}

/** 1250 → "1,250.00 ر.س" (ar) / "SAR 1,250.00" (en). Old Intl.NumberFormatOptions still work
 *  (maximumFractionDigits etc.), so existing calls keep compiling. */
export function formatSAR(n: number, lang: Lang, o: Intl.NumberFormatOptions & MoneyOptions = {}): string {
  const { isolate: wrap, currency = "SAR", digits, currencyAs: unit = "symbol", signed, ...nf } = o;
  const fd = digits ?? (nf.maximumFractionDigits !== undefined && nf.minimumFractionDigits === undefined ? Math.min(2, nf.maximumFractionDigits) : 2);
  const num = formatNumber(n, lang, { minimumFractionDigits: nf.minimumFractionDigits ?? (nf.notation === "compact" ? 0 : fd), maximumFractionDigits: nf.maximumFractionDigits ?? fd, signDisplay: signed ? "exceptZero" : nf.signDisplay ?? "auto", notation: nf.notation, compactDisplay: nf.compactDisplay, useGrouping: nf.useGrouping });
  const u = currencyUnit(lang, currency, unit);
  const s = !u ? num : lang === "ar" ? `${num} ${u}` : `${u} ${num}`;
  return iso(s, lang, { isolate: wrap });
}

/** Compact amounts for stat cards that must fit at 360 px: 1,330,000 → "1.33 مليون ر.س" /
 *  "SAR 1.33M"; below 10,000 the full amount without decimals. */
export function formatCompactSAR(n: number, lang: Lang, o: MoneyOptions = {}): string {
  const a = Math.abs(n);
  const u = currencyUnit(lang, o.currency ?? "SAR", o.currencyAs ?? "symbol");
  let num: string;
  if (a < 10_000) num = formatNumber(n, lang, { maximumFractionDigits: 0, signDisplay: o.signed ? "exceptZero" : "auto" });
  else {
    const [div, ar, en] = a >= 1e9 ? [1e9, "مليار", "B"] : a >= 1e6 ? [1e6, "مليون", "M"] : [1e3, "ألف", "K"];
    const v = formatNumber(n / div, lang, { maximumFractionDigits: a / div >= 100 ? 0 : 2, signDisplay: o.signed ? "exceptZero" : "auto" });
    num = lang === "ar" ? `${v} ${ar}` : `${v}${en}`;
  }
  const s = !u ? num : lang === "ar" ? `${num} ${u}` : `${u} ${num}`;
  return iso(s, lang, o);
}

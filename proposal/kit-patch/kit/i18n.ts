// Tiny i18n: one {en, ar} dictionary per app, plural forms through Intl.PluralRules
// (Arabic has six: zero one two few many other) with grammatical-case variants, bidi
// isolation of every substituted value, dir on <html>, numbers, percent, SAR.
// The pure helpers live in format.ts (no imports, node-testable) and are re-exported here.
//
// DIGITS: Latin digits (0-9) by default in Arabic too — Saudi business documents,
// invoices (ZATCA) and banking UIs use them, and mixed-digit tables are hard to scan.
// Arabic-Indic digits (٠-٩) are one flag away: setArabicDigits(true).
import { createContext, createElement, useCallback, useContext, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { getView, setView, useCycls } from "./cycls";
import { formatDual, formatGregorian, formatHijri, formatStamp, type FormatOptions, type ISODate, type Lang, type StampOptions } from "./saudi-time";
import {
  agentName, countNoun, formatCompactSAR, formatNumber, formatPercent, formatSAR, interpolate, isolate, selectForm, usesArabicDigits,
  type GrammaticalCase, type MoneyOptions, type PluralForms,
} from "./format";

export type { Lang } from "./saudi-time";
export {
  AGENT_NAMES, FSI, LRI, NOUNS, PDI, RLI, agentName, countNoun, currencyUnit, formatCompactSAR, formatNumber, formatPercent, formatSAR,
  interpolate, isolate, lastDaysPhrase, ltr, plain, pluralCategory, selectForm, setArabicDigits, usesArabicDigits,
} from "./format";
export type { AgentSlug, GrammaticalCase, KitFormatOptions, MoneyOptions, NounKey, PluralCategory, PluralForms } from "./format";

/** A value is a string with {vars}, or plural forms keyed by Intl.PluralRules category,
 *  with optional case variants (`two_gen: "يومين"`; pick one with t(key, {count, case: "gen"})). */
export type Entry = string | PluralForms;
export type Dict = Record<string, Entry>;
export interface Dicts<K extends string> { en: Record<K, Entry>; ar: Record<K, Entry> }
/** Values for {placeholders}. Reserved: `count` (picks the plural form; a numeric string
 *  works too) and `case` ("nom" | "gen" | "acc": picks a case variant). */
export type Vars = Record<string, string | number>;

export const langOf = (locale?: string | null): Lang => (locale && locale.toLowerCase().startsWith("ar") ? "ar" : "en");
export const dirOf = (lang: Lang): "rtl" | "ltr" => (lang === "ar" ? "rtl" : "ltr");

/** t() without the hook. Every substituted value is bidi-isolated where it needs it
 *  (format.ts interpolate(): in Arabic the value plus the symbols glued to it — "{w}×{h}",
 *  "T+{n}", "{pct}%" — unless it is plain Arabic words; in English a value with Arabic
 *  letters), so «تحققت في {date}» keeps 2026-10-21 in order. Numbers are formatted first.
 *  `{raw: true}` (5th argument) for text that is NOT for the screen (file contents, data you
 *  store): no isolates. askAgent / copyText / saveFile strip them anyway. */
export function translate<K extends string>(dicts: Dicts<K>, lang: Lang, key: K, vars: Vars = {}, o: { raw?: boolean } = {}): string {
  const entry: Entry | undefined = dicts[lang][key] ?? dicts.en[key];
  if (entry === undefined) return key;
  let s: string;
  if (typeof entry === "string") s = entry;
  else {
    const c = vars.count;
    const n = typeof c === "number" ? c : typeof c === "string" && c.trim() !== "" && Number.isFinite(Number(c)) ? Number(c) : 0;
    s = selectForm(entry, n, lang, (vars.case as GrammaticalCase | undefined) ?? "nom");
  }
  return interpolate(s, vars, lang, o);
}

// ---- the language context (shared by every component in the kit) ---------------------

/** Formatters for the SCREEN. sar / sarCompact / pct return an isolated token in Arabic
 *  (FSI…PDI around "1,250.00 ر.س", "+13.31%"), so they sit correctly in any sentence.
 *  num / date / hijri / dual / stamp return plain text, as before (their output reorders
 *  correctly on its own, and `{num(x)}%`-style code must not get an isolate between the
 *  number and its sign: write pct(x) instead). For data, files and prompts use the pure
 *  functions (formatNumber, formatSAR, …) or plain(). */
export interface LangState {
  lang: Lang;
  dir: "rtl" | "ltr";
  setLang: (l: Lang) => void;
  num: (n: number, o?: Intl.NumberFormatOptions) => string;
  /** 1250 → "1,250.00 ر.س" / "SAR 1,250.00" (formatSAR) */
  sar: (n: number, o?: Intl.NumberFormatOptions & MoneyOptions) => string;
  /** 1330000 → "1.33 مليون ر.س" / "SAR 1.33M": stat cards at 360 px (formatCompactSAR) */
  sarCompact: (n: number, o?: MoneyOptions) => string;
  /** 0.153 → "15.3%" (a FRACTION in); one sign, "%", in both languages (formatPercent) */
  pct: (fraction: number, digits?: number, o?: { signed?: boolean; minDigits?: number }) => string;
  date: (iso: ISODate, o?: FormatOptions) => string;
  hijri: (iso: ISODate, o?: FormatOptions) => string;
  /** both calendars; `{hijriFirst: true}` for government correspondence */
  dual: (iso: ISODate, o?: FormatOptions) => string;
  /** a timestamp (updatedAt: ISO with time, or ms) → "21 Oct 2026 · 14:05", Riyadh time */
  stamp: (at: string | number | Date | null | undefined, o?: StampOptions) => string;
  /** count(7, NOUNS.day) → "7 أيام"; {case: "gen"} after a preposition → "قبل يومين" */
  count: (n: number, forms: PluralForms | Record<Lang, PluralForms>, o?: { case?: GrammaticalCase }) => string;
  /** agent slug → its display name ({quote: true} → «خطابك» in Arabic) */
  agent: (slug: string | null | undefined, o?: { quote?: boolean }) => string;
}

const LangCtx = createContext<LangState | null>(null);
const VIEW_KEY = "kit:lang";

function applyDir(lang: Lang) {
  const de = document.documentElement;
  const l = lang === "ar" ? "ar" : "en", d = dirOf(lang);
  if (de.lang !== l) de.lang = l;
  if (de.dir !== d) de.dir = d;
}

export function LangProvider({ children }: { children: ReactNode }) {
  const { locale, pending } = useCycls();
  const [chosen, setChosen] = useState<Lang | null>(() => getView<Lang | null>(VIEW_KEY, null));
  const lang: Lang = chosen ?? langOf(locale);
  const setLang = useCallback((l: Lang) => { setChosen(l); setView(VIEW_KEY, l); }, []);
  // <html lang dir> BEFORE the app's first paint. It used to be a useEffect, which runs
  // after the paint: English pages painted one RTL frame, then flipped (CLS 0.042). Set
  // during render, so the commit that mounts the app already has the right direction;
  // the layout effect repeats it in case React throws that render away.
  const ready = !(pending && !chosen);
  if (ready && typeof document !== "undefined") applyDir(lang);
  useLayoutEffect(() => { if (ready) applyDir(lang); }, [lang, ready]);
  const value = useMemo<LangState>(() => {
    const d = (o?: FormatOptions) => ({ arabicDigits: usesArabicDigits(), ...o });
    const w = (s: string) => isolate(s, lang);
    return {
      lang, dir: dirOf(lang), setLang,
      num: (n, o) => formatNumber(n, lang, o),
      sar: (n, o) => w(formatSAR(n, lang, o)),
      sarCompact: (n, o) => w(formatCompactSAR(n, lang, o)),
      pct: (f, digits = 1, o) => w(formatPercent(f, lang, digits, o)),
      date: (iso, o) => formatGregorian(iso, lang, d(o)),
      hijri: (iso, o) => formatHijri(iso, lang, d(o)),
      dual: (iso, o) => formatDual(iso, lang, d(o)),
      stamp: (at, o) => formatStamp(at, lang, d(o)),
      count: (n, forms, o) => countNoun(n, forms, lang, o),
      agent: (slug, o) => agentName(slug, lang, o),
    };
  }, [lang, setLang]);
  return createElement(LangCtx.Provider, { value }, children);
}

export function useLang(): LangState {
  const v = useContext(LangCtx);
  if (!v) throw new Error("useLang() needs <LangProvider> (AppShell includes it)");
  return v;
}

/** const t = useT(dicts); t("key", {count: 3}); t("before", {count: 2, case: "gen"}) */
export function useT<K extends string>(dicts: Dicts<K>) {
  const { lang } = useLang();
  return useCallback((key: K, vars?: Vars) => translate(dicts, lang, key, vars), [dicts, lang]);
}

/** For data that carries both languages: {en, ar} → the current one (falls back to the other). */
export type L10n = { en: string; ar: string } | string;
export function pick(v: L10n | undefined, lang: Lang): string {
  if (v === undefined || v === null) return "";
  if (typeof v === "string") return v;
  return v[lang] || v[lang === "ar" ? "en" : "ar"] || "";
}

// Saudi calendar helpers. No imports, erasable TypeScript only, so `node --test` runs it
// directly and the build service bundles it unchanged.
//
// Dates are civil dates as ISO strings "YYYY-MM-DD" — no time zone, no Date objects at
// rest. That is what the agent writes with `database`, and what survives JSON.
//
// Hijri = Umm al-Qura, through Intl with the calendar named EXPLICITLY
// ("islamic-umalqura"). Never rely on a locale's default calendar: "ar-SA" alone
// formats in Umm al-Qura in ICU, so a "gregorian" Arabic date must say ca-gregory.

export type ISODate = string; // "YYYY-MM-DD"
export type Lang = "ar" | "en";
export interface Hijri { y: number; m: number; d: number }

const DAY = 86_400_000;
const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function parseISO(iso: ISODate): number {
  const m = ISO_RE.exec(iso);
  if (!m) throw new RangeError(`not a YYYY-MM-DD date: ${iso}`);
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  if (toISO(t) !== iso) throw new RangeError(`no such date: ${iso}`);
  return t;
}

export function toISO(t: number | Date): ISODate {
  const d = new Date(typeof t === "number" ? t : t.getTime());
  const y = d.getUTCFullYear();
  return `${y < 0 ? "-" : ""}${String(Math.abs(y)).padStart(4, "0")}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

export function isISODate(v: unknown): v is ISODate {
  if (typeof v !== "string" || !ISO_RE.test(v)) return false;
  try { parseISO(v); return true; } catch { return false; }
}

export function addDays(iso: ISODate, n: number): ISODate { return toISO(parseISO(iso) + n * DAY); }
export function diffDays(a: ISODate, b: ISODate): number { return Math.round((parseISO(b) - parseISO(a)) / DAY); }
/** 0 = Sunday … 6 = Saturday */
export function weekday(iso: ISODate): number { return new Date(parseISO(iso)).getUTCDay(); }

/** Today's civil date in Riyadh (UTC+3, no DST), whatever the device's zone. */
export function todayRiyadh(now: Date = new Date()): ISODate {
  return toISO(now.getTime() + 3 * 3_600_000);
}

// ---- Hijri (Umm al-Qura) -------------------------------------------------------------

const HIJRI_FMT = new Intl.DateTimeFormat("en-u-ca-islamic-umalqura-nu-latn", {
  timeZone: "UTC", year: "numeric", month: "numeric", day: "numeric",
});

/** False when this engine's ICU lacks Umm al-Qura (it then silently answers in another
 *  calendar). Callers show gregorian only in that case. */
export const HIJRI_SUPPORTED: boolean = (() => {
  try {
    if (HIJRI_FMT.resolvedOptions().calendar !== "islamic-umalqura") return false;
    const h = hijriParts(Date.UTC(2026, 9, 21));
    return h.y === 1448 && h.m === 5 && h.d === 10;
  } catch { return false; }
})();

function hijriParts(t: number): Hijri {
  let y = 0, m = 0, d = 0;
  for (const p of HIJRI_FMT.formatToParts(new Date(t))) {
    if (p.type === "year") y = parseInt(p.value, 10);
    else if (p.type === "month") m = parseInt(p.value, 10);
    else if (p.type === "day") d = parseInt(p.value, 10);
  }
  return { y, m, d };
}

export function toHijri(iso: ISODate): Hijri { return hijriParts(parseISO(iso)); }

const HIJRI_EPOCH = Date.UTC(622, 6, 19); // ≈ 1 Muharram 1 AH; only a starting guess

function hijriOrdinal(h: Hijri): number { return (h.y * 12 + (h.m - 1)) * 30 + h.d; }

function firstOfHijriMonth(y: number, m: number): number {
  // Guess, then walk: the forward conversion is the truth, this only finds where it says so.
  let t = HIJRI_EPOCH + Math.round(((y - 1) * 12 + (m - 1)) * 29.530588853) * DAY;
  for (let i = 0; i < 40; i++) {
    const h = hijriParts(t);
    if (h.y === y && h.m === m && h.d === 1) return t;
    const delta = hijriOrdinal({ y, m, d: 1 }) - hijriOrdinal(h);
    t += (delta === 0 ? -1 : Math.max(-400, Math.min(400, Math.round(delta * 0.98)))) * DAY;
  }
  throw new RangeError(`cannot locate 1/${m}/${y} AH`);
}

/** 29 or 30. */
export function hijriMonthLength(y: number, m: number): number {
  const next = m === 12 ? firstOfHijriMonth(y + 1, 1) : firstOfHijriMonth(y, m + 1);
  return Math.round((next - firstOfHijriMonth(y, m)) / DAY);
}

export function fromHijri(y: number, m: number, d: number): ISODate {
  if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d) || m < 1 || m > 12 || d < 1 || d > 30) {
    throw new RangeError(`not a hijri date: ${d}/${m}/${y}`);
  }
  if (d > hijriMonthLength(y, m)) throw new RangeError(`${m}/${y} AH has ${hijriMonthLength(y, m)} days`);
  return toISO(firstOfHijriMonth(y, m) + (d - 1) * DAY);
}

/** Adds hijri months; the day is clamped to the target month's length (30 → 29). */
export function addHijriMonths(iso: ISODate, n: number): ISODate {
  const h = toHijri(iso);
  const total = h.y * 12 + (h.m - 1) + n;
  const y = Math.floor(total / 12), m = (total - y * 12) + 1;
  return fromHijri(y, m, Math.min(h.d, hijriMonthLength(y, m)));
}
export function addHijriYears(iso: ISODate, n: number): ISODate { return addHijriMonths(iso, n * 12); }

export const HIJRI_MONTHS: Record<Lang, string[]> = {
  ar: ["محرم", "صفر", "ربيع الأول", "ربيع الآخر", "جمادى الأولى", "جمادى الآخرة", "رجب", "شعبان", "رمضان", "شوال", "ذو القعدة", "ذو الحجة"],
  en: ["Muharram", "Safar", "Rabi al-Awwal", "Rabi al-Akhir", "Jumada al-Ula", "Jumada al-Akhirah", "Rajab", "Sha'ban", "Ramadan", "Shawwal", "Dhu al-Qadah", "Dhu al-Hijjah"],
};

// ---- formatting ----------------------------------------------------------------------

export interface FormatOptions {
  /** Arabic-Indic digits in Arabic. Default false: Latin digits, as Saudi business documents use. */
  arabicDigits?: boolean;
  weekday?: boolean;
  /** "long" (default): 21 October 2026; "short": 21 Oct 2026; "numeric": 21/10/2026 */
  style?: "long" | "short" | "numeric";
  /** formatDual: Hijri first ("10 جمادى الأولى 1448 هـ · 21 أكتوبر 2026"), as government
   *  correspondence is read in KSA (khitabik, monafasaty deadlines). Default false. */
  hijriFirst?: boolean;
}

function locale(lang: Lang, cal: "gregory", o: FormatOptions): string {
  const nu = lang === "ar" && o.arabicDigits ? "arab" : "latn";
  return `${lang === "ar" ? "ar-SA" : "en-GB"}-u-ca-${cal}-nu-${nu}`;
}

function digits(n: number, lang: Lang, o: FormatOptions): string {
  return new Intl.NumberFormat(lang === "ar" && o.arabicDigits ? "ar-SA-u-nu-arab" : "en-u-nu-latn", { useGrouping: false }).format(n);
}

export function formatGregorian(iso: ISODate, lang: Lang, o: FormatOptions = {}): string {
  const style = o.style ?? "long";
  const opts: Intl.DateTimeFormatOptions = { timeZone: "UTC", year: "numeric", day: "numeric",
    month: style === "numeric" ? "2-digit" : style };
  if (style === "numeric") opts.day = "2-digit";
  if (o.weekday) opts.weekday = style === "long" ? "long" : "short";
  return new Intl.DateTimeFormat(locale(lang, "gregory", o), opts).format(new Date(parseISO(iso)));
}

export function formatHijri(iso: ISODate, lang: Lang, o: FormatOptions = {}): string {
  if (!HIJRI_SUPPORTED) return "";
  const h = toHijri(iso);
  const style = o.style ?? "long";
  const D = digits(h.d, lang, o), Y = digits(h.y, lang, o), M = digits(h.m, lang, o);
  const suffix = lang === "ar" ? "هـ" : "AH";
  // One numeric notation everywhere: D/M/Y with هـ glued ("10/5/1448هـ"), as khitabik's
  // registers write it; English "10/5/1448 AH".
  if (style === "numeric") return lang === "ar" ? `${D}/${M}/${Y}${suffix}` : `${D}/${M}/${Y} ${suffix}`;
  return `${D} ${HIJRI_MONTHS[lang][h.m - 1]} ${Y} ${suffix}`;
}

/** "Wed, 21 October 2026 · 10 Jumada al-Ula 1448 AH"; `hijriFirst` puts the Hijri date
 *  first (the weekday stays at the front). */
export function formatDual(iso: ISODate, lang: Lang, o: FormatOptions = {}): string {
  if (o.hijriFirst && HIJRI_SUPPORTED) {
    const g = formatGregorian(iso, lang, { ...o, weekday: false });
    let h = formatHijri(iso, lang, o);
    if (o.weekday) {
      const wd = new Intl.DateTimeFormat(locale(lang, "gregory", o), { timeZone: "UTC", weekday: (o.style ?? "long") === "long" ? "long" : "short" }).format(new Date(parseISO(iso)));
      h = `${wd}${lang === "ar" ? "، " : ", "}${h}`;
    }
    return `${h} · ${g}`;
  }
  const g = formatGregorian(iso, lang, o);
  const h = formatHijri(iso, lang, { ...o, weekday: false });
  return h ? `${g} · ${h}` : g;
}

export interface StampOptions extends FormatOptions {
  /** show the time (default true); false = the date only */
  time?: boolean;
  /** add the Hijri date ("21 Oct 2026 · 10/5/1448هـ · 14:05") */
  hijri?: boolean;
}
/** A timestamp (ISO string with time, or epoch ms) in Riyadh time: "21 Oct 2026 · 14:05"
 *  (24 h, Latin digits), the same short date as every other date in the app. Unreadable →
 *  "" (callers show an "unreadable value" badge, never a made-up date). */
export function formatStamp(at: string | number | Date | null | undefined, lang: Lang, o: StampOptions = {}): string {
  if (at === null || at === undefined || at === "") return "";
  const t = at instanceof Date ? at.getTime() : typeof at === "number" ? at : ISO_RE.test(at) ? parseISO(at) - 3 * 3_600_000 : Date.parse(at);
  if (!Number.isFinite(t)) return "";
  const r = t + 3 * 3_600_000;                      // Riyadh wall clock, read through UTC
  const day = toISO(r);
  const parts = [formatGregorian(day, lang, { ...o, style: o.style ?? "short", weekday: o.weekday })];
  if (o.hijri) { const h = formatHijri(day, lang, { ...o, style: "numeric" }); if (h) parts.push(h); }
  if (o.time !== false && !(typeof at === "string" && ISO_RE.test(at))) {
    const d = new Date(r);
    const hm = `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
    parts.push(lang === "ar" && o.arabicDigits ? hm.replace(/\d/g, (x) => "٠١٢٣٤٥٦٧٨٩"[+x]) : hm);
  }
  return parts.join(" · ");
}

// ---- Saudi business days -------------------------------------------------------------
// Weekend is Friday + Saturday since 29 June 2013 (Royal Decree; e.g.
// https://www.crowell.com/en/insights/client-alerts/saudi-arabia-changes-weekend-to-friday-saturday-from-29-june-2013).

export type HolidayList = Iterable<ISODate> | ReadonlySet<ISODate>;
const asSet = (h?: HolidayList): ReadonlySet<ISODate> => (h instanceof Set ? h : new Set(h ?? []));

export function isWeekend(iso: ISODate): boolean { const w = weekday(iso); return w === 5 || w === 6; }
export function isBusinessDay(iso: ISODate, holidays?: HolidayList): boolean {
  return !isWeekend(iso) && !asSet(holidays).has(iso);
}

/** n business days after `iso` (before, for n < 0). n = 0 returns `iso` unchanged. */
export function addBusinessDays(iso: ISODate, n: number, holidays?: HolidayList): ISODate {
  if (!Number.isInteger(n)) throw new RangeError("business days must be an integer");
  const set = asSet(holidays);
  const step = n < 0 ? -1 : 1;
  let t = parseISO(iso), left = Math.abs(n), guard = 0;
  while (left > 0) {
    t += step * DAY;
    const d = toISO(t);
    if (!isWeekend(d) && !set.has(d)) left--;
    if (++guard > 100_000) throw new RangeError("holiday list leaves no business days");
  }
  return toISO(t);
}

/** Business days in (a, b] — so diffBusinessDays(a, addBusinessDays(a, n)) === n.
 *  Negative when b is before a. */
export function diffBusinessDays(a: ISODate, b: ISODate, holidays?: HolidayList): number {
  const set = asSet(holidays);
  const ta = parseISO(a), tb = parseISO(b);
  if (ta === tb) return 0;
  const sign = tb > ta ? 1 : -1;
  let n = 0;
  for (let t = ta + sign * DAY; sign > 0 ? t <= tb : t >= tb; t += sign * DAY) {
    const d = toISO(t);
    if (!isWeekend(d) && !set.has(d)) n++;
  }
  // Going backwards counts [b, a): the days you would have to un-work to reach b.
  return sign * n;
}

// ---- official holidays (ESTIMATES — data, not law) -----------------------------------
// Private-sector rule as summarised from Art. 24 of the Labor Law Implementing
// Regulations: Eid al-Fitr 4 days from the day after 29 Ramadan; Eid al-Adha 4 days from
// the Day of Arafah (9 Dhu al-Hijjah); National Day 23 September; Founding Day 22 February.
// Sources (secondary — verify against the HRSD announcement every year):
//   https://www.qoyod.com/en/glossary/public-holiday-leave/
//   https://saudipedia.com/en/official-holidays-in-saudi-arabia
// Eid dates move with the moon sighting; the government sector gets longer breaks.
// An app stores the confirmed list as data (e.g. key `holidays:<year>`) and passes it in;
// this function is only the default shown with an "estimated" mark.

export interface Holiday {
  date: ISODate; key: "eid_fitr" | "eid_adha" | "national_day" | "founding_day"; name: Record<Lang, string>; estimated: boolean;
  /** a day off given because the holiday itself fell on the weekend (Art. 24) */
  compensation?: boolean;
}
export const HOLIDAY_SOURCE = {
  urls: ["https://www.qoyod.com/en/glossary/public-holiday-leave/", "https://saudipedia.com/en/official-holidays-in-saudi-arabia"],
  verifiedAt: "2026-10-21",
  note: "Estimate from the Umm al-Qura calendar; confirm with the HRSD announcement.",
};

const NAMES: Record<Holiday["key"], Record<Lang, string>> = {
  eid_fitr: { ar: "عيد الفطر", en: "Eid al-Fitr" },
  eid_adha: { ar: "عيد الأضحى", en: "Eid al-Adha" },
  national_day: { ar: "اليوم الوطني", en: "National Day" },
  founding_day: { ar: "يوم التأسيس", en: "Founding Day" },
};

/** Estimated private-sector holidays falling in gregorian year `gy`. */
export function estimatedHolidays(gy: number): Holiday[] {
  const out: Holiday[] = [];
  const push = (date: ISODate, key: Holiday["key"]) => { if (date.startsWith(String(gy))) out.push({ date, key, name: NAMES[key], estimated: true }); };
  // Art. 24 of the Labor Law Implementing Regulations: when Founding Day or National Day
  // falls on the weekend, a working day is given instead — Thursday before a Friday,
  // Sunday after a Saturday (as HRSD announced it; next case: National Day 2028, a
  // Saturday → Sunday 24 Sep 2028). An estimate like the rest: confirm each year.
  for (const [md, key] of [["02-22", "founding_day"], ["09-23", "national_day"]] as const) {
    const d = `${gy}-${md}`;
    push(d, key);
    const w = weekday(d);
    if (w === 5 || w === 6) {
      const c = addDays(d, w === 5 ? -1 : 1);
      if (c.startsWith(String(gy))) out.push({ date: c, key, name: { ar: `${NAMES[key].ar} (يوم تعويضي)`, en: `${NAMES[key].en} (compensation day)` }, estimated: true, compensation: true });
    }
  }
  if (HIJRI_SUPPORTED) {
    const hy0 = toHijri(`${gy}-01-01`).y;
    for (const hy of [hy0, hy0 + 1]) {
      const fitr = addDays(fromHijri(hy, 9, 29), 1);
      for (let i = 0; i < 4; i++) push(addDays(fitr, i), "eid_fitr");
      const arafah = fromHijri(hy, 12, 9);
      for (let i = 0; i < 4; i++) push(addDays(arafah, i), "eid_adha");
    }
  }
  return out.sort((a, b) => (a.date < b.date ? -1 : 1));
}

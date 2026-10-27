// Reading rows the agent (or a person, or an old version of the app) wrote. NO imports:
// node --test runs this file directly.
//
// RULE: never coerce silently. A value the app cannot read is NOT replaced by a default
// that looks real (today's date, 0 riyals, the first enum value): it comes back flagged,
// and the UI shows it with <UnreadableValue> ("unreadable value") next to the raw text,
// so the person, and the agent on its next turn, can see and fix it.
//
//   const due = parseISODate(row.due);       // {ok:true, value:"2026-10-25"} | {ok:false, raw, reason}
//   const amt = parseAmount(row.amount);     // "1,150.00" → 1150
//   const st  = parseEnum(row.status, STATUSES, "todo");  // {value:"todo", unknown:true, raw:"in_progress"}

export type ParseFailure = "missing" | "type" | "format" | "ambiguous" | "range";
export type Parsed<T> =
  | { ok: true; value: T; raw: unknown }
  | { ok: false; value: null; raw: unknown; reason: ParseFailure };

const ok = <T>(value: T, raw: unknown): Parsed<T> => ({ ok: true, value, raw });
const bad = (raw: unknown, reason: ParseFailure): Parsed<never> => ({ ok: false, value: null, raw, reason });
const isMissing = (v: unknown) => v === undefined || v === null || (typeof v === "string" && v.trim() === "");

/** Digits in any script → Latin ("١٤٤٨" → "1448", "۱۲" → "12"). */
export function latinDigits(s: string): string {
  return s.replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660)).replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06F0));
}

function validYMD(y: number, m: number, d: number): boolean {
  if (m < 1 || m > 12 || d < 1) return false;
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}
const pad = (n: number, w = 2) => String(n).padStart(w, "0");

export interface DateParseOptions {
  /** inclusive bounds on the year (default 1900–2200): a Hijri year written as gregorian (1448-05-10) is "range" */
  minYear?: number; maxYear?: number;
  /** Time zone for ISO timestamps: their civil date in Riyadh (default) or "UTC". */
  zone?: "riyadh" | "utc";
}

/** A civil date "YYYY-MM-DD". Accepts "2026-10-25", "2026-10-25T09:30:00Z",
 *  "2026-10-25T09:30:00+03:00", "2026-10-25 09:30" (→ the Riyadh civil date), Arabic-Indic
 *  digits, and "2026/10/25". REJECTS what it cannot read for sure:
 *  "25/10/2026" or "10/11/2026" (day/month order unknown → "ambiguous"), "1448/05/10"
 *  (a Hijri year → "range"), "Oct 25" (→ "format"). Never Date.parse (it reads 10/11 as
 *  11 October). */
export function parseISODate(v: unknown, o: DateParseOptions = {}): Parsed<string> {
  if (isMissing(v)) return bad(v, "missing");
  if (typeof v !== "string") return bad(v, "type");
  const s = latinDigits(v.trim());
  const minY = o.minYear ?? 1900, maxY = o.maxYear ?? 2200;
  let m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(s);
  if (m) {
    const y = +m[1], mo = +m[2], d = +m[3];
    if (y < minY || y > maxY) return bad(v, "range");
    return validYMD(y, mo, d) ? ok(`${m[1]}-${pad(mo)}-${pad(d)}`, v) : bad(v, "range");
  }
  m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?$/i.exec(s);
  if (m) {
    const y = +m[1], mo = +m[2], d = +m[3];
    if (y < minY || y > maxY) return bad(v, "range");
    if (!validYMD(y, mo, d) || +m[4] > 23 || +m[5] > 59) return bad(v, "range");
    if (!m[7]) return ok(`${m[1]}-${m[2]}-${m[3]}`, v);          // local wall time: its own date
    const t = Date.parse(s.replace(" ", "T"));
    if (Number.isNaN(t)) return bad(v, "format");
    const shifted = new Date(t + (o.zone === "utc" ? 0 : 3 * 3_600_000));
    return ok(`${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`, v);
  }
  // DD/MM/YYYY or MM/DD/YYYY: never guessed. Both parts ≤ 12 → "ambiguous", else "format".
  m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$/.exec(s);
  if (m) return bad(v, +m[1] <= 12 && +m[2] <= 12 ? "ambiguous" : "format");
  return bad(v, "format");
}

/** An ISO timestamp (e.g. updatedAt) → epoch ms. Accepts a date alone (midnight Riyadh). */
export function parseTimestamp(v: unknown): Parsed<number> {
  if (isMissing(v)) return bad(v, "missing");
  if (typeof v === "number") return Number.isFinite(v) && v > 0 ? ok(v, v) : bad(v, "range");
  if (typeof v !== "string") return bad(v, "type");
  const s = latinDigits(v.trim());
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) { const d = parseISODate(s); return d.ok ? ok(Date.parse(d.value + "T00:00:00+03:00"), v) : d; }
  if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s)) return /^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}/.test(s) ? bad(v, "ambiguous") : bad(v, "format");
  const t = Date.parse(s.replace(" ", "T"));
  return Number.isNaN(t) ? bad(v, "format") : ok(t, v);
}

export interface AmountParseOptions {
  /** allow negative amounts (default true) */
  negative?: boolean;
}
/** A number written by a person or a spreadsheet: 1150, "1150", "1,150.00". Only
 *  unambiguous forms: digits with "," thousands groups and "." decimals, Arabic-Indic
 *  digits and the Arabic separators (٬ thousands, ٫ decimal), a leading +/−, and a currency
 *  word or sign around it ("SAR 1,150", "1,150.00 ر.س", "1,150 ريال"). "1.150,00" (European)
 *  and "12,34" are "ambiguous", never guessed. A "%" is "format" (use parsePercent). */
export function parseAmount(v: unknown, o: AmountParseOptions = {}): Parsed<number> {
  if (isMissing(v)) return bad(v, "missing");
  if (typeof v === "number") return !Number.isFinite(v) ? bad(v, "type") : (o.negative === false && v < 0 ? bad(v, "range") : ok(v, v));
  if (typeof v !== "string") return bad(v, "type");
  let s = latinDigits(v.trim()).replace(/٬/g, ",").replace(/٫/g, ".").replace(/[⁦-⁩‎‏  ]/g, " ");
  s = s.replace(/^(SAR|SR|USD|ر\.?\s?س\.?|ريال(?:\s?سعودي)?|﷼|⃁)\s*/i, "").replace(/\s*(SAR|SR|USD|ر\.?\s?س\.?|ريالًا|ريال(?:\s?سعودي)?|﷼|⃁)$/i, "").trim();
  if (/%|٪/.test(s)) return bad(v, "format");
  s = s.replace(/^−/, "-");
  if (!/^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$/.test(s)) return /^[+-]?\d{1,3}(\.\d{3})+(,\d+)?$|^[+-]?\d+,\d{1,2}$/.test(s) ? bad(v, "ambiguous") : bad(v, "format");
  const n = Number(s.replace(/,/g, ""));
  if (!Number.isFinite(n)) return bad(v, "format");
  return o.negative === false && n < 0 ? bad(v, "range") : ok(n, v);
}

/** A rate as a FRACTION: 0.15, "0.15", "15%", "15 %", "١٥٪" → 0.15. A bare number above 1
 *  (15) is "ambiguous" — 15 % or 1500 %? — unless `percentIfAbove1: true`. */
export function parsePercent(v: unknown, o: { percentIfAbove1?: boolean } = {}): Parsed<number> {
  if (isMissing(v)) return bad(v, "missing");
  if (typeof v === "string" && /[%٪]\s*$/.test(v.trim())) {
    const a = parseAmount(v.trim().replace(/\s*[%٪]$/, ""));
    return a.ok ? ok(a.value / 100, v) : bad(v, a.reason);
  }
  const a = parseAmount(v);
  if (!a.ok) return bad(v, a.reason);
  if (Math.abs(a.value) > 1) return o.percentIfAbove1 ? ok(a.value / 100, v) : bad(v, "ambiguous");
  return ok(a.value, v);
}

/** An integer count (quantity, days): 3, "3", "٣" → 3; 2.5 or "3 days" → "format". */
export function parseCount(v: unknown, o: { min?: number; max?: number } = {}): Parsed<number> {
  const a = parseAmount(v);
  if (!a.ok) return a;
  if (!Number.isInteger(a.value)) return bad(v, "format");
  if ((o.min !== undefined && a.value < o.min) || (o.max !== undefined && a.value > o.max)) return bad(v, "range");
  return a;
}

export interface EnumResult<T extends string> {
  /** the matched value, or `fallback` when unknown (the UI still needs something to render) */
  value: T;
  /** true when `raw` was present but not one of `allowed`: flag it, never silently rename it */
  unknown: boolean;
  /** true when the field was absent / empty (the fallback is then the normal default) */
  missing: boolean;
  raw: unknown;
}
/** One of `allowed`. Matching ignores case, spaces, "-" and "_" ("In progress" → "in_progress"),
 *  and `aliases` maps other spellings, Arabic ones included ({"قيد التنفيذ": "doing"}).
 *  Anything else → {value: fallback, unknown: true, raw}. */
export function parseEnum<T extends string>(v: unknown, allowed: readonly T[], fallback: T,
  aliases: Record<string, T> = {}): EnumResult<T> {
  if (isMissing(v)) return { value: fallback, unknown: false, missing: true, raw: v };
  if (typeof v !== "string") return { value: fallback, unknown: true, missing: false, raw: v };
  if ((allowed as readonly string[]).includes(v)) return { value: v as T, unknown: false, missing: false, raw: v };
  const norm = (x: string) => x.trim().toLowerCase().replace(/[\s_-]+/g, "");
  const k = norm(v);
  const hit = allowed.find((a) => norm(a) === k)
    ?? Object.entries(aliases).find(([a]) => norm(a) === k || a.trim() === v.trim())?.[1];
  return hit ? { value: hit, unknown: false, missing: false, raw: v } : { value: fallback, unknown: true, missing: false, raw: v };
}

/** A string field: trims; a number becomes its text; an object/array is "type". */
export function parseText(v: unknown, o: { max?: number } = {}): Parsed<string> {
  if (isMissing(v)) return bad(v, "missing");
  if (typeof v === "number" && Number.isFinite(v)) return ok(String(v), v);
  if (typeof v !== "string") return bad(v, "type");
  const s = v.trim();
  return o.max !== undefined && s.length > o.max ? bad(v, "range") : ok(s, v);
}

/** A boolean: true/false, "true"/"false", "yes"/"no", "نعم"/"لا", 1/0. Anything else is "format"
 *  (so {anonymous: "maybe"} is flagged, never read as a named form). */
export function parseBool(v: unknown): Parsed<boolean> {
  if (isMissing(v)) return bad(v, "missing");
  if (typeof v === "boolean") return ok(v, v);
  if (v === 1 || v === 0) return ok(v === 1, v);
  if (typeof v !== "string") return bad(v, "type");
  const s = v.trim().toLowerCase();
  if (["true", "yes", "y", "1", "نعم"].includes(s)) return ok(true, v);
  if (["false", "no", "n", "0", "لا"].includes(s)) return ok(false, v);
  return bad(v, "format");
}

/** The raw value as short text for the "unreadable value" badge. */
export function rawText(raw: unknown, max = 60): string {
  // An absent value has no text to show: "" lets callers render their own "missing" state
  // instead of the word "undefined".
  if (raw === undefined || raw === null) return "";
  let s: string;
  try { s = typeof raw === "string" ? raw : JSON.stringify(raw) ?? String(raw); } catch { s = String(raw); }
  return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

/** Collects the fields of one row that failed to parse, for a row-level badge/notice:
 *  const issues = new Issues(); const due = issues.check("due", parseISODate(r.due)); … issues.list */
export class Issues {
  list: { field: string; raw: unknown; reason: ParseFailure | "unknown" }[] = [];
  /** records a failed Parsed (except "missing" unless `required`) and returns its value or null */
  check<T>(field: string, p: Parsed<T>, required = false): T | null {
    if (!p.ok && (p.reason !== "missing" || required)) this.list.push({ field, raw: p.raw, reason: p.reason });
    return p.ok ? p.value : null;
  }
  /** records an unknown enum value and returns the (fallback) value */
  enumOf<T extends string>(field: string, e: EnumResult<T>): T {
    if (e.unknown) this.list.push({ field, raw: e.raw, reason: "unknown" });
    return e.value;
  }
  get any() { return this.list.length > 0; }
  has(field: string) { return this.list.some((i) => i.field === field); }
}

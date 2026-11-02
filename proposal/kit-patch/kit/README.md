# kit/ — shared source for the default apps

Copied **as source** into every app's `src/kit/` by `scripts/build.mjs` (so the agent's
`build_app` can rebuild the app). Only the 29 toolchain packages. Imports are **relative**:
from `src/App.tsx` it is `./kit/…`, from `src/blocks/x/y.tsx` it is `../../kit/…`. There is no
`@/` alias, because the toolchain's `vite.config.mjs` must stay byte-identical to the build service's.

```
kit/
  cycls.ts         window.cycls typed, mode detection, data hooks, refresh, ask/copy/save
  i18n.ts          {en, ar} dictionaries, plurals + case, bidi isolation, dir, numbers, %, SAR, agent names
  format.ts        the pure part of i18n (no imports; node-testable): isolate, countNoun, NOUNS, AGENT_NAMES, formatSAR…
  parse.ts         parseISODate / parseAmount / parseEnum …: read rows without silent coercion (no imports)
  saudi-time.ts    Umm al-Qura, business days, holidays estimate (no imports; node-testable)
  strings.ts       the kit's own words (en/ar) + the shared ones every app reuses (loadExample, fictional, …)
  theme.css        shadcn variables (light/dark) + kit extras + base layer
  lib/utils.ts     cn()
  hooks/           use-mobile (shadcn), use-media-query
  ui/              shadcn/ui new-york-v4 SOURCE (lowercase files, shadcn's API)
  components/      the kit's composites, built on ui/: AppShell, Toolbar, Kanban, DataTable, …
```

## cycls.ts

### Mode — decided once per document

| mode | when | hooks serve |
|---|---|---|
| `live` | the shim answered `ready` and `cycls.me.get` answered | the workspace |
| `gallery` | the shim refuses data (`reason: "no-workspace"`, shared/gallery view) or never answers (`"no-answer"`, e.g. the mobile host without `cycls:data`; turns live if the answer comes late) | demo data, writes in memory + a "demo" toast |
| `standalone` | no `window.cycls` (`"no-shim"`) or `ready` not within 2.5 s (`"no-ready"`) | demo data |

`<AppShell>` decides it, shows the demo banner, and sets `<html data-cycls-mode>`.
`useCycls()` → `{mode, reason, pending, demo, ctx, locale, theme, canWrite, isAdmin, checkAdmin}`.
`useIsAdmin()` → `true | false | null` (probes `cycls.users.all` once; the 403 is the answer).

### Data hooks

```ts
const tasks = useCollection<Task>("task:", { demo: () => demoTasks(lang), validate: isTask });
//  tasks.items, .status ("loading"|"ready"|"error"), .invalid, .demo
//  tasks.add(rec)            create-only: cycls.update(key, cur => { if (cur) throw; return rec })
//  tasks.update(id, patch)   CAS on the FRESH row: a concurrent edit of another field survives
//  tasks.remove(id)          cycls.set(key, undefined) → delete op after the 250 ms flush
//  tasks.loadDemo()          writes the demo rows into an empty live shelf ("load example")
const rules = useDoc<Rules>("rules", { fallback: DEFAULT_RULES, demo: DEMO_RULES }); // .value .set .update
const prefs = useMine<Prefs>("prefs", { fallback: {} });     // cycls.me — this viewer only
const rows  = useMembers<Profile>("profile");                // admins: every member's me-row with that key
```

Every write is stamped `updatedAt` + `updatedBy: "user"` (override with `stamp`). Failures toast
and roll back. Records are `{ id, … }`; the key is `prefix + id`.

### Traps in the shim (verified in `_ref/app-shim.branch.ts`; the hooks handle them)

1. `cycls.get` / `cycls.all()` load the shared shelf **once per document and never again**; a failed
   load is cached as an empty shelf. Fresh rows that an agent wrote cannot be re-read in place.
   → On `turn_end` the kit **reloads the document** (`requestRefresh`), keeping view state.
2. `cycls.get` / `all()` **never reject**, not even in a gallery view. The mode probe uses `cycls.me.get`.
3. `cycls.users.all(prefix)` matches `prefix` against `"<user>/<key>"` (`app_shelf(…, everyone=True)`),
   i.e. the **user id** first. Call it without a prefix and filter keys (`allMembers`, `useMembers`).
4. `cycls.update(key, fn)` runs `fn` on a fresh read; if `fn` throws, nothing is written.
5. `onCommand`, `ask` and `engine` exist only on the `feat/agent-design-extensions` host: use
   `features.ask` and friends, or `askAgent()`, which returns `false` when it can't.

### Refresh on `turn_end`

`turn_end` (and `data_changed`) → `requestRefresh()`. Only `useMine`/`useMembers` mounted: re-fetched
in place. A shared-shelf hook mounted: `cycls.flush()` then `location.reload()` of the frame
(the host re-handshakes; the branch bridge supports a document that re-announces itself). It waits
while a write is in flight, an input is focused, a `ResponsiveSheet` is open, a Kanban drag is
active, or anything else calls `holdRefresh()`.

`useViewState(key, initial)` is `useState` that survives that reload (stored in `window.name`, the
only state a sandboxed frame keeps across a reload). Use it for the view, filters, search, the open
record. Scroll position, theme and language are kept by the kit. Copy the boot `<script>` from
`apps/common/tasks/src/index.html` into your `index.html`, so the reload doesn't flash the wrong theme.

### Other helpers

`askAgent(text)` (≤ 1000 chars, never sends) · `copyText(text)` (textarea + execCommand, since the
Clipboard API is not delegated to the frame) · `saveFile(name, content)` (host save dialog; `null`
if the person cancels) · `newId("t")` · `errorText(e)` · `withTimeout(p, ms)` · `holdRefresh()`.

## i18n.ts (+ format.ts)

```ts
const STRINGS = { en: { hello: "Hello {name}", left: { one: "{count} day left", other: "{count} days left" } },
                  ar: { hello: "مرحبًا {name}",
                        left: { zero: "لم يبقَ أي يوم", one: "بقي يوم واحد", two: "بقي يومان", few: "بقيت {count} أيام", many: "بقي {count} يومًا", other: "بقي {count} يوم" },
                        late: { one: "متأخر يومًا واحدًا", two: "متأخر يومين", other: "متأخر {count} يوم", few: "متأخر {count} أيام", many: "متأخر {count} يومًا" } } };
const t = useT(STRINGS);  t("left", { count: 3 });  t("before", { count: 2, case: "gen" })
const { lang, dir, setLang, num, sar, sarCompact, pct, date, hijri, dual, stamp, count, agent } = useLang();
```

Language = `ctx.locale` (Arabic if it starts with `ar`), else `navigator.language`. The toggle in the
Toolbar wins and survives the refresh. `<html lang dir>` is set **during the render that mounts the
app** (not in an effect after the paint: English pages used to paint one RTL frame, CLS 0.042).
**Digits: Latin (0-9) in Arabic by default** (`setArabicDigits(true)` switches). Data carrying both
languages: `pick(v, lang)`. The pure helpers are in `format.ts` (no imports, `node --test`-able) and
re-exported by `i18n.ts`: import everything from `./kit/i18n`.

### Bidi: values are isolated for you in t()

An Arabic line is a right-to-left paragraph; a value with no Arabic letter of its own is reordered by
it (`تحققت في 2026-10-21` displayed **21-10-2026**, `1080×1920` → **1920×1080**, `T+2` → **2+T**,
`≥ 70` → **70 ≤**). `t()` / `translate()` now wraps **each substituted value plus the symbols glued to
it** (`{w}×{h}`, `T+{n}`, `{p}%`, `{a}–{b}`, `≥{n}`) in FSI…PDI (U+2068/2069). In Arabic it skips
what displays correctly on its own — Arabic words, a plain number (`5`, `1,250.50`, `21/10/2026`,
`10:30`) and Latin words (`USD`) — so text-matching tests and copies see no invisible character
there; in English only values containing Arabic letters are isolated. Across `. : / _` inside a Latin
run the token keeps going (`system_prompt.md:{line}`, `event/{id}`). A token stops at a
space, an Arabic letter (`لـ{unit}` keeps «لـ» outside) and a sentence-ending `.,:;!?`.
Measured in Chromium (`npm run test:bidi`): every case above displays in reading order.

- The isolates are invisible. `askAgent`, `copyText` and `saveFile` strip them (`plain()`); strip them
  yourself (`plain(s)`, or `translate(…, {raw: true})`) before **storing** t() output in a row or a file.
- Screen formatters: `sar()`, `sarCompact()`, `pct()` return an isolated token in Arabic. `num()`,
  `date()`, `hijri()`, `dual()`, `stamp()` return plain text as before (they display correctly).
- **In JSX** nothing is automatic: `{num(w)}×{num(h)}` or `{num(x)}%` next to Arabic still reorders
  (measured: `{num(42)}%` shows "%42"). Write `pct(0.42)`, put formulas in `<Ltr>` / `.ltr`
  (`<Ltr>{w}×{h}</Ltr>`), or pass them through `t()` with a template.
- Comparison words, not signs, in prose: «70 فأكثر», «أقل من 30» (not `≥ 70`, `< 30`). Ranges in prose:
  «من 10:00 إلى 15:00»; in tables an `.ltr` cell.
- `isolate(v, lang)` (FSI when needed) and `ltr(v)` (always LRI) for strings you build yourself.

### Plurals and grammatical case

Plural entries are keyed by `Intl.PluralRules` category (`zero one two few many other`; Arabic uses all
six: 0 → zero, 1 → one, 2 → two, 3–10 → few, 11–99 → many, 100+ → other). Add a **case variant** where
the form changes after a preposition or in an idafa: `two_gen: "يومين"`, `other_gen: …`; select it with
`t(key, {count, case: "gen"})` (a missing variant falls back to the plain form). `count` may be a numeric
string. **A counted noun is always a plural entry** — never `"{count} معاملة"` (gives «4 معاملة»), or put
the label first: «عدد المعاملات: {count}».

```ts
countNoun(7, NOUNS.day, "ar")                  // "7 أيام"      (2 → "يومان", 11 → "11 يومًا", 100 → "100 يوم")
countNoun(2, NOUNS.day, "ar", { case: "gen" })  // "يومين"       → «قبل يومين»، «بعد يومي عمل» (NOUNS.businessDay)
countNoun(n, { one: "معاملة واحدة", two: "معاملتان", two_gen: "معاملتين", few: "{count} معاملات", many: "{count} معاملة", other: "{count} معاملة" }, "ar")
count(5, NOUNS.year)                            // useLang() shortcut, both languages
lastDaysPhrase(7, "ar")                         // "آخر 7 أيام" (not «لآخر 7 يومًا»); "the last 7 days"
```
`NOUNS`: `day businessDay week month year hour item row record member`, each `{ar, en}` with `two_gen`.
A form without `{count}` is used as is for zero/one/two and gets the number in front for few/many/other.

### Agent names

```ts
AGENT_NAMES  // {super:{ar:"سوبر",en:"Super"}, haseef:{ar:"حصيف"}, khitabik:{ar:"خطابك"}, imagine:{ar:"مصمم",en:"Imagine"},
             //  injaz:{ar:"إنجاز"}, tasibot:{ar:"محلل تاسي",en:"TasiBot"}, monafasaty:{ar:"منافساتي"}}
agentName("monafasaty", "ar", { quote: true })  // "«منافساتي»" — quote inside Arabic sentences («مصمم», «خطابك» read as nouns)
agent(row.source_agent)                          // useLang() shortcut; case-insensitive ("Monafasaty"), unknown → unchanged
```
Never a Latin `AGENT_NAME` map in an app. «أضافه {agent}» = `t("addedByAgent", {agent: agent(slug, {quote:true})})` (kit key).

### Percent and currency — one function each (decision 2026-10-21)

| | Arabic | English | function |
|---|---|---|---|
| percent | `15.3%` (sign **%**, never ٪) | `15.3%` | `formatPercent(fraction, lang, digits, {signed})` / `pct(fraction)` |
| amount | `1,250.00 ر.س` (no trailing dot) | `SAR 1,250.00` | `formatSAR(n, lang, {digits, currency, currencyAs, signed})` / `sar(n)` |
| stat card | `1.33 مليون ر.س` | `SAR 1.33M` | `formatCompactSAR` / `sarCompact(n)` / `<Amount value compact="auto">` |
| prose | «ريال» written in the string | "riyals" | — |

Percent takes a **fraction** (0.153). `formatSAR` still accepts the old `Intl.NumberFormatOptions`
(`maximumFractionDigits`, `notation: "compact"`), so existing calls compile; the space before the unit is
non-breaking (the unit never wraps away from the number). Never write `{n}%` or `٪` in a string: pass a
`pct()` value. Rationale: Latin digits are the kit default and ZATCA / bank / Tadawul documents print
`15%`; the trailing dot of Intl's `ر.س.‏` reads as a sentence end in tables.

### Dates and times in the UI

`date(iso)`, `hijri(iso)`, `dual(iso, {hijriFirst})` — **government apps (khitabik, monafasaty
deadlines) pass `hijriFirst: true`**: «10 جمادى الأولى 1448 هـ · 21 أكتوبر 2026». Timestamps
(`updatedAt`, `createdAt`) go through `stamp(at)` → «21 أكتوبر 2026 · 14:05» (Riyadh time, 24 h,
`{hijri: true}` adds «10/5/1448هـ», `{time: false}` the date only) — never `toLocaleString`. One numeric
Hijri notation: `D/M/Yهـ` («10/5/1448هـ»). Never show an ISO date (`2026-10-21`) to a person: format it.

## parse.ts — reading rows without silent coercion

Rows come from the agent, a person, or an older app version. **Never replace a value you cannot read by
a default that looks real** (today, 0 SAR, the first enum value): flag it, show it, let the person and
the agent fix it. Every parser returns `{ok: true, value, raw}` or `{ok: false, value: null, raw, reason}`,
`reason` ∈ `missing | type | format | ambiguous | range`.

```ts
import { parseISODate, parseAmount, parseEnum, parsePercent, parseCount, parseBool, parseText, Issues } from "./kit/parse";
parseISODate("2026-10-25T00:00:00Z")  // ok "2026-10-25"  (timestamps → their Riyadh civil date; "2026/10/25" ok)
parseISODate("10/11/2026")            // ✗ ambiguous — never Date.parse (it reads 11 Oct); "25/10/2026" ✗ format
parseISODate("1448/05/10")            // ✗ range (a Hijri year: years outside 1900–2200)
parseAmount("1,150.00")               // ok 1150  ("SAR 1,150", "1,150 ر.س", "١٬١٥٠٫٥", "-25"); "1.150,00" ✗ ambiguous
parsePercent("15%") → 0.15;  parsePercent(15) → ✗ ambiguous (15 % or 1500 %?)  ({percentIfAbove1: true} to accept)
parseEnum(row.status, ["todo","doing","done"], "todo", {"قيد التنفيذ": "doing"})
                                      // {value, unknown, missing, raw}: "in_progress" → {value:"todo", unknown:true}
parseBool("maybe")                    // ✗ format (not false: {anonymous:"maybe"} must not become a named form)
const issues = new Issues();          // per row: const due = issues.check("due", parseISODate(r.due)); issues.enumOf("status", …)
```
In the UI: `<UnreadableValue raw={p.raw} field="due" />` where the value would be (chip «قيمة غير مقروءة»
/ "Unreadable value" + the raw text, hint in a tooltip), and `<UnreadableNotice count={col.invalid} />`
for rows the validator dropped. Keep the raw value in the row: the app must not rewrite it on save
unless the person edits that field. A validator (`useCollection({validate})`) should reject only rows
it cannot show at all (no title); a bad field is a flagged field, not a dropped row.

## saudi-time.ts

Civil dates are `"YYYY-MM-DD"` strings. `todayRiyadh()`, `toHijri(iso)` → `{y,m,d}`, `fromHijri(y,m,d)`,
`hijriMonthLength`, `addHijriMonths` / `addHijriYears` (day clamped 30 → 29), `formatGregorian` /
`formatHijri` / `formatDual(iso, lang, {weekday, style, arabicDigits, hijriFirst})`, `formatStamp(at, lang,
{time, hijri})`, `isWeekend` (Fri, Sat), `isBusinessDay`, `addBusinessDays(iso, n, holidays)`,
`diffBusinessDays(a, b, holidays)` (counts (a, b], so `diff(a, add(a, n)) === n`), `estimatedHolidays(year)`
(+ `HOLIDAY_SOURCE`; Founding/National Day on a Friday adds the Thursday before, on a Saturday the Sunday
after, as `compensation: true` rows — Art. 24; next case 24 Sep 2028), `HIJRI_SUPPORTED`.
The calendar is always named explicitly (`islamic-umalqura`). `ar-SA` alone formats in Umm al-Qura,
so gregorian Arabic must say `ca-gregory`. Tests: `npm test` (Node ICU), and `scripts/check.mjs` reruns
the same vectors in Chromium. The exchange (Tadawul) closes longer than the labour-law Eid estimate:
an app about trading days must not use `estimatedHolidays` as exchange closures.

## theme.css: tokens

shadcn names: `background foreground card card-foreground popover popover-foreground primary
primary-foreground secondary secondary-foreground muted muted-foreground accent accent-foreground
destructive border input ring chart-1..5 sidebar-*`. Kit extras: `primary-soft success success-soft
warning warning-soft info info-soft destructive-soft border-strong`. Use them as `bg-card`,
`text-muted-foreground`, `bg-success-soft text-success` etc., **never raw colors**. Dark mode is `.dark`
**and** `[data-theme=dark]` on `<html>` (the kit sets both; `dark:` works).

Measured with `scripts/check.mjs` (painted to a canvas): every text pair ≥ 4.5:1. Lowest: light 5.44,
dark 5.70 (`destructive` on `destructive-soft`).

Bidi utilities: `.num` (tabular digits + isolate, keeps the paragraph direction: right for
«1,250.00 ر.س», «7 أيام»); `.ltr` / `.num-ltr` (direction ltr + isolate: `1080×1920`, `9:16`, `T+2`,
`×1.00`, `+13.31%`, `10:00–15:00`, ISO keys, file names — `.num` alone shows «1920×1080»);
`.text-auto` (`unicode-bidi: plaintext`, each paragraph takes its first strong letter's direction).

Base rules worth knowing: touch targets are raised to 40 px on phones through shadcn's `data-slot`
(`h-9` buttons stay 36 px on desktop); `[data-slot=chart]` and `[data-slot=table-container]` are
`contain: inline-size` and `[data-slot=card]` is `min-width: 0` (a recharts chart in a grid card
otherwise locks the page wider than the phone); reduced motion sets `transition-duration: 0s` (the
common `0.01ms` snippet gives every element a transition).

## ui/: shadcn source

From `https://ui.shadcn.com/r/styles/new-york-v4/<name>.json` via `node scripts/shadcn-pull.mjs <name…>`
(public registry), passed through `scripts/shadcn-fix.mjs`: relative imports, `"use client"` removed,
`next-themes` → `components/theme`, physical → logical classes (`ml/mr/pl/pr/left/right/text-left/border-l`
→ `ms/me/ps/pe/start/end/text-start/border-s`). Exceptions: vaul `direction=left/right` and Sheet
`side="left"|"right"` stay physical (their slide animations are). Sidebar `side="left"` means the
**start** side (right in Arabic).

Present: avatar badge button calendar card chart checkbox collapsible command dialog drawer
dropdown-menu input label native-select progress scroll-area select separator sheet sidebar skeleton
sonner table tabs textarea tooltip (+ hooks/use-mobile).

**Local patches** (marked `cycls-default-apps:`; a re-pull overwrites them, so re-apply):
- `chart.tsx`: the registry targets recharts 3, the toolchain pins 2.15.3: `TooltipValueType` is defined locally.
- `dropdown-menu.tsx`: the sub-menu chevron flips in RTL.
- `dialog.tsx`, `sheet.tsx`, `sidebar.tsx`, `command.tsx`: sr-only / aria labels through `kitWord()`
  («إغلاق», «إظهار الشريط الجانبي أو إخفاؤه», «لوحة الأوامر») instead of English.
- `avatar.tsx`: `rtl:space-x-reverse` on the avatar group.
- `sidebar.tsx`: the `document.cookie` write is in try/catch (throws in the sandbox); the rail's
  translate is mirrored in RTL.

## components/: kit composites

`AppShell` (providers + radix `Direction.Provider` + `TooltipProvider` + Toaster + demo banner +
error boundary that reports `cycls:loaderror`), `Toolbar` (title, actions, language and theme toggles),
`ResponsiveSheet` (Drawer under 640 px, Dialog above) and `Confirm`, `Field` + `SimpleSelect`,
`Segmented` (Tabs), `StatusBadge` (tones), `EmptyState`, `LoadExampleButton`, `Spinner` (`aria-busy`,
which the checks wait on), `DataTable` (tanstack on shadcn Table), `Kanban` (dnd-kit; mouse, long-press,
keyboard Space/arrows/Space, Enter opens), `DatePicker` (shadcn Calendar, gregorian + hijri day,
Sun-first, Fri/Sat and holidays marked, "+N business days" chips), `Markdownish`, `MiniTable`,
`MiniChart`, `SeriesChart`, `DocMock`, `SafeImage` (data: only), `ExamplesShowcase`, `ContentResult`,
`TryPrompt`, `EmailImport`, and the text primitives below. Import from `./kit/components`; shadcn
primitives from their file (`./kit/ui/button`).

Behaviour worth knowing (2026-10-21 fix round, measured with Playwright before → after):

| component | behaviour | measured |
|---|---|---|
| `Toolbar` | nothing truncates: the h1 wraps (balanced), the subtitle shows 2 lines (full text in `title`), the actions wrap to their own row when they leave the title < 7rem. Keep ≤ 2 icon actions at 360 px; the rest in a `DropdownMenu` | h1 cut 16–49 px → 0, subtitle cut 59–221 px → 0 (expenses, register, deadlines, screener, limitation at 360 ar); header 57 px → 69–101 px where it had to wrap, tasks unchanged at 57 |
| `Segmented` | each trigger as wide as its label (`flex-none`); a row wider than its box scrolls inside it | label overflow 10 px (kpis "Not on Adaa yet"), 1–3 px (vault, minutes, playbook) → 0 |
| `DataTable` | numeric columns end-aligned with tabular digits in both languages: automatic when every accessor value is a number, else `meta: {align: "end"}` (also `meta.headerClassName / cellClassName`) | portfolio right-edge spread 8–18 px → 0, contracts 9 → 0 |
| `ExamplesShowcase` | prompt preview: padding on the box, clamp on an inner span | 4th-line bleed 8 px → 0 (haseef-, imagine-example) |
| `LangProvider` | `<html lang dir>` set in the render that mounts the app | CLS at 1280 en 0.042–0.045 → 0 (tasks, requests, portfolio, pricing) |
| `StatusBadge` | `dir="auto"` | — |
| `AppShell` Toaster | `aria-label` «الإشعارات»; toasts are click-through (`pointer-events: none`): at the top they cover the Toolbar, and sonner never dismisses a hovered toast, so a pointer over one blocked the title/actions behind it (found by `common/compliance` checks). A toast with an action button needs `style: {pointerEvents: "auto"}` | — |
| `EmailImport` | a button only (`variant="block"` for the old note under it); the sheet explains that without a mail connector the agent asks for pasted emails; `EmailImportQuery.period` = «آخر 7 أيام» / "the last 7 days" | no-connector rule kept ≤ the old length (EN 376 vs 380 chars, AR 326 vs 325) |

Text primitives (`components/text.tsx`):

```tsx
<AutoText as="p" className="…">{row.note}</AutoText>      // dir="auto": user/agent text of unknown language
<Ltr>{w}×{h}</Ltr>                                         // <bdi dir="ltr" class="num-ltr">: formulas, codes, T+2, ranges
<Amount value={1_330_000} compact="auto" />                // unit in its own smaller span, never truncated; compact < sm
<UnreadableValue raw={p.raw} field="due" />                // a field parse*() flagged: «قيمة غير مقروءة» + raw text
<UnreadableNotice count={col.invalid} />                   // «تعذّرت قراءة 3 صفوف»
<LoadExampleButton onClick={rows.loadDemo} />              // «إضافة بيانات تجريبية» / "Add example data"
```

Kit words every app reuses (`useKitT()`, or `kitWord(key)` outside React): `loadExample`,
`loadedExample`, `fictional` («افتراضية»), `fictionalNote`, `prompt` («التعليمة» — the agent prompt;
«الطلب» is the business object of requests/forms/bids), `tryPrompt`, `copyPrompt`, `unreadableValue`,
`unreadableRows`, `verifiedOn` («تاريخ التحقق: {date}»), `toVerify` («بحاجة إلى تحقق»), `addedByUser`
(«أضافه مستخدم»), `addedByAgent` («أضافه {agent}»), `notifications`, `whatAgentDid`, `sources`.

## ExamplesShowcase: data

```ts
<ExamplesShowcase examples={EXAMPLES} categories?={…} renderResult?={(ex, compact) => node | undefined} stateKey?="showcase" />

interface Example {
  id: string;
  category: string | { en: string; ar: string };  // an id from `categories`, or a label (categories derived)
  title: L10n; prompt: L10n;                       // L10n = string | { en, ar }
  summary?: L10n; featured?: boolean; kind?: string;
  result: ResultBlock[] | object | L10n;           // see below
  did?: L10n;                                      // "what the agent did" (detail sheet)
  sources?: (string | { title?: L10n; url: string })[];  // URLs become links, the rest code refs
  fictional?: boolean | L10n;
}
type ResultBlock =
  | { type: "text"; md: L10n }                     // # headings, - lists, 1. lists, **bold**, > quote
  | { type: "table"; columns: L10n[]; rows: (string | number | L10n)[][]; caption?: L10n }
  | { type: "chart"; kind: "bar" | "line" | "donut"; data: { label: L10n; value: number }[]; unit?: L10n; title?: L10n }
  | { type: "image"; src: "data:image/…"; alt: L10n }
  | { type: "doc"; kind: L10n; title: L10n; meta?: { k: L10n; v: L10n }[]; body: L10n }
  | { type: "kpis"; items: { label: L10n; value: L10n; hint?: L10n; tone?: "success"|"warning"|"danger"|"info" }[] };
```

A `result` **object** (the shape of `apps/<agent>/example/examples.json`) goes through `ContentResult`,
which renders: `kpis`, `chart` / `charts[]` (`type|chartType`, `labels|x`, `series[{name, data}]`),
`columns`+`rows` (array or keyed rows) and `table`, letters (`header`, `subject`, `recipient`, `greeting`,
`body[]`, `closing`, `signature`), `sections[]`, checklist `items[]`, `insight / takeaway / summary /
intro / text`, `note / caveat`, `image` (pending → framed placeholder with the alt), `file` + `format`.
Unknown fields are ignored: a kind of your own goes through `renderResult`. The 81 entries present on
2026-10-21 all render (kit gallery, checked at 360 and 1280).
"Try this prompt" = `cycls.ask` when the host has it and the view is live, else copy, else a
selectable textarea.

## Checklist for app code (kit round of 2026-10-21)

1. No `toLocaleString`/`toLocaleDateString` in the UI: `stamp(at)`, `date()`, `dual()`; khitabik and
   monafasaty deadlines `dual(d, {hijriFirst: true})`. No ISO date shown to a person.
2. No `{num(x)}%`, no `٪`, no hand-made `+${…}`: `pct(fraction, digits, {signed})`. Money: `sar()`,
   stat cards `<Amount>` / `sarCompact()` (and drop `truncate` on the value).
3. Formulas/codes in JSX (`w×h`, `T+2`, `×1.00`, ranges, keys): `<Ltr>` or `.ltr`; comparison and range
   words in prose («70 فأكثر», «من 10:00 إلى 15:00»).
4. Every counted noun is a plural entry or `count(n, NOUNS.x)`; after قبل/بعد/بـ/خلال/متأخر use
   `{case: "gen"}` (`two_gen`). Email prompts: `q.period` instead of `${days} يومًا`.
5. Agent names: `agent(slug, {quote: true})`; delete local `AGENT_NAME` maps and «Monafasaty» literals.
6. Shared words from the kit: `loadExample` (or `<LoadExampleButton>`), `fictional`, `prompt`,
   `verifiedOn`, `toVerify`, `addedByUser`, `addedByAgent`.
7. Model code: `parseISODate` / `parseAmount` / `parsePercent` / `parseEnum` / `parseBool` instead of
   `Date.parse`, `Number()`, silent enum fallbacks; show `<UnreadableValue>` for flagged fields and
   `<UnreadableNotice>` for dropped rows. A bad Hijri trigger or DD/MM date is flagged, never "today".
8. Numeric DataTable columns whose accessor is not a number: `meta: {align: "end"}`.
9. User/agent text of unknown language in an LTR or RTL box: `<AutoText>` / `dir="auto"`.
10. Before storing or exporting t() output: `plain()` (askAgent, copyText, saveFile already do).

## Lead updates after the fix round (2026-10-21)
- `<UnreadableValue raw field reason?>`: `reason` is shown under the chip; native `title` instead of a Radix Tooltip (−56 KB per app). `rawText(undefined|null)` is `""` (no more "undefined").
- `useCollection`: the **key** decides `id` (a row whose `value.id` differs from its key is no longer written back under another key).
- `useDoc.update(fn)`: `fn` runs once outside the state updater; throwing in `fn` writes nothing and no longer crashes the render.
- `<EmailImport>`: `variant="none"` + `open`/`onOpenChange` to open it from a menu item; `compact` hides "(30 days)" below 640 px.

// Default renderer for the Example apps' content files (apps/<agent>/example/examples.json):
// a `result` object whose fields vary by `kind`. It renders the recurring fields and
// ignores the rest; an app with a kind of its own passes renderResult to ExamplesShowcase.
//
// Recognised fields (any combination):
//   fictional (bool | L10n) · entity · project · subtitle · period · as_of
//   kpis[{label, value, unit?, delta?}]
//   chart | charts[]: {type|chartType: bar|line|donut|pie, title?, x? | labels? ({en,ar} arrays or array), series[{name, data[]}]}
//   columns + rows (rows as arrays, or objects keyed by column.key) | table {title?, columns, rows}
//   letter: header{entity, number, date{hijri, gregorian}}, subject, recipient[], greeting, body[], closing, signature{name,title}
//   document: header{…}, sections[{heading, body}]
//   items[{label, owner?, status?}] (checklist)
//   insight | takeaway | note | caveat | summary | why_it_matters | intro | text (L10n or md)
//   image {src: data-URI}|null with status/alt (pending → a framed placeholder)
//   format + file (+ pages) → a file chip
import type { ReactNode } from "react";
import { CheckCircle2, Circle, CircleAlert, FileText, ImageIcon, Info } from "lucide-react";
import { useLang, type L10n } from "../i18n";
import { isISODate } from "../saudi-time";
import { DocMock, Markdownish, SafeImage } from "./rich";
import { StatusBadge } from "./status-badge";
import { cn } from "../lib/utils";

type Any = Record<string, any>;
const isL10n = (v: unknown): v is { en: unknown; ar: unknown } => !!v && typeof v === "object" && !Array.isArray(v) && ("en" in (v as Any) || "ar" in (v as Any));

/** Text of a value that may be a string, a number, {en, ar}, or {value, unit}. */
export function useText() {
  const { lang, num } = useLang();
  const text = (v: unknown): string => {
    if (v === null || v === undefined) return "";
    if (typeof v === "number") return num(v);
    if (typeof v === "string") return v;
    if (Array.isArray(v)) return v.map(text).join(", ");
    if (isL10n(v)) return text((v as Any)[lang] ?? (v as Any)[lang === "ar" ? "en" : "ar"]);
    if (typeof v === "object" && "value" in (v as Any)) return `${text((v as Any).value)}${(v as Any).unit ? " " + text((v as Any).unit) : ""}`;
    return "";
  };
  /** An array that may be per-language: {en: [...], ar: [...]} or [...] */
  const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : isL10n(v) ? ((v as Any)[lang] ?? (v as Any).en ?? []) : []);
  return { text, list, lang };
}

const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

/** Several series on one SVG: grouped bars or lines. x runs with the reading direction. */
export function SeriesChart({ type, labels, series, title }: { type: string; labels: string[]; series: { name: string; data: number[] }[]; title?: string }) {
  const { dir, num } = useLang();
  const W = 320, H = 120, pad = 8;
  const n = Math.max(labels.length, ...series.map((s) => s.data.length));
  const max = Math.max(1, ...series.flatMap((s) => s.data.map((d) => Number(d) || 0)));
  const X = (i: number, w = 0) => { const x = pad + (i / Math.max(1, n - (type === "line" ? 1 : 0))) * (W - 2 * pad) + w; return dir === "rtl" ? W - x : x; };
  const Y = (v: number) => H - pad - ((Number(v) || 0) / max) * (H - 2 * pad);
  const summary = `${title ? title + ": " : ""}${series.map((s) => `${s.name} ${s.data.map((d) => num(Number(d) || 0)).join(", ")}`).join("; ")}`;
  const slot = (W - 2 * pad) / Math.max(1, n);
  const bw = Math.max(2, (slot * 0.7) / Math.max(1, series.length));
  return (
    <figure role="img" aria-label={summary} className="space-y-2">
      {title && <figcaption className="text-xs font-medium text-muted-foreground">{title}</figcaption>}
      <svg viewBox={`0 0 ${W} ${H}`} className="h-28 w-full" preserveAspectRatio="none" aria-hidden>
        {type === "line"
          ? series.map((s, k) => <polyline key={k} points={s.data.map((d, i) => `${X(i)},${Y(d)}`).join(" ")} fill="none" stroke={SERIES[k % 5]} strokeWidth="2.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />)
          : series.map((s, k) => s.data.map((d, i) => {
              const x0 = pad + i * slot + slot * 0.15 + k * bw;
              const x = dir === "rtl" ? W - x0 - bw : x0;
              return <rect key={`${k}-${i}`} x={x} y={Y(d)} width={bw} height={H - pad - Y(d)} rx="1.5" fill={SERIES[k % 5]} />;
            }))}
      </svg>
      <div className="flex justify-between gap-2 text-[11px] text-muted-foreground"><span className="truncate">{labels[0]}</span><span className="truncate">{labels[labels.length - 1]}</span></div>
      {series.length > 1 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
          {series.map((s, k) => <li key={k} className="flex items-center gap-1.5"><span aria-hidden className="size-2.5 rounded-sm" style={{ background: SERIES[k % 5] }} />{s.name}</li>)}
        </ul>
      )}
    </figure>
  );
}

function Chart({ c }: { c: Any }) {
  const { text, list } = useText();
  const type = String(c.type ?? c.chartType ?? "bar");
  const labels = (list(c.labels).length ? list(c.labels) : list(c.x)).map(text);
  const series = (Array.isArray(c.series) ? c.series : c.data ? [{ name: c.title, data: c.data }] : [])
    .map((s: Any) => ({ name: text(s.name), data: (Array.isArray(s.data) ? s.data : []).map((d: unknown) => (typeof d === "object" && d ? Number((d as Any).value) : Number(d))) }));
  if (!series.length) return null;
  if (type === "donut" || type === "pie") {
    const s = series[0];
    const total = s.data.reduce((a: number, b: number) => a + (b || 0), 0) || 1;
    return (
      <div className="space-y-1.5">
        {c.title && <div className="text-xs font-medium text-muted-foreground">{text(c.title)}</div>}
        {s.data.map((d: number, i: number) => (
          <div key={i} className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-2 text-xs">
            <span className="truncate text-muted-foreground">{labels[i]}</span>
            <span className="h-2.5 rounded-sm bg-muted"><span className="block h-2.5 rounded-sm" style={{ width: `${(d / total) * 100}%`, background: SERIES[i % 5] }} /></span>
            <span className="num">{Math.round((d / total) * 100)}%</span>
          </div>
        ))}
      </div>
    );
  }
  return <SeriesChart type={type === "line" ? "line" : "bar"} labels={labels} series={series} title={text(c.title)} />;
}

function Table({ columns, rows, title, compact }: { columns: Any[]; rows: Any[]; title?: unknown; compact?: boolean }) {
  const { text } = useText();
  const { date } = useLang();
  const cols = columns.map((c, i) => ({ key: typeof c === "object" && c?.key ? String(c.key) : String(i), label: text(typeof c === "object" && c && !isL10n(c) && "label" in c ? c.label : c) }));
  const shown = compact ? rows.slice(0, 4) : rows;
  return (
    <div className="w-full overflow-x-auto rounded-lg border contain-inline-size">
      <table className="w-full border-collapse text-xs">
        {title ? <caption className="px-3 py-2 text-start font-medium text-muted-foreground">{text(title)}</caption> : null}
        <thead className="bg-muted text-muted-foreground"><tr>{cols.map((c) => <th key={c.key} scope="col" className="whitespace-nowrap px-3 py-2 text-start font-medium">{c.label}</th>)}</tr></thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className="border-t">
              {cols.map((c, j) => {
                const v = Array.isArray(r) ? r[j] : r?.[c.key];
                const iso = isISODate(v);
                return <td key={c.key} className={cn("px-3 py-2 align-top", (typeof v === "number" || iso) && "num whitespace-nowrap")}>{iso ? date(v as string, { style: "short" }) : text(v)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Callout({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warning" }) {
  return (
    <div className={cn("flex gap-2 rounded-lg px-3 py-2 text-xs", tone === "info" ? "bg-info-soft text-info" : "bg-warning-soft text-warning")}>
      {tone === "info" ? <Info className="mt-0.5 size-4 shrink-0" /> : <CircleAlert className="mt-0.5 size-4 shrink-0" />}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function ContentResult({ result, compact = false }: { result: unknown; compact?: boolean }) {
  const { text, lang } = useText();
  if (result === null || result === undefined) return null;
  if (typeof result === "string") return <Markdownish text={result} className={compact ? "line-clamp-6 text-xs" : undefined} />;
  if (isL10n(result)) return <Markdownish text={text(result)} className={compact ? "line-clamp-6 text-xs" : undefined} />;
  const r = result as Any;
  const parts: ReactNode[] = [];
  const push = (node: ReactNode) => parts.push(<div key={parts.length}>{node}</div>);

  const meta = [r.entity, r.project, r.subtitle, r.period, r.as_of].map(text).filter(Boolean);
  if (meta.length && !compact) push(<p className="text-xs text-muted-foreground">{meta.join(" · ")}</p>);

  // image (pending ones are a framed placeholder at the requested ratio)
  if ("image" in r || r.status === "pending") {
    const src = typeof r.image === "string" ? r.image : r.image?.src;
    push(src ? <SafeImage src={src} alt={text(r.alt)} className={compact ? "max-h-40" : undefined} /> : (
      <div className="grid aspect-square max-h-56 w-full place-items-center rounded-lg border border-dashed bg-muted text-center text-xs text-muted-foreground">
        <div className="space-y-2 px-4"><ImageIcon className="mx-auto size-8 opacity-60" /><p className="line-clamp-4">{text(r.alt)}</p></div>
      </div>
    ));
  }

  if (Array.isArray(r.kpis) && r.kpis.length) push(
    <div className="grid grid-cols-2 gap-2">
      {(compact ? r.kpis.slice(0, 4) : r.kpis).map((k: Any, i: number) => (
        <div key={i} className="min-w-0 rounded-lg border bg-card p-2.5">
          <div className="truncate text-[11px] text-muted-foreground">{text(k.label)}</div>
          <div className="num truncate text-base font-semibold">{text(k.value)}{k.unit ? <span className="ms-1 text-xs font-normal text-muted-foreground">{text(k.unit)}</span> : null}</div>
          {k.delta ? <div className="truncate text-[11px] text-muted-foreground">{text(k.delta)}</div> : null}
        </div>
      ))}
    </div>,
  );

  const charts = [r.chart, ...(Array.isArray(r.charts) ? r.charts : [])].filter(Boolean);
  if (!charts.length && Array.isArray(r.series)) charts.push({ type: r.chartType, labels: r.labels, series: r.series, title: r.title });
  for (const c of compact ? charts.slice(0, 1) : charts) push(<Chart c={c} />);

  if (Array.isArray(r.columns) && Array.isArray(r.rows)) push(<Table columns={r.columns} rows={r.rows} compact={compact} />);
  if (r.table && Array.isArray(r.table.columns)) push(<Table columns={r.table.columns} rows={r.table.rows ?? []} title={r.table.title} compact={compact} />);

  // letter
  if (r.subject || (Array.isArray(r.body) && r.greeting)) {
    const h = r.header ?? {};
    const body = [r.greeting, ...(Array.isArray(r.body) ? r.body : [r.body]), r.closing].map(text).filter(Boolean).join("\n\n");
    push(<div dir={r.dir ?? undefined}><DocMock kind={text(h.entity) || (lang === "ar" ? "خطاب" : "Letter")} title={text(r.subject)}
      meta={[h.number && { k: lang === "ar" ? "الرقم" : "No.", v: text(h.number) }, h.date && { k: lang === "ar" ? "التاريخ" : "Date", v: [text(h.date.hijri), text(h.date.gregorian)].filter(Boolean).join(" · ") },
        Array.isArray(r.recipient) && { k: lang === "ar" ? "إلى" : "To", v: r.recipient.map(text).join(" ") }].filter(Boolean) as { k: L10n; v: L10n }[]}
      body={compact ? body.split("\n\n").slice(0, 2).join("\n\n") : body + (r.signature ? `\n\n**${text(r.signature.name)}**\n${text(r.signature.title)}` : "")} /></div>);
  }

  // sectioned document
  if (Array.isArray(r.sections) && r.sections.length) push(
    <DocMock kind={text(r.format)?.toUpperCase() || (lang === "ar" ? "مستند" : "Document")} title={text(r.title ?? r.header?.project) || ""}
      body={(compact ? r.sections.slice(0, 2) : r.sections).map((s: Any) => `## ${text(s.heading)}\n${text(s.body)}`).join("\n\n")} />,
  );

  // checklist
  if (Array.isArray(r.items) && r.items.length && r.items.every((x: unknown) => x && typeof x === "object" && "label" in (x as Any))) push(
    <ul className="space-y-1.5 text-xs">
      {(compact ? r.items.slice(0, 5) : r.items).map((it: Any, i: number) => (
        <li key={i} className="flex items-start gap-2">
          {it.status === "ok" || it.status === "done" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
          <span className="min-w-0 flex-1">{text(it.label)}</span>
          {it.owner && <StatusBadge tone="neutral">{text(it.owner)}</StatusBadge>}
        </li>
      ))}
    </ul>,
  );

  const prose = ["text", "intro", "summary", "insight", "takeaway", "why_it_matters"].map((k) => r[k]).filter((v) => v && (typeof v === "string" || isL10n(v)));
  for (const v of compact ? prose.slice(0, 1) : prose) push(<Markdownish text={text(v)} className={compact ? "line-clamp-4 text-xs" : undefined} />);
  for (const k of ["note", "caveat"]) if (r[k] && !compact) push(<Callout tone="warning">{text(r[k])}</Callout>);

  if (r.file && !compact) push(
    <div className="flex items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-xs">
      <FileText className="size-4 shrink-0 text-muted-foreground" />
      <span dir="ltr" className="min-w-0 flex-1 truncate">{String(r.file)}</span>
      {r.format && <StatusBadge tone="primary">{String(r.format).toUpperCase()}{r.pages ? ` · ${r.pages}` : ""}</StatusBadge>}
    </div>,
  );

  if (!parts.length) return <p className="text-xs text-muted-foreground">{text(r.title) || "—"}</p>;
  return <div className="space-y-3">{parts}</div>;
}

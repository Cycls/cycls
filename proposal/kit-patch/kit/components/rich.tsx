// Small renderers for agent output previews: markdown-ish text, tables, SVG charts,
// images (data: URIs only — the CSP blocks everything else) and document mock-ups.
import { Fragment, type ReactNode } from "react";
import { useLang, pick, type L10n } from "../i18n";
import { cn } from "../lib/utils";

// ---- markdown-ish ---------------------------------------------------------------------
// # / ## / ### headings, "- " or "• " bullets, "1. " numbered, **bold**, blank-line
// paragraphs, "> " quote. No HTML is ever interpreted.

function inline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>);
}

export function Markdownish({ text, className }: { text: string; className?: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r/g, "").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  let para: string[] = [];
  const flushPara = () => { if (para.length) { blocks.push(<p key={blocks.length}>{inline(para.join(" "))}</p>); para = []; } };
  const flushList = () => {
    if (!list) return;
    const L = list.ordered ? "ol" : "ul";
    blocks.push(<L key={blocks.length} className={cn("space-y-1 ps-5", list.ordered ? "list-decimal" : "list-disc")}>{list.items.map((x, i) => <li key={i}>{inline(x)}</li>)}</L>);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    const ul = /^\s*[-•]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const q = /^>\s?(.*)$/.exec(line);
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if (h) { flushPara(); flushList(); const lvl = h[1].length; blocks.push(<div key={blocks.length} role="heading" aria-level={lvl + 2} className={cn("font-semibold", lvl === 1 ? "text-base" : "text-sm")}>{inline(h[2])}</div>); continue; }
    if (ul || ol) { flushPara(); const ordered = !!ol; if (!list || list.ordered !== ordered) { flushList(); list = { ordered, items: [] }; } list.items.push((ul || ol)![1]); continue; }
    if (q) { flushPara(); flushList(); blocks.push(<blockquote key={blocks.length} className="border-s-2 border-border-strong ps-3 text-muted-foreground">{inline(q[1])}</blockquote>); continue; }
    flushList(); para.push(line.trim());
  }
  flushPara(); flushList();
  return <div className={cn("space-y-2 text-sm leading-relaxed break-words", className)}>{blocks}</div>;
}

// ---- table -----------------------------------------------------------------------------

export function MiniTable({ columns, rows, caption }: { columns: L10n[]; rows: (string | number | L10n)[][]; caption?: L10n }) {
  const { lang, num } = useLang();
  const cell = (v: string | number | L10n) => (typeof v === "number" ? num(v) : pick(v, lang));
  return (
    <div className="w-full overflow-x-auto rounded-lg border border-border contain-inline-size">
      <table className="w-full border-collapse text-xs">
        {caption && <caption className="px-3 py-2 text-start text-xs font-medium text-muted-foreground">{pick(caption, lang)}</caption>}
        <thead className="bg-muted text-muted-foreground"><tr>{columns.map((c, i) => <th key={i} scope="col" className="whitespace-nowrap px-3 py-2 text-start font-medium">{pick(c, lang)}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-border">{r.map((v, j) => <td key={j} className={cn("px-3 py-2", typeof v === "number" && "num")}>{cell(v)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

// ---- charts (SVG, token colors, direction-aware) -------------------------------------------

export interface ChartDatum { label: L10n; value: number }
const SERIES = ["var(--color-chart-1)", "var(--color-chart-2)", "var(--color-chart-3)", "var(--color-chart-4)", "var(--color-chart-5)"];

export function MiniChart({ kind, data, unit, title }: { kind: "bar" | "line" | "donut"; data: ChartDatum[]; unit?: L10n; title?: L10n }) {
  const { lang, dir, num } = useLang();
  const label = (d: ChartDatum) => pick(d.label, lang);
  const u = unit ? ` ${pick(unit, lang)}` : "";
  const summary = `${title ? pick(title, lang) + ": " : ""}${data.map((d) => `${label(d)} ${num(d.value)}${u}`).join(", ")}`;
  if (kind === "donut") {
    const total = data.reduce((s, d) => s + Math.max(0, d.value), 0) || 1;
    let acc = 0;
    const R = 40, C = 2 * Math.PI * R;
    return (
      <figure className="flex flex-wrap items-center gap-4" aria-label={summary} role="img">
        <svg viewBox="0 0 100 100" className="size-28 shrink-0 -rotate-90" aria-hidden>
          <circle cx="50" cy="50" r={R} fill="none" stroke="var(--muted)" strokeWidth="16" />
          {data.map((d, i) => {
            const len = (Math.max(0, d.value) / total) * C;
            const el = <circle key={i} cx="50" cy="50" r={R} fill="none" stroke={SERIES[i % SERIES.length]} strokeWidth="16" strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-acc} />;
            acc += len;
            return el;
          })}
        </svg>
        <ul className="min-w-0 space-y-1 text-xs">
          {data.map((d, i) => <li key={i} className="flex items-center gap-2"><span aria-hidden className="size-2.5 shrink-0 rounded-sm" style={{ background: SERIES[i % SERIES.length] }} /><span className="min-w-0 flex-1 truncate">{label(d)}</span><span className="num text-muted-foreground">{num(Math.round((d.value / total) * 100))}%</span></li>)}
        </ul>
      </figure>
    );
  }
  const max = Math.max(1, ...data.map((d) => d.value));
  if (kind === "bar") {
    return (
      <figure role="img" aria-label={summary} className="space-y-1.5">
        {data.map((d, i) => (
          <div key={i} className="grid grid-cols-[minmax(0,7rem)_1fr_auto] items-center gap-2 text-xs">
            <span className="truncate text-muted-foreground">{label(d)}</span>
            <span className="h-3 rounded-sm bg-muted"><span className="block h-3 rounded-sm" style={{ width: `${(d.value / max) * 100}%`, background: SERIES[0] }} /></span>
            <span className="num tabular-nums">{num(d.value)}{u}</span>
          </div>
        ))}
      </figure>
    );
  }
  // line: x runs with the reading direction
  const W = 300, H = 90, pad = 6;
  const pts = data.map((d, i) => {
    const x = pad + (i / Math.max(1, data.length - 1)) * (W - 2 * pad);
    return [dir === "rtl" ? W - x : x, H - pad - (d.value / max) * (H - 2 * pad)] as const;
  });
  return (
    <figure role="img" aria-label={summary}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-24 w-full" preserveAspectRatio="none" aria-hidden>
        <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke={SERIES[0]} strokeWidth="2.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r="3" fill={SERIES[0]} />)}
      </svg>
      <div className="mt-1 flex justify-between text-[11px] text-muted-foreground">{data.length > 0 && <><span>{label(data[0])}</span><span>{label(data[data.length - 1])}</span></>}</div>
    </figure>
  );
}

// ---- document mock-up --------------------------------------------------------------------

export function DocMock({ kind, title, meta, body }: { kind: string; title: L10n; meta?: { k: L10n; v: L10n }[]; body: L10n }) {
  const { lang } = useLang();
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-3 border-b border-border pb-3">
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{kind}</div>
          <div className="break-words text-sm font-semibold">{pick(title, lang)}</div>
        </div>
        <div aria-hidden className="h-8 w-8 shrink-0 rounded-md bg-primary-soft" />
      </div>
      {meta && meta.length > 0 && (
        <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          {meta.map((m, i) => <Fragment key={i}><dt className="text-muted-foreground">{pick(m.k, lang)}</dt><dd className="min-w-0 break-words">{pick(m.v, lang)}</dd></Fragment>)}
        </dl>
      )}
      <Markdownish text={pick(body, lang)} className="text-xs" />
    </div>
  );
}

export function SafeImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
  if (!/^data:image\/(png|jpe?g|gif|webp|svg\+xml);/i.test(src)) return null;   // CSP: data: only
  return <img src={src} alt={alt} className={cn("max-h-72 w-full rounded-lg border border-border object-contain", className)} />;
}

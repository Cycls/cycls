// A chart in a reply, drawn here in SVG with no library, in the look of shadcn's: column, bar, stacked, line, area, pie,
// donut and treemap. It comes as a ```chart block of JSON or a part ({"type": "chart", "kind", "data"}), in the Design
// tool's format: {"kind", "title"?, "subtitle"?, "source"?, "data": {"labels": […], "series": [{"name", "values": […],
// "color"?}]}, "prefix"?, "suffix"?, "short"?, "values"?}. Pie, donut and treemap draw the first series.
// A person can draw it another way or as a table, hide or pick out a series from its numbers over the chart (a slice
// from its legend), keep the last few of a long run, read any point under the pointer, and take it out: to their
// files, as a picture, or as its numbers.
import { memo, useContext, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { t } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { DropdownMenu } from "../files";
import { CodePart } from "./code-part";
import { FileActions } from "./file-part";
import { csv, download, fileName, picture } from "./export";

type Key = Parameters<typeof t>[0];
const PALETTE = ["#3171F6", "#EF8733", "#10B981", "#8B5CF6", "#F43F5E", "#06B6D4", "#EAB308", "#64748B"];
const KINDS = ["column", "bar", "stacked", "line", "area", "pie", "donut", "treemap"] as const;
type Kind = (typeof KINDS)[number];
type Series = { name: string; color: string; values: number[]; key: number };
export type Chart = {
  kind: Kind; labels: string[]; series: Series[]; title?: string; subtitle?: string; source?: string;
  prefix: string; suffix: string; short: boolean; values: boolean;
};

const text = (v: unknown, n: number) => (typeof v === "string" ? v.slice(0, n) : undefined);

const specOf = (c: Chart, kind: Kind) => ({
  kind, title: c.title, subtitle: c.subtitle, source: c.source, prefix: c.prefix || undefined, suffix: c.suffix || undefined,
  short: c.short || undefined, values: c.values || undefined,
  data: { labels: c.labels, series: c.series.map(({ name, values, color }) => ({ name, values, color })) },
});

/** What a chart says, made safe to draw: up to 8 series over 200 labels, every value a number, colors in hex. */
export function chartOf(raw: unknown): Chart | null {
  const s = (raw && typeof raw === "object" ? raw : {}) as Record<string, any>;
  const labels: string[] = Array.isArray(s.data?.labels) ? s.data.labels.slice(0, 200).map((l: unknown) => String(l ?? "")) : [];
  const series: Series[] = (Array.isArray(s.data?.series) ? s.data.series : [])
    .filter((x: any) => Array.isArray(x?.values)).slice(0, 8)
    .map((x: any, i: number) => ({
      name: String(x.name ?? ""), key: i,
      color: typeof x.color === "string" && /^#[0-9a-f]{3,8}$/i.test(x.color) ? x.color : PALETTE[i % PALETTE.length],
      values: labels.map((_, j) => { const v = Number(x.values[j]); return Number.isFinite(v) ? v : 0; }),
    }));
  if (!labels.length || !series.length) return null;
  return {
    kind: KINDS.includes(s.kind) ? s.kind : "column", labels, series,
    title: text(s.title, 200), subtitle: text(s.subtitle, 300), source: text(s.source, 300),
    prefix: text(s.prefix, 12) ?? "", suffix: text(s.suffix, 12) ?? "", short: s.short === true, values: s.values === true,
  };
}

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const plain = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
const fmt = (c: Chart, v: number, axis = false) => `${c.prefix}${(axis || c.short ? compact : plain).format(v)}${c.suffix}`;
const pct = (d: number) => `${Math.abs(d) >= 100 ? Math.round(Math.abs(d)) : Math.abs(d).toFixed(1)}%`;
const cut = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
// A part's value and its share of the whole, once when they're the same (values given as percentages)
const ofWhole = (c: Chart, v: number, total: number, axis = false) => {
  const value = fmt(c, v, axis), share = `${Math.round((v / (total || 1)) * 100)}%`;
  return value === share ? value : `${value} · ${share}`;
};
const change = (from: number, to: number) => (from ? ((to - from) / Math.abs(from)) * 100 : null);

// Labels in time order (months, days, dates, years, quarters, hours): a change from the first to the last, a total
// and the last few mean something there; over branches or products they don't
const TIME = /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|يناير|فبراير|مارس|أبريل|إبريل|ابريل|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر|محرم|صفر|ربيع|جماد|رجب|شعبان|رمضان|شوال|القعدة|الحجة|^(19|20)\d\d|\d{1,4}[-/.]\d{1,2}|^q[1-4]|الربع|^(w|week|day)\s*\d|يوم|أسبوع|اسبوع|شهر|\d{1,2}:\d\d|^\d+$/i;
const ordered = (c: Chart) => c.kind === "line" || c.kind === "area" || c.labels.filter((l) => TIME.test(l.trim())).length >= c.labels.length * 0.6;

// Round steps (1, 2, 2.5, 5 × 10ⁿ) from below `lo` to past `hi`
function ticks(lo: number, hi: number, count = 4) {
  if (hi === lo) hi = lo + 1;
  const raw = (hi - lo) / count, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((x) => x >= raw)!;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; out.length < 12; v += step) {
    out.push(Number(v.toPrecision(12)));
    if (v >= hi) break;
  }
  return out;
}

// A bar from `base` to `end`, its far end rounded: up or down a column, or along a row
const column = (x: number, w: number, base: number, end: number, r = 4) => {
  const k = Math.min(r, w / 2, Math.abs(base - end)), s = end < base ? 1 : -1;
  return `M${x},${base}V${end + s * k}Q${x},${end} ${x + k},${end}H${x + w - k}Q${x + w},${end} ${x + w},${end + s * k}V${base}Z`;
};
const row = (y: number, h: number, base: number, end: number, r = 4) => {
  const k = Math.min(r, h / 2, Math.abs(end - base)), s = end > base ? 1 : -1;
  return `M${base},${y}H${end - s * k}Q${end},${y} ${end},${y + k}V${y + h - k}Q${end},${y + h} ${end - s * k},${y + h}H${base}Z`;
};

// A line through the points that never overshoots them (monotone, Fritsch–Carlson)
function smooth(p: [number, number][]) {
  const n = p.length;
  if (n < 3) return `M${p.map((q) => q.join(",")).join("L")}`;
  const m = p.slice(1).map((q, i) => (q[1] - p[i][1]) / (q[0] - p[i][0]));
  const t = p.map((_, i) => (i === 0 ? m[0] : i === n - 1 ? m[n - 2] : m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2));
  m.forEach((mi, i) => {
    if (mi === 0) { t[i] = t[i + 1] = 0; return; }
    const a = t[i] / mi, b = t[i + 1] / mi, h = a * a + b * b;
    if (h > 9) { t[i] = (3 / Math.sqrt(h)) * a * mi; t[i + 1] = (3 / Math.sqrt(h)) * b * mi; }
  });
  let d = `M${p[0][0]},${p[0][1]}`;
  for (let i = 0; i < n - 1; i++) {
    const h = (p[i + 1][0] - p[i][0]) / 3;
    d += `C${p[i][0] + h},${p[i][1] + t[i] * h} ${p[i + 1][0] - h},${p[i + 1][1] - t[i + 1] * h} ${p[i + 1][0]},${p[i + 1][1]}`;
  }
  return d;
}

// A slice from angle a0 to a1 (radians, clockwise from twelve o'clock); r0 > 0 leaves the donut's hole
function slice(cx: number, cy: number, r0: number, r1: number, a0: number, a1: number) {
  a1 = Math.min(a1, a0 + 2 * Math.PI - 1e-4);
  const at = (r: number, a: number) => `${cx + r * Math.sin(a)},${cy - r * Math.cos(a)}`;
  const big = a1 - a0 > Math.PI ? 1 : 0;
  return `M${at(r1, a0)}A${r1},${r1} 0 ${big} 1 ${at(r1, a1)}`
    + (r0 > 0 ? `L${at(r0, a1)}A${r0},${r0} 0 ${big} 0 ${at(r0, a0)}Z` : `L${cx},${cy}Z`);
}

const NAME: Record<Kind | "table", Key> = {
  column: "chartColumn", bar: "chartBar", stacked: "chartStacked", line: "chartLine", area: "chartArea",
  pie: "chartPie", donut: "chartDonut", treemap: "chartTreemap", table: "chartTable",
};
const GLYPH: Record<Kind | "table", string> = {
  column: "M6 20V11M12 20V5M18 20v-6",
  bar: "M4 6h9M4 12h16M4 18h6",
  stacked: "M6 20v-4M6 13v-2M12 20v-6M12 11V6M18 20v-3M18 14v-3",
  line: "M3 17l5-6 4 3 5-7 4 4",
  area: "M3 19v-2l5-6 4 3 5-7 4 4v8z",
  pie: "M11 3.05A9 9 0 1020.95 13H11zM13 2.05A9 9 0 0121.95 11H13z",
  donut: "M12 3a9 9 0 110 18 9 9 0 010-18zm0 5a4 4 0 100 8 4 4 0 000-8z",
  treemap: "M3 4h8v9H3zM13 4h8v5h-8zM13 11h8v9h-8zM3 15h8v5H3z",
  table: "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
};
const solid = (k: Kind | "table") => k === "pie" || k === "donut";
const Glyph = ({ k }: { k: Kind | "table" }) => (
  <svg viewBox="0 0 24 24" className="size-3.5" fillRule="evenodd" strokeLinecap="round" strokeLinejoin="round"
       fill={solid(k) || k === "area" ? "currentColor" : "none"} fillOpacity={k === "area" ? 0.35 : 1}
       stroke={solid(k) ? "none" : "currentColor"} strokeWidth={k === "column" || k === "bar" || k === "stacked" ? 3 : 2}>
    <path d={GLYPH[k]} />
  </svg>
);

const Change = ({ d }: { d: number | null }) => d == null || Math.abs(d) < 0.05 ? null : (
  <span className={cn("rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums",
                      d > 0 ? "bg-emerald-500/12 text-emerald-600 dark:text-emerald-400" : "bg-rose-500/12 text-rose-600 dark:text-rose-400")}>
    {d > 0 ? "▲" : "▼"} {pct(d)}
  </span>
);

type Hover = { i: number; x: number; y: number } | null;
type Row = { name: string; color: string; value: string; change?: number | null };

function Tip({ hover, width, title, rows, foot }: { hover: NonNullable<Hover>; width: number; title: string; rows: Row[]; foot?: string }) {
  return (
    <div className="pointer-events-none absolute z-10 min-w-36 rounded-xl border border-border/60 bg-background/95 px-3 py-2 text-xs shadow-xl backdrop-blur"
         style={{ left: hover.x, top: hover.y, transform: `translate(${hover.x > width / 2 ? "calc(-100% - 14px)" : "14px"}, -50%)` }}>
      <p dir="auto" className="mb-1.5 font-semibold text-foreground">{title}</p>
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2 whitespace-nowrap leading-5">
          <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: r.color }} />
          {r.name && <span dir="auto" className="text-muted-foreground">{r.name}</span>}
          <span className="ms-auto ps-3 font-semibold tabular-nums text-foreground">{r.value}</span>
          {r.change != null && Math.abs(r.change) >= 0.05 && (
            <span className={cn("text-[10px] tabular-nums", r.change > 0 ? "text-emerald-500" : "text-rose-500")}>{r.change > 0 ? "▲" : "▼"}{pct(r.change)}</span>
          )}
        </div>
      ))}
      {foot && (
        <div className="mt-1.5 flex justify-between gap-3 border-t border-border/60 pt-1.5 font-semibold">
          <span className="text-muted-foreground">{t("chartTotal")}</span><span className="tabular-nums text-foreground">{foot}</span>
        </div>
      )}
    </div>
  );
}

const point = (e: React.PointerEvent<SVGSVGElement>) => {
  const r = e.currentTarget.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
};

function Cartesian({ c, width, emph, seq }: { c: Chart; width: number; emph: number | null; seq: boolean }) {
  const id = useId().replace(/\W/g, "");
  const [hover, setHover] = useState<Hover>(null);
  const n = c.labels.length, stacked = c.kind === "stacked", bars = c.kind === "column" || stacked, k = c.series.length;
  const tops = c.labels.map((_, j) => c.series.reduce((top, s, i) => (s.values[j] > 0 ? i : top), -1));
  const sums = c.labels.map((_, j) => c.series.reduce((a, s) => a + Math.max(0, s.values[j]), 0));
  const all = stacked ? sums : c.series.flatMap((s) => s.values);
  const tk = ticks(Math.min(0, ...all), Math.max(0, ...all));
  const H = 240, top = 22, bottom = 26, lo = tk[0], hi = tk[tk.length - 1];
  const left = Math.max(...tk.map((v) => fmt(c, v, true).length)) * 6.5 + 12;
  const band = (width - left - 4) / n, plot = H - top - bottom;
  const X = (j: number) => left + band * j + band / 2;
  const Y = (v: number) => top + plot - ((v - lo) / (hi - lo)) * plot;
  const every = Math.max(1, Math.ceil((Math.max(...c.labels.map((l) => Math.min(l.length, 12))) * 6.5 + 10) / band));
  const group = Math.min(band * 0.72, (stacked ? 1 : k) * 48);
  const gap = stacked || k === 1 ? 0 : 3;
  const w = stacked ? group : (group - gap * (k - 1)) / k;
  const base = Y(0);
  const dim = (key: number, j?: number) => Math.min(emph != null && emph !== key ? 0.22 : 1, bars && hover && j != null && hover.i !== j ? 0.4 : 1);
  const peak = !bars && k === 1 && n > 2 ? c.series[0].values.indexOf(Math.max(...c.series[0].values)) : -1;

  return (
    <div className="relative">
      <svg width={width} height={H} role="img" aria-label={c.title || c.kind} className="block touch-pan-y overflow-visible"
           onPointerMove={(e) => { const p = point(e); const i = Math.floor((p.x - left) / band); setHover(i >= 0 && i < n ? { i, ...p } : null); }}
           onPointerLeave={() => setHover(null)}>
        <defs>
          {c.series.map((s) => (
            <linearGradient key={s.key} id={`${id}${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={bars ? 1 : 0.38} />
              <stop offset="100%" stopColor={s.color} stopOpacity={bars ? 0.7 : 0.02} />
            </linearGradient>
          ))}
        </defs>
        {tk.map((v) => (
          <g key={v}>
            <line x1={left} x2={width - 4} y1={Y(v)} y2={Y(v)} className="stroke-border" strokeDasharray={v === 0 ? undefined : "3 4"} />
            <text x={left - 8} y={Y(v)} dy="0.32em" textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">{fmt(c, v, true)}</text>
          </g>
        ))}
        {hover && bars && <rect x={left + band * hover.i + 2} y={top - 8} width={band - 4} height={plot + 8} rx={8} className="fill-secondary" />}
        {hover && !bars && <line x1={X(hover.i)} x2={X(hover.i)} y1={top - 8} y2={top + plot} strokeDasharray="3 3" className="stroke-muted-foreground/50" />}
        {bars ? c.series.map((s, i) => (
          <g key={s.key} fill={`url(#${id}${s.key})`}>
            {s.values.map((v, j) => {
              const below = stacked ? c.series.slice(0, i).reduce((a, q) => a + Math.max(0, q.values[j]), 0) : 0;
              const x = left + band * j + (band - group) / 2 + (stacked ? 0 : i * (w + gap));
              const from = stacked ? Y(below) : base, to = stacked ? Y(below + Math.max(0, v)) : Y(v);
              return from === to ? null : (
                <path key={j} d={column(x, w, from, to, stacked && tops[j] !== i ? 0 : 5)} className="chart-rise chart-morph" style={{ opacity: dim(s.key, j) }} />
              );
            })}
            {c.values && !stacked && s.values.map((v, j) => (
              <text key={`v${j}`} x={left + band * j + (band - group) / 2 + i * (w + gap) + w / 2} y={Y(v) - 6} textAnchor="middle"
                    className="fill-foreground text-[10px] font-semibold tabular-nums">{fmt(c, v, true)}</text>
            ))}
          </g>
        )) : c.series.map((s) => {
          const pts = s.values.map((v, j): [number, number] => [X(j), Y(v)]);
          const d = smooth(pts);
          return (
            <g key={s.key} style={{ opacity: dim(s.key) }} className="chart-morph">
              {c.kind === "area" && <path d={`${d}L${pts[n - 1][0]},${base}L${pts[0][0]},${base}Z`} fill={`url(#${id}${s.key})`} className="chart-fade chart-morph" />}
              <path d={d} fill="none" stroke={s.color} strokeWidth={8} strokeOpacity={0.12} strokeLinecap="round" className="chart-fade chart-morph" />
              <path d={d} fill="none" stroke={s.color} strokeWidth={2.25} strokeLinecap="round" pathLength={1} className="chart-draw chart-morph" />
              {(n === 1 || (c.kind === "line" && n <= 16)) && pts.map(([x, y], j) => (
                <circle key={j} cx={x} cy={y} r={3} fill={s.color} strokeWidth={1.5} className="stroke-background chart-fade" />
              ))}
              {c.values && pts.map(([x, y], j) => (
                <text key={`v${j}`} x={x} y={y - 10} textAnchor="middle" className="fill-foreground text-[10px] font-semibold tabular-nums">{fmt(c, s.values[j], true)}</text>
              ))}
              {hover && <circle cx={pts[hover.i][0]} cy={pts[hover.i][1]} r={5} fill={s.color} strokeWidth={2.5} className="stroke-background" />}
            </g>
          );
        })}
        {peak >= 0 && !hover && (() => {
          const s = c.series[0], x = X(peak), y = Y(s.values[peak]), label = fmt(c, s.values[peak], true), pw = label.length * 6.2 + 14;
          const px = Math.min(Math.max(x - pw / 2, left), width - pw);
          return (
            <g className="chart-fade" pointerEvents="none">
              <circle cx={x} cy={y} r={4} fill={s.color} strokeWidth={2} className="stroke-background" />
              <rect x={px} y={y - 25} width={pw} height={17} rx={8.5} className="fill-foreground" />
              <text x={px + pw / 2} y={y - 16.5} dy="0.32em" textAnchor="middle" className="fill-background text-[10px] font-semibold tabular-nums">{label}</text>
            </g>
          );
        })()}
        {c.labels.map((l, j) => j % every === 0 && (
          <text key={j} x={X(j)} y={H - 8} textAnchor="middle"
                className={cn("text-[11px]", hover?.i === j ? "fill-foreground font-medium" : "fill-muted-foreground")}>{cut(l, 12)}</text>
        ))}
      </svg>
      {hover && (
        <Tip hover={hover} width={width} title={c.labels[hover.i]}
             rows={c.series.map((s) => ({ name: s.name, color: s.color, value: fmt(c, s.values[hover.i]),
                                          change: seq && hover.i ? change(s.values[hover.i - 1], s.values[hover.i]) : null }))}
             foot={stacked && k > 1 ? fmt(c, sums[hover.i]) : undefined} />
      )}
    </div>
  );
}

function Rows({ c, width, emph }: { c: Chart; width: number; emph: number | null }) {
  const id = useId().replace(/\W/g, "");
  const [hover, setHover] = useState<Hover>(null);
  const k = c.series.length, rowH = k > 1 ? 12 * k + 14 : 34, bar = (rowH - 12 - 2 * (k - 1)) / k;
  const all = c.series.flatMap((s) => s.values), lo = Math.min(0, ...all), hi = Math.max(0, ...all) || 1;
  const labelW = Math.min(140, Math.max(...c.labels.map((l) => Math.min(l.length, 20))) * 6.5 + 12);
  const room = width - labelW - Math.max(...all.map((v) => fmt(c, v, true).length)) * 6.5 - 14;
  const X = (v: number) => labelW + ((v - lo) / (hi - lo)) * room;
  const H = c.labels.length * rowH + 4;
  return (
    <div className="relative">
      <svg width={width} height={H} role="img" aria-label={c.title || c.kind} className="block touch-pan-y overflow-visible"
           onPointerMove={(e) => { const p = point(e); const i = Math.floor(p.y / rowH); setHover(i >= 0 && i < c.labels.length ? { i, ...p } : null); }}
           onPointerLeave={() => setHover(null)}>
        <defs>
          {c.series.map((s) => (
            <linearGradient key={s.key} id={`${id}${s.key}`} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.7} /><stop offset="100%" stopColor={s.color} />
            </linearGradient>
          ))}
        </defs>
        {hover && <rect x={0} y={hover.i * rowH + 2} width={width} height={rowH - 4} rx={8} className="fill-secondary" />}
        {c.labels.map((l, j) => (
          <text key={j} x={labelW - 10} y={j * rowH + rowH / 2} dy="0.32em" textAnchor="end"
                className={cn("text-[11px]", hover?.i === j ? "fill-foreground font-medium" : "fill-muted-foreground")}>{cut(l, 20)}</text>
        ))}
        {c.series.map((s, i) => s.values.map((v, j) => {
          const y = j * rowH + 6 + i * (bar + 2);
          const fade = Math.min(emph != null && emph !== s.key ? 0.22 : 1, hover && hover.i !== j ? 0.4 : 1);
          return (
            <g key={`${s.key}.${j}`} style={{ opacity: fade }} className="chart-morph">
              {v !== 0 && <path d={row(y, bar, X(0), X(v))} fill={`url(#${id}${s.key})`} className="chart-grow chart-morph" />}
              <text x={X(Math.max(0, v)) + 6} y={y + bar / 2} dy="0.32em" className="fill-foreground text-[11px] font-semibold tabular-nums">{fmt(c, v, true)}</text>
            </g>
          );
        }))}
      </svg>
      {hover && <Tip hover={hover} width={width} title={c.labels[hover.i]}
                     rows={c.series.map((s) => ({ name: s.name, color: s.color, value: fmt(c, s.values[hover.i]) }))} />}
    </div>
  );
}

type Slice = { label: string; value: number; color: string; key: number };

function Round({ c, slices, width, emph }: { c: Chart; slices: Slice[]; width: number; emph: number | null }) {
  const [hover, setHover] = useState<Hover>(null);
  const total = slices.reduce((a, s) => a + s.value, 0);
  const size = Math.min(width, 260), R = size / 2 - 10, hole = c.kind === "donut" ? R * 0.64 : 0, cx = width / 2, cy = size / 2;
  let a = 0;
  const parts = slices.map((s) => { const a0 = a; a += total ? (s.value / total) * 2 * Math.PI : 0; return [a0, a] as const; });
  const at = (p: { x: number; y: number }) => {
    const dx = p.x - cx, dy = p.y - cy, d = Math.hypot(dx, dy);
    if (d > R + 6 || d < hole) return -1;
    const ang = (Math.atan2(dx, -dy) + 2 * Math.PI) % (2 * Math.PI);
    return parts.findIndex(([a0, a1]) => ang >= a0 && ang < a1);
  };
  const lit = hover ? slices[hover.i]?.key : emph;
  const focus = slices.find((s) => s.key === lit);
  const share = (v: number) => Math.round((v / (total || 1)) * 100);
  return (
    <div className="relative">
      <svg width={width} height={size} role="img" aria-label={c.title || c.kind} className="block touch-pan-y overflow-visible chart-fade"
           onPointerMove={(e) => { const p = point(e); const i = at(p); setHover(i >= 0 ? { i, ...p } : null); }}
           onPointerLeave={() => setHover(null)}>
        {parts.map(([a0, a1], i) => a1 > a0 && (
          <path key={slices[i].key} d={slice(cx, cy, hole, slices[i].key === lit ? R + 7 : R, a0, a1)} fill={slices[i].color} strokeWidth={2.5}
                className="stroke-background chart-morph" style={{ opacity: lit != null && slices[i].key !== lit ? 0.5 : 1 }} />
        ))}
        {hole > 0 && (
          <text x={cx} y={cy} textAnchor="middle">
            <tspan x={cx} dy="-0.15em" className="fill-foreground text-2xl font-semibold tabular-nums">{fmt(c, focus ? focus.value : total, true)}</tspan>
            <tspan x={cx} dy="1.7em" className="fill-muted-foreground text-xs">
              {focus ? `${cut(focus.label, 18)} · ${share(focus.value)}%` : cut(c.series[0].name || t("chartTotal"), 24)}
            </tspan>
          </text>
        )}
      </svg>
      {hover && !hole && <Tip hover={hover} width={width} title={slices[hover.i].label}
                              rows={[{ name: "", color: slices[hover.i].color, value: ofWhole(c, slices[hover.i].value, total) }]} />}
    </div>
  );
}

// Boxes sized by their value, biggest first, each row as near square as it goes (squarified)
function squarify(items: { key: number; value: number }[], x: number, y: number, w: number, h: number) {
  const total = items.reduce((a, i) => a + i.value, 0), out: { key: number; x: number; y: number; w: number; h: number }[] = [];
  if (!total) return out;
  const rest = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value).map((i) => ({ key: i.key, area: (i.value / total) * w * h }));
  while (rest.length) {
    const side = Math.min(w, h);
    const worst = (row: typeof rest) => {
      const s = row.reduce((a, r) => a + r.area, 0);
      return Math.max(...row.map((r) => Math.max((side * side * r.area) / (s * s), (s * s) / (side * side * r.area))));
    };
    const row = [rest.shift()!];
    while (rest.length && worst([...row, rest[0]]) <= worst(row)) row.push(rest.shift()!);
    const thick = row.reduce((a, r) => a + r.area, 0) / side;
    let at = 0;
    for (const r of row) {
      const len = r.area / thick;
      out.push(w >= h ? { key: r.key, x, y: y + at, w: thick, h: len } : { key: r.key, x: x + at, y, w: len, h: thick });
      at += len;
    }
    if (w >= h) { x += thick; w -= thick; } else { y += thick; h -= thick; }
  }
  return out;
}

function Tiles({ c, slices, width, emph }: { c: Chart; slices: Slice[]; width: number; emph: number | null }) {
  const id = useId().replace(/\W/g, "");
  const [hover, setHover] = useState<Hover>(null);
  const H = Math.round(Math.min(320, Math.max(220, width * 0.55)));
  const total = slices.reduce((a, s) => a + s.value, 0);
  const boxes = squarify(slices, 0, 0, width, H);
  const of = (key: number) => slices.find((s) => s.key === key)!;
  const lit = hover ? boxes[hover.i]?.key : emph;
  const on = hover && of(boxes[hover.i].key);
  return (
    <div className="relative">
      <svg width={width} height={H} role="img" aria-label={c.title || c.kind} className="block touch-pan-y overflow-visible"
           onPointerMove={(e) => { const p = point(e); const i = boxes.findIndex((b) => p.x >= b.x && p.x < b.x + b.w && p.y >= b.y && p.y < b.y + b.h); setHover(i >= 0 ? { i, ...p } : null); }}
           onPointerLeave={() => setHover(null)}>
        <defs>
          {slices.map((s) => (
            <linearGradient key={s.key} id={`${id}${s.key}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor={s.color} /><stop offset="100%" stopColor={s.color} stopOpacity={0.78} />
            </linearGradient>
          ))}
        </defs>
        {boxes.map((b) => {
          const s = of(b.key), w = Math.max(0, b.w - 3), h = Math.max(0, b.h - 3);
          return (
            <g key={b.key} style={{ opacity: lit != null && lit !== b.key ? 0.45 : 1 }} className="chart-morph">
              <rect x={b.x + 1.5} y={b.y + 1.5} width={w} height={h} rx={8} fill={`url(#${id}${b.key})`} className="chart-fade chart-morph" />
              {w > 70 && h > 42 && (
                <text className="fill-white">
                  <tspan x={b.x + 12} y={b.y + 22} className="text-xs font-semibold">{cut(s.label, Math.floor(w / 7.5))}</tspan>
                  <tspan x={b.x + 12} dy="1.45em" className="fill-white/80 text-[11px] font-medium tabular-nums">{ofWhole(c, s.value, total, true)}</tspan>
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {hover && on && <Tip hover={hover} width={width} title={on.label} rows={[{ name: "", color: on.color, value: ofWhole(c, on.value, total) }]} />}
    </div>
  );
}

function Table({ head, rows, foot }: { head: { text: string; color?: string }[]; rows: string[][]; foot?: string[] }) {
  const side = (i: number) => (i ? "text-end" : "text-start");
  return (
    <div className="max-h-80 overflow-auto rounded-xl border border-border chart-fade">
      <table className="w-full text-xs tabular-nums">
        <thead className="sticky top-0 bg-secondary">
          <tr>{head.map((h, i) => (
            <th key={i} className={cn("px-3 py-2 font-medium text-muted-foreground", side(i))}>
              <span className="inline-flex items-center gap-1.5">{h.color && <span className="size-2 rounded-full" style={{ background: h.color }} />}<bdi>{h.text}</bdi></span>
            </th>
          ))}</tr>
        </thead>
        <tbody>{rows.map((r, j) => (
          <tr key={j} className="border-t border-border hover:bg-secondary/50">
            {r.map((v, i) => <td key={i} className={cn("px-3 py-1.5", side(i), i ? "text-foreground" : "text-muted-foreground")}><bdi>{v}</bdi></td>)}
          </tr>
        ))}</tbody>
        {foot && <tfoot><tr className="border-t border-border font-semibold">{foot.map((v, i) => <td key={i} className={cn("px-3 py-2 text-foreground", side(i))}>{v}</td>)}</tr></tfoot>}
      </table>
    </div>
  );
}

export const DataChart = memo(function DataChart({ chart: c }: { chart: Chart }) {
  const whole = c.kind === "pie" || c.kind === "donut" || c.kind === "treemap";   // parts of a whole: the first series
  const kinds = (whole ? ["donut", "pie", "treemap"] : ["column", "line", "area", ...(c.series.length > 1 ? ["stacked"] : []), ...(c.kind === "bar" ? ["bar"] : [])]) as Kind[];
  const [kind, setKind] = useState<Kind>(c.kind);
  const [table, setTable] = useState(false);
  const [hidden, setHidden] = useState<number[]>([]);   // series, or a pie's slices, put away
  const [emph, setEmph] = useState<number | null>(null);   // the one under the pointer in the numbers or the legend
  const [range, setRange] = useState(0);   // the last few labels; 0, all of them
  const [menu, setMenu] = useState(false);
  const files = useContext(FileActions);
  const box = useRef<HTMLDivElement>(null);
  const [measured, setMeasured] = useState(0);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setMeasured(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(([e]) => setMeasured(Math.round(e.contentRect.width)));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const width = measured || 480;
  const n = c.labels.length, seq = !whole && ordered(c);
  const ranges = seq && kind !== "bar" ? [7, 12, 30, 90].filter((r) => r < n).slice(-2) : [];
  const from = range && range < n ? n - range : 0;
  const view: Chart = useMemo(() => ({
    ...c, kind, labels: c.labels.slice(from),
    series: c.series.filter((s) => !hidden.includes(s.key)).map((s) => ({ ...s, values: s.values.slice(from) })),
  }), [c, kind, from, hidden]);
  const slices = whole ? c.labels.map((label, i) => ({ label, value: Math.max(0, c.series[0].values[i]), color: PALETTE[i % PALETTE.length], key: i })) : [];
  const shown = slices.filter((s) => !hidden.includes(s.key)), sliceTotal = shown.reduce((a, s) => a + s.value, 0);
  const sum = c.kind !== "line" && c.kind !== "area";   // its numbers are totals; a line's or an area's, where it ended
  const toggle = (key: number, count: number) =>
    setHidden((h) => (h.includes(key) ? h.filter((x) => x !== key) : h.length < count - 1 ? [...h, key] : h));
  const grid = whole
    ? { head: [{ text: "" }, { text: c.series[0].name || t("chartTotal") }, { text: "%" }],
        rows: shown.map((s) => [s.label, fmt(c, s.value), `${Math.round((s.value / (sliceTotal || 1)) * 100)}%`]),
        foot: [t("chartTotal"), fmt(c, sliceTotal), "100%"] }
    : { head: [{ text: "" }, ...view.series.map((s) => ({ text: s.name, color: s.color }))],
        rows: view.labels.map((l, j) => [l, ...view.series.map((s) => fmt(c, s.values[j]))]),
        foot: seq && sum ? [t("chartTotal"), ...view.series.map((s) => fmt(c, s.values.reduce((a, b) => a + b, 0)))] : undefined };
  const name = fileName(c.title, "chart");
  const save = files?.save && (() => files.save!(`charts/${name}.md`, "```chart\n" + JSON.stringify(specOf(c, kind), null, 2) + "\n```\n"));
  const image = async () => {
    if (table) { setTable(false); await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); }
    const svg = box.current?.querySelector<SVGSVGElement>("svg[role=img]");
    const legend = whole ? (kind === "treemap" ? [] : shown.map((s) => ({ name: s.label, color: s.color })))
      : view.series.length > 1 ? view.series.map((s) => ({ name: s.name, color: s.color })) : [];
    if (svg) download(await picture(svg, { title: c.title, subtitle: c.subtitle, legend, source: c.source }), `${name}.png`);
  };
  const data = () => download(csv(whole ? [["", c.series[0].name || t("chartTotal")], ...slices.map((s) => [s.label, s.value])]
    : [["", ...c.series.map((s) => s.name)], ...c.labels.map((l, j) => [l, ...c.series.map((s) => s.values[j])])]), `${name}.csv`);

  return (
    <figure className="not-prose my-4 rounded-2xl border border-border bg-background p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <figcaption className="min-w-0 flex-1">
          {c.title && <p dir="auto" className="text-sm font-semibold text-foreground">{c.title}</p>}
          {c.subtitle && <p dir="auto" className="mt-0.5 text-xs text-muted-foreground">{c.subtitle}</p>}
        </figcaption>
        <div dir="ltr" className="flex shrink-0 items-center gap-0.5 rounded-lg bg-secondary p-0.5">
          {[...kinds, "table" as const].map((k) => {
            const on = k === "table" ? table : !table && kind === k;
            return (
              <button key={k} onClick={() => { if (k === "table") setTable((v) => !v); else { setKind(k); setTable(false); } }}
                      aria-pressed={on} aria-label={t(NAME[k])} title={t(NAME[k])}
                      className={cn("flex size-7 cursor-pointer items-center justify-center rounded-md transition-colors",
                                    on ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                <Glyph k={k} />
              </button>
            );
          })}
        </div>
        <div className="relative shrink-0">
          <button onClick={() => setMenu((v) => !v)} aria-label={t("download")} title={t("download")}
                  className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 4v11m0 0l-4-4m4 4l4-4M5 20h14" />
            </svg>
          </button>
          {menu && (
            <DropdownMenu onClose={() => setMenu(false)} items={[
              ...(save ? [{ label: t("chartSave"), onClick: save }] : []),
              { label: t("chartImage"), onClick: () => void image() },
              { label: t("chartData"), onClick: data },
            ]} />
          )}
        </div>
      </div>
      {!whole && (
        <div className="mt-3 flex flex-wrap gap-2">
          {c.series.map((s) => {
            const v = s.values.slice(from), off = hidden.includes(s.key), many = c.series.length > 1;
            const top = v.indexOf(Math.max(...v));   // over branches or products: the one ahead
            return (
              <button key={s.key} onClick={() => many && toggle(s.key, c.series.length)} aria-pressed={!off}
                      onPointerEnter={() => many && !off && setEmph(s.key)} onPointerLeave={() => setEmph(null)}
                      className={cn("min-w-0 rounded-xl border px-3 py-2 text-start transition", off ? "border-dashed border-border opacity-45" : "border-border",
                                    many ? "cursor-pointer hover:bg-secondary/60" : "cursor-default")}>
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="size-2 shrink-0 rounded-full" style={{ background: s.color }} /><bdi className="truncate">{s.name || c.title}</bdi>
                </span>
                <span className="mt-0.5 flex items-center gap-2">
                  <span className="text-lg font-semibold leading-7 tabular-nums text-foreground">
                    {fmt(c, !seq ? v[top] : sum ? v.reduce((a, b) => a + b, 0) : v[v.length - 1], true)}
                  </span>
                  {seq ? <Change d={change(v[0], v[v.length - 1])} /> : <bdi className="truncate text-xs text-muted-foreground">{c.labels[from + top]}</bdi>}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {ranges.length > 0 && !table && (
        <div className="mt-3 flex gap-1">
          {[0, ...ranges].map((r) => (
            <button key={r} onClick={() => setRange(r)} aria-pressed={range === r}
                    className={cn("cursor-pointer rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                                  range === r ? "bg-foreground text-background" : "bg-secondary text-muted-foreground hover:text-foreground")}>
              {r ? t("chartLast").replace("{n}", String(r)) : t("chartAll")}
            </button>
          ))}
        </div>
      )}
      <div ref={box} dir={table ? undefined : "ltr"} className="mt-4">
        {table ? <Table {...grid} />
          : whole ? (kind === "treemap" ? <Tiles c={view} slices={shown} width={width} emph={emph} /> : <Round c={view} slices={shown} width={width} emph={emph} />)
          : view.kind === "bar" ? <Rows c={view} width={width} emph={emph} />
          : <Cartesian c={view} width={width} emph={emph} seq={seq} />}
      </div>
      {whole && !table && (
        <div className="mt-3 flex flex-wrap justify-center gap-1.5">
          {slices.map((s) => {
            const off = hidden.includes(s.key);
            return (
              <button key={s.key} onClick={() => toggle(s.key, slices.length)} aria-pressed={!off}
                      onPointerEnter={() => !off && setEmph(s.key)} onPointerLeave={() => setEmph(null)}
                      className={cn("flex cursor-pointer items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs transition hover:bg-secondary/60",
                                    off && "border-dashed opacity-45")}>
                <span className="size-2 rounded-full" style={{ background: s.color }} /><bdi className="text-foreground">{cut(s.label, 22)}</bdi>
                {!off && <span className="tabular-nums text-muted-foreground">{Math.round((s.value / (sliceTotal || 1)) * 100)}%</span>}
              </button>
            );
          })}
        </div>
      )}
      {c.source && <p dir="auto" className="mt-3 text-xs text-muted-foreground">{c.source}</p>}
    </figure>
  );
});

// A ```chart block in a reply: drawn once its JSON is whole, a placeholder while it streams, and the JSON itself if
// it never becomes a chart.
export function ChartBlock({ code, done }: { code: string; done: boolean }) {
  const chart = useMemo(() => { try { return chartOf(JSON.parse(code)); } catch { return null; } }, [code]);
  if (chart) return <DataChart chart={chart} />;
  if (!done) return <div className="not-prose my-4 h-80 animate-pulse rounded-2xl border border-border bg-secondary/30" />;
  return <CodePart code={code} language="json" className="bg-background" />;
}

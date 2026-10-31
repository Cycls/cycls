import { memo, useEffect, useRef, useState } from "react";
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { fetchAuthed } from "../../hooks/use-auth-headers";
import { useDarkMode } from "../../hooks/use-dark-mode";
import type { ChartMarker, ChartSeries, Part } from "../../hooks/use-chat";

// A chart a tool sent (`{"type": "chart", series, markers, live}`), drawn with TradingView's Lightweight Charts.
// A series is candles ([time, open, high, low, close]), a line or an area ([time, value]), or bars under it
// ([time, value]); `pane` stacks it below the first. Time is "YYYY-MM-DD" for days, epoch seconds for intraday.
// `live.url` is polled (with the person's sign-in) while the chart is on screen, and the answer moves the last
// point of the first series: {time, value} or {time, open, high, low, close}.

const PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"];
const UP = "#16a34a";
const DOWN = "#dc2626";

type Point = Record<string, number | string>;

function points(s: ChartSeries): Point[] {
  return (s.data || []).map((d): Point =>
    s.kind === "candles"
      ? { time: d[0], open: d[1], high: d[2], low: d[3], close: d[4] }
      : { time: d[0], value: d[1] },
  );
}

function addSeries(chart: IChartApi, s: ChartSeries, i: number, precision: number): ISeriesApi<SeriesType> {
  const color = s.color || PALETTE[i % PALETTE.length];
  const priceFormat = { type: "price" as const, precision, minMove: 1 / 10 ** precision };
  const pane = s.pane || 0;
  if (s.kind === "candles")
    return chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, wickUpColor: UP, wickDownColor: DOWN, borderVisible: false, priceFormat,
    }, pane);
  if (s.kind === "histogram")
    return chart.addSeries(HistogramSeries, { color: `${color}88`, priceFormat: { type: "volume" }, lastValueVisible: false }, pane);
  if (s.kind === "area")
    return chart.addSeries(AreaSeries, {
      lineColor: color, topColor: `${color}55`, bottomColor: `${color}05`, lineWidth: 2, priceFormat,
    }, pane);
  return chart.addSeries(LineSeries, { color, lineWidth: 2, priceFormat }, pane);
}

export const ChartPart = memo(function ChartPart({ part }: { part: Part }) {
  const box = useRef<HTMLDivElement>(null);
  const first = useRef<ISeriesApi<SeriesType> | null>(null);
  const dark = useDarkMode();
  const [liveAt, setLiveAt] = useState<string | null>(null);
  const series = part.series || [];
  const panes = Math.max(0, ...series.map((s) => s.pane || 0));

  useEffect(() => {
    if (!box.current || !series.length) return;
    const text = dark ? "#a1a1aa" : "#52525b";
    const grid = dark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
    const intraday = series.some((s) => typeof s.data?.[0]?.[0] === "number");
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text, fontFamily: "inherit" },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: intraday },
      crosshair: { horzLine: { labelBackgroundColor: text }, vertLine: { labelBackgroundColor: text } },
    });
    const made = series.map((s, i) => {
      const api = addSeries(chart, s, i, part.precision ?? 2);
      api.setData(points(s) as never);
      return api;
    });
    first.current = made[0];
    const marks = (part.markers || []).filter((m: ChartMarker) => m.time !== undefined);
    if (marks.length) {
      const bySeries = new Map<number, SeriesMarker<Time>[]>();
      for (const m of marks) {
        const list = bySeries.get(m.series || 0) || [];
        list.push({
          time: m.time as Time,
          position: m.position || "aboveBar",
          shape: m.shape || "circle",
          color: m.color || (dark ? "#e4e4e7" : "#3f3f46"),
          text: m.text,
        });
        bySeries.set(m.series || 0, list);
      }
      for (const [i, list] of bySeries)
        if (made[i]) createSeriesMarkers(made[i], list.sort((a, b) => String(a.time).localeCompare(String(b.time))));
    }
    chart.timeScale().fitContent();
    return () => {
      first.current = null;
      chart.remove();
    };
  }, [part, dark]); // eslint-disable-line react-hooks/exhaustive-deps

  // Live: poll while the tab is visible; three failures in a row stop it.
  useEffect(() => {
    const live = part.live;
    if (!live?.url) return;
    let failures = 0;
    let stopped = false;
    const tick = async () => {
      if (stopped || document.hidden || !first.current) return;
      try {
        const res = await fetchAuthed(live.url);
        if (!res.ok) throw new Error(String(res.status));
        const p = await res.json();
        if (p && p.time !== undefined && first.current) {
          first.current.update((series[0]?.kind === "candles"
            ? { time: p.time, open: p.open, high: p.high, low: p.low, close: p.close ?? p.value }
            : { time: p.time, value: p.value ?? p.close }) as never);
          setLiveAt(p.at || new Date().toLocaleTimeString());
        }
        failures = 0;
      } catch {
        if (++failures >= 3) stopped = true;
      }
    };
    tick();
    const timer = window.setInterval(tick, Math.max(5, live.every || 15) * 1000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [part.live?.url]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!series.length) return null;
  return (
    <div dir="ltr" className="my-3 rounded-xl border border-border p-3">
      {(part.title || part.subtitle || part.live) && (
        <div className="mb-2 flex items-start justify-between gap-3">
          <div dir="auto" className="min-w-0">
            {part.title && <div className="font-medium text-foreground">{part.title}</div>}
            {part.subtitle && <div className="text-xs text-muted-foreground">{part.subtitle}</div>}
          </div>
          {part.live && (
            <div className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground" title={liveAt || undefined}>
              <span className="relative flex size-2">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-green-500 opacity-60" />
                <span className="relative inline-flex size-2 rounded-full bg-green-500" />
              </span>
              {liveAt || "live"}
            </div>
          )}
        </div>
      )}
      <div ref={box} style={{ height: 300 + panes * 110 }} />
      {(part.source || part.as_of) && (
        <div dir="auto" className="mt-2 text-xs text-muted-foreground">
          {[part.source, part.as_of].filter(Boolean).join(" · ")}
        </div>
      )}
    </div>
  );
});

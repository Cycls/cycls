// A flowchart in a reply (a ```flowchart block of JSON), laid out and drawn here with no library: steps in layers,
// fewer crossings, a long arrow led around the steps it skips. {"title"?, "subtitle"?, "direction"?: "down" | "right",
// "nodes": [{"id", "label", "shape"?: "start" | "step" | "decision" | "end" | "note", "note"?}], "edges": [{"from",
// "to", "label"?}]}. An org chart or a mind map is one too. Hovering or tapping a step lights its path, before and
// after it; it turns to run down or across (right to left in Arabic), and goes to the person's files or a picture.
import { memo, useContext, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { t } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { dirOf } from "../../lib/bidi";
import { DropdownMenu } from "../files";
import { CodePart } from "./code-part";
import { FileActions } from "./file-part";
import { download, fileName, picture } from "./export";

const SHAPES = ["start", "step", "decision", "end", "note"] as const;
type Shape = (typeof SHAPES)[number];
type Node = { id: string; label: string; shape: Shape; note?: string };
type Edge = { from: string; to: string; label?: string };
export type Flow = { title?: string; subtitle?: string; direction: "down" | "right"; nodes: Node[]; edges: Edge[] };

const text = (v: unknown, n: number) => (typeof v === "string" && v.trim() ? v.trim().slice(0, n) : undefined);

/** A flowchart made safe to draw: up to 80 steps and 160 arrows, every arrow between two steps it names. */
export function flowOf(raw: unknown): Flow | null {
  const f = (raw && typeof raw === "object" ? raw : {}) as Record<string, any>;
  const seen = new Set<string>();
  const nodes: Node[] = (Array.isArray(f.nodes) ? f.nodes : []).flatMap((n: any) => {
    const id = n && (typeof n.id === "string" || typeof n.id === "number") ? String(n.id) : "";
    if (!id || seen.has(id) || seen.size >= 80) return [];
    seen.add(id);
    return [{ id, label: text(n.label, 90) ?? id, shape: SHAPES.includes(n.shape) ? n.shape : "step", note: text(n.note, 300) }];
  });
  const edges: Edge[] = (Array.isArray(f.edges) ? f.edges : []).flatMap((e: any) => {
    const from = String(e?.from ?? ""), to = String(e?.to ?? "");
    return seen.has(from) && seen.has(to) && from !== to ? [{ from, to, label: text(e.label, 40) }] : [];
  }).slice(0, 160);
  if (!nodes.length) return null;
  return {
    title: text(f.title, 200), subtitle: text(f.subtitle, 300), nodes, edges,
    direction: /^(right|left|across|horizontal|lr|rl)$/i.test(String(f.direction ?? "")) ? "right" : "down",
  };
}

let pen: CanvasRenderingContext2D | null | undefined;
function measure(s: string, size: number, weight = 500) {
  if (pen === undefined) { try { pen = document.createElement("canvas").getContext("2d"); } catch { pen = null; } }
  if (!pen) return s.length * size * 0.55;
  pen.font = `${weight} ${size}px ${getComputedStyle(document.body).fontFamily}`;
  return pen.measureText(s).width;
}
function wrap(label: string, max: number) {
  const lines: string[] = [];
  let line = "";
  for (const w of label.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${w}` : w;
    if (line && measure(next, 13) > max) { lines.push(line); line = w; } else line = next;
  }
  if (line) lines.push(line);
  return lines.slice(0, 4);
}

type Placed = { id: string; x: number; y: number; w: number; h: number; rank: number; lines: string[]; node: Node };
type Route = { edge: Edge; d: string; at: [number, number]; rank: number; i: number };

// Steps in layers by their longest way from a start, a loop's way back set aside so it can't pull a step down; each
// layer ordered by where its neighbors sit, a few times each way; then each step pulled toward its neighbors, keeping
// its layer's order and gaps. An arrow that skips layers goes through a waypoint in each, so it keeps clear of steps.
function layout(f: Flow, rtl: boolean) {
  const across = f.direction === "right", GAP = 28, RANK = 52;
  const size = new Map(f.nodes.map((n) => {
    const lines = wrap(n.label, n.shape === "decision" ? 120 : 150);
    const tw = Math.max(...lines.map((l) => measure(l, 13))), th = lines.length * 18;
    const [w, h] = n.shape === "decision" ? [Math.max(130, tw + 70), Math.max(76, th + 46)] : [Math.max(96, tw + 34), Math.max(42, th + 22)];
    return [n.id, { w, h, lines }];
  }));
  const out = new Map<string, Edge[]>();
  f.edges.forEach((e) => out.set(e.from, [...(out.get(e.from) || []), e]));
  const state = new Map<string, number>(), back = new Set<Edge>();
  const walk = (v: string) => {
    state.set(v, 1);
    for (const e of out.get(v) || []) { const s = state.get(e.to); if (s === 1) back.add(e); else if (!s) walk(e.to); }
    state.set(v, 2);
  };
  f.nodes.forEach((n) => { if (!state.get(n.id)) walk(n.id); });

  const rank = new Map(f.nodes.map((n) => [n.id, 0]));
  const need = new Map(f.nodes.map((n) => [n.id, 0]));
  const forward = f.edges.filter((e) => !back.has(e));
  forward.forEach((e) => need.set(e.to, need.get(e.to)! + 1));
  const ready = f.nodes.filter((n) => !need.get(n.id)).map((n) => n.id);
  while (ready.length) {
    const v = ready.shift()!;
    for (const e of forward) if (e.from === v) {
      rank.set(e.to, Math.max(rank.get(e.to)!, rank.get(v)! + 1));
      need.set(e.to, need.get(e.to)! - 1);
      if (!need.get(e.to)) ready.push(e.to);
    }
  }

  const layers: string[][] = [];
  const put = (id: string, r: number) => (layers[r] ||= []).push(id);
  f.nodes.forEach((n) => put(n.id, rank.get(n.id)!));
  const chains = f.edges.map((e, i) => {
    const [a, b] = back.has(e) ? [e.to, e.from] : [e.from, e.to];
    const ids = [a];
    for (let r = rank.get(a)! + 1; r < rank.get(b)!; r++) { put(`~${i}.${r}`, r); ids.push(`~${i}.${r}`); }
    ids.push(b);
    return { edge: e, ids, back: back.has(e), i };
  });
  const up = new Map<string, string[]>(), down = new Map<string, string[]>();
  const link = (m: Map<string, string[]>, k: string, v: string) => m.set(k, [...(m.get(k) || []), v]);
  chains.forEach((c) => c.ids.slice(1).forEach((id, j) => { link(down, c.ids[j], id); link(up, id, c.ids[j]); }));

  const pos = new Map<string, number>();
  layers.forEach((l) => l.forEach((id, i) => pos.set(id, i)));
  const mean = (ids: string[] | undefined, at: Map<string, number>) => (ids?.length ? ids.reduce((a, id) => a + at.get(id)!, 0) / ids.length : null);
  for (let pass = 0; pass < 6; pass++) {
    const by = pass % 2 ? down : up;
    for (const r of pass % 2 ? [...layers.keys()].reverse() : [...layers.keys()]) {
      const want = new Map(layers[r].map((id) => [id, mean(by.get(id), pos) ?? pos.get(id)!]));
      layers[r].sort((a, b) => want.get(a)! - want.get(b)!).forEach((id, i) => pos.set(id, i));
    }
  }

  const dim = (id: string) => (id.startsWith("~") ? { w: 6, h: 6 } : size.get(id)!);
  const along = (id: string) => (across ? dim(id).w : dim(id).h), side = (id: string) => (across ? dim(id).h : dim(id).w);
  const level: number[] = [];
  let reach = 0;
  layers.forEach((l, r) => { const thick = Math.max(...l.map(along)); level[r] = reach + thick / 2; reach += thick + RANK; });
  const cross = new Map<string, number>();
  layers.forEach((l) => { let x = 0; l.forEach((id) => { cross.set(id, x + side(id) / 2); x += side(id) + GAP; }); });
  for (let pass = 0; pass < 10; pass++) {
    const by = pass % 2 ? down : up;
    for (const r of pass % 2 ? [...layers.keys()].reverse() : [...layers.keys()]) {
      const l = layers[r], want = l.map((id) => mean(by.get(id), cross) ?? cross.get(id)!);
      const xs = [...want];
      for (let i = 1; i < l.length; i++) xs[i] = Math.max(xs[i], xs[i - 1] + (side(l[i - 1]) + side(l[i])) / 2 + GAP);
      const shift = want.reduce((a, w, i) => a + w - xs[i], 0) / l.length;
      l.forEach((id, i) => cross.set(id, xs[i] + shift));
    }
  }

  const at = new Map<string, [number, number]>();
  layers.forEach((l, r) => l.forEach((id) => at.set(id, across ? [level[r], cross.get(id)!] : [cross.get(id)!, level[r]])));
  if (rtl && across) { const far = Math.max(...[...at.values()].map((p) => p[0])); at.forEach((p, id) => at.set(id, [far - p[0], p[1]])); }

  const nodes: Placed[] = f.nodes.map((n) => {
    const { w, h, lines } = size.get(n.id)!, [x, y] = at.get(n.id)!;
    return { id: n.id, x, y, w, h, rank: rank.get(n.id)!, lines, node: n };
  });
  const edge = (from: string, toward: [number, number]): [number, number] => {
    const [x, y] = at.get(from)!, { w, h } = dim(from);
    if (from.startsWith("~")) return [x, y];
    return across ? [x + Math.sign(toward[0] - x) * w / 2, y] : [x, y + Math.sign(toward[1] - y) * h / 2];
  };
  const routes: Route[] = chains.map((c) => {
    const ids = c.back ? [...c.ids].reverse() : c.ids;
    const pts = ids.map((id, j) => (j === 0 ? edge(id, at.get(ids[1])!) : j === ids.length - 1 ? edge(id, at.get(ids[j - 1])!) : at.get(id)!));
    const d = pts.reduce((s, p, j) => {
      if (!j) return `M${p[0]},${p[1]}`;
      const q = pts[j - 1];
      if (across) { const m = (q[0] + p[0]) / 2; return `${s}C${m},${q[1]} ${m},${p[1]} ${p[0]},${p[1]}`; }
      const m = (q[1] + p[1]) / 2;
      return `${s}C${q[0]},${m} ${p[0]},${m} ${p[0]},${p[1]}`;
    }, "");
    const mid = pts.length > 2 ? pts[Math.floor(pts.length / 2)] : [(pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2] as [number, number];
    return { edge: c.edge, d, at: mid, rank: rank.get(c.ids[0])!, i: c.i };
  });
  const xs = nodes.flatMap((n) => [n.x - n.w / 2, n.x + n.w / 2]), ys = nodes.flatMap((n) => [n.y - n.h / 2, n.y + n.h / 2]);
  const pad = 14, x0 = Math.min(...xs) - pad, y0 = Math.min(...ys) - pad;
  return { nodes, routes, x0, y0, w: Math.max(...xs) + pad - x0, h: Math.max(...ys) + pad - y0 };
}

// Every step before and after this one: its path through the chart
function path(id: string, edges: Edge[]) {
  const lit = new Set([id]);
  for (const [from, to] of [["from", "to"], ["to", "from"]] as const) {
    const todo = [id];
    while (todo.length) {
      const v = todo.pop()!;
      for (const e of edges) if (e[from] === v && !lit.has(e[to])) { lit.add(e[to]); todo.push(e[to]); }
    }
  }
  return lit;
}

const BLUE = "#3171F6", AMBER = "#EF8733";

export const FlowChart = memo(function FlowChart({ flow: f }: { flow: Flow }) {
  const id = useId().replace(/\W/g, "");
  const [direction, setDirection] = useState(f.direction);
  const [hover, setHover] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const files = useContext(FileActions);
  const box = useRef<HTMLDivElement>(null);
  const [room, setRoom] = useState(0);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setRoom(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(([e]) => setRoom(Math.round(e.contentRect.width)));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const rtl = useMemo(() => dirOf(f.nodes.map((n) => n.label).join(" ")) === "rtl", [f]);
  const L = useMemo(() => layout({ ...f, direction }, rtl), [f, direction, rtl]);
  const focus = hover ?? pinned;
  const lit = useMemo(() => (focus ? path(focus, f.edges) : null), [focus, f.edges]);
  const scale = Math.max(0.55, Math.min(1, (room || 600) / L.w));
  const name = fileName(f.title, "flowchart");
  const save = files?.save && (() => files.save!(`diagrams/${name}.md`, "```flowchart\n" + JSON.stringify({ ...f, direction }, null, 2) + "\n```\n"));
  const image = async () => {
    const svg = box.current?.querySelector<SVGSVGElement>("svg[role=img]");
    if (svg) download(await picture(svg, { title: f.title, subtitle: f.subtitle }), `${name}.png`);
  };
  const noted = focus ? L.nodes.find((n) => n.id === focus && n.node.note) : undefined;

  return (
    <figure className="not-prose my-4 rounded-2xl border border-border bg-background p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <figcaption className="min-w-0 flex-1">
          {f.title && <p dir="auto" className="text-sm font-semibold text-foreground">{f.title}</p>}
          {f.subtitle && <p dir="auto" className="mt-0.5 text-xs text-muted-foreground">{f.subtitle}</p>}
        </figcaption>
        <div dir="ltr" className="flex shrink-0 items-center gap-0.5 rounded-lg bg-secondary p-0.5">
          {(["down", "right"] as const).map((d) => (
            <button key={d} onClick={() => setDirection(d)} aria-pressed={direction === d} aria-label={t(d === "down" ? "flowDown" : "flowAcross")}
                    title={t(d === "down" ? "flowDown" : "flowAcross")}
                    className={cn("flex size-7 cursor-pointer items-center justify-center rounded-md transition-colors",
                                  direction === d ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              <svg viewBox="0 0 24 24" className={cn("size-3.5", d === "right" && rtl && "-scale-x-100")} fill="none" stroke="currentColor" strokeWidth={2}
                   strokeLinecap="round" strokeLinejoin="round">
                <path d={d === "down" ? "M7 3h10v5H7zM7 16h10v5H7zM12 8v8" : "M3 7h5v10H3zM16 7h5v10h-5zM8 12h8"} />
              </svg>
            </button>
          ))}
        </div>
        <div className="relative shrink-0">
          <button onClick={() => setMenu((v) => !v)} aria-label={t("download")} title={t("download")}
                  className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground">
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 4v11m0 0l-4-4m4 4l4-4M5 20h14" />
            </svg>
          </button>
          {menu && <DropdownMenu onClose={() => setMenu(false)} items={[
            ...(save ? [{ label: t("chartSave"), onClick: save }] : []),
            { label: t("chartImage"), onClick: () => void image() },
          ]} />}
        </div>
      </div>
      <div ref={box} dir="ltr" className="relative mt-4 overflow-x-auto">
        <svg role="img" aria-label={f.title || "flowchart"} width={L.w * scale} height={L.h * scale} viewBox={`${L.x0} ${L.y0} ${L.w} ${L.h}`}
             className="mx-auto block touch-pan-y" onClick={() => setPinned(null)}>
          <defs>
            {[["m", "fill-muted-foreground"], ["on", "fill-[#3171F6]"]].map(([k, fill]) => (
              <marker key={k} id={`${id}${k}`} viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,1L9,5L0,9z" className={fill} />
              </marker>
            ))}
          </defs>
          {L.routes.map((r) => {
            const on = !!lit && lit.has(r.edge.from) && lit.has(r.edge.to);
            return (
              <path key={r.i} d={r.d} fill="none" strokeWidth={on ? 2 : 1.5} pathLength={1} markerEnd={`url(#${id}${on ? "on" : "m"})`}
                    className={cn("chart-draw chart-morph", on ? "stroke-[#3171F6]" : "stroke-muted-foreground/60")}
                    style={{ opacity: lit && !on ? 0.2 : 1, animationDelay: `${r.rank * 70 + 150}ms`, animationFillMode: "backwards" }} />
            );
          })}
          {L.routes.filter((r) => r.edge.label).map((r) => {
            const w = measure(r.edge.label!, 11) + 14, on = !!lit && lit.has(r.edge.from) && lit.has(r.edge.to);
            return (
              <g key={`l${r.i}`} style={{ transform: `translate(${r.at[0]}px, ${r.at[1]}px)`, opacity: lit && !on ? 0.25 : 1 }} className="flow-move">
                <rect x={-w / 2} y={-10} width={w} height={20} rx={10} strokeWidth={1}
                      className={cn("chart-fade", on ? "fill-[#3171F6] stroke-[#3171F6]" : "fill-background stroke-border")} />
                <text textAnchor="middle" dy="0.35em" className={cn("text-[11px] font-medium", on ? "fill-white" : "fill-muted-foreground")}>{r.edge.label}</text>
              </g>
            );
          })}
          {L.nodes.map((p) => {
            const n = p.node, on = !!lit?.has(n.id), here = focus === n.id, { w, h } = p;
            const fill = n.shape === "start" ? "fill-[#3171F6]" : n.shape === "end" ? "fill-foreground" : n.shape === "note" ? "fill-secondary" : "fill-background";
            const ink = n.shape === "start" ? "fill-white" : n.shape === "end" ? "fill-background" : n.shape === "note" ? "fill-muted-foreground" : "fill-foreground";
            const stroke = here ? BLUE : n.shape === "decision" ? AMBER : undefined;
            return (
              <g key={n.id} style={{ transform: `translate(${p.x}px, ${p.y}px)`, opacity: lit && !on ? 0.3 : 1 }} className="flow-move cursor-pointer"
                 onPointerEnter={() => setHover(n.id)} onPointerLeave={() => setHover(null)}
                 onClick={(e) => { e.stopPropagation(); setPinned((v) => (v === n.id ? null : n.id)); }}>
                <g className="chart-pop" style={{ animationDelay: `${p.rank * 70}ms` }}>
                  {n.shape === "decision"
                    ? <polygon points={`0,${-h / 2} ${w / 2},0 0,${h / 2} ${-w / 2},0`} strokeWidth={here ? 2 : 1.5} strokeLinejoin="round"
                               stroke={stroke} fill={AMBER} fillOpacity={0.12} />
                    : <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={n.shape === "start" || n.shape === "end" ? h / 2 : 12} strokeWidth={here ? 2 : 1.25}
                            strokeDasharray={n.shape === "note" ? "4 3" : undefined} stroke={stroke}
                            className={cn(fill, !stroke && (n.shape === "start" || n.shape === "end" ? "stroke-transparent" : "stroke-border"))} />}
                  <text textAnchor="middle" className={cn("text-[13px] font-medium", ink)}>
                    {p.lines.map((l, i) => <tspan key={i} x={0} y={(i - (p.lines.length - 1) / 2) * 18} dy="0.35em">{l}</tspan>)}
                  </text>
                  {n.note && <circle cx={w / 2 - (n.shape === "decision" ? w / 4 : 8)} cy={-h / 2 + (n.shape === "decision" ? h / 4 : 8)} r={3} fill={BLUE} />}
                </g>
              </g>
            );
          })}
        </svg>
        {noted && (
          <div dir="auto" className="pointer-events-none absolute z-10 max-w-64 rounded-xl border border-border/60 bg-background/95 px-3 py-2 text-xs leading-5 text-foreground shadow-xl backdrop-blur"
               style={{ left: Math.max(0, (room - L.w * scale) / 2) + (noted.x - L.x0) * scale, top: (noted.y - L.y0 - noted.h / 2) * scale - 8,
                        transform: "translate(-50%, -100%)" }}>
            {noted.node.note}
          </div>
        )}
      </div>
    </figure>
  );
});

// A ```flowchart block in a reply: drawn once its JSON is whole, a placeholder while it streams, and the JSON itself
// if it never becomes a flowchart.
export function FlowBlock({ code, done }: { code: string; done: boolean }) {
  const flow = useMemo(() => { try { return flowOf(JSON.parse(code)); } catch { return null; } }, [code]);
  if (flow) return <FlowChart flow={flow} />;
  if (!done) return <div className="not-prose my-4 h-72 animate-pulse rounded-2xl border border-border bg-secondary/30" />;
  return <CodePart code={code} language="json" className="bg-background" />;
}

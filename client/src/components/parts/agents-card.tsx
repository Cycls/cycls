import { memo, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { AgentState, Part } from "../../hooks/use-chat";
import { useEscape } from "../../hooks/use-escape";
import { GlowStar } from "../cycls-star";
import { Icon } from "../icon";
import { StepPart, clock, useNow } from "./step-part";
import { TextPart } from "./text-part";
import { localStep, t, tn } from "../../lib/i18n";

const seconds = (a: AgentState, now: number) =>
  a.started ? Math.max(0, Math.round(((a.ended ? Date.parse(a.ended) : now) - Date.parse(a.started)) / 1000)) : 0;

function Status({ a }: { a: AgentState }) {
  if (a.status === "working") return <GlowStar size={15} spin />;
  if (a.status === "done")
    return <span className="flex size-4 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600"><Icon name="check" className="size-3" /></span>;
  return <Icon name="x" className="size-3.5 text-muted-foreground" />;
}

function line(a: AgentState) {
  if (a.status === "failed") return t("agentFailed");
  if (a.status === "stopped") return t("agentStopped");
  if (a.status === "done")   // the report's first line, as plain words
    return (a.report?.split("\n").find((l) => l.trim()) ?? "").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[*_`#>]/g, "");
  const last = a.steps[a.steps.length - 1];
  if (!last) return "";
  const { tool_name, step } = localStep({ type: "step", ...last });
  return [tool_name, step].filter(Boolean).join(" · ");
}

// The agents a turn started, in one card: the working ones first, a row opens that agent's work.
export const AgentsCard = memo(function AgentsCard({ items }: { items: Part[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const agents = items.map((p) => ({ id: p.id || "", a: p.agent ?? { label: p.step || "", brief: "", status: "working" as const, started: "", steps: [] } }));
  const working = agents.some(({ a }) => a.status === "working");
  const now = useNow(working);
  const rows = [...agents].sort((x, y) => Number(x.a.status !== "working") - Number(y.a.status !== "working"));
  const took = Math.max(0, ...agents.map(({ a }) => seconds(a, now)));
  const shown = agents.find((x) => x.id === open)?.a;
  return (
    <div className="my-3 overflow-hidden rounded-xl border border-border">
      <div className="flex items-center gap-2 border-b border-border bg-secondary/40 px-3 py-2 text-sm">
        {working ? <GlowStar size={15} spin /> : <Icon name="check" className="size-4 text-emerald-600" />}
        <span className="font-medium">{tn("agents", agents.length)}</span>
        <span className="ms-auto text-xs tabular-nums text-muted-foreground">{clock(took)}</span>
      </div>
      {rows.map(({ id, a }) => (
        <button key={id} type="button" onClick={() => setOpen(id)}
                className="flex w-full cursor-pointer items-center gap-3 px-3 py-2 text-start transition-colors hover:bg-secondary/50">
          <span className="flex size-5 shrink-0 items-center justify-center"><Status a={a} /></span>
          <span className="w-2/5 shrink-0 truncate text-sm text-foreground"><bdi>{a.label || "…"}</bdi></span>
          <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground"><bdi>{line(a)}</bdi></span>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{clock(seconds(a, now))}</span>
        </button>
      ))}
      {shown && <AgentPanel a={shown} now={now} onClose={() => setOpen(null)} />}
    </div>
  );
});

function AgentPanel({ a, now, onClose }: { a: AgentState; now: number; onClose: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useEscape(onClose);
  useEffect(() => {
    const away = (e: Event) => { if (!ref.current?.contains(e.target as Node)) onClose(); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [onClose]);
  return createPortal(
    <aside ref={ref} dir="ltr" className="fixed inset-y-0 right-0 z-[60] flex w-[28rem] max-w-full flex-col border-s border-border bg-background shadow-xl">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="flex size-5 shrink-0 items-center justify-center"><Status a={a} /></span>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold"><bdi>{a.label}</bdi></span>
        <span className="text-xs tabular-nums text-muted-foreground">{clock(seconds(a, now))}</span>
        <button type="button" onClick={onClose} aria-label={t("close")}
                className="cursor-pointer rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground">
          <Icon name="x" className="size-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <p className="mb-1 text-xs font-medium text-muted-foreground">{t("agentAsked")}</p>
        <p dir="auto" className="mb-5 whitespace-pre-wrap text-sm leading-6">{a.brief}</p>
        <div className="mb-5">
          {a.steps.map((s, i) => {
            const { tool_name, step } = localStep({ type: "step", ...s });
            return <StepPart key={s.id || i} step={step || ""} toolName={tool_name} ok={s.ok}
                             isStreaming={a.status === "working" && i === a.steps.length - 1} />;
          })}
        </div>
        {a.report && (<>
          <p className="mb-1 text-xs font-medium text-muted-foreground">{t("agentReport")}</p>
          <TextPart text={a.report} />
        </>)}
      </div>
    </aside>,
    document.body,
  );
}

import { memo, useContext, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "../../lib/utils";
import { Icon } from "../icon";
import { localStep, t, tn, getLang } from "../../lib/i18n";
import type { Part } from "../../hooks/use-chat";
import { StepDot, StepPart, clock, useNow } from "./step-part";
import { ThinkingPart } from "./thinking-part";
import { ToolCall, ConnectorsContext, isCall } from "./tool-call";
import { connectorLabel, type Connector } from "../connectors-dialog";

// Plain-language summary verbs per tool — the collapsed line is for
// non-technical users, not a call log.
const VERB_KEYS = {
  Bash: "verbBash",
  "Web Search": "verbWebSearch",
  Fetching: "verbFetch",
  Reading: "verbRead",
  Editing: "verbEdit",
  Database: "verbDatabase",
  Canvas: "verbCanvas",
  Skill: "verbSkill",
  Suggest: "verbSuggest",
  Ask: "verbAsk",
} as const;

function summarize(items: Part[], connectors: Connector[]) {
  const verbs: string[] = [];
  for (const p of items) {
    const c = connectors.find((x) => x.name === p.connector);
    const key = VERB_KEYS[p.tool_name as keyof typeof VERB_KEYS];
    const v = c ? connectorLabel(c) : key ? t(key) : p.plain ? localStep(p).tool_name : p.tool_name?.toLowerCase();
    if (v && !verbs.includes(v)) verbs.push(v);
  }
  return verbs.slice(0, 3).join(" · ");
}

// `timed` false: the row sits under a summary that keeps the time already, so it shows no second clock.
const Row = ({ p, live, timed = true }: { p: Part; live?: boolean; timed?: boolean }) => {
  if (p.type === "thinking") return <ThinkingPart thinking={p.thinking || ""} isStreaming={live} />;
  if (isCall(p)) return <ToolCall p={p} live={live} />;
  const { step, tool_name } = localStep(p);
  return <StepPart step={step || ""} toolName={tool_name} isStreaming={live} ok={p.ok} args={p.args} at={timed ? p.at : undefined} plain={p.plain} />;
};

// How long a stretch of work took: from its first part to what came after it (`end`), else to its last part;
// counting up while it runs. Parts are stamped as they stream in, and from the model's own timings on a reload.
function useSpan(items: Part[], end: number | undefined, live: boolean | undefined): string | null {
  const now = useNow(live);
  const stamps = items.map((p) => p.at).filter((t): t is number => typeof t === "number");
  if (!stamps.length) return null;
  const until = live ? now : end ?? Math.max(...stamps);
  const secs = Math.floor((until - Math.min(...stamps)) / 1000);
  return secs >= 1 ? clock(secs) : null;
}

// Consecutive tool steps, and the thinking between them, fold into one summary
// line ("7 steps · searched the web · edited files"), expandable on tap: a long
// turn reads as one line of work, not a ladder of "Thinking" and calls. While
// streaming, the current step or thought stays visible below the summary so
// there's always a live signal.
export const StepGroup = memo(function StepGroup({ items, live, end }: { items: Part[]; live?: boolean; end?: number }) {
  const [open, setOpen] = useState(false);
  const connectors = useContext(ConnectorsContext);
  const span = useSpan(items, end, live);
  if (items.length === 1) {
    return <div className="my-3"><Row p={items[0]} live={live} /></div>;
  }

  const current = items[items.length - 1];
  const steps = items.filter((p) => p.type === "step");
  const gist = summarize(steps, connectors);
  const named = steps.every((p) => !!p.connector);
  return (
    <div className="my-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 py-1 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        <StepDot live={live} />
        {/* on the left in either language; in Arabic its words still read right to left */}
        <span className="text-[13px]" dir={getLang() === "ar" ? "rtl" : undefined}>
          {named ? <span className="font-medium text-foreground">{t("usedConnectors").replace("{names}", gist)}</span> : (
            <><span className="font-medium text-foreground">{tn("steps", steps.length)}</span>{gist && <span> · {gist}</span>}</>
          )}
          {span && <span data-testid="steps-span" className="tabular-nums text-muted-foreground/70"> · {span}</span>}
        </span>
        <Icon name="chevron-down" className={cn("size-3 shrink-0 transition-transform", open ? "rotate-180" : "")} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="overflow-hidden ps-7"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", duration: 0.2, bounce: 0 }}
          >
            {items.map((p, i) => <Row key={i} p={p} live={live && i === items.length - 1} />)}
          </motion.div>
        )}
      </AnimatePresence>

      {live && !open && <div className="ps-7"><Row p={current} live timed={false} /></div>}
    </div>
  );
});

import { memo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { cn } from "../../lib/utils";
import { Icon } from "../icon";
import { t } from "../../lib/i18n";
import type { Part } from "../../hooks/use-chat";
import { StepPart } from "./step-part";

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
} as const;

function summarize(items: Part[]) {
  const verbs: string[] = [];
  for (const p of items) {
    const key = VERB_KEYS[p.tool_name as keyof typeof VERB_KEYS];
    const v = key ? t(key) : p.tool_name?.toLowerCase();
    if (v && !verbs.includes(v)) verbs.push(v);
  }
  return verbs.slice(0, 3).join(" · ");
}

// Consecutive tool steps fold into one summary line ("7 steps — searched the
// web · edited files"), expandable on tap. While streaming, the current step
// stays visible below the summary so there's always a live signal.
export const StepGroup = memo(function StepGroup({ items, live }: { items: Part[]; live?: boolean }) {
  const [open, setOpen] = useState(false);
  if (items.length === 1) {
    return (
      <div className="my-3">
        <StepPart step={items[0].step || ""} toolName={items[0].tool_name} isStreaming={live} />
      </div>
    );
  }

  const current = items[items.length - 1];
  const gist = summarize(items);
  return (
    <div className="my-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 py-1 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        <span
          className={cn(
            "flex size-5 shrink-0 items-center justify-center rounded-full border border-border",
            live ? "border-accent" : "bg-accent/10",
          )}
        >
          {live ? (
            <span className="block size-1.5 rounded-full bg-accent animate-pulse" />
          ) : (
            <svg className="size-3 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
            </svg>
          )}
        </span>
        <span className="text-[13px]">
          <span className="font-medium text-foreground">{items.length} {t("steps")}</span>
          {gist && <span> — {gist}</span>}
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
            {items.map((p, i) => (
              <StepPart key={i} step={p.step || ""} toolName={p.tool_name} isStreaming={live && i === items.length - 1} />
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {live && !open && (
        <div className="ps-7">
          <StepPart step={current.step || ""} toolName={current.tool_name} isStreaming />
        </div>
      )}
    </div>
  );
});

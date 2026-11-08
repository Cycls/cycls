import { memo, useState } from "react";
import { cn } from "../../lib/utils";
import { AnimatePresence, motion } from "framer-motion";
import { Icon } from "../icon";
import { t } from "../../lib/i18n";
import { StepDot } from "./step-part";
import { dirOf } from "../../lib/bidi";

// Thinking reads as one more step of the work: the same Cycls star as a tool's row (its colours sweeping through
// while the model thinks, grey once it has), the same row, and what it thought under it on tap.

export const ThinkingPart = memo(function ThinkingPart({
  thinking,
  isStreaming,
}: {
  thinking: string;
  isStreaming?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div>
      <button
        className="text-muted-foreground hover:text-foreground flex items-center gap-2 py-1 transition-colors cursor-pointer text-sm"
        onClick={() => setIsExpanded(!isExpanded)}
        type="button"
        data-testid="thinking-row"
      >
        <StepDot live={isStreaming} />
        <span className={cn("text-[13px]", isStreaming && "text-shimmer")}>{t("thinking")}</span>
        <Icon name="chevron-down" className={cn("w-3 h-3 transition-transform", isExpanded ? "rotate-180" : "")} />
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            className="mb-2 mt-1 overflow-hidden ps-7"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", duration: 0.2, bounce: 0 }}
          >
            <div dir={dirOf(thinking)} className="text-muted-foreground border-s border-muted-foreground/20 ps-4 text-sm whitespace-pre-wrap">
              {thinking}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

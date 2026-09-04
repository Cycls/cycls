import { memo, useState } from "react";
import { cn } from "../../lib/utils";
import { AnimatePresence, motion } from "framer-motion";
import { Icon } from "../icon";
import { t } from "../../lib/i18n";

export const ThinkingPart = memo(function ThinkingPart({
  thinking,
  isStreaming,
}: {
  thinking: string;
  isStreaming?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="mb-2">
      <button
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 transition-colors cursor-pointer text-sm"
        onClick={() => setIsExpanded(!isExpanded)}
        type="button"
      >
        <span className={cn(isStreaming && "text-shimmer")}>{t("thinking")}</span>
        <Icon name="chevron-down" className={cn("w-3 h-3 transition-transform", isExpanded ? "rotate-180" : "")} />
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            className="mt-2 overflow-hidden"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", duration: 0.2, bounce: 0 }}
          >
            <div className="text-muted-foreground border-l border-muted-foreground/20 pl-4 text-sm whitespace-pre-wrap">
              {thinking}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
});

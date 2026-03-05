import { useState } from "react";
import { cn } from "../../lib/utils";
import { AnimatePresence, motion } from "framer-motion";

export function ThinkingPart({
  thinking,
  isStreaming,
}: {
  thinking: string;
  isStreaming?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(isStreaming ?? true);

  return (
    <div className="mb-2">
      <button
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 transition-colors cursor-pointer text-sm"
        onClick={() => setIsExpanded(!isExpanded)}
        type="button"
      >
        <span>Thinking</span>
        <svg
          className={cn(
            "w-3 h-3 transition-transform",
            isExpanded ? "rotate-180" : "",
          )}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
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
}
